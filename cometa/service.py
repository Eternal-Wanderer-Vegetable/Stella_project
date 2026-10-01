# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""CometaService：入口（QQ/WebUI/能力钩子）使用的有界服务接口（方案 §6.1）。

职责与边界：

- 鉴权（actor 与任务的绑定）、提交幂等、查询、输入答复、取消——全部是
  **短事务**，绝不等待 Agent 执行（§1.3 不变量 3：受理回执 ≠ 最终结果）；
- Origin 只来自可信入口；服务层核验 instance 归属与 profile 绑定；
- cancel 返回「已请求取消」，不提前声称已取消（§6.1）；
- 数据库繁忙译成 :class:`SubmissionPendingError`——客户端沿用原幂等键查询，
  **禁止换 key 重提**（§6.3）。

actor 约定：``kind`` ∈ qq_user / webchat_admin / operator / system；
operator 与 webchat_admin 可管理实例内全部任务，qq_user 只能读写自己的任务
（§8.1 test_authorization：A 不能查询/取消/批准 B 的任务）。
"""

from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass
from datetime import timedelta

from .config import CometaConfig
from .models import (
    SCHEMA_VERSION,
    AgentResult,
    ArtifactRef,
    Origin,
    SubmissionReceipt,
    TaskSnapshot,
    TaskSpec,
    TaskState,
    utc_now,
)
from .policy import SubmissionPolicy
from .store import (
    CometaStore,
    CometaStoreError,
    IdempotencyConflictError,
    InputRequestStateError,
    QuotaExceededError,
    StoreBusyError,
    TaskNotFoundError,
)

SUBMIT_TIMEOUT_DEFAULT = 2.0


class CometaServiceError(RuntimeError):
    """服务层错误基类。"""


class NotAuthorizedError(CometaServiceError):
    """actor 无权访问该任务（§8.1：拒绝且无后端调用）。"""


class InvalidRequestError(CometaServiceError):
    """请求不合法（缺字段/请求不属于任务/revision 不匹配）。"""


class SubmissionPendingError(CometaServiceError):
    """提交结果待确认：事务结果不明。客户端必须沿用原幂等键查询/重试。"""


@dataclass(slots=True)
class Actor:
    """入口确定的主体（不从模型输出推断）。"""

    kind: str  # qq_user | webchat_admin | operator | system
    id: str = ""

    @property
    def is_operator(self) -> bool:
        return self.kind in ("operator", "webchat_admin", "system")


@dataclass(slots=True)
class TaskPage:
    tasks: list[TaskSnapshot]
    next_cursor: int = 0


@dataclass(slots=True)
class EventPage:
    task_id: str
    events: list[dict]
    next_sequence: int = 0
    reset_required: bool = False


def _snapshot_of(task) -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task.task_id,
        state=task.state,
        created_at=task.created_at,
        updated_at=task.updated_at,
        backend_id=task.backend_id,
        attempt_id=task.current_attempt,
        attempt_no=task.attempt_no,
        phase=task.phase,
        last_activity_at=task.last_activity_at,
        heartbeat_at=task.heartbeat_at,
        deadline_at=task.deadline_at,
        waiting_request_id=task.waiting_request_id,
        result_id=task.result_id,
        delivery_state=task.delivery_state,
        retry_of=task.retry_of,
    )


class CometaService:
    """受理/查询/控制的有界门面。一个 Bot 进程一个实例（runtime 装配）。"""

    def __init__(self, store: CometaStore, config: CometaConfig, *, instance_id: str = ""):
        self.store = store
        self.config = config
        self.instance_id = instance_id
        self.policy = SubmissionPolicy(config)

    # ============================================================
    # 提交（§6.3 事务边界 1）
    # ============================================================

    def submit(
        self,
        spec: TaskSpec,
        *,
        actor: Actor,
        origin: Origin,
        idempotency_key: str,
        deadline_seconds: float | None = None,
    ) -> SubmissionReceipt:
        """受理一个委派任务。落库成功才返回 receipt（accepted ≠ running）。"""
        if origin.instance_id and self.instance_id and origin.instance_id != self.instance_id:
            raise NotAuthorizedError("origin.instance_id 与本实例不一致，拒绝跨实例提交")
        origin = self._bind_instance(origin)
        decision = self.policy.check(origin=origin, spec=spec)
        if not decision.ok:
            raise InvalidRequestError(f"{decision.reason_code}: {decision.message}")
        if actor.kind == "qq_user" and str(actor.id) != str(origin.requester_id):
            raise NotAuthorizedError("actor 与 origin 请求者不一致")
        if not idempotency_key:
            idempotency_key = f"auto:{origin.source_request_id}:{spec.content_fingerprint()[:16]}"
        now = utc_now()
        deadline = now + timedelta(
            seconds=deadline_seconds or self.config.task_timeout_seconds
        )
        config_snapshot = {
            "schema_version": SCHEMA_VERSION,
            "config_hash": self.config.config_hash,
            "limits": {
                "per_user_active": self.config.limits.per_user_active,
                "per_group_active": self.config.limits.per_group_active,
            },
            "policy": dataclasses.asdict(decision),
        }
        try:
            task_id, created = self.store.submit_task(
                origin=origin,
                spec=spec,
                idempotency_key=idempotency_key,
                requester_id=origin.requester_id,
                group_id=origin.conversation_id if origin.platform == "qq" else "",
                backend_id=decision.backend_id,
                profile=decision.profile,
                workspace_id=decision.workspace_id,
                workspace_key=decision.workspace_key,
                deadline_at=deadline,
                config_snapshot=config_snapshot,
                now=now,
            )
        except (IdempotencyConflictError, QuotaExceededError) as e:
            raise InvalidRequestError(str(e)) from e
        except StoreBusyError as e:
            raise SubmissionPendingError(
                "提交状态待确认：请沿用原幂等键查询，不要换 key 重提（方案 §6.3）"
            ) from e
        except CometaStoreError as e:
            raise CometaServiceError(f"受理失败: {e}") from e
        receipt = SubmissionReceipt(task_id=task_id, accepted_at=now)
        if not created:
            return receipt  # 幂等重放：同一 key 返回原任务
        ack = self.store.notification_of_dedupe(task_id, f"ack:{task_id}")
        if ack is not None:
            receipt.ack_notification_id = ack.notification_id
        with contextlib.suppress(CometaStoreError):
            self.store.audit(
                actor=f"{actor.kind}:{actor.id}",
                action="submit",
                task_id=task_id,
                detail=f"backend={decision.backend_id} profile={decision.profile}",
            )
        return receipt

    def _bind_instance(self, origin: Origin) -> Origin:
        if not origin.instance_id:
            origin.instance_id = self.instance_id
        return origin

    # ============================================================
    # 查询
    # ============================================================

    def _authorize_task(self, task, actor: Actor) -> None:
        if actor.is_operator:
            return
        if actor.kind == "qq_user" and str(actor.id) == str(task.requester_id):
            return
        raise NotAuthorizedError("无权访问该任务")

    def get(self, task_id: str, *, actor: Actor) -> TaskSnapshot:
        task = self.store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务 {task_id} 不存在")
        self._authorize_task(task, actor)
        return _snapshot_of(task)

    def list_tasks(self, *, actor: Actor, cursor: int = 0, limit: int = 50) -> TaskPage:
        """列表：operator 看全实例，普通用户只看自己的。"""
        if actor.is_operator:
            records = self.store.list_tasks(
                self.instance_id, limit=limit, offset=cursor
            )
        elif actor.kind == "qq_user":
            records = self.store.list_tasks(
                self.instance_id, requester_id=str(actor.id), limit=limit, offset=cursor
            )
        else:
            raise NotAuthorizedError("无权列出任务")
        snapshots = [_snapshot_of(t) for t in records]
        next_cursor = cursor + len(snapshots) if len(snapshots) == limit else 0
        return TaskPage(tasks=snapshots, next_cursor=next_cursor)

    def events(self, task_id: str, *, actor: Actor, after_sequence: int = 0, limit: int = 200) -> EventPage:
        task = self.store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务 {task_id} 不存在")
        self._authorize_task(task, actor)
        records = self.store.events_page(task_id, after_sequence=after_sequence, limit=limit)
        events = [
            {
                "schema_version": SCHEMA_VERSION,
                "task_id": r.task_id,
                "attempt_id": r.attempt_id,
                "sequence": r.sequence,
                "kind": r.kind.value,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "payload": r.payload,
            }
            for r in records
        ]
        next_sequence = records[-1].sequence if records else after_sequence
        return EventPage(task_id=task_id, events=events, next_sequence=next_sequence)

    def result(self, task_id: str, *, actor: Actor) -> AgentResult:
        task = self.store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务 {task_id} 不存在")
        self._authorize_task(task, actor)
        record = self.store.get_result(task_id)
        if record is None:
            raise InvalidRequestError("任务还没有最终结果")
        # 已发布但文件缺失必须显示 unavailable（§6.12 第 5 步）
        artifacts: list[ArtifactRef] = []
        if self.store.list_artifacts(task_id):
            from .artifacts import ArtifactCollector

            collector = ArtifactCollector(self.config.artifacts_dir)
            for a in self.store.list_artifacts(task_id):
                artifacts.append(
                    ArtifactRef(
                        artifact_id=a.artifact_id,
                        display_name=a.display_name,
                        relative_storage_key=a.relative_storage_key,
                        sha256=a.sha256,
                        size=a.size,
                        mime=a.mime,
                        availability=collector.verify_availability(
                            task_id, a.relative_storage_key
                        ),
                    )
                )
        return AgentResult(
            outcome=record.outcome,
            summary=record.summary,
            final_text_ref=record.final_text_ref,
            artifacts=artifacts,
            evidence=record.evidence,
            verification_status=record.verification_status,
            limitations=record.limitations,
            error=record.error,
            usage=record.usage,
        )

    @staticmethod
    def _artifact_file_ok(task_id: str, storage_key: str) -> bool:
        from .artifacts import ArtifactError

        try:

            return True
        except ArtifactError:
            return False

    # ============================================================
    # 控制：取消 / 答复（§6.8/§6.10）
    # ============================================================
    def cancel(
        self, task_id: str, *, actor: Actor, idempotency_key: str = ""
    ) -> tuple[str, TaskState]:
        """请求取消。返回 (status, task_state)；status 是「已请求」类事实。"""
        task = self.store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务 {task_id} 不存在")
        self._authorize_task(task, actor)
        if task.state is TaskState.RECOVERY_REQUIRED and not actor.is_operator:
            raise NotAuthorizedError("恢复待处理的任务只有管理员能操作")
        try:
            status, _tid, _extra = self.store.request_cancel(
                task_id,
                actor=f"{actor.kind}:{actor.id}",
                idempotency_key=idempotency_key,
            )
        except StoreBusyError as e:
            raise SubmissionPendingError("取消请求状态待确认，请稍后查询") from e
        with contextlib.suppress(CometaStoreError):
            self.store.audit(
                actor=f"{actor.kind}:{actor.id}", action="cancel", task_id=task_id
            )
        refreshed = self.store.get_task(task_id)
        return status, refreshed.state if refreshed else TaskState.CANCELLING

    def respond(
        self,
        task_id: str,
        request_id: str,
        answer: str,
        *,
        actor: Actor,
        expected_revision: int,
    ) -> str:
        """答复输入/审批请求（§6.10）：普通补充由原请求者回答；权限提升类
        （approval）按管理员规则——首版仅 operator 可答审批。"""
        request = self.store.get_input_request(request_id)
        if request is None or request.task_id != task_id:
            raise InvalidRequestError("request_id 与任务不匹配")
        task = self.store.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务 {task_id} 不存在")
        if request.kind == "approval" and not actor.is_operator:
            raise NotAuthorizedError("审批只能由管理员答复")
        if not actor.is_operator and str(actor.id) != str(task.requester_id):
            raise NotAuthorizedError("无权答复该任务的请求")
        if not str(answer).strip():
            raise InvalidRequestError("答复内容不能为空")
        try:
            status, _tid, _answer = self.store.respond_input(
                request_id,
                str(answer),
                actor=f"{actor.kind}:{actor.id}",
                expected_revision=expected_revision,
            )
        except InputRequestStateError as e:
            raise InvalidRequestError(str(e)) from e
        except StoreBusyError as e:
            raise SubmissionPendingError("答复状态待确认，请稍后查询") from e
        with contextlib.suppress(CometaStoreError):
            self.store.audit(
                actor=f"{actor.kind}:{actor.id}",
                action="respond",
                task_id=task_id,
                request_id=request_id,
            )
        return status

    # ============================================================
    # 观测
    # ============================================================

    def health(self) -> dict:
        """健康状态（§6.13）：disabled/ready/degraded。"""
        if not self.config.enabled:
            return {"state": "disabled"}
        try:
            self.store.get_task("health-probe-nonexistent")
        except StoreBusyError:
            return {"state": "degraded", "reason": "database_busy"}
        except CometaStoreError as e:
            return {"state": "degraded", "reason": str(e)[:120]}
        return {
            "state": "ready",
            "config_hash": self.config.config_hash,
            "backends": sorted(b.backend_id for b in self.config.enabled_backends()),
        }


__all__ = [
    "Actor",
    "CometaService",
    "CometaServiceError",
    "EventPage",
    "InvalidRequestError",
    "NotAuthorizedError",
    "SubmissionPendingError",
    "TaskPage",
]
