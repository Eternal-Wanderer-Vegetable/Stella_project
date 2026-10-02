from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nonebot.exception import FinishedException

from core.context import ChatContext


@pytest.fixture(scope="module")
def ai_gateway_module():
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()

    from stella_project.plugins.bot_main import ai_gateway

    return ai_gateway


@pytest.mark.asyncio
async def test_handle_chat_sends_deterministic_reply_once(ai_gateway_module, monkeypatch):
    gateway = ai_gateway_module
    ctx = ChatContext(user_id=111, group_id=1, msg_id=42, message="查东京天气")
    ctx.reply = "东京明天 27℃，晴。"
    ctx.lines = [ctx.reply]

    gateway._run_turn_via_engine = AsyncMock(return_value=ctx)
    monkeypatch.setattr(
        gateway,
        "get_consolidator",
        lambda: SimpleNamespace(has_new_messages_to_consolidate=lambda *a, **k: 0),
    )
    monkeypatch.setattr(gateway, "budget_blocked", lambda role: False)
    monkeypatch.setattr(
        gateway,
        "get_proactive",
        lambda: SimpleNamespace(record_spoken=Mock()),
    )
    monkeypatch.setattr(
        gateway,
        "get_participation_manager",
        lambda: SimpleNamespace(note_stella_spoke=Mock()),
    )
    monkeypatch.setattr(gateway.expression_learning, "on_reply_sent", Mock())
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    # 新发送契约（计划 §6.1）：每段都走 send 并返回平台回执，finish 只结束
    # matcher 流程不再携带消息；BOT_SELF 只记确认送达的片段。
    send = AsyncMock(return_value={"message_id": 777})
    monkeypatch.setattr(gateway.chat_handler, "send", send)
    finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(gateway.chat_handler, "finish", finish)

    event = SimpleNamespace(
        group_id=1,
        user_id=111,
        self_id=9,
        message_id=42,
        get_plaintext=lambda: "查东京天气",
    )
    bot = SimpleNamespace(self_id="9")

    with pytest.raises(FinishedException):
        await gateway.handle_chat(bot, event)

    gateway._run_turn_via_engine.assert_awaited_once()
    send.assert_awaited_once()
    finish.assert_awaited_once_with()
    gateway._record_bot_lines.assert_awaited_once_with(9, 1, [ctx.reply])


@pytest.mark.asyncio
async def test_flow_watch_finish_captures_reply_text(ai_gateway_module):
    """matcher.finish 包装：发出的文本成为 command.reply 检查点（计划 §6.3 A04）。"""
    import asyncio

    from core.observability import message_flow, turn_trace

    root = message_flow.begin_trace(root_kind="qq_command", trace_id="cmd-cap")

    class FakeMatcher:
        @classmethod
        async def finish(cls, msg, **kwargs):
            return "ok"

    gateway = ai_gateway_module
    original = FakeMatcher.finish
    gateway._flow_watch_finish(FakeMatcher)
    assert FakeMatcher.finish is not original  # 已包装

    token = gateway._flow_reply_ctx.set(root)
    try:
        await FakeMatcher.finish("已进入安静模式")
    finally:
        gateway._flow_reply_ctx.reset(token)
    message_flow.flush()

    import sqlite3

    conn = sqlite3.connect(turn_trace.current_db_path())
    try:
        rows = conn.execute(
            "SELECT node_id, summary FROM flow_events "
            "WHERE trace_id='cmd-cap' AND node_id='command.reply'"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [("command.reply", "已进入安静模式")]

    # 无 fctx（私聊）：finish 原样工作且不产生事件
    token = gateway._flow_reply_ctx.set(None)
    try:
        assert await FakeMatcher.finish("hi") == "ok"
    finally:
        gateway._flow_reply_ctx.reset(token)
    message_flow.end_trace(root, outcome="command_sent")
    message_flow.flush()
    conn = sqlite3.connect(turn_trace.current_db_path())
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM flow_events "
            "WHERE trace_id='cmd-cap' AND node_id='command.reply'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 1
