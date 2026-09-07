# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话上下文缓存（设计阶段四）的测试：session_id + history_version + mode + policy_version。

钉住三个性质：
1. 历史版本未变 → 复用上次组装结果（省掉尾巴等重查询，且逐字节一致）；
2. 消息/摘要/会话摘要任一变化 → 版本变化 → 重新组装；
3. 复用结果与全新组装结果相同（缓存不改变语义）。
"""

import asyncio
import sqlite3

import memory.pre_processors as pre_processors_mod
import memory.session_context as session_context
from core.context import ChatContext
from memory.pre_processors import build_context
from memory.timeutil import db_timestamp_str


def _make_db(path, messages, summary_row=None):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT,
            user_id TEXT,
            content TEXT,
            source_kind TEXT DEFAULT 'PASSIVE',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) VALUES (?, ?, ?, ?)",
        messages,
    )
    if summary_row is not None:
        conn.execute("""
            CREATE TABLE short_term_context (
                group_id TEXT PRIMARY KEY,
                active_summary TEXT,
                pending_topic TEXT,
                recent_exchanges TEXT,
                updated_at DATETIME
            )
        """)
        conn.execute(
            "INSERT INTO short_term_context (group_id, active_summary, pending_topic, updated_at) "
            "VALUES (?, ?, '无', ?)",
            ("1", summary_row[0], summary_row[1]),
        )
    conn.commit()
    conn.close()


def _reset(monkeypatch, db):
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    monkeypatch.setattr(session_context, "SESSION_CONTEXT_ENABLED", True)
    pre_processors_mod._SESSION_CONTEXT_CACHE.clear()
    session_context.reset_state()


def _build():
    return asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="在吗")))


def test_unchanged_history_reuses_assembled_context(tmp_path, monkeypatch):
    """无新消息/无摘要变化 → 组装结果被复用，不再重算。

    首次组装会顺带把会话状态从「无状态」初始化（summary_version -1→0），
    该迁移本身算历史版本变化，第二次组装重算一次属于预期；第三次起命中。
    """
    db = tmp_path / "ctx.db"
    _make_db(db, [("1", "1000", "你平时用手机还是电脑", "BOT_SELF"), ("1", "2001", "手机", "PASSIVE")])
    _reset(monkeypatch, db)

    first = _build()
    second = _build()  # 会话状态初始化导致的版本迁移：重算一次
    assert len(pre_processors_mod._SESSION_CONTEXT_CACHE) == 2
    third = _build()
    # 命中：不新增缓存条目，三次结果逐字节一致
    assert len(pre_processors_mod._SESSION_CONTEXT_CACHE) == 2
    assert third.short_term == second.short_term == first.short_term
    assert third.tail_start_id == first.tail_start_id


def test_new_message_invalidates_cache(tmp_path, monkeypatch):
    """新消息落库 → max(id) 变化 → 重新组装，新消息进入尾巴。"""
    db = tmp_path / "ctx.db"
    _make_db(db, [("1", "1000", "你平时用手机还是电脑", "BOT_SELF")])
    _reset(monkeypatch, db)

    first = _build()
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) VALUES ('1', '2001', '手机', 'PASSIVE')"
    )
    conn.commit()
    conn.close()

    second = _build()
    assert "用户(2001): 手机" in second.short_term
    assert "用户(2001): 手机" not in first.short_term
    assert len(pre_processors_mod._SESSION_CONTEXT_CACHE) == 2


def test_summary_update_invalidates_cache(tmp_path, monkeypatch):
    """整合器更新 short_term_context（updated_at 变化）→ 重新组装。

    时间戳用 db_timestamp_str 生成（UTC、与 CURRENT_TIMESTAMP 同基准），
    距今 60s 内不会被「摘要过期」分支改写成「之前的话题」标题。
    """
    db = tmp_path / "ctx.db"
    _make_db(db, [("1", "1000", "你好", "PASSIVE")], summary_row=("旧摘要", db_timestamp_str(-60 / 3600)))
    _reset(monkeypatch, db)

    first = _build()
    assert "对话摘要: 旧摘要" in first.short_term
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE short_term_context SET active_summary = '新摘要', updated_at = ? WHERE group_id = '1'",
        (db_timestamp_str(0),),
    )
    conn.commit()
    conn.close()

    second = _build()
    assert "对话摘要: 新摘要" in second.short_term
    assert "对话摘要: 旧摘要" not in second.short_term


def test_session_summary_version_invalidates_cache(tmp_path, monkeypatch):
    """会话压缩产出新摘要（compact_count 递增）→ 重新组装。"""
    db = tmp_path / "ctx.db"
    _make_db(db, [("1", "1000", "你好", "PASSIVE")])
    _reset(monkeypatch, db)

    first = _build()
    assert "本场对话较早的内容" not in first.short_term
    session_context.apply_summary(1, "更早聊过散打", up_to_id=1, message_count=1)

    second = _build()
    assert "本场对话较早的内容" in second.short_term
    assert "更早聊过散打" in second.short_term


def test_cache_key_isolates_databases(tmp_path, monkeypatch):
    """不同库（key 含 DB_PATH）绝不互读缓存——测试与多库部署的共同前提。"""
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    _make_db(db_a, [("1", "1000", "消息A", "PASSIVE")])
    _make_db(db_b, [("1", "1000", "消息B", "PASSIVE")])

    _reset(monkeypatch, db_a)
    ctx_a = _build()
    _reset(monkeypatch, db_b)
    ctx_b = _build()
    # b 的重算没有被 a 的缓存短路
    assert "消息A" in ctx_a.short_term
    assert "消息B" in ctx_b.short_term
