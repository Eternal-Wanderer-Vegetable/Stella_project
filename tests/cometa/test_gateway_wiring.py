# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""ai_gateway 的 cometa 接线回归（2026-09-30 用户实测缺陷 #9）。

缺陷：handle_chat 引用 cometa_bridge，但模块级从未导入——_start_cometa 里的
局部导入只绑定局部名。探针测试全部绕过 handle_chat 入口，直到真实 @ 触发
才以 NameError 爆出。本文件让 handle_chat **真实执行**委派分支：
模块级绑定存在性 + ack 分支经 cometa_bridge.deliver_ack 的端到端。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

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


def test_cometa_bridge_bound_at_module_level(ai_gateway_module):
    """缺陷 #9 的直接锚点：模块级必须能取到 cometa_bridge。"""
    from stella_project.plugins.bot_main import cometa_bridge

    assert ai_gateway_module.cometa_bridge is cometa_bridge


@pytest.mark.asyncio
async def test_handle_chat_cometa_ack_branch_end_to_end(
    ai_gateway_module, monkeypatch, tmp_path
):
    """COMETA_ENABLED=true 的 @ 触发：handle_chat 走到 cometa ack 分支并经
    桥接真实认领/发送，不再 NameError；ack 通知落 SENT，普通回复链路被跳过。"""
    from cometa import runtime as cometa_runtime
    from cometa.config import BackendConfig, CometaConfig, ProfileConfig
    from cometa.models import NotificationState, Origin, TaskSpec
    from cometa.service import Actor, CometaService
    from cometa.store import CometaStore

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

    # 真实服务（临时库）：受理一条任务拿到 ack 通知
    cfg = CometaConfig.load(env={"STELLA_HOME": str(tmp_path), "COMETA_ENABLED": "true"})
    cfg.enabled = True
    cfg.backends["fake"] = BackendConfig(backend_id="fake", type="fake", enabled=True)
    cfg.profiles["coding"] = ProfileConfig(name="coding", backend="fake")
    cfg.access.qq_user_ids = {111}
    cfg.access.qq_group_ids = {1}
    service = CometaService(CometaStore(cfg.db_path), cfg, instance_id="inst-gw")
    receipt = service.submit(
        TaskSpec(objective="网关接线验证"),
        actor=Actor(kind="qq_user", id="111"),
        origin=Origin(
            instance_id="inst-gw", platform="qq", bot_id="9",
            conversation_id="1", requester_id="111",
            source_request_id="msg-42", reply_to_message_id="42",
        ),
        idempotency_key="k-gw",
    )
    task = service.store.get_task(receipt.task_id)
    from cometa.presentation import render_ack

    ack_text = render_ack(task)
    cometa_runtime.set_current(
        SimpleNamespace(config=cfg, store=service.store, service=service, enabled=True)
    )

    # 打开 cometa 总开关（handle_chat 的入口门）
    monkeypatch.setattr(gateway, "_cometa_enabled", lambda: True)
    monkeypatch.setattr(gateway, "_cometa_instance_id", lambda: "inst-gw")
    # handle_chat 的其余依赖（与 deterministic 回归同款替身）
    ctx = ChatContext(user_id=111, group_id=1, msg_id=42, message="委派 做点什么")
    ctx.trace_id = "cometa-ack-delivery-test"
    ctx.turn_id = "cometa-ack-delivery-turn"
    ctx.conversation_kind = "group"
    ctx.conversation_key = "qq:9:group:1"
    ctx.bot_id = "9"
    ctx.peer_id = "1"
    ctx.storage_session_id = 1
    ctx.delivery_source_kind = "trusted-server"
    ctx.reply_disposition = "deliver"
    ctx.lines = ["placeholder"]
    ctx.delivery_draft = delivery_draft_from_context(ctx)
    ctx.cometa_origin = {
        "instance_id": "inst-gw", "platform": "qq", "bot_id": "9",
        "conversation_id": "1", "requester_id": "111",
        "source_request_id": "msg-42", "reply_to_message_id": "42",
    }
    ctx.cometa_submission = {
        "task_id": receipt.task_id,
        "ack_notification_id": receipt.ack_notification_id,
        "ack_text": ack_text,
    }
    ctx.reply = ack_text
    ctx.lines = [ack_text]
    monkeypatch.setattr(
        gateway, "_run_turn_via_engine", AsyncMock(return_value=ctx)
    )
    monkeypatch.setattr(
        gateway,
        "get_consolidator",
        lambda: SimpleNamespace(has_new_messages_to_consolidate=lambda *a, **k: 0),
    )
    monkeypatch.setattr(gateway, "budget_blocked", lambda role: False)
    send = AsyncMock(return_value=888)  # OneBot v11 send 返回 message_id
    monkeypatch.setattr(gateway.chat_handler, "send", send)
    finish = AsyncMock(side_effect=FinishedException)
    monkeypatch.setattr(gateway.chat_handler, "finish", finish)
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    monkeypatch.setattr(
        gateway, "_social_delivery_enabled", lambda: False, raising=False
    )
    monkeypatch.setattr(gateway, "_delivery_plan_is_current", lambda *a, **k: True)

    event = SimpleNamespace(
        group_id=1, user_id=111, self_id=9, message_id=42,
        get_plaintext=lambda: "委派 做点什么",
    )
    bot = SimpleNamespace(self_id="9")

    with pytest.raises(FinishedException):
        await gateway.handle_chat(bot, event)

    # ack 经 cometa_bridge.deliver_ack 认领并恰发送一次
    send.assert_awaited_once()
    assert ack_text[:12] in send.call_args.args[0].extract_plain_text()
    finish.assert_awaited_once_with()
    # v16 契约：origin ctx 随行（多人身份修复计划 §6.2）
    gateway._record_bot_lines.assert_awaited_once_with(
        9, 1, [ack_text], origin=ANY, receipts=ANY
    )
    ack = service.store.notification_of_dedupe(
        receipt.task_id, f"ack:{receipt.task_id}"
    )
    assert ack.state is NotificationState.SENT
    assert ack.receipt == "888"
    cometa_runtime.set_current(None)
