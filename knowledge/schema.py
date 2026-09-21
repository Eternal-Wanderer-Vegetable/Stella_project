# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""知识库独立 Schema（knowledge.db）。

**存储隔离是本子系统的第一设计约束**（plan §6.2）：知识库使用独立的
``KNOWLEDGE_DB_PATH``（默认 ``<STELLA_HOME>/knowledge/knowledge.db``），
与记忆库 ``agent_memory.db`` 没有任何表、索引或迁移历史上的交集——记忆的
清理任务、候选晋升、空间合并、保留策略都不许触碰外部文档，反之知识库的
重建与归档也不影响记忆。

版本管理沿用记忆系统的约定（``schema_meta`` 记版本号、幂等建表、
``PRAGMA`` 探测），但独立计数、独立迁移：knowledge.db 从 v1 开始。
表清单：

- ``kb``                知识库（模式/库主/直发开关/embedding 指纹）
- ``kb_grant``          ACL 授权（主体三态 × 角色三档；owner 不入库）
- ``kb_document``       文档身份（哈希/来源/生命周期状态/active 版本指针）
- ``kb_document_version`` 不可变版本（索引状态机/块计数/解析元数据）
- ``kb_chunk``          版本的块（定位符 + 向量 BLOB；版本内 seq 唯一）
- ``kb_chunk_fts``      FTS5 全文索引（rowid 对齐 kb_chunk.id）
- ``kb_import_job``     导入作业（观测：状态/失败原因/耗时）

独立运行：``python -m knowledge.schema``（可 ``--dry-run`` 预览）。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from nonebot import logger

from config import KNOWLEDGE_DB_PATH

# 当前 Schema 版本。+1 时必须新增幂等迁移步骤并补旧库回归测试
# （与 memory/schema.py 的新规矩同源：禁止「本版不做迁移」）。
SCHEMA_VERSION = 1

# 知识库状态/模式/角色的合法值与 knowledge.domain 保持字面一致——schema 层
# 不 import domain（存储层是领域层的下游），用本地常量镜像并注明出处。
# 单一真相源仍是 knowledge.domain；这里漂移时测试会抓住。

KB_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kb (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'managed',
    owner_user_id TEXT NOT NULL DEFAULT '',
    direct_publish INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    description TEXT NOT NULL DEFAULT '',
    embed_model TEXT NOT NULL DEFAULT '',
    embed_dim INTEGER NOT NULL DEFAULT 0,
    embed_encoder TEXT NOT NULL DEFAULT '',
    index_version INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
)
"""

KB_GRANT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kb_grant (
    kb_id TEXT NOT NULL,
    principal_kind TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    granted_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kb_id, principal_kind, principal_id)
)
"""

KB_DOCUMENT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kb_document (
    id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'markdown',
    source_uri TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    active_version INTEGER NOT NULL DEFAULT 0,
    latest_version INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
)
"""

KB_DOCUMENT_VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kb_document_version (
    kb_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    indexed_chunk_count INTEGER NOT NULL DEFAULT 0,
    content_chars INTEGER NOT NULL DEFAULT 0,
    importer_version INTEGER NOT NULL DEFAULT 1,
    parser_meta TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    activated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (doc_id, version_no)
)
"""

KB_CHUNK_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kb_chunk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kb_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    text TEXT NOT NULL,
    section_path TEXT NOT NULL DEFAULT '',
    page INTEGER NOT NULL DEFAULT 0,
    paragraph INTEGER NOT NULL DEFAULT 0,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    vector BLOB,
    UNIQUE (doc_id, version_no, seq)
)
"""

# FTS5 全文索引（BM25 路）。rowid 显式对齐 kb_chunk.id，检索命中后按 id 回表。
# kb_id/doc_id/version_no 做 UNINDEXED 列：过滤在 SQL 层完成，不进分词器。
KB_CHUNK_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunk_fts USING fts5(
    text,
    kb_id UNINDEXED,
    doc_id UNINDEXED,
    version_no UNINDEXED,
    tokenize='unicode61'
)
"""

KB_IMPORT_JOB_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS kb_import_job (
    id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL,
    doc_id TEXT NOT NULL DEFAULT '',
    version_no INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'queued',
    source_type TEXT NOT NULL DEFAULT '',
    source_uri TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
)
"""

_ALL_TABLE_DDLS = (
    KB_TABLE_DDL,
    KB_GRANT_TABLE_DDL,
    KB_DOCUMENT_TABLE_DDL,
    KB_DOCUMENT_VERSION_TABLE_DDL,
    KB_CHUNK_TABLE_DDL,
    KB_IMPORT_JOB_TABLE_DDL,
)

_INDEXES = (
    (
        "idx_kb_chunk_version",
        "CREATE INDEX IF NOT EXISTS idx_kb_chunk_version ON kb_chunk (doc_id, version_no, seq)",
    ),
    (
        "idx_kb_chunk_kb",
        "CREATE INDEX IF NOT EXISTS idx_kb_chunk_kb ON kb_chunk (kb_id, doc_id, version_no)",
    ),
    (
        "idx_kb_document_kb_status",
        "CREATE INDEX IF NOT EXISTS idx_kb_document_kb_status ON kb_document (kb_id, status)",
    ),
    (
        "idx_kb_document_hash",
        "CREATE INDEX IF NOT EXISTS idx_kb_document_hash ON kb_document (kb_id, content_hash)",
    ),
    (
        "idx_kb_grant_principal",
        "CREATE INDEX IF NOT EXISTS idx_kb_grant_principal ON kb_grant (principal_kind, principal_id)",
    ),
    (
        "idx_kb_import_job_kb",
        "CREATE INDEX IF NOT EXISTS idx_kb_import_job_kb ON kb_import_job (kb_id, created_at)",
    ),
)


def connect(db_path: Path | str = KNOWLEDGE_DB_PATH) -> sqlite3.Connection:
    """打开 knowledge.db 连接（调用方负责 close）。

    WAL：检索读与导入写在同一进程内并发（plan §9：SQLite contention——
    导入事务与回复路径的读隔离）。``timeout`` 给足写锁等待，导入事务
    偶发撞上读高峰时不至于立刻失败。
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _fts_ok(conn: sqlite3.Connection) -> bool:
    """FTS5 可用性探测（SQLite 未编译 FTS5 时 BM25 路整体降级，见 retrieval）。"""
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _kb_fts_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _kb_fts_probe")
        return True
    except sqlite3.OperationalError:
        return False


def ensure_schema(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    """幂等建表/建索引，返回本次变更项数（dry_run 只统计不执行）。

    FTS5 不可用时跳过虚拟表（返回的计数不含它），检索层据此降级为
    纯语义路——知识库可用性不因编译选项打折。
    """
    cursor = conn.cursor()
    changes = 0
    for ddl in _ALL_TABLE_DDLS:
        if dry_run:
            changes += 1
            continue
        try:
            cursor.execute(ddl)
            changes += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [KnowledgeSchema] 建表失败: {e}")
    if not dry_run and _fts_ok(conn):
        try:
            cursor.execute(KB_CHUNK_FTS_DDL)
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [KnowledgeSchema] FTS5 表创建失败（BM25 路降级）: {e}")
    for name, ddl in _INDEXES:
        if dry_run:
            changes += 1
            continue
        try:
            cursor.execute(ddl)
            changes += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [KnowledgeSchema] 建索引失败 {name}: {e}")
    if not dry_run:
        _set_version(conn, SCHEMA_VERSION)
    return changes


def _get_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT version FROM schema_meta WHERE k='version'"
        ).fetchone()
        return int(row[0]) if row and row[0] else 0
    except sqlite3.OperationalError:
        return 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            k TEXT PRIMARY KEY,
            version INTEGER,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO schema_meta (k, version, updated_at)
        VALUES ('version', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(k) DO UPDATE SET version = excluded.version, updated_at = CURRENT_TIMESTAMP
        """,
        (version,),
    )


def migrate_to_latest(db_path: Path | str = KNOWLEDGE_DB_PATH) -> int:
    """把 knowledge.db 升到当前版本；返回变更项数。启动期与 deploy 共用。"""
    conn = connect(db_path)
    try:
        current = _get_version(conn)
        if current >= SCHEMA_VERSION:
            return 0
        changes = ensure_schema(conn)
        conn.commit()
        logger.info(
            f"🔧 [KnowledgeSchema] 知识库存储已就绪 v{current} → v{SCHEMA_VERSION}"
            f"（变更 {changes} 项）"
        )
        return changes
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stella 知识库 Schema 迁移")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不落盘")
    args = parser.parse_args()
    if args.dry_run:
        conn = connect(KNOWLEDGE_DB_PATH)
        try:
            print(
                f"[KnowledgeSchema] 当前版本: {_get_version(conn)}（目标 v{SCHEMA_VERSION}）"
            )
            print(f"[KnowledgeSchema] 预计变更: {ensure_schema(conn, dry_run=True)} 项")
            print(f"[KnowledgeSchema] FTS5 可用: {_fts_ok(conn)}")
        finally:
            conn.close()
    else:
        migrate_to_latest()
        print("[KnowledgeSchema] 完成")
