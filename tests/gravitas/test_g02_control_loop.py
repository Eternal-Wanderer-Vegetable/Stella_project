# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from gravitas.clock import ManualControlClock
from gravitas.config import GravitasMode, default_config, parse_config
from gravitas.contracts import (
    HealthDimension,
    HealthFact,
    HealthValue,
    Operation,
    ScopeKind,
    ScopeRef,
)
from gravitas.controller import FactCache, GravitasController
from gravitas.events import EventBuffer, EventKind
from gravitas.metrics import BoundedMetrics
from gravitas.policy import (
    PressureState,
    ResourcePolicyState,
    ResourceSignals,
    evaluate_pressure,
)


def _setup_gravitas(driver, *, stella_home, status_api):
    source = (
        Path(__file__).resolve().parents[2]
        / "stella_project"
        / "plugins"
        / "bot_main"
        / "gravitas_bootstrap.py"
    )
    spec = importlib.util.spec_from_file_location("gravitas_bootstrap_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.setup_gravitas(driver, stella_home=stella_home, status_api=status_api)


def _fact(*, sequence: int, boot_id: str = "boot-a", observed_at: float = 1.0):
    return HealthFact(
        schema_version=1,
        scope=ScopeRef(ScopeKind.RESOURCE, "local_inference", "scheduler"),
        dimension=HealthDimension.PRESSURE,
        value=HealthValue.HEALTHY,
        reason_code="within_limit",
        source_id="scheduler",
        source_boot_id=boot_id,
        source_sequence=sequence,
        observed_control_time=observed_at,
        valid_for_seconds=5.0,
    )


def test_fact_cache_rejects_replay_after_expiry_and_old_boots():
    cache = FactCache(max_scopes=2, ttl_seconds=5.0)
    first = _fact(sequence=4)
    assert cache.put(first, now=1.0, expected_boot_id="boot-a")
    assert not cache.put(first, now=1.0, expected_boot_id="boot-a")
    assert cache.put(_fact(sequence=5, observed_at=2.0), now=2.0, expected_boot_id="boot-a")

    cache.prune(8.0)
    assert cache.snapshot(now=8.0) == ()
    assert not cache.put(
        _fact(sequence=5, observed_at=8.0), now=8.0, expected_boot_id="boot-a"
    )
    assert not cache.put(
        _fact(sequence=6, boot_id="old-boot", observed_at=8.0),
        now=8.0,
        expected_boot_id="boot-a",
    )
    assert cache.stats(now=8.0).rejected == 3


def test_fact_cache_is_bounded_and_marks_evictions_incomplete():
    cache = FactCache(max_scopes=1, ttl_seconds=5.0)
    assert cache.put(_fact(sequence=1), now=1.0, expected_boot_id="boot-a")
    second = HealthFact(
        schema_version=1,
        scope=ScopeRef(ScopeKind.RESOURCE, "other_resource", "scheduler"),
        dimension=HealthDimension.PRESSURE,
        value=HealthValue.HEALTHY,
        reason_code="within_limit",
        source_id="scheduler",
        source_boot_id="boot-a",
        source_sequence=2,
        observed_control_time=1.0,
        valid_for_seconds=5.0,
    )
    assert not cache.put(
        second,
        now=1.0,
        active_scopes={(ScopeKind.RESOURCE.value, "local_inference")},
        expected_boot_id="boot-a",
    )
    stats = cache.stats(now=1.0)
    assert stats.tracked == 1
    assert stats.incomplete


def test_metric_window_is_bounded_and_missing_p95_is_not_zero():
    metrics = BoundedMetrics(
        max_samples_per_resource=3,
        window_seconds=60.0,
        max_resources=1,
    )
    for second in range(4):
        assert metrics.record(
            "local_inference",
            observed_at=float(second),
            waiting=1,
            holding=1,
            limit=1,
            oldest_wait_seconds=None,
        )
    view = metrics.snapshot("local_inference", now=3.0)
    assert view.sample_count == 3
    assert view.p95_interactive_wait_seconds is None
    assert view.p95_sample_count == 0
    assert view.incomplete
    assert metrics.dropped_samples == 1

    assert not metrics.record(
        "another_resource",
        observed_at=4.0,
        waiting=0,
        holding=0,
        limit=1,
    )
    assert metrics.snapshot("local_inference", now=100.0) is None


def test_event_buffer_is_bounded_and_accepts_only_structured_reasons():
    events = EventBuffer(capacity=2)
    for reason in ("within_limit", "pressure_high", "recovery_started"):
        events.append(
            EventKind.PRESSURE_TRANSITION,
            reason,
            observed_at=1.0,
            resource_id="local_inference",
        )
    assert events.snapshot() == {
        "capacity": 2,
        "count": 2,
        "dropped": 1,
        "last_sequence": 3,
        "kinds": ["pressure_transition"],
    }
    assert len(events.recent()) == 2
    with pytest.raises(ValueError, match="low-cardinality"):
        events.append(EventKind.COLLECTOR_ERROR, "private chat text", observed_at=2.0)
    assert events.recent(0) == ()


def test_pressure_policy_hysteresis_and_staged_recovery():
    config = default_config()
    pressure = config.pressure
    state = ResourcePolicyState(
        state=PressureState.NORMAL,
        background_tokens=config.limits.background_queue,
    )
    high = ResourceSignals(queue_depth=8, oldest_wait_seconds=None)
    for now in (1.0, 2.0):
        state = evaluate_pressure(
            state,
            high,
            pressure,
            now=now,
            background_token_limit=4,
        ).next_state
        assert state.state is PressureState.NORMAL
    state = evaluate_pressure(
        state, high, pressure, now=3.0, background_token_limit=4
    ).next_state
    assert state.state is PressureState.CONSTRAINED
    assert state.background_tokens == 0

    low = ResourceSignals(queue_depth=0, oldest_wait_seconds=0.0)
    for now in (4.0, 10.0):
        state = evaluate_pressure(
            state, low, pressure, now=now, background_token_limit=4
        ).next_state
        assert state.state is PressureState.CONSTRAINED
    state = evaluate_pressure(
        state, low, pressure, now=19.0, background_token_limit=4
    ).next_state
    assert state.state is PressureState.RECOVERING
    assert state.background_tokens == 0

    state = evaluate_pressure(
        state, low, pressure, now=29.0, background_token_limit=4
    ).next_state
    assert state.background_tokens == 1
    state = evaluate_pressure(
        state, high, pressure, now=30.0, background_token_limit=4
    ).next_state
    assert state.state is PressureState.CONSTRAINED
    assert state.background_tokens == 0

    missing = evaluate_pressure(
        state,
        ResourceSignals(queue_depth=None, oldest_wait_seconds=None),
        pressure,
        now=31.0,
        background_token_limit=4,
    )
    assert missing.next_state.state is PressureState.UNKNOWN


def test_config_rejects_pressure_thresholds_without_hysteresis():
    example = (Path(__file__).resolve().parents[2] / "config" / "gravitas.example.toml").read_text(encoding="utf-8")
    invalid = example.replace("recover_queue_depth = 2", "recover_queue_depth = 8")
    with pytest.raises(ValueError, match="recovery queue threshold"):
        parse_config(invalid)
    over_capacity = example.replace(
        "max_samples_per_resource = 512", "max_samples_per_resource = 513"
    )
    with pytest.raises(ValueError, match="cannot exceed 512"):
        parse_config(over_capacity)


def test_shadow_controller_caches_facts_and_never_changes_business_effects():
    clock = ManualControlClock(100.0, clock_id="controller-boot")
    state = {"waiting": 0}
    reads = {"scheduler": 0, "capture": 0}
    business_effects = []

    def scheduler_source():
        reads["scheduler"] += 1
        return {
            "CHAT": {
                "waiting": state["waiting"],
                "holding": 1,
                "limit": 1,
            }
        }

    def capture_source():
        reads["capture"] += 1
        return {"state": "ready", "allowed": True}

    controller = GravitasController(
        default_config(),
        scheduler_source=scheduler_source,
        capture_source=capture_source,
        mode=GravitasMode.SHADOW,
        clock=clock,
        controller_boot_id="controller-boot",
    )
    controller.tick()
    for _ in range(3):
        state["waiting"] = 8
        clock.advance(1.0)
        controller.tick()

    status = controller.status_snapshot()
    assert status["mode"] == "shadow"
    assert status["enforcement_enabled"] is False
    assert status["resources"][0]["pressure"] == "constrained"
    assert status["facts"]["fresh"] == 2
    assert controller.policy.allowed_operations == tuple(item.value for item in Operation)
    reads_before_status = reads.copy()
    controller.status_snapshot()
    assert reads == reads_before_status
    assert business_effects == []

    status["resources"].clear()
    assert controller.status_snapshot()["resources"]
    clock.advance(6.0)
    assert not controller.status_snapshot()["snapshot_valid"]


class _FakeDriver:
    def __init__(self):
        self.startup = []
        self.shutdown = []

    def on_startup(self, callback):
        self.startup.append(callback)

    def on_shutdown(self, callback):
        self.shutdown.append(callback)


class _FakeStatusApi:
    def set_gravitas_status_provider(self, provider):
        self.provider = provider


def test_bootstrap_refuses_enforce_and_starts_stops_shadow_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAVITAS_MODE", "enforce")
    driver = _FakeDriver()
    status_api = _FakeStatusApi()
    runtime = _setup_gravitas(driver, stella_home=tmp_path, status_api=status_api)

    initial = status_api.provider()
    assert initial["configured_mode"] == "enforce"
    assert initial["mode"] == "shadow"
    assert initial["enforcement_enabled"] is False
    assert initial["reason_code"] == "enforcement_refused"
    assert len(driver.startup) == len(driver.shutdown) == 1

    async def lifecycle():
        await driver.startup[0]()
        await asyncio.sleep(0)
        active = status_api.provider()
        assert active["snapshot_valid"]
        await driver.shutdown[0]()
        assert runtime._task is None

    asyncio.run(lifecycle())


def test_bootstrap_config_errors_are_visible_without_loading_user_data(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "gravitas.toml").write_text("schema_version = 99", encoding="utf-8")
    status_api = _FakeStatusApi()
    _setup_gravitas(_FakeDriver(), stella_home=tmp_path, status_api=status_api)
    status = status_api.provider()
    assert status["bootstrap_state"] == "degraded"
    assert status["reason_code"] == "config_error"
    assert status["enforcement_enabled"] is False
