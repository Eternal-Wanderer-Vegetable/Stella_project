# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""主动 @ 流程中可独立验证的部分。

大部分用例不启动 NoneBot；少量网关回归用例用最小替身验证发送、记账与退避
之间的边界，避免把自然承接失败变成用户可见的突兀发言。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from memory.proactive import ProactiveController
from memory.proactive_prompt import PROACTIVE_SKIP_MARKER
from memory.proactive_state import get_state, record_at, record_reply_result
from memory.proactive_target import ProactiveTarget


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "proactive.db"
    path.touch()
    monkeypatch.setattr("memory.proactive_state.DB_PATH", path)
    monkeypatch.setattr("memory.schema.DB_PATH", path)
    return path


@pytest.fixture(scope="module")
def ai_gateway_module():
    """加载网关模块一次，避免在每个用例里重复注册 NoneBot 处理器。"""
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


class _FakeProactive:
    def __init__(self, *, should_speak=True):
        self.should_speak_result = should_speak
        self.marked = []
        self.recorded = []

    def recently_spoken(self, group_id, lines):
        return False

    def mark_spoke(self, group_id):
        self.marked.append(group_id)

    def record_spoken(self, group_id, lines):
        self.recorded.append((group_id, lines))

    def should_speak(self, group_id):
        return self.should_speak_result


class _FakeTask:
    def add_done_callback(self, callback):
        callback(self)


class _FakeParticipation:
    def __init__(self):
        self.notes = []

    def note_stella_spoke(self, group_id, trigger):
        self.notes.append((group_id, trigger))


def test_record_at_counts_and_persists(db):
    """发出即计数，且落库后可跨实例读取。"""
    record_at(1, 1001, topic="最近在玩什么游戏")
    state = get_state(1, 1001)
    assert state["at_count_today"] == 1
    assert state["last_asked_topic"] == "最近在玩什么游戏"
    assert state["last_at_at"] is not None

    record_at(1, 1001, topic="平时喜欢吃什么")
    assert get_state(1, 1001)["at_count_today"] == 2


def test_no_reply_accumulates_then_resets(db):
    """连续无回应累计，一次回应即归零（退避可恢复）。"""
    record_at(1, 1001)
    record_reply_result(1, 1001, replied=False)
    assert get_state(1, 1001)["consecutive_no_reply"] == 1

    record_reply_result(1, 1001, replied=False)
    assert get_state(1, 1001)["consecutive_no_reply"] == 2

    record_reply_result(1, 1001, replied=True)
    assert get_state(1, 1001)["consecutive_no_reply"] == 0


def test_quota_is_per_user(db):
    """配额按用户独立，不互相影响。"""
    record_at(1, 1001)
    record_at(1, 1001)
    record_at(1, 1002)
    assert get_state(1, 1001)["at_count_today"] == 2
    assert get_state(1, 1002)["at_count_today"] == 1


def test_last_spoke_ts_tracks_any_message():
    """last_spoke_ts 记的是「发过任意消息」，不是「回应了 Bot」。

    回应检测已改用 last_tome_ts（见 tests/test_reply_detection.py）：这里只保留
    活跃度时间戳本身的语义断言，免得再有人把它当成回应判据。
    """
    # 用独立实例，不污染全局单例（真实 monotonic 值会干扰其他用例的假时钟）
    proactive = ProactiveController()

    assert proactive.last_spoke_ts(1, 1001) is None

    proactive.record_message(1, 1001)
    assert proactive.last_spoke_ts(1, 1001) > 0.0
    # 反向断言：发言不得被记成「对 Bot 说话」
    assert proactive.last_tome_ts(1, 1001) is None


@pytest.mark.asyncio
async def test_proactive_at_skip_has_no_visible_or_accounting_side_effects(
    ai_gateway_module, monkeypatch
):
    """没有自然承接时，skip 不得发送、记账、统计或启动回应检测。"""
    gateway = ai_gateway_module
    bot = _FakeBot()
    proactive = _FakeProactive()
    target = ProactiveTarget(
        user_id=1001,
        mode="coldstart",
        topic="最近在玩什么游戏",
    )
    participation = Mock()
    record_at_mock = Mock()
    record_bot_lines = AsyncMock()
    create_task = Mock(side_effect=AssertionError("skip 不得启动回应检测"))

    monkeypatch.setattr(gateway, "can_speak", lambda group_id, kind: (True, ""))
    monkeypatch.setattr(gateway, "pick_target", lambda group_id, exclude_user_ids: target)
    monkeypatch.setattr(gateway, "_resolve_nickname", AsyncMock(return_value="小明"))

    async def fake_run(ctx):
        ctx.lines = [PROACTIVE_SKIP_MARKER]
        return ctx

    monkeypatch.setattr(gateway.pipeline, "run", fake_run)
    monkeypatch.setattr(gateway, "get_proactive", lambda: proactive)
    monkeypatch.setattr(gateway, "get_participation_manager", participation)
    monkeypatch.setattr(gateway, "record_at", record_at_mock)
    monkeypatch.setattr(gateway, "_record_bot_lines", record_bot_lines)
    monkeypatch.setattr(gateway.asyncio, "create_task", create_task)

    assert await gateway._proactive_at_user(bot, 1) is False
    bot.send_group_msg.assert_not_awaited()
    assert proactive.marked == []
    assert proactive.recorded == []
    participation.assert_not_called()
    record_at_mock.assert_not_called()
    record_bot_lines.assert_not_awaited()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_proactive_at_normal_output_still_sends_and_records(
    ai_gateway_module, monkeypatch
):
    """正常生成结果仍沿用原有发送、主动发言统计与 @ 配额记账。"""
    gateway = ai_gateway_module
    bot = _FakeBot()
    proactive = _FakeProactive()
    participation = _FakeParticipation()
    target = ProactiveTarget(
        user_id=1001,
        mode="coldstart",
        topic="最近在玩什么游戏",
    )
    record_at_mock = Mock()
    record_bot_lines = AsyncMock()
    expression_sent = Mock()
    task = _FakeTask()
    create_task = Mock()

    def fake_create_task(coro):
        coro.close()
        return task

    monkeypatch.setattr(gateway, "can_speak", lambda group_id, kind: (True, ""))
    monkeypatch.setattr(gateway, "pick_target", lambda group_id, exclude_user_ids: target)
    monkeypatch.setattr(gateway, "_resolve_nickname", AsyncMock(return_value="小明"))

    async def fake_run(ctx):
        ctx.lines = ["你最近在玩什么游戏？"]
        return ctx

    monkeypatch.setattr(gateway.pipeline, "run", fake_run)
    monkeypatch.setattr(gateway, "get_proactive", lambda: proactive)
    monkeypatch.setattr(gateway, "get_participation_manager", lambda: participation)
    monkeypatch.setattr(gateway, "record_at", record_at_mock)
    monkeypatch.setattr(gateway, "_record_bot_lines", record_bot_lines)
    monkeypatch.setattr(gateway.expression_learning, "on_reply_sent", expression_sent)
    monkeypatch.setattr(gateway, "schedule_compact", Mock())
    create_task.side_effect = fake_create_task
    monkeypatch.setattr(gateway.asyncio, "create_task", create_task)

    assert await gateway._proactive_at_user(bot, 1) is True
    bot.send_group_msg.assert_awaited_once()
    assert proactive.marked == [1]
    assert proactive.recorded == [(1, ["你最近在玩什么游戏？"])]
    assert participation.notes == [(1, "proactive")]
    record_at_mock.assert_called_once_with(
        1,
        1001,
        topic="最近在玩什么游戏",
        candidate_id="",
    )
    record_bot_lines.assert_awaited_once()
    expression_sent.assert_called_once()
    create_task.assert_called_once()


@pytest.mark.asyncio
async def test_proactive_group_skip_finishes_gate_without_side_effects(
    ai_gateway_module, monkeypatch
):
    """群级主动插话收到 skip 时，必须释放 ReplyGate 且不留下发送痕迹。"""
    gateway = ai_gateway_module
    bot = _FakeBot()
    proactive = _FakeProactive()
    participation = Mock()
    record_bot_lines = AsyncMock()
    gate = Mock()
    gate.evaluate.return_value = SimpleNamespace(
        allowed=True,
        path="proactive",
        score=0.5,
        reasons=("local_gate",),
    )
    consolidator = SimpleNamespace(
        has_new_messages_to_consolidate=lambda group_id, threshold: 0
    )

    monkeypatch.setattr(gateway, "can_speak", lambda group_id, kind: (True, ""))
    monkeypatch.setattr(gateway, "get_proactive", lambda: proactive)
    monkeypatch.setattr(gateway, "get_reply_gate", lambda: gate)
    monkeypatch.setattr(gateway, "get_consolidator", lambda: consolidator)
    monkeypatch.setattr(gateway, "get_participation_manager", participation)
    monkeypatch.setattr(gateway, "_record_bot_lines", record_bot_lines)

    async def fake_run(ctx):
        ctx.lines = [PROACTIVE_SKIP_MARKER]
        return ctx

    monkeypatch.setattr(gateway.pipeline, "run", fake_run)

    await gateway._proactive_speak_for_group(bot, 1, skip_dice=True)

    gate.start.assert_called_once_with(1, proactive=True)
    gate.finish.assert_called_once_with(1, waiting=False)
    bot.send_group_msg.assert_not_awaited()
    assert proactive.marked == []
    assert proactive.recorded == []
    participation.assert_not_called()
    record_bot_lines.assert_not_awaited()
