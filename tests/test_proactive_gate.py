# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言准入闸门的行为基线。

睡眠判定必须与运行时刻无关（注入固定时间），否则测试会在特定时段随机失败。
"""
from datetime import datetime

import pytest

from memory import proactive_gate as gate


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """每个用例前清空进程内状态，并默认开启睡眠功能。"""
    gate.reset_state()
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_ENABLED", True)
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_START", "23:30")
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_END", "07:30")
    yield
    gate.reset_state()


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 15, hour, minute)


# ── 睡眠时段判定 ──────────────────────────────────────

def test_sleeping_across_midnight():
    """跨午夜区间：23:30–07:30。"""
    assert gate.is_sleeping(_at(23, 40))
    assert gate.is_sleeping(_at(0, 30))
    assert gate.is_sleeping(_at(6, 0))
    assert not gate.is_sleeping(_at(7, 30))   # 终点不含
    assert not gate.is_sleeping(_at(12, 0))
    assert not gate.is_sleeping(_at(23, 0))


def test_sleeping_same_day_range(monkeypatch):
    """非跨午夜区间：01:00–05:00。"""
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_START", "01:00")
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_END", "05:00")
    assert gate.is_sleeping(_at(3, 0))
    assert not gate.is_sleeping(_at(0, 30))
    assert not gate.is_sleeping(_at(5, 0))


def test_sleeping_disabled(monkeypatch):
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_ENABLED", False)
    assert not gate.is_sleeping(_at(3, 0))


def test_equal_start_end_never_sleeps(monkeypatch):
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_START", "23:00")
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_END", "23:00")
    assert not gate.is_sleeping(_at(23, 0))


def test_malformed_config_falls_back(monkeypatch):
    """格式非法时回退默认值（23:30–07:30），不抛异常。"""
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_START", "不是时间")
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_END", "")
    assert gate.is_sleeping(_at(3, 0))
    assert not gate.is_sleeping(_at(12, 0))


# ── 状态跃变与醒来缓冲 ────────────────────────────────

def test_first_call_is_not_a_transition():
    """进程刚启动的首次判定不算跃变——否则每次重启都会播报。"""
    assert gate.note_sleep_transition(1, True) is None
    assert gate.note_sleep_transition(1, True) is None


def test_transition_detects_both_directions():
    gate.note_sleep_transition(1, False)
    assert gate.note_sleep_transition(1, True) == "sleep"
    assert gate.note_sleep_transition(1, True) is None
    assert gate.note_sleep_transition(1, False) == "wakeup"


def test_transitions_are_per_group():
    gate.note_sleep_transition(1, False)
    gate.note_sleep_transition(2, False)
    assert gate.note_sleep_transition(1, True) == "sleep"
    assert gate.note_sleep_transition(2, True) == "sleep"


def test_wakeup_grace_active_then_expires(monkeypatch):
    gate.note_sleep_transition(1, True)
    gate.note_sleep_transition(1, False)          # 触发苏醒，记录时刻
    assert gate.in_wakeup_grace(1)

    monkeypatch.setattr(gate, "PROACTIVE_WAKEUP_GRACE_SECONDS", 0.0)
    assert not gate.in_wakeup_grace(1)


def test_no_grace_without_wakeup():
    assert not gate.in_wakeup_grace(999)


# ── can_speak 的短路顺序 ──────────────────────────────

@pytest.fixture
def _allow_all(monkeypatch):
    """把除被测条件外的所有闸门都设为放行。"""
    monkeypatch.setattr(gate, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(gate, "PROACTIVE_AT_ENABLED", True)
    monkeypatch.setattr(gate, "PROACTIVE_RUNTIME_TOGGLE_ENABLED", False)
    monkeypatch.setattr(gate, "PROACTIVE_SLEEP_ENABLED", False)

    class _FakeProactive:
        def in_cooldown(self, group_id):
            return False

        def has_enough_new_messages(self, group_id):
            return True

        def messages_since_spoke(self, group_id):
            return 99

    monkeypatch.setattr(gate, "get_proactive", lambda: _FakeProactive())


def test_can_speak_allows_when_all_clear(_allow_all):
    for kind in ("at", "join"):
        ok, reason = gate.can_speak(1, kind)
        assert ok, reason


def test_master_switch_blocks_both(_allow_all, monkeypatch):
    monkeypatch.setattr(gate, "PROACTIVE_ENABLED", False)
    for kind in ("at", "join"):
        ok, reason = gate.can_speak(1, kind)
        assert not ok and "总开关" in reason


def test_at_switch_blocks_only_at(_allow_all, monkeypatch):
    monkeypatch.setattr(gate, "PROACTIVE_AT_ENABLED", False)
    ok, reason = gate.can_speak(1, "at")
    assert not ok and "主动 @" in reason
    assert gate.can_speak(1, "join")[0]


def test_mute_blocks_both(_allow_all, monkeypatch):
    monkeypatch.setattr(gate, "PROACTIVE_RUNTIME_TOGGLE_ENABLED", True)
    monkeypatch.setattr(gate, "get_runtime_state", lambda gid: {"proactive_muted": True})
    for kind in ("at", "join"):
        ok, reason = gate.can_speak(1, kind)
        assert not ok and "管理员" in reason


def test_sleep_blocks_both(_allow_all, monkeypatch):
    monkeypatch.setattr(gate, "is_sleeping", lambda now=None: True)
    for kind in ("at", "join"):
        ok, reason = gate.can_speak(1, kind)
        assert not ok and "睡眠" in reason


def test_wakeup_grace_blocks(_allow_all, monkeypatch):
    monkeypatch.setattr(gate, "in_wakeup_grace", lambda gid: True)
    ok, reason = gate.can_speak(1, "join")
    assert not ok and "缓冲" in reason


def test_cooldown_blocks(_allow_all, monkeypatch):
    class _Cooling:
        def in_cooldown(self, group_id):
            return True

        def has_enough_new_messages(self, group_id):
            return True

        def messages_since_spoke(self, group_id):
            return 99

    monkeypatch.setattr(gate, "get_proactive", lambda: _Cooling())
    ok, reason = gate.can_speak(1, "join")
    assert not ok and "冷却" in reason


def test_message_threshold_blocks(_allow_all, monkeypatch):
    class _NotEnough:
        def in_cooldown(self, group_id):
            return False

        def has_enough_new_messages(self, group_id):
            return False

        def messages_since_spoke(self, group_id):
            return 3

    monkeypatch.setattr(gate, "get_proactive", lambda: _NotEnough())
    ok, reason = gate.can_speak(1, "join")
    assert not ok and "新消息" in reason
