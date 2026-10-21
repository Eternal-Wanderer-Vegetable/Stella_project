# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Bounded, low-cardinality observations for controller policy inputs."""

from __future__ import annotations

import math
from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchedulerSample:
    observed_at: float
    waiting: int | None
    holding: int | None
    limit: int | None
    oldest_wait_seconds: float | None = None
    interactive_wait_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ResourceMetrics:
    resource_id: str
    sample_count: int
    waiting: int | None
    holding: int | None
    limit: int | None
    oldest_wait_seconds: float | None
    p95_interactive_wait_seconds: float | None
    p95_sample_count: int
    incomplete: bool


class BoundedMetrics:
    """Keep a bounded rolling window; missing values never become zeroes."""

    def __init__(
        self,
        *,
        max_samples_per_resource: int = 512,
        window_seconds: float = 60.0,
        max_resources: int = 256,
    ) -> None:
        if max_samples_per_resource < 1 or max_resources < 1:
            raise ValueError("metric bounds must be positive")
        if not _finite_positive(window_seconds):
            raise ValueError("window_seconds must be finite and positive")
        self._capacity = max_samples_per_resource
        self._window = float(window_seconds)
        self._max_resources = max_resources
        self._samples: OrderedDict[str, deque[SchedulerSample]] = OrderedDict()
        self._resource_incomplete: set[str] = set()
        self._dropped_samples = 0
        self._evicted_resources = 0

    @property
    def dropped_samples(self) -> int:
        return self._dropped_samples

    @property
    def evicted_resources(self) -> int:
        return self._evicted_resources

    @property
    def resource_ids(self) -> tuple[str, ...]:
        return tuple(self._samples)

    def record(
        self,
        resource_id: str,
        *,
        observed_at: float,
        waiting: int | None,
        holding: int | None,
        limit: int | None,
        oldest_wait_seconds: float | None = None,
        interactive_wait_seconds: float | None = None,
    ) -> bool:
        resource_id = _resource_id(resource_id)
        observed_at = _finite(observed_at, "observed_at")
        waiting = _count(waiting, "waiting")
        holding = _count(holding, "holding")
        limit = _count(limit, "limit")
        oldest_wait_seconds = _optional_nonnegative(oldest_wait_seconds, "oldest_wait_seconds")
        interactive_wait_seconds = _optional_nonnegative(
            interactive_wait_seconds, "interactive_wait_seconds"
        )

        samples = self._samples.get(resource_id)
        if samples is None:
            if len(self._samples) >= self._max_resources:
                inactive = next(
                    (
                        name
                        for name, values in self._samples.items()
                        if not values or values[-1].holding in (None, 0)
                    ),
                    None,
                )
                if inactive is None:
                    self._dropped_samples += 1
                    return False
                self._samples.pop(inactive)
                self._resource_incomplete.discard(inactive)
                self._evicted_resources += 1
            samples = deque()
            self._samples[resource_id] = samples
        else:
            self._samples.move_to_end(resource_id)

        if len(samples) >= self._capacity:
            samples.popleft()
            self._resource_incomplete.add(resource_id)
            self._dropped_samples += 1
        samples.append(
            SchedulerSample(
                observed_at=observed_at,
                waiting=waiting,
                holding=holding,
                limit=limit,
                oldest_wait_seconds=oldest_wait_seconds,
                interactive_wait_seconds=interactive_wait_seconds,
            )
        )
        self._prune(resource_id, observed_at)
        return True

    def snapshot(self, resource_id: str, *, now: float) -> ResourceMetrics | None:
        resource_id = _resource_id(resource_id)
        now = _finite(now, "now")
        samples = self._samples.get(resource_id)
        if samples is None:
            return None
        self._prune(resource_id, now)
        if not samples:
            return None
        latest = samples[-1]
        wait_samples = sorted(
            item.interactive_wait_seconds
            for item in samples
            if item.interactive_wait_seconds is not None
        )
        p95 = None
        if len(wait_samples) >= 20:
            p95 = wait_samples[max(0, math.ceil(0.95 * len(wait_samples)) - 1)]
        self._samples.move_to_end(resource_id)
        return ResourceMetrics(
            resource_id=resource_id,
            sample_count=len(samples),
            waiting=latest.waiting,
            holding=latest.holding,
            limit=latest.limit,
            oldest_wait_seconds=latest.oldest_wait_seconds,
            p95_interactive_wait_seconds=p95,
            p95_sample_count=len(wait_samples),
            incomplete=resource_id in self._resource_incomplete,
        )

    def _prune(self, resource_id: str, now: float) -> None:
        samples = self._samples.get(resource_id)
        if samples is None:
            return
        cutoff = now - self._window
        while samples and samples[0].observed_at < cutoff:
            samples.popleft()


def _resource_id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("resource_id must be a non-empty trimmed string")
    if len(value) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("resource_id is invalid")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _finite_positive(value: object) -> bool:
    try:
        return _finite(value, "value") > 0
    except ValueError:
        return False


def _count(value: object, name: str) -> int | None:
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
