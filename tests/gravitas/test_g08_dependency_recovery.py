# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest

import core.llm.registry as llm_registry
import core.llm.scheduler as scheduler
from capability.registry import CapabilityProvider
from gravitas.config import default_config
from gravitas.contracts import HealthValue, ScopeKind, WorkClass
from gravitas.dependency_recovery import (
    DependencyRecovery,
    DependencyScope,
    FailureKind,
    StorageDomain,
    classify_dependency_failure,
    connect_sqlite,
    dependency_recovery,
    endpoint_scope,
    storage_scope,
)
from gravitas.model_calls import ModelCallContext, execute_model_call


class _FakeClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_s13_scopes_are_isolated_and_late_outcomes_are_fenced():
    clock = _FakeClock()
    recovery = DependencyRecovery(clock=clock, seed=20261021)
    endpoint_a = DependencyScope(ScopeKind.ENDPOINT, "provider-a:primary")
    endpoint_b = DependencyScope(ScopeKind.ENDPOINT, "provider-b:primary")

    older = recovery.begin_attempt(endpoint_a)
    newer = recovery.begin_attempt(endpoint_a)
    assert recovery.record_attempt_result(newer, success=False)
    assert not recovery.record_attempt_result(older, success=True)
    assert recovery.fact(endpoint_a).health is HealthValue.DEGRADED
    assert recovery.fact(endpoint_b).health is HealthValue.UNKNOWN

    retry_at = recovery.fact(endpoint_a).next_probe_at
    assert retry_at is not None
    assert recovery.claim_probe(endpoint_a, now=retry_at - 0.01) is None
    clock.now = retry_at
    lease = recovery.claim_probe(endpoint_a)
    assert lease is not None
    assert recovery.claim_probe(endpoint_a) is None
    assert recovery.finish_probe(lease, success=True, next_probe_delay=5.0)
    assert recovery.fact(endpoint_a).health is HealthValue.HEALTHY

    endpoint_c = DependencyScope(ScopeKind.ENDPOINT, "provider-c:primary")
    old_probe = recovery.claim_probe(endpoint_c)
    assert old_probe is not None
    fresh_attempt = recovery.begin_attempt(endpoint_c)
    assert recovery.record_attempt_result(fresh_attempt, success=True)
    assert not recovery.finish_probe(old_probe, success=False)
    assert recovery.fact(endpoint_c).health is HealthValue.HEALTHY


def test_s13_probe_budget_and_terminal_configuration_fail_closed():
    clock = _FakeClock(0.0)
    recovery = DependencyRecovery(
        clock=clock,
        seed=7,
        probe_window_seconds=10.0,
        max_probes_per_scope=2,
        global_probe_budget=1,
    )
    first = DependencyScope(ScopeKind.CONNECTION, "connection-a")
    second = DependencyScope(ScopeKind.CONNECTION, "connection-b")
    lease = recovery.claim_probe(first, lease_seconds=2.0)
    assert lease is not None
    assert recovery.claim_probe(first) is None
    assert recovery.claim_probe(second) is None
    clock.now = 2.0
    assert not recovery.finish_probe(lease, success=True)
    clock.now = 10.0
    assert recovery.claim_probe(second) is not None

    terminal = DependencyScope(ScopeKind.ENDPOINT, "bad-model")
    fence = recovery.begin_attempt(terminal)
    assert recovery.record_attempt_result(
        fence,
        success=False,
        failure_kind=FailureKind.CONFIGURATION,
    )
    assert recovery.fact(terminal).health is HealthValue.FAILED
    assert recovery.claim_probe(terminal) is None
    assert classify_dependency_failure(RuntimeError("HTTP 403 forbidden")) is FailureKind.AUTHORIZATION
    class _ResponseError(RuntimeError):
        response = type("Response", (), {"status_code": 404})()

    assert classify_dependency_failure(_ResponseError("missing model")) is FailureKind.CONFIGURATION


def test_s13_fallback_success_does_not_restore_the_primary_endpoint():
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(lambda _resource: 1)

    class Backend:
        def __init__(self, slot: str, *, failures: int = 0) -> None:
            self.slot = slot
            self.failures = failures

        async def generate_single_attempt(self, prompt: str, system_prompt: str = ""):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("connection reset")
            return f"{system_prompt}:{prompt}", "stop"

    primary = Backend("G08_PRIMARY", failures=2)
    fallback = Backend("G08_FALLBACK")
    role = llm_registry.RoleBackend("chat", primary, fallback, cooldown=30.0)
    try:
        result = asyncio.run(
            execute_model_call(
                role,
                "synthetic prompt",
                context=ModelCallContext("G08_PRIMARY", WorkClass.INTERACTIVE),
            )
        )
        assert result == ":synthetic prompt"
        assert dependency_recovery.fact(endpoint_scope(primary)).health is HealthValue.DEGRADED
        assert dependency_recovery.fact(endpoint_scope(fallback)).health is HealthValue.HEALTHY
    finally:
        scheduler.reset_state()
        scheduler.set_concurrency_resolver(llm_registry.concurrency_of)


def test_provider_cooldown_survives_a_late_success():
    provider = CapabilityProvider(
        provider_id="provider-g08-fence",
        capability_id="capability-g08-fence",
        tool_name="synthetic-tool",
    )
    now = time.time()
    assert provider.mark_failure(1, 30.0, now=now)
    cooldown = provider.disabled_until
    provider.mark_success()
    assert provider.disabled_until == cooldown
    assert provider.available(now=now) is False


@pytest.mark.parametrize("domain", list(StorageDomain))
def test_s14_locked_storage_is_degraded_not_corrupt(tmp_path, domain):
    clock = _FakeClock()
    recovery = DependencyRecovery(clock=clock, seed=20261021)
    path = tmp_path / f"{domain.value}.db"
    owner = connect_sqlite(domain, path, timeout=0.0, recovery=recovery)
    owner.execute("CREATE TABLE sample (value INTEGER NOT NULL)")
    owner.commit()
    assert recovery.fact(storage_scope(domain)).health is HealthValue.UNKNOWN
    owner.execute("BEGIN EXCLUSIVE")

    contender = connect_sqlite(domain, path, timeout=0.0, recovery=recovery)
    try:
        with pytest.raises(sqlite3.OperationalError, match=r"locked|busy"):
            contender.execute("INSERT INTO sample VALUES (1)")
        fact = recovery.fact(storage_scope(domain))
        assert fact.health is HealthValue.DEGRADED
        assert fact.failure_kind == FailureKind.CONTENTION.value
        assert fact.health is not HealthValue.INVALID
        assert recovery.claim_probe(storage_scope(domain)) is None
        assert recovery.mark_storage_maintenance_success(domain, check_passed=True)
        assert recovery.fact(storage_scope(domain)).health is HealthValue.HEALTHY
    finally:
        contender.close()
        owner.rollback()
        owner.close()


def test_s14_readonly_disk_full_and_corruption_have_distinct_contracts():
    recovery = DependencyRecovery(clock=_FakeClock(), seed=3)
    recovery.record_storage_failure(
        StorageDomain.MEMORY,
        sqlite3.OperationalError("attempt to write a readonly database"),
    )
    recovery.record_storage_failure(
        StorageDomain.SOCIAL,
        sqlite3.OperationalError("database or disk is full"),
    )
    recovery.record_storage_failure(
        StorageDomain.COMETA,
        sqlite3.DatabaseError("database disk image is malformed"),
    )

    assert recovery.fact(storage_scope(StorageDomain.MEMORY)).health is HealthValue.FAILED
    assert recovery.fact(storage_scope(StorageDomain.MEMORY)).failure_kind == FailureKind.READ_ONLY.value
    assert recovery.fact(storage_scope(StorageDomain.SOCIAL)).failure_kind == FailureKind.DISK_FULL.value
    assert recovery.fact(storage_scope(StorageDomain.COMETA)).health is HealthValue.INVALID
    assert recovery.fact(storage_scope(StorageDomain.SCHEDULING)).health is HealthValue.UNKNOWN


def test_recovery_snapshot_is_bounded_and_contains_only_safe_facts():
    recovery = DependencyRecovery(clock=_FakeClock(), seed=1, max_scopes=1)
    first = DependencyScope(ScopeKind.ENDPOINT, "safe-endpoint-token")
    second = DependencyScope(ScopeKind.PROVIDER, "safe-provider-token")
    recovery.begin_attempt(first)
    recovery.begin_attempt(second)
    snapshot = recovery.snapshot()
    assert len(snapshot["facts"]) == 1
    assert snapshot["incomplete"] is True
    assert snapshot["scope_overflow_count"] == 1
    assert "api_key" not in str(snapshot)
    assert "prompt" not in str(snapshot)


def test_g08_scenarios_remain_v2_and_do_not_mutate_the_inventory():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    inventory = json.loads(
        (root / "docs/plans/2026-10-21-gravitas-inventory.json").read_text(encoding="utf-8")
    )
    scenarios = {scenario["id"]: scenario for scenario in inventory["scenarios"]}
    assert scenarios["S13"]["release"] == "v2"
    assert scenarios["S14"]["release"] == "v2"
    assert scenarios["S13"]["required_invariants"] == ["I01", "I07", "I10"]
    assert scenarios["S14"]["required_invariants"] == ["I01", "I04", "I05"]
    assert default_config().schema_version == 1
