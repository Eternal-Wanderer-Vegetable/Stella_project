# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""build_context 摘要与原始尾巴并存（2026-08-13 bug）的回归护栏。

覆盖：
1. 库里有摘要 + 原始消息 → short_term 同时含摘要与「最近的对话」，且不含「近期关键发言」；
2. 有摘要但无原始消息 → 回退到 recent_exchanges（「近期关键发言」）；
3. BOT_SELF 消息渲染为「我: xxx」，不带 QQ 号；
4. 尾巴按时间正序（最早的在前）；
回归：`[BOT_SELF: 你平时用手机还是电脑, 用户: 手机]` 中「我: 你平时用手机还是电脑」
必须出现在「用户(...): 手机」之前——这正是当时缺失的那一行。
"""
import asyncio
import json
import sqlite3

import memory.pre_processors as pre_processors_mod
from core.context import ChatContext
from memory.pre_processors import build_context


def _make_db(path, messages, summary=None, exchanges=None):
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
    if summary is not None or exchanges is not None:
        conn.execute("""
            CREATE TABLE short_term_context (
                group_id TEXT PRIMARY KEY,
                active_summary TEXT,
                pending_topic TEXT,
                recent_exchanges TEXT
            )
        """)
        conn.execute(
            "INSERT INTO short_term_context (group_id, active_summary, pending_topic, recent_exchanges) VALUES (?, ?, ?, ?)",
            (
                "1",
                summary or "",
                "无",
                json.dumps(exchanges, ensure_ascii=False) if exchanges else None,
            ),
        )
    conn.commit()
    conn.close()


def _run(db_path, **monkeypatch):
    ctx = ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")
    return asyncio.run(build_context(ctx)), ctx


def test_summary_and_tail_coexist(tmp_path, monkeypatch):
    """摘要 + 原始消息 → 同时含摘要与「最近的对话」，且不含「近期关键发言」。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [("1", "1000", "你平时用手机还是电脑", "BOT_SELF"), ("1", "2001", "手机", "PASSIVE")],
        summary="用户偏好手机",
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")))

    assert "对话摘要: 用户偏好手机" in ctx.short_term
    assert "最近的对话" in ctx.short_term
    assert "近期关键发言" not in ctx.short_term


def test_no_tail_falls_back_to_exchanges(tmp_path, monkeypatch):
    """有摘要但无原始消息 → 回退到 recent_exchanges（「近期关键发言」）。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [],
        summary="用户偏好手机",
        exchanges=[{"user_id": "2001", "content": "我一直用手机"}],
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")))

    assert "对话摘要: 用户偏好手机" in ctx.short_term
    assert "近期关键发言" in ctx.short_term
    assert "用户(2001): 我一直用手机" in ctx.short_term
    assert "最近的对话" not in ctx.short_term


def test_bot_self_rendered_as_wo(tmp_path, monkeypatch):
    """BOT_SELF 渲染为「我: xxx」，不带 QQ 号。"""
    db = tmp_path / "ctx.db"
    _make_db(db, [("1", "1000", "我在问你问题", "BOT_SELF")])
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="")))

    assert "我: 我在问你问题" in ctx.short_term
    assert "1000" not in ctx.short_term


def test_tail_in_time_order(tmp_path, monkeypatch):
    """尾巴按时间正序：最早的在前。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [
            ("1", "2001", "第一条", "PASSIVE"),
            ("1", "1000", "第二条", "BOT_SELF"),
            ("1", "2002", "第三条", "PASSIVE"),
        ],
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="")))

    pos_first = ctx.short_term.index("用户(2001): 第一条")
    pos_second = ctx.short_term.index("我: 第二条")
    pos_third = ctx.short_term.index("用户(2002): 第三条")
    assert pos_first < pos_second < pos_third


def test_regression_bot_self_before_user_reply(tmp_path, monkeypatch):
    """回归：Bot 问「你平时用手机还是电脑」，紧接着用户回「手机」——
    「我: 你平时用手机还是电脑」必须出现在「用户(...): 手机」之前。"""
    db = tmp_path / "ctx.db"
    _make_db(
        db,
        [("1", "1000", "你平时用手机还是电脑", "BOT_SELF"), ("1", "2001", "手机", "PASSIVE")],
    )
    monkeypatch.setattr(pre_processors_mod, "DB_PATH", db)
    ctx = asyncio.run(build_context(ChatContext(user_id=1000, group_id=1, msg_id=0, message="手机")))

    assert "我: 你平时用手机还是电脑" in ctx.short_term
    assert "用户(2001): 手机" in ctx.short_term
    assert ctx.short_term.index("我: 你平时用手机还是电脑") < ctx.short_term.index("用户(2001): 手机")
