# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""恢复矩阵基线（方案 §8.1 test_recovery、§6.8）。

关键不变量：**没有停止证据不得启动第二份执行**。每个崩溃窗口都用
FakeBackend 的记账（turns_started）验证没有重复执行。
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from conftest import claim_task, submit_task

from cometa.models import EventKind, LaunchPhase, TaskState, iso_utc, utc_now


def _expire_attempt_lease(store, attempt_id: str, *, seconds_ago: float = 60.0) -> None:
    """把租约改成已过期（模拟宿主崩溃后时间流逝）。"""
    past = utc_now() - timedelta(seconds=seconds_ago)
    conn = sqlite3.connect(str(store.db_path))
    conn.execute(
        "UPDATE attempts SET lease_until_utc = ? WHERE attempt_id = ?",
        (iso_utc(past), attempt_id),
    )
    conn.commit()
    conn.close()


def _recover(store, executor, task_id: str) -> str:
    task = store.get_task(task_id)
    attempt = store.get_attempt(task.current_attempt)
    _expire_attempt_lease(store, attempt.attempt_id)
    assert store.tasks_needing_recovery("inst-test", now=utc_now())
    return executor.recover_task(task, attempt)


class TestCrashWindows:
    """启动协议各崩溃窗口（§6.8 恢复矩阵 1-3 行）。"""

    @pytest.mark.asyncio
    async def test_crash_before_dispatch_requeues(self, make_executor, store, config):
        executor, fake = make_executor()
        task_id = submit_task(store, config)
        _task, _attempt = claim_task(store)  # launch_phase=claimed
        # 模拟宿主在 dispatch 之前崩溃
        result = _recover(store, executor, task_id)
        assert result == "requeued"
        record = store.get_task(task_id)
        assert record.state is TaskState.QUEUED
        assert record.current_attempt == ""
        assert not fake.turns_started, "未 dispatch 就崩溃：从未执行"

    @pytest.mark.asyncio
    async def test_crash_during_dispatch_requires_recovery(
        self, make_executor, store, config
    ):
        executor, fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        store.update_launch_phase(
            attempt.attempt_id, "w-test", attempt.lease_epoch, LaunchPhase.DISPATCHING.value
        )
        assert _recover(store, executor, task_id) == "recovery_required"
        assert store.get_task(task_id).state is TaskState.RECOVERY_REQUIRED
        assert not fake.turns_started, "启动结果不明：不允许第二份执行"

    @pytest.mark.asyncio
    async def test_crash_while_running_requires_recovery(
        self, make_executor, store, config
    ):
        executor, _fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        store.transition_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        assert _recover(store, executor, task_id) == "recovery_required"
        assert store.get_task(task_id).state is TaskState.RECOVERY_REQUIRED

    @pytest.mark.asyncio
    async def test_connecting_with_session_requires_recovery(
        self, make_executor, store, config
    ):
        executor, _fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        store.update_launch_phase(
            attempt.attempt_id,
            "w-test",
            attempt.lease_epoch,
            LaunchPhase.CONNECTING.value,
            session_id="sess-1",
        )
        assert _recover(store, executor, task_id) == "recovery_required"

    @pytest.mark.asyncio
    async def test_connecting_without_session_requeues(self, make_executor, store, config):
        executor, _fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        store.update_launch_phase(
            attempt.attempt_id, "w-test", attempt.lease_epoch, LaunchPhase.CONNECTING.value
        )
        assert _recover(store, executor, task_id) == "requeued"


class TestNoDuplicateExecution:
    @pytest.mark.asyncio
    async def test_old_epoch_write_rejected_after_requeue(
        self, make_executor, store, config
    ):
        """回队后重新认领：旧 attempt 的身份围栏防止旧执行者继续写。"""
        _executor, _fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        old_attempt_id = attempt.attempt_id
        store.begin_recovery(task_id)
        assert store.requeue_task(task_id, reason="test")
        _task, attempt2 = claim_task(store)
        assert attempt2.attempt_id != old_attempt_id
        # 旧 attempt 已经不是 current_attempt：任何写入都被拒绝
        ok = store.transition_task(
            task_id,
            attempt_id=old_attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        assert ok is False, "旧 attempt 写入必须被围栏拒绝"

    @pytest.mark.asyncio
    async def test_recovery_required_not_reclaimable(self, make_executor, store, config):
        """recovery_required 是等待管理员的状态，worker 不自动重跑。"""
        executor, _fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        store.transition_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        assert _recover(store, executor, task_id) == "recovery_required"
        assert (
            store.claim_next_task(
                instance_id="inst-test",
                worker_id="w2",
                backend_ids={"fake"},
                lease_seconds=30,
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_completed_before_db_commit_is_not_duplicated(
        self, make_executor, store, config
    ):
        """「Agent 完成但 cometa 未写结果」：正常路径一次收束，绝不重跑。"""
        from cometa.backends.fake import fake_completed

        executor, fake = make_executor()
        fake.behavior.events = fake_completed("done")
        task_id = submit_task(store, config)
        task, attempt = claim_task(store)
        await executor.run_attempt(task, attempt)
        assert store.get_task(task_id).state is TaskState.SUCCEEDED
        assert len(fake.turns_started) == 1


class TestStaleWriters:
    @pytest.mark.asyncio
    async def test_old_owner_cannot_append_events(self, make_executor, store, config):
        _executor, _fake = make_executor()
        task_id = submit_task(store, config)
        _task, attempt = claim_task(store)
        _expire_attempt_lease(store, attempt.attempt_id)
        taken = store.take_over_expired_attempt(attempt.attempt_id, "w2", lease_seconds=30)
        assert taken is not None
        seq = store.append_event(
            task_id,
            attempt_id=attempt.attempt_id,
            owner=attempt.lease_owner,
            epoch=attempt.lease_epoch,
            kind=EventKind.PROGRESS,
            payload={"x": 1},
        )
        assert seq is None, "租约已易主：旧 owner 不能写事件"
        seq2 = store.append_event(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w2",
            epoch=taken.lease_epoch,
            kind=EventKind.PROGRESS,
            payload={"x": 2},
        )
        assert seq2 is not None
