# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Deterministic ordering for evaluation messages and virtual timer events.

Business time is advanced only through the injected ``Clock``. Events at the
same instant use a frozen order: timers run before messages, then source
sequence and event id break ties. This module does not schedule real asyncio
callbacks or alter production timers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from core.evaluation.clock import Clock

EventKind = Literal["timer", "message"]


@dataclass(frozen=True)
class ReplayEvent:
    event_id: str
    at: datetime
    kind: EventKind
    sequence: int
    payload: Mapping[str, Any]


def replay_events(
    events: Iterable[ReplayEvent],
    *,
    clock: Clock,
    handle: Callable[[ReplayEvent], None],
) -> list[str]:
    """Advance business time and dispatch events in a deterministic order.

    The original sequence is preserved for events of the same kind and time.
    Input timestamps must be timezone aware; silently assuming host-local time
    would make replay fingerprints and timer boundaries machine dependent.
    """
    materialized = list(events)
    ids: set[str] = set()
    for event in materialized:
        if not event.event_id:
            raise ValueError("replay event id must not be empty")
        if event.event_id in ids:
            raise ValueError(f"duplicate replay event id: {event.event_id}")
        ids.add(event.event_id)
        if event.kind not in ("timer", "message"):
            raise ValueError(f"unsupported replay event kind: {event.kind}")
        if event.sequence < 0:
            raise ValueError("replay event sequence must be non-negative")
        if event.at.tzinfo is None or event.at.utcoffset() is None:
            raise ValueError(f"replay event {event.event_id} has a naive timestamp")

    priority = {"timer": 0, "message": 1}
    ordered = sorted(
        materialized,
        key=lambda event: (
            event.at.astimezone(timezone.utc),
            priority[event.kind],
            event.sequence,
            event.event_id,
        ),
    )
    dispatched: list[str] = []
    for event in ordered:
        clock.advance_to(event.at)
        handle(event)
        dispatched.append(event.event_id)
    return dispatched


__all__ = ["EventKind", "ReplayEvent", "replay_events"]
