# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""决策轨迹路由（M1 硬性交付：轨迹流 + 单条消息回放）。"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

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


# ---- 消息流程（计划 §6.6）：message_traces/flow_events 只读 + SSE ----


@router.get("/api/v1/trace/messages")
async def flow_messages(
    platform: str | None = None,
    root_kind: str | None = None,
    outcome: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Any:
    from webui.services import flow as flow_service

    return ok(
        flow_service.messages(
            platform=platform, root_kind=root_kind, outcome=outcome,
            limit=limit, offset=offset,
        )
    )


@router.get("/api/v1/trace/messages/{trace_id}")
async def flow_message_detail(trace_id: str) -> Any:
    from webui.services import flow as flow_service

    detail = flow_service.message_detail(trace_id)
    if detail is None:
        raise ApiError("消息轨迹不存在", status_code=404)
    return ok(detail)


@router.get("/api/v1/trace/messages/{trace_id}/events")
async def flow_message_events(
    trace_id: str,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> Any:
    """持久事件增量分页（断线补漏/轮询兜底共用；升序，按 row_id 去重）。"""
    from webui.services import flow as flow_service

    return ok({"items": flow_service.events_after(trace_id, after_id=after, limit=limit)})


@router.get("/api/v1/trace/flow/specs/{version}")
async def flow_spec(version: str) -> Any:
    """不可变拓扑 manifest（计划 §6.6）；缺版本显式 404，前端标 unmapped。"""
    from webui.services import flow as flow_service

    data = flow_service.spec(version)
    if data is None:
        raise ApiError("该版本的拓扑清单不存在", status_code=404)
    return ok(data)


@router.get("/api/v1/trace/flow/spec-version")
async def flow_spec_version() -> Any:
    from webui.services import flow as flow_service

    return ok({"topology_version": flow_service.latest_spec_version()})


@router.get("/api/v1/trace/messages/{trace_id}/stream")
async def flow_message_stream(
    trace_id: str,
    request: Request,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """SSE 事件流：持久读兜底（广播只作唤醒，这里直接轮询增量，计划 §6.6）。

    帧：``id: <row_id>`` + ``data: <event json>``；trace 关闭且增量排空后发
    ``{"type": "trace_end"}`` 并断开；客户端用 Last-Event-ID + /events 补漏。
    """
    from webui.services import flow as flow_service

    async def gen():
        cursor = int(after)
        import asyncio
        import json as _json

        while True:
            if await request.is_disconnected():
                return
            events = await asyncio.to_thread(
                flow_service.events_after, trace_id, after_id=cursor, limit=200
            )
            for ev in events:
                cursor = ev["row_id"]
                yield f"id: {ev['row_id']}\ndata: {_json.dumps(ev, ensure_ascii=False)}\n\n"
            if events:
                continue
            detail = await asyncio.to_thread(flow_service.message_detail, trace_id)
            if detail is None:
                yield 'data: {"type": "missing"}\n\n'
                return
            if detail["status"] in ("closed", "interrupted"):
                yield 'data: {"type": "trace_end"}\n\n'
                return
            yield ": ping\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
