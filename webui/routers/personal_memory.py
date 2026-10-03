# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""个人记忆管理路由（计划 §6.9）。

require_auth（单管理员）是前端门槛；服务端过滤（只认 PERSON 行）才是
授权边界——前端筛选永远不充当授权。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from webui.auth import require_auth
from webui.responses import ApiError, ok
from webui.services import personal_memory as service

router = APIRouter(
    tags=["personal-memory"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/personal-memory")
async def list_personal_memories(
    subject_key: str = "",
    audience: str = "",
    source_conversation_key: str = "",
    include_content: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    return ok(
        service.list_personal_memories(
            subject_key=subject_key,
            audience=audience,
            source_conversation_key=source_conversation_key,
            include_content=include_content,
            limit=limit,
            offset=offset,
        )
    )


@router.delete("/api/v1/personal-memory/{memory_id}")
async def delete_personal_memory(memory_id: str) -> Any:
    if not service.delete_personal_memory(memory_id):
        raise ApiError("记录不存在或不是个人记忆", status_code=404)
    return ok({"deleted": memory_id})


@router.get("/api/v1/personal-memory/export")
async def export_personal_memories(subject_key: str = "") -> Any:
    return ok(service.export_personal_memories(subject_key=subject_key))
