# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebUI 的 cometa 服务适配：获取服务、DTO、错误映射（方案 §6.14）。

- 服务来源是 :mod:`cometa.runtime` 的进程内登记（ai_gateway 装配）；
  未装配/未启用时统一译成「功能未启用」，前端据此隐藏入口；
- WebUI 管理员走现有 require_auth，actor 映射为 ``webchat_admin``——
  可管理实例内全部任务；task_id 本身**不是**凭据（§6.14）；
- WebChat 提交用固定会话身份构造 Origin（§6.11：沿用服务端单管理员），
  客户端请求 ID 参与幂等键。
"""

from __future__ import annotations

import dataclasses

from cometa import runtime as cometa_runtime
from cometa.models import Origin, TaskSpec, TaskState, parse_iso_utc
from cometa.service import (
    Actor,
    CometaService,
    InvalidRequestError,
    NotAuthorizedError,
    SubmissionPendingError,
)
from cometa.store import (
    CometaStoreError,
    TaskNotFoundError,
)
from webui.responses import ApiError


class CometaUnavailable(ApiError):  # noqa: N818 - 语义是「未启用」状态，不是错误对象
    def __init__(self):
        super().__init__("cometa 未启用（COMETA_ENABLED=false 或 runtime 未装配）",
                         status_code=503)


def get_service() -> CometaService:
    service = cometa_runtime.current_service()
    if service is None:
        raise CometaUnavailable
    return service


def actor_of(username: str) -> Actor:
    """WebUI 管理员 → actor。当前是单管理员模型（§2/§6.13）。"""
    return Actor(kind="webchat_admin", id=username)


def webchat_origin(service: CometaService, username: str, request_id: str) -> Origin:
    """WebChat 提交的 Origin。固定虚拟会话身份 + 客户端请求 ID（§6.11）。"""
    return Origin(
        instance_id=service.instance_id,
        platform="webchat",
        bot_id="webui",
        conversation_id="webchat",
        requester_id=username,
        source_request_id=request_id or f"webui-{username}",
        reply_to_message_id="",
        conversation_generation=1,
    )


def task_dto(snapshot) -> dict:
    """TaskSnapshot → 前端 DTO（时间全部 ISO 字符串）。"""
    return {
        "task_id": snapshot.task_id,
        "short_id": snapshot.task_id[:8],
        "state": snapshot.state.value if isinstance(snapshot.state, TaskState) else str(snapshot.state),
        "backend_id": snapshot.backend_id,
        "attempt_no": snapshot.attempt_no,
        "phase": snapshot.phase,
        "last_activity_at": _iso(snapshot.last_activity_at),
        "heartbeat_at": _iso(snapshot.heartbeat_at),
        "deadline_at": _iso(snapshot.deadline_at),
        "waiting_request_id": snapshot.waiting_request_id,
        "delivery_state": snapshot.delivery_state,
        "created_at": _iso(snapshot.created_at),
        "updated_at": _iso(snapshot.updated_at),
    }


def result_dto(result) -> dict:
    return {
        "schema_version": result.to_dict().get("schema_version", 1),
        "outcome": result.outcome.value,
        "summary": result.summary,
        "final_text_ref": result.final_text_ref,
        "verification_status": result.verification_status.value,
        "artifacts": [dataclasses.asdict(a) if dataclasses.is_dataclass(a) else dict(a) for a in result.artifacts],
        "evidence": result.evidence,
        "limitations": result.limitations,
        "error": result.error,
        "usage": result.usage,
    }


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def map_error(e: Exception) -> ApiError:
    """服务层异常 → WebUI error envelope（不泄内部细节）。"""
    if isinstance(e, ApiError):
        return e  # 端点里主动构造的语义错误（4xx）原样透传
    if isinstance(e, TaskNotFoundError):
        return ApiError(str(e), status_code=404)
    if isinstance(e, NotAuthorizedError):
        return ApiError(str(e), status_code=403)
    if isinstance(e, (InvalidRequestError, SubmissionPendingError)):
        return ApiError(str(e), status_code=409 if isinstance(e, SubmissionPendingError) else 400)
    if isinstance(e, CometaStoreError):
        return ApiError(f"任务库错误: {e}", status_code=503)
    return ApiError("cometa 内部错误", status_code=500)


def spec_from_payload(payload: dict) -> TaskSpec:
    if not isinstance(payload, dict):
        raise ApiError("请求体必须是 JSON 对象", status_code=422)
    objective = str(payload.get("objective") or "").strip()
    if not objective:
        raise ApiError("objective 不能为空", status_code=422)
    return TaskSpec(
        objective=objective,
        context_excerpt=str(payload.get("context_excerpt") or ""),
        required_capabilities=[str(c) for c in (payload.get("required_capabilities") or [])],
        backend_preference=str(payload.get("backend_preference") or ""),
        workspace_id=str(payload.get("workspace_id") or ""),
        permission_profile=str(payload.get("permission_profile") or ""),
        acceptance_criteria=[str(c) for c in (payload.get("acceptance_criteria") or [])],
        limits=dict(payload.get("limits") or {}),
    )


__all__ = [
    "CometaUnavailable",
    "actor_of",
    "get_service",
    "map_error",
    "parse_iso_utc",
    "result_dto",
    "spec_from_payload",
    "task_dto",
    "webchat_origin",
]
