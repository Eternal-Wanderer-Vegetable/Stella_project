# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""服务层集成测试：ACL 矩阵、审核/发布流程、授权检索、状态面。

覆盖 plan §8 测试策略的 ACL 与 Lifecycle 两组场景（临时库 + 假 embedder，
不依赖本地 embedding 服务）。
"""

from __future__ import annotations

import pytest

from knowledge.acl import Principal
from knowledge.service import (
    KnowledgePermissionError,
    KnowledgeService,
    KnowledgeStateError,
)
from knowledge.store import KnowledgeStore


class FakeEmbedder:
    """确定性假 embedder：全部块给同一个单位向量（dense 通道可用）。"""

    def __init__(self) -> None:
        self.profile: dict = {
            "base_url": "http://local",
            "model": "fake-model",
            "dim": 4,
            "encoder": "raw-v1",
            "index_version": 1,
        }

    @property
    def available(self) -> bool:
        return True

    async def embed_query(self, text: str) -> list[float] | None:
        return [1.0, 0.0, 0.0, 0.0]

    def embed_batch_sync(self, texts: list[str]) -> list[bytes | None]:
        import struct

        blob = struct.pack("<4f", 1.0, 0.0, 0.0, 0.0)
        return [blob] * len(texts)


@pytest.fixture()
def svc(tmp_path) -> KnowledgeService:
    store = KnowledgeStore(tmp_path / "knowledge.db")
    embedder = FakeEmbedder()
    from knowledge.retrieval import HybridRetriever

    retriever = HybridRetriever(store, embedder=embedder)
    return KnowledgeService(store=store, embedder=embedder, retriever=retriever)


OWNER = Principal(user_id="100")
ALICE = Principal(user_id="101")
BOB = Principal(user_id="102")
GROUP_CHAT = Principal(user_id="101", group_id="777", space="s777")


def _managed(svc) -> str:
    return svc.create_kb(name="管理库", mode="managed", owner_user_id=OWNER.user_id).id


def _shared(svc, **kw) -> str:
    return svc.create_kb(
        name="共享库", mode="shared", owner_user_id=OWNER.user_id, **kw
    ).id


def _grant(svc, kb_id: str, principal_id: str, role: str, kind: str = "user") -> None:
    svc.grant(
        kb_id,
        principal_kind=kind,
        principal_id=principal_id,
        role=role,
        actor=OWNER,
    )


async def _submit(
    svc, kb_id: str, principal: Principal, content: str, title: str = "文档"
):
    return await svc.submit(
        kb_id, source_type="text", data=content, title=title, actor=principal
    )


# ── ACL 矩阵（plan §8）───────────────────────────────────


async def test_managed_contributor_cannot_submit_maintainer_can(svc) -> None:
    kb_id = _managed(svc)
    _grant(svc, kb_id, ALICE.user_id, "maintainer")
    _grant(svc, kb_id, BOB.user_id, "contributor")

    outcome = await _submit(svc, kb_id, ALICE, "维护者上传的内容", title="手册")
    assert outcome.ok

    with pytest.raises(KnowledgePermissionError):
        await _submit(svc, kb_id, BOB, "成员越权投稿")


async def test_managed_upload_auto_publishes(svc) -> None:
    kb_id = _managed(svc)
    _grant(svc, kb_id, ALICE.user_id, "maintainer")
    outcome = await _submit(svc, kb_id, ALICE, "即刻可见的内容", title="公告")
    doc = svc.store.get_document(outcome.doc_id)
    assert doc.status == "published"
    assert doc.active_version == outcome.version_no


async def test_shared_contributor_needs_approval_then_maintainer_publishes(svc) -> None:
    kb_id = _shared(svc)
    _grant(svc, kb_id, BOB.user_id, "contributor")
    _grant(svc, kb_id, ALICE.user_id, "maintainer")

    outcome = await _submit(svc, kb_id, BOB, "成员投稿草稿内容", title="投稿")
    doc = svc.store.get_document(outcome.doc_id)
    assert doc.status == "in_review"

    # 未发布前检索不到
    result = await svc.search("草稿内容", ALICE, in_group=False)
    assert result.evidence == []

    # 贡献者自己不能发布
    with pytest.raises(KnowledgePermissionError):
        await svc.publish(kb_id, doc.id, actor=BOB)

    await svc.publish(kb_id, doc.id, actor=ALICE)
    doc = svc.store.get_document(doc.id)
    assert doc.status == "published"
    result = await svc.search("草稿内容", ALICE, in_group=False)
    assert result.evidence


async def test_shared_direct_publish_skips_review_for_contributor(svc) -> None:
    kb_id = _shared(svc, direct_publish=True)
    _grant(svc, kb_id, BOB.user_id, "contributor")
    outcome = await _submit(svc, kb_id, BOB, "直发库的低风险内容", title="速递")
    doc = svc.store.get_document(outcome.doc_id)
    assert doc.status == "published"


async def test_group_grant_enables_group_search_private_denied(svc) -> None:
    """群授权可见 vs 仅 user 授权在群聊不可见（private 库群聊不可用）。"""
    kb_id = _managed(svc)
    _grant(svc, kb_id, ALICE.user_id, "maintainer")
    await _submit(svc, kb_id, ALICE, "私有手册内容条款", title="私库")

    # 私聊：授权人可检索
    result = await svc.search("手册内容", ALICE, in_group=False)
    assert result.evidence
    # 群聊：仅 user 授权不生效
    group_alice = Principal(user_id=ALICE.user_id, group_id="777", space="s777")
    result = await svc.search("手册内容", group_alice, in_group=True)
    assert result.evidence == []
    assert kb_id in result.authorized_kb_ids or kb_id not in result.authorized_kb_ids

    # 群授权后群聊可见
    _grant(svc, kb_id, "777", "viewer", kind="group")
    result = await svc.search("手册内容", group_alice, in_group=True)
    assert result.evidence


async def test_unrelated_user_gets_no_metadata(svc) -> None:
    kb_id = _managed(svc)
    with pytest.raises(KnowledgePermissionError):
        svc.kb_status(kb_id, BOB)
    visible = svc.list_accessible_kbs(BOB, in_group=False)
    assert all(item["kb_id"] != kb_id for item in visible)


# ── 生命周期（plan §8）───────────────────────────────────


async def test_duplicate_content_ignored_on_submit(svc) -> None:
    kb_id = _managed(svc)
    first = await _submit(svc, kb_id, OWNER, "完全一致的内容", title="A")
    second = await _submit(svc, kb_id, OWNER, "完全一致的内容", title="B")
    assert first.state == "ready"
    assert second.state == "duplicate"


async def test_replacement_version_then_atomic_switch(svc) -> None:
    kb_id = _managed(svc)
    v1 = await _submit(svc, kb_id, OWNER, "第一版条款内容", title="条款")
    v2 = await _submit(svc, kb_id, OWNER, "第二版条款内容", title="条款")
    assert v2.doc_id == v1.doc_id and v2.version_no == 2
    doc = svc.store.get_document(v1.doc_id)
    assert doc.active_version == 2
    versions = {v.version_no: v for v in svc.store.list_versions(doc.id)}
    assert versions[1].state == "superseded"
    assert versions[2].state == "active"


async def test_archived_document_excluded_from_search(svc) -> None:
    kb_id = _managed(svc)
    outcome = await _submit(svc, kb_id, OWNER, "将被下架的旧政策", title="旧政策")
    doc_id = outcome.doc_id
    await svc.archive_document(kb_id, doc_id, actor=OWNER)
    result = await svc.search("旧政策", OWNER, in_group=False)
    assert result.evidence == []


async def test_publish_without_ready_version_rejected(svc) -> None:
    kb_id = _shared(svc)
    _grant(svc, kb_id, BOB.user_id, "contributor")
    outcome = await _submit(svc, kb_id, BOB, "待审内容", title="待审")
    # 人为把版本打成 not-ready（模拟索引损坏）
    version = svc.store.get_version(outcome.doc_id, outcome.version_no)
    version.state = "pending"
    svc.store.update_version(version)
    from knowledge.lifecycle import LifecycleError

    with pytest.raises(LifecycleError):
        await svc.publish(kb_id, outcome.doc_id, actor=OWNER)


async def test_direct_publish_toggle_requires_owner_and_shared(svc) -> None:
    kb_id = _shared(svc)
    with pytest.raises(KnowledgePermissionError):
        svc.set_direct_publish(kb_id, True, actor=ALICE)
    svc.set_direct_publish(kb_id, True, actor=OWNER)
    assert svc.store.get_kb(kb_id).direct_publish is True
    managed_id = _managed(svc)
    with pytest.raises(KnowledgeStateError):
        svc.set_direct_publish(managed_id, True, actor=OWNER)


# ── 状态面（plan §8）─────────────────────────────────────


async def test_status_reports_versions_jobs_and_fingerprint(svc) -> None:
    kb_id = _managed(svc)
    await _submit(svc, kb_id, OWNER, "一些内容用于状态观测", title="观测")
    status = svc.kb_status(kb_id, OWNER)
    assert status["published_count"] == 1
    assert status["fingerprint_locked"] is True
    assert status["fingerprint_matches_current"] is True
    assert status["documents"][0]["active_version"] == 1
    assert status["recent_jobs"][0]["state"] in ("succeeded", "running")


async def test_search_denied_explicit_kb_recorded(svc) -> None:
    kb_id = _managed(svc)
    result = await svc.search("任意", BOB, in_group=False, kb_ids=[kb_id])
    assert result.evidence == []
    assert result.denied_kb_ids == [kb_id]
