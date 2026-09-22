# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebChat 路由（方案 §7.7，M4）。SSE 事件帧见方案 §8.2。

鉴权走路由依赖；消息与回复的落库在 chat_ingress（虚拟群 + 专属空间）。
M4 语义：非流式——SSE 只有三类帧 run_started/complete/error；整段返回
后前端做打字机渲染。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from webui.auth import AuthContext, require_auth
from webui.db import connect_ro
from webui.responses import ok
from webui.services import conversations as conv_service

router = APIRouter(
    tags=["chat"], dependencies=[Depends(require_auth)]
)


def _virtual_group() -> str:
    from webui.chat_ingress import WEBCHAT_GROUP_ID

    return str(WEBCHAT_GROUP_ID)


@router.get("/api/v1/chat/session")
async def chat_session() -> Any:
    group_id = _virtual_group()
    total = 0
    conn = connect_ro(conv_service._memory_db())
    if conn is not None:
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM group_messages WHERE group_id = ?", (group_id,)
            ).fetchone()[0]
        except Exception:
            total = 0
        finally:
            conn.close()
    return ok({"group_id": group_id, "message_count": total, "space": "webchat"})


@router.get("/api/v1/chat/messages")
async def chat_messages(
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Any:
    group_id = _virtual_group()
    conn = connect_ro(conv_service._memory_db())
    if conn is None:
        return ok({"items": []})
    try:
        sql = ("SELECT id, timestamp, user_id, content, source_kind FROM group_messages "
               "WHERE group_id = ?")
        params: list = [group_id]
        if before_id:
            sql += " AND id < ?"
            params.append(before_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
    except Exception:
        return ok({"items": []})
    finally:
        conn.close()
    keys = ("id", "timestamp", "user_id", "content", "source_kind")
    items = [dict(zip(keys, row, strict=True)) for row in rows]
    return ok({"items": list(reversed(items))})  # 旧→新，前端顺序渲染


@router.post("/api/v1/chat/reset")
async def chat_reset() -> Any:
    """清空 WebChat 会话：删虚拟群消息段 + 整合 checkpoint（长期记忆不动）。"""
    db = conv_service._memory_db()
    if not db.exists():
        return ok({"cleared": 0})
    conn = sqlite3.connect(db)
    try:
        cursor = conn.execute("DELETE FROM group_messages WHERE group_id = ?",
                              (_virtual_group(),))
        # 整合 checkpoint 一并清除（强制从头重整；表可能尚未建——幂等建表）
        conn.execute(
            """CREATE TABLE IF NOT EXISTS consolidation_state (
                group_id TEXT PRIMARY KEY,
                last_processed_id INTEGER NOT NULL DEFAULT 0,
                skip_streak INTEGER NOT NULL DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute("DELETE FROM consolidation_state WHERE group_id = ?",
                     (_virtual_group(),))
        conn.commit()
        cleared = cursor.rowcount
    finally:
        conn.close()
    return ok({"cleared": cleared})


@router.post("/api/v1/chat")
async def chat(
    payload: dict,
    auth: Annotated[AuthContext, Depends(require_auth)] = None,  # type: ignore[assignment]
) -> Any:
    message = (payload.get("message") or "").strip()
    if not message:
        return ok({"lines": [], "thought": ""})

    async def stream():
        from webui.chat_ingress import run_turn

        yield f"data: {json.dumps({'type': 'run_started', 'data': {}})}\n\n"
        try:
            result = await asyncio.wait_for(run_turn(message, auth.username), timeout=120.0)
            payload_out = {
                "type": "complete",
                "data": {"lines": result["lines"], "thought": result["thought"]},
            }
            yield f"data: {json.dumps(payload_out, ensure_ascii=False)}\n\n"
        except RuntimeError as e:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}}, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'data': {'message': '回复超时'}})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
