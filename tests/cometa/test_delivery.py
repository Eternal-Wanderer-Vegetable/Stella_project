# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""投递泵基线（方案 §8.1 test_delivery）：ack 入口与 pump 竞争、
阶段合并、final 优先、发送前失败退避、delivery_unknown 不盲目重投。"""

from __future__ import annotations

import asyncio

import pytest

from cometa.delivery import NotificationPump, SenderUnavailable
from cometa.models import (
    EventKind,
    NotificationKind,
    NotificationState,
    Outcome,
    TaskState,
)
from cometa.store import NotificationSpec
from tests.cometa_helpers import claim_task, submit_task


class FakeSender:
    def __init__(self, *, receipt="msg-1", error=None, unavailable=False):
        self.receipt = receipt
        self.error = error
        self.unavailable = unavailable
        self.sent: list[tuple[dict, str]] = []

    async def send(self, target: dict, text: str, payload: dict | None = None) -> str | None:
        self.sent.append((dict(target), text))
        if self.unavailable:
            raise SenderUnavailable("bot offline")
        if self.error is not None:
            raise self.error
        return self.receipt


@pytest.fixture()
def pump(store):
    def _make(sender: FakeSender, **kwargs) -> NotificationPump:
        return NotificationPump(store, sender, poll_interval_seconds=0.1, **kwargs)

    return _make


def _task_with_ack(store, config) -> str:
    return submit_task(store, config)


class TestAckCompetition:
    @pytest.mark.asyncio
    async def test_entry_claim_wins_pump_skips(self, store, config, pump):
        task_id = _task_with_ack(store, config)
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        sender = FakeSender()
        # 入口先 claim（模拟 QQ 桥接 deliver_ack）
        claimed = store.claim_notification(ack.notification_id)
        assert claimed is not None
        # 泵同轮扫描：claim 不到，跳过
        count = await pump(sender).pump_once()
        assert count == 0
        assert sender.sent == []
        assert (
            store.notification_of_dedupe(task_id, f"ack:{task_id}").state
            is NotificationState.SENDING
        )
        store.mark_notification(
            ack.notification_id, state=NotificationState.SENT, receipt="entry"
        )

    @pytest.mark.asyncio
    async def test_pump_delivers_unclaimed_ack(self, store, config, pump):
        task_id = _task_with_ack(store, config)
        sender = FakeSender()
        delivered = await pump(sender).pump_once()
        assert delivered == 1
        assert len(sender.sent) == 1
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        assert ack.state is NotificationState.SENT
        assert ack.receipt == "msg-1"
        # 短 ID 与目标在文案里（§6.5：用户仍能识别任务）
        target, text = sender.sent[0]
        assert target["platform"] == "qq"
        assert task_id[:8] in text


class TestFinalDelivery:
    @pytest.mark.asyncio
    async def test_final_supersedes_pending_progress(self, store, config, pump):
        task_id = _task_with_ack(store, config)
        _task, attempt = claim_task(store)
        store.append_event(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            kind=EventKind.PROGRESS,
            payload={"text": "进行中"},
            notification=NotificationSpec(
                kind=NotificationKind.PROGRESS,
                dedupe_key=f"progress:{task_id}",
                payload={"text": "进行中"},
                merge=True,
            ),
        )
        store.finish_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            outcome=Outcome.SUCCEEDED,
            state=TaskState.SUCCEEDED,
            summary="全部完成",
        )
        sender = FakeSender()
        await pump(sender).pump_once()
        progress = store.notification_of_dedupe(task_id, f"progress:{task_id}")
        final = store.notification_of_dedupe(task_id, f"final:{task_id}")
        assert progress.state is NotificationState.SUPERSEDED
        assert final.state is NotificationState.SENT
        _target, text = sender.sent[-1]
        assert "全部完成" in text


class TestFailures:
    @pytest.mark.asyncio
    async def test_sender_unavailable_retries_with_backoff(self, store, config, pump):
        task_id = _task_with_ack(store, config)
        sender = FakeSender(unavailable=True)
        p = pump(sender, retry_backoff_seconds=60.0)
        assert await p.pump_once() == 0
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        assert ack.state is NotificationState.PENDING
        assert ack.next_attempt_at is not None  # 已退避
        # 恢复可用后能发出
        sender.unavailable = False
        sender.receipt = "ok"
        # 手动把退避时间清掉，模拟时间流逝
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE notifications SET next_attempt_utc = NULL, state = 'pending'"
            " WHERE notification_id = ?",
            (ack.notification_id,),
        )
        conn.commit()
        conn.close()
        assert await p.pump_once() == 1

    @pytest.mark.asyncio
    async def test_unavailable_exhausted_becomes_unknown(self, store, config, pump):
        task_id = _task_with_ack(store, config)
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        sender = FakeSender(unavailable=True)
        p = pump(sender, retry_backoff_seconds=1.0, max_attempts=2)
        import sqlite3

        for _ in range(2):
            # 每次 claim 之间重置退避与 pending，让 max_attempts 生效
            conn = sqlite3.connect(str(store.db_path))
            conn.execute(
                "UPDATE notifications SET state='pending', next_attempt_utc = NULL"
                " WHERE notification_id = ?",
                (ack.notification_id,),
            )
            conn.commit()
            conn.close()
            await p.pump_once()
        final_state = store.notification_of_dedupe(
            task_id, f"ack:{task_id}"
        ).state
        # 第一次退避（attempt 1），第二次达到上限 → delivery_unknown
        assert final_state is NotificationState.DELIVERY_UNKNOWN

    @pytest.mark.asyncio
    async def test_send_error_is_delivery_unknown_never_resent(self, store, config, pump):
        task_id = _task_with_ack(store, config)
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        sender = FakeSender(error=RuntimeError("platform exploded mid-call"))
        await pump(sender).pump_once()
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        assert ack.state is NotificationState.DELIVERY_UNKNOWN
        # 未知终态不再出现在 due 队列
        due = store.due_notifications()
        assert all(n.notification_id != ack.notification_id for n in due)
        # 再泵一轮也不会再发
        sender2 = FakeSender()
        assert await pump(sender2).pump_once() == 0
        assert sender2.sent == []

    @pytest.mark.asyncio
    async def test_run_forever_stops_cleanly(self, store, config, pump):
        _task_with_ack(store, config)
        sender = FakeSender()
        stop = asyncio.Event()
        runner = asyncio.create_task(pump(sender).run_forever(stop))
        await asyncio.sleep(0.2)
        stop.set()
        await asyncio.wait_for(runner, timeout=5)
        assert sender.sent


class TestFunctionSenderAdapter:
    @pytest.mark.asyncio
    async def test_bare_async_function_accepted(self, store, config):
        """接线层传裸 async 函数（QQ 桥接形态）也能投递——曾因 AttributeError
        把所有通知打成 delivery_unknown（2026-09-30 人工清单实测）。"""

        async def bare_send(target: dict, text: str, payload: dict | None = None) -> str | None:
            bare_send.calls.append((dict(target), text))
            return "fn-receipt"

        bare_send.calls = []
        task_id = submit_task(store, config)
        pump = NotificationPump(store, bare_send, poll_interval_seconds=0.1)
        delivered = await pump.pump_once()
        assert delivered == 1
        assert bare_send.calls
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        assert ack.state is NotificationState.SENT
        assert ack.receipt == "fn-receipt"
