# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""决策轨迹路由（M1 硬性交付：轨迹流 + 单条消息回放）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from webui.auth import require_auth
from webui.responses import ApiError, ok
from webui.services import trace as trace_service

router = APIRouter(
    tags=["trace"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/trace/memory")
async def memory_traces(
    group_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    return ok(trace_service.memory_traces(group_id, limit=limit, offset=offset))


@router.get("/api/v1/trace/memory/{trace_id}")
async def memory_trace_detail(trace_id: int) -> Any:
    detail = trace_service.memory_trace_detail(trace_id)
    if detail is None:
        raise ApiError("轨迹不存在", status_code=404)
    return ok(detail)


@router.get("/api/v1/trace/participation")
async def participation_traces(
    group_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    return ok(trace_service.participation(group_id, limit=limit, offset=offset))
