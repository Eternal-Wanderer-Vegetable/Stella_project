# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Deadline-aware await and lock helpers for turn execution."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TypeVar

from gravitas.clock import ControlClock, system_control_clock
from gravitas.contracts import Deadline
from gravitas.errors import DeadlineExceeded

T = TypeVar("T")


def remaining(deadline: Deadline, *, clock: ControlClock | None = None) -> float:
    """Return total turn time remaining on the clock that owns the deadline."""
    resolved_clock = clock or system_control_clock()
    return deadline.remaining(
        resolved_clock.now(), clock_id=resolved_clock.clock_id
    )


def raise_if_expired(
    deadline: Deadline,
    *,
    phase: str,
    clock: ControlClock | None = None,
) -> None:
    """Raise the dedicated control signal when the turn budget is exhausted."""
    if remaining(deadline, clock=clock) <= 0:
        raise DeadlineExceeded(phase)


async def run_with_deadline(
    operation: Callable[[], Awaitable[T]],
    deadline: Deadline,
    *,
    phase: str,
    timeout_cap: float | None = None,
    clock: ControlClock | None = None,
    on_task: Callable[[asyncio.Future[T]], None] | None = None,
) -> T:
    """Run one awaitable under total time and an optional legacy phase cap.

    ``operation`` is lazy so an already expired turn never starts new work.
    A timeout caused by ``timeout_cap`` remains ``asyncio.TimeoutError`` for
    legacy fallback handling; a timeout caused by the total deadline becomes
    ``DeadlineExceeded``. Exceptions raised by the operation itself propagate.
    """
    resolved_clock = clock or system_control_clock()
    total_remaining = remaining(deadline, clock=resolved_clock)
    if total_remaining <= 0:
        raise DeadlineExceeded(phase)

    total_is_limit = timeout_cap is None
    timeout = total_remaining
    if timeout_cap is not None:
        phase_cap = float(timeout_cap)
        total_is_limit = total_remaining <= phase_cap
        timeout = min(total_remaining, phase_cap)
        if phase_cap <= 0:
            raise asyncio.TimeoutError

    task = asyncio.ensure_future(operation())
    if on_task is not None:
        on_task(task)
    try:
        result = await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError as exc:
        # An operation may itself raise TimeoutError. Only wait_for's own
        # cancellation marks this task cancelled.
        if task.cancelled() and (
            total_is_limit or remaining(deadline, clock=resolved_clock) <= 0
        ):
            raise DeadlineExceeded(phase) from exc
        raise

    if remaining(deadline, clock=resolved_clock) <= 0:
        raise DeadlineExceeded(phase)
    return result


@contextlib.asynccontextmanager
async def lock_with_deadline(
    lock,
    deadline: Deadline,
    *,
    phase: str,
    clock: ControlClock | None = None,
):
    """Acquire an asyncio-style lock before expiry and release it exactly once."""
    resolved_clock = clock or system_control_clock()
    total_remaining = remaining(deadline, clock=resolved_clock)
    if total_remaining <= 0:
        raise DeadlineExceeded(phase)

    acquire_task = asyncio.create_task(lock.acquire())
    acquired = False
    try:
        try:
            acquired = bool(await asyncio.wait_for(acquire_task, timeout=total_remaining))
        except asyncio.TimeoutError as exc:
            if acquire_task.cancelled() or remaining(deadline, clock=resolved_clock) <= 0:
                raise DeadlineExceeded(phase) from exc
            raise
        if not acquired:
            raise DeadlineExceeded(phase)
        try:
            raise_if_expired(deadline, phase=phase, clock=resolved_clock)
        except BaseException:
            lock.release()
            acquired = False
            raise
        yield
    finally:
        if acquired:
            lock.release()
