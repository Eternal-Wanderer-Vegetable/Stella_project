# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""投递状态机的基线：ready→sending→sent 次序、silent、delivery_unknown、
指纹幂等、租约丢失放弃与脱敏摘要。

发送器用可编程 Fake：能返回回执、抛异常、超时，并记录每次调用。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from stella_project.plugins.bot_main.scheduling.delivery import (
    DeliveryService,
    render_reminder,
    result_fingerprint,
    run_summary,
)
from stella_project.plugins.bot_main.scheduling.models import (
    NotificationMode,
    RunState,
    TaskMode,
)
from stella_project.plugins.bot_main.scheduling.store import TaskStore

UTC = timezone.utc


class FakeSender:
    def __init__(self, *, receipt="10001", error=None, delay=0.0):
        self.receipt = receipt
        self.error = error
        self.delay = delay
        self.sent: list[tuple[int, str]] = []

    async def __call__(self, group_id: int, text: str) -> str | None:
        self.sent.append((group_id, text))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.receipt


@pytest.fixture()
def store(tmp_path):
    return TaskStore(tmp_path / "scheduling.db")


def _make_task(store, **overrides):
    params = {
        "bot_id": "10000",
        "group_id": 12345,
        "owner_id": 777,
        "mode": TaskMode.REMINDER,
        "objective": "站会提醒",
        "cron_expr": "0 9 * * MON-FRI",
        "timezone": "Asia/Shanghai",
        "notification_mode": NotificationMode.ALWAYS,
    }
    params.update(overrides)
    return store.create_task(**params)


async def _claimed_run(store, task, *, worker="w1"):
    run_id = store.insert_run(task.task_id, request_id="req-x")
    assert run_id is not None
    claimed = store.claim_next_run(worker, lease_seconds=600)
    assert claimed is not None
    assert store.mark_running(run_id, worker)
    run = store.get_run(run_id)
    assert run is not None
    return run


# ── 成功路径与次序 ───────────────────────────────────

async def test_happy_path_persists_ready_before_send(store):
    task = _make_task(store)
    run = await _claimed_run(store, task)
    sender = FakeSender()
    service = DeliveryService(store, sender=sender)

    result = await service.deliver(run=run, task=task, text="九点站会")

    assert result.state is RunState.SENT
    assert result.receipt == "10001"
    assert sender.sent == [(12345, "九点站会")]
    final = store.get_run(run.run_id)
    assert final.state is RunState.SENT
    assert final.delivery_receipt == "10001"
    assert final.result_text == "九点站会"
    assert final.fingerprint
    assert store.quota_usage(12345)["messages_used"] == 1


async def test_receipt_optional_still_sent(store):
    """适配器不回执：记 sent 但 receipt 为空（不声称 exactly-once）。"""
    task = _make_task(store)
    run = await _claimed_run(store, task)
    service = DeliveryService(store, sender=FakeSender(receipt=None))
    result = await service.deliver(run=run, task=task, text="提醒")
    assert result.state is RunState.SENT
    assert result.receipt == ""
    assert store.get_run(run.run_id).delivery_receipt == ""


# ── silent 与空产出 ──────────────────────────────────

async def test_on_content_empty_output_is_silent_without_send(store):
    task = _make_task(store, mode=TaskMode.AGENT,
                      notification_mode=NotificationMode.ON_CONTENT)
    run = await _claimed_run(store, task)
    sender = FakeSender()
    result = await DeliveryService(store, sender=sender).deliver(
        run=run, task=task, text="   "
    )
    assert result.state is RunState.SILENT
    assert sender.sent == []
    assert store.get_run(run.run_id).state is RunState.SILENT


async def test_always_mode_empty_output_fails_without_send(store):
    task = _make_task(store)
    run = await _claimed_run(store, task)
    sender = FakeSender()
    result = await DeliveryService(store, sender=sender).deliver(
        run=run, task=task, text=""
    )
    assert result.state is RunState.FAILED
    assert result.error == "empty_output"
    assert sender.sent == []


# ── delivery_unknown ─────────────────────────────────

async def test_sender_exception_becomes_delivery_unknown(store):
    task = _make_task(store)
    run = await _claimed_run(store, task)
    sender = FakeSender(error=RuntimeError("websocket gone"))
    result = await DeliveryService(store, sender=sender).deliver(
        run=run, task=task, text="提醒"
    )
    assert result.state is RunState.DELIVERY_UNKNOWN
    final = store.get_run(run.run_id)
    assert final.state is RunState.DELIVERY_UNKNOWN
    assert "RuntimeError" in final.delivery_error


async def test_sender_timeout_becomes_delivery_unknown(store):
    task = _make_task(store)
    run = await _claimed_run(store, task)
    sender = FakeSender(delay=2.0)
    service = DeliveryService(store, sender=sender, send_timeout_seconds=0.2)
    result = await service.deliver(run=run, task=task, text="提醒")
    assert result.state is RunState.DELIVERY_UNKNOWN
    assert "send_timeout" in store.get_run(run.run_id).delivery_error


async def test_delivery_unknown_is_never_auto_retried(store):
    """unknown 是终态：认领扫不到、租约恢复不碰它。"""
    task = _make_task(store)
    run = await _claimed_run(store, task)
    service = DeliveryService(store, sender=FakeSender(error=RuntimeError("x")))
    await service.deliver(run=run, task=task, text="提醒")
    # 不会出现在认领队列里
    assert store.claim_next_run("w2", lease_seconds=60) is None
    # 租约恢复也不改它的状态
    counts = store.recover_expired_leases()
    assert counts == {"requeued": 0, "delivery_unknown": 0}
    assert store.get_run(run.run_id).state is RunState.DELIVERY_UNKNOWN


# ── 租约竞争 ─────────────────────────────────────────

async def test_lost_lease_aborts_delivery_without_sending(store):
    """CAS 竞争失败（租约被接管/状态被改）：直接放弃，绝不发送。"""
    task = _make_task(store)
    run = await _claimed_run(store, task)
    # 模拟租约过期后运行被恢复回队列（状态已不是 running）
    store.recover_expired_leases(now=datetime.now(UTC) + timedelta(hours=1))
    sender = FakeSender()
    result = await DeliveryService(store, sender=sender).deliver(
        run=run, task=task, text="提醒"
    )
    assert result.state is RunState.CANCELLED
    assert result.error == "lease_lost"
    assert sender.sent == []


# ── 指纹与脱敏 ───────────────────────────────────────

def test_fingerprint_deterministic_and_sensitive_to_content():
    base = {"task_id": "t", "revision": 1, "run_key": "2026-01-01T09:00:00+00:00"}
    a = result_fingerprint(text="提醒大家喝水", **base)
    assert a == result_fingerprint(text="提醒大家喝水", **base)
    assert a != result_fingerprint(text="提醒大家休息", **base)
    assert a != result_fingerprint(text="提醒大家喝水", task_id="other", revision=1,
                                   run_key=base["run_key"])
    # 行尾空白不改变指纹（跨端换行差异不算内容变化）
    assert a == result_fingerprint(text="提醒大家喝水\r\n", **base)


def test_render_reminder_is_objective_verbatim(tmp_path):
    task = _make_task(TaskStore(tmp_path / "s.db"), objective="  纯文本提醒  ")
    assert render_reminder(task) == "纯文本提醒"


async def test_run_summary_is_redacted(store):
    task = _make_task(store)
    run = await _claimed_run(store, task)
    await DeliveryService(store, sender=FakeSender()).deliver(
        run=run, task=task, text="包含敏感内容的提醒文本"
    )
    final = store.get_run(run.run_id)
    summary = run_summary(final, task=task)
    assert summary["state"] == "sent"
    assert summary["result_chars"] == len("包含敏感内容的提醒文本")
    assert "包含敏感内容" not in str(summary)  # 内容本身绝不进摘要
    assert summary["fingerprint"] == final.fingerprint
    assert summary["latency_seconds"] is not None
    assert summary["mode"] == "reminder"


async def test_manual_retry_creates_new_run(store):
    """delivery_unknown 的人工恢复 = 定时立即（新运行），旧行保持 unknown。"""
    task = _make_task(store)
    run = await _claimed_run(store, task)
    await DeliveryService(store, sender=FakeSender(error=RuntimeError("x"))).deliver(
        run=run, task=task, text="提醒"
    )
    # 人工 run-now（新的 request_id）产生新运行
    retry_id = store.insert_run(task.task_id, request_id="manual-retry-1")
    assert retry_id is not None
    assert retry_id != run.run_id
    assert store.get_run(run.run_id).state is RunState.DELIVERY_UNKNOWN
