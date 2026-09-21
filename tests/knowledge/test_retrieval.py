# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""混合检索测试：BM25 精确词、RRF 融合、指纹重建标记、证据上限、降级链。

dense 通道用确定性假向量（不依赖本地 embedding 服务）；真服务的集成由
``tests/test_embeddings.py`` 覆盖编码层本身。
"""

from __future__ import annotations

import typing

import pytest

from knowledge.domain import KnowledgeBase
from knowledge.ingest import ingest_content
from knowledge.retrieval import HybridRetriever
from knowledge.store import KnowledgeStore, pack_vector


@pytest.fixture()
def store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.db")


def _setup_kb(store, kb_id: str = "kb1", **kw) -> KnowledgeBase:
    kb = KnowledgeBase(id=kb_id, name=kw.pop("name", "资料库"), owner_user_id="1", **kw)
    store.create_kb(kb)
    return kb


def _ingest_published(
    store, kb: KnowledgeBase, text: str, title: str = "文档", embedder=None
) -> str:
    # ingest 侧的 embedder 是纯批量回调（文本列表 → BLOB 列表）
    batch = embedder.embed_batch if embedder is not None else None
    outcome = ingest_content(
        store, kb, "text", text, title=title, submitted_by="1", embedder=batch
    )
    assert outcome.ok, outcome.error
    store.activate_version(outcome.doc_id, outcome.version_no)
    return outcome.doc_id


def _fake_embedder(vectors: dict[str, list[float]], dim: int = 8):
    """确定性假 embedder：文本命中关键词表 → 固定向量；否则零向量。"""

    class FakeEmbedder:
        def __init__(self) -> None:
            self.profile: dict = {
                "base_url": "http://local",
                "model": "fake",
                "dim": dim,
                "encoder": "raw-v1",
                "index_version": 1,
            }

        @property
        def available(self) -> bool:
            return True

        async def embed_query(self, text: str) -> list[float] | None:
            for key, vec in vectors.items():
                if key in text:
                    return vec
            return [0.0] * dim

        def embed_batch(self, texts: list[str]) -> list[bytes | None]:
            out: list[bytes | None] = []
            for text in texts:
                vec = None
                for key, v in vectors.items():
                    if key in text:
                        vec = v
                        break
                out.append(pack_vector(vec) if vec else None)
            return out

    return FakeEmbedder()


# ── BM25 通道 ─────────────────────────────────────────────


def test_bm25_exact_term_hit(store) -> None:
    kb = _setup_kb(store)
    _ingest_published(
        store, kb, "本库的数据库备份策略是每日全量。\n\n群机器人接入使用 OneBot 协议。"
    )
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("数据库备份", [kb.id]))
    assert result.evidence, "BM25 应命中『数据库备份』所在块"
    assert all("备份" in ev.text or "数据库" in ev.text for ev in result.evidence)


def test_draft_and_unpublished_chunks_never_retrievable(store) -> None:
    """草稿/审核中的内容物理上不可检索（过滤在 SQL 层，不是事后筛选）。"""
    kb = _setup_kb(store)
    outcome = ingest_content(
        store, kb, "text", "机密草稿内容量子密钥", submitted_by="1"
    )
    assert outcome.ok
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("量子密钥", [kb.id]))
    assert result.evidence == []


def test_superseded_version_not_retrievable(store) -> None:
    kb = _setup_kb(store)
    doc_id = _ingest_published(store, kb, "旧版本内容区块链白皮书", title="手册")
    outcome = ingest_content(
        store, kb, "text", "新版本内容云计算架构", title="手册", submitted_by="1"
    )
    store.activate_version(outcome.doc_id, outcome.version_no)
    assert store.get_version(doc_id, 1).state == "superseded"
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("区块链白皮书", [kb.id]))
    assert result.evidence == []
    result = _run(retriever.search("云计算架构", [kb.id]))
    assert result.evidence


# ── dense 通道 / 指纹 ─────────────────────────────────────


def test_dense_semantic_match_without_term_overlap(store) -> None:
    kb = _setup_kb(store)
    vec = [1.0] + [0.0] * 7
    # 两侧同义映射：chunk 里的「虚拟专用」与查询里的「VPN」落同一向量空间点，
    # 词面零重叠，命中只能来自 dense 通道
    embedder = _fake_embedder({"虚拟专用": vec, "VPN": vec})
    _ingest_published(store, kb, "远程办公需要接入虚拟专用网络。", embedder=embedder)
    retriever = HybridRetriever(store, embedder=embedder)
    result = _run(retriever.search("VPN 怎么连", [kb.id]))
    assert result.dense_available
    assert result.evidence and result.evidence[0].matched_by in ("dense", "both")


def test_fingerprint_mismatch_marks_needs_rebuild(store) -> None:
    kb = _setup_kb(store)
    _ingest_published(store, kb, "远程办公需要接入虚拟专用网络。")
    # 库锁定为旧模型
    kb.embed_model, kb.embed_dim, kb.embed_encoder, kb.index_version = (
        "old-model",
        8,
        "raw-v1",
        1,
    )
    store.update_kb(kb)
    embedder = _fake_embedder({"虚拟专用": [1.0] + [0.0] * 7})
    embedder.profile["model"] = "new-model"
    retriever = HybridRetriever(store, embedder=embedder)
    result = _run(retriever.search("虚拟专用网络", [kb.id]))
    assert result.needs_rebuild and result.rebuild_kb_ids == [kb.id]
    assert not result.dense_available  # 该库 dense 停用
    assert result.degraded


# ── 融合 / 去重 / 上限 ────────────────────────────────────


def test_rrf_boosts_dual_channel_hits(store) -> None:
    kb = _setup_kb(store)
    vec = [1.0] + [0.0] * 7
    embedder = _fake_embedder({"数据库": vec})
    _ingest_published(
        store,
        kb,
        "数据库每日备份策略。\n\n群机器人协议规范。\n\n虚拟专用网络接入指南。",
        embedder=embedder,
    )
    retriever = HybridRetriever(store, embedder=embedder)
    result = _run(retriever.search("数据库备份", [kb.id]))
    assert result.evidence
    assert result.evidence[0].matched_by in ("both", "bm25")
    # 命中『数据库』的块（双通道）应排在纯 dense 命中之前
    texts = [ev.text for ev in result.evidence]
    assert any("备份" in t for t in texts[:1])


def test_evidence_cap_limits_items(store, monkeypatch) -> None:
    monkeypatch.setattr("config.settings.KNOWLEDGE_EVIDENCE_MAX_ITEMS", 2)
    kb = _setup_kb(store)
    _ingest_published(
        store, kb, "\n\n".join(f"条款{i}：数据保留期限说明" for i in range(6))
    )
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("数据保留期限", [kb.id]))
    assert len(result.evidence) <= 2


def test_evidence_per_item_char_cap(store, monkeypatch) -> None:
    monkeypatch.setattr("config.settings.KNOWLEDGE_EVIDENCE_MAX_CHARS", 50)
    kb = _setup_kb(store)
    _ingest_published(store, kb, "很长的一段。 " * 60)
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("很长的一段", [kb.id]))
    assert result.evidence
    assert all(len(ev.text) <= 50 for ev in result.evidence)


def test_duplicate_text_dedup(store) -> None:
    kb = _setup_kb(store)
    _ingest_published(
        store,
        kb,
        "重复模板页脚联系管理员。\n\n正文A数据字典。\n\n重复模板页脚联系管理员。",
    )
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("数据字典 页脚", [kb.id]))
    texts = [ev.text for ev in result.evidence]
    assert len(texts) == len(set(texts))


def test_empty_authorization_returns_empty(store) -> None:
    kb = _setup_kb(store)
    _ingest_published(store, kb, "有内容。")
    retriever = HybridRetriever(store, embedder=_no_embedder())
    result = _run(retriever.search("内容", []))
    assert result.evidence == []


# ── rerank 挂点 ───────────────────────────────────────────


def test_reranker_applied_when_enabled(store, monkeypatch) -> None:
    monkeypatch.setattr("config.settings.KNOWLEDGE_RERANK_ENABLED", True)
    kb = _setup_kb(store)
    _ingest_published(store, kb, "条款甲数据字典。\n\n条款乙数据库。")
    retriever = HybridRetriever(store, embedder=_no_embedder())

    async def flip(query, evidence):
        return list(reversed(evidence))

    retriever.reranker = flip
    result = _run(retriever.search("数据库", [kb.id]))
    plain = _run(
        HybridRetriever(store, embedder=_no_embedder()).search("数据库", [kb.id])
    )
    if len(result.evidence) > 1:
        assert [e.chunk_seq for e in result.evidence] == [
            e.chunk_seq for e in reversed(plain.evidence)
        ]


def _no_embedder():
    class NoneEmbedder:
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

        def embed_batch(self, texts):
            return [None] * len(texts)

    return NoneEmbedder()


def _run(coro):
    import asyncio

    return asyncio.run(coro)
