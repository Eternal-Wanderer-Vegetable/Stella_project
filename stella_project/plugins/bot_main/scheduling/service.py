# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""任务生命周期服务：CRUD / 暂停恢复 / 立即运行 / 历史 + 权限与审计。

权限矩阵（计划 §6.3，v1 仅群任务）：

- **群成员**：创建 / 编辑 / 暂停恢复取消 **自己的 reminder 任务**；
- **群主 / 群管理员 / 全局管理员**（``is_admin=True`` 由 QQ 边界注入）：
  - 创建 agent 任务（模型调用是花钱花算力的路径，不对普通成员开放）；
  - 修改任务策略（工具允许清单、补跑策略）；
  - 管理**他人**的任务（含 agent 任务）；
- **跨群**：一切操作只认「操作者当前所在的群」，对别的群的任务id 操作一律
  拒绝并审计——任务id 即使泄露也无法跨群使用。

每次受控变更都写审计（谁、哪个群、哪个任务、做了什么、摘要细节）。审计写入
失败不阻断业务（store 侧已兜底）。

同步 API：SQLite 短连接，与 memory/ 各模块的调用习惯一致（QQ handler 直接调，
不必包线程）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from nonebot import logger

from .cron import CronError, CronSchedule, parse_cron
from .models import (
    CoalesceMode,
    NotificationMode,
    Run,
    Task,
    TaskMode,
    TaskStatus,
    utc_now,
)
from .store import (
    GroupTaskLimitError,
    TaskNotFoundError,
    TaskStore,
)

# objective 的长度上限：它是模型目标（agent）或群消息（reminder），不是文章
_DEFAULT_OBJECTIVE_MAX_CHARS = 500


class SchedulingServiceError(ValueError):
    """生命周期服务的用户可读错误基类（message 可直接回帖）。"""


class PermissionDeniedError(SchedulingServiceError):
    """权限不足或跨群操作。"""


class InvalidTaskError(SchedulingServiceError):
    """任务参数非法（objective / 模式 / 策略）。"""


class RunNotQueuedError(SchedulingServiceError):
    """立即运行未能入队（已有运行在进行，或请求重复提交）。"""


@dataclass(slots=True)
class SchedulingLimits:
    """部署侧限制（Phase 8 从 config/settings 注入；测试可覆盖）。

    ``global_admin_ids`` 是配置级的全局管理员（QQ 号）集合——群主/群管理员之外
    的第三类授权来源。
    """

    max_tasks_per_group: int = 8
    max_tasks_per_user: int = 3
    daily_group_run_cap: int = 40
    objective_max_chars: int = _DEFAULT_OBJECTIVE_MAX_CHARS
    allow_agent_mode: bool = True
    global_admin_ids: frozenset[int] = field(default_factory=frozenset)


def normalize_policy(policy: dict | None, *, mode: TaskMode) -> dict:
    """校验并规范化策略 JSON（未知键丢弃，取值非法抛 :class:`InvalidTaskError`）。

    v1 键位：

    - ``coalesce``：``latest``（agent 默认）| ``all``（reminder 默认）——
      错过多次触发时补跑最近一次还是逐个补；
    - ``tools``：允许的工具名列表（仅 agent 任务；空 = 纯模型轮，不挂任何工具）。
    """
    policy = policy or {}
    if not isinstance(policy, dict):
        raise InvalidTaskError("策略必须是 JSON 对象")
    if mode is TaskMode.REMINDER and policy.get("tools"):
        raise InvalidTaskError("reminder 任务不能配置工具允许清单")
    tools_raw = policy.get("tools", [])
    if not isinstance(tools_raw, list) or not all(isinstance(t, str) for t in tools_raw):
        raise InvalidTaskError("tools 必须是字符串列表")
    if len(tools_raw) != len(set(tools_raw)):
        raise InvalidTaskError("tools 存在重复项")
    coalesce_raw = policy.get("coalesce")
    if coalesce_raw is None:
        coalesce = (
            CoalesceMode.ALL if mode is TaskMode.REMINDER else CoalesceMode.LATEST
        )
    else:
        try:
            # 大小写不敏感：聊天输入里的 "Latest"/"LATEST" 都接受
            coalesce = CoalesceMode(str(coalesce_raw).strip().lower())
        except ValueError as e:
            raise InvalidTaskError(f"coalesce 只能是 latest/all，收到 {coalesce_raw!r}") from e
    return {"coalesce": coalesce.value, "tools": sorted(set(tools_raw))}


class SchedulingService:
    """TaskStore 之上的业务门面：验证 → 授权 → 变更 → 审计。"""

    def __init__(self, store: TaskStore, *, limits: SchedulingLimits | None = None) -> None:
        self.store = store
        self.limits = limits or SchedulingLimits()

    # ── 授权 ─────────────────────────────────────────────
    def _is_admin(self, actor_id: int, *, is_group_admin: bool) -> bool:
        return is_group_admin or actor_id in self.limits.global_admin_ids

    def _load_task_in_group(self, task_id: str, group_id: int) -> Task:
        task = self.store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError("任务不存在（或已被删除）")
        if task.group_id != group_id:
            # 跨群访问：与「不存在」同一句话回应，避免向别的群泄露任务存在性
            logger.info(
                f"[Scheduling] 跨群操作被拒绝：群 {group_id} 用户试图访问群 "
                f"{task.group_id} 的任务 {task_id[:8]}"
            )
            raise PermissionDeniedError("任务不存在（或已被删除）")
        return task

    def _require_owner_or_admin(self, task: Task, actor_id: int, *, is_admin: bool) -> None:
        if actor_id != task.owner_id and not is_admin:
            raise PermissionDeniedError("只有任务创建者或管理员可以操作这个任务")

    def _require_not_cancelled(self, task: Task) -> None:
        if task.status is TaskStatus.CANCELLED:
            raise InvalidTaskError("任务已取消，无法再操作")

    def _resolve_task_id(self, task_id_prefix: str, group_id: int) -> str:
        """任务id 允许写前缀（群内唯一即可）；歧义/不存在在这里报错。"""
        prefix = (task_id_prefix or "").strip()
        if not prefix:
            raise InvalidTaskError("请提供任务id（可用「定时列表」查看）")
        candidates = [
            t for t in self.store.list_tasks(group_id, include_cancelled=True)
            if t.task_id.startswith(prefix)
        ]
        if len(candidates) == 1:
            return candidates[0].task_id
        if not candidates:
            raise TaskNotFoundError("找不到这个任务（可用「定时列表」查看）")
        raise InvalidTaskError(f"任务id 前缀 {prefix!r} 命中了 {len(candidates)} 个任务，请写得更长")

    # ── 创建 ─────────────────────────────────────────────
    def create_task(
        self,
        *,
        actor_id: int,
        group_id: int,
        bot_id: str,
        is_group_admin: bool = False,
        mode: TaskMode | str,
        objective: str,
        cron_expr: str,
        timezone: str,
        notification_mode: NotificationMode | str | None = None,
        policy: dict | None = None,
        now=None,
    ) -> Task:
        now = now or utc_now()
        mode = TaskMode(mode)
        is_admin = self._is_admin(actor_id, is_group_admin=is_group_admin)
        if mode is TaskMode.AGENT:
            if not self.limits.allow_agent_mode:
                raise PermissionDeniedError("Agent 任务在当前部署未启用")
            if not is_admin:
                raise PermissionDeniedError("只有群管理员可以创建 Agent 任务")
        objective = (objective or "").strip()
        if not objective:
            raise InvalidTaskError("任务内容不能为空")
        if len(objective) > self.limits.objective_max_chars:
            raise InvalidTaskError(
                f"任务内容过长（上限 {self.limits.objective_max_chars} 字符）"
            )
        if mode is TaskMode.REMINDER and policy and policy.get("tools"):
            raise InvalidTaskError("reminder 任务不能配置工具允许清单")
        policy = normalize_policy(policy, mode=mode)
        if notification_mode is None:
            notification_mode = (
                NotificationMode.ALWAYS if mode is TaskMode.REMINDER
                else NotificationMode.ON_CONTENT
            )
        else:
            notification_mode = NotificationMode(notification_mode)
        schedule = parse_cron(cron_expr, timezone)  # CronError 直接上抛（用户可读）

        user_tasks = self.store.list_tasks(group_id, owner_id=actor_id, include_cancelled=False)
        if not is_admin and len(user_tasks) >= self.limits.max_tasks_per_user:
            raise GroupTaskLimitError(
                f"你在这个群已有 {len(user_tasks)} 个任务（上限 {self.limits.max_tasks_per_user}）"
            )
        task = self.store.create_task(
            instance_id=_instance_id(),
            bot_id=str(bot_id),
            group_id=group_id,
            owner_id=actor_id,
            mode=mode,
            objective=objective,
            cron_expr=schedule.expr,
            timezone=schedule.tz_name,
            policy=policy,
            notification_mode=notification_mode,
            max_tasks_per_group=self.limits.max_tasks_per_group,
            now=now,
        )
        self._refresh_schedule_cache(task.task_id, now=now)
        self.store.record_audit(
            "create",
            actor_id=actor_id,
            group_id=group_id,
            task_id=task.task_id,
            detail=f"mode={mode.value} cron={schedule.expr} tz={schedule.tz_name}",
            now=now,
        )
        logger.info(
            f"[Scheduling] 群 {group_id} 用户 {actor_id} 创建{'' if mode is TaskMode.REMINDER else ' agent '}"
            f"任务 {task.task_id[:8]}（{schedule.expr} @ {schedule.tz_name}）"
        )
        return self.store.get_task(task.task_id)  # type: ignore[return-value]

    # ── 查询 ─────────────────────────────────────────────
    def list_tasks(self, *, group_id: int, include_cancelled: bool = False) -> list[Task]:
        """群内任务清单（清单本身群内可见；单任务的管理操作另有权限）。"""
        return self.store.list_tasks(group_id, include_cancelled=include_cancelled)

    def show_task(self, *, actor_id: int, group_id: int, task_id_prefix: str,
                  is_group_admin: bool = False) -> Task:
        task = self._load_task_in_group(
            self._resolve_task_id(task_id_prefix, group_id), group_id
        )
        _ = actor_id, is_group_admin  # 详情全员可看（内容不含凭据）
        return task

    def history(self, *, actor_id: int, group_id: int, task_id_prefix: str,
                is_group_admin: bool = False, limit: int = 10) -> list[Run]:
        task = self._load_task_in_group(
            self._resolve_task_id(task_id_prefix, group_id), group_id
        )
        self._require_owner_or_admin(task, actor_id, is_admin=self._is_admin(
            actor_id, is_group_admin=is_group_admin
        ))
        return self.store.list_runs(task.task_id, limit=limit)

    # ── 编辑 / 状态 ──────────────────────────────────────
    def edit_task(
        self,
        *,
        actor_id: int,
        group_id: int,
        task_id_prefix: str,
        expected_revision: int,
        is_group_admin: bool = False,
        cron_expr: str | None = None,
        timezone: str | None = None,
        objective: str | None = None,
        notification_mode: NotificationMode | str | None = None,
        policy: dict | None = None,
        now=None,
    ) -> Task:
        now = now or utc_now()
        is_admin = self._is_admin(actor_id, is_group_admin=is_group_admin)
        task_id = self._resolve_task_id(task_id_prefix, group_id)
        task = self._load_task_in_group(task_id, group_id)
        self._require_not_cancelled(task)
        self._require_owner_or_admin(task, actor_id, is_admin=is_admin)
        if policy is not None and not is_admin:
            raise PermissionDeniedError("只有群管理员可以修改任务策略（工具允许清单/补跑策略）")

        updates: dict = {}
        new_mode = task.mode
        if cron_expr is not None or timezone is not None:
            new_cron = cron_expr if cron_expr is not None else task.cron_expr
            new_tz = timezone if timezone is not None else task.timezone
            schedule = parse_cron(new_cron, new_tz)
            updates["cron_expr"] = schedule.expr
            updates["timezone"] = schedule.tz_name
        if objective is not None:
            objective = objective.strip()
            if not objective:
                raise InvalidTaskError("任务内容不能为空")
            if len(objective) > self.limits.objective_max_chars:
                raise InvalidTaskError(
                    f"任务内容过长（上限 {self.limits.objective_max_chars} 字符）"
                )
            updates["objective"] = objective
        if notification_mode is not None:
            updates["notification_mode"] = NotificationMode(notification_mode).value

        # 策略是「整体替换」语义：传入即覆盖，缺省键回落到该模式的默认值
        effective_policy = (
            normalize_policy(policy, mode=new_mode) if policy is not None else None
        )
        updated = self.store.edit_task(
            task_id,
            expected_revision,
            updates=updates,
            policy=effective_policy,
            now=now,
        )
        if "cron_expr" in updates:
            self._refresh_schedule_cache(task_id, now=now)
        self.store.record_audit(
            "edit",
            actor_id=actor_id,
            group_id=group_id,
            task_id=task_id,
            detail=f"fields={sorted(updates) or []} policy={'replaced' if effective_policy else 'unchanged'} "
                   f"revision={expected_revision}->{updated.revision}",
            now=now,
        )
        return updated

    def set_policy(
        self,
        *,
        actor_id: int,
        group_id: int,
        task_id_prefix: str,
        expected_revision: int,
        is_group_admin: bool,
        policy: dict,
        now=None,
    ) -> Task:
        """策略替换的显式入口（admin-only，commands 层的 定时允许/定时禁止 走这里）。"""
        return self.edit_task(
            actor_id=actor_id,
            group_id=group_id,
            task_id_prefix=task_id_prefix,
            expected_revision=expected_revision,
            is_group_admin=is_group_admin,
            policy=policy,
            now=now,
        )

    def _set_status(
        self,
        action: str,
        status: TaskStatus,
        *,
        actor_id: int,
        group_id: int,
        task_id_prefix: str,
        expected_revision: int,
        is_group_admin: bool = False,
        now=None,
    ) -> Task:
        now = now or utc_now()
        is_admin = self._is_admin(actor_id, is_group_admin=is_group_admin)
        task_id = self._resolve_task_id(task_id_prefix, group_id)
        task = self._load_task_in_group(task_id, group_id)
        self._require_owner_or_admin(task, actor_id, is_admin=is_admin)
        if action != "cancel":
            self._require_not_cancelled(task)
        updated = self.store.set_status(task_id, expected_revision, status, now=now)
        self.store.record_audit(
            action,
            actor_id=actor_id,
            group_id=group_id,
            task_id=task_id,
            detail=f"revision={expected_revision}->{updated.revision}",
            now=now,
        )
        if status is not TaskStatus.ACTIVE:
            self.store.record_task_fired(task_id, clear_next_run=True)
        else:
            self._refresh_schedule_cache(task_id, now=now)
        return updated

    def pause(self, **kwargs) -> Task:
        return self._set_status("pause", TaskStatus.PAUSED, **kwargs)

    def resume(self, **kwargs) -> Task:
        return self._set_status("resume", TaskStatus.ACTIVE, **kwargs)

    def cancel(self, **kwargs) -> Task:
        return self._set_status("cancel", TaskStatus.CANCELLED, **kwargs)

    # ── 立即运行 ─────────────────────────────────────────
    def run_now(
        self,
        *,
        actor_id: int,
        group_id: int,
        task_id_prefix: str,
        is_group_admin: bool = False,
        request_id: str | None = None,
        now=None,
    ) -> Run:
        now = now or utc_now()
        is_admin = self._is_admin(actor_id, is_group_admin=is_group_admin)
        task_id = self._resolve_task_id(task_id_prefix, group_id)
        task = self._load_task_in_group(task_id, group_id)
        self._require_not_cancelled(task)
        self._require_owner_or_admin(task, actor_id, is_admin=is_admin)
        request_id = request_id or uuid.uuid4().hex
        run_id = self.store.insert_run(task_id, request_id=request_id, now=now)
        if run_id is None:
            raise RunNotQueuedError(
                "这个任务已有运行在进行，或者这次请求已提交过；稍后再试"
            )
        run = self.store.get_run(run_id)
        assert run is not None
        self.store.record_audit(
            "run_now",
            actor_id=actor_id,
            group_id=group_id,
            task_id=task_id,
            detail=f"run_id={run_id} request_id={request_id}",
            now=now,
        )
        return run

    # ── 审计查询 ─────────────────────────────────────────
    def audit_log(self, *, group_id: int, limit: int = 20):
        return self.store.list_audit(group_id, limit=limit)

    # ── 内部 ─────────────────────────────────────────────
    def _refresh_schedule_cache(self, task_id: str, *, now) -> None:
        """把「下一次触发」的预览写进任务行（展示用；错误只告警不打断创建）。"""
        try:
            task = self.store.get_task(task_id)
            if task is None or task.status is not TaskStatus.ACTIVE:
                return
            schedule: CronSchedule = parse_cron(task.cron_expr, task.timezone)
            self.store.record_task_fired(
                task_id, next_run_utc=schedule.next_fire(now)
            )
        except CronError as e:
            logger.warning(f"⚠️ [Scheduling] 任务 {task_id[:8]} 触发预览失败: {e}")


def _instance_id() -> str:
    """当前进程的实例标识（informational；迟到导入避免测试环境强依赖）。"""
    try:
        from config import INSTANCE_ID

        return str(INSTANCE_ID)
    except Exception:
        return ""


__all__ = [
    "GroupTaskLimitError",
    "InvalidTaskError",
    "PermissionDeniedError",
    "RunNotQueuedError",
    "SchedulingLimits",
    "SchedulingService",
    "SchedulingServiceError",
    "normalize_policy",
]
