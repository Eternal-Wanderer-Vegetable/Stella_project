from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

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
async def test_handle_chat_sends_deterministic_reply_once(
    ai_gateway_module, monkeypatch, tmp_path
):
    gateway = ai_gateway_module
    from config import settings
    from core.social.delivery import delivery_draft_from_context
    from memory import social_store
    from memory.schema import create_memory_scope_versions_table

    delivery_db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(settings, "DB_PATH", delivery_db)
    monkeypatch.setattr(gateway, "DB_PATH", delivery_db)
    with sqlite3.connect(delivery_db) as conn:
        create_memory_scope_versions_table(conn)
    monkeypatch.setattr(social_store, "_TABLES_READY", False)
    social_store.ensure_tables()
    ctx = ChatContext(user_id=111, group_id=1, msg_id=42, message="查东京天气")
    ctx.reply = "东京明天 27℃，晴。"
    ctx.lines = [ctx.reply]
    ctx.trace_id = "deterministic-reply-test"
    ctx.turn_id = "deterministic-reply-turn"
    ctx.conversation_kind = "group"
    ctx.conversation_key = "qq:9:group:1"
    ctx.bot_id = "9"
    ctx.peer_id = "1"
    ctx.storage_session_id = 1
    ctx.delivery_source_kind = "model"
    ctx.reply_disposition = "deliver"
    ctx.llm_call_count = 1
    ctx.delivery_draft = delivery_draft_from_context(ctx)

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
    monkeypatch.setattr(gateway, "_delivery_plan_is_current", lambda *a, **k: True)
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
    # v16 契约：origin（本轮 ctx）+ 确认回执随行（多人身份修复计划 §6.2）
    gateway._record_bot_lines.assert_awaited_once_with(
        9, 1, [ctx.reply], origin=ANY, receipts=ANY
    )


@pytest.mark.asyncio
async def test_flow_watch_finish_captures_reply_text(ai_gateway_module):
    """matcher.finish 包装：发出的文本成为 command.reply 检查点（计划 §6.3 A04）。"""

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
