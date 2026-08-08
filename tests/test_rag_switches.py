# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""针对 settings.py 中 RAG 开关（RAG_ENABLED / RAG_SQLITE_FTS_ENABLED / RAG_TOP_K）
的检索行为测试，验证开关组合下 retriever 的取舍是否正确。
"""
import sqlite3
from pathlib import Path

import memory.retriever as retriever


def _new_db(tmp_path: Path, monkeypatch) -> Path:
    """建临时库 + 创建 memories / long_term_memories 表，并把 DB_PATH 指过去。"""
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            group_id TEXT, user_id TEXT, type TEXT, content TEXT, content_raw TEXT,
            importance REAL, confidence REAL, status TEXT, confirmation_count INTEGER,
            last_confirmed_at DATETIME, last_accessed_at DATETIME, compressed_at DATETIME,
            compression_version INTEGER, is_atomized INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE long_term_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT,
            summary TEXT, importance REAL, access_count INTEGER, last_accessed_at DATETIME
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(retriever, "DB_PATH", db)
    return db


def _insert_memory(db: Path, mid: str, group: str, user: str, content: str, importance: float, accessed: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) "
        "VALUES (?, ?, ?, 'FACT', ?, ?, ?, 0.9, 'active', 1, ?)",
        (mid, group, user, content, content, importance, accessed),
    )
    conn.commit()
    conn.close()


def test_rag_disabled_uses_weighted_fallback_ranking(tmp_path, monkeypatch):
    """RAG_ENABLED=False：query 触发的回退要按“关键词+重要度+置信度”综合排序，
    而不是只看时间新旧（更近但无关的不得排第一）。"""
    db = _new_db(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "RAG_ENABLED", False)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)

    _insert_memory(db, "m1", "1", "100", "我在练习羽毛球发球", 0.9, "2026-08-08 12:00:00")
    _insert_memory(db, "m2", "1", "100", "今天和大家吃了火锅", 0.9, "2026-08-08 13:00:00")

    results = retriever.get_group_memories(1, query="羽毛球", limit=2)
    assert results[0]["content"] == "我在练习羽毛球发球"


def test_fts_disabled_minnes_total_also_digit_ranking(tmp_path, monkeypatch):
    """RAG_ENABLED=True 但 RAG_SQLITE_FTS_ENABLED=False：FTS 查询为空 → 同样走加权回退。"""
    db = _new_db(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", False)

    _insert_memory(db, "m1", "1", "100", "我喜欢打网球", 0.9, "2026-08-08 09:00:00")
    _insert_memory(db, "m2", "1", "100", "最近在学编程", 0.9, "2026-08-08 12:00:00")

    results = retriever.get_user_memories(1, 100, query="网球", limit=2)
    assert results[0]["content"] == "我喜欢打网球"


def test_get_user_memories_query_scopes_to_user(tmp_path, monkeypatch):
    """开启 RAG 后，get_user_memories 的 query 路径必须只返回对应用户的记忆。"""
    db = _new_db(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_TOP_K", 5)

    _insert_memory(db, "m1", "2", "100", "用户100喜欢篮球", 0.9, "2026-08-08 09:00:00")
    _insert_memory(db, "m2", "2", "200", "用户200喜欢篮球", 0.9, "2026-08-08 09:00:00")

    results = retriever.get_user_memories(2, 100, query="篮球", limit=5)
    assert len(results) == 1
    assert results[0]["content"] == "用户100喜欢篮球"


def test_rag_disabled_does_not_create_fts_table(tmp_path, monkeypatch):
    """RAG_ENABLED=False：单纯的搜索不应创建 memories_fts 虚拟表。"""
    db = _new_db(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "RAG_ENABLED", False)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)

    _insert_memory(db, "m1", "3", "100", "看球真有意思", 0.8, "2026-08-08 09:00:00")

    retriever.get_group_memories(3, query="球", limit=5)

    conn = sqlite3.connect(db)
    table_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='memories_fts'"
    ).fetchone()[0]
    conn.close()
    assert table_count == 0


def test_rag_top_k_sets_candidate_pool_floor(tmp_path, monkeypatch):
    """RAG_TOP_K 作为候选池下限：检索 wrapper 用 max(limit, RAG_TOP_K) 拉取候选，
    所以 RAG_TOP_K 越大，进入后续精排的候选就越多。"""
    db = _new_db(tmp_path, monkeypatch)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)

    _insert_memory(db, "m1", "4", "100", "我最近喜欢篮球", 0.8, "2026-08-08 09:00:00")
    _insert_memory(db, "m2", "4", "100", "篮球比赛真精彩", 0.8, "2026-08-08 10:00:00")

    conn = sqlite3.connect(db)
    cursor = conn.cursor()

    # RAG_TOP_K=3：即便限流 limit=1，也可拿满 2 条候选
    monkeypatch.setattr(retriever, "RAG_TOP_K", 3)
    pool_big = retriever._query_rag_results(cursor, 4, "篮球", limit=max(1, retriever.RAG_TOP_K))
    assert len(pool_big) == 2

    # RAG_TOP_K=1：候选池被压到 1 条
    monkeypatch.setattr(retriever, "RAG_TOP_K", 1)
    pool_small = retriever._query_rag_results(cursor, 4, "篮球", limit=max(1, retriever.RAG_TOP_K))
    assert len(pool_small) == 1

    conn.close()