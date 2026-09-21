# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""knowledge.search 能力接线测试：backend 解析、工具 ACL、hooks 证据分流。"""

from __future__ import annotations

import json
import typing
from dataclasses import dataclass
from typing import Any

import pytest

from capability.hooks import _knowledge_evidence_of
from capability.providers.knowledge import (
    KNOWLEDGE_SEARCH_CAPABILITY,
    KNOWLEDGE_SEARCH_TOOL,
    KnowledgeBackend,
    KnowledgeSearchTool,
)
from capability.registry import CapabilityProvider
from knowledge.service import KnowledgeService
from knowledge.store import KnowledgeStore


@dataclass
class FakeEvent:
    """最小事件替身：够 _principal_of 与工具契约使用。"""

    user_id: int = 101
    group_id: int = 0

    def get_sender_id(self) -> str:
        return str(self.user_id)

    def get_group_id(self) -> str:
        return str(self.group_id) if self.group_id else ""


@dataclass
class FakeContext:
    context: Any = None


class FakeEmbedder:
    profile: typing.ClassVar[dict] = {
        "model": "",
        "dim": 0,
        "encoder": "raw-v1",
        "index_version": 1,
    }

    @property
    def available(self) -> bool:
        return False

    async def embed_query(self, text):
        return None

    def embed_batch_sync(self, texts):
        return [None] * len(texts)


@pytest.fixture()
def svc(tmp_path) -> KnowledgeService:
    from knowledge.retrieval import HybridRetriever

    store = KnowledgeStore(tmp_path / "knowledge.db")
    embedder = FakeEmbedder()
    return KnowledgeService(
        store=store, embedder=embedder, retriever=HybridRetriever(store, embedder)
    )


@pytest.fixture()
def patch_service(monkeypatch, svc):
    """单例替换：工具的延迟导入拿到测试服务。"""
    import knowledge.service as service_module

    monkeypatch.setattr(service_module, "_service", svc)
    return svc


def _published_kb(svc: KnowledgeService) -> str:
    kb = svc.create_kb(name="群资料库", mode="managed", owner_user_id="100")
    svc.store.set_grant(
        __import__("knowledge.domain", fromlist=["KBGrant"]).KBGrant(
            kb_id=kb.id, principal_kind="group", principal_id="777", role="viewer"
        )
    )
    from knowledge.ingest import ingest_content

    outcome = ingest_content(
        svc.store,
        kb,
        "text",
        "本团队的数据库每日全量备份。",
        title="运维手册",
        submitted_by="100",
    )
    assert outcome.ok, outcome.error
    svc.store.activate_version(outcome.doc_id, outcome.version_no)
    return kb.id


# ── backend 判定 ──────────────────────────────────────────


def test_backend_live_follows_enabled_flag(monkeypatch) -> None:
    monkeypatch.setattr("config.settings.KNOWLEDGE_ENABLED", True)
    backend = KnowledgeBackend()
    provider = CapabilityProvider(
        provider_id="p",
        capability_id=KNOWLEDGE_SEARCH_CAPABILITY,
        kind="native",
        tool_name=KNOWLEDGE_SEARCH_TOOL,
    )
    assert backend.is_live(provider)
    assert backend.resolve(provider) is not None
    assert backend.schema(provider)["required"] == ["query"]

    monkeypatch.setattr("config.settings.KNOWLEDGE_ENABLED", False)
    assert not backend.is_live(provider)
    assert backend.resolve(provider) is None


# ── 工具：ACL 主体来自事件，不是参数 ──────────────────────


async def test_tool_search_uses_event_principal(patch_service) -> None:
    kb_id = _published_kb(patch_service)
    tool = KnowledgeSearchTool()

    # 群聊成员（群授权 viewer）：能检索到
    raw = await tool.call(
        FakeContext(FakeEvent(user_id=901, group_id=777)), query="数据库备份"
    )
    payload = json.loads(raw)
    assert payload["evidence"], "群授权用户应能检索"
    assert payload["evidence"][0]["kb_id"] == kb_id
    assert payload["evidence"][0]["citation"]

    # 未授权用户：同样的调用，零结果、零元数据
    raw = await tool.call(
        FakeContext(FakeEvent(user_id=902, group_id=0)), query="数据库备份"
    )
    payload = json.loads(raw)
    assert payload["evidence"] == []


async def test_tool_cannot_spoof_principal(patch_service) -> None:
    """工具没有 user 参数可传——伪造参数改变不了从事件推导的主体。"""
    _published_kb(patch_service)
    tool = KnowledgeSearchTool()
    raw = await tool.call(
        FakeContext(FakeEvent(user_id=902, group_id=0)),
        query="数据库备份",
        user_id="100",
        group_id="777",
    )
    payload = json.loads(raw)
    assert payload["evidence"] == []


async def test_tool_missing_query(patch_service) -> None:
    tool = KnowledgeSearchTool()
    raw = await tool.call(FakeContext(FakeEvent()))
    payload = json.loads(raw)
    assert payload["evidence"] == [] and "error" in payload


# ── hooks 证据分流 ────────────────────────────────────────


def _result(capability: str, data: Any, summary: str = "摘要"):
    from core.tasks import Result, ResultStatus

    return Result(
        task_id="t1",
        status=ResultStatus.SUCCESS,
        data=data,
        summary=summary,
        metadata={"capability": capability},
    )


def test_hooks_extract_knowledge_evidence() -> None:
    payload = json.dumps(
        {
            "evidence": [
                {"doc_title": "手册", "text": "每日备份", "citation": "《手册》"}
            ]
        },
        ensure_ascii=False,
    )
    result = _result(KNOWLEDGE_SEARCH_CAPABILITY, [("knowledge_search", payload)])
    evidence = _knowledge_evidence_of(result)
    assert evidence and evidence[0]["doc_title"] == "手册"


def test_hooks_extract_returns_none_on_unparseable() -> None:
    result = _result(KNOWLEDGE_SEARCH_CAPABILITY, [("knowledge_search", "not json{")])
    assert _knowledge_evidence_of(result) is None
    plain = _result("weather.query", [("weather", "晴 25 度")])
    assert _knowledge_evidence_of(plain) is None


def test_hooks_extract_empty_evidence_list() -> None:
    payload = json.dumps({"evidence": []}, ensure_ascii=False)
    result = _result(KNOWLEDGE_SEARCH_CAPABILITY, [("knowledge_search", payload)])
    assert _knowledge_evidence_of(result) == []
