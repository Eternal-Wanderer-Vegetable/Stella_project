# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Versioned, dependency-free DTOs shared by Gravitas adapters."""

from __future__ import annotations

import math
import types
from dataclasses import MISSING, dataclass, fields, is_dataclass
from enum import Enum
from typing import TypeVar, Union, get_args, get_origin, get_type_hints

T = TypeVar("T", bound="ContractDTO")


class ContractError(ValueError):
    """A wire contract has an invalid or unsupported shape."""


class _StringEnum(str, Enum):
    @classmethod
    def parse(cls, value: object):
        try:
            return cls(value)
        except (TypeError, ValueError) as exc:
            raise ContractError(f"invalid {cls.__name__}: {value!r}") from exc


class ScopeKind(_StringEnum):
    INSTANCE = "instance"
    RESOURCE = "resource"
    ENDPOINT = "endpoint"
    PROVIDER = "provider"
    STORAGE = "storage"
    CONNECTION = "connection"
    CONVERSATION = "conversation"
    TASK = "task"


class HealthDimension(_StringEnum):
    PRESSURE = "pressure"
    AVAILABILITY = "availability"
    INTEGRITY = "integrity"
    RECOVERY = "recovery"


class HealthValue(_StringEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    SATURATED = "saturated"
    FAILED = "failed"
    INVALID = "invalid"
    RECOVERING = "recovering"


class WorkClass(_StringEnum):
    INTERACTIVE = "interactive"
    BACKGROUND = "background"
    MAINTENANCE = "maintenance"


class Operation(_StringEnum):
    TURN_ADMIT = "turn.admit"
    MODEL_ATTEMPT = "model.attempt"
    MEMORY_CAPTURE = "memory.capture"
    MEMORY_CONSOLIDATE = "memory.consolidate"
    MEMORY_COMPACT = "memory.compact"
    PROACTIVE_EMIT = "proactive.emit"
    TRANSPORT_SEND = "transport.send"
    CONTROL_PROBE = "control.probe"


class SideEffectClass(_StringEnum):
    NONE = "none"
    MODEL = "model"
    PERSISTENT = "persistent"
    EXTERNAL = "external"


class DecisionKind(_StringEnum):
    ALLOW = "allow"
    DEFER = "defer"
    DENY = "deny"


class OutcomeKind(_StringEnum):
    STARTED = "started"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    COMPLETED = "completed"
    CANCELLED_BEFORE_EFFECT = "cancelled_before_effect"
    PARTIAL = "partial"
    EFFECT_UNKNOWN = "effect_unknown"
    FAILED_KNOWN = "failed_known"


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ContractError(f"{name} must be a finite positive number")
    return result


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{name} must be an integer >= {minimum}")
    return value


def _text(value: object, name: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string")
    if not value or value != value.strip() or len(value) > max_length:
        raise ContractError(
            f"{name} must be non-empty, trimmed, and at most {max_length} chars"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractError(f"{name} contains a control character")
    return value


def _decode(annotation: object, value: object, name: str) -> object:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ContractError(f"{name} must be an array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], item, name) for item in value)
        if len(value) != len(args):
            raise ContractError(f"{name} must contain {len(args)} items")
        return tuple(
            _decode(kind, item, name) for kind, item in zip(args, value, strict=True)
        )
    if origin in (Union, types.UnionType):
        if value is None and type(None) in args:
            return None
        for kind in args:
            if kind is type(None):
                continue
            try:
                return _decode(kind, value, name)
            except (ContractError, TypeError, ValueError):
                pass
        raise ContractError(f"{name} has an invalid value")
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation.parse(value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, dict):
            raise ContractError(f"{name} must be an object")
        return annotation.from_dict(value)
    if annotation is str:
        return _text(value, name)
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ContractError(f"{name} must be an integer")
        return value
    if annotation is float:
        return _number(value, name)
    if annotation is bool:
        if not isinstance(value, bool):
            raise ContractError(f"{name} must be a boolean")
        return value
    return value


def _wire(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, ContractDTO):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_wire(item) for item in value]
    return value


class ContractDTO:
    """Strict versioned dictionary conversion shared by immutable DTOs."""

    def to_dict(self) -> dict[str, object]:
        if not is_dataclass(self):
            raise TypeError("ContractDTO subclasses must be dataclasses")
        return {field.name: _wire(getattr(self, field.name)) for field in fields(self)}

    @classmethod
    def from_dict(cls: type[T], value: object) -> T:  # noqa: PYI019 -- Self is not in Python 3.10.
        if not isinstance(value, dict) or any(
            not isinstance(key, str) for key in value
        ):
            raise ContractError(f"{cls.__name__} must be an object with string keys")
        allowed = {field.name for field in fields(cls)}
        unknown = value.keys() - allowed
        if unknown:
            raise ContractError(
                f"unknown {cls.__name__} fields: {', '.join(sorted(unknown))}"
            )
        hints = get_type_hints(cls)
        kwargs: dict[str, object] = {}
        for field in fields(cls):
            if field.name not in value:
                if field.default is MISSING and field.default_factory is MISSING:
                    raise ContractError(f"missing {cls.__name__}.{field.name}")
                continue
            kwargs[field.name] = _decode(
                hints[field.name], value[field.name], field.name
            )
        return cls(**kwargs)


@dataclass(frozen=True, slots=True)
class ScopeRef(ContractDTO):
    kind: ScopeKind
    key: str
    source_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ScopeKind):
            raise ContractError("kind must be a ScopeKind")
        _text(self.key, "key")
        _text(self.source_id, "source_id", max_length=128)


@dataclass(frozen=True, slots=True)
class Deadline(ContractDTO):
    expires_at: float
    clock_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "expires_at", _number(self.expires_at, "expires_at"))
        _text(self.clock_id, "clock_id", max_length=128)

    def remaining(self, now: float, *, clock_id: str) -> float:
        if clock_id != self.clock_id:
            raise ContractError("deadline belongs to a different control clock")
        return max(0.0, self.expires_at - _number(now, "now"))

    def is_expired(self, now: float, *, clock_id: str) -> bool:
        return self.remaining(now, clock_id=clock_id) <= 0.0


@dataclass(frozen=True, slots=True)
class HealthFact(ContractDTO):
    schema_version: int
    scope: ScopeRef
    dimension: HealthDimension
    value: HealthValue
    reason_code: str
    source_id: str
    source_boot_id: str
    source_sequence: int
    observed_control_time: float
    valid_for_seconds: float
    metric_value: float | None = None

    def __post_init__(self) -> None:
        if _integer(self.schema_version, "schema_version", minimum=1) != 1:
            raise ContractError("unsupported HealthFact schema_version")
        if not isinstance(self.scope, ScopeRef):
            raise ContractError("scope must be a ScopeRef")
        if not isinstance(self.dimension, HealthDimension) or not isinstance(
            self.value, HealthValue
        ):
            raise ContractError("invalid HealthFact dimension or value")
        _text(self.reason_code, "reason_code", max_length=128)
        _text(self.source_id, "source_id", max_length=128)
        _text(self.source_boot_id, "source_boot_id", max_length=128)
        _integer(self.source_sequence, "source_sequence")
        object.__setattr__(
            self,
            "observed_control_time",
            _number(self.observed_control_time, "observed_control_time"),
        )
        object.__setattr__(
            self,
            "valid_for_seconds",
            _number(self.valid_for_seconds, "valid_for_seconds", positive=True),
        )
        if self.metric_value is not None:
            object.__setattr__(
                self, "metric_value", _number(self.metric_value, "metric_value")
            )

    def is_fresh(self, now: float) -> bool:
        return _number(now, "now") < self.observed_control_time + self.valid_for_seconds


@dataclass(frozen=True, slots=True)
class PolicySnapshot(ContractDTO):
    schema_version: int
    controller_boot_id: str
    policy_revision: int
    config_digest: str
    issued_at: float
    valid_for_seconds: float
    allowed_operations: tuple[str, ...]
    resource_limits: tuple[tuple[str, int], ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _integer(self.schema_version, "schema_version", minimum=1) != 1:
            raise ContractError("unsupported PolicySnapshot schema_version")
        _text(self.controller_boot_id, "controller_boot_id", max_length=128)
        _integer(self.policy_revision, "policy_revision")
        _text(self.config_digest, "config_digest", max_length=128)
        object.__setattr__(self, "issued_at", _number(self.issued_at, "issued_at"))
        object.__setattr__(
            self,
            "valid_for_seconds",
            _number(self.valid_for_seconds, "valid_for_seconds", positive=True),
        )
        _validate_text_items(self.allowed_operations, "allowed_operations")
        if len(set(self.allowed_operations)) != len(self.allowed_operations):
            raise ContractError("allowed_operations contains duplicates")
        unknown = set(self.allowed_operations) - {item.value for item in Operation}
        if unknown:
            raise ContractError(
                "unsupported enforce operations: " + ", ".join(sorted(unknown))
            )
        _validate_pairs(self.resource_limits)
        _validate_text_items(self.reason_codes, "reason_codes")

    @property
    def expires_at(self) -> float:
        return self.issued_at + self.valid_for_seconds


@dataclass(frozen=True, slots=True)
class OperationRequest(ContractDTO):
    op_id: str
    operation: str
    scope_refs: tuple[ScopeRef, ...]
    work_class: WorkClass
    deadline: Deadline | None
    origin_turn: str | None
    origin_task: str | None
    side_effect_class: SideEffectClass

    def __post_init__(self) -> None:
        _text(self.op_id, "op_id", max_length=128)
        _text(self.operation, "operation", max_length=128)
        if not isinstance(self.scope_refs, tuple) or any(
            not isinstance(item, ScopeRef) for item in self.scope_refs
        ):
            raise ContractError("scope_refs must be a tuple of ScopeRef")
        if not isinstance(self.work_class, WorkClass):
            raise ContractError("work_class must be a WorkClass")
        if self.deadline is not None and not isinstance(self.deadline, Deadline):
            raise ContractError("deadline must be a Deadline or None")
        if self.origin_turn is not None:
            _text(self.origin_turn, "origin_turn", max_length=128)
        if self.origin_task is not None:
            _text(self.origin_task, "origin_task", max_length=128)
        if not isinstance(self.side_effect_class, SideEffectClass):
            raise ContractError("side_effect_class must be a SideEffectClass")


@dataclass(frozen=True, slots=True)
class AdmissionDecision(ContractDTO):
    kind: DecisionKind
    reason_codes: tuple[str, ...]
    policy_revision: int
    valid_until: float
    clock_id: str
    retry_not_before: float | None = None
    resource_group_id: str | None = None
    max_attempts: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DecisionKind):
            raise ContractError("kind must be a DecisionKind")
        _validate_text_items(self.reason_codes, "reason_codes")
        _integer(self.policy_revision, "policy_revision")
        object.__setattr__(
            self, "valid_until", _number(self.valid_until, "valid_until")
        )
        _text(self.clock_id, "clock_id", max_length=128)
        if self.retry_not_before is not None:
            object.__setattr__(
                self,
                "retry_not_before",
                _number(self.retry_not_before, "retry_not_before"),
            )
        if self.kind is DecisionKind.DEFER and self.retry_not_before is None:
            raise ContractError("DEFER requires retry_not_before")
        if self.resource_group_id is not None:
            _text(self.resource_group_id, "resource_group_id", max_length=128)
        _integer(self.max_attempts, "max_attempts")


@dataclass(frozen=True, slots=True)
class OperationOutcome(ContractDTO):
    kind: OutcomeKind
    effect_started: bool
    attempt_count: int
    policy_revision: int
    result_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, OutcomeKind):
            raise ContractError("kind must be an OutcomeKind")
        if not isinstance(self.effect_started, bool):
            raise ContractError("effect_started must be a boolean")
        _integer(self.attempt_count, "attempt_count")
        _integer(self.policy_revision, "policy_revision")
        _text(self.result_code, "result_code", max_length=128)


@dataclass(frozen=True, slots=True)
class AppliedAck(ContractDTO):
    adapter_id: str
    policy_revision: int
    applied: bool
    reason_code: str
    acknowledged_at: float

    def __post_init__(self) -> None:
        _text(self.adapter_id, "adapter_id", max_length=128)
        _integer(self.policy_revision, "policy_revision")
        if not isinstance(self.applied, bool):
            raise ContractError("applied must be a boolean")
        _text(self.reason_code, "reason_code", max_length=128)
        object.__setattr__(
            self, "acknowledged_at", _number(self.acknowledged_at, "acknowledged_at")
        )


def _validate_text_items(items: object, name: str) -> None:
    if not isinstance(items, tuple):
        raise ContractError(f"{name} must be a tuple")
    for index, item in enumerate(items):
        _text(item, f"{name}[{index}]")


def _validate_pairs(items: object) -> None:
    if not isinstance(items, tuple):
        raise ContractError("resource_limits must be a tuple")
    seen: set[str] = set()
    for pair in items:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise ContractError(
                "resource_limits entries must be (resource_id, limit) pairs"
            )
        resource_id, limit = pair
        _text(resource_id, "resource_id", max_length=128)
        if resource_id in seen:
            raise ContractError(f"duplicate resource limit: {resource_id}")
        seen.add(resource_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ContractError("resource limits must be positive integers")
