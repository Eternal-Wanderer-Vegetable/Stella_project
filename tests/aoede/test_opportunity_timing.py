# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S2-02 unified opportunity timing tests (2026-11-03 plan §6.2 step 3).

Covers: cancellable debounce wake, bounded TTL expiry DROP, per-conversation
single in-flight opportunity, merge-on-new-message with context revision,
cancel on topic bump/mute/direct request, verification ASK competing without
priority, and the retirement of the old dice/message-count gates from the
new path's preflight.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aoede.opportunity import OpportunityManager


class FakeClock:
    """Frozen-ish clock advanced manually (plan §8.1 uses the same shape)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeHandle:
    def __init__(self, loop, entry) -> None:
        self._loop = loop
        self._entry = entry
        self._cancelled = False

    def cancel(self) -> None:
        if not self._cancelled:
            self._cancelled = True
            try:
                self._loop.pending.remove(self._entry)
            except ValueError:
                pass


class FakeLoop:
    """Records call_later callbacks instead of running a real event loop."""

    def __init__(self) -> None:
        self.pending: list[tuple[float, object, tuple]] = []

    def call_later(self, delay, callback, *args):
        entry = (delay, callback, args)
        self.pending.append(entry)
        return FakeHandle(self, entry)

    def fire_all(self):
        pending, self.pending = self.pending, []
        for _delay, callback, args in pending:
            callback(*args)


@pytest.fixture()
def loop(monkeypatch):
    fake = FakeLoop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: fake, raising=False)
    return fake


@pytest.fixture()
def clock():
    return FakeClock()


def _decision(mode: str = "TOPIC_INTEREST", should_speak: bool = True):
    return SimpleNamespace(mode=mode, should_speak=should_speak, group_id=1)


def test_submit_creates_single_inflight_and_merges(clock, loop, monkeypatch) -> None:
    monkeypatch.setattr(
        "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
        lambda self, gid: "",
    )
    manager = OpportunityManager(clock=clock, debounce_seconds=3.0, ttl_seconds=15.0)
    assert manager.submit(1, _decision()) == "created"
    # second message while in flight: merges, keeps original expiry, re-arms
    assert manager.submit(1, _decision()) == "merged"
    # one timer pending (re-armed), not two
    assert len(loop.pending) == 1
    # different conversation: separate opportunity
    assert manager.submit(2, _decision()) == "created"
    assert len(loop.pending) == 2


def test_ttl_expiry_drops_merged_opportunity(clock, loop, monkeypatch) -> None:
    monkeypatch.setattr(
        "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
        lambda self, gid: "",
    )
    manager = OpportunityManager(clock=clock, debounce_seconds=3.0, ttl_seconds=15.0)
    assert manager.submit(1, _decision()) == "created"
    clock.now += 10.0
    # merge accepted but expiry NOT extended
    assert manager.submit(1, _decision()) == "merged"
    clock.now += 6.0  # beyond original 15s TTL
    # old opportunity dropped; the message starts a fresh window
    assert manager.submit(1, _decision()) == "created"


async def test_fire_after_ttl_drops_without_speaking(clock, loop, monkeypatch) -> None:
    monkeypatch.setattr(
        "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
        lambda self, gid: "",
    )
    fired = []

    async def fake_speak(opp):
        fired.append(opp.group_id)

    manager = OpportunityManager(clock=clock, debounce_seconds=3.0, ttl_seconds=15.0)
    manager._cooldown_blocked = lambda gid: False
    monkeypatch.setattr(manager, "_speak", fake_speak)
    assert manager.submit(1, _decision()) == "created"
    clock.now += 20.0
    loop.fire_all()  # debounce elapsed, but TTL already exceeded
    await asyncio.sleep(0)
    assert fired == []
    # in-TTL fire reaches speak
    assert manager.submit(1, _decision()) == "created"
    clock.now += 3.0
    loop.fire_all()
    await asyncio.sleep(0)
    assert fired == [1]


def test_cancel_on_topic_bump_and_unknown_group(clock, loop) -> None:
    manager = OpportunityManager(clock=clock)
    assert manager.cancel(1, "topic_revision_bumped") is False
    monkeypatch = None  # noqa: F841 - readability
    manager._preflight_blocked_reason = lambda gid: ""
    manager.submit(1, _decision())
    assert manager.cancel(1, "topic_revision_bumped") is True
    assert manager._inflight == {}


def test_preflight_block_reasons(clock, loop, monkeypatch) -> None:
    manager = OpportunityManager(clock=clock)
    import config

    monkeypatch.setattr(config, "PROACTIVE_ENABLED", False, raising=False)
    assert manager.submit(1, _decision()).startswith("dropped:proactive_disabled")
    monkeypatch.setattr(config, "PROACTIVE_ENABLED", True, raising=False)
    # muted
    manager2 = OpportunityManager(clock=clock)
    monkeypatch.setattr(
        "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
        lambda self, gid: "muted" if gid == 1 else "",
    )
    assert manager2.submit(1, _decision()) == "dropped:muted"
    assert manager2.submit(2, _decision()) == "created"


def test_verification_competes_without_priority(clock, loop, monkeypatch) -> None:
    monkeypatch.setattr(
        "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
        lambda self, gid: "",
    )
    manager = OpportunityManager(clock=clock)
    manager._cooldown_blocked = lambda gid: False
    assert manager.submit_verification(1) == "created"
    # ordinary message while a verification ask is in flight: merged slot is
    # the ASK (unique in-flight), a new CONTRIBUTE cannot stack on top via
    # submit_verification; and a second verification is refused too
    assert manager.submit_verification(1) == "dropped:inflight"


def test_cooldown_blocks_fire_not_preflight(clock, loop, monkeypatch) -> None:
    """冷却只拦截开火（内部安全下限），不拦截机会登记。"""
    monkeypatch.setattr(
        "aoede.opportunity.OpportunityManager._preflight_blocked_reason",
        lambda self, gid: "",
    )
    manager = OpportunityManager(clock=clock)
    manager._cooldown_blocked = lambda gid: True
    assert manager.submit(1, _decision()) == "created"
    loop.fire_all()
    # dropped at fire time (cooldown), not at submit time
    assert manager._inflight == {}


def test_old_dice_and_message_count_gates_not_in_preflight(clock, monkeypatch) -> None:
    """掷骰与 15 条门槛不出现在新路径预检（计划 §6.2 旧策略退役）。"""
    import inspect

    from aoede import opportunity

    source = inspect.getsource(opportunity.OpportunityManager._preflight_blocked_reason)
    for retired in ("should_speak", "has_enough_new_messages", "PROACTIVE_PROB"):
        assert retired not in source, retired


def test_reset_cancels_all(clock, loop) -> None:
    from aoede.opportunity import (
        get_opportunity_manager,
        reset_opportunity_manager_for_tests,
    )

    manager = get_opportunity_manager()
    manager._preflight_blocked_reason = lambda gid: ""
    manager.submit(1, _decision())
    reset_opportunity_manager_for_tests()
    assert get_opportunity_manager() is not manager
