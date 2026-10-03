# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M6 验收（native）：主动 @ / 主动插话经 facade 执行（确定性集成，stub 平台发送）。

与 tests/test_proactive_at_flow.py 的差别：那个钉的是 legacy 接缝
（``pipeline.run``），本文件钉 native 接缝（``_run_turn_via_engine`` → facade），
证明 M6 之后主动发言的真实执行路径。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
import runtime_harness as harness


@pytest.fixture
def ai_gateway_module():
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()

    from stella_project.plugins.bot_main import ai_gateway

    return ai_gateway


class _FakeBot:
    self_id = "999"

    def __init__(self):
        self.send_group_msg = AsyncMock()


class _FakeTask:
    """替身 task：吞掉协程(不执行)、不触发回调，仅满足 add_done_callback 契约。"""

    def close(self):
        pass

    def add_done_callback(self, callback):
        pass

    def cancel(self):
        pass


class _FakeProactive:
    def __init__(self):
        self.marked = []
        self.recorded = []
        self.skipped = []

    def recently_spoken(self, group_id, lines):
        return False

    def mark_spoke(self, group_id):
        self.marked.append(group_id)

    def record_spoken(self, group_id, lines):
        self.recorded.append((group_id, lines))

    def mark_proactive_skip(self, group_id, user_id, subject):
        self.skipped.append((group_id, user_id, subject))


async def test_proactive_at_goes_through_native_facade(ai_gateway_module, monkeypatch, tmp_path):
    gateway = ai_gateway_module
    h = harness.RuntimeHarness(tmp_path)
    await h.start()
    _orig_provider = h.facade._provider

    async def _spy_provider(key, prompt):
        try:
            r = await _orig_provider(key, prompt)
            print(f"[spy-provider] ok: {r[:40]!r}")
            return r
        except BaseException:
            import traceback
            traceback.print_exc()
            raise

    h.facade._provider = _spy_provider
    bot = _FakeBot()
    proactive = _FakeProactive()
    from memory.proactive_target import ProactiveTarget

    target = ProactiveTarget(user_id=1001, candidate_id="cand-9", candidate_content="他住在上海")

    seen: dict = {}

    async def engine(session_key, ctx, **kw):
        seen["key"] = session_key
        seen["intent"] = ctx.intent
        out = await h.facade.submit_turn(session_key, gateway.pipeline, ctx, **kw)
        seen["reply"] = out.reply
        seen["wait"] = bool(getattr(out, "planner_wait", False))
        seen["prompted"] = bool(getattr(out, "prompt_log", ""))
        return out

    monkeypatch.setattr(gateway, "_run_turn_via_engine", engine)
    monkeypatch.setattr(gateway, "can_speak", lambda group_id, kind: (True, ""))
    monkeypatch.setattr(gateway, "pick_target", lambda group_id, exclude_user_ids: target)
    monkeypatch.setattr(gateway, "_resolve_nickname", AsyncMock(return_value="小明"))
    monkeypatch.setattr(gateway, "get_proactive", lambda: proactive)
    monkeypatch.setattr(gateway, "get_participation_manager", Mock())
    monkeypatch.setattr(gateway, "record_at", Mock())
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    monkeypatch.setattr(gateway, "_check_reply_later", AsyncMock())
    try:
        await gateway._proactive_at_user(bot, 1)
    finally:
        await h.stop()

    # 走了 native facade：同会话键、proactive_at 意图、一次 provider 调用
    assert seen.get("key") == "qq:1"
    assert seen.get("intent") == "proactive_at"
    assert len(h.provider_calls) == 1, f"seen={seen} store={[r['state'] for r in h.store_lines()]}"
    # 发送：@ + 正文（无引用段），且已记账
    bot.send_group_msg.assert_awaited()
    assert proactive.recorded and proactive.marked == [1]


async def test_proactive_join_goes_through_native_facade(ai_gateway_module, monkeypatch, tmp_path):
    gateway = ai_gateway_module
    h = harness.RuntimeHarness(tmp_path)
    await h.start()
    bot = _FakeBot()
    proactive = _FakeProactive()

    seen: dict = {}

    async def engine(session_key, ctx, **kw):
        seen["key"] = session_key
        seen["intent"] = ctx.intent
        return await h.facade.submit_turn(session_key, gateway.pipeline, ctx, **kw)

    monkeypatch.setattr(gateway, "_run_turn_via_engine", engine)
    monkeypatch.setattr(gateway, "can_speak", lambda group_id, kind: (True, ""))

    gate = Mock()
    gate.evaluate = Mock(return_value=Mock(allowed=True, path="proactive", score=0.9, reasons=()))
    gate.start = Mock()
    gate.finish = Mock()
    monkeypatch.setattr(gateway, "get_reply_gate", lambda: gate)
    monkeypatch.setattr(gateway, "get_proactive", lambda: proactive)
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    monkeypatch.setattr(gateway, "_check_reply_later", AsyncMock())
    try:
        await gateway._proactive_speak_for_group(bot, 1, skip_dice=True)
    finally:
        await h.stop()

    assert seen.get("key") == "qq:1"
    assert seen.get("intent") == "proactive_join"
    assert len(h.provider_calls) == 1
    bot.send_group_msg.assert_awaited()
