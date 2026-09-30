# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""CometaStore 的事务基线：受理幂等/冲突、配额原子性、认领互斥、
租约围栏、通知去重与合并、终态不可覆盖、工作区锁（方案 §6.3/§8.1）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from cometa.models import (
    ControlKind,
    EventKind,
    NotificationKind,
    NotificationState,
    Origin,
    Outcome,
    TaskSpec,
    TaskState,
    iso_utc,
    utc_now,
)
from cometa.store import (
    CometaStore,
    IdempotencyConflictError,
    InputRequestStateError,
    NotificationSpec,
    QuotaExceededError,
    StaleLeaseError,
    TaskNotFoundError,
)


def _origin(**overrides) -> Origin:
    fields = {
        "instance_id": "inst-1",
        "platform": "qq",
        "bot_id": "10000",
        "conversation_id": "12345",
        "requester_id": "777",
        "source_request_id": "req-1",
        "reply_to_message_id": "m-1",
    }
    fields.update(overrides)
    return Origin(**fields)


def _spec(objective="写一个排序算法", **overrides) -> TaskSpec:
    fields = {
        "objective": objective,
        "required_capabilities": ["code.edit", "code.test"],
        "workspace_id": "stella",
        "permission_profile": "coding",
    }
    fields.update(overrides)
    return TaskSpec(**fields)


def _submit(
    store: CometaStore,
    *,
    key="k1",
    origin=None,
    spec=None,
    limits=None,
    task_timeout=1800.0,
    now=None,
) -> tuple[str, bool]:
    now = now or utc_now()
    origin = origin or _origin()
    spec = spec or _spec()
    return store.submit_task(
        origin=origin,
        spec=spec,
        idempotency_key=key,
        requester_id=origin.requester_id,
        group_id=origin.conversation_id if origin.platform == "qq" else "",
        backend_id="fake",
        profile="coding",
        workspace_id=spec.workspace_id,
        workspace_key=f"ws:{spec.workspace_id}" if spec.workspace_id else "",
        deadline_at=now + timedelta(seconds=task_timeout),
        config_snapshot={"limits": limits or {"per_user_active": 1, "per_group_active": 2}},
        now=now,
    )


def _claim(store: CometaStore, *, worker="w1", backend_ids=None):
    return store.claim_next_task(
        instance_id="inst-1",
        worker_id=worker,
        backend_ids=backend_ids or {"fake"},
        lease_seconds=30.0,
    )


@pytest.fixture()
def store(tmp_path):
    return CometaStore(tmp_path / "cometa.db")


# ── 受理幂等（§6.3 事务边界 1） ───────────────────────────


class TestSubmit:
    def test_submit_creates_task_with_ack_notification(self, store):
        task_id, created = _submit(store)
        assert created is True
        task = store.get_task(task_id)
        assert task is not None
        assert task.state is TaskState.QUEUED
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        assert ack is not None
        assert ack.kind is NotificationKind.ACK
        assert ack.state is NotificationState.PENDING
        events = store.events_page(task_id)
        assert [e.kind for e in events] == [EventKind.ACCEPTED]

    def test_same_key_same_content_returns_same_task(self, store):
        task_id_1, created_1 = _submit(store)
        task_id_2, created_2 = _submit(store)
        assert created_1 is True
        assert created_2 is False
        assert task_id_1 == task_id_2

    def test_same_key_different_content_conflicts(self, store):
        _task_id, _ = _submit(store)
        with pytest.raises(IdempotencyConflictError):
            _submit(store, key="k1", spec=_spec(objective="完全不同的目标"))

    def test_same_key_different_origin_no_conflict(self, store):
        _submit(store, key="k1")
        task_id_2, created = _submit(
            store,
            key="k1",
            origin=_origin(conversation_id="99999", requester_id="888"),
        )
        assert created is True
        assert task_id_2

    def test_per_user_quota_enforced_atomically(self, store):
        _submit(store, key="k1")
        # per_user_active=1：同用户第二个进行中任务被拒
        with pytest.raises(QuotaExceededError):
            _submit(store, key="k2", origin=_origin(source_request_id="req-2"))

    def test_per_user_quota_released_after_terminal(self, store):
        task_id, _ = _submit(store)
        # 取消 queued 任务（直接终态）后配额释放
        store.request_cancel(task_id, actor="u777")
        _task_id_2, created = _submit(store, key="k2", origin=_origin(source_request_id="req-2"))
        assert created is True

    def test_per_group_quota(self, store):
        limits = {"per_user_active": 5, "per_group_active": 1}
        _submit(store, key="k1", limits=limits)
        with pytest.raises(QuotaExceededError):
            _submit(
                store,
                key="k2",
                limits=limits,
                origin=_origin(requester_id="888", source_request_id="req-2"),
            )

    def test_cancel_queued_is_immediate_terminal(self, store):
        task_id, _ = _submit(store)
        state, _, _ = store.request_cancel(task_id, actor="u777")
        assert state == "cancelled_immediately"
        task = store.get_task(task_id)
        assert task.state is TaskState.CANCELLED
        kinds = [e.kind for e in store.events_page(task_id)]
        assert EventKind.CANCELLED in kinds
        final = store.notification_of_dedupe(task_id, f"final:{task_id}")
        assert final is not None

    def test_cancel_twice_idempotent(self, store):
        task_id, _ = _submit(store)
        task, attempt = _claim(store)
        store.transition_task(
            task.task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        first = store.request_cancel(task_id, actor="u", idempotency_key="c1")
        second = store.request_cancel(task_id, actor="u", idempotency_key="c1")
        assert first[0] == "cancelling"
        assert second[0] == "already_requested"  # 同 key 返回既有命令

    def test_cancel_after_terminal_reports_state(self, store):
        task_id, _ = _submit(store)
        store.request_cancel(task_id, actor="u")  # queued → 立即终态
        state, _, _ = store.request_cancel(task_id, actor="u", idempotency_key="c2")
        assert state == "already_terminal"

    def test_cancel_terminal_task_reports_current_state(self, store):
        task_id, _ = _submit(store)
        store.request_cancel(task_id, actor="u")
        state, _, _ = store.request_cancel(task_id, actor="u", idempotency_key="c2")
        assert state == "already_terminal"


# ── 认领与租约（§6.3 事务边界 2） ─────────────────────────


class TestClaim:
    def test_claim_transitions_to_starting_with_attempt(self, store):
        task_id, _ = _submit(store)
        claimed = _claim(store)
        assert claimed is not None
        task, attempt = claimed
        assert task.task_id == task_id
        assert task.state is TaskState.STARTING
        assert attempt.task_id == task_id
        assert attempt.attempt_no == 1
        assert attempt.lease_owner == "w1"
        assert attempt.launch_phase == "claimed"
        kinds = [e.kind for e in store.events_page(task_id)]
        assert EventKind.STARTED in kinds

    def test_claim_empty_queue_returns_none(self, store):
        assert _claim(store) is None

    def test_double_claim_wont_duplicate(self, store):
        _submit(store)
        first = _claim(store, worker="w1")
        second = _claim(store, worker="w2")
        assert first is not None
        assert second is None  # 认领后不再是 queued

    def test_claim_skips_task_with_locked_workspace(self, store):
        # 任务 A 认领后持工作区锁；任务 B 同工作区不可认领
        generous = {"per_user_active": 9, "per_group_active": 9}
        _task_a, _ = _submit(store, key="ka", limits=generous)
        _task_b, created = _submit(
            store,
            key="kb",
            limits=generous,
            origin=_origin(requester_id="888", source_request_id="req-b"),
        )
        assert created
        assert _claim(store, worker="w1") is not None
        claimed_b = _claim(store, worker="w2")
        # 工作区锁被 A 持有：B 不可认领（A 已非 queued，B 是唯一候选但被锁挡住）
        assert claimed_b is None

    def test_claim_respects_backend_filter(self, store):
        _submit(store, key="k1")
        claimed = _claim(store, backend_ids={"codex"})
        assert claimed is None  # 任务指定 backend=fake，不在可用集合
        claimed2 = _claim(store, backend_ids={"fake"})
        assert claimed2 is not None


class TestLease:
    def test_renew_lease_extends_window(self, store):
        _submit(store)
        _task, attempt = _claim(store)
        assert store.renew_lease(attempt.attempt_id, "w1", lease_seconds=60.0)
        renewed = store.get_attempt(attempt.attempt_id)
        assert renewed.lease_until > attempt.lease_until

    def test_renew_lease_fails_for_wrong_owner(self, store):
        _submit(store)
        _, attempt = _claim(store)
        assert not store.renew_lease(attempt.attempt_id, "w2", lease_seconds=60.0)

    def test_take_over_expired_attempt_bumps_epoch(self, store):
        _submit(store)
        _, attempt = _claim(store)
        # 把租约改成已过期
        past = utc_now() - timedelta(seconds=120)
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE attempts SET lease_until_utc = ? WHERE attempt_id = ?",
            (iso_utc(past), attempt.attempt_id),
        )
        conn.commit()
        conn.close()
        taken = store.take_over_expired_attempt(attempt.attempt_id, "w2", lease_seconds=30.0)
        assert taken is not None
        assert taken.lease_owner == "w2"
        assert taken.lease_epoch == attempt.lease_epoch + 1
        # 未过期时不可接管
        assert (
            store.take_over_expired_attempt(attempt.attempt_id, "w3", lease_seconds=30.0)
            is None
        )


class TestTransition:
    def test_transition_with_valid_lease(self, store):
        _submit(store)
        task, attempt = _claim(store)
        ok = store.transition_task(
            task.task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
            phase="running",
        )
        assert ok is True
        assert store.get_task(task.task_id).state is TaskState.RUNNING

    def test_transition_rejects_wrong_epoch(self, store):
        _submit(store)
        task, attempt = _claim(store)
        ok = store.transition_task(
            task.task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch + 5,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        assert ok is False
        assert store.get_task(task.task_id).state is TaskState.STARTING


# ── 完成与终态（§6.3 事务边界 4） ─────────────────────────


class TestFinish:
    def _running(self, store):
        task_id, _ = _submit(store)
        task, attempt = _claim(store)
        store.transition_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        return task_id, task, attempt

    def test_finish_writes_result_notification_and_releases_lock(self, store):
        task_id, task, attempt = self._running(store)
        result_id = store.finish_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            outcome=Outcome.SUCCEEDED,
            state=TaskState.SUCCEEDED,
            summary="完成",
            artifacts=[
                {"relative_storage_key": "patch.diff", "sha256": "abc", "size": 3}
            ],
        )
        record = store.get_task(task_id)
        assert record.state is TaskState.SUCCEEDED
        assert record.result_id == result_id
        assert record.delivery_state == "pending"
        final = store.notification_of_dedupe(task_id, f"final:{task_id}")
        assert final is not None and final.state is NotificationState.PENDING
        kinds = [e.kind for e in store.events_page(task_id)]
        assert EventKind.COMPLETED in kinds
        artifacts = store.list_artifacts(task_id)
        assert len(artifacts) == 1
        # 工作区锁释放
        assert store.workspace_lock_holder(f"ws:{task.workspace_key}") is None
        result = store.get_result(task_id)
        assert result.outcome is Outcome.SUCCEEDED

    def test_finish_rejects_stale_lease(self, store):
        task_id, _task, attempt = self._running(store)
        with pytest.raises(StaleLeaseError):
            store.finish_task(
                task_id,
                attempt_id=attempt.attempt_id,
                owner="w2",
                epoch=attempt.lease_epoch,
                outcome=Outcome.SUCCEEDED,
                state=TaskState.SUCCEEDED,
                summary="x",
            )

    def test_finish_rejects_double_terminal(self, store):
        task_id, _task, attempt = self._running(store)
        store.finish_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            outcome=Outcome.SUCCEEDED,
            state=TaskState.SUCCEEDED,
            summary="first",
        )
        with pytest.raises(StaleLeaseError):
            store.finish_task(
                task_id,
                attempt_id=attempt.attempt_id,
                owner="w1",
                epoch=attempt.lease_epoch,
                outcome=Outcome.FAILED,
                state=TaskState.FAILED,
                summary="second",
            )

    def test_supersedes_pending_progress(self, store):
        task_id, _task, attempt = self._running(store)
        store.append_event(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
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
        progress = store.notification_of_dedupe(task_id, f"progress:{task_id}")
        assert progress.state is NotificationState.PENDING
        store.finish_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            outcome=Outcome.SUCCEEDED,
            state=TaskState.SUCCEEDED,
            summary="done",
        )
        progress = store.notification_of_dedupe(task_id, f"progress:{task_id}")
        assert progress.state is NotificationState.SUPERSEDED


# ── 事件与通知 ────────────────────────────────────────────


class TestEvents:
    def test_progress_event_after_terminal_is_rejected(self, store):
        task_id, _ = _submit(store)
        store.request_cancel(task_id, actor="u")
        seq = store.append_event(
            task_id,
            kind=EventKind.PROGRESS,
            payload={"text": "迟到的进度"},
        )
        assert seq is None

    def test_native_event_dedupe(self, store):
        task_id, _ = _submit(store)
        first = store.append_event(
            task_id,
            kind=EventKind.PROGRESS,
            payload={"n": 1},
            backend_event_id="native-1",
        )
        dup = store.append_event(
            task_id,
            kind=EventKind.PROGRESS,
            payload={"n": 1},
            backend_event_id="native-1",
        )
        assert first is not None and first > 0
        assert dup == -1  # 重放

    def test_progress_notification_merges(self, store):
        from cometa.store import NotificationSpec

        task_id, _ = _submit(store)
        for i in range(2):
            store.append_event(
                task_id,
                kind=EventKind.PROGRESS,
                payload={"text": f"进度{i}"},
                notification=NotificationSpec(
                    kind=NotificationKind.PROGRESS,
                    dedupe_key=f"progress:{task_id}",
                    payload={"text": f"进度{i}"},
                    merge=True,
                ),
            )
        progress = store.notification_of_dedupe(task_id, f"progress:{task_id}")
        assert progress.payload == {"text": "进度1"}  # 后到覆盖（合并语义）
        assert progress.state is NotificationState.PENDING


# ── 输入与审批（§6.10） ──────────────────────────────────


class TestInputs:
    def _running(self, store):
        task_id, _ = _submit(store)
        _task, attempt = _claim(store)
        store.transition_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        return task_id, attempt

    def test_register_input_moves_task_to_waiting(self, store):
        task_id, attempt = self._running(store)
        request_id = store.register_input_request(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            backend_request_id="br-1",
            kind="input",
            question="需要哪个分支？",
            schema={"type": "string"},
            options=[],
            expires_at=utc_now() + timedelta(seconds=600),
        )
        assert request_id
        task = store.get_task(task_id)
        assert task.state is TaskState.WAITING_INPUT
        assert task.waiting_request_id == request_id
        notification = store.notification_of_dedupe(
            task_id, f"input:{task_id}:{request_id}"
        )
        assert notification is not None

    def test_respond_answer_then_conflict(self, store):
        task_id, attempt = self._running(store)
        request_id = store.register_input_request(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            backend_request_id="br-1",
            kind="input",
            question="?",
            schema={},
            options=[],
            expires_at=utc_now() + timedelta(seconds=600),
        )
        record = store.get_input_request(request_id)
        status, _, _ = store.respond_input(
            request_id, "main", actor="u777", expected_revision=record.revision
        )
        assert status == "queued"
        # 相同内容重复答复 → 幂等
        status2, _, _ = store.respond_input(
            request_id, "main", actor="u777", expected_revision=record.revision
        )
        assert status2 == "answered_before"
        # 不同内容 → 冲突
        with pytest.raises(InputRequestStateError):
            store.respond_input(
                request_id, "dev", actor="u777", expected_revision=record.revision
            )

    def test_respond_rejects_stale_revision(self, store):
        task_id, attempt = self._running(store)
        request_id = store.register_input_request(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            backend_request_id="br-1",
            kind="input",
            question="?",
            schema={},
            options=[],
            expires_at=utc_now() + timedelta(seconds=600),
        )
        with pytest.raises(InputRequestStateError, match="revision"):
            store.respond_input(request_id, "x", actor="u", expected_revision=99)

    def test_expired_input_interrupts_task(self, store):
        task_id, attempt = self._running(store)
        store.register_input_request(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            backend_request_id="br-1",
            kind="input",
            question="?",
            schema={},
            options=[],
            expires_at=utc_now() - timedelta(seconds=1),
        )
        interrupted = store.expire_stale_inputs()
        assert task_id in interrupted
        assert store.get_task(task_id).state is TaskState.CANCELLING


# ── 通知投递 CAS（§6.3 事务边界 5 / §6.5） ────────────────


class TestNotifications:
    def test_claim_is_exclusive(self, store):
        task_id, _ = _submit(store)
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        first = store.claim_notification(ack.notification_id)
        second = store.claim_notification(ack.notification_id)
        assert first is not None
        assert second is None  # 入口与 pump 竞争只有一个发送者

    def test_mark_sent_and_delivery_state(self, store):
        task_id, _ = _submit(store)
        _task, attempt = _claim(store)
        store.finish_task(
            task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            outcome=Outcome.SUCCEEDED,
            state=TaskState.SUCCEEDED,
            summary="done",
        )
        final = store.notification_of_dedupe(task_id, f"final:{task_id}")
        store.claim_notification(final.notification_id)
        assert store.mark_notification(
            final.notification_id, state=NotificationState.SENT, receipt="msg-1"
        )
        assert store.get_task(task_id).delivery_state == "sent"

    def test_delivery_unknown_is_terminal_no_retry(self, store):
        task_id, _ = _submit(store)
        ack = store.notification_of_dedupe(task_id, f"ack:{task_id}")
        store.claim_notification(ack.notification_id)
        store.mark_notification(
            ack.notification_id, state=NotificationState.DELIVERY_UNKNOWN, error="timeout"
        )
        due = store.due_notifications()
        assert all(n.notification_id != ack.notification_id for n in due)


# ── worker 租约与恢复 ────────────────────────────────────


class TestWorkersAndRecovery:
    def test_second_worker_rejected_while_first_alive(self, store):
        epoch = store.register_worker("inst-1", "w1", "pid:1", lease_seconds=30.0)
        assert epoch == 1
        with pytest.raises(Exception, match="worker"):
            store.register_worker("inst-1", "w2", "pid:2", lease_seconds=30.0)

    def test_worker_takeover_after_expiry(self, store):
        store.register_worker("inst-1", "w1", "pid:1", lease_seconds=1.0)
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE worker_leases SET lease_until_utc = ? WHERE instance_id = 'inst-1'",
            (iso_utc(utc_now() - timedelta(seconds=5)),),
        )
        conn.commit()
        conn.close()
        epoch = store.register_worker("inst-1", "w2", "pid:2", lease_seconds=30.0)
        assert epoch == 2

    def test_recovery_flow_to_recovery_required(self, store):
        _submit(store)
        task, attempt = _claim(store)
        # 模拟宿主崩溃：租约过期
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE attempts SET lease_until_utc = ? WHERE attempt_id = ?",
            (iso_utc(utc_now() - timedelta(seconds=60)), attempt.attempt_id),
        )
        conn.commit()
        conn.close()
        need = store.tasks_needing_recovery("inst-1", now=utc_now())
        assert [t.task_id for t in need] == [task.task_id]
        assert store.begin_recovery(task.task_id)
        store.mark_recovery_required(task.task_id, reason="dispatch_unknown")
        assert store.get_task(task.task_id).state is TaskState.RECOVERY_REQUIRED
        kinds = [e.kind for e in store.events_page(task.task_id)]
        assert EventKind.RECOVERY_REQUIRED in kinds

    def test_requeue_starting_task(self, store):
        _submit(store)
        task, _attempt = _claim(store)
        store.begin_recovery(task.task_id)
        assert store.requeue_task(task.task_id, reason="not_dispatched")
        record = store.get_task(task.task_id)
        assert record.state is TaskState.QUEUED
        assert record.current_attempt == ""


# ── 期限 ─────────────────────────────────────────────────


class TestDeadlines:
    def test_expired_queued_task_cancelled_directly(self, store):
        task_id, _ = _submit(store, task_timeout=-1.0)
        expired = store.enforce_deadlines()
        assert task_id in expired
        assert store.get_task(task_id).state is TaskState.CANCELLED

    def test_expired_running_task_goes_cancelling(self, store):
        task_id, _ = _submit(store)  # 先给正常期限以便认领
        task, attempt = _claim(store)
        store.transition_task(
            task.task_id,
            attempt_id=attempt.attempt_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        # 运行中把期限改成已过期
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.execute(
            "UPDATE tasks SET deadline_utc = ? WHERE task_id = ?",
            (iso_utc(utc_now() - timedelta(seconds=1)), task_id),
        )
        conn.commit()
        conn.close()
        expired = store.enforce_deadlines()
        assert task_id in expired
        assert store.get_task(task_id).state is TaskState.CANCELLING
        # 控制命令已注入，worker 消费后落 timed_out
        controls = store.pending_controls_for_task(
            task_id,
            owner="w1",
            epoch=attempt.lease_epoch,
            attempt_id=attempt.attempt_id,
        )
        assert [c.kind for c in controls] == [ControlKind.CANCEL]

    def test_alive_tasks_not_touched(self, store):
        task_id, _ = _submit(store, task_timeout=3600.0)
        assert store.enforce_deadlines() == []
        assert store.get_task(task_id).state is TaskState.QUEUED


# ── 审计与查询 ───────────────────────────────────────────


class TestQueries:
    def test_audit_and_list(self, store):
        task_id, _ = _submit(store)
        store.audit(actor="u777", action="submit", task_id=task_id)
        tasks = store.list_tasks("inst-1")
        assert len(tasks) == 1
        tasks_777 = store.list_tasks("inst-1", requester_id="777")
        assert len(tasks_777) == 1
        assert store.list_tasks("inst-1", requester_id="999") == []

    def test_missing_task(self, store):
        assert store.get_task("nonexistent") is None
        with pytest.raises(TaskNotFoundError):
            store.request_cancel("nonexistent", actor="u")
