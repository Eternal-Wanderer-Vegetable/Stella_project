# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""会话浏览路由（M1 只读；内容仅返回给已登录管理员）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from webui.auth import require_auth
from webui.responses import ok
from webui.services import conversations as conv_service

router = APIRouter(
    tags=["conversations"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/conversations/groups")
async def conversation_groups() -> Any:
    return ok({"groups": conv_service.groups()})


@router.get("/api/v1/conversations")
async def list_messages(
    group_id: str,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    offset = (page - 1) * page_size
    return ok(conv_service.messages(group_id, limit=page_size, offset=offset))


@router.get("/api/v1/conversations/context")
async def conversation_context(group_id: str) -> Any:
    return ok(
        {
            "group_id": group_id,
            "consolidation": conv_service.consolidation_checkpoint(group_id),
        }
    )
