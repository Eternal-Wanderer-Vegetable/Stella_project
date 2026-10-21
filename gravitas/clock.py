# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Control time and performance time are intentionally separate."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Protocol


class ControlClock(Protocol):
    """Monotonic clock for TTLs, deadlines, cooldowns, and policy leases."""

    @property
    def clock_id(self) -> str: ...

    def now(self) -> float: ...


@dataclass(frozen=True, slots=True)
class SystemControlClock:
    """Process-local clock; its id prevents comparing deadlines across boots."""

    clock_id: str = field(default_factory=lambda: f"control-{uuid.uuid4().hex}")

    def now(self) -> float:
        return time.monotonic()


@dataclass(frozen=True, slots=True)
class PerformanceClock:
    """Real duration measurement, unaffected by replayed control time."""

    def now(self) -> float:
        return time.perf_counter()


class ManualControlClock:
    """Deterministic control clock for contract tests and offline replay."""

    def __init__(self, start: float = 0.0, *, clock_id: str = "manual") -> None:
        self._now = self._finite(start, "start")
        if (
            not isinstance(clock_id, str)
            or not clock_id
            or clock_id != clock_id.strip()
        ):
            raise ValueError("clock_id must be a non-empty trimmed string")
        self._clock_id = clock_id

    @property
    def clock_id(self) -> str:
        return self._clock_id

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        delta = self._finite(seconds, "seconds")
        if delta < 0:
            raise ValueError("control time cannot move backwards")
        next_value = self._now + delta
        if not math.isfinite(next_value):
            raise ValueError("control time must remain finite")
        self._now = next_value
        return self._now

    @staticmethod
    def _finite(value: float, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"{name} must be a finite number")
        return result
