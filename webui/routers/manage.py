# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""MCP / Skills / 知识库 / 定时任务 路由（M3）。写入全部过审计。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from webui import audit
from webui.auth import AuthContext, require_auth
from webui.responses import ApiError, ok
from webui.services import kb as kb_service
from webui.services import mcpmanage as mcp_service
from webui.services import sched as sched_service
from webui.services import skillsmanage as skills_service

mcp_router = APIRouter(tags=["mcp"], dependencies=[Depends(require_auth)])
skills_router = APIRouter(tags=["skills"], dependencies=[Depends(require_auth)])
kb_router = APIRouter(tags=["knowledge"], dependencies=[Depends(require_auth)])
sched_router = APIRouter(tags=["scheduling"], dependencies=[Depends(require_auth)])


# ---------- MCP ----------

@mcp_router.get("/api/v1/mcp/servers")
async def mcp_servers() -> Any:
    return ok(mcp_service.list_servers())


@mcp_router.post("/api/v1/mcp/servers")
async def mcp_create(payload: dict) -> Any:
    server_id = payload.get("server_id", "")
    result = mcp_service.save_server(server_id, payload)
    return ok(result)


@mcp_router.put("/api/v1/mcp/servers/{server_id}")
async def mcp_update(server_id: str, payload: dict) -> Any:
    return ok(mcp_service.save_server(server_id, payload))


@mcp_router.delete("/api/v1/mcp/servers/{server_id}")
async def mcp_delete(server_id: str) -> Any:
    return ok(mcp_service.delete_server(server_id))


@mcp_router.post("/api/v1/mcp/servers/{server_id}/test")
async def mcp_test(server_id: str) -> Any:
    return ok(await mcp_service.test_server(server_id))


@mcp_router.get("/api/v1/mcp/servers/{server_id}/tools")
async def mcp_tools(server_id: str) -> Any:
    return ok(mcp_service.server_tools(server_id))


@mcp_router.post("/api/v1/mcp/apply")
async def mcp_apply() -> Any:
    """保存后热生效（MCP_ENABLED=false 时返回提示而非报错）。"""
    result = await mcp_service.apply_runtime()
    return ok(result)


# ---------- Skills ----------

@skills_router.get("/api/v1/skills")
async def skills_list() -> Any:
    return ok(skills_service.list_skills())


@skills_router.get("/api/v1/skills/{name}")
async def skill_detail(name: str) -> Any:
    return ok(skills_service.get_skill(name))


@skills_router.put("/api/v1/skills/{name}")
async def skill_save(name: str, payload: dict) -> Any:
    return ok(skills_service.save_skill_body(name, payload.get("body", "")))


@skills_router.post("/api/v1/skills/upload")
async def skills_upload(
    request: Request,
    file: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    result = skills_service.upload_zip(await file.read())
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="skills.upload", detail={"name": result.get("name")})
    return ok(result)


@skills_router.delete("/api/v1/skills/{name}")
async def skill_delete(name: str) -> Any:
    return ok(skills_service.delete_skill(name))


# ---------- 知识库 ----------

@kb_router.get("/api/v1/knowledge-bases")
async def kb_list() -> Any:
    return ok({"knowledge_bases": kb_service.list_kbs()})


@kb_router.post("/api/v1/knowledge-bases")
async def kb_create(payload: dict) -> Any:
    return ok(kb_service.create_kb(payload.get("name", ""), description=payload.get("description", "")))


@kb_router.get("/api/v1/knowledge-bases/{kb_id}")
async def kb_detail(kb_id: str) -> Any:
    return ok(kb_service.kb_detail(kb_id))


@kb_router.delete("/api/v1/knowledge-bases/{kb_id}")
async def kb_archive(kb_id: str) -> Any:
    return ok(await kb_service.archive(kb_id))


@kb_router.post("/api/v1/knowledge-bases/{kb_id}/documents")
async def kb_add_document(
    request: Request,
    kb_id: str,
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    if payload.get("url"):
        result = await kb_service.submit_document(
            kb_id, source_type="url", data=payload["url"], title=payload.get("title", ""),
            uri=payload["url"],
        )
    elif payload.get("file_base64"):
        # 前端 JSON 通道：base64 文件内容（md/txt/pdf/docx 均按字节交给解析器）
        import base64

        data = base64.b64decode(payload["file_base64"])
        result = await kb_service.submit_document(
            kb_id, source_type="file", data=data, title=payload.get("title", "")
        )
    else:
        raise ApiError("需要 url 或 file_base64")
    audit.record(request=request, username=auth.username, via=auth.via,
                 action="knowledge.import", detail={"kb_id": kb_id, "state": result.get("state")})
    return ok(result)


@kb_router.post("/api/v1/knowledge-bases/{kb_id}/retrieve")
async def kb_retrieve(kb_id: str, payload: dict) -> Any:
    return ok(await kb_service.retrieve(kb_id, payload.get("query", "")))


@kb_router.post("/api/v1/knowledge-bases/{kb_id}/acl")
async def kb_grant(kb_id: str, payload: dict) -> Any:
    return ok(
        await kb_service.set_grant(
            kb_id,
            principal_kind=payload.get("principal_kind", "user"),
            principal_id=payload.get("principal_id", ""),
            role=payload.get("role", "viewer"),
        )
    )


@kb_router.delete("/api/v1/knowledge-bases/{kb_id}/acl")
async def kb_revoke(kb_id: str, payload: dict) -> Any:
    return ok(
        await kb_service.set_revoke(
            kb_id,
            principal_kind=payload.get("principal_kind", "user"),
            principal_id=payload.get("principal_id", ""),
        )
    )


# ---------- 定时任务 ----------

@sched_router.get("/api/v1/scheduling/tasks")
async def sched_list(
    group_id: str | None = None,
    include_cancelled: bool = False,
) -> Any:
    return ok(sched_service.list_tasks(group_id, include_cancelled=include_cancelled))


@sched_router.post("/api/v1/scheduling/tasks")
async def sched_create(payload: dict) -> Any:
    return ok(sched_service.create_task(payload))


@sched_router.get("/api/v1/scheduling/tasks/{task_id}")
async def sched_detail(task_id: str, group_id: str) -> Any:
    return ok(sched_service.get_task(group_id, task_id))


@sched_router.patch("/api/v1/scheduling/tasks/{task_id}")
async def sched_edit(task_id: str, payload: dict) -> Any:
    return ok(sched_service.edit_task(payload["group_id"], task_id, payload))


def _sched_action(action: str, payload: dict) -> Any:
    return ok(getattr(sched_service, action)(payload["group_id"], payload["task_id"]))


@sched_router.post("/api/v1/scheduling/tasks/{task_id}/pause")
async def sched_pause(task_id: str, payload: dict) -> Any:
    return ok(sched_service._status_action("pause", payload["group_id"], task_id, payload["expected_revision"]))


@sched_router.post("/api/v1/scheduling/tasks/{task_id}/resume")
async def sched_resume(task_id: str, payload: dict) -> Any:
    return ok(sched_service._status_action("resume", payload["group_id"], task_id, payload["expected_revision"]))


@sched_router.post("/api/v1/scheduling/tasks/{task_id}/cancel")
async def sched_cancel(task_id: str, payload: dict) -> Any:
    return ok(sched_service._status_action("cancel", payload["group_id"], task_id, payload["expected_revision"]))


@sched_router.post("/api/v1/scheduling/tasks/{task_id}/run-now")
async def sched_run_now(task_id: str, payload: dict) -> Any:
    return ok(sched_service.run_now(payload["group_id"], task_id))


@sched_router.get("/api/v1/scheduling/tasks/{task_id}/history")
async def sched_history(
    task_id: str,
    group_id: str,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Any:
    return ok(sched_service.history(group_id, task_id, limit=limit))


@sched_router.get("/api/v1/scheduling/audit")
async def sched_audit(group_id: str | None = None) -> Any:
    return ok(sched_service.audit(group_id))
