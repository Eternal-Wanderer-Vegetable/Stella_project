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


# ---- 轮次追踪（计划 §6.8）：全部沿用 require_auth + 分页/大小限制 ----


@router.get("/api/v1/trace/turns")
async def turn_traces(
    scope: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    return ok(trace_service.turns(scope=scope, limit=limit, offset=offset))


@router.get("/api/v1/trace/turns/{turn_id}")
async def turn_detail(turn_id: str) -> Any:
    detail = trace_service.turn_timeline(turn_id)
    if detail is None:
        raise ApiError("轮次追踪不存在", status_code=404)
    return ok(detail)


@router.get("/api/v1/trace/turns/{turn_id}/payloads")
async def turn_detail_payloads(turn_id: str) -> Any:
    """detailed 快照正文：含用户消息等敏感正文，仅鉴权管理员可读。"""
    payloads = trace_service.turn_payloads(turn_id)
    if payloads is None:
        raise ApiError("该轮次没有 detailed 快照", status_code=404)
    return ok(payloads)


@router.post("/api/v1/trace/turns/{turn_id}/replay")
async def replay_turn(turn_id: str) -> Any:
    """离线决策回放（默认零副作用：provider/工具/发送器/学习全为只读桩）。"""
    try:
        return ok(trace_service.replay_turn(turn_id))
    except ValueError:
        raise ApiError("轮次追踪不存在", status_code=404) from None
