# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""cometa 管理 API（方案 §6.14）。

全部端点 require_auth（WebUI 管理员）；写操作记 audit；受理/取消带客户端
幂等键；答复带 expected_revision；事件用**游标分页**（SSE 断线补读同参数）；
产物下载只按 manifest 存储键取，不接受任意 path 参数（§6.12）。

受理成功返回 **202**：accepted ≠ running，前端据此渲染「排队中」。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from cometa.models import ArtifactAvailability
from webui.audit import record as audit_record
from webui.auth import AuthContext, require_auth
from webui.responses import ApiError, ok
from webui.services import cometa as cometa_service

router = APIRouter(tags=["cometa"], dependencies=[Depends(require_auth)])


@router.get("/api/v1/cometa/health")
async def cometa_health() -> Any:
    try:
        service = cometa_service.get_service()
    except cometa_service.CometaUnavailable as e:
        return ok({"state": "disabled", "message": e.message})
    return ok(service.health())


@router.get("/api/v1/cometa/backends")
async def cometa_backends() -> Any:
    try:
        service = cometa_service.get_service()
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    backends = []
    for backend in service.config.enabled_backends():
        backends.append(
            {
                "backend_id": backend.backend_id,
                "type": backend.type,
                "capabilities": backend.capabilities,
            }
        )
    return ok({"backends": backends})


@router.get("/api/v1/cometa/tasks")
async def cometa_list_tasks(
    cursor: int = 0, limit: int = 50, auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        page = service.list_tasks(
            actor=cometa_service.actor_of(auth.username), cursor=cursor, limit=limit
        )
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    return ok(
        {
            "tasks": [cometa_service.task_dto(t) for t in page.tasks],
            "next_cursor": page.next_cursor,
        }
    )


@router.post("/api/v1/cometa/tasks", status_code=202)
async def cometa_submit_task(
    request: Request, auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        payload = await request.json()
        spec = cometa_service.spec_from_payload(payload)
        request_id = str(payload.get("request_id") or "")
        receipt = service.submit(
            spec,
            actor=cometa_service.actor_of(auth.username),
            origin=cometa_service.webchat_origin(service, auth.username, request_id),
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    audit_record(
        request=request,
        username=auth.username,
        via=auth.via,
        action="cometa.submit",
        detail={"task_id": receipt.task_id},
    )
    return ok(
        {
            "task_id": receipt.task_id,
            "accepted_at": receipt.accepted_at.isoformat(),
            "state": "queued",
        }
    )


@router.get("/api/v1/cometa/tasks/{task_id}")
async def cometa_get_task(
    task_id: str, auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        snapshot = service.get(task_id, actor=cometa_service.actor_of(auth.username))
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    dto = cometa_service.task_dto(snapshot)
    # 等待输入/审批的问题文本（§6.14：展示等待问题）
    if snapshot.waiting_request_id:
        record = service.store.get_input_request(snapshot.waiting_request_id)
        if record is not None:
            dto["waiting_question"] = record.question
            dto["waiting_kind"] = record.kind
            dto["waiting_revision"] = record.revision
    return ok(dto)


@router.get("/api/v1/cometa/tasks/{task_id}/events")
async def cometa_task_events(
    task_id: str,
    after_sequence: int = 0,
    limit: int = 200,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        page = service.events(
            task_id,
            actor=cometa_service.actor_of(auth.username),
            after_sequence=after_sequence,
            limit=limit,
        )
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    return ok(
        {
            "task_id": page.task_id,
            "events": page.events,
            "next_sequence": page.next_sequence,
        }
    )


@router.post("/api/v1/cometa/tasks/{task_id}/cancel")
async def cometa_cancel_task(
    request: Request,
    task_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        payload: dict = {}
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        status, state = service.cancel(
            task_id,
            actor=cometa_service.actor_of(auth.username),
            idempotency_key=str(payload.get("idempotency_key") or ""),
        )
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    audit_record(
        request=request,
        username=auth.username,
        via=auth.via,
        action="cometa.cancel",
        detail={"task_id": task_id, "status": status},
    )
    return ok({"task_id": task_id, "status": status, "state": state.value})


@router.post("/api/v1/cometa/tasks/{task_id}/inputs/{request_id}")
async def cometa_respond_input(
    request: Request,
    task_id: str,
    request_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        payload = await request.json()
        answer = str(payload.get("answer") or "")
        expected_revision = int(payload.get("expected_revision") or 0)
        status = service.respond(
            task_id,
            request_id,
            answer,
            actor=cometa_service.actor_of(auth.username),
            expected_revision=expected_revision,
        )
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    audit_record(
        request=request,
        username=auth.username,
        via=auth.via,
        action="cometa.respond",
        detail={"task_id": task_id, "request_id": request_id},
    )
    return ok({"task_id": task_id, "request_id": request_id, "status": status})


@router.get("/api/v1/cometa/tasks/{task_id}/result")
async def cometa_task_result(
    task_id: str, auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        result = service.result(task_id, actor=cometa_service.actor_of(auth.username))
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except Exception as e:
        raise cometa_service.map_error(e) from e
    return ok(cometa_service.result_dto(result))


@router.get("/api/v1/cometa/tasks/{task_id}/artifacts/{artifact_id}")
async def cometa_artifact_download(
    task_id: str,
    artifact_id: str,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    try:
        service = cometa_service.get_service()
        cometa_service.actor_of(auth.username)  # 认证已由 router 依赖保证
        # 服务端解析 manifest/DB 记录，不接受任意 path 参数（§6.12）
        artifact = service.store.get_artifact(artifact_id)
        if artifact is None or artifact.task_id != task_id:
            raise ApiError("产物不存在", status_code=404)
        if artifact.availability is ArtifactAvailability.UNAVAILABLE:
            raise ApiError("产物文件已缺失", status_code=410)
        from cometa.artifacts import ArtifactCollector, ArtifactError

        collector = ArtifactCollector(service.config.artifacts_dir)
        try:
            path = collector.artifact_path(task_id, artifact.relative_storage_key)
        except ArtifactError as e:
            raise ApiError(str(e), status_code=404) from e
        if not path.is_file():
            raise ApiError("产物文件已缺失", status_code=410)
    except cometa_service.CometaUnavailable as e:
        raise ApiError(e.message, status_code=503) from None
    except ApiError:
        raise
    except Exception as e:
        raise cometa_service.map_error(e) from e
    return FileResponse(
        path,
        media_type=artifact.mime or "application/octet-stream",
        filename=artifact.display_name,
    )


__all__ = ["router"]
