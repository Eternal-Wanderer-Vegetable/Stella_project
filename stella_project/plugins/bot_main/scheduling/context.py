# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""调度运行的有界只读上下文（计划 §6.5）。

Agent 任务生成前给模型看「这个群最近在聊什么」——刻意**不走**共享 Pipeline 的
``build_context`` pre-hook：那上面挂着会话初始化、压缩排程等交互副作用，调度
路径是只读的，一样都不许发生（计划 §2/§6.5）。这里自开只读连接读两张表，
拼装后按字符预算封顶：

- 短期话题摘要（``short_term_context.active_summary``，整合器产物）；
- 最近群消息尾巴（``group_messages``，每条截断、条数封顶、总长封顶）。

失败语义：**上下文是增强而非安全闸**——读不到就空着跑（显式 no_context），
与门控的 fail-closed 是两回事（那在 ``memory.proactive_gate.can_speak_for_scheduled``）。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from nonebot import logger

# 单条消息进上下文的最大字符：再长的消息对「最近在聊什么」没有增量信息
_PER_MESSAGE_MAX_CHARS = 80
# 尾巴条数上限（每条已被截到 80 字符，这是第二道闸）
_MAX_MESSAGES = 20


@dataclass(slots=True)
class ScheduledContext:
    """有界上下文。``has_context=False`` 是显式的「无上下文」结果（新群/读库
    失败），调用方应如实告诉模型「没有可参考的群聊历史」。"""

    text: str = ""
    has_context: bool = False
    truncated: bool = False
    summary_used: bool = False
    messages_used: int = 0


def build_scheduled_context(
    group_id: int,
    *,
    max_chars: int = 1200,
    max_messages: int = _MAX_MESSAGES,
) -> ScheduledContext:
    """读群摘要 + 近期消息，拼装出封顶的只读上下文。

    任何读取失败都降级为「无上下文」并告警，绝不抛异常打断调度链路。
    """
    max_chars = max(int(max_chars), 200)
    summary_text = _read_summary(group_id)
    message_lines, older_available, clipped_any = _read_recent_messages(
        group_id, limit=max(1, int(max_messages))
    )

    used_summary = False
    used_messages: list[str] = []
    truncated = False

    sections: list[str] = []
    budget = max_chars
    if summary_text:
        head = "【群近期话题】\n"
        if len(summary_text) > budget:
            summary_text = summary_text[:budget]
            truncated = True
        if summary_text:
            sections.append(head + summary_text)
            budget -= len(head) + len(summary_text)
            used_summary = True

    if budget > 0 and message_lines:
        tail_head = "\n【最近消息】\n"
        budget -= len(tail_head)
        # 从最新往回收，直到预算用尽（丢的是更旧的消息）
        for line in reversed(message_lines):
            if len(line) > budget:
                truncated = True
                break
            used_messages.append(line)
            budget -= len(line) + 1  # +1 换行
        used_messages.reverse()
        if used_messages:
            sections.append(tail_head + "\n".join(used_messages))
    elif message_lines and not used_messages:
        truncated = True

    text = "\n".join(sections).strip()
    return ScheduledContext(
        text=text,
        has_context=bool(text),
        truncated=truncated or (older_available > 0) or clipped_any,
        summary_used=used_summary,
        messages_used=len(used_messages),
    )


def _connect_readonly() -> sqlite3.Connection:
    """只读连接（``file:...?mode=ro``）：调度路径对记忆库零写入的硬保证。"""
    from config import DB_PATH

    uri = Path(DB_PATH).resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


def _read_summary(group_id: int) -> str:
    """短期话题摘要（整合器产物）；表不存在/读失败 → 空串。"""
    try:
        conn = _connect_readonly()
        try:
            row = conn.execute(
                "SELECT active_summary FROM short_term_context WHERE group_id = ?",
                (str(group_id),),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"[Scheduling] 读取群 {group_id} 短期摘要失败（按无摘要）: {e}")
        return ""
    return str(row[0]).strip() if row and row[0] else ""


def _read_recent_messages(group_id: int, *, limit: int) -> tuple[list[str], int, bool]:
    """最近消息行（旧→新排序的格式化文本）；读取失败 → 空 + 无丢弃。

    返回 ``(lines, older_available, clipped_any)``：``older_available``=1 表示
    还有更旧的消息没进候选；``clipped_any`` 表示有消息正文被单条截断。
    """
    try:
        conn = _connect_readonly()
        try:
            rows = conn.execute(
                "SELECT user_id, content, source_kind FROM group_messages "
                "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                (str(group_id), limit + 1),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"[Scheduling] 读取群 {group_id} 近期消息失败（按无上下文）: {e}")
        return [], 0, False

    older_available = 1 if len(rows) > limit else 0
    rows = rows[:limit]
    lines: list[str] = []
    clipped_any = False
    for user_id, content, source_kind in reversed(rows):  # 旧→新
        text = " ".join(str(content or "").split())
        if not text:
            continue
        if len(text) > _PER_MESSAGE_MAX_CHARS:
            text = text[:_PER_MESSAGE_MAX_CHARS]
            clipped_any = True
        speaker = "Stella" if str(source_kind or "") == "BOT_SELF" else f"用户{user_id}"
        lines.append(f"{speaker}: {text}")
    return lines, older_available, clipped_any


__all__ = ["ScheduledContext", "build_scheduled_context"]
