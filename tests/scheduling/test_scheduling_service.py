# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""生命周期服务的基线：权限矩阵、群边界、修订门闩、审计与立即运行。"""

from __future__ import annotations

import pytest

from stella_project.plugins.bot_main.scheduling.cron import CronError
from stella_project.plugins.bot_main.scheduling.models import (
    NotificationMode,
    RunState,
    TaskMode,
    TaskStatus,
)
from stella_project.plugins.bot_main.scheduling.service import (
    InvalidTaskError,
    PermissionDeniedError,
    RunNotQueuedError,
    SchedulingLimits,
    SchedulingService,
    normalize_policy,
)
from stella_project.plugins.bot_main.scheduling.store import (
    GroupTaskLimitError,
    StaleRevisionError,
    TaskNotFoundError,
    TaskStore,
)

GROUP_A = 12345
GROUP_B = 67890
OWNER = 1001          # 群普通成员，任务创建者
STRANGER = 1002       # 同群普通成员，与任务无关
ADMIN = 2001          # 群管理员


@pytest.fixture()
def store(tmp_path):
    return TaskStore(tmp_path / "scheduling.db")


@pytest.fixture()
def service(store):
    return SchedulingService(
        store,
        limits=SchedulingLimits(max_tasks_per_group=5, max_tasks_per_user=2),
    )


def _create(service: SchedulingService, *, actor=OWNER, group=GROUP_A, mode="reminder",
            objective="提醒喝水", admin=False, **overrides):
    params = {
        "actor_id": actor,
        "group_id": group,
        "bot_id": "10000",
        "is_group_admin": admin,
        "mode": mode,
        "objective": objective,
        "cron_expr": "0 9 * * MON-FRI",
        "timezone": "Asia/Shanghai",
    }
    params.update(overrides)
    return service.create_task(**params)


# ── 创建与默认值 ─────────────────────────────────────

def test_member_creates_reminder_with_defaults(service):
    task = _create(service)
    assert task.mode is TaskMode.REMINDER
    assert task.status is TaskStatus.ACTIVE
    assert task.notification_mode is NotificationMode.ALWAYS
    assert task.policy == {"coalesce": "all", "tools": []}
    assert task.next_run_utc is not None  # 创建即给出触发预览
    assert task.revision == 1


def test_agent_task_requires_admin(service):
    with pytest.raises(PermissionDeniedError):
        _create(service, mode="agent", objective="总结群聊", admin=False)
    task = _create(service, mode="agent", objective="总结群聊", admin=ADMIN, actor=ADMIN)
    assert task.mode is TaskMode.AGENT
    assert task.notification_mode is NotificationMode.ON_CONTENT
    assert task.policy["coalesce"] == "latest"


def test_create_validates_objective_and_cron(service):
    with pytest.raises(InvalidTaskError):
        _create(service, objective="   ")
    with pytest.raises(InvalidTaskError):
        _create(service, objective="x" * 501)
    with pytest.raises(CronError):
        _create(service, cron_expr="0 9 * * 1")  # 数字星期被拒
    with pytest.raises(CronError):
        _create(service, timezone="Mars/Phobos")


def test_reminder_cannot_carry_tool_allowlist(service):
    with pytest.raises(InvalidTaskError):
        _create(service, policy={"tools": ["mcp_fs_read"]})


def test_per_user_task_limit(service):
    _create(service, objective="任务一")
    _create(service, objective="任务二")
    with pytest.raises(GroupTaskLimitError, match="上限"):
        _create(service, objective="任务三")


def test_admin_is_exempt_from_per_user_limit(service):
    for i in range(4):
        _create(service, objective=f"管理员任务{i}", actor=ADMIN, admin=True)
    assert len(service.list_tasks(group_id=GROUP_A)) == 4


# ── 群边界与权限矩阵 ─────────────────────────────────

def test_cross_group_access_is_denied_without_leaking(service):
    """任务id 按群解析：他群的任务id 看起来就是「找不到」，不泄露存在性。"""
    task = _create(service)
    with pytest.raises(TaskNotFoundError, match="找不到"):
        service.show_task(actor_id=STRANGER, group_id=GROUP_B, task_id_prefix=task.task_id[:6])


def test_cross_group_mutation_blocked_and_not_audited(service):
    """拿别群任务的完整 id 直接走 store 通道也会被群边界挡下（纵深防御）。"""
    task = _create(service)
    with pytest.raises(PermissionDeniedError):
        service._load_task_in_group(task.task_id, GROUP_B)
    with pytest.raises(TaskNotFoundError):
        service.pause(actor_id=STRANGER, group_id=GROUP_B, is_group_admin=True,
                      task_id_prefix=task.task_id[:6], expected_revision=task.revision)
    assert service.audit_log(group_id=GROUP_B) == []


def test_non_owner_member_cannot_mutate(service):
    task = _create(service)
    with pytest.raises(PermissionDeniedError):
        service.pause(actor_id=STRANGER, group_id=GROUP_A,
                      task_id_prefix=task.task_id[:6], expected_revision=task.revision)
    with pytest.raises(PermissionDeniedError):
        service.cancel(actor_id=STRANGER, group_id=GROUP_A,
                       task_id_prefix=task.task_id[:6], expected_revision=task.revision)


def test_admin_can_manage_others_task(service):
    task = _create(service)
    paused = service.pause(actor_id=ADMIN, group_id=GROUP_A, is_group_admin=True,
                           task_id_prefix=task.task_id[:6], expected_revision=task.revision)
    assert paused.status is TaskStatus.PAUSED
    resumed = service.resume(actor_id=ADMIN, group_id=GROUP_A, is_group_admin=True,
                             task_id_prefix=task.task_id[:6], expected_revision=paused.revision)
    assert resumed.status is TaskStatus.ACTIVE


def test_cancelled_task_rejects_further_operations(service):
    task = _create(service)
    cancelled = service.cancel(actor_id=OWNER, group_id=GROUP_A,
                               task_id_prefix=task.task_id[:6],
                               expected_revision=task.revision)
    assert cancelled.status is TaskStatus.CANCELLED
    with pytest.raises(InvalidTaskError):
        service.pause(actor_id=OWNER, group_id=GROUP_A,
                      task_id_prefix=task.task_id[:6],
                      expected_revision=cancelled.revision)
    with pytest.raises(InvalidTaskError):
        service.run_now(actor_id=OWNER, group_id=GROUP_A,
                        task_id_prefix=task.task_id[:6])


# ── id 前缀解析 ──────────────────────────────────────

def test_task_id_prefix_resolution_and_ambiguity(service):
    task1 = _create(service, objective="一")
    task2 = _create(service, objective="二")
    # 前缀唯一时可用
    shown = service.show_task(actor_id=STRANGER, group_id=GROUP_A,
                              task_id_prefix=task1.task_id[:6])
    assert shown.task_id == task1.task_id
    # 制造同前缀的第二个任务：歧义必须报错而不是猜测
    shared_prefix = task1.task_id[:4]
    if task2.task_id.startswith(shared_prefix):
        with pytest.raises(InvalidTaskError, match="命中"):
            service.show_task(actor_id=STRANGER, group_id=GROUP_A,
                              task_id_prefix=shared_prefix)
    with pytest.raises(TaskNotFoundError):
        service.show_task(actor_id=STRANGER, group_id=GROUP_A, task_id_prefix="zzzzzz")


# ── 编辑与策略 ───────────────────────────────────────

def test_owner_edits_cron_and_revision_fencing(service):
    task = _create(service)
    updated = service.edit_task(
        actor_id=OWNER, group_id=GROUP_A, task_id_prefix=task.task_id[:6],
        expected_revision=task.revision, cron_expr="30 8 * * *", timezone="UTC+8",
    )
    assert updated.revision == 2
    assert updated.cron_expr == "30 8 * * *"
    assert updated.timezone == "UTC+8"
    assert updated.next_run_utc is not None
    with pytest.raises(StaleRevisionError):
        service.edit_task(
            actor_id=OWNER, group_id=GROUP_A, task_id_prefix=task.task_id[:6],
            expected_revision=task.revision, objective="过期写入",
        )


def test_policy_edit_requires_admin(service):
    task = _create(service, mode="agent", actor=ADMIN, admin=True, objective="目标")
    with pytest.raises(PermissionDeniedError):
        service.edit_task(
            actor_id=OWNER, group_id=GROUP_A, task_id_prefix=task.task_id[:6],
            expected_revision=task.revision, is_group_admin=False,
            policy={"tools": ["x"]},
        )
    updated = service.edit_task(
        actor_id=ADMIN, group_id=GROUP_A, task_id_prefix=task.task_id[:6],
        expected_revision=task.revision, is_group_admin=True,
        policy={"tools": ["mcp_fs_read"], "coalesce": "all"},
    )
    assert updated.policy == {"coalesce": "all", "tools": ["mcp_fs_read"]}


def test_unknown_edit_field_is_rejected(service):
    task = _create(service)
    with pytest.raises(ValueError):
        # store 层白名单兜底：owner_id 这类身份字段不允许从编辑通道改
        service.store.edit_task(task.task_id, task.revision, updates={"owner_id": 666})


# ── 立即运行与历史 ───────────────────────────────────

def test_run_now_queues_and_dedupes(service):
    task = _create(service)
    run = service.run_now(actor_id=OWNER, group_id=GROUP_A,
                          task_id_prefix=task.task_id[:6], request_id="req-1")
    assert run.state is RunState.QUEUED
    assert run.is_manual
    with pytest.raises(RunNotQueuedError):
        service.run_now(actor_id=OWNER, group_id=GROUP_A,
                        task_id_prefix=task.task_id[:6], request_id="req-2")


def test_history_visible_to_owner_and_admin_only(service):
    task = _create(service)
    service.run_now(actor_id=OWNER, group_id=GROUP_A, task_id_prefix=task.task_id[:6])
    runs = service.history(actor_id=OWNER, group_id=GROUP_A,
                           task_id_prefix=task.task_id[:6])
    assert len(runs) == 1
    assert service.history(actor_id=ADMIN, group_id=GROUP_A, is_group_admin=True,
                           task_id_prefix=task.task_id[:6])
    with pytest.raises(PermissionDeniedError):
        service.history(actor_id=STRANGER, group_id=GROUP_A,
                        task_id_prefix=task.task_id[:6])


# ── 审计 ─────────────────────────────────────────────

def test_mutations_are_audited(service):
    task = _create(service)
    service.pause(actor_id=ADMIN, group_id=GROUP_A, is_group_admin=True,
                  task_id_prefix=task.task_id[:6], expected_revision=task.revision)
    service.edit_task(actor_id=OWNER, group_id=GROUP_A, task_id_prefix=task.task_id[:6],
                      expected_revision=2, objective="新目标")
    service.run_now(actor_id=OWNER, group_id=GROUP_A, task_id_prefix=task.task_id[:6])
    actions = [e.action for e in service.audit_log(group_id=GROUP_A)]
    assert actions == ["run_now", "edit", "pause", "create"]
    entry = service.audit_log(group_id=GROUP_A)[-1]
    assert entry.actor_id == OWNER
    assert entry.group_id == GROUP_A
    assert entry.task_id == task.task_id
    assert "reminder" in entry.detail


# ── 策略规范化 ───────────────────────────────────────

def test_normalize_policy_defaults_and_validation():
    assert normalize_policy(None, mode=TaskMode.REMINDER) == {
        "coalesce": "all", "tools": [],
    }
    assert normalize_policy({}, mode=TaskMode.AGENT) == {
        "coalesce": "latest", "tools": [],
    }
    assert normalize_policy({"coalesce": "LATEST"}, mode=TaskMode.REMINDER) == {
        "coalesce": "latest", "tools": [],
    }
    with pytest.raises(InvalidTaskError):
        normalize_policy({"coalesce": "sometimes"}, mode=TaskMode.AGENT)
    with pytest.raises(InvalidTaskError):
        normalize_policy({"tools": "not-a-list"}, mode=TaskMode.AGENT)
