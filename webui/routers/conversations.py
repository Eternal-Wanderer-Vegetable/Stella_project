# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""会话浏览路由（M1 只读；内容仅返回给已登录管理员）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from webui.auth import require_auth
from webui.responses import ApiError, ok
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


@router.get("/api/v1/conversations/scenes")
async def transport_conversation_scenes(
    adapter: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    connection_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    kind: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
) -> Any:
    return ok(
        {
            "scenes": conv_service.transport_scenes(
                adapter=adapter, connection_id=connection_id, kind=kind
            )
        }
    )


@router.get("/api/v1/conversations/messages")
async def list_transport_messages(
    conversation_key: Annotated[str, Query(min_length=4, max_length=8192)],
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[int | None, Query(gt=0)] = None,
    snapshot_id: Annotated[int | None, Query(ge=0)] = None,
) -> Any:
    try:
        data = conv_service.transport_messages(
            conversation_key,
            limit=page_size,
            cursor=cursor,
            snapshot_id=snapshot_id,
        )
    except ValueError as exc:
        code = (
            "conversation_key_invalid"
            if str(exc) == "conversation_key_invalid"
            else "history_cursor_invalid"
        )
        raise ApiError(
            code, data={"code": code}
        ) from exc
    except LookupError as exc:
        raise ApiError(
            "conversation_not_registered",
            status_code=404,
            data={"code": "conversation_not_registered"},
        ) from exc
    return ok(data)
