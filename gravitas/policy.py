# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Pure per-resource pressure hysteresis; this module never performs admission."""

from __future__ import annotations

import math
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class PressureStep:
    next_state: ResourcePolicyState
    reason_code: str
    changed: bool
    valid_sample: bool


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
            )
            return _step(previous, next_state, "pressure_high", valid=True)
        if not low:
            next_state = ResourcePolicyState(
                state=PressureState.CONSTRAINED,
                consecutive_high_windows=0,
                background_tokens=0,
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
        )
        return _step(previous, next_state, "recovery_stabilizing", valid=True)

    if current is PressureState.RECOVERING:
        if high:
            next_state = ResourcePolicyState(
                state=PressureState.CONSTRAINED,
                consecutive_high_windows=1,
                background_tokens=0,
            )
            return _step(previous, next_state, "pressure_rebounded", valid=True)
        if not low:
            next_state = ResourcePolicyState(
                state=PressureState.RECOVERING,
                last_token_at=now,
                background_tokens=previous.background_tokens,
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
            tokens += 1
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
