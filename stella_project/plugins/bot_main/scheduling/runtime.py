# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""租约 worker 运行时：认领到期运行 → 门控 → 生成 → 投递（计划 §6.4）。

一个调度库同时只有一个活跃 worker（``worker_lease`` 单行租约，TTL 内续租；
过期即视为死亡，其它进程可接管）。worker 的每一轮（tick）：

1. 抢/续 worker 租约，顺带做租约恢复（过期 claimed/running/ready 回队、
   过期 ``sending`` 判 ``delivery_unknown``）；
2. 巡检 active 任务的 Cron：把到期的触发入队（幂等键去重）。错过的触发按
   任务策略补跑——``latest`` 只补最近一次（agent 默认），``all`` 逐个补但
   每轮封顶（reminder 默认；超过上限的更旧触发放弃并告警）；
3. 逐条认领并执行（单 worker 串行；群内再经**网关共享的每群锁**与 @ 回复 /
   主动发言互斥，计划 §3「inject the existing group lock at the boundary」）。

执行序列（一次运行）：mark_running → 严格门控（拒绝记 skipped）→
reminder 直投 / agent 有界生成 →  delivery（ready→sending→sent/unknown）。
agent 的取消检查点在每轮模型调用与工具调用前重读运行与任务的修订/状态——
编辑、暂停、取消对在途运行的 fence 落在这里。

优雅停止：停止新认领，等当前运行收尾（受 ``stop_grace_seconds`` 上界），
释放 worker 租约。测试入口是 :meth:`tick_once`（不依赖真实睡眠）。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from nonebot import logger

from memory.proactive_gate import can_speak_for_scheduled

from .agent import AgentRunLimits, ScheduledAgentRunner, TaskCancelledError
from .context import build_scheduled_context
from .cron import CronError, CronSchedule, parse_cron
from .delivery import DeliveryService, render_reminder
from .models import (
    CoalesceMode,
    Run,
    RunState,
    Task,
    TaskMode,
    TaskStatus,
    utc_now,
)
from .store import TaskStore

# 单任务单轮补跑的出现上限：stop 几天后的 reminder 也不会一口气补几十条
_MAX_MISSED_PER_TICK = 20


class SchedulerRuntime:
    """调度库的租约 worker。依赖全部构造注入；无真实环境也可完整测试。"""

    def __init__(
        self,
        *,
        store: TaskStore,
        delivery: DeliveryService,
        agent_runner: ScheduledAgentRunner | None = None,
        group_locks: dict[int, asyncio.Lock] | None = None,
        worker_id: str = "",
        lease_ttl_seconds: float = 300.0,
        tick_interval_seconds: float = 30.0,
        daily_group_run_cap: int = 0,
        context_max_chars: int = 1200,
        stop_grace_seconds: float = 30.0,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.store = store
        self.delivery = delivery
        self.agent_runner = agent_runner
        self.group_locks: dict[int, asyncio.Lock] = (
            group_locks if group_locks is not None else defaultdict(asyncio.Lock)
        )
        self.worker_id = worker_id or f"worker-{id(self):x}"
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.tick_interval_seconds = max(float(tick_interval_seconds), 1.0)
        self.daily_group_run_cap = int(daily_group_run_cap)
        self.context_max_chars = int(context_max_chars)
        self.stop_grace_seconds = float(stop_grace_seconds)
        self._clock = clock
        self._stop_event: asyncio.Event | None = None
        self._loop_task: asyncio.Task | None = None
        # task_id -> 下一次应触发的 UTC 时刻（内存游标；重启后从 last_run 重建）
        self._cursors: dict[str, datetime] = {}
        # task_id -> (revision, expr, tz, CronSchedule)：解析缓存，修订变化即失效
        self._schedule_cache: dict[str, tuple[int, str, str, CronSchedule]] = {}

    # ── 生命周期 ─────────────────────────────────────────
    async def start(self) -> None:
        """启动 worker 循环（后台任务）。抢不到租约时保持待命、每 tick 重试。"""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(
            self._loop(), name=f"scheduling-worker-{self.worker_id}"
        )
        logger.info(
            f"⏰ [Scheduling] worker {self.worker_id} 已启动（tick "
            f"{self.tick_interval_seconds:.0f}s，租约 TTL {self.lease_ttl_seconds:.0f}s）"
        )

    async def stop(self) -> None:
        """优雅停止：停新认领、等当前运行收尾、释放租约。"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._loop_task is None:
            return
        try:
            await asyncio.wait_for(self._loop_task, timeout=self.stop_grace_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                f"⚠️ [Scheduling] worker {self.worker_id} 停止超时"
                f"（>{self.stop_grace_seconds:.0f}s），放弃等待；在途运行由租约恢复接管"
            )
        except asyncio.CancelledError:
            pass
        self._loop_task = None
        self._stop_event = None
        self.store.release_worker_lease(self.worker_id)
        logger.info(f"⏰ [Scheduling] worker {self.worker_id} 已停止")

    async def _loop(self) -> None:
        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                await self.tick_once()
            except asyncio.CancelledError:
                return
            except Exception as e:
                # 单轮失败不拖垮 worker（与 consolidation_drain_job 同哲学）
                logger.warning(f"⚠️ [Scheduling] tick 异常（下一轮重试）: {e}")
            # 可中断睡眠：stop() 置位事件立即醒来，不等满 tick 间隔
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.tick_interval_seconds
                )

    # ── 单轮巡检（测试直接驱动） ─────────────────────────
    async def tick_once(self) -> int:
        """跑一轮：租约 → 恢复 → 入队 → 认领执行。返回本轮执行的运行数。

        没抢到 worker 租约时返回 -1（另一个 worker 活着，本实例待命）。
        """
        now = self._clock()
        if not self.store.acquire_worker_lease(
            self.worker_id, ttl_seconds=self.lease_ttl_seconds, now=now
        ):
            return -1
        self.store.recover_expired_leases(now=now)
        self._enqueue_due_occurrences(now)
        executed = 0
        while self._stop_event is None or not self._stop_event.is_set():
            run = self.store.claim_next_run(
                self.worker_id,
                now=self._clock(),
                lease_seconds=self.lease_ttl_seconds,
                daily_group_run_cap=self.daily_group_run_cap,
            )
            if run is None:
                break
            try:
                await self._execute(run)
            except Exception as e:
                logger.error(
                    f"❌ [Scheduling] 运行 {run.run_id[:8]} 执行异常: {e}"
                )
                self.store.transition_run(
                    run.run_id, self.worker_id,
                    from_states=(RunState.CLAIMED, RunState.RUNNING),
                    to_state=RunState.FAILED, error=f"runtime: {e}"[:200],
                )
            executed += 1
            # 续 worker 租约：一条长运行不应让本 worker 丢掉租约
            self.store.renew_worker_lease(
                self.worker_id, ttl_seconds=self.lease_ttl_seconds, now=self._clock()
            )
        return executed

    # ── 到期触发入队（错过补跑） ─────────────────────────
    def _enqueue_due_occurrences(self, now: datetime) -> None:
        for task in self.store.list_active_tasks():
            schedule = self._schedule_of(task)
            if schedule is None:
                continue
            cursor = self._cursors.get(task.task_id)
            if cursor is None:
                # 重启/首见：从上次触发缓存（或创建时刻）重建游标
                base = task.last_run_utc or task.created_at or now
                cursor = schedule.next_fire(base) or now
            missed: list[datetime] = []
            probe = cursor
            while probe is not None and probe <= now and len(missed) < _MAX_MISSED_PER_TICK + 1:
                missed.append(probe)
                probe = schedule.next_fire(probe)
            if not missed:
                self._cursors[task.task_id] = cursor
                continue
            dropped = max(0, len(missed) - _MAX_MISSED_PER_TICK)
            if dropped:
                logger.warning(
                    f"⚠️ [Scheduling] 任务 {task.task_id[:8]} 错过 {len(missed)} 次触发，"
                    f"本轮先补 {_MAX_MISSED_PER_TICK} 次，其余随后续 tick 继续"
                )
            if task.policy.get("coalesce") == CoalesceMode.LATEST.value:
                # latest：只补最近一次，更旧的错过触发就此放弃（cursor 越过全部）
                batch = missed[-1:]
            else:
                batch = missed[:_MAX_MISSED_PER_TICK]
            # 逐个入队。每任务同时只有一个活跃运行（部分唯一索引），所以 "all"
            # 的后续触发要在当前运行结束后由下一个 tick 续补：入队失败（任务忙）
            # 时游标停在当前 fire，不越过它。
            advanced_to: datetime | None = None
            for fire in batch:
                if self.store.insert_run(task.task_id, scheduled_for=fire, now=now):
                    advanced_to = fire
                else:
                    break
            if advanced_to is None:
                self._cursors[task.task_id] = cursor
                continue
            following = schedule.next_fire(advanced_to)
            self._cursors[task.task_id] = following or advanced_to
            self.store.record_task_fired(
                task.task_id, last_run_utc=advanced_to, next_run_utc=following
            )

    def _schedule_of(self, task: Task) -> CronSchedule | None:
        cached = self._schedule_cache.get(task.task_id)
        if cached is not None and cached[0] == task.revision:
            return cached[3]
        try:
            schedule = parse_cron(task.cron_expr, task.timezone)
        except CronError as e:
            # 创建/编辑时已校验；这里兜底（库被手改）——跳过并告警，不拖垮巡检
            logger.error(f"❌ [Scheduling] 任务 {task.task_id[:8]} Cron 解析失败: {e}")
            return None
        self._schedule_cache[task.task_id] = (
            task.revision, task.cron_expr, task.timezone, schedule,
        )
        return schedule

    # ── 运行执行 ─────────────────────────────────────────
    async def _execute(self, run: Run) -> None:
        task = self.store.get_task(run.task_id)
        if (
            task is None
            or task.status is not TaskStatus.ACTIVE
            or task.revision != run.task_revision
        ):
            return  # 认领扫描负责清扫；这里是防御
        lock = self.group_locks.setdefault(run.group_id, asyncio.Lock())
        async with lock:
            await self._execute_locked(run, task)

    async def _execute_locked(self, run: Run, task: Task) -> None:
        if not self.store.mark_running(run.run_id, self.worker_id):
            return
        # 严格门控：管理员静音 / 睡眠 / 冷却时预约任务也闭嘴（读库失败则拒绝）
        allowed, reason = can_speak_for_scheduled(run.group_id)
        if not allowed:
            logger.info(f"[Scheduling] 运行 {run.run_id[:8]} 被门控跳过：{reason}")
            self.store.transition_run(
                run.run_id, self.worker_id,
                from_states=(RunState.RUNNING,), to_state=RunState.SKIPPED,
                error=f"gate: {reason}"[:200],
            )
            return
        # 发送窗口前续租：减少「发完还没落回执就被判 unknown」的窗口
        self.store.renew_lease(
            run.run_id, self.worker_id, seconds=self.lease_ttl_seconds
        )
        if task.mode is TaskMode.REMINDER:
            await self.delivery.deliver(
                run=run, task=task, text=render_reminder(task)
            )
            return
        await self._execute_agent(run, task)

    async def _execute_agent(self, run: Run, task: Task) -> None:
        if self.agent_runner is None:
            self.store.transition_run(
                run.run_id, self.worker_id,
                from_states=(RunState.RUNNING,), to_state=RunState.FAILED,
                error="runner_missing",
            )
            return
        context = build_scheduled_context(
            task.group_id, max_chars=self.context_max_chars
        )
        limits = AgentRunLimits(
            max_model_rounds=task.max_model_rounds,
            max_tool_calls=task.max_tool_calls,
            wall_clock_seconds=task.run_timeout_seconds,
            output_max_chars=task.output_max_chars,
        )

        async def cancel_check() -> None:
            self._assert_run_runnable(run.run_id, task.task_id, task.revision)

        try:
            outcome = await self.agent_runner.run(
                task_id=task.task_id,
                run_id=run.run_id,
                objective=task.objective,
                policy=task.policy,
                context_text=context.text,
                limits=limits,
                cancel_check=cancel_check,
            )
        except TaskCancelledError:
            self.store.transition_run(
                run.run_id, self.worker_id,
                from_states=(RunState.RUNNING,), to_state=RunState.CANCELLED,
                error="task_fenced",
            )
            return
        counters: dict[str, Any] = {
            "model_rounds": outcome.model_rounds,
            "tool_calls": outcome.tool_calls,
        }
        if outcome.status == "cancelled":
            self.store.transition_run(
                run.run_id, self.worker_id,
                from_states=(RunState.RUNNING,), to_state=RunState.CANCELLED,
                error="task_fenced", **counters,
            )
            return
        if outcome.status in ("failed", "timeout"):
            self.store.transition_run(
                run.run_id, self.worker_id,
                from_states=(RunState.RUNNING,), to_state=RunState.FAILED,
                error=outcome.error or outcome.status, **counters,
            )
            return
        await self.delivery.deliver(
            run=run, task=task, text=outcome.text, **counters
        )

    def _assert_run_runnable(self, run_id: str, task_id: str, revision: int) -> None:
        """取消检查点：任务被暂停/取消/修订过期/租约丢失 → 抛 TaskCancelledError。"""
        fresh = self.store.get_run(run_id)
        if (
            fresh is None
            or fresh.state is not RunState.RUNNING
            or fresh.lease_owner != self.worker_id
        ):
            raise TaskCancelledError("run no longer owned")
        task = self.store.get_task(task_id)
        if (
            task is None
            or task.status is not TaskStatus.ACTIVE
            or task.revision != revision
        ):
            raise TaskCancelledError("task fenced")

    def snapshot(self) -> dict:
        """worker 状态摘要（状态接口 / 日志用）。"""
        return {
            "worker_id": self.worker_id,
            "tick_interval_seconds": self.tick_interval_seconds,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "daily_group_run_cap": self.daily_group_run_cap,
            "tracked_tasks": len(self._cursors),
            "running": bool(self._loop_task and not self._loop_task.done()),
        }


__all__ = ["SchedulerRuntime"]
