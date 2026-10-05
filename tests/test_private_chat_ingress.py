# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""私聊入口闭环测试（计划 §6.2/§8.2 tests/test_private_chat_ingress.py）。

覆盖：真实 NoneBot 私聊 matcher 规则（无须 @）、插件接管短路、用户消息
只记录一次且带 PRIVATE_DIRECT/注册表存储键、同 QQ 两个私聊会话存储隔离、
trace scope 不共享、私聊不触发 resolve_space(0)。

LLM/管线走 mock（真实 adapter 验收是 M5，需要测试账号）。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent

from core.context import ChatContext

nonebot.init()

from stella_project.plugins.bot_main import ai_gateway as gateway


def _private_event(user_id=20001, message_id=9001, self_id="10000", text="在吗"):
    return PrivateMessageEvent(
        time=0, self_id=self_id, post_type="message", sub_type="friend",
        user_id=user_id, message_type="private", message_id=message_id,
        message=Message(text), original_message=Message(text),
        raw_message=text, font=0, sender={"nickname": "u"},
    )


@pytest.fixture()
def private_env(tmp_path, monkeypatch):
    """隔离 DB + 关掉外部副作用，返回事件构造与查询游标。"""
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(gateway, "DB_PATH", db)
    import memory.pre_processors as pre

    monkeypatch.setattr(pre, "DB_PATH", db)
    monkeypatch.setattr(gateway, "schedule_compact", lambda *a, **k: None)
    monkeypatch.setattr(
        gateway,
        "get_consolidator",
        lambda: SimpleNamespace(has_new_messages_to_consolidate=lambda *a, **k: 0),
    )
    monkeypatch.setattr(gateway, "budget_blocked", lambda role: False)
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    send = AsyncMock(return_value={"message_id": 777})
    monkeypatch.setattr(gateway.private_chat_handler, "send", send)
    finish = AsyncMock()
    monkeypatch.setattr(gateway.private_chat_handler, "finish", finish)
    return SimpleNamespace(db=db, send=send, finish=finish)


def _rows(db, sql, params=()):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


class TestPrivateTrigger:
    @pytest.mark.asyncio
    async def test_plain_text_triggers_without_mention(self, monkeypatch):
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ENABLED", True)
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ALLOWLIST", set())
        assert await gateway.is_private_trigger(_private_event())

    @pytest.mark.asyncio
    async def test_disabled_or_self_echo_or_not_allowlisted(self, monkeypatch):
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ENABLED", False)
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ALLOWLIST", set())
        assert not await gateway.is_private_trigger(_private_event())
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ENABLED", True)
        assert not await gateway.is_private_trigger(_private_event(user_id=10000))  # 自身回显
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ALLOWLIST", {20001})
        assert await gateway.is_private_trigger(_private_event(user_id=20001))
        assert not await gateway.is_private_trigger(_private_event(user_id=99999))

    @pytest.mark.asyncio
    async def test_empty_text_no_vision_does_not_trigger(self, monkeypatch):
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ENABLED", True)
        monkeypatch.setattr(gateway, "PRIVATE_CHAT_ALLOWLIST", set())
        monkeypatch.setattr(gateway, "vision_available", lambda: False)
        assert not await gateway.is_private_trigger(_private_event(text=""))


class TestEventKey:
    def test_same_message_id_across_bots_and_kinds_isolated(self):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent

        group = GroupMessageEvent(
            time=0, self_id="10000", post_type="message", sub_type="normal",
            user_id=1, message_type="group", message_id=42, group_id=12345,
            message=Message("x"), original_message=Message("x"), raw_message="x",
            font=0, sender={"nickname": "u", "role": "member"},
        )
        private = _private_event(user_id=12345, message_id=42)
        other_bot = _private_event(user_id=12345, message_id=42, self_id="20000")
        keys = {gateway._event_key(e) for e in (group, private, other_bot)}
        assert len(keys) == 3  # 同 msg_id 不同 Bot/会话互不压掉


@pytest.mark.asyncio
async def test_private_chat_end_to_end_once_recorded(private_env, monkeypatch):
    """正文不带 @ 的私聊：注册 → 落库一次（PRIVATE_DIRECT/负存储键）→ 回复。"""
    env = private_env
    turn_ctx = ChatContext(
        user_id=20001, group_id=0, msg_id=9001, message="在吗",
        source_kind="PRIVATE_DIRECT",
    )
    turn_ctx.lines = ["在的"]
    engine = AsyncMock(return_value=turn_ctx)
    monkeypatch.setattr(gateway, "_run_turn_via_engine", engine)

    await gateway.handle_private_chat(
        Mock(self_id="10000"), _private_event()
    )

    # 注册表：私聊会话一行，负存储 ID 从 -2 起（-1 是 WebChat 保留）
    reg = _rows(env.db, "SELECT kind, peer_id, storage_session_id FROM conversation_registry")
    assert reg == [("private", "20001", -2)]
    # 用户消息恰好一次，落注册表存储键，来源 PRIVATE_DIRECT
    msgs = _rows(
        env.db,
        "SELECT group_id, user_id, source_kind, content FROM group_messages",
    )
    assert msgs == [("-2", "20001", "PRIVATE_DIRECT", "在吗")]
    # runtime 键 = 规范会话键
    assert engine.await_args.args[0] == "qq:10000:private:20001"
    # 回复已发送
    assert env.send.await_count == 1
    # BOT_SELF 按确认送达片段落库（存储键参数）
    assert gateway._record_bot_lines.await_args.args[1] == -2


@pytest.mark.asyncio
async def test_two_users_distinct_storage_and_scope(private_env, monkeypatch):
    """同 Bot 两个私聊：存储 ID 递增不冲突，runtime 键互不相同。"""
    env = private_env
    turn_ctx = ChatContext(user_id=1, group_id=0, msg_id=1, message="x")
    turn_ctx.lines = ["y"]
    engine = AsyncMock(return_value=turn_ctx)
    monkeypatch.setattr(gateway, "_run_turn_via_engine", engine)

    await gateway.handle_private_chat(Mock(self_id="10000"), _private_event(user_id=20001, message_id=1))
    await gateway.handle_private_chat(Mock(self_id="10000"), _private_event(user_id=20002, message_id=2))

    reg = _rows(
        env.db,
        "SELECT peer_id, storage_session_id FROM conversation_registry"
        " WHERE kind='private' ORDER BY peer_id",
    )
    assert reg == [("20001", -2), ("20002", -3)]
    assert engine.await_args_list[0].args[0] == "qq:10000:private:20001"
    assert engine.await_args_list[1].args[0] == "qq:10000:private:20002"
    owners = _rows(
        env.db,
        "SELECT DISTINCT group_id FROM group_messages ORDER BY group_id",
    )
    assert owners == [("-2",), ("-3",)]


@pytest.mark.asyncio
async def test_plugin_handled_short_circuits_before_record(private_env, monkeypatch):
    """AstrBot 插件接管（计划 §6.2 优先权）：本体不生成、用户消息不再补写。"""
    env = private_env
    event = _private_event()
    gateway._plugin_handled_msgs[gateway._event_key(event)] = __import__("time").time()
    await gateway.handle_private_chat(Mock(self_id="10000"), event)
    assert env.send.await_count == 0
    # 表都还没建（record_message 未执行）——插件短路径发生在任何落库之前
    tables = _rows(env.db, "SELECT name FROM sqlite_master WHERE type='table' AND name='group_messages'")
    assert tables == []


def test_private_space_prompt_never_resolves_group_zero(tmp_path, monkeypatch):
    """私聊系统 prompt 走显式空间；绝不 resolve_space(0)（账本污染）。"""
    import config.spaces as spaces

    monkeypatch.setattr(spaces, "_AUTO_FILE", tmp_path / "ledger.json")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    spaces.reload()
    ctx = ChatContext(
        user_id=1, group_id=0, msg_id=1, message="x",
        group_shared_space="private:qq:10000:20001",
        conversation_kind="private",
    )
    prompt = gateway._space_system_prompt(ctx)
    assert prompt  # 回退默认人格（私聊空间没有 toml）
    assert not (tmp_path / "ledger.json").exists()  # 群 0 未被分配空间


def test_chat_context_storage_key_semantics():
    """storage_key：升级入口用注册表 ID；旧入口回退 group_id。"""
    legacy = ChatContext(user_id=1, group_id=263402786, msg_id=1, message="x")
    assert legacy.storage_key() == 263402786
    assert legacy.trace_scope == "qq:263402786"
    private = ChatContext(
        user_id=1, group_id=0, msg_id=1, message="x",
        conversation_key="qq:10000:private:20001",
        conversation_kind="private", peer_id="20001", storage_session_id=-2,
    )
    assert private.storage_key() == -2
    assert private.trace_scope == "qq:10000:private:20001"
    # 投影 v4：身份字段 + 消息信封过桥（计划 §6.1/§6.2）
    projection = private.to_json_projection()
    assert projection["projection_schema_version"] == 5
    assert "reply_to_msg_id" in projection
    assert "mentioned_user_ids" in projection
    assert projection["conversation_key"] == "qq:10000:private:20001"
    assert projection["storage_session_id"] == -2


class TestDirectEvidence:
    def test_has_direct_evidence_recognizes_private_direct(self):
        from memory.memory_manager import MemoryManager

        assert MemoryManager._has_direct_evidence('["PRIVATE_DIRECT"]')
        assert MemoryManager._has_direct_evidence('["AT_MENTION", "PASSIVE"]')
        assert not MemoryManager._has_direct_evidence('["PASSIVE"]')
        assert not MemoryManager._has_direct_evidence('["BOT_SELF"]')
        # 旧 helper 保留兼容（只认 AT_MENTION）
        assert not MemoryManager._has_at_mention('["PRIVATE_DIRECT"]')

    def test_promotion_decision_uses_direct_evidence(self):
        from memory.memory_manager import MemoryManager

        candidate = {
            "confidence": 0.7,
            "importance": 0.5,
            "occurrence_count": 1,
            "source_kinds": '["PRIVATE_DIRECT"]',
        }
        ok, reason = MemoryManager._decide_promotion(candidate)
        assert ok and "直接对话" in reason

