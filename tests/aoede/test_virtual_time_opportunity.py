# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Aoede opportunity replay with shared virtual timers and monotonic time."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aoede.opportunity import (
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_TTL_SECONDS,
    OpportunityManager,
)
from proactive_eval.b03 import simulate_arrival_interval
from proactive_eval.virtual_time import VirtualTimeDriver


@pytest.mark.parametrize(
    ("interval", "expected_created", "expected_merged", "expected_sends"),
    [(1.0, 1, 9, 1), (3.0, 10, 0, 10), (10.0, 10, 0, 10)],
)
async def test_opportunity_manager_replays_synthetic_turn_intervals(
    interval: float, expected_created: int, expected_merged: int, expected_sends: int
) -> None:
    result = await simulate_arrival_interval(interval)
    assert result["interval_source"] == "synthetic"
    assert result["created"] == expected_created
    assert result["merged"] == expected_merged
    assert result["speak_actions"] == expected_sends
    if interval == DEFAULT_DEBOUNCE_SECONDS:
        # A due timer fires before a message at the same virtual timestamp.
        assert result["timer_fires_after_submitted_turn_count"] == list(range(1, 11))


async def test_opportunity_ttl_is_not_extended_by_merges() -> None:
    driver = VirtualTimeDriver()
    manager = OpportunityManager(
        clock=driver.monotonic,
        debounce_seconds=DEFAULT_DEBOUNCE_SECONDS,
        ttl_seconds=DEFAULT_TTL_SECONDS,
    )
    manager._preflight_blocked_reason = lambda _group_id: ""
    manager._cooldown_blocked = lambda _group_id: False
    decision = SimpleNamespace(mode="TOPIC_INTEREST", should_speak=True, group_id=1)
    sends: list[int] = []

    async def record_speak(opportunity) -> None:
        if manager._inflight.get(opportunity.group_id) is opportunity:
            manager._inflight.pop(opportunity.group_id, None)
        sends.append(opportunity.group_id)

    manager._speak = record_speak
    with patch.object(asyncio, "get_running_loop", return_value=driver):
        assert manager.submit(1, decision) == "created"
        first = manager._inflight[1]
        for _ in range(int(DEFAULT_TTL_SECONDS) - 1):
            await driver.advance(1)
            assert manager.submit(1, decision) == "merged"
        assert first.expires_at == DEFAULT_TTL_SECONDS
        await driver.advance(1)
        assert manager.submit(1, decision) == "created"
        assert manager._inflight[1] is not first
        await driver.advance(DEFAULT_DEBOUNCE_SECONDS)
    assert sends == [1]


async def test_lost_opportunity_timer_can_be_rearmed() -> None:
    driver = VirtualTimeDriver()
    manager = OpportunityManager(clock=driver.monotonic)
    manager._preflight_blocked_reason = lambda _group_id: ""
    manager._cooldown_blocked = lambda _group_id: False
    decision = SimpleNamespace(mode="TOPIC_INTEREST", should_speak=True, group_id=1)
    sends: list[int] = []

    async def record_speak(opportunity) -> None:
        if manager._inflight.get(opportunity.group_id) is opportunity:
            manager._inflight.pop(opportunity.group_id, None)
        sends.append(opportunity.group_id)

    manager._speak = record_speak
    with patch.object(asyncio, "get_running_loop", return_value=driver):
        manager.submit(1, decision)
        opportunity = manager._inflight[1]
        opportunity.timer.cancel()
        opportunity.timer = None
        assert manager.recover_group(1) == "rearmed"
        await driver.advance(DEFAULT_DEBOUNCE_SECONDS)
    assert sends == [1]
