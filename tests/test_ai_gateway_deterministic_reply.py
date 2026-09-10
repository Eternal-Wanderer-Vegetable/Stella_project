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

    gateway.pipeline.run = AsyncMock(return_value=ctx)
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

    gateway.pipeline.run.assert_awaited_once()
    finish.assert_awaited_once()
    gateway._record_bot_lines.assert_awaited_once_with(9, 1, [ctx.reply])
