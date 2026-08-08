# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.retriever 检索模块的测试。

测试思路：在每个用例里新建临时 SQLite 库（tmp_path），并把 retriever.DB_PATH
monkeypatch 指过去；再按需开关 RAG_ENABLED / RAG_SQLITE_FTS_ENABLED / RAG_TOP_K
来验证 FTS 命中路径与回退排序路径各自的行为。

注意：这些测试断言的是“行为契约”（哪些记忆应排在前、type 应是什么），
断言本身不得被改动。
"""

import sqlite3
from pathlib import Path

import memory.retriever as retriever


def _create_temp_db(tmp_path: Path):
    """在 pytest 的 tmp_path 下创建一张带 memories / long_term_memories 表的临时库，返回库路径。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS long_term_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT,
            user_id TEXT,
            summary TEXT,
            importance REAL,
            access_count INTEGER,
            last_accessed_at DATETIME
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_related_memories_are_ranked_by_relevance_and_recency(tmp_path, monkeypatch):
    """默认（RAG 关闭）时 get_related_memories 走回退排序：查“篮球训练”应命中内容含“篮球”的记忆。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(retriever, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m1",
            "1",
            "100",
            "FACT",
            "我最近在学打篮球",
            "我最近在学打篮球",
            0.4,
            0.6,
            "active",
            1,
            "2026-08-06 09:00:00",
        ),
    )
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m2",
            "1",
            "200",
            "FACT",
            "我在学习篮球战术",
            "我在学习篮球战术",
            0.9,
            0.9,
            "active",
            2,
            "2026-08-07 12:00:00",
        ),
    )
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m3",
            "1",
            "300",
            "FACT",
            "我喜欢看电影",
            "我喜欢看电影",
            0.8,
            0.8,
            "active",
            1,
            "2026-08-07 11:00:00",
        ),
    )
    conn.commit()
    conn.close()

    results = retriever.get_related_memories(1, 99, "篮球训练", limit=2)

    assert results[0]["content"] == "我在学习篮球战术"
    assert results[0]["type"] == "RELATED"


def test_related_memories_use_sqlite_rag_index(tmp_path, monkeypatch):
    """开启 RAG + FTS 时 get_related_memories 命中 bm25 索引：应返回“篮球馆训练”那条记忆。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(retriever, "DB_PATH", db_path)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_TOP_K", 5)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m_rag",
            "1",
            "200",
            "FACT",
            "今晚我在篮球馆训练了罚球",
            "今晚我在篮球馆训练了罚球",
            0.8,
            0.9,
            "active",
            1,
            "2026-08-07 14:00:00",
        ),
    )
    conn.commit()
    conn.close()

    results = retriever.get_related_memories(1, 99, "篮球训练", limit=1)

    assert len(results) == 1
    assert results[0]["content"] == "今晚我在篮球馆训练了罚球"


def test_group_memories_prefer_recent_and_important_entries(tmp_path, monkeypatch):
    """无 query 时 get_group_memories 按访问时间倒序：最新访问的“新重要记忆”应排在第一位。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(retriever, "DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m1",
            "2",
            "10",
            "FACT",
            "旧记忆",
            "旧记忆",
            0.2,
            0.5,
            "active",
            1,
            "2026-07-01 00:00:00",
        ),
    )
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m2",
            "2",
            "11",
            "FACT",
            "新重要记忆",
            "新重要记忆",
            0.9,
            0.9,
            "active",
            3,
            "2026-08-07 13:00:00",
        ),
    )
    conn.commit()
    conn.close()

    results = retriever.get_group_memories(2, limit=2)

    assert results[0]["content"] == "新重要记忆"


def test_group_memories_query_prefers_rag_results(tmp_path, monkeypatch):
    """带 query 且开启 RAG 时，get_group_memories 优先用 FTS 命中“篮球场打球”那条。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(retriever, "DB_PATH", db_path)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_TOP_K", 5)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m4",
            "3",
            "20",
            "FACT",
            "今天我们去篮球场打球",
            "今天我们去篮球场打球",
            0.7,
            0.7,
            "active",
            1,
            "2026-08-08 09:00:00",
        ),
    )
    conn.commit()
    conn.close()

    results = retriever.get_group_memories(3, query="篮球比赛", limit=1)

    assert len(results) == 1
    assert results[0]["content"] == "今天我们去篮球场打球"


def test_user_memories_query_prefers_rag_results(tmp_path, monkeypatch):
    """开启 RAG 时，get_user_memories 应通过 FTS 且只返回该用户的“乒乓球”记忆。"""
    db_path = _create_temp_db(tmp_path)
    monkeypatch.setattr(retriever, "DB_PATH", db_path)
    monkeypatch.setattr(retriever, "RAG_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_SQLITE_FTS_ENABLED", True)
    monkeypatch.setattr(retriever, "RAG_TOP_K", 5)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, content_raw, importance, confidence, status, confirmation_count, last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "m5",
            "4",
            "30",
            "FACT",
            "用户30喜欢打乒乓球",
            "用户30喜欢打乒乓球",
            0.8,
            0.8,
            "active",
            1,
            "2026-08-08 10:00:00",
        ),
    )
    conn.commit()
    conn.close()

    results = retriever.get_user_memories(4, 30, query="乒乓球", limit=1)

    assert len(results) == 1
    assert results[0]["content"] == "用户30喜欢打乒乓球"
