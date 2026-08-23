# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""ConversationManager（`context.conversation_manager`）。

插件用它读写多轮对话历史。落在独立的 `astrbot_conversations` 表，与 Stella 的
记忆系统完全隔离——插件的对话不参与记忆整合，也不会被记忆压缩任务动到。

`Conversation.history` 是 **JSON 字符串**而不是 list：上游就是这样，插件里到处是
`json.loads(conv.history)`，改成 list 会把它们全打断。
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from config import DB_PATH

from .po import Conversation
from .preferences import sp

logger = logging.getLogger("astrbot_compat.conversation")

SEL_CONV_KEY = "sel_conv_id"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    from memory.schema import create_astrbot_conversations_table

    create_astrbot_conversations_table(conn)
    return conn


def _row_to_conversation(row: tuple) -> Conversation:
    cid, platform_id, user_id, content, title, persona_id, token_usage, created, updated = row
    return Conversation(
        platform_id=platform_id or "",
        user_id=user_id or "",
        cid=cid,
        history=content or "[]",
        title=title or "",
        persona_id=persona_id or "",
        created_at=created or 0,
        updated_at=updated or 0,
        token_usage=token_usage or 0,
    )


_SELECT = (
    "SELECT cid, platform_id, user_id, content, title, persona_id, "
    "token_usage, created_at, updated_at FROM astrbot_conversations"
)


class ConversationManager:
    """与上游 `astrbot.core.conversation_mgr.ConversationManager` 对齐的异步 API。"""

    def __init__(self) -> None:
        self.session_conversations: dict[str, str] = {}
        self._on_deleted: list[Callable[[str], Awaitable[None]]] = []

    def register_on_session_deleted(
        self,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        self._on_deleted.append(callback)

    async def _trigger_session_deleted(self, unified_msg_origin: str) -> None:
        for cb in self._on_deleted:
            with contextlib.suppress(Exception):
                await cb(unified_msg_origin)

    # ---------- 增删改查 ----------

    async def new_conversation(
        self,
        unified_msg_origin: str,
        platform_id: str | None = None,
        content: list[dict] | None = None,
        title: str | None = None,
        persona_id: str | None = None,
    ) -> str:
        if not platform_id:
            parts = unified_msg_origin.split(":")
            platform_id = parts[0] if len(parts) >= 3 else "unknown"
        cid = str(uuid.uuid4())
        now = int(time.time())
        try:
            with contextlib.closing(_connect()) as conn:
                conn.execute(
                    "INSERT INTO astrbot_conversations "
                    "(cid, platform_id, user_id, content, title, persona_id, "
                    "token_usage, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        cid,
                        platform_id,
                        unified_msg_origin,
                        json.dumps(content or [], ensure_ascii=False),
                        title,
                        persona_id,
                        0,
                        now,
                        now,
                    ),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"[astrbot_compat] 新建对话失败 {unified_msg_origin}: {e}")
            raise
        self.session_conversations[unified_msg_origin] = cid
        await sp.session_put(unified_msg_origin, SEL_CONV_KEY, cid)
        return cid

    async def switch_conversation(self, unified_msg_origin: str, conversation_id: str) -> None:
        self.session_conversations[unified_msg_origin] = conversation_id
        await sp.session_put(unified_msg_origin, SEL_CONV_KEY, conversation_id)

    async def get_curr_conversation_id(self, unified_msg_origin: str) -> str | None:
        cid = self.session_conversations.get(unified_msg_origin)
        if cid:
            return cid
        cid = await sp.session_get(unified_msg_origin, SEL_CONV_KEY, None)
        if cid:
            self.session_conversations[unified_msg_origin] = cid
        return cid

    async def get_conversation(
        self,
        unified_msg_origin: str,
        conversation_id: str,
        create_if_not_exists: bool = False,
    ) -> Conversation | None:
        conv = self._fetch(conversation_id)
        if conv is None and create_if_not_exists:
            new_cid = await self.new_conversation(unified_msg_origin)
            conv = self._fetch(new_cid)
        return conv

    def _fetch(self, conversation_id: str) -> Conversation | None:
        try:
            with contextlib.closing(_connect()) as conn:
                row = conn.execute(
                    f"{_SELECT} WHERE cid=?",
                    (conversation_id,),
                ).fetchone()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 读取对话失败 {conversation_id}: {e}")
            return None
        return _row_to_conversation(row) if row else None

    async def get_conversations(
        self,
        unified_msg_origin: str | None = None,
        platform_id: str | None = None,
    ) -> list[Conversation]:
        sql = _SELECT
        clauses: list[str] = []
        params: list[Any] = []
        if unified_msg_origin:
            clauses.append("user_id=?")
            params.append(unified_msg_origin)
        if platform_id:
            clauses.append("platform_id=?")
            params.append(platform_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        try:
            with contextlib.closing(_connect()) as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 列出对话失败: {e}")
            return []
        return [_row_to_conversation(r) for r in rows]

    async def get_filtered_conversations(
        self,
        page: int = 1,
        page_size: int = 20,
        platform_ids: list[str] | None = None,
        search_query: str = "",
        include_history: bool = True,
        **kwargs: Any,
    ) -> tuple[list[Conversation], int]:
        _ = (include_history, kwargs)
        convs = await self.get_conversations()
        if platform_ids:
            convs = [c for c in convs if c.platform_id in platform_ids]
        if search_query:
            convs = [
                c
                for c in convs
                if search_query in (c.title or "") or search_query in c.history
            ]
        total = len(convs)
        start = max(page - 1, 0) * page_size
        return convs[start : start + page_size], total

    async def update_conversation(
        self,
        unified_msg_origin: str,
        conversation_id: str | None = None,
        history: list[dict] | None = None,
        title: str | None = None,
        persona_id: str | None = None,
        token_usage: int | None = None,
    ) -> None:
        if not conversation_id:
            conversation_id = await self.get_curr_conversation_id(unified_msg_origin)
        if not conversation_id:
            logger.warning(f"[astrbot_compat] 无当前对话，跳过更新: {unified_msg_origin}")
            return
        sets: list[str] = ["updated_at=?"]
        params: list[Any] = [int(time.time())]
        if history is not None:
            sets.append("content=?")
            params.append(json.dumps(history, ensure_ascii=False))
        if title is not None:
            sets.append("title=?")
            params.append(title)
        if persona_id is not None:
            sets.append("persona_id=?")
            params.append(persona_id)
        if token_usage is not None:
            sets.append("token_usage=?")
            params.append(token_usage)
        params.append(conversation_id)
        try:
            with contextlib.closing(_connect()) as conn:
                conn.execute(
                    f"UPDATE astrbot_conversations SET {', '.join(sets)} WHERE cid=?",
                    params,
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 更新对话失败 {conversation_id}: {e}")

    async def update_conversation_title(
        self,
        unified_msg_origin: str,
        title: str,
        conversation_id: str | None = None,
    ) -> None:
        await self.update_conversation(unified_msg_origin, conversation_id, title=title)

    async def update_conversation_persona_id(
        self,
        unified_msg_origin: str,
        persona_id: str,
        conversation_id: str | None = None,
    ) -> None:
        await self.update_conversation(
            unified_msg_origin,
            conversation_id,
            persona_id=persona_id,
        )

    async def delete_conversation(
        self,
        unified_msg_origin: str,
        conversation_id: str | None = None,
    ) -> None:
        if not conversation_id:
            conversation_id = await self.get_curr_conversation_id(unified_msg_origin)
        if not conversation_id:
            return
        try:
            with contextlib.closing(_connect()) as conn:
                conn.execute(
                    "DELETE FROM astrbot_conversations WHERE cid=?",
                    (conversation_id,),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 删除对话失败 {conversation_id}: {e}")
            return
        if self.session_conversations.get(unified_msg_origin) == conversation_id:
            self.session_conversations.pop(unified_msg_origin, None)
            await sp.session_remove(unified_msg_origin, SEL_CONV_KEY)
        await self._trigger_session_deleted(unified_msg_origin)

    async def delete_conversations_by_user_id(self, unified_msg_origin: str) -> None:
        try:
            with contextlib.closing(_connect()) as conn:
                conn.execute(
                    "DELETE FROM astrbot_conversations WHERE user_id=?",
                    (unified_msg_origin,),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"[astrbot_compat] 批量删除对话失败 {unified_msg_origin}: {e}")
            return
        self.session_conversations.pop(unified_msg_origin, None)
        await sp.session_remove(unified_msg_origin, SEL_CONV_KEY)
        await self._trigger_session_deleted(unified_msg_origin)

    async def add_message_pair(
        self,
        cid: str,
        user_message: Any,
        assistant_message: Any,
    ) -> None:
        conv = self._fetch(cid)
        if conv is None:
            raise ValueError(f"Conversation with id {cid} not found")
        history = _loads_history(conv.history)
        history.append(_as_dict(user_message))
        history.append(_as_dict(assistant_message))
        await self.update_conversation(conv.user_id, cid, history=history)

    async def get_human_readable_context(
        self,
        unified_msg_origin: str,
        conversation_id: str,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[str], int]:
        _ = unified_msg_origin
        conv = self._fetch(conversation_id)
        if conv is None:
            return [], 0
        history = _loads_history(conv.history)
        lines: list[str] = []
        for msg in history:
            role = msg.get("role", "?")
            content = msg.get("content")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            lines.append(f"{role}: {content}")
        total_pages = max((len(lines) + page_size - 1) // page_size, 1)
        start = max(page - 1, 0) * page_size
        return lines[start : start + page_size], total_pages

    def reset_cache(self) -> None:
        """仅供单测：换 DB_PATH 后清掉进程内的当前会话映射。"""
        self.session_conversations.clear()


def _loads_history(history: str) -> list[dict]:
    try:
        data = json.loads(history or "[]")
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _as_dict(message: Any) -> dict:
    if isinstance(message, dict):
        return message
    if hasattr(message, "to_openai"):
        return message.to_openai()
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    return {"role": "user", "content": str(message)}


_manager: ConversationManager | None = None


def get_conversation_manager() -> ConversationManager:
    global _manager
    if _manager is None:
        _manager = ConversationManager()
    return _manager


__all__ = ["ConversationManager", "get_conversation_manager"]
