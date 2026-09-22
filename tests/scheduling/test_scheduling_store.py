# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""调度库存取层的行为基线（幂等插入 / 修订门闩 / 租约 / 配额 / 重启恢复）。

时间用注入的固定 ``datetime``，不依赖真实时钟——租约过期、每日配额这类
「跟时间走」的判定必须可复现。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from stella_project.plugins.bot_main.scheduling.migrations import (
    MigrationError,
    migrate,
)
from stella_project.plugins.bot_main.scheduling.models import (
    NotificationMode,
    RunState,
    TaskMode,
    TaskStatus,
    iso_utc,
)
from stella_project.plugins.bot_main.scheduling.store import (
    GroupTaskLimitError,
    StaleRevisionError,
    TaskNotFoundError,
    TaskStore,
)

UTC = timezone.utc
T0 = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture()
def store(tmp_path):
    return TaskStore(tmp_path / "scheduling" / "tasks.db")


def _make_task(store: TaskStore, **overrides):
    params = {
        "bot_id": "10000",
        "group_id": 12345,
        "owner_id": 777,
        "mode": TaskMode.REMINDER,
        "objective": "提醒大家喝水",
        "cron_expr": "0 9 * * MON-FRI",
        "timezone": "Asia/Shanghai",
        "notification_mode": NotificationMode.ALWAYS,
    }
    params.update(overrides)
    return store.create_task(**params)


def _insert(store: TaskStore, task_id: str, offset_seconds: float, **kwargs):
    return store.insert_run(task_id, scheduled_for=_at(offset_seconds), **kwargs)


# ── 迁移 ─────────────────────────────────────────────

def test_migrate_is_idempotent_and_records_version(tmp_path):
    db = tmp_path / "scheduling" / "tasks.db"
    migrate(db)
    migrate(db)  # 重复调用必须空操作
    import sqlite3

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    conn.close()
    assert int(row[0]) >= 1


def test_migrate_rejects_downgrade(tmp_path):
    db = tmp_path / "tasks.db"
    migrate(db)
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(MigrationError, match="降级"):
        migrate(db)


# ── 任务 CRUD 与修订门闩 ─────────────────────────────

def test_create_and_get_task_roundtrip(store):
    task = _make_task(store)
    loaded = store.get_task(task.task_id)
    assert loaded is not None
    assert loaded.revision == 1
    assert loaded.status is TaskStatus.ACTIVE
    assert loaded.mode is TaskMode.REMINDER
    assert loaded.objective == "提醒大家喝水"
    assert loaded.notification_mode is NotificationMode.ALWAYS
    assert loaded.created_at is not None and loaded.updated_at is not None


def test_edit_bumps_revision_and_stale_revision_rejected(store):
    task = _make_task(store)
    edited = store.edit_task(
        task.task_id,
        task.revision,
        updates={"objective": "提醒大家开会", "cron_expr": "30 8 * * *"},
    )
    assert edited.revision == 2
    assert edited.objective == "提醒大家开会"
    assert edited.cron_expr == "30 8 * * *"
    with pytest.raises(StaleRevisionError):
        store.edit_task(task.task_id, task.revision, updates={"objective": "过期写入"})
    with pytest.raises(TaskNotFoundError):
        store.edit_task("no-such-task", 1, updates={"objective": "x"})


def test_pause_resume_cancel_with_fencing(store):
    task = _make_task(store)
    paused = store.set_status(task.task_id, task.revision, TaskStatus.PAUSED)
    assert paused.status is TaskStatus.PAUSED and paused.revision == 2
    with pytest.raises(StaleRevisionError):
        store.set_status(task.task_id, task.revision, TaskStatus.ACTIVE)
    resumed = store.set_status(task.task_id, paused.revision, TaskStatus.ACTIVE)
    assert resumed.status is TaskStatus.ACTIVE and resumed.revision == 3
    cancelled = store.set_status(task.task_id, resumed.revision, TaskStatus.CANCELLED)
    assert cancelled.status is TaskStatus.CANCELLED and cancelled.revision == 4


def test_cancel_sweeps_queued_runs(store):
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    store.set_status(task.task_id, task.revision, TaskStatus.CANCELLED)
    run = store.get_run(run_id)
    assert run.state is RunState.CANCELLED
    assert run.error == "task_cancelled"


def test_group_task_limit(store):
    _make_task(store, max_tasks_per_group=1)
    with pytest.raises(GroupTaskLimitError):
        _make_task(store, max_tasks_per_group=1)


def test_list_tasks_filters_cancelled_and_owner(store):
    task_a = _make_task(store, owner_id=1)
    task_b = _make_task(store, owner_id=2)
    store.set_status(task_b.task_id, task_b.revision, TaskStatus.CANCELLED)
    ids = {t.task_id for t in store.list_tasks(12345)}
    assert ids == {task_a.task_id}
    owner_two = store.list_tasks(12345, owner_id=2, include_cancelled=True)
    assert [t.task_id for t in owner_two] == [task_b.task_id]


# ── 运行插入与幂等 ───────────────────────────────────

def test_duplicate_occurrence_insert_is_idempotent(store):
    task = _make_task(store)
    first = _insert(store, task.task_id, 60)
    second = _insert(store, task.task_id, 60)
    assert first is not None and second is None


def test_edit_allows_new_occurrence_at_same_time_under_new_revision(store):
    task = _make_task(store)
    first = _insert(store, task.task_id, 60)
    store.edit_task(task.task_id, task.revision, updates={"objective": "v2"})
    # 旧运行仍占着活跃名额：同一时刻的新触发先被「任务忙」挡住
    assert _insert(store, task.task_id, 60) is None
    store.claim_next_run("w", now=_at(60), lease_seconds=600)
    store.transition_run(
        first, "w", from_states=(RunState.CLAIMED,), to_state=RunState.SENT
    )
    # 名额释放后，新修订下的同一触发时刻是新的一次触发（幂等键含 revision）
    assert _insert(store, task.task_id, 60) is not None


def test_manual_run_dedupes_by_request_id(store):
    task = _make_task(store)
    first = store.insert_run(task.task_id, request_id="req-1")
    # 任务忙（已有活跃运行）：任何新触发都入不了队——不同 request_id 也一样
    assert store.insert_run(task.task_id, request_id="req-1") is None
    assert store.insert_run(task.task_id, request_id="req-2") is None
    claimed = store.claim_next_run("w", now=_at(0), lease_seconds=600)
    assert claimed is not None and claimed.run_id == first
    store.transition_run(
        first, "w", from_states=(RunState.CLAIMED,), to_state=RunState.SENT
    )
    # 完成后：重放同一 request_id 仍被幂等键挡住（不重复执行）；新请求正常入队
    assert store.insert_run(task.task_id, request_id="req-1") is None
    assert store.insert_run(task.task_id, request_id="req-2") is not None


def test_insert_run_ignores_when_task_busy(store):
    """每任务至多一个活跃运行：已有排队运行时，新触发不入队（返回 None）。"""
    task = _make_task(store)
    assert _insert(store, task.task_id, 60) is not None
    assert _insert(store, task.task_id, 120) is None


def test_insert_run_requires_identifier(store):
    task = _make_task(store)
    with pytest.raises(ValueError):
        store.insert_run(task.task_id)


# ── 认领与群串行 ─────────────────────────────────────

def test_claim_picks_earliest_due_run_and_sets_lease(store):
    """两条到期运行（不同任务、同群）：先到期的先认领。"""
    first_task = _make_task(store)
    second_task = _make_task(store, cron_expr="0 10 * * MON-FRI")
    later = _insert(store, first_task.task_id, 120)
    earlier = _insert(store, second_task.task_id, 60)
    claimed = store.claim_next_run("worker-a", now=_at(61), lease_seconds=600)
    assert claimed is not None and claimed.run_id == earlier
    assert claimed.state is RunState.CLAIMED
    assert claimed.lease_owner == "worker-a"
    assert claimed.lease_expires_utc is not None
    assert claimed.task_id == second_task.task_id
    assert later is not None  # 另一条仍在队列
    usage = store.quota_usage(12345, now=_at(61))
    assert usage["runs_used"] == 1


def test_claim_skips_future_runs(store):
    task = _make_task(store)
    _insert(store, task.task_id, 3600)
    assert store.claim_next_run("worker-a", now=_at(0), lease_seconds=600) is None


def test_claim_respects_group_serialization(store):
    """同群已有执行中运行时本轮不认领（保留队列，等它结束）。"""
    task1 = _make_task(store)
    _insert(store, task1.task_id, 60)
    task2 = _make_task(store, cron_expr="0 10 * * MON-FRI")
    second = _insert(store, task2.task_id, 61)
    first_claimed = store.claim_next_run("w", now=_at(60), lease_seconds=600)
    assert first_claimed is not None
    # task2 的运行仍在排队：执行中的 task1 挡住它，claim 返回 None
    assert store.claim_next_run("w", now=_at(63), lease_seconds=600) is None
    # 活跃计数 = 1 执行中 + 1 排队
    assert store.count_group_active_runs(12345) == 2
    # 第一条结束（终态）后，第二条可以被认领
    store.transition_run(
        first_claimed.run_id, "w", from_states=(RunState.CLAIMED,), to_state=RunState.SENT
    )
    claimed = store.claim_next_run("w", now=_at(64), lease_seconds=600)
    assert claimed is not None and claimed.run_id == second


def test_claim_sweeps_stale_revision_then_claims_current(store):
    task = _make_task(store)
    stale_run = _insert(store, task.task_id, 60)
    store.edit_task(task.task_id, task.revision, updates={"objective": "v2"})
    # 旧修订的排队运行还占着活跃名额，重插会先被挡住
    assert _insert(store, task.task_id, 60) is None
    # 认领扫描把过期修订的队头运行作废（skipped），本轮无可认领
    assert store.claim_next_run("w", now=_at(120), lease_seconds=600) is None
    stale = store.get_run(stale_run)
    assert stale.state is RunState.SKIPPED and stale.error == "revision_stale"
    # 名额释放后（运行时下一轮扫描重插），新修订的运行正常认领
    fresh = _insert(store, task.task_id, 60)
    claimed = store.claim_next_run("w", now=_at(121), lease_seconds=600)
    assert claimed is not None and claimed.run_id == fresh


def test_claim_sweeps_paused_task_runs(store):
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    store.set_status(task.task_id, task.revision, TaskStatus.PAUSED)
    claimed = store.claim_next_run("w", now=_at(120), lease_seconds=600)
    assert claimed is None
    run = store.get_run(run_id)
    assert run.state is RunState.SKIPPED and run.error == "task_paused"


def test_quota_cap_skips_run_not_blocks_worker(store):
    """配额满：该运行被跳过（终态可查），后续候选/明日运行不受牵连。"""
    task = _make_task(store)
    _insert(store, task.task_id, 60)
    first = store.claim_next_run("w", now=_at(60), lease_seconds=600, daily_group_run_cap=1)
    assert first is not None
    assert store.transition_run(
        first.run_id, "w", from_states=(RunState.CLAIMED,), to_state=RunState.SENT
    )
    task2 = _make_task(store, cron_expr="0 10 * * MON-FRI")
    second_run = _insert(store, task2.task_id, 120)
    claimed = store.claim_next_run("w", now=_at(120), lease_seconds=600, daily_group_run_cap=1)
    assert claimed is None
    skipped = store.get_run(second_run)
    assert skipped.state is RunState.SKIPPED and skipped.error == "quota_exceeded"
def test_claim_handles_manual_runs(store):
    task = _make_task(store)
    run_id = store.insert_run(task.task_id, request_id="req-1")
    claimed = store.claim_next_run("w", now=_at(0), lease_seconds=600)
    assert claimed is not None and claimed.run_id == run_id


# ── 租约续期与恢复 ───────────────────────────────────

def test_renew_lease_extends_and_fails_after_state_change(store):
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    claimed = store.claim_next_run("w", now=_at(60), lease_seconds=60)
    assert store.renew_lease(run_id, "w", seconds=60, now=_at(90))
    renewed = store.get_run(run_id)
    assert renewed.lease_expires_utc > claimed.lease_expires_utc
    assert not store.renew_lease(run_id, "worker-b", seconds=60, now=_at(91))


def test_recover_expired_lease_requeues_running_run(store):
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    store.claim_next_run("w", now=_at(60), lease_seconds=60)
    store.mark_running(run_id, "w")
    counts = store.recover_expired_leases(now=_at(121))
    assert counts["requeued"] == 1
    run = store.get_run(run_id)
    assert run.state is RunState.QUEUED and run.lease_owner == ""


def test_recover_sending_lease_becomes_delivery_unknown(store):
    """sending 中 worker 死亡 → delivery_unknown，绝不自动重投。"""
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    store.claim_next_run("w", now=_at(60), lease_seconds=60)
    assert store.transition_run(
        run_id, "w", from_states=(RunState.CLAIMED,), to_state=RunState.SENDING
    )
    counts = store.recover_expired_leases(now=_at(121))
    assert counts["delivery_unknown"] == 1
    run = store.get_run(run_id)
    assert run.state is RunState.DELIVERY_UNKNOWN
    assert run.delivery_error == "worker_died_after_send_call"


def test_recover_ignores_live_leases(store):
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    store.claim_next_run("w", now=_at(60), lease_seconds=600)
    counts = store.recover_expired_leases(now=_at(61))
    assert counts == {"requeued": 0, "delivery_unknown": 0}
    assert store.get_run(run_id).state is RunState.CLAIMED


# ── worker 单租约 ────────────────────────────────────

def test_worker_lease_single_holder_and_takeover(store):
    assert store.acquire_worker_lease("w1", ttl_seconds=60, now=_at(0))
    assert not store.acquire_worker_lease("w2", ttl_seconds=60, now=_at(1))
    assert store.renew_worker_lease("w1", ttl_seconds=60, now=_at(30))
    # 持有期内 w2 无法接管；过期后 w2 接管成功，w1 的续租与再获取都失败
    assert not store.acquire_worker_lease("w2", ttl_seconds=60, now=_at(89))
    assert store.acquire_worker_lease("w2", ttl_seconds=60, now=_at(91))
    assert not store.renew_worker_lease("w1", ttl_seconds=60, now=_at(92))
    assert not store.acquire_worker_lease("w1", ttl_seconds=60, now=_at(92))
    store.release_worker_lease("w2")
    assert store.acquire_worker_lease("w1", ttl_seconds=60, now=_at(93))


# ── 重启恢复与审计 ───────────────────────────────────

def test_state_survives_reopen(tmp_path):
    db = tmp_path / "scheduling" / "tasks.db"
    store = TaskStore(db)
    task = _make_task(store)
    run_id = _insert(store, task.task_id, 60)
    store.claim_next_run("w", now=_at(60), lease_seconds=600)
    reopened = TaskStore(db)
    task_after = reopened.get_task(task.task_id)
    assert task_after is not None and task_after.revision == task.revision
    run_after = reopened.get_run(run_id)
    assert run_after is not None and run_after.state is RunState.CLAIMED


def test_audit_roundtrip(store):
    task = _make_task(store)
    store.record_audit(
        "create", actor_id=777, group_id=12345, task_id=task.task_id, detail="创建提醒"
    )
    store.record_audit("pause", actor_id=888, group_id=99999)
    entries = store.list_audit(12345)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_id == 777
    assert entry.action == "create"
    assert entry.task_id == task.task_id
    assert entry.detail == "创建提醒"
    assert entry.created_at_utc is not None
    assert len(store.list_audit()) == 2


def test_record_task_fired_updates_cache(store):
    task = _make_task(store)
    store.record_task_fired(
        task.task_id, last_run_utc=_at(60), next_run_utc=_at(3660)
    )
    loaded = store.get_task(task.task_id)
    assert loaded.revision == 1  # 缓存刷新不动修订
    assert iso_utc(loaded.last_run_utc) == iso_utc(_at(60))
    assert iso_utc(loaded.next_run_utc) == iso_utc(_at(3660))
