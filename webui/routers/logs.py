# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""日志路由：history + SSE live（契约见 openspec 的 logs tag，M1）。

SSE 帧协议见方案 §8.3：``id: <字节偏移>`` + ``data: {JSON}``，空闲心跳
``: heartbeat``；重连带 ``Last-Event-ID`` 从断点续传。鉴权走 Bearer 头
（前端用 fetch 流读取，不用 EventSource——后者带不了自定义头）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from webui.auth import require_auth
from webui.responses import ok
from webui.services import logs as logs_service

router = APIRouter(
    tags=["logs"], dependencies=[Depends(require_auth)]
)


@router.get("/api/v1/logs/history")
async def logs_history(
    tail: Annotated[int, Query(ge=1, le=5000)] = 500,
    level: str | None = None,
) -> Any:
    return ok(logs_service.history(tail=tail, level=level))


@router.get("/api/v1/logs/live")
async def logs_live(
    request: Request,
    level: str | None = None,
    resume: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    # 断点续传：优先 Last-Event-ID 头（SSE 语义），兼容 ?resume= 查询参数
    raw_id = request.headers.get("Last-Event-ID", "").strip()
    offset = int(raw_id) if raw_id.isdigit() else resume
    return StreamingResponse(
        logs_service.live(offset, level=level),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 反代默认缓冲会杀死 SSE（方案 R8）
        },
    )
