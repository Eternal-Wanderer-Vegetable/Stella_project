# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""有界只读上下文（build_scheduled_context）的基线。

用真实 SQLite 库（只读连接走 config.DB_PATH 的 uri）验证：摘要 + 尾巴的拼装、
字符预算封顶、显式「无上下文」结果与读取失败的降级。
"""

from __future__ import annotations

import sqlite3

import pytest

from stella_project.plugins.bot_main.scheduling.context import (
    ScheduledContext,
    build_scheduled_context,
)

GROUP = 12345


@pytest.fixture()
def memory_db(tmp_path, monkeypatch):
    """最小记忆库：group_messages + short_term_context 两张表。"""
    db = tmp_path / "memory.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "group_id TEXT, user_id TEXT, content TEXT, source_kind TEXT DEFAULT 'PASSIVE', "
        "timestamp TEXT)"
    )
    conn.execute(
        "CREATE TABLE short_term_context (group_id TEXT PRIMARY KEY, active_summary TEXT)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr("config.DB_PATH", db)
    return db


def _insert_messages(db, messages, *, source="PASSIVE", user="777"):
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) "
        "VALUES (?, ?, ?, ?)",
        [(str(GROUP), user, text, source) for text in messages],
    )
    conn.commit()
    conn.close()


def _set_summary(db, summary):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO short_term_context (group_id, active_summary) VALUES (?, ?)",
        (str(GROUP), summary),
    )
    conn.commit()
    conn.close()


def test_empty_group_yields_explicit_no_context(memory_db):
    ctx = build_scheduled_context(GROUP)
    assert isinstance(ctx, ScheduledContext)
    assert not ctx.has_context and ctx.text == ""
    assert ctx.messages_used == 0 and not ctx.summary_used


def test_context_includes_summary_and_tail(memory_db):
    _set_summary(memory_db, "群里在讨论周末去爬山")
    _insert_messages(memory_db, ["周六出发吗", "已经订好车了"])
    ctx = build_scheduled_context(GROUP)
    assert ctx.has_context
    assert ctx.summary_used and ctx.messages_used == 2
    assert "群里在讨论周末去爬山" in ctx.text
    assert "用户777: 周六出发吗" in ctx.text
    assert "用户777: 已经订好车了" in ctx.text
    # 顺序：摘要在前、消息旧→新在后
    assert ctx.text.index("【群近期话题】") < ctx.text.index("【最近消息】")
    assert ctx.text.index("周六出发吗") < ctx.text.index("已经订好车了")


def test_bot_self_lines_are_labelled(memory_db):
    _insert_messages(memory_db, ["我来提醒大家"], source="BOT_SELF", user="0")
    ctx = build_scheduled_context(GROUP)
    assert "Stella: 我来提醒大家" in ctx.text


def test_character_budget_is_respected(memory_db):
    _set_summary(memory_db, "话题摘要" * 10)  # 40 字符
    _insert_messages(memory_db, [f"消息{i}" + "内容" * 30 for i in range(10)])
    ctx = build_scheduled_context(GROUP, max_chars=300)
    assert len(ctx.text) <= 300
    assert ctx.has_context
    # 预算吃紧时丢的是更旧的消息，最新的必须留下
    assert "消息9" in ctx.text


def test_message_count_cap(memory_db):
    _insert_messages(memory_db, [f"m{i}" for i in range(50)])
    ctx = build_scheduled_context(GROUP, max_messages=5)
    assert ctx.messages_used <= 5
    assert ctx.truncated  # 还有更旧的消息没进上下文


def test_per_message_truncation(memory_db):
    _insert_messages(memory_db, ["长" * 500])
    ctx = build_scheduled_context(GROUP, max_chars=2000)
    assert ctx.has_context
    assert len(ctx.text) < 200  # 单条被截到 80 字符以内（加前缀）
    assert ctx.truncated


def test_read_failure_degrades_to_no_context(tmp_path, monkeypatch):
    """库读不了（不存在的目录）→ 显式无上下文，绝不抛异常。"""
    monkeypatch.setattr("config.DB_PATH", tmp_path / "missing-dir" / "x.db")
    ctx = build_scheduled_context(GROUP)
    assert not ctx.has_context and ctx.text == ""
