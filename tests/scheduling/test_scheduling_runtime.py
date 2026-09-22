# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""租约 worker 运行时的集成基线（fake 时钟 + fake 发送器，不发真消息）。

覆盖：到期认领→门控→投递全链、门控拒绝记 skipped、暂停任务的清理、
latest/all 补跑策略、worker 租约互斥、优雅停止与群锁注入。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from stella_project.plugins.bot_main.scheduling import runtime as runtime_module
from stella_project.plugins.bot_main.scheduling.delivery import DeliveryService
from stella_project.plugins.bot_main.scheduling.models import (
    NotificationMode,
    RunState,
    TaskMode,
    TaskStatus,
)
from stella_project.plugins.bot_main.scheduling.runtime import SchedulerRuntime
from stella_project.plugins.bot_main.scheduling.store import TaskStore

UTC = timezone.utc
T0 = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
GROUP = 12345


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now = self.now + timedelta(seconds=seconds)
        return self.now


class FakeSender:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def __call__(self, group_id: int, text: str) -> str | None:
        self.sent.append((group_id, text))
        return f"mid-{len(self.sent)}"


@dataclass
class FakeOutcome:
    status: str = "completed"
    text: str = "agent 产出"
    model_rounds: int = 2
    tool_calls: int = 1
    error: str = ""
    output_truncated: bool = False
    denied_tools: list = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.denied_tools is None:
            self.denied_tools = []


class FakeAgentRunner:
    def __init__(self, outcome: FakeOutcome | None = None):
        self.outcome = outcome or FakeOutcome()
        self.calls: list[dict] = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture()
def store(tmp_path):
    return TaskStore(tmp_path / "scheduling.db")


@pytest.fixture()
def sender():
    return FakeSender()


@pytest.fixture()
def clock():
    return Clock(T0)


@pytest.fixture()
def gate_allow(monkeypatch):
    monkeypatch.setattr(
        runtime_module, "can_speak_for_scheduled", lambda gid: (True, "允许")
    )


def _make_delivery(store, sender) -> DeliveryService:
    return DeliveryService(store, sender=sender, send_timeout_seconds=5)


def _make_runtime(store, sender, clock, **overrides) -> SchedulerRuntime:
    params = {
        "store": store,
        "delivery": _make_delivery(store, sender),
        "worker_id": "w-test",
        "lease_ttl_seconds": 300.0,
        "tick_interval_seconds": 30.0,
        "clock": clock,
    }
    params.update(overrides)
    return SchedulerRuntime(**params)


def _make_task(store, *, mode=TaskMode.REMINDER, cron="* * * * *", **overrides):
    params = {
        "bot_id": "10000",
        "group_id": GROUP,
        "owner_id": 777,
        "mode": mode,
        "objective": "整点喝水",
        "cron_expr": cron,
        "timezone": "Asia/Shanghai",
        "notification_mode": NotificationMode.ALWAYS,
        "now": T0,
    }
    params.update(overrides)
    return store.create_task(**params)


# ── 全链路：入队 → 认领 → 门控 → 投递 ────────────────

async def test_due_reminder_flows_to_delivery(store, sender, clock, gate_allow):
    task = _make_task(store)  # 每分钟一次，创建于 T0
    clock.advance(90)  # T0+90：错过 T0+60 那一次
    rt = _make_runtime(store, sender, clock)
    executed = await rt.tick_once()
    assert executed == 1
    assert sender.sent == [(GROUP, "整点喝水")]
    runs = store.list_runs(task.task_id)
    assert len(runs) == 1 and runs[0].state is RunState.SENT
    assert runs[0].delivery_receipt == "mid-1"
    # 任务缓存刷新：last_run 是补跑的那次触发，next 指向未来
    loaded = store.get_task(task.task_id)
    assert loaded.last_run_utc is not None and loaded.next_run_utc > clock.now


async def test_gate_denial_marks_skipped(store, sender, clock, monkeypatch):
    task = _make_task(store)
    monkeypatch.setattr(
        runtime_module,
        "can_speak_for_scheduled",
        lambda gid: (False, "睡眠时段（23:30–07:30）"),
    )
    clock.advance(90)
    rt = _make_runtime(store, sender, clock)
    assert await rt.tick_once() == 1
    assert sender.sent == []
    run = store.list_runs(task.task_id)[0]
    assert run.state is RunState.SKIPPED
    assert run.error.startswith("gate:")


async def test_paused_task_queued_run_swept_not_executed(store, sender, clock, gate_allow):
    task = _make_task(store)
    # 暂停前就已经在队列里的运行：认领扫描必须把它作废
    assert store.insert_run(task.task_id, scheduled_for=clock.now + timedelta(seconds=60)) is not None
    store.set_status(task.task_id, task.revision, TaskStatus.PAUSED)
    clock.advance(90)
    rt = _make_runtime(store, sender, clock)
    assert await rt.tick_once() == 0
    assert sender.sent == []
    run = store.list_runs(task.task_id)[0]
    assert run.state is RunState.SKIPPED and run.error == "task_paused"


async def test_edited_task_fires_missed_slot_under_new_revision(store, sender, clock, gate_allow):
    """编辑后首个 tick：错过的触发槽按**新修订**补跑（排队中的旧修订才会被作废）。"""
    task = _make_task(store)
    clock.advance(90)
    store.edit_task(task.task_id, task.revision, updates={"objective": "v2 文案"})
    rt = _make_runtime(store, sender, clock)
    await rt.tick_once()
    assert sender.sent == [(GROUP, "v2 文案")]
    run = store.list_runs(task.task_id)[0]
    assert run.task_revision == 2


# ── 补跑策略 ─────────────────────────────────────────

async def test_all_coalesce_drains_missed_across_ticks(store, sender, clock, gate_allow):
    """错过 3 次：第一个 tick 入队最早一次；每轮运行结束后续 tick 续补。"""
    task = _make_task(store)  # reminder 默认 all
    clock.advance(190)  # 错过 T0+60 / +120 / +180
    rt = _make_runtime(store, sender, clock)
    for _ in range(5):
        if await rt.tick_once() == 0:
            break
    assert len(sender.sent) == 3
    assert len(store.list_runs(task.task_id)) == 3


async def test_latest_coalesce_only_enqueues_last_missed(store, sender, clock, gate_allow):
    task = _make_task(store, mode=TaskMode.AGENT, objective="总结",
                      policy={"coalesce": "latest", "tools": []})
    clock.advance(190)
    rt = _make_runtime(store, sender, clock, agent_runner=FakeAgentRunner())
    await rt.tick_once()
    runs = store.list_runs(task.task_id)
    assert len(runs) == 1
    # 补的是最近一次（T0+180），不是最早那次（T0+60）
    assert runs[0].scheduled_for_utc == T0 + timedelta(seconds=180)


# ── agent 全链 ───────────────────────────────────────

async def test_agent_run_completes_and_delivers(store, sender, clock, gate_allow):
    task = _make_task(store, mode=TaskMode.AGENT, objective="总结群聊",
                      policy={"coalesce": "latest", "tools": []})
    runner = FakeAgentRunner(FakeOutcome(text="昨晚大家聊了爬山", model_rounds=2, tool_calls=1))
    clock.advance(90)
    rt = _make_runtime(store, sender, clock, agent_runner=runner)
    assert await rt.tick_once() == 1
    assert sender.sent == [(GROUP, "昨晚大家聊了爬山")]
    run = store.list_runs(task.task_id)[0]
    assert run.model_rounds == 2 and run.tool_calls == 1
    # runner 收到了取消检查点与任务参数
    call = runner.calls[0]
    assert call["objective"] == "总结群聊"
    assert callable(call["cancel_check"])


async def test_agent_failure_maps_to_failed_run(store, sender, clock, gate_allow):
    task = _make_task(store, mode=TaskMode.AGENT, objective="x",
                      policy={"coalesce": "latest", "tools": []})
    runner = FakeAgentRunner(FakeOutcome(status="failed", error="provider_unavailable"))
    clock.advance(90)
    rt = _make_runtime(store, sender, clock, agent_runner=runner)
    await rt.tick_once()
    run = store.list_runs(task.task_id)[0]
    assert run.state is RunState.FAILED
    assert run.error == "provider_unavailable"
    assert sender.sent == []


async def test_agent_cancelled_maps_to_cancelled_run(store, sender, clock, gate_allow):
    task = _make_task(store, mode=TaskMode.AGENT, objective="x",
                      policy={"coalesce": "latest", "tools": []})
    runner = FakeAgentRunner(FakeOutcome(status="cancelled"))
    clock.advance(90)
    rt = _make_runtime(store, sender, clock, agent_runner=runner)
    await rt.tick_once()
    run = store.list_runs(task.task_id)[0]
    assert run.state is RunState.CANCELLED


async def test_cancel_check_fences_paused_task_mid_run(store, sender, clock, gate_allow):
    """取消检查点：运行中任务被暂停 → 检查点抛错，运行被标 cancelled。"""
    task = _make_task(store, mode=TaskMode.AGENT, objective="x",
                      policy={"coalesce": "latest", "tools": []})
    captured: dict = {}

    class PausingRunner:
        async def run(self, **kwargs):
            captured["cancel_check"] = kwargs["cancel_check"]
            # 模拟「生成期间管理员暂停了任务」
            fresh = store.get_task(task.task_id)
            store.set_status(task.task_id, fresh.revision, TaskStatus.PAUSED)
            await kwargs["cancel_check"]()  # 必须抛 TaskCancelledError
            return FakeOutcome()

    clock.advance(90)
    rt = _make_runtime(store, sender, clock, agent_runner=PausingRunner())
    await rt.tick_once()
    run = store.list_runs(task.task_id)[0]
    assert run.state is RunState.CANCELLED
    assert sender.sent == []


# ── worker 租约与生命周期 ────────────────────────────

async def test_standby_worker_does_not_claim(store, sender, clock, gate_allow):
    _make_task(store)
    clock.advance(90)
    store.acquire_worker_lease("worker-other", ttl_seconds=3600, now=clock.now)
    rt = _make_runtime(store, sender, clock)
    assert await rt.tick_once() == -1
    assert sender.sent == []


async def test_stop_releases_worker_lease(store, sender, clock, gate_allow):
    rt = _make_runtime(store, sender, clock)
    await rt.start()
    try:
        # 让后台循环跑到「持有租约、等待下个 tick」的状态
        for _ in range(5):
            await asyncio.sleep(0)
        assert store.acquire_worker_lease("probe", ttl_seconds=60, now=clock.now) is False
    finally:
        await rt.stop()
    # 停止后租约释放，其它 worker 可以接管
    assert store.acquire_worker_lease("probe", ttl_seconds=60, now=clock.now) is True
    assert rt.snapshot()["running"] is False


async def test_group_lock_is_shared_mapping(store, sender, clock, gate_allow):
    locks = {}
    _make_task(store)
    clock.advance(90)
    rt = _make_runtime(store, sender, clock, group_locks=locks)
    await rt.tick_once()
    assert GROUP in locks  # 用的是注入的同一把锁字典（与网关共享）
