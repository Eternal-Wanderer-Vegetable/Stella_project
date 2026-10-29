# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Bounded FIFO and independently scoped quota scheduling for outbound sends."""

from __future__ import annotations

import asyncio
import contextlib
import math
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar

from core.transport.capabilities import RateLimitBucket
from gravitas import deadlines as deadline_helpers
from gravitas.contracts import Deadline
from gravitas.errors import DeadlineExceeded

T = TypeVar("T")


class SchedulerAdmissionError(RuntimeError):
    """A send was not started because the scheduler rejected its admission."""

    def __init__(self, error_code: str):
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(slots=True)
class _TargetLane:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiters: int = 0


class OutboundSendScheduler:
    """Serialize each exact target and reserve all applicable quotas atomically.

    Scheduler state is process-local. A restart drops queued work and resets
    rolling-window reservations; durable delivery receipts remain the caller's
    responsibility. UNKNOWN exporter outcomes are never replayed here.
    """

    def __init__(
        self,
        *,
        max_queue_per_target: int = 32,
        max_target_lanes: int = 4096,
        max_quota_buckets: int = 4096,
        max_retry_after_seconds: float = 30.0,
    ) -> None:
        for name, value in (
            ("max_queue_per_target", max_queue_per_target),
            ("max_target_lanes", max_target_lanes),
            ("max_quota_buckets", max_quota_buckets),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.max_queue_per_target = max_queue_per_target
        self.max_target_lanes = max_target_lanes
        self.max_quota_buckets = max_quota_buckets
        if (
            isinstance(max_retry_after_seconds, bool)
            or not isinstance(max_retry_after_seconds, (int, float))
            or not math.isfinite(max_retry_after_seconds)
            or max_retry_after_seconds <= 0
        ):
            raise ValueError("max_retry_after_seconds must be finite and positive")
        self.max_retry_after_seconds = float(max_retry_after_seconds)
        self._lanes: OrderedDict[tuple[Any, ...], _TargetLane] = OrderedDict()
        self._quota_guard = asyncio.Lock()
        self._quota_events: OrderedDict[tuple[Any, ...], tuple[float, deque[float]]] = OrderedDict()

    async def run(
        self,
        target: Any,
        buckets: tuple[RateLimitBucket, ...],
        *,
        deadline: Deadline | None,
        send_window_seconds: float | None,
        operation: Callable[[Callable[..., Awaitable[None]], Deadline | None], Awaitable[T]],
    ) -> T:
        """Run one logical send within the target's fair FIFO lane."""
        effective_deadline, deadline_code = self._effective_deadline(
            target, deadline, send_window_seconds
        )
        if target.is_expired():
            raise SchedulerAdmissionError("send_window_expired")
        lane_key = self._target_key(target)
        lane = self._get_lane(lane_key)
        async with self._lane(lane, effective_deadline, deadline_code):
            self._check_budget(target, deadline, effective_deadline, deadline_code)

            async def reserve_part(*, wait_before_seconds: float = 0.0) -> None:
                await self._reserve_part(
                    target,
                    buckets,
                    wait_before_seconds=wait_before_seconds,
                    deadline=effective_deadline,
                    deadline_code=deadline_code,
                )

            return await operation(reserve_part, effective_deadline)

    @staticmethod
    def _target_key(target: Any) -> tuple[Any, ...]:
        bot, scene = target.bot, target.scene
        return (
            bot.adapter,
            bot.platform_scope,
            bot.connection_id,
            bot.self_id,
            scene.kind,
            scene.scene_id,
            scene.parent_path,
            scene.thread_id,
            target.routing_parameters,
        )

    def _get_lane(self, key: tuple[Any, ...]) -> _TargetLane:
        lane = self._lanes.get(key)
        if lane is not None:
            self._lanes.move_to_end(key)
            return lane
        if len(self._lanes) >= self.max_target_lanes:
            for stale_key, stale_lane in tuple(self._lanes.items()):
                if not stale_lane.lock.locked() and stale_lane.waiters == 0:
                    del self._lanes[stale_key]
                    if len(self._lanes) < self.max_target_lanes:
                        break
        if len(self._lanes) >= self.max_target_lanes:
            raise SchedulerAdmissionError("send_scheduler_capacity")
        lane = _TargetLane()
        self._lanes[key] = lane
        return lane

    @contextlib.asynccontextmanager
    async def _lane(
        self,
        lane: _TargetLane,
        deadline: Deadline | None,
        deadline_code: str,
    ):
        waiting = lane.lock.locked() or lane.waiters > 0
        if waiting:
            if lane.waiters >= self.max_queue_per_target:
                raise SchedulerAdmissionError("send_queue_full")
            lane.waiters += 1
        try:
            if deadline is None:
                async with lane.lock:
                    if waiting:
                        lane.waiters -= 1
                        waiting = False
                    yield
            else:
                try:
                    async with deadline_helpers.lock_with_deadline(
                        lane.lock, deadline, phase="send.queue"
                    ):
                        if waiting:
                            lane.waiters -= 1
                            waiting = False
                        yield
                except DeadlineExceeded as exc:
                    raise SchedulerAdmissionError(deadline_code) from exc
        finally:
            if waiting:
                lane.waiters -= 1
            if not lane.lock.locked() and lane.waiters == 0:
                for key, item in tuple(self._lanes.items()):
                    if item is lane:
                        del self._lanes[key]
                        break

    def _effective_deadline(
        self,
        target: Any,
        turn_deadline: Deadline | None,
        send_window_seconds: float | None,
    ) -> tuple[Deadline | None, str]:
        clock = deadline_helpers.system_control_clock()
        now = clock.now()
        bounds: list[tuple[float, str]] = []
        if turn_deadline is not None:
            turn_remaining = deadline_helpers.remaining(turn_deadline, clock=clock)
            if turn_remaining <= 0:
                raise SchedulerAdmissionError("turn_deadline")
            bounds.append((turn_remaining, "turn_deadline"))
        if send_window_seconds is not None:
            if not math.isfinite(send_window_seconds) or send_window_seconds <= 0:
                raise SchedulerAdmissionError("send_window_expired")
            bounds.append((float(send_window_seconds), "send_window_expired"))
        target_remaining = self._target_remaining(target)
        if target_remaining is not None:
            if target_remaining <= 0:
                raise SchedulerAdmissionError("send_window_expired")
            bounds.append((target_remaining, "send_window_expired"))
        if not bounds:
            return None, "turn_deadline"
        budget, error_code = min(bounds, key=lambda bound: bound[0])
        return Deadline(now + budget, clock.clock_id), error_code

    @staticmethod
    def _target_remaining(target: Any) -> float | None:
        if not target.expires_at_utc:
            return None
        try:
            expiry = datetime.fromisoformat(target.expires_at_utc.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if expiry.tzinfo is None:
            return 0.0
        return max(0.0, (expiry - datetime.now(timezone.utc)).total_seconds())

    def _check_budget(
        self,
        target: Any,
        turn_deadline: Deadline | None,
        effective_deadline: Deadline | None,
        deadline_code: str,
    ) -> None:
        if target.is_expired():
            raise SchedulerAdmissionError("send_window_expired")
        if turn_deadline is not None and deadline_helpers.remaining(turn_deadline) <= 0:
            raise SchedulerAdmissionError("turn_deadline")
        if effective_deadline is not None and deadline_helpers.remaining(effective_deadline) <= 0:
            raise SchedulerAdmissionError(deadline_code)

    @staticmethod
    def _bucket_key(target: Any, bucket: RateLimitBucket) -> tuple[Any, ...]:
        bot, scene = target.bot, target.scene
        identity = (bot.adapter, bot.platform_scope, bucket.category, bucket.name)
        if bucket.scope == "adapter":
            return ("adapter", *identity)
        connection = (*identity, bot.connection_id, bot.self_id)
        if bucket.scope == "connection":
            return ("connection", *connection)
        scene_key = (
            "scene",
            *connection,
            scene.kind,
            scene.scene_id,
            scene.parent_path,
            scene.thread_id,
        )
        if bucket.scope == "scene":
            return scene_key
        return (*scene_key, "target", target.routing_parameters)

    async def _reserve_part(
        self,
        target: Any,
        buckets: tuple[RateLimitBucket, ...],
        *,
        wait_before_seconds: float,
        deadline: Deadline | None,
        deadline_code: str,
    ) -> None:
        if wait_before_seconds < 0 or not math.isfinite(wait_before_seconds):
            raise SchedulerAdmissionError("invalid_retry_after")
        if wait_before_seconds > self.max_retry_after_seconds:
            raise SchedulerAdmissionError("retry_after_exceeds_budget")
        if wait_before_seconds:
            await self._wait(wait_before_seconds, target, deadline, deadline_code)
        keys = tuple((self._bucket_key(target, bucket), bucket) for bucket in buckets)
        while True:
            self._check_budget(target, None, deadline, deadline_code)
            now = asyncio.get_running_loop().time()
            async with self._quota_guard:
                for key, bucket in keys:
                    state = self._quota_events.get(key)
                    if state is not None and bucket.window_seconds > state[0]:
                        self._quota_events[key] = (bucket.window_seconds, state[1])
                self._prune_quota_events(now)
                waits: list[float] = []
                for key, bucket in keys:
                    state = self._quota_events.get(key)
                    events = state[1] if state is not None else None
                    if events is not None and len(events) >= bucket.limit:
                        wait_window = max(state[0], bucket.window_seconds) if state is not None else bucket.window_seconds
                        waits.append(max(0.0, events[0] + wait_window - now))
                if not waits:
                    missing = [key for key, _ in keys if key not in self._quota_events]
                    if len(self._quota_events) + len(missing) > self.max_quota_buckets:
                        raise SchedulerAdmissionError("send_quota_state_full")
                    for key, bucket in keys:
                        state = self._quota_events.get(key)
                        if state is None:
                            events = deque()
                            self._quota_events[key] = (bucket.window_seconds, events)
                        else:
                            window, events = state
                            self._quota_events[key] = (max(window, bucket.window_seconds), events)
                        events.append(now)
                        self._quota_events.move_to_end(key)
                    return
                wait_seconds = max(waits)
            await self._wait(wait_seconds, target, deadline, deadline_code)

    def _prune_quota_events(self, now: float) -> None:
        for key, (window, events) in tuple(self._quota_events.items()):
            cutoff = now - window
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                del self._quota_events[key]

    async def _wait(
        self,
        seconds: float,
        target: Any,
        deadline: Deadline | None,
        deadline_code: str,
    ) -> None:
        if seconds <= 0:
            return
        target_remaining = self._target_remaining(target)
        try:
            if deadline is not None:
                timeout_cap = target_remaining
                await deadline_helpers.run_with_deadline(
                    lambda: asyncio.sleep(seconds),
                    deadline,
                    phase="send.quota_wait",
                    timeout_cap=timeout_cap,
                )
            elif target_remaining is not None:
                await asyncio.wait_for(asyncio.sleep(seconds), timeout=target_remaining)
            else:
                await asyncio.sleep(seconds)
        except DeadlineExceeded as exc:
            raise SchedulerAdmissionError(deadline_code) from exc
        except TimeoutError as exc:
            if target.is_expired():
                raise SchedulerAdmissionError("send_window_expired") from exc
            raise
        if target.is_expired():
            raise SchedulerAdmissionError("send_window_expired")


__all__ = ["OutboundSendScheduler", "SchedulerAdmissionError"]
