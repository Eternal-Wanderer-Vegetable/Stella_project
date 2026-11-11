# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Deterministic wall/monotonic time and timer driver for offline replays.

The driver composes the existing business-time ``VirtualClock`` with a virtual
monotonic counter and an asyncio-compatible ``call_later`` queue.  Advancing to
an event timestamp fires timers due at or before that instant first; callers
then dispatch the event.  PITCH turns remain turn units and are never converted
to elapsed time by this module.
"""

from __future__ import annotations

import asyncio
import heapq
import inspect
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.evaluation.clock import VirtualClock


@dataclass(order=True)
class _ScheduledTimer:
    deadline: float
    sequence: int
    handle: "VirtualTimerHandle" = field(compare=False)


class VirtualTimerHandle:
    """Small TimerHandle-compatible cancellation token."""

    def __init__(self, callback: Callable[..., Any], args: tuple[Any, ...]) -> None:
        self.callback = callback
        self.args = args
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def cancelled(self) -> bool:
        return self._cancelled


class VirtualTimeDriver:
    """Drive virtual UTC, monotonic time, and scheduled callbacks together."""

    def __init__(
        self,
        *,
        start: datetime | None = None,
        monotonic_start: float = 0.0,
    ) -> None:
        if not math.isfinite(monotonic_start):
            raise ValueError("monotonic_start must be finite")
        self.wall_clock = VirtualClock(start=start)
        self._monotonic = float(monotonic_start)
        self._timers: list[_ScheduledTimer] = []
        self._sequence = 0

    def now(self) -> datetime:
        """Return the current aware UTC business time."""
        return self.wall_clock.now()

    def monotonic(self) -> float:
        """Return the replay's monotonic seconds."""
        return self._monotonic

    def call_later(
        self, delay: float, callback: Callable[..., Any], *args: Any
    ) -> VirtualTimerHandle:
        """Schedule a callback relative to virtual monotonic time."""
        delay = float(delay)
        if not math.isfinite(delay):
            raise ValueError("timer delay must be finite")
        handle = VirtualTimerHandle(callback, args)
        self._sequence += 1
        heapq.heappush(
            self._timers,
            _ScheduledTimer(self._monotonic + max(0.0, delay), self._sequence, handle),
        )
        return handle

    @property
    def pending_timer_count(self) -> int:
        return sum(not item.handle.cancelled() for item in self._timers)

    async def advance(self, seconds: float) -> None:
        """Advance both clocks, running every timer due by the target instant.

        When the caller dispatches a message after this method returns, timers
        at exactly that message's arrival time have already fired.
        """
        seconds = float(seconds)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("virtual time can only advance by a finite non-negative duration")
        target = self._monotonic + seconds
        callbacks = 0
        while self._timers and self._timers[0].deadline <= target:
            timer = heapq.heappop(self._timers)
            if timer.handle.cancelled():
                continue
            self._advance_to(timer.deadline)
            result = timer.handle.callback(*timer.handle.args)
            if inspect.isawaitable(result):
                await result
            callbacks += 1
            if callbacks > 10000:
                raise RuntimeError("virtual timer callback limit exceeded")
            await self._settle_ready_tasks()
        self._advance_to(target)
        await self._settle_ready_tasks()

    async def _settle_ready_tasks(self) -> None:
        # Timer callbacks often create a task (as asyncio.call_later does in
        # OpportunityManager); let those immediately-ready tasks finish before
        # returning control to the replay event dispatcher.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    def _advance_to(self, target: float) -> None:
        if target < self._monotonic:
            raise ValueError("virtual monotonic time cannot move backwards")
        self.wall_clock.advance(target - self._monotonic)
        self._monotonic = target


__all__ = ["VirtualTimeDriver", "VirtualTimerHandle"]
