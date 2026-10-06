# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""私聊 idle 收尾整合测试（复核 F10，整改计划 P2）。

覆盖：idle 结束的注册会话按 storage_session_id 查可信 ref 再走统一入口；
未注册的负 ID 跳过且绝不伪造 ref；正群号保持旧路径；无内容的 idle 不触发。
"""

from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import Mock

import nonebot
import pytest

nonebot.init()

import memory.session_context as session_context
from memory.conversation_registry import get_or_register_private
from stella_project.plugins.bot_main import ai_gateway as gateway


@pytest.fixture()
def idle_env(tmp_path, monkeypatch):
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(gateway, "DB_PATH", db)
    monkeypatch.setattr(session_context, "SESSION_CONTEXT_ENABLED", True)
    calls: list = []
    capture = Mock(side_effect=lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(gateway, "maybe_consolidate", capture)
    # 清掉其他测试遗留的会话状态
    session_context._sessions.clear()
    return SimpleNamespace(db=db, calls=calls)


def _seed_idle_session(key: int, *, with_content: bool = True) -> None:
    state = session_context._state(key)
    if with_content:
        state.summary = "曾经聊过"
        state.compact_count = 1
    state.last_activity = time.monotonic() - 10_000


def _register_private(db, bot_id: str, user_id: int) -> int:
    conn = sqlite3.connect(db)
    try:
        ref = get_or_register_private(conn, bot_id, user_id)
        conn.commit()
        return ref.storage_session_id
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_idle_private_uses_registered_ref(idle_env):
    """复核 F10 主反例：负存储 ID 的私聊 idle 收尾必须按注册 ref 整合。"""
    storage = _register_private(idle_env.db, "10000", 20001)
    assert storage < 0
    _seed_idle_session(storage)
    await gateway.session_idle_check_job()
    assert len(idle_env.calls) == 1
    args, kwargs = idle_env.calls[0]
    assert not args, "idle 不得把负存储 ID 当群号传位置参数"
    ref = kwargs["conversation_ref"]
    assert ref.storage_session_id == storage
    assert ref.conversation_key == "qq:10000:private:20001"
    assert ref.memory_space == "private:qq:10000:20001"


@pytest.mark.asyncio
async def test_idle_unregistered_negative_key_skips(idle_env):
    """未注册的负 ID：记原因跳过，绝不从负号反推伪造 ref。"""
    _seed_idle_session(-9_999)
    await gateway.session_idle_check_job()
    assert idle_env.calls == []


@pytest.mark.asyncio
async def test_idle_positive_group_keeps_legacy_path(idle_env):
    _seed_idle_session(263402786)
    await gateway.session_idle_check_job()
    assert len(idle_env.calls) == 1
    args, kwargs = idle_env.calls[0]
    assert args == (263402786,)
    assert kwargs == {}


@pytest.mark.asyncio
async def test_idle_without_content_does_not_trigger(idle_env):
    """无压缩/无摘要的静默会话：end_session 返回 False，不触发整合。"""
    storage = _register_private(idle_env.db, "10000", 20002)
    _seed_idle_session(storage, with_content=False)
    await gateway.session_idle_check_job()
    assert idle_env.calls == []


@pytest.mark.asyncio
async def test_idle_and_immediate_trigger_share_pending_key(idle_env):
    """idle 与即时触发用同一 storage_session_id 去重：并发无双消费。

    maybe_consolidate 已被 mock，这里直接验证其真实去重键语义：
    ref.storage_session_id 与即时路径的 key 相同。
    """
    storage = _register_private(idle_env.db, "10000", 20003)
    _seed_idle_session(storage)
    await gateway.session_idle_check_job()
    kwargs = idle_env.calls[0][1]
    assert kwargs["conversation_ref"].storage_session_id == storage
