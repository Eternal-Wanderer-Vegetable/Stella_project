# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""调度严格门控（can_speak_for_scheduled / get_runtime_state_strict）的基线。

钉住三件事：
1. 安全闸与交互版 can_speak 同源（静音/睡眠/冷却全保留）；
2. 唯一豁免是新消息门槛，且静音读取失败 fail closed；
3. 交互版 can_speak 的既有语义（含 fail-open）完全不变。
"""

from __future__ import annotations

import sqlite3

import pytest

from memory import proactive_gate as gate
from memory import proactive_state


@pytest.fixture(autouse=True)
def _clean_gate_state():
    gate.reset_state()
    yield
    gate.reset_state()


class _FakeProactive:
    def __init__(self, *, in_cooldown=False, enough=True):
        self._in_cooldown = in_cooldown
        self._enough = enough

    def in_cooldown(self, group_id):
        return self._in_cooldown

    def has_enough_new_messages(self, group_id):
        return self._enough

    def messages_since_spoke(self, group_id):
        return 0


@pytest.fixture()
def permissive_env(monkeypatch):
    """除被测条件外全部放行的环境。"""
    monkeypatch.setattr(gate, "PROACTIVE_ENABLED", True)
    monkeypatch.setattr(gate, "PROACTIVE_RUNTIME_TOGGLE_ENABLED", True)
    monkeypatch.setattr(gate, "is_sleeping", lambda: False)
    monkeypatch.setattr(gate, "in_wakeup_grace", lambda group_id: False)
    fake = _FakeProactive()
    monkeypatch.setattr(gate, "get_proactive", lambda: fake)
    monkeypatch.setattr(
        gate, "get_runtime_state_strict", lambda group_id: {"proactive_muted": False}
    )
    return fake


def test_scheduled_gate_allows_when_all_gates_pass(permissive_env):
    allowed, reason = gate.can_speak_for_scheduled(12345)
    assert allowed, reason


def test_scheduled_gate_ignores_new_message_heuristic(permissive_env, monkeypatch):
    """群里不热闹（新消息门槛不过）不影响预约任务——这是唯一的豁免。"""
    permissive_env._enough = False
    allowed, _ = gate.can_speak_for_scheduled(12345)
    assert allowed
    # 对照：交互版会被同一条门槛拦下
    interactive_allowed, _ = gate.can_speak(12345, "join")
    assert not interactive_allowed


@pytest.mark.parametrize(
    ("mutate", "expected_fragment"),
    [
        (lambda m: m.setattr(gate, "PROACTIVE_ENABLED", False), "总开关"),
        (lambda m: m.setattr(gate, "is_sleeping", lambda: True), "睡眠"),
        (lambda m: m.setattr(gate, "in_wakeup_grace", lambda gid: True), "缓冲"),
        (
            lambda m: m.setattr(
                gate, "get_proactive", lambda: _FakeProactive(in_cooldown=True)
            ),
            "冷却",
        ),
        (
            lambda m: m.setattr(
                gate,
                "get_runtime_state_strict",
                lambda gid: {"proactive_muted": True},
            ),
            "临时关闭",
        ),
    ],
)
def test_scheduled_gate_keeps_safety_gates(permissive_env, monkeypatch, mutate, expected_fragment):
    mutate(monkeypatch)
    allowed, reason = gate.can_speak_for_scheduled(12345)
    assert not allowed
    assert expected_fragment in reason


def test_scheduled_gate_fails_closed_on_state_read_error(permissive_env, monkeypatch):
    """策略读取失败 → 拒绝（fail closed），与交互版的 fail-open 相反。"""
    monkeypatch.setattr(gate, "get_runtime_state_strict", lambda gid: None)
    allowed, reason = gate.can_speak_for_scheduled(12345)
    assert not allowed
    assert "fail closed" in reason


def test_interactive_can_speak_contract_unchanged(permissive_env, monkeypatch):
    """交互版 fail-open 与新消息门槛行为不被本特性改动。"""
    monkeypatch.setattr(
        gate, "get_runtime_state", lambda gid: {"proactive_muted": False}
    )
    allowed, _ = gate.can_speak(12345, "join")
    assert allowed  # fail-open：状态读得到、全部放行


# ── get_runtime_state_strict 的存储行为 ──────────────

def test_strict_state_reads_persisted_mute(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", db)
    proactive_state.set_proactive_muted(12345, True, operator_id=99)
    state = proactive_state.get_runtime_state_strict(12345)
    assert state is not None and state["proactive_muted"] is True
    assert state["muted_by"] == "99"


def test_strict_state_returns_none_on_broken_db(tmp_path, monkeypatch):
    """库坏掉（这里是目录路径）→ None，调用方 fail closed；不抛异常。"""
    monkeypatch.setattr(proactive_state, "DB_PATH", tmp_path / "no-such-dir" / "x.db")
    # set_proactive_muted 建目录的行为不存在：直接读
    state = proactive_state.get_runtime_state_strict(12345)
    assert state is None


def test_strict_state_missing_row_returns_defaults(tmp_path, monkeypatch):
    db = tmp_path / "memory.db"
    db.touch()
    monkeypatch.setattr(proactive_state, "DB_PATH", db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE group_runtime_state (group_id TEXT PRIMARY KEY, proactive_muted INTEGER, "
        "muted_by TEXT, muted_at TEXT, last_sleep_announce_date TEXT, "
        "last_wakeup_announce_date TEXT, updated_at TEXT)"
    )
    conn.commit()
    conn.close()
    state = proactive_state.get_runtime_state_strict(12345)
    assert state == {
        "proactive_muted": False,
        "muted_by": "",
        "muted_at": None,
        "last_sleep_announce_date": "",
        "last_wakeup_announce_date": "",
    }
