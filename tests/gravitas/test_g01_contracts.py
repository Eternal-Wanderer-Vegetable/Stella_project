# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import math
from pathlib import Path

import pytest

from gravitas.admission import is_operation_supported, snapshot_is_current
from gravitas.clock import ManualControlClock, PerformanceClock
from gravitas.config import ConfigError, GravitasMode, load_config, parse_config
from gravitas.contracts import (
    AdmissionDecision,
    AppliedAck,
    ContractError,
    Deadline,
    DecisionKind,
    HealthDimension,
    HealthFact,
    HealthValue,
    Operation,
    OperationOutcome,
    OperationRequest,
    OutcomeKind,
    PolicySnapshot,
    ScopeKind,
    ScopeRef,
    SideEffectClass,
    WorkClass,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "config" / "gravitas.example.toml"


def _round_trip(value):
    assert type(value).from_dict(value.to_dict()) == value


@pytest.mark.parametrize(
    "value",
    [
        ScopeRef(ScopeKind.CONVERSATION, "qq:group:123", "runtime.ingress"),
        Deadline(12.5, "boot-a"),
        HealthFact(
            1,
            ScopeRef(ScopeKind.RESOURCE, "local_inference", "scheduler"),
            HealthDimension.PRESSURE,
            HealthValue.SATURATED,
            "queue_full",
            "scheduler",
            "boot-a",
            4,
            8.0,
            5.0,
            0.95,
        ),
        PolicySnapshot(
            1,
            "boot-a",
            3,
            "sha256:abc",
            10.0,
            2.0,
            (Operation.TURN_ADMIT.value,),
            (("local_inference", 1),),
            ("pressure_high",),
        ),
        OperationRequest(
            "op-1",
            "turn.admit",
            (ScopeRef(ScopeKind.CONVERSATION, "webchat:room:42", "webchat"),),
            WorkClass.INTERACTIVE,
            Deadline(20.0, "boot-a"),
            "turn-1",
            None,
            SideEffectClass.MODEL,
        ),
        AdmissionDecision(DecisionKind.DEFER, ("queue_full",), 3, 15.0, "boot-a", 12.0),
        OperationOutcome(OutcomeKind.COMPLETED, True, 1, 3, "ok"),
        AppliedAck("runtime.facade", 3, True, "applied", 14.0),
    ],
)
def test_contract_dtos_round_trip(value):
    _round_trip(value)


def test_operation_request_keeps_unknown_operation_representable_but_not_supported():
    request = OperationRequest(
        "op-unknown",
        "cometa.admin",
        (),
        WorkClass.BACKGROUND,
        None,
        None,
        "task-1",
        SideEffectClass.PERSISTENT,
    )
    assert request.operation == "cometa.admin"
    assert not is_operation_supported(request.operation)
    assert is_operation_supported("model.attempt")

    with pytest.raises(ContractError, match="unsupported enforce operations"):
        PolicySnapshot(1, "boot-a", 1, "digest", 10.0, 5.0, ("cometa.admin",))


def test_contract_wire_shape_rejects_unknown_fields_and_bad_numbers():
    scope = ScopeRef(ScopeKind.RESOURCE, "local_inference", "scheduler").to_dict()
    scope["trust_me"] = True
    with pytest.raises(ContractError, match="unknown"):
        ScopeRef.from_dict(scope)

    deadline = Deadline(10, "boot-a").to_dict()
    deadline["expires_at"] = math.inf
    with pytest.raises(ContractError, match="finite"):
        Deadline.from_dict(deadline)

    with pytest.raises(ContractError, match="integer"):
        HealthFact(
            1,
            ScopeRef(ScopeKind.RESOURCE, "local_inference", "scheduler"),
            HealthDimension.PRESSURE,
            HealthValue.UNKNOWN,
            "unknown",
            "scheduler",
            "boot-a",
            "4",
            1.0,
            5.0,
        )


def test_defer_requires_retry_time():
    with pytest.raises(ContractError, match="retry_not_before"):
        AdmissionDecision(DecisionKind.DEFER, ("busy",), 1, 20.0, "boot-a")


def test_config_example_parses_as_strict_v1():
    config = load_config(EXAMPLE)
    assert config.schema_version == 1
    assert config.controller.tick_seconds == 1.0
    assert config.limits.max_pending_per_conversation == 1
    assert config.resource("local_inference").slots == ("CHAT", "MEMORY")
    assert GravitasMode.SHADOW.value == "shadow"

    from scripts.generate_message_flow import ProjectIndex

    assert "gravitas" in ProjectIndex.PACKAGE_DIRS


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda text: text.replace("schema_version = 1", "schema_version = 2"),
            "unsupported",
        ),
        (
            lambda text: text.replace(
                "schema_version = 1", "schema_version = 1\nunknown = true"
            ),
            "unknown root keys",
        ),
        (
            lambda text: text.replace("tick_seconds = 1.0", "tick_seconds = nan"),
            "finite",
        ),
        (
            lambda text: text.replace(
                "fact_ttl_seconds = 5.0", "fact_ttl_seconds = 0.5"
            ),
            "tick_seconds",
        ),
        (
            lambda text: text.replace(
                'slots = ["CHAT", "MEMORY"]', 'slots = ["CHAT", "CHAT"]'
            ),
            "duplicates",
        ),
        (lambda text: text.replace("concurrency = 1", "concurrency = true"), "integer"),
    ],
)
def test_config_rejects_invalid_profile(mutation, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(mutation(EXAMPLE.read_text(encoding="utf-8")))


def test_control_clock_expiry_is_deterministic_and_separate_from_performance_time():
    clock = ManualControlClock(10.0, clock_id="boot-a")
    deadline = Deadline(clock.now() + 2.0, clock.clock_id)
    snapshot = PolicySnapshot(1, "boot-a", 7, "sha256:abc", 10.0, 5.0, ("turn.admit",))
    perf = PerformanceClock()

    assert deadline.remaining(clock.now(), clock_id=clock.clock_id) == 2.0
    assert snapshot_is_current(snapshot, now=clock.now(), expected_boot_id="boot-a")
    assert not snapshot_is_current(snapshot, now=clock.now(), expected_boot_id="boot-b")
    clock.advance(2.0)
    assert deadline.is_expired(clock.now(), clock_id=clock.clock_id)
    assert snapshot_is_current(snapshot, now=clock.now(), expected_boot_id="boot-a")
    assert isinstance(perf.now(), float)
    with pytest.raises(ContractError, match="different control clock"):
        deadline.remaining(clock.now(), clock_id="boot-b")
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(-1)


def test_fact_ttl_expires_on_control_clock():
    clock = ManualControlClock(1.0)
    fact = HealthFact(
        1,
        ScopeRef(ScopeKind.RESOURCE, "local_inference", "scheduler"),
        HealthDimension.PRESSURE,
        HealthValue.HEALTHY,
        "within_limit",
        "scheduler",
        "boot-a",
        1,
        clock.now(),
        2.0,
    )
    assert fact.is_fresh(clock.now())
    clock.advance(2.0)
    assert not fact.is_fresh(clock.now())
