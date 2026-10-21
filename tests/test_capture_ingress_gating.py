# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""入站门控端到端测试（AI-gated memory capture 计划 §7 步骤 5/6）。

覆盖：QQ 群 / QQ 私聊 / WebChat 三入口在「门关闭」时不产生任何原始行或
内容派生副作用（身份声明、共享授权、社会证据、表达学习、参与评分、整合
触发），回复链路照常；「门开启」时一切照旧；关闭期间的消息在恢复后**不
补录不回放**；BOT_SELF 写入方在门关闭时整段不落库。

LLM/管线走 mock；门用注入假探针的 CaptureGate 实例（不依赖真实端点）。
"""

from __future__ import annotations

import asyncio
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    PrivateMessageEvent,
)

nonebot.init()

import memory.expression_learning as expression_learning
import memory.pre_processors as pre
import webui.chat_ingress as chat_ingress
from core.context import ChatContext
from memory import capture_gate
from stella_project.plugins.bot_main import ai_gateway as gateway

BOT = "10000"
GROUP = 7777
USER = 2001


def _static_probe(ok: bool, category: str = "no_backend"):
    async def _probe() -> tuple[bool, str]:
        return ok, category

    return _probe


def _install_closed(monkeypatch) -> capture_gate.CaptureGate:
    """装一个「探针失败后关门」的实例。

    直接置状态而非跑 probe_once：本文件要在同步/异步两种测试里复用，
    asyncio.run 不能嵌进事件循环；门状态机自身的迁移逻辑由
    tests/test_memory_capture_gate.py 覆盖。
    """
    gate = capture_gate.CaptureGate(probe=_static_probe(False, "no_backend"))
    gate._started = True
    gate._state = capture_gate.STATE_UNAVAILABLE
    gate._error_category = "no_backend"
    monkeypatch.setattr(capture_gate, "_gate", gate)
    return gate


def _install_ready(monkeypatch) -> capture_gate.CaptureGate:
    gate = capture_gate.CaptureGate(probe=_static_probe(True, ""))
    gate._started = True
    gate._state = capture_gate.STATE_READY
    gate._ready_until = time.monotonic() + 60.0
    monkeypatch.setattr(capture_gate, "_gate", gate)
    return gate


def _rows(db, sql="SELECT * FROM group_messages ORDER BY id", params=()):
    """读 group_messages；表不存在（关门时连建表都不该发生）按空处理。"""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()


# ============================================================
# QQ 群入口
# ============================================================


def _group_event(user_id=USER, message_id=555, text="今天天气不错"):
    return GroupMessageEvent(
        time=0, self_id=BOT, post_type="message", sub_type="normal",
        user_id=user_id, message_type="group", message_id=message_id,
        group_id=GROUP, message=Message(text), original_message=Message(text),
        raw_message=text, font=0, sender={"nickname": "u", "role": "member"},
    )


@pytest.fixture()
def group_env(tmp_path, monkeypatch):
    """群链路隔离：临时库 + 社会关闭 + 表达/参与打间谍。"""
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db)
    monkeypatch.setattr(gateway, "DB_PATH", db)
    import config.spaces as spaces

    monkeypatch.setattr(spaces, "resolve_space", lambda _group_id: "test-space")
    monkeypatch.setattr(gateway, "ALLOWED_GROUPS", {GROUP})
    monkeypatch.setattr(gateway, "_social_delivery_enabled", lambda: False)
    monkeypatch.setattr(gateway, "PARTICIPATION_ENABLED", True)
    monkeypatch.setattr(gateway, "PARTICIPATION_TRIGGER_ENABLED", False)
    calls = {"expression": 0, "observe": 0}

    def _spy_expression(*_a, **_k):
        calls["expression"] += 1

    class _FakePM:
        async def observe(self, *_a, **_k):
            calls["observe"] += 1
            return

    monkeypatch.setattr(expression_learning, "note_passive_message", _spy_expression)
    monkeypatch.setattr(gateway, "get_participation_manager", lambda: _FakePM())
    return SimpleNamespace(db=db, calls=calls)


@pytest.mark.asyncio
async def test_group_closed_gate_writes_nothing_derived(group_env, monkeypatch):
    """门关闭：无原始行、无表达学习、无参与评分——内容派生全部缺席。"""
    _install_closed(monkeypatch)
    await gateway.record_group_chat(_group_event())
    assert _rows(group_env.db) == []
    assert _rows(
        group_env.db,
        "SELECT conversation_key, storage_session_id FROM conversation_registry",
    ) == []
    assert group_env.calls == {"expression": 0, "observe": 0}


@pytest.mark.asyncio
async def test_group_ready_gate_persists_with_side_effects(group_env, monkeypatch):
    """门开启：原始行照常，表达学习与参与评分照常（正路径不回归）。"""
    _install_ready(monkeypatch)
    await gateway.record_group_chat(_group_event())
    rows = _rows(group_env.db)
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "PASSIVE"
    assert rows[0]["content"] == "今天天气不错"
    assert _rows(
        group_env.db,
        "SELECT conversation_key, storage_session_id FROM conversation_registry",
    ) == [{"conversation_key": f"qq:{BOT}:group:{GROUP}", "storage_session_id": GROUP}]
    assert group_env.calls["expression"] == 1
    assert group_env.calls["observe"] == 1


@pytest.mark.asyncio
async def test_group_outage_interval_not_replayed_after_recovery(
    group_env, monkeypatch
):
    """恢复后只采新消息：关闭期间收到的内容不补录、不回放。"""
    _install_closed(monkeypatch)
    await gateway.record_group_chat(_group_event(text="宕机期间说的话", message_id=1))
    assert _rows(group_env.db) == []
    _install_ready(monkeypatch)
    await gateway.record_group_chat(_group_event(text="恢复后第一条", message_id=2))
    rows = _rows(group_env.db)
    assert [r["content"] for r in rows] == ["恢复后第一条"]
    assert not any("宕机期间" in (r["content"] or "") for r in rows)


# ============================================================
# QQ 私聊入口
# ============================================================


def _private_event(user_id=USER, message_id=9001, text="在吗"):
    return PrivateMessageEvent(
        time=0, self_id=BOT, post_type="message", sub_type="friend",
        user_id=user_id, message_type="private", message_id=message_id,
        message=Message(text), original_message=Message(text),
        raw_message=text, font=0, sender={"nickname": "u"},
    )


@pytest.fixture()
def private_env(tmp_path, monkeypatch):
    """私聊链路隔离（同 test_private_chat_ingress 的口径）+ 三个间谍。"""
    db = tmp_path / "agent_memory.db"
    from config import settings

    monkeypatch.setattr(gateway, "DB_PATH", db)
    monkeypatch.setattr(settings, "DB_PATH", db)
    monkeypatch.setattr(pre, "DB_PATH", db)
    from memory import social_store
    from memory.schema import create_memory_scope_versions_table

    with sqlite3.connect(db) as conn:
        create_memory_scope_versions_table(conn)
    monkeypatch.setattr(social_store, "_TABLES_READY", False)
    social_store.ensure_tables()
    monkeypatch.setattr(gateway, "_social_delivery_enabled", lambda: False)
    monkeypatch.setattr(gateway, "_delivery_plan_is_current", lambda *a, **k: True)
    monkeypatch.setattr(gateway, "schedule_compact", lambda *a, **k: None)
    consolidator = SimpleNamespace(
        has_new_messages_to_consolidate=Mock(return_value=0)
    )
    monkeypatch.setattr(gateway, "get_consolidator", lambda: consolidator)
    monkeypatch.setattr(gateway, "budget_blocked", lambda role: False)
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    send = AsyncMock(return_value={"message_id": 777})
    monkeypatch.setattr(gateway.private_chat_handler, "send", send)
    finish = AsyncMock()
    monkeypatch.setattr(gateway.private_chat_handler, "finish", finish)

    async def reply(_session_key, turn_ctx, **_kwargs):
        from core.social.delivery import delivery_draft_from_context

        turn_ctx.lines = ["在的"]
        turn_ctx.turn_id = "gating-private-test"
        turn_ctx.delivery_source_kind = "model"
        turn_ctx.llm_call_count = 1
        turn_ctx.delivery_draft = delivery_draft_from_context(turn_ctx)
        return turn_ctx

    engine = AsyncMock(side_effect=reply)
    monkeypatch.setattr(gateway, "_run_turn_via_engine", engine)
    sharing = Mock()
    monkeypatch.setattr(gateway, "_maybe_personal_sharing", sharing)
    return SimpleNamespace(
        db=db, send=send, consolidator=consolidator, sharing=sharing,
    )


@pytest.mark.asyncio
async def test_private_closed_gate_skips_persist_reply_still_works(
    private_env, monkeypatch
):
    """门关闭：不落库、无身份声明、无共享授权、无整合触发；回复照常。"""
    _install_closed(monkeypatch)
    await gateway.handle_private_chat(Mock(self_id=BOT), _private_event())
    assert _rows(private_env.db) == []
    private_env.sharing.assert_not_called()
    private_env.consolidator.has_new_messages_to_consolidate.assert_not_called()
    private_env.send.assert_awaited()  # 回复链路不受采集门影响


@pytest.mark.asyncio
async def test_private_ready_gate_persists_with_sharing_and_trigger(
    private_env, monkeypatch
):
    """门开启：PRIVATE_DIRECT 行 + 共享授权 + 整合触发全部照旧。"""
    _install_ready(monkeypatch)
    await gateway.handle_private_chat(Mock(self_id=BOT), _private_event())
    rows = _rows(private_env.db)
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "PRIVATE_DIRECT"
    private_env.sharing.assert_called_once()
    private_env.consolidator.has_new_messages_to_consolidate.assert_called_once()


# ============================================================
# WebChat 入口
# ============================================================


@pytest.fixture()
def webchat_env(tmp_path, monkeypatch):
    """WebChat 链路隔离：临时库 + 假管线/假 facade + 社会关闭。"""
    import config as config_pkg
    from config import settings
    from core.runtime import facade as rt_facade

    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db)
    monkeypatch.setattr(config_pkg, "DB_PATH", db)
    monkeypatch.setattr(settings, "DB_PATH", db)
    monkeypatch.setattr(config_pkg, "SOCIAL_ENABLED", False)
    monkeypatch.setattr(settings, "SOCIAL_ENABLED", False)
    monkeypatch.setattr(chat_ingress, "_resolve_pipeline", lambda: object())

    class _FakeFacade:
        async def submit_turn(self, _key, _pipeline, ctx):
            ctx.lines = ["回复照常返回"]
            ctx.turn_id = "wc-turn-1"
            return ctx

    async def _fake_start():
        return _FakeFacade()

    monkeypatch.setattr(rt_facade, "ensure_shared_facade_started", _fake_start)
    return SimpleNamespace(db=db)


def test_webchat_closed_gate_skips_rows_returns_lines(webchat_env, monkeypatch):
    """门关闭：用户输入与 BOT_SELF 回复都不落库；SSE 回复内容照常。"""
    _install_closed(monkeypatch)
    result = asyncio.run(chat_ingress.run_turn("在吗", "admin"))
    assert result["lines"] == ["回复照常返回"]
    assert _rows(webchat_env.db) == []


def test_webchat_ready_gate_persists_user_and_bot_self(webchat_env, monkeypatch):
    """门开启：AT_MENTION 输入行 + BOT_SELF 回例行照常。"""
    _install_ready(monkeypatch)
    result = asyncio.run(chat_ingress.run_turn("在吗", "admin"))
    assert result["lines"] == ["回复照常返回"]
    rows = _rows(webchat_env.db)
    kinds = [r["source_kind"] for r in rows]
    assert kinds == ["AT_MENTION", "BOT_SELF"]
    assert rows[0]["content"] == "在吗"
    assert rows[1]["content"] == "回复照常返回"


# ============================================================
# BOT_SELF 写入方（_record_bot_lines：全部播报/应答共用入口）
# ============================================================


def test_bot_self_lines_gated_then_recorded_after_recovery(tmp_path, monkeypatch):
    """门关闭时 Bot 台词整段不落库（无 AI 播报不能变成记忆行）；恢复后照常。"""
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db)
    origin = ChatContext(
        user_id=USER, group_id=GROUP, msg_id=1, message="x",
        conversation_kind="group", conversation_key=f"qq:{BOT}:group:{GROUP}",
        bot_id=BOT,
    )
    _install_closed(monkeypatch)
    asyncio.run(gateway._record_bot_lines(int(BOT), GROUP, ["好的我知道了"], origin=origin))
    assert _rows(db) == []
    _install_ready(monkeypatch)
    asyncio.run(gateway._record_bot_lines(int(BOT), GROUP, ["好的我知道了"], origin=origin))
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["source_kind"] == "BOT_SELF"
