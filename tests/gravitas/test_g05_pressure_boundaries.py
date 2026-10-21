# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import memory.pre_processors as pre_processors
from core.context import ChatContext
from gravitas.clock import ManualControlClock
from gravitas.config import GravitasMode, default_config, parse_config
from gravitas.controller import GravitasController
from gravitas.policy import (
    BacklogState,
    MemoryBacklogGuard,
    MemoryBacklogSnapshot,
    PressureState,
    ResourcePolicyState,
    ResourceSignals,
    admit_background,
    evaluate_pressure,
)


def test_existing_schema_v1_profiles_keep_loading_without_backlog_keys():
    example_path = (
        Path(__file__).resolve().parents[2] / "config" / "gravitas.example.toml"
    )
    text = example_path.read_text(encoding="utf-8")
    old_profile = "\n".join(
        line for line in text.splitlines() if not line.startswith("backlog_")
    )
    parsed = parse_config(old_profile)
    assert parsed.pressure.backlog_session_high_water == 500
    assert parsed.pressure.backlog_instance_low_water == 2500


def test_recovery_tokens_do_not_accumulate_into_a_burst():
    config = replace(default_config().pressure, normal_stable_seconds=500.0)
    state = ResourcePolicyState(
        state=PressureState.RECOVERING,
        normal_since=0.0,
        last_token_at=0.0,
        background_tokens=0,
    )
    low = ResourceSignals(queue_depth=0, oldest_wait_seconds=0.0)
    for now in (10.0, 60.0, 120.0):
        state = evaluate_pressure(
            state, low, config, now=now, background_token_limit=4
        ).next_state
        assert state.state is PressureState.RECOVERING
        assert state.background_tokens == 1


def test_aged_backend_requires_integrity_and_has_one_per_interval():
    state = ResourcePolicyState(
        state=PressureState.CONSTRAINED,
        last_aged_backend_at=10.0,
        background_tokens=0,
    )
    denied = admit_background(
        state,
        now=20.0,
        oldest_age_seconds=900.0,
        aged_after_seconds=600.0,
        token_interval_seconds=10.0,
        integrity_ok=False,
    )
    assert not denied.allowed
    assert denied.reason_code == "integrity_untrusted"
    assert denied.next_state == state

    first = admit_background(
        state,
        now=20.0,
        oldest_age_seconds=900.0,
        aged_after_seconds=600.0,
        token_interval_seconds=10.0,
        integrity_ok=True,
    )
    assert first.allowed
    assert first.reason_code == "aged_backend_share"
    assert first.next_state.last_aged_backend_at == 20.0
    too_soon = admit_background(
        first.next_state,
        now=29.0,
        oldest_age_seconds=900.0,
        aged_after_seconds=600.0,
        token_interval_seconds=10.0,
        integrity_ok=True,
    )
    assert not too_soon.allowed
    assert too_soon.reason_code == "aged_share_cooling"
    next_interval = admit_background(
        first.next_state,
        now=30.0,
        oldest_age_seconds=900.0,
        aged_after_seconds=600.0,
        token_interval_seconds=10.0,
        integrity_ok=True,
    )
    assert next_interval.allowed


def test_capture_backlog_uses_high_low_hysteresis_and_body_free_gap_ledger():
    config = default_config().pressure
    guard = MemoryBacklogGuard(config)
    low = MemoryBacklogSnapshot(100, 1000, 5.0, True)
    assert guard.evaluate(low, now=0.0, wall_time=1000.0).allowed

    high = MemoryBacklogSnapshot(500, 5000, 5.0, True)
    refused = guard.evaluate(high, now=1.0, wall_time=1001.0)
    assert not refused.allowed
    assert refused.state is BacklogState.CONSTRAINED
    guard.record_gap(refused.reason_code, wall_time=1001.0)

    below_low = MemoryBacklogSnapshot(100, 2000, 5.0, True)
    assert not guard.evaluate(below_low, now=2.0, wall_time=1002.0).allowed
    recovery = guard.evaluate(below_low, now=18.0, wall_time=1018.0)
    assert recovery.allowed
    assert recovery.state is BacklogState.RECOVERING
    assert guard.evaluate(high, now=19.0, wall_time=1019.0).state is BacklogState.CONSTRAINED

    assert not guard.evaluate(below_low, now=20.0, wall_time=1020.0).allowed
    assert guard.evaluate(below_low, now=36.0, wall_time=1036.0).state is BacklogState.RECOVERING
    normal = guard.evaluate(below_low, now=66.0, wall_time=1066.0)
    assert normal.allowed
    assert normal.state is BacklogState.NORMAL
    status = guard.status()
    assert status["capture_gap_count"] == 1
    assert status["capture_gap_started_at"] == 1001.0
    assert status["capture_gap_ended_at"] == 1018.0
    assert status["capture_gap_reason"] == "session_backlog_high"
    assert "content" not in status and "message" not in status


def test_capture_pressure_does_not_change_shadow_business_behavior():
    clock = ManualControlClock(1.0, clock_id="g05-shadow")
    controller = GravitasController(
        default_config(),
        scheduler_source=dict,
        capture_source=lambda: {"state": "ready", "allowed": True},
        mode=GravitasMode.SHADOW,
        clock=clock,
        controller_boot_id="g05-shadow",
    )
    decision = controller.admit_memory_capture(
        MemoryBacklogSnapshot(500, 5000, 700.0, True), wall_time=1000.0
    )
    assert decision.allowed
    assert decision.would_deny
    status = controller.status_snapshot()["memory_backpressure"]
    assert status["capture_gap_count"] == 0
    assert status["would_reject_count"] == 1


def test_pressure_capture_denial_is_explicit_and_writes_no_message(
    tmp_path: Path, monkeypatch
):
    db = tmp_path / "isolated-memory.sqlite3"
    monkeypatch.setattr(pre_processors, "DB_PATH", db)
    monkeypatch.setattr(pre_processors, "_capture_pressure_provider", None)
    pre_processors.set_capture_pressure_provider(
        lambda snapshot, _wall_time: SimpleNamespace(
            allowed=False,
            would_deny=True,
            reason_code="session_backlog_high",
        )
    )
    ctx = ChatContext(
        user_id=2001,
        group_id=7777,
        msg_id=1,
        message="synthetic body must not be stored",
        source_kind="AT_MENTION",
        conversation_kind="group",
        conversation_key="qq:test:group:7777",
        bot_id="test",
        peer_id="7777",
        storage_session_id=7777,
    )
    try:
        asyncio.run(pre_processors.record_message(ctx))
    finally:
        pre_processors.set_capture_pressure_provider(None)

    assert ctx.recorded_row_id == 0
    assert ctx.capture_result == "not_captured_pressure"
    with sqlite3.connect(db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM group_messages WHERE content = ?",
            ("synthetic body must not be stored",),
        ).fetchone()[0]
    assert count == 0

