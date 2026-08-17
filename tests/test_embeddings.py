# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""memory.embeddings 语义编码与检索的测试。

覆盖：纯向量工具（归一化/余弦）、EmbeddingService 的 HTTP 调用与缓存、失败降级，
以及 embedding 语义分注入 rank_memories / retrieve_memories 的集成。
"""

import asyncio

import httpx

import memory.policy as policy
from memory.embeddings import EmbeddingService, cosine_similarity, normalize


def _run(coro):
    return asyncio.run(coro)


def test_normalize_and_cosine():
    """归一化与余弦相似度是纯函数：同向=1、正交=0、反向=0（截断到 0）。"""
    a = normalize([1.0, 2.0, 3.0])
    assert abs(sum(v * v for v in a) - 1.0) < 1e-9
    assert abs(cosine_similarity([1, 0], [1, 0]) - 1.0) < 1e-9
    assert abs(cosine_similarity([1, 0], [0, 1])) < 1e-9
    assert abs(cosine_similarity([1, 0], [-1, 0])) < 1e-9


def test_cosine_mismatched_dim_returns_zero():
    """维度不一致的向量余弦为 0，不抛异常。"""
    assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0
    assert cosine_similarity([], []) == 0.0


def test_embedding_service_caches_and_calls(monkeypatch):
    """EmbeddingService.embed：走 /v1/embeddings、缓存命中不再重复请求。"""
    calls = []

    async def fake_post(self, url, json):
        calls.append((url, json))
        return _FakeResp({"data": [{"embedding": [1.0, 0.0]}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    svc = EmbeddingService("http://x", model="m", cache={})
    assert _run(svc.embed("hello")) == [1.0, 0.0]
    assert _run(svc.embed("hello")) == [1.0, 0.0]  # 缓存命中
    assert len(calls) == 1
    assert calls[0][0] == "http://x/v1/embeddings"
    assert calls[0][1]["model"] == "m"


def test_embedding_service_degrades_on_failure(monkeypatch):
    """服务不可用/无 embedding 模型时返回 None（不抛异常，供调用方降级）。"""

    async def boom(self, url, json):
        raise httpx.ConnectError("no service")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    svc = EmbeddingService("http://x", cache={})
    assert _run(svc.embed("any")) is None
    assert _run(svc.similarity("a", "b")) is None


def test_embedding_service_empty_text(monkeypatch):
    """空文本返回 None，不发请求。"""
    calls = []

    async def fake_post(self, url, json):
        calls.append(1)
        return _FakeResp({"data": [{"embedding": [1.0]}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    svc = EmbeddingService("http://x", cache={})
    assert _run(svc.embed("")) is None
    assert calls == []


def test_rank_memories_uses_injected_semantic_scores():
    """rank_memories 优先用注入的 semantic_scores（而非规则版占位），并落进 _score_parts.sem。"""
    mems = [
        {"id": "a", "type": "EVENT", "content": "最近在学做菜", "usage_tags": ["TOPIC_CONTINUE"],
         "visibility": "OPEN", "confidence": 0.8, "importance": 0.5, "last_accessed_at": "2026-08-09 10:00:00"},
        {"id": "b", "type": "EVENT", "content": "最近在学做菜", "usage_tags": ["TOPIC_CONTINUE"],
         "visibility": "OPEN", "confidence": 0.8, "importance": 0.5, "last_accessed_at": "2026-08-09 10:00:00"},
    ]
    # 注入让 b 语义更高 → b 应排在 a 前
    ranked = policy.rank_memories(mems, "CASUAL_REPLY", "一起玩游戏吧", semantic_scores={"a": 0.1, "b": 0.9})
    assert [m["id"] for m in ranked] == ["b", "a"]
    assert abs(ranked[0]["_score_parts"]["sem"] - 0.35 * 0.9) < 0.02
    # 注入缺失的 id 退化规则版（此处两记忆语义相同，排序只受注入影响）
    ranked2 = policy.rank_memories(mems, "CASUAL_REPLY", "一起玩游戏吧", semantic_scores={"b": 0.9})
    assert ranked2[0]["id"] == "b"


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _make_db(tmp_path, rows):
    """建一张带 v2 列的 memories 表并插入若干行（与生产 schema 对齐）。"""
    import sqlite3

    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, group_shared_space TEXT, user_id TEXT, type TEXT, "
        "content TEXT, importance REAL, confidence REAL, status TEXT, usage_tags TEXT, "
        "visibility TEXT, trigger_data TEXT, behavior_rule TEXT, last_accessed_at DATETIME)"
    )
    for mid, content, imp, conf in rows:
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, confidence, "
            "status, usage_tags, visibility, last_accessed_at) VALUES (?,?,?,?,?,?,?,'active',?,?,'2026-08-09 10:00:00')",
            (mid, "1", "100", "EVENT", content, imp, conf, '["TOPIC_CONTINUE"]', "OPEN"),
        )
    conn.commit()
    conn.close()
    return db_path


class _StubService:
    """按文本返回固定向量的假 EmbeddingService：相关记忆给高分、无关给低分。"""

    def __init__(self):
        self._vec = {"游戏": [1.0, 0.0], "电影": [0.0, 1.0]}

    async def similarity(self, query, content):
        for key in self._vec:
            if key in (query or "") and key in (content or ""):
                return 1.0
            if key in (query or "") and key not in (content or ""):
                return 0.0
        return 0.0


def test_retrieve_memories_emb_routes_semantic_scores(tmp_path, monkeypatch):
    """retrieve_memories_emb 用注入的 EmbeddingService 算语义分，并让相关记忆排前。"""
    import memory.retrieval_v2 as retrieval_v2

    db_path = _make_db(
        tmp_path,
        [
            ("rel", "用户喜欢合作游戏", 0.5, 0.8),
            ("irr", "用户最近在追电影", 0.5, 0.8),
        ],
    )
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    retrieval_v2._CACHE.clear()

    result = _run(retrieval_v2.retrieve_memories_emb("1", 100, "有什么游戏推荐吗", service=_StubService()))
    ids = [m["id"] for m in result.conversation_memories]
    # 语义强的 rel 必须进入会话并排前；语义≈0 的 irr 在新权重（conf/imp 只当
    # tie-breaker）下被 MEMORY_SCORE_MIN 挡掉，属「宁缺毋滥」的预期行为。
    assert ids and ids[0] == "rel"


def test_retrieve_memories_emb_falls_back_on_service_failure(tmp_path, monkeypatch):
    """EmbeddingService 失败（返回 None）时，retrieve_memories_emb 回退规则版，不中断。"""
    import memory.retrieval_v2 as retrieval_v2

    db_path = _make_db(tmp_path, [("m1", "用户喜欢合作游戏", 0.5, 0.8)])
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    retrieval_v2._CACHE.clear()

    class _Broken:
        async def similarity(self, q, c):
            return None

    result = _run(retrieval_v2.retrieve_memories_emb("1", 100, "有什么游戏推荐吗", service=_Broken()))
    assert [m["id"] for m in result.conversation_memories] == ["m1"]

