# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""知识库存储层（knowledge.db 的唯一读写入口）。

职责边界：

- **纯持久化**：行 ↔ 领域对象的映射、事务边界、原子版本激活。业务判定
  （角色够不够、生命周期能不能走）一律在 acl.py / lifecycle.py / service.py，
  store 不重复实现，也不放行绕过它们的捷径；
- **连接纪律**：每次操作独立连接（``schema.connect``，WAL），导入这类长事务
  用 ``transaction()`` 显式包住——检索读路径永远拿到一致快照，不会被写事务
  的中间态污染（plan §9：SQLite contention）；
- **向量以 BLOB 落库**（float32 小端），``pack_vector`` / ``unpack_vector``
  是唯一的编解码出口，格式变更必须伴随 ``index_version`` 递增。

原子激活（plan §6.3 / §9 partial index activation）：``activate_version``
在**单个事务**里完成「旧 active → superseded、新 ready → active、
doc.active_version 前移、doc.status=published」四件事；激活前提由
``KBDocumentVersion.index_complete`` 在 service 层校验，store 只保证
事务性——半套索引不可能成为对外可见的状态。
"""

from __future__ import annotations

import json
import sqlite3
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import KNOWLEDGE_DB_PATH
from knowledge import schema
from knowledge.domain import (
    DOC_STATE_ACTIVE,
    ChunkLocator,
    KBDocument,
    KBDocumentVersion,
    KBGrant,
    KnowledgeBase,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# 向量 BLOB 编码：float32 小端 + 无头。维度由 kb.embed_dim 锁定，不重复存储。


def pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack_vector(blob: bytes | None) -> list[float]:
    if not blob:
        return []
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


@contextmanager
def transaction(
    db_path: Path | str = KNOWLEDGE_DB_PATH,
) -> Iterator[sqlite3.Connection]:
    """显式事务：with 块内所有写要么全提交、要么全回滚。"""
    conn = schema.connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_kb(row: sqlite3.Row) -> KnowledgeBase:
    return KnowledgeBase(
        id=row["id"],
        name=row["name"],
        mode=row["mode"],
        owner_user_id=row["owner_user_id"],
        direct_publish=bool(row["direct_publish"]),
        status=row["status"],
        description=row["description"],
        embed_model=row["embed_model"],
        embed_dim=row["embed_dim"],
        embed_encoder=row["embed_encoder"],
        index_version=row["index_version"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_doc(row: sqlite3.Row) -> KBDocument:
    return KBDocument(
        id=row["id"],
        kb_id=row["kb_id"],
        title=row["title"],
        source_type=row["source_type"],
        source_uri=row["source_uri"],
        content_hash=row["content_hash"],
        status=row["status"],
        active_version=row["active_version"],
        latest_version=row["latest_version"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_version(row: sqlite3.Row) -> KBDocumentVersion:
    return KBDocumentVersion(
        kb_id=row["kb_id"],
        doc_id=row["doc_id"],
        version_no=row["version_no"],
        state=row["state"],
        chunk_count=row["chunk_count"],
        indexed_chunk_count=row["indexed_chunk_count"],
        content_chars=row["content_chars"],
        importer_version=row["importer_version"],
        parser_meta=json.loads(row["parser_meta"] or "{}"),
        error=row["error"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        activated_at=row["activated_at"],
    )


def _row_to_grant(row: sqlite3.Row) -> KBGrant:
    return KBGrant(
        kb_id=row["kb_id"],
        principal_kind=row["principal_kind"],
        principal_id=row["principal_id"],
        role=row["role"],
        granted_by=row["granted_by"],
        created_at=row["created_at"],
    )


class KnowledgeStore:
    """knowledge.db 仓储。方法一律同步（导入与检索都在 worker 线程跑）。"""

    def __init__(self, db_path: Path | str = KNOWLEDGE_DB_PATH):
        self.db_path = Path(db_path)
        conn = schema.connect(self.db_path)
        try:
            schema.ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()

    # ── 知识库 ───────────────────────────────────────────

    def create_kb(self, kb: KnowledgeBase) -> KnowledgeBase:
        now = _now()
        kb.created_at = kb.created_at or now
        kb.updated_at = now
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kb (id, name, mode, owner_user_id, direct_publish, status,
                                description, embed_model, embed_dim, embed_encoder,
                                index_version, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kb.id,
                    kb.name,
                    kb.mode,
                    kb.owner_user_id,
                    int(kb.direct_publish),
                    kb.status,
                    kb.description,
                    kb.embed_model,
                    kb.embed_dim,
                    kb.embed_encoder,
                    kb.index_version,
                    kb.created_by,
                    kb.created_at,
                    kb.updated_at,
                ),
            )
        return kb

    def get_kb(self, kb_id: str) -> KnowledgeBase | None:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM kb WHERE id=?", (kb_id,)).fetchone()
            return _row_to_kb(row) if row else None
        finally:
            conn.close()

    def list_kbs(self, *, include_archived: bool = False) -> list[KnowledgeBase]:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            sql = "SELECT * FROM kb"
            if not include_archived:
                sql += " WHERE status='active'"
            rows = conn.execute(sql + " ORDER BY name").fetchall()
            return [_row_to_kb(r) for r in rows]
        finally:
            conn.close()

    def update_kb(self, kb: KnowledgeBase) -> None:
        """整行更新（fingerprint 锁定、直发开关、归档都走这里）。"""
        kb.updated_at = _now()
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE kb SET name=?, mode=?, owner_user_id=?, direct_publish=?, status=?,
                              description=?, embed_model=?, embed_dim=?, embed_encoder=?,
                              index_version=?, updated_at=?
                WHERE id=?
                """,
                (
                    kb.name,
                    kb.mode,
                    kb.owner_user_id,
                    int(kb.direct_publish),
                    kb.status,
                    kb.description,
                    kb.embed_model,
                    kb.embed_dim,
                    kb.embed_encoder,
                    kb.index_version,
                    kb.updated_at,
                    kb.id,
                ),
            )

    # ── ACL 授权 ─────────────────────────────────────────

    def set_grant(self, grant: KBGrant) -> None:
        now = _now()
        grant.created_at = grant.created_at or now
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kb_grant (kb_id, principal_kind, principal_id, role, granted_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id, principal_kind, principal_id)
                DO UPDATE SET role=excluded.role, granted_by=excluded.granted_by,
                              created_at=excluded.created_at
                """,
                (
                    grant.kb_id,
                    grant.principal_kind,
                    grant.principal_id,
                    grant.role,
                    grant.granted_by,
                    grant.created_at,
                ),
            )

    def remove_grant(self, kb_id: str, principal_kind: str, principal_id: str) -> bool:
        with transaction(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM kb_grant WHERE kb_id=? AND principal_kind=? AND principal_id=?",
                (kb_id, principal_kind, principal_id),
            )
            return cur.rowcount > 0

    def acl_snapshot(self, kb_id: str):
        """整张授权表快照（acl.ACLSnapshot；评估是纯函数，一次灌入）。"""
        from knowledge.acl import ACLSnapshot

        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM kb_grant WHERE kb_id=?", (kb_id,)
            ).fetchall()
            grants = [_row_to_grant(r) for r in rows]
        finally:
            conn.close()
        return ACLSnapshot(roles={g.key: g.role for g in grants})

    def list_grants(self, kb_id: str) -> list[KBGrant]:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM kb_grant WHERE kb_id=? ORDER BY principal_kind, principal_id",
                (kb_id,),
            ).fetchall()
            return [_row_to_grant(r) for r in rows]
        finally:
            conn.close()

    def kb_ids_for_principal(self, principal_kind: str, principal_id: str) -> list[str]:
        """某主体被授权的全部库（服务层用它圈定可检索候选集）。"""
        conn = schema.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT kb_id FROM kb_grant WHERE principal_kind=? AND principal_id=?",
                (principal_kind, principal_id),
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    # ── 文档与版本 ────────────────────────────────────────

    def upsert_document(self, doc: KBDocument) -> KBDocument:
        now = _now()
        doc.created_at = doc.created_at or now
        doc.updated_at = now
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kb_document (id, kb_id, title, source_type, source_uri,
                                         content_hash, status, active_version,
                                         latest_version, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, status=excluded.status,
                    active_version=excluded.active_version,
                    latest_version=excluded.latest_version,
                    updated_at=excluded.updated_at
                """,
                (
                    doc.id,
                    doc.kb_id,
                    doc.title,
                    doc.source_type,
                    doc.source_uri,
                    doc.content_hash,
                    doc.status,
                    doc.active_version,
                    doc.latest_version,
                    doc.created_by,
                    doc.created_at,
                    doc.updated_at,
                ),
            )
        return doc

    def get_document(self, doc_id: str) -> KBDocument | None:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM kb_document WHERE id=?", (doc_id,)
            ).fetchone()
            return _row_to_doc(row) if row else None
        finally:
            conn.close()

    def find_document_by_hash(self, kb_id: str, content_hash: str) -> KBDocument | None:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM kb_document WHERE kb_id=? AND content_hash=?",
                (kb_id, content_hash),
            ).fetchone()
            return _row_to_doc(row) if row else None
        finally:
            conn.close()

    def list_documents(
        self, kb_id: str, *, status: str | None = None
    ) -> list[KBDocument]:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM kb_document WHERE kb_id=? AND status=? ORDER BY created_at DESC",
                    (kb_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kb_document WHERE kb_id=? ORDER BY created_at DESC",
                    (kb_id,),
                ).fetchall()
            return [_row_to_doc(r) for r in rows]
        finally:
            conn.close()

    def create_version(self, version: KBDocumentVersion) -> KBDocumentVersion:
        now = _now()
        version.created_at = version.created_at or now
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kb_document_version
                    (kb_id, doc_id, version_no, state, chunk_count, indexed_chunk_count,
                     content_chars, importer_version, parser_meta, error, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.kb_id,
                    version.doc_id,
                    version.version_no,
                    version.state,
                    version.chunk_count,
                    version.indexed_chunk_count,
                    version.content_chars,
                    version.importer_version,
                    json.dumps(version.parser_meta, ensure_ascii=False),
                    version.error,
                    version.created_by,
                    version.created_at,
                ),
            )
            # latest_version 指针随版本创建前移（发布走 activate_version，两者分离）
            conn.execute(
                "UPDATE kb_document SET latest_version=?, updated_at=? WHERE id=?",
                (version.version_no, now, version.doc_id),
            )
        return version

    def update_version(self, version: KBDocumentVersion) -> None:
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE kb_document_version
                SET state=?, chunk_count=?, indexed_chunk_count=?, content_chars=?,
                    parser_meta=?, error=?
                WHERE doc_id=? AND version_no=?
                """,
                (
                    version.state,
                    version.chunk_count,
                    version.indexed_chunk_count,
                    version.content_chars,
                    json.dumps(version.parser_meta, ensure_ascii=False),
                    version.error,
                    version.doc_id,
                    version.version_no,
                ),
            )

    def get_version(self, doc_id: str, version_no: int) -> KBDocumentVersion | None:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM kb_document_version WHERE doc_id=? AND version_no=?",
                (doc_id, version_no),
            ).fetchone()
            return _row_to_version(row) if row else None
        finally:
            conn.close()

    def list_versions(self, doc_id: str) -> list[KBDocumentVersion]:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM kb_document_version WHERE doc_id=? ORDER BY version_no DESC",
                (doc_id,),
            ).fetchall()
            return [_row_to_version(r) for r in rows]
        finally:
            conn.close()

    # ── chunk（含 FTS 同步）───────────────────────────────

    def replace_version_chunks(
        self,
        conn: sqlite3.Connection,
        kb_id: str,
        doc_id: str,
        version_no: int,
        chunks: list[tuple[int, str, ChunkLocator, bytes | None]],
    ) -> None:
        """整版本重写 chunk（必须在 ``transaction()`` 内调用）。

        ``chunks`` 元素：``(seq, text, locator, vector_blob)``。先清后插，
        FTS 行同步重建——旧版本的残留索引一个字节都不留。
        """
        conn.execute(
            "DELETE FROM kb_chunk WHERE doc_id=? AND version_no=?",
            (doc_id, version_no),
        )
        conn.execute(
            "DELETE FROM kb_chunk_fts WHERE doc_id=? AND version_no=?",
            (doc_id, version_no),
        )
        for seq, text, loc, blob in chunks:
            cur = conn.execute(
                """
                INSERT INTO kb_chunk
                    (kb_id, doc_id, version_no, seq, text,
                     section_path, page, paragraph, char_start, char_end, vector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kb_id,
                    doc_id,
                    version_no,
                    seq,
                    text,
                    loc.section_path,
                    loc.page,
                    loc.paragraph,
                    loc.char_start,
                    loc.char_end,
                    blob,
                ),
            )
            conn.execute(
                """
                INSERT INTO kb_chunk_fts (rowid, text, kb_id, doc_id, version_no)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cur.lastrowid, text, kb_id, doc_id, version_no),
            )

    def get_chunk_row(
        self, chunk_id: int
    ) -> tuple[int, str, int, str, ChunkLocator, bytes | None] | None:
        """按 rowid 取块（检索回表/补水）。返回 ``(doc_id, kb_id, version_no, seq…)``。"""
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM kb_chunk WHERE id=?", (chunk_id,)
            ).fetchone()
            if row is None:
                return None
            loc = ChunkLocator(
                section_path=row["section_path"],
                page=row["page"],
                paragraph=row["paragraph"],
                char_start=row["char_start"],
                char_end=row["char_end"],
            )
            return (
                row["kb_id"],
                row["doc_id"],
                row["version_no"],
                row["seq"],
                row["text"],
                loc,
                row["vector"],
            )
        finally:
            conn.close()

    # ── 原子版本激活 ──────────────────────────────────────

    def activate_version(self, doc_id: str, version_no: int) -> None:
        """把一个 ready 版本置为文档的 active 版本（单事务，plan §6.3）。

        四步同事务：旧 active 版本 → superseded；新版本 → active（记时间）；
        doc.active_version 前移；doc.status → published。任何一步失败整体回滚，
        不存在「索引换了一半」的中间态。
        """
        now = _now()
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE kb_document_version SET state='superseded'
                WHERE doc_id=? AND state='active' AND version_no<>?
                """,
                (doc_id, version_no),
            )
            cur = conn.execute(
                """
                UPDATE kb_document_version
                SET state='active', activated_at=?
                WHERE doc_id=? AND version_no=? AND state='ready'
                """,
                (now, doc_id, version_no),
            )
            if cur.rowcount == 0:
                raise ValueError(
                    f"版本 {doc_id} v{version_no} 不是 ready 状态，拒绝激活"
                )
            conn.execute(
                """
                UPDATE kb_document
                SET active_version=?, status=?, updated_at=?
                WHERE id=?
                """,
                (version_no, DOC_STATE_ACTIVE, now, doc_id),
            )

    # ── 导入作业（观测面）─────────────────────────────────

    def create_job(
        self,
        job_id: str,
        kb_id: str,
        source_type: str,
        source_uri: str,
        created_by: str,
    ) -> None:
        now = _now()
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO kb_import_job (id, kb_id, state, source_type, source_uri,
                                           created_by, created_at, updated_at)
                VALUES (?, ?, 'running', ?, ?, ?, ?, ?)
                """,
                (job_id, kb_id, source_type, source_uri, created_by, now, now),
            )

    def finish_job(
        self, job_id: str, *, doc_id: str = "", version_no: int = 0, error: str = ""
    ) -> None:
        now = _now()
        with transaction(self.db_path) as conn:
            conn.execute(
                """
                UPDATE kb_import_job
                SET state=?, doc_id=?, version_no=?, error=?, updated_at=?
                WHERE id=?
                """,
                (
                    "succeeded" if not error else "failed",
                    doc_id,
                    version_no,
                    error,
                    now,
                    job_id,
                ),
            )

    def recent_jobs(self, kb_id: str, limit: int = 20) -> list[dict]:
        conn = schema.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM kb_import_job WHERE kb_id=?
                ORDER BY created_at DESC LIMIT ?
                """,
                (kb_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


__all__ = [
    "KnowledgeStore",
    "pack_vector",
    "transaction",
    "unpack_vector",
]
