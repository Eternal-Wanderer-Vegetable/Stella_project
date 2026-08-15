# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据库 Schema 迁移（记忆系统 v2）。

采用 Additive Migration（只加字段、不删数据）：
1. 首次迁移前把数据库备份为 ``stella_memory_backup.db``；
2. 为 ``long_term_memories`` / ``memory_candidates`` / ``memories`` 增加 v2 字段
   （memory_type / usage_tags / visibility / trigger_data / behavior_rule / confidence / status）；
3. 新增常用检索索引（group_id / user_id / memory_type / visibility / status）；
4. v3 为 ``group_messages`` / ``memory_candidates`` / ``memories`` 补 ``source_kind``
   列（消息来源分级：AT_MENTION / PASSIVE），并新增按来源归因的审计索引；
5. v4 为 ``memory_candidates`` 补候选强化字段（occurrence_count / first_seen_at /
   source_kinds），支撑「暂存 → 交叉验证 → 逐步强化」的累计证据语义；
6. v5 新增 ``proactive_state`` 表（主动发言的持久化状态：每用户 @ 配额计数、
   上次追问内容、连续无回应次数）。
7. v6 新增 ``group_runtime_state`` 表（主动发言的运行时静音开关与
   睡眠/苏醒播报的每日去重锚点）。

迁移以 ``schema_meta`` 表记录版本号，幂等；所有 ALTER 都经过 ``PRAGMA table_info``
探测，绝不对已存在的列重复添加。任何情况都不删除旧数据。

独立运行：``python -m memory.schema``（可先 ``--dry-run`` 预览）。
"""

from __future__ import annotations

import argparse
import contextlib
import sqlite3
from pathlib import Path

from nonebot import logger

from config import DB_PATH

# 当前 Schema 版本（v6：新增 group_runtime_state 群级运行时状态表）
SCHEMA_VERSION = 6
# 备份文件名（放在数据库同目录）
BACKUP_FILENAME = "stella_memory_backup.db"

# 消息来源分级（source_kind）的合法取值——存储层的单一真相源。
# AT_MENTION：用户直接对 Bot 说（高密度证据，单次可晋升）
# PASSIVE   ：被动摄入的群聊（需复现才可晋升）
# BOT_SELF  ：Bot 自己的发言（**只作上下文，绝不产出候选**）
SOURCE_KINDS = frozenset({"AT_MENTION", "PASSIVE", "BOT_SELF"})
DEFAULT_SOURCE_KIND = "PASSIVE"


def normalize_source_kind(value: str | None) -> str:
    """把任意值规范为合法 source_kind；非法/缺省回退 PASSIVE。"""
    kind = (value or "").strip().upper()
    return kind if kind in SOURCE_KINDS else DEFAULT_SOURCE_KIND


# ── 表结构定义 ──────────────────────────────────────────
# (表名, 列名, ADD COLUMN 语句)
_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    # long_term_memories（旧表）：补上 v2 记忆字段
    (
        "long_term_memories",
        "memory_type",
        "ALTER TABLE long_term_memories ADD COLUMN memory_type TEXT DEFAULT 'FACT'",
    ),
    (
        "long_term_memories",
        "usage_tags",
        "ALTER TABLE long_term_memories ADD COLUMN usage_tags TEXT",
    ),
    (
        "long_term_memories",
        "visibility",
        "ALTER TABLE long_term_memories ADD COLUMN visibility TEXT DEFAULT 'OPEN'",
    ),
    (
        "long_term_memories",
        "trigger_data",
        "ALTER TABLE long_term_memories ADD COLUMN trigger_data TEXT",
    ),
    (
        "long_term_memories",
        "behavior_rule",
        "ALTER TABLE long_term_memories ADD COLUMN behavior_rule TEXT",
    ),
    (
        "long_term_memories",
        "confidence",
        "ALTER TABLE long_term_memories ADD COLUMN confidence REAL DEFAULT 1.0",
    ),
    (
        "long_term_memories",
        "status",
        "ALTER TABLE long_term_memories ADD COLUMN status TEXT DEFAULT 'ACTIVE'",
    ),
    # memory_candidates：补上 v2 记忆字段
    (
        "memory_candidates",
        "usage_tags",
        "ALTER TABLE memory_candidates ADD COLUMN usage_tags TEXT",
    ),
    (
        "memory_candidates",
        "visibility",
        "ALTER TABLE memory_candidates ADD COLUMN visibility TEXT DEFAULT 'OPEN'",
    ),
    (
        "memory_candidates",
        "trigger_data",
        "ALTER TABLE memory_candidates ADD COLUMN trigger_data TEXT",
    ),
    (
        "memory_candidates",
        "behavior_rule",
        "ALTER TABLE memory_candidates ADD COLUMN behavior_rule TEXT",
    ),
    # memories（主表）：补上 v2 记忆字段
    (
        "memories",
        "usage_tags",
        "ALTER TABLE memories ADD COLUMN usage_tags TEXT",
    ),
    (
        "memories",
        "visibility",
        "ALTER TABLE memories ADD COLUMN visibility TEXT DEFAULT 'OPEN'",
    ),
    (
        "memories",
        "trigger_data",
        "ALTER TABLE memories ADD COLUMN trigger_data TEXT",
    ),
    (
        "memories",
        "behavior_rule",
        "ALTER TABLE memories ADD COLUMN behavior_rule TEXT",
    ),
    # v3：消息来源分级（source_kind）——@ 对话 vs 被动摄入
    (
        "group_messages",
        "source_kind",
        "ALTER TABLE group_messages ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'",
    ),
    (
        "memory_candidates",
        "source_kind",
        "ALTER TABLE memory_candidates ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'",
    ),
    (
        "memories",
        "source_kind",
        "ALTER TABLE memories ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'",
    ),
    # v4：候选强化（交叉验证）——同一事实累积证据而非重复插入
    (
        "memory_candidates",
        "occurrence_count",
        "ALTER TABLE memory_candidates ADD COLUMN occurrence_count INTEGER DEFAULT 1",
    ),
    (
        "memory_candidates",
        "first_seen_at",
        "ALTER TABLE memory_candidates ADD COLUMN first_seen_at DATETIME",
    ),
    (
        "memory_candidates",
        "source_kinds",
        "ALTER TABLE memory_candidates ADD COLUMN source_kinds TEXT DEFAULT '[\"PASSIVE\"]'",
    ),
]

# 新增索引：按检索高频字段建索引，避免 SQLite 全表扫描
# 结构：(索引名, 所在表名, DDL)
_INDEXES: list[tuple[str, str, str]] = [
    (
        "idx_memories_group_type_status",
        "memories",
        "CREATE INDEX IF NOT EXISTS idx_memories_group_type_status ON memories (group_id, type, status)",
    ),
    (
        "idx_memories_group_visibility_status",
        "memories",
        "CREATE INDEX IF NOT EXISTS idx_memories_group_visibility_status ON memories (group_id, visibility, status)",
    ),
    (
        "idx_candidates_status",
        "memory_candidates",
        "CREATE INDEX IF NOT EXISTS idx_candidates_status ON memory_candidates (status)",
    ),
    (
        "idx_longterm_group_user_type",
        "long_term_memories",
        "CREATE INDEX IF NOT EXISTS idx_longterm_group_user_type ON long_term_memories (group_id, user_id, memory_type)",
    ),
    (
        "idx_memories_group_source_kind",
        "memories",
        "CREATE INDEX IF NOT EXISTS idx_memories_group_source_kind ON memories (group_id, source_kind, status)",
    ),
    (
        "idx_group_messages_source_kind",
        "group_messages",
        "CREATE INDEX IF NOT EXISTS idx_group_messages_source_kind ON group_messages (group_id, source_kind, id)",
    ),
    (
        "idx_candidates_group_user_type_status",
        "memory_candidates",
        "CREATE INDEX IF NOT EXISTS idx_candidates_group_user_type_status "
        "ON memory_candidates (group_id, user_id, type, status)",
    ),
]


# 记忆主表（memories）的规范 DDL：所有业务模块与该表打交道的建表/取数必须用它定义，
# 避免各处手抄一份导致加字段时漂移（benchmark 临时库也复用它）。
MEMORIES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    group_id TEXT,
    user_id TEXT,
    type TEXT,
    content TEXT,
    content_raw TEXT,
    importance REAL,
    confidence REAL,
    status TEXT,
    confirmation_count INTEGER,
    last_confirmed_at DATETIME,
    last_accessed_at DATETIME,
    compressed_at DATETIME,
    compression_version INTEGER,
    is_atomized INTEGER,
    usage_tags TEXT,
    visibility TEXT DEFAULT 'OPEN',
    trigger_data TEXT,
    behavior_rule TEXT,
    source_kind TEXT DEFAULT 'PASSIVE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_memories_table(conn: sqlite3.Connection) -> None:
    """确保 memories 表存在（幂等）。benchmark 临时库等场景复用规范 DDL。"""
    conn.execute(MEMORIES_TABLE_DDL)


# 主动发言状态的持久化表：每用户 @ 配额计数、上次追问内容、连续无回应次数。
# 独立于 additive column 体系（新表而非加列），升级路径见 _migrate。
PROACTIVE_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS proactive_state (
    group_id TEXT,
    user_id TEXT,
    at_count_today INTEGER DEFAULT 0,
    at_count_date TEXT,
    last_at_at DATETIME,
    last_asked_topic TEXT,
    last_asked_candidate_id TEXT,
    consecutive_no_reply INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, user_id)
)
"""


def create_proactive_state_table(conn: sqlite3.Connection) -> None:
    """确保 proactive_state 表存在（幂等）。

    主动发言状态必须落库：内存态用 time.monotonic()，重启后基准漂移无法持久化，
    而「问过谁什么」丢失会导致重启后重复追问同一个人同一件事。
    """
    conn.execute(PROACTIVE_STATE_TABLE_DDL)


GROUP_RUNTIME_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS group_runtime_state (
    group_id TEXT PRIMARY KEY,
    proactive_muted INTEGER DEFAULT 0,
    muted_by TEXT,
    muted_at DATETIME,
    last_sleep_announce_date TEXT,
    last_wakeup_announce_date TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_group_runtime_state_table(conn: sqlite3.Connection) -> None:
    """确保 group_runtime_state 表存在（幂等）。

    保存两类必须跨重启存活的群级状态：

    - ``proactive_muted``：管理员的运行时静音开关。管理员关掉它通常是因为
      出了问题，重启不该把它悄悄打开；
    - ``last_*_announce_date``：睡眠/苏醒播报的去重锚点。播报由定时任务触发，
      不记录已播报日期的话，睡眠期内重启会重复播报「我去睡了」。
    """
    conn.execute(GROUP_RUNTIME_STATE_TABLE_DDL)


def _table_exists(cursor: sqlite3.Cursor, table: str) -> bool:
    """判断表是否存在。"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    """判断表中是否已存在某列。"""
    if not _table_exists(cursor, table):
        return True  # 表不存在视为“无需加列”，由建表语句负责
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """读取当前 schema 版本；无版本表时返回 0（表示旧库，需要迁移）。"""
    try:
        row = conn.execute(
            "SELECT version FROM schema_meta WHERE k='version'"
        ).fetchone()
        return int(row[0]) if row and row[0] else 0
    except sqlite3.OperationalError:
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """写入 schema 版本号（幂等 upsert）。"""
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


def backup_database(db_path: Path = DB_PATH) -> Path:
    """把数据库备份为同目录下 ``stella_memory_backup.db``。

    用 SQLite 在线备份 API 复制，避免文件被占用时直接复制失败。
    若备份已存在则跳过（保留第一次的原始库，防止误覆盖）。
    """
    backup = db_path.parent / BACKUP_FILENAME
    if backup.exists():
        logger.info(f"📦 [Schema] 备份已存在，跳过: {backup}")
        return backup
    conn = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup)
        try:
            conn.backup(dst)
        finally:
            dst.close()
    finally:
        conn.close()
    logger.info(f"📦 [Schema] 数据库已备份到 {backup}")
    return backup


def _migrate(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """执行增量迁移：加列 + 建索引。返回本次变更的列/索引数量（dry_run 时不落盘）。

    每条变更独立 try/except：单个失败（如旧表结构异常）不拖垮整批迁移，
    剩余项照常执行（幂等，重跑会续上失败的项）。
    """
    cursor = conn.cursor()
    changes = 0
    # v5：主动发言状态表（新表，不属于 additive column 范畴）
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(PROACTIVE_STATE_TABLE_DDL)
    # v6：群级运行时状态表（新表，不属于 additive column 范畴）
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(GROUP_RUNTIME_STATE_TABLE_DDL)
    for table, column, ddl in _ADDITIVE_COLUMNS:
        if _column_exists(cursor, table, column):
            continue
        if dry_run:
            changes += 1
            continue
        try:
            cursor.execute(ddl)
            changes += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [Schema] 加列失败 {table}.{column}: {e}")
    for name, table, ddl in _INDEXES:
        # 表还不存在（业务表由各模块惰性建）→ 跳过索引，避免 CREATE INDEX 报 no such table
        if not _table_exists(cursor, table):
            if dry_run:
                changes += 1
            continue
        if _index_exists(cursor, name):
            continue
        if dry_run:
            changes += 1
            continue
        try:
            cursor.execute(ddl)
            changes += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [Schema] 建索引失败 {name}: {e}")
    return changes


def _index_exists(cursor: sqlite3.Cursor, index: str) -> bool:
    """判断索引是否已存在（用于幂等，避免 IF NOT EXISTS 每次都被计入变更）。"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index,),
    )
    return cursor.fetchone() is not None


def _missing_v2_columns(conn: sqlite3.Connection) -> list[str]:
    """返回现有业务表中仍缺的 v2 列（用于版本号已到位但缺列时修补）。"""
    cursor = conn.cursor()
    return [
        f"{table}.{column}"
        for table, column, _ in _ADDITIVE_COLUMNS
        if _table_exists(cursor, table) and not _column_exists(cursor, table, column)
    ]


def ensure_v2_schema(db_path: Path = DB_PATH) -> bool:
    """幂等地把数据库升级到 v2 Schema；返回是否发生了实际迁移。

    - 数据库不存在 → 直接返回 False（由各业务模块建表即可）；
    - 已经是 v2 → 跳过，返回 False；
    - 首次迁移 → 先备份，再加列/建索引，最后写版本号，返回 True。
    """
    if not db_path.exists():
        return False
    conn = sqlite3.connect(db_path)
    try:
        changes = 0
        # 版本已到位但实际缺列（历史脏库：旧建表语句没带 v2 列）→ 仍然补齐
        if _get_schema_version(conn) >= SCHEMA_VERSION:
            missing = _missing_v2_columns(conn)
            if not missing:
                return False
            logger.warning(f"⚠️ [Schema] 版本已到 v{SCHEMA_VERSION} 但缺列，正在修补: {missing}")
        # 首次迁移才备份，避免每次启动都生成多余备份
        if _get_schema_version(conn) < SCHEMA_VERSION:
            backup_database(db_path)
        changes = _migrate(conn, dry_run=False)
        conn.commit()
        _set_schema_version(conn, SCHEMA_VERSION)
        conn.commit()
        if changes:
            logger.info(f"🔧 [Schema] 记忆系统已补齐到 v{SCHEMA_VERSION}（变更 {changes} 项）")
        return changes > 0
    except Exception as e:
        logger.warning(f"⚠️ [Schema] 迁移失败（回滚重试）: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def dry_run_report(db_path: Path = DB_PATH) -> None:
    """打印迁移预览：列出将要添加的列与索引，不落盘。"""
    if not db_path.exists():
        print(f"[Schema] 数据库不存在: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    try:
        version = _get_schema_version(conn)
        print(f"[Schema] 当前版本: {version}（目标 v{SCHEMA_VERSION}）")
        if version >= SCHEMA_VERSION:
            print("[Schema] 已是最新版本，无需迁移")
            return
        print("\n[Schema] 将执行以下变更（dry-run，未落盘）:")
        for table, column, _ in _ADDITIVE_COLUMNS:
            if not _column_exists(conn.cursor(), table, column):
                print(f"  + {table}.{column}")
        for name, _, _ in _INDEXES:
            print(f"  + 索引 {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stella 记忆系统 Schema 迁移")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际迁移")
    parser.add_argument("--backup", action="store_true", help="仅备份数据库，不迁移")
    args = parser.parse_args()
    if args.backup:
        backup_database()
        print(f"[Schema] 备份完成: {DB_PATH.parent / BACKUP_FILENAME}")
    elif args.dry_run:
        dry_run_report()
    else:
        if ensure_v2_schema():
            print("[Schema] 迁移完成")
        else:
            print("[Schema] 无需迁移或迁移失败（详见日志）")
