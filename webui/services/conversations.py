# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""只读的 legacy QQ 会话和已注册 V2 场景浏览。

旧群消息/checkpoint 路由保持原样；跨平台路由只读取现存 V2 注册表，并按完整
连接与规范会话键分页。短期话题状态仍是 session_context 的进程内内存，不在此暴露。
"""

from __future__ import annotations

from pathlib import Path

import config.settings as settings
from core.transport.keys import decode_conversation_key_v2
from memory.message_store import effective_history_filter
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


def transport_scenes(
    *, adapter: str | None = None, connection_id: str | None = None, kind: str | None = None
) -> list[dict]:
    """List registered V2 scenes and effective message counts without creating schema."""
    conn = connect_ro(_memory_db())
    if conn is None:
        return []
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('conversation_registry_v2', 'group_messages')"
            ).fetchall()
        }
        if "conversation_registry_v2" not in tables:
            return []
        rows = conn.execute(
            "SELECT conversation_key, memory_space, created_at "
            "FROM conversation_registry_v2 ORDER BY conversation_key"
        ).fetchall()
        message_columns = (
            {row[1] for row in conn.execute("PRAGMA table_info(group_messages)").fetchall()}
            if "group_messages" in tables
            else set()
        )
        can_count = {"connection_id", "conversation_key", "timestamp"}.issubset(
            message_columns
        )
        count_filter = effective_history_filter(conn.cursor()) if can_count else ""
        result = []
        for conversation_key, memory_space, created_at in rows:
            try:
                bot, scene = decode_conversation_key_v2(str(conversation_key))
            except (TypeError, ValueError):
                # Corrupt historical registry rows are omitted, never guessed into a
                # QQ integer identity or exposed with a malformed key.
                continue
            if adapter is not None and bot.adapter != adapter:
                continue
            if connection_id is not None and bot.connection_id != connection_id:
                continue
            if kind is not None and scene.kind != kind:
                continue
            total, last_ts = 0, None
            if can_count:
                row = conn.execute(
                    "SELECT COUNT(*), MAX(timestamp) FROM group_messages "
                    "WHERE connection_id = ? AND conversation_key = ? "
                    f"{count_filter}",
                    (bot.connection_id, conversation_key),
                ).fetchone()
                total, last_ts = int(row[0] or 0), row[1]
            result.append(
                {
                    "conversation_key": str(conversation_key),
                    "connection_id": bot.connection_id,
                    "adapter": bot.adapter,
                    "platform_scope": bot.platform_scope,
                    "self_id": bot.self_id,
                    "kind": scene.kind,
                    "scene_id": scene.scene_id,
                    "parent_path": list(scene.parent_path),
                    "thread_id": scene.thread_id,
                    "memory_space": str(memory_space),
                    "created_at": created_at,
                    "messages": total,
                    "last_ts": last_ts,
                }
            )
        return result
    except Exception:
        return []
    finally:
        conn.close()


def transport_messages(
    conversation_key: str,
    *,
    limit: int,
    cursor: int | None = None,
    snapshot_id: int | None = None,
) -> dict:
    """Return effective history for one canonical, registered V2 conversation."""
    try:
        bot, _scene = decode_conversation_key_v2(conversation_key)
    except (TypeError, ValueError) as exc:
        raise ValueError("conversation_key_invalid") from exc

    conn = connect_ro(_memory_db())
    if conn is None:
        return {
            "conversation_key": conversation_key,
            "total": 0,
            "items": [],
            "snapshot_id": 0,
            "next_cursor": None,
        }
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('conversation_registry_v2', 'group_messages')"
            ).fetchall()
        }
        if "conversation_registry_v2" not in tables:
            raise LookupError("conversation_not_registered")
        registered = conn.execute(
            "SELECT 1 FROM conversation_registry_v2 WHERE conversation_key = ?",
            (conversation_key,),
        ).fetchone()
        if registered is None:
            raise LookupError("conversation_not_registered")
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(group_messages)").fetchall()
        }
        required = {"id", "timestamp", "user_id", "content", "source_kind", "msg_id",
                    "connection_id", "conversation_key", "platform_message_id"}
        if not required.issubset(columns):
            return {
                "conversation_key": conversation_key,
                "total": 0,
                "items": [],
                "snapshot_id": 0,
                "next_cursor": None,
            }
        before_id = cursor
        if before_id is not None and snapshot_id is None:
            raise ValueError("history_snapshot_id_required")
        db_cursor = conn.cursor()
        effective_filter = effective_history_filter(db_cursor)
        params = (bot.connection_id, conversation_key)
        if snapshot_id is None:
            snapshot_id = int(
                db_cursor.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM group_messages "
                    "WHERE connection_id = ? AND conversation_key = ?",
                    params,
                ).fetchone()[0]
            )
        if snapshot_id < 0 or (before_id is not None and (before_id <= 0 or before_id > snapshot_id)):
            raise ValueError("history_cursor_invalid")
        id_filter = " AND id <= ?"
        id_params: tuple[int, ...] = (snapshot_id,)
        if before_id is not None:
            id_filter += " AND id < ?"
            id_params = (snapshot_id, before_id)
        total = db_cursor.execute(
            "SELECT COUNT(*) FROM group_messages "
            "WHERE connection_id = ? AND conversation_key = ? "
            f"AND id <= ? "
            f"{effective_filter}",
            (*params, snapshot_id),
        ).fetchone()[0]
        rows = db_cursor.execute(
            "SELECT id, timestamp, user_id, content, source_kind, msg_id, platform_message_id "
            "FROM group_messages WHERE connection_id = ? AND conversation_key = ? "
            f"{id_filter} {effective_filter} ORDER BY id DESC LIMIT ?",
            (*params, *id_params, int(limit) + 1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        keys = (
            "id", "timestamp", "user_id", "content", "source_kind", "msg_id",
            "platform_message_id",
        )
        return {
            "conversation_key": conversation_key,
            "total": int(total),
            "items": [dict(zip(keys, row, strict=True)) for row in rows],
            "snapshot_id": snapshot_id,
            "next_cursor": int(rows[-1][0]) if rows and has_more else None,
        }
    finally:
        conn.close()
