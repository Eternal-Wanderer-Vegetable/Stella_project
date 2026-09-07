# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""语义检索缓存 key（设计阶段四）的回归护栏。

旧 key 不含话题：(空间, 用户, trigger, 模式) 相同即复用——5 分钟内换话题
会拿到上一个话题的检索结果。新 key = 空间 + 用户 + 话题哈希 + 模式 + 记忆
历史版本，这里钉住四个性质：
1. 话题变化 → 新桶（不复用旧结果）；
2. 同一文本的书写差异（标点/表情）→ 命中旧桶（保命中率）；
3. 主动发言（空间级）与 @ 回复（用户级）→ 分桶；
4. 记忆库写入后版本递增 → 旧桶不可达（整合出的新记忆立刻可见）。
"""

import sqlite3
from pathlib import Path

import memory.retrieval_v2 as retrieval_v2
from memory.cache_keys import bump_memory_history


def _create_v2_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            usage_tags TEXT,
            visibility TEXT,
            trigger_data TEXT,
            behavior_rule TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _setup(monkeypatch, tmp_path) -> Path:
    db_path = tmp_path / "agent_memory.db"
    _create_v2_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, "
        "confidence, status, usage_tags, visibility, last_accessed_at) "
        "VALUES ('m1', '1', '100', 'PREFERENCE', '用户喜欢轻松闲聊', 0.8, 0.9, 'active', "
        "'[\"TOPIC_CONTINUE\"]', 'OPEN', '2026-08-09 10:00:00')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    retrieval_v2._CACHE.clear()
    return db_path


def test_topic_change_creates_new_cache_bucket(tmp_path, monkeypatch):
    """验收项：话题变化后不会错误复用旧检索结果。"""
    _setup(monkeypatch, tmp_path)
    retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧", trigger="reply")
    assert len(retrieval_v2._CACHE) == 1
    retrieval_v2.retrieve_memories("1", 100, "我明天要出差怎么办", trigger="reply")
    # 换话题必须换桶：旧实现这里仍只有 1 个条目（第二个查询复用了第一个的结果）
    assert len(retrieval_v2._CACHE) == 2


def test_same_text_writing_variant_hits_cache(tmp_path, monkeypatch):
    """同一句话的标点/表情差异不换桶（缓存命中率不明显劣化）。"""
    _setup(monkeypatch, tmp_path)
    r1 = retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧", trigger="reply")
    r2 = retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧！！😄", trigger="reply")
    assert len(retrieval_v2._CACHE) == 1
    # 命中的是同一份结果对象（未重算）
    assert r1 is r2


def test_proactive_and_reply_are_separate_buckets(tmp_path, monkeypatch):
    """主动发言=空间级检索、@ 回复=用户级检索，user 位不同必然分桶。"""
    _setup(monkeypatch, tmp_path)
    retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧", trigger="reply")
    retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧", trigger="proactive")
    assert len(retrieval_v2._CACHE) == 2


def test_memory_history_bump_invalidates_cache(tmp_path, monkeypatch):
    """验收项：历史版本变化时失效缓存——整合写入后旧桶不可达。"""
    _setup(monkeypatch, tmp_path)
    r1 = retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧", trigger="reply")
    bump_memory_history()
    r2 = retrieval_v2.retrieve_memories("1", 100, "一起玩游戏吧", trigger="reply")
    assert len(retrieval_v2._CACHE) == 2
    assert r1 is not r2
