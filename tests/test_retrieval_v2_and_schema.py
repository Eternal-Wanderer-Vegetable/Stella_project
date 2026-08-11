# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""memory.retrieval_v2 检索管线与 memory.schema 迁移的测试。"""

import sqlite3
from pathlib import Path

import memory.retrieval_v2 as retrieval_v2
import memory.schema as schema


def _create_v2_db(db_path: Path):
    """建一张带 v2 列的 memories 表。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
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


def _insert_memory(db_path: Path, mid: str, content: str, usage: str, visibility: str, behavior: str = "", owner: str = "100"):
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO memories (id, group_id, user_id, type, content, importance, confidence, status, usage_tags, visibility, behavior_rule, last_accessed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (mid, "1", owner, "PREFERENCE", content, 0.8, 0.9, "active", usage, visibility, behavior, "2026-08-09 10:00:00"),
    )
    conn.commit()
    conn.close()


def test_retrieval_v2_filters_restricted_in_casual(tmp_path, monkeypatch):
    """CASUAL_REPLY 下 RESTRICTED 记忆完全禁止激活（不进聊天素材也不进行为约束）。"""
    db_path = tmp_path / "agent_memory.db"
    _create_v2_db(db_path)
    _insert_memory(
        db_path, "m_open", "用户喜欢轻松闲聊", "[\"TOPIC_CONTINUE\"]", "OPEN"
    )
    _insert_memory(
        db_path,
        "m_boundary",
        "用户不喜欢未经允许摸头",
        "[\"BOUNDARY_PROTECTION\"]",
        "RESTRICTED",
        "避免对该用户进行摸头互动",
    )
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)

    result = retrieval_v2.retrieve_memories(1, 100, "一起玩游戏吧", trigger="reply")
    conversation_ids = [m["id"] for m in result.conversation_memories]
    behavior_ids = [m["id"] for m in result.behavior_constraints]

    assert "m_open" in conversation_ids
    assert "m_boundary" not in conversation_ids
    assert "m_boundary" not in behavior_ids
    assert result.mode == "CASUAL_REPLY"


def test_retrieval_v2_conflict_mode_activates_behavior_guard(tmp_path, monkeypatch):
    """CONFLICT_AVOID 是 Behavior Guard 入口：RESTRICTED 记忆进入行为约束，不进聊天素材。"""
    db_path = tmp_path / "agent_memory.db"
    _create_v2_db(db_path)
    _insert_memory(
        db_path,
        "m_boundary",
        "用户不喜欢未经允许摸头",
        "[\"BOUNDARY_PROTECTION\"]",
        "RESTRICTED",
        "避免对该用户进行摸头互动",
        owner="235",
    )
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)

    result = retrieval_v2.retrieve_memories(1, 235, "你别开这种玩笑，我不喜欢别人这样碰我", trigger="reply")
    behavior_ids = [m["id"] for m in result.behavior_constraints]
    conversation_ids = [m["id"] for m in result.conversation_memories]

    assert result.mode == "CONFLICT_AVOID"
    assert "m_boundary" in behavior_ids
    assert "m_boundary" not in conversation_ids


def test_retrieval_v2_proactive_uses_group_memories(tmp_path, monkeypatch):
    """主动插话（user_id=0）按群级取记忆，BOUNDARY 仍被挡在聊天素材外。"""
    db_path = tmp_path / "agent_memory.db"
    _create_v2_db(db_path)
    _insert_memory(db_path, "g1", "最近群里经常玩摸头梗", "[\"GROUP_CONTEXT\"]", "OPEN")
    _insert_memory(
        db_path, "b1", "用户235不喜欢越界摸头", "[\"BOUNDARY_PROTECTION\"]", "RESTRICTED"
    )
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)

    result = retrieval_v2.retrieve_memories(1, 0, "（想自然插一句话）", trigger="proactive")
    conversation_ids = [m["id"] for m in result.conversation_memories]
    assert "g1" in conversation_ids
    assert "b1" not in conversation_ids
    assert result.mode == "ACTIVE_JOIN"


def test_retrieval_v2_fts_path_returns_qualified_columns(tmp_path, monkeypatch):
    """FTS 路径：开启 RAG+FTS 时能正确命中记忆（列名必须限定表名，避免 ambiguous column）。"""
    db_path = tmp_path / "agent_memory.db"
    _create_v2_db(db_path)
    _insert_memory(db_path, "m1", "用户喜欢打乒乓球", "[\"TOPIC_CONTINUE\"]", "OPEN")
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", True)

    # 手动建 FTS 索引（复用 retriever 的索引结构）
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
        "mem_id UNINDEXED, content, group_id UNINDEXED, user_id UNINDEXED)"
    )
    conn.execute("INSERT INTO memories_fts (mem_id, content, group_id, user_id) VALUES ('m1', '用户喜欢打乒乓球', '1', '100')")
    conn.commit()
    conn.close()

    result = retrieval_v2.retrieve_memories(1, 100, "乒乓球", trigger="reply")
    conversation_ids = [m["id"] for m in result.conversation_memories]
    assert "m1" in conversation_ids


def test_retrieval_v2_score_floor_filters_noise(tmp_path, monkeypatch):
    """/MEMORY_SCORE_MIN：低于分数门槛的合法候选不进最终会话（动态数量而非固定 Top-K）。"""
    import memory.policy as policy

    db_path = tmp_path / "agent_memory.db"
    _create_v2_db(db_path)
    conn = sqlite3.connect(db_path)
    rows = [
        # 强信号 + 新鲜：保住
        ("s", "1", "100", "EVENT", "最近在追一部剧", 0.5, 0.8, "[\"TOPIC_CONTINUE\"]", "OPEN", "2026-08-09 10:00:00"),
        # 弱信号：usage 基础分低(TOPIC_START=3) + 类型不兼容(0.75) + 很久没访问被 recency
        # 衰减，应被 0.40 门槛挡掉
        ("w", "1", "100", "STYLE", "偶尔熬夜", 0.2, 0.5, "[\"TOPIC_START\"]", "OPEN", "2025-06-01 10:00:00"),
    ]
    for mid, g, u, typ, content, imp, conf, usage, vis, lts in rows:
        conn.execute(
            "INSERT INTO memories (id, group_id, user_id, type, content, importance, confidence, "
            "status, usage_tags, visibility, last_accessed_at) VALUES (?,?,?,?,?,?,?,'active',?,?, ?)",
            (mid, g, u, typ, content, imp, conf, usage, vis, lts),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)

    result = retrieval_v2.retrieve_memories(1, 100, "一起玩游戏吧", trigger="reply")
    conversation_ids = [m["id"] for m in result.conversation_memories]

    assert "s" in conversation_ids
    assert "w" not in conversation_ids
    # "w" 只是被分数门槛（+ recency 衰减）挡掉，排序阶段仍应给出 _score 供诊断。
    # 同池放入新鲜强信号，使 reference 落在新鲜侧，弱项被 recency 衰减到门槛下。
    ranked = policy.rank_memories(
        [
            {"id": "s", "type": "EVENT", "content": "最近在追一部剧", "usage_tags": ["TOPIC_CONTINUE"],
             "visibility": "OPEN", "confidence": 0.8, "importance": 0.5,
             "last_accessed_at": "2026-08-09 10:00:00"},
            {"id": "w", "type": "STYLE", "content": "偶尔熬夜", "usage_tags": ["TOPIC_START"],
             "visibility": "OPEN", "confidence": 0.5, "importance": 0.2,
             "last_accessed_at": "2025-06-01 10:00:00"},
        ],
        "CASUAL_REPLY",
        query="一起玩游戏吧",
    )
    ids = [m["id"] for m in ranked]
    assert ids.index("s") < ids.index("w")
    assert next(m["_score"] for m in ranked if m["id"] == "w") < 0.40
    assert next(m["_score"] for m in ranked if m["id"] == "s") >= 0.40


def test_schema_migration_adds_columns(tmp_path, monkeypatch):
    """迁移给旧表补上 v2 列，并创建索引；幂等重跑不重复加列。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, group_id TEXT, content TEXT, status TEXT)"
    )
    conn.execute(
        "CREATE TABLE long_term_memories (id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, summary TEXT)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(schema, "DB_PATH", db_path)
    migrated = schema.ensure_v2_schema(db_path)

    assert migrated is True
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    ltm_cols = {row[1] for row in conn.execute("PRAGMA table_info(long_term_memories)")}
    assert {"usage_tags", "visibility", "behavior_rule"} <= cols
    assert {"memory_type", "usage_tags", "visibility", "confidence", "status"} <= ltm_cols
    version = conn.execute("SELECT version FROM schema_meta WHERE k='version'").fetchone()[0]
    conn.close()
    assert version == schema.SCHEMA_VERSION

    # 幂等：重跑不再迁移
    assert schema.ensure_v2_schema(db_path) is False


def test_schema_migration_does_not_touch_existing_data(tmp_path, monkeypatch):
    """Additive Migration：已有数据不被删除或破坏。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE memories (id TEXT PRIMARY KEY, group_id TEXT, content TEXT, status TEXT)"
    )
    conn.execute(
        "INSERT INTO memories (id, group_id, content, status) VALUES ('m1', '1', '旧记忆', 'active')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(schema, "DB_PATH", db_path)
    schema.ensure_v2_schema(db_path)

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT content, status FROM memories WHERE id='m1'").fetchone()
    conn.close()
    assert row == ("旧记忆", "active")
