# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Bounded diagnostic events without chat, credential, or free-form fields."""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass
from enum import Enum


class EventKind(str, Enum):
    COLLECTOR_ERROR = "collector_error"
    FACT_REJECTED = "fact_rejected"
    METRIC_EVICTED = "metric_evicted"
    PRESSURE_TRANSITION = "pressure_transition"
    POLICY_PUBLISHED = "policy_published"
    ENFORCEMENT_REFUSED = "enforcement_refused"


@dataclass(frozen=True, slots=True)
class GravitasEvent:
    sequence: int
    observed_at: float
    kind: EventKind
    reason_code: str
    resource_id: str | None = None


class EventBuffer:
    """A finite ring of structured diagnostics with an explicit drop count."""

    def __init__(self, capacity: int = 1024) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("event capacity must be a positive integer")
        self._capacity = capacity
        self._items: deque[GravitasEvent] = deque()
        self._sequence = 0
        self._dropped = 0

    @property
    def dropped(self) -> int:
        return self._dropped

    def append(
        self,
        kind: EventKind,
        reason_code: str,
        *,
        observed_at: float,
        resource_id: str | None = None,
    ) -> GravitasEvent:
        if not isinstance(kind, EventKind):
            raise ValueError("event kind must be an EventKind")
        if not isinstance(reason_code, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", reason_code
        ):
            raise ValueError("reason_code must be a low-cardinality code")
        if resource_id is not None and (
            not isinstance(resource_id, str)
            or not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", resource_id)
        ):
            raise ValueError("resource_id must be a bounded resource label")
        if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)):
            raise ValueError("observed_at must be finite")
        observed_at = float(observed_at)
        if not math.isfinite(observed_at):
            raise ValueError("observed_at must be finite")
        if len(self._items) == self._capacity:
            self._items.popleft()
            self._dropped += 1
        self._sequence += 1
        event = GravitasEvent(
            self._sequence, observed_at, kind, reason_code, resource_id
        )
        self._items.append(event)
        return event

    def snapshot(self) -> dict[str, object]:
        return {
            "capacity": self._capacity,
            "count": len(self._items),
            "dropped": self._dropped,
            "last_sequence": self._sequence,
            "kinds": sorted({item.kind.value for item in self._items}),
        }

    def recent(self, limit: int = 32) -> tuple[GravitasEvent, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return ()
        return tuple(self._items)[-min(limit, self._capacity) :]
