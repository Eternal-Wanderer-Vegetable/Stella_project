# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Pure per-resource pressure hysteresis; this module never performs admission."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import Enum

from gravitas.config import PressureConfig


class PressureState(str, Enum):
    UNKNOWN = "unknown"
    NORMAL = "normal"
    CONSTRAINED = "constrained"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class ResourceSignals:
    queue_depth: int | None
    oldest_wait_seconds: float | None


@dataclass(frozen=True, slots=True)
class ResourcePolicyState:
    state: PressureState = PressureState.UNKNOWN
    consecutive_high_windows: int = 0
    low_since: float | None = None
    normal_since: float | None = None
    last_token_at: float | None = None
    background_tokens: int = 0
    last_aged_backend_at: float | None = None


@dataclass(frozen=True, slots=True)
class PressureStep:
    next_state: ResourcePolicyState
    reason_code: str
    changed: bool
    valid_sample: bool


@dataclass(frozen=True, slots=True)
class BackgroundAdmission:
    allowed: bool
    reason_code: str
    next_state: ResourcePolicyState


@dataclass(frozen=True, slots=True)
class OperationAdmission:
    allowed: bool
    would_deny: bool
    reason_code: str


class BacklogState(str, Enum):
    UNKNOWN = "unknown"
    NORMAL = "normal"
    CONSTRAINED = "constrained"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class MemoryBacklogSnapshot:
    session_pending: int | None
    instance_pending: int | None
    oldest_age_seconds: float | None
    metrics_valid: bool
    session_oldest_age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class CaptureAdmission:
    allowed: bool
    would_deny: bool
    reason_code: str
    state: BacklogState


class MemoryBacklogGuard:
    """Hysteretic capture cap with a body-free, process-local gap ledger."""

    def __init__(self, config) -> None:
        self._config = config
        self._state = BacklogState.UNKNOWN
        self._low_since: float | None = None
        self._normal_since: float | None = None
        self._gap_count = 0
        self._gap_started_at: float | None = None
        self._gap_ended_at: float | None = None
        self._gap_reason = ""
        self._would_deny_count = 0
        self._gap_open = False

    def evaluate(
        self,
        snapshot: MemoryBacklogSnapshot,
        *,
        now: float,
        wall_time: float,
    ) -> CaptureAdmission:
        now = _finite(now, "now")
        wall_time = _finite(wall_time, "wall_time")
        session = _optional_count(snapshot.session_pending, "session_pending")
        instance = _optional_count(snapshot.instance_pending, "instance_pending")
        age = _optional_nonnegative(snapshot.oldest_age_seconds, "oldest_age_seconds")
        session_age = _optional_nonnegative(
            snapshot.session_oldest_age_seconds, "session_oldest_age_seconds"
        )
        if session_age is None and session == 0:
            session_age = 0.0
        elif session_age is None:
            session_age = age
        valid = (
            session is not None
            and instance is not None
            and age is not None
            and session_age is not None
            and snapshot.metrics_valid is True
        )
        if not valid:
            self._state = BacklogState.CONSTRAINED
            self._low_since = None
            self._normal_since = None
            return self._deny("backlog_integrity_untrusted")

        high_reason = ""
        if session >= self._config.backlog_session_high_water:
            high_reason = "session_backlog_high"
        elif instance >= self._config.backlog_instance_high_water:
            high_reason = "instance_backlog_high"
        elif session_age >= self._config.backlog_age_high_water_seconds:
            high_reason = "session_backlog_age_high"
        elif age >= self._config.backlog_age_high_water_seconds:
            high_reason = "backlog_age_high"
        if high_reason:
            self._state = BacklogState.CONSTRAINED
            self._low_since = None
            self._normal_since = None
            return self._deny(high_reason)

        low = (
            session <= self._config.backlog_session_low_water
            and instance <= self._config.backlog_instance_low_water
        )
        if self._state is BacklogState.UNKNOWN:
            self._state = BacklogState.NORMAL
        elif self._state is BacklogState.CONSTRAINED:
            if not low:
                self._low_since = None
                return self._deny("backlog_recovery_waiting_for_low_water")
            self._low_since = self._low_since if self._low_since is not None else now
            if now - self._low_since < self._config.recover_stable_seconds:
                return self._deny("backlog_recovery_stabilizing")
            self._state = BacklogState.RECOVERING
            self._normal_since = now
        elif self._state is BacklogState.RECOVERING:
            if not low:
                self._state = BacklogState.CONSTRAINED
                self._low_since = None
                self._normal_since = None
                return self._deny("backlog_rebounded")
            self._normal_since = self._normal_since if self._normal_since is not None else now
            if now - self._normal_since >= self._config.normal_stable_seconds:
                self._state = BacklogState.NORMAL
                self._low_since = None
                self._normal_since = None

        if self._gap_open:
            self._gap_ended_at = wall_time
            self._gap_open = False
        return CaptureAdmission(True, False, "capture_allowed", self._state)

    def record_gap(self, reason_code: str, *, wall_time: float) -> None:
        wall_time = _finite(wall_time, "wall_time")
        if not isinstance(reason_code, str) or not _REASON_CODE.fullmatch(reason_code):
            raise ValueError("reason_code must be a bounded low-cardinality code")
        self._gap_count += 1
        if self._gap_started_at is None:
            self._gap_started_at = wall_time
        self._gap_ended_at = wall_time
        self._gap_reason = reason_code
        self._gap_open = True

    def status(self) -> dict[str, object]:
        return {
            "state": self._state.value,
            "capture_gap_count": self._gap_count,
            "capture_gap_started_at": self._gap_started_at,
            "capture_gap_ended_at": self._gap_ended_at,
            "capture_gap_reason": self._gap_reason,
            "would_reject_count": self._would_deny_count,
        }

    def _deny(self, reason: str) -> CaptureAdmission:
        self._would_deny_count += 1
        return CaptureAdmission(False, True, reason, self._state)


_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def evaluate_pressure(
    previous: ResourcePolicyState,
    signals: ResourceSignals,
    config: PressureConfig,
    *,
    now: float,
    background_token_limit: int,
) -> PressureStep:
    """Advance one state transition from current facts and prior control state."""
    now = _finite(now, "now")
    if (
        isinstance(background_token_limit, bool)
        or not isinstance(background_token_limit, int)
        or background_token_limit < 0
    ):
        raise ValueError("background_token_limit must be a non-negative integer")
    depth = _optional_count(signals.queue_depth, "queue_depth")
    oldest = _optional_nonnegative(signals.oldest_wait_seconds, "oldest_wait_seconds")
    valid = depth is not None or oldest is not None
    if not valid:
        unknown = ResourcePolicyState(state=PressureState.UNKNOWN)
        return _step(previous, unknown, "metrics_missing", valid=False)

    high = (depth is not None and depth >= config.enter_queue_depth) or (
        oldest is not None and oldest >= config.enter_oldest_wait_seconds
    )
    # With no queued work there is no oldest waiter to age; queue_depth=0 is an
    # explicit empty queue, while an absent depth remains unknown.
    low_wait = (depth == 0) or (
        oldest is not None and oldest <= config.recover_oldest_wait_seconds
    )
    low = (
        depth is not None
        and depth <= config.recover_queue_depth
        and low_wait
    )

    current = previous.state
    if current is PressureState.UNKNOWN:
        current = PressureState.NORMAL
        previous = ResourcePolicyState(
            state=current,
            background_tokens=background_token_limit,
        )

    if current is PressureState.NORMAL:
        count = previous.consecutive_high_windows + 1 if high else 0
        if count >= config.enter_consecutive_windows:
            next_state = ResourcePolicyState(
                state=PressureState.CONSTRAINED,
                consecutive_high_windows=count,
                background_tokens=0,
                last_aged_backend_at=now,
            )
            return _step(previous, next_state, "pressure_high", valid=True)
        next_state = ResourcePolicyState(
            state=PressureState.NORMAL,
            consecutive_high_windows=count,
            background_tokens=background_token_limit,
        )
        return _step(previous, next_state, "pressure_high_observed" if high else "within_limit", valid=True)

    if current is PressureState.CONSTRAINED:
        if high:
            next_state = ResourcePolicyState(
                state=PressureState.CONSTRAINED,
                consecutive_high_windows=previous.consecutive_high_windows,
                background_tokens=0,
                last_aged_backend_at=previous.last_aged_backend_at,
            )
            return _step(previous, next_state, "pressure_high", valid=True)
        if not low:
            next_state = ResourcePolicyState(
                state=PressureState.CONSTRAINED,
                consecutive_high_windows=0,
                background_tokens=0,
                last_aged_backend_at=previous.last_aged_backend_at,
            )
            return _step(previous, next_state, "recovery_conditions_unproven", valid=True)
        low_since = previous.low_since if previous.low_since is not None else now
        if now - low_since >= config.recover_stable_seconds:
            next_state = ResourcePolicyState(
                state=PressureState.RECOVERING,
                low_since=low_since,
                normal_since=now,
                last_token_at=now,
                background_tokens=0,
            )
            return _step(previous, next_state, "recovery_started", valid=True)
        next_state = ResourcePolicyState(
            state=PressureState.CONSTRAINED,
            low_since=low_since,
            background_tokens=0,
            last_aged_backend_at=previous.last_aged_backend_at,
        )
        return _step(previous, next_state, "recovery_stabilizing", valid=True)

    if current is PressureState.RECOVERING:
        if high:
            next_state = ResourcePolicyState(
                state=PressureState.CONSTRAINED,
                consecutive_high_windows=1,
                background_tokens=0,
                last_aged_backend_at=now,
            )
            return _step(previous, next_state, "pressure_rebounded", valid=True)
        if not low:
            next_state = ResourcePolicyState(
                state=PressureState.RECOVERING,
                last_token_at=now,
                background_tokens=previous.background_tokens,
                last_aged_backend_at=previous.last_aged_backend_at,
            )
            return _step(previous, next_state, "recovery_conditions_unproven", valid=True)

        normal_since = previous.normal_since if previous.normal_since is not None else now
        tokens = previous.background_tokens
        last_token_at = previous.last_token_at
        if (
            tokens < background_token_limit
            and last_token_at is not None
            and now - last_token_at >= config.background_token_interval_seconds
        ):
            # Recovery opens one fresh backend start per interval. Unused time
            # does not accumulate into a burst when a backlog worker wakes.
            tokens = min(1, tokens + 1)
            last_token_at = now
        if now - normal_since >= config.normal_stable_seconds:
            next_state = ResourcePolicyState(
                state=PressureState.NORMAL,
                consecutive_high_windows=0,
                background_tokens=background_token_limit,
            )
            return _step(previous, next_state, "recovery_complete", valid=True)
        next_state = ResourcePolicyState(
            state=PressureState.RECOVERING,
            low_since=previous.low_since,
            normal_since=normal_since,
            last_token_at=last_token_at,
            background_tokens=tokens,
        )
        return _step(previous, next_state, "recovery_ramping", valid=True)

    raise ValueError(f"unsupported pressure state: {current!r}")


def admit_background(
    previous: ResourcePolicyState,
    *,
    now: float,
    oldest_age_seconds: float | None,
    aged_after_seconds: float,
    token_interval_seconds: float,
    integrity_ok: bool,
) -> BackgroundAdmission:
    """Consume a recovery token or one constrained aged-work permit.

    Integrity is a hard gate: aging can never turn an unsafe or unknown store
    into an allowed operation. Calls in NORMAL do not consume recovery credit.
    """
    now = _finite(now, "now")
    aged_after_seconds = _finite(aged_after_seconds, "aged_after_seconds")
    token_interval_seconds = _finite(token_interval_seconds, "token_interval_seconds")
    if aged_after_seconds <= 0 or token_interval_seconds <= 0:
        raise ValueError("background admission intervals must be positive")
    if not isinstance(integrity_ok, bool):
        raise ValueError("integrity_ok must be a boolean")
    age = _optional_nonnegative(oldest_age_seconds, "oldest_age_seconds")
    if not integrity_ok:
        return BackgroundAdmission(False, "integrity_untrusted", previous)
    if previous.state is PressureState.NORMAL:
        return BackgroundAdmission(True, "within_limit", previous)
    if previous.state is PressureState.CONSTRAINED:
        if age is None or age < aged_after_seconds:
            return BackgroundAdmission(False, "pressure_constrained", previous)
        last = previous.last_aged_backend_at
        if last is not None and now - last < token_interval_seconds:
            return BackgroundAdmission(False, "aged_share_cooling", previous)
        updated = replace(previous, last_aged_backend_at=now)
        return BackgroundAdmission(True, "aged_backend_share", updated)
    if previous.state is PressureState.RECOVERING:
        if previous.background_tokens <= 0:
            return BackgroundAdmission(False, "recovery_token_unavailable", previous)
        updated = replace(previous, background_tokens=previous.background_tokens - 1)
        return BackgroundAdmission(True, "recovery_token", updated)
    return BackgroundAdmission(False, "pressure_unknown", previous)


def _step(
    previous: ResourcePolicyState,
    next_state: ResourcePolicyState,
    reason_code: str,
    *,
    valid: bool,
) -> PressureStep:
    return PressureStep(
        next_state=next_state,
        reason_code=reason_code,
        changed=next_state.state is not previous.state,
        valid_sample=valid,
    )


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _optional_count(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer or None")
    return value


def _optional_nonnegative(value: object, name: str) -> float | None:
    if value is None:
        return None
    result = _finite(value, name)
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return result
