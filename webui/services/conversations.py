# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""会话浏览取数（只读，方案 §6.9 会话页）。

群消息表（``group_messages``）按 QQ 群归属；整合 checkpoint
（``consolidation_state``）同库。短期话题状态在 session_context 的**进程内
内存**里，不落库——本模块不给（它属于「当下这场对话」，webui 同进程其实
拿得到，但读别人模块的活内存容易踩并发假设，M1 刻意不做，方案 §19 留档）。
"""

from __future__ import annotations

from pathlib import Path

import config.settings as settings
from webui.db import connect_ro


def _memory_db() -> Path:
    return Path(settings.DB_PATH)


def groups() -> list[dict]:
    """有消息的群清单（含计数与最新消息时间），供筛选下拉。"""
    conn = connect_ro(_memory_db())
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT group_id, COUNT(*) AS messages, MAX(timestamp) AS last_ts "
            "FROM group_messages GROUP BY group_id ORDER BY last_ts DESC"
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [
        {"group_id": r[0], "messages": r[1], "last_ts": r[2]} for r in rows
    ]


def messages(group_id: str, *, limit: int, offset: int) -> dict:
    """某群消息分页（时间倒序）。content 是聊天内容，仅返回给已登录管理员。"""
    conn = connect_ro(_memory_db())
    if conn is None:
        return {"group_id": group_id, "total": 0, "items": []}
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM group_messages WHERE group_id = ?", (group_id,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT id, timestamp, user_id, content, source_kind, msg_id "
            "FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (group_id, int(limit), int(offset)),
        ).fetchall()
    except Exception:
        return {"group_id": group_id, "total": 0, "items": []}
    finally:
        conn.close()
    keys = ("id", "timestamp", "user_id", "content", "source_kind", "msg_id")
    return {
        "group_id": group_id,
        "total": int(total),
        "items": [dict(zip(keys, row, strict=True)) for row in rows],
    }


def consolidation_checkpoint(group_id: str) -> dict | None:
    """整合 checkpoint（排障「这条消息为什么没被整合」的直接依据）。"""
    conn = connect_ro(_memory_db())
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT group_id, last_processed_id, skip_streak, updated_at "
            "FROM consolidation_state WHERE group_id = ?",
            (group_id,),
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    keys = ("group_id", "last_processed_id", "skip_streak", "updated_at")
    return dict(zip(keys, row, strict=True))
