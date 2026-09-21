# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""knowledge.store / schema 的存储层测试（临时库，不触碰真实数据目录）。"""

from __future__ import annotations

import pytest

from knowledge.domain import (
    DOC_STATE_DRAFT,
    VERSION_STATE_FAILED,
    VERSION_STATE_PENDING,
    VERSION_STATE_READY,
    ChunkLocator,
    KBDocument,
    KBDocumentVersion,
    KBGrant,
    KnowledgeBase,
)
from knowledge.schema import SCHEMA_VERSION, _get_version
from knowledge.store import KnowledgeStore, pack_vector, unpack_vector


@pytest.fixture()
def store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.db")


def _kb(kb_id: str = "kb1", **kw) -> KnowledgeBase:
    base: dict = {"id": kb_id, "name": "测试库", "owner_user_id": "100"}
    base.update(kw)
    return KnowledgeBase(**base)


def _doc(doc_id: str = "d1", kb_id: str = "kb1", **kw) -> KBDocument:
    base: dict = {"id": doc_id, "kb_id": kb_id, "title": "文档"}
    base.update(kw)
    return KBDocument(**base)


def _version(doc_id: str = "d1", version_no: int = 1, **kw) -> KBDocumentVersion:
    base: dict = {"kb_id": "kb1", "doc_id": doc_id, "version_no": version_no}
    base.update(kw)
    return KBDocumentVersion(**base)


def test_store_creates_isolated_db_at_custom_path(store, tmp_path) -> None:
    assert (tmp_path / "knowledge.db").exists()
    from knowledge.schema import connect

    conn = connect(store.db_path)
    try:
        assert _get_version(conn) == SCHEMA_VERSION
    finally:
        conn.close()


def test_kb_crud_roundtrip(store) -> None:
    kb = _kb(embed_model="m", embed_dim=4, embed_encoder="v1", index_version=1)
    store.create_kb(kb)
    loaded = store.get_kb("kb1")
    assert loaded is not None and loaded.name == "测试库"
    assert loaded.fingerprint_locked()
    loaded.direct_publish = True
    store.update_kb(loaded)
    assert store.get_kb("kb1").direct_publish is True
    assert [k.id for k in store.list_kbs()] == ["kb1"]


def test_grant_upsert_and_snapshot(store) -> None:
    store.create_kb(_kb())
    store.set_grant(
        KBGrant(kb_id="kb1", principal_kind="user", principal_id="1", role="viewer")
    )
    store.set_grant(
        KBGrant(kb_id="kb1", principal_kind="user", principal_id="1", role="maintainer")
    )
    snap = store.acl_snapshot("kb1")
    assert snap.role_of("user", "1") == "maintainer"
    assert store.kb_ids_for_principal("user", "1") == ["kb1"]
    assert store.remove_grant("kb1", "user", "1")
    assert store.acl_snapshot("kb1").role_of("user", "1") is None


def test_duplicate_hash_lookup(store) -> None:
    store.create_kb(_kb())
    doc = _doc(content_hash="abc")
    store.upsert_document(doc)
    hit = store.find_document_by_hash("kb1", "abc")
    assert hit is not None and hit.id == "d1"
    assert store.find_document_by_hash("kb1", "nope") is None


def test_create_version_bumps_latest_pointer(store) -> None:
    store.create_kb(_kb())
    store.upsert_document(_doc())
    store.create_version(_version(version_no=1))
    store.create_version(_version(version_no=2, state=VERSION_STATE_PENDING))
    doc = store.get_document("d1")
    assert doc.latest_version == 2
    assert doc.active_version == 0  # 未发布
    assert [v.version_no for v in store.list_versions("d1")] == [2, 1]


def test_atomic_version_activation(store) -> None:
    """激活是单事务：ready → active、旧 active → superseded、doc 指针与状态前移。"""
    from knowledge.store import transaction as ktransaction

    store.create_kb(_kb())
    store.upsert_document(_doc(status=DOC_STATE_DRAFT))
    store.create_version(_version(version_no=1, chunk_count=2, indexed_chunk_count=2))
    with ktransaction(store.db_path) as conn:
        store.replace_version_chunks(
            conn,
            "kb1",
            "d1",
            1,
            [
                (0, ".alpha.", ChunkLocator(paragraph=1), pack_vector([0.1, 0.2])),
                (1, "beta", ChunkLocator(section_path="一>二"), None),
            ],
        )
    store.update_version(
        _version(
            version_no=1,
            state=VERSION_STATE_READY,
            chunk_count=2,
            indexed_chunk_count=2,
        )
    )
    store.activate_version("d1", 1)
    doc = store.get_document("d1")
    assert doc.active_version == 1 and doc.status == "published"
    v1 = store.get_version("d1", 1)
    assert v1.state == "active" and v1.activated_at

    # v2 激活后 v1 必须 superseded（同一事务内完成）
    store.create_version(_version(version_no=2, chunk_count=3, indexed_chunk_count=3))
    store.update_version(
        _version(
            version_no=2,
            state=VERSION_STATE_READY,
            chunk_count=3,
            indexed_chunk_count=3,
        )
    )
    store.activate_version("d1", 2)
    assert store.get_version("d1", 1).state == "superseded"
    assert store.get_version("d1", 2).state == "active"
    assert store.get_document("d1").active_version == 2


def test_activate_rejects_non_ready_version(store) -> None:
    store.create_kb(_kb())
    store.upsert_document(_doc())
    store.create_version(
        _version(version_no=1, state=VERSION_STATE_FAILED, error="解析失败")
    )
    with pytest.raises(ValueError, match="ready"):
        store.activate_version("d1", 1)
    assert store.get_document("d1").status == DOC_STATE_DRAFT


def test_replace_version_chunks_syncs_fts(store) -> None:
    from knowledge.store import transaction as ktransaction

    store.create_kb(_kb())
    store.upsert_document(_doc())
    store.create_version(_version(version_no=1, chunk_count=2))
    with ktransaction(store.db_path) as conn:
        store.replace_version_chunks(
            conn,
            "kb1",
            "d1",
            1,
            [
                (0, "群机器人协议规范", ChunkLocator(paragraph=1), None),
                (1, "数据库备份策略", ChunkLocator(paragraph=2), None),
            ],
        )
    rows = conn_rows(store, "SELECT count(*) c FROM kb_chunk_fts WHERE doc_id='d1'")
    assert rows[0]["c"] == 2
    # 整版本重写：先清后插，不留残行
    with ktransaction(store.db_path) as conn:
        store.replace_version_chunks(
            conn,
            "kb1",
            "d1",
            1,
            [(0, "全新内容", ChunkLocator(), None)],
        )
    rows = conn_rows(store, "SELECT count(*) c FROM kb_chunk WHERE doc_id='d1'")
    assert rows[0]["c"] == 1
    rows = conn_rows(store, "SELECT count(*) c FROM kb_chunk_fts WHERE doc_id='d1'")
    assert rows[0]["c"] == 1


def test_vector_roundtrip() -> None:
    blob = pack_vector([0.25, -0.5, 1.0])
    assert unpack_vector(blob) == pytest.approx([0.25, -0.5, 1.0])
    assert unpack_vector(None) == []


def test_job_lifecycle(store) -> None:
    store.create_kb(_kb())
    store.create_job("j1", "kb1", "markdown", "", "100")
    store.finish_job("j1", doc_id="d1", version_no=1)
    jobs = store.recent_jobs("kb1")
    assert jobs[0]["state"] == "succeeded" and jobs[0]["doc_id"] == "d1"
    store.create_job("j2", "kb1", "pdf", "http://x/y.pdf", "100")
    store.finish_job("j2", error="解析失败：扫描版 PDF 不受支持")
    jobs = store.recent_jobs("kb1")
    assert jobs[0]["state"] == "failed" and "扫描版" in jobs[0]["error"]


def conn_rows(store: KnowledgeStore, sql: str) -> list[dict]:
    import sqlite3

    from knowledge.schema import connect as kconnect

    conn = kconnect(store.db_path)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()
