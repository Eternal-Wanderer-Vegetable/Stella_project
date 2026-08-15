# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话上下文压缩的状态管理（Session Context）。

解决的问题：短时连续对话中，早期消息会滚出尾巴窗口（RECENT_TAIL_LIMIT）
而彻底消失，Bot 在长对话里会忘记前面聊过什么。本机制把滚出的部分压缩成
一段摘要，随尾巴一起注入 Prompt。

**边界约束（本模块的核心不变量）**：摘要覆盖范围严格早于尾巴。
``summarized_up_to_id`` 记录已压缩到的消息 id，压缩只处理
``(summarized_up_to_id, 尾巴起点)`` 这个开闭区间。两者重叠会导致同一段对话
出现两个版本，模型以摘要为准从而接错话题（2026-08-13 缺陷的成因）。

状态是**进程内**的：重启后摘要丢失，但原始消息在库里、尾巴可重建，
下一次压缩会重新生成。为此不引入 schema 迁移。

本模块只管状态与判定，不含 LLM 调用（见 memory/session_compact.py），
因此可以完全离线单测。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from nonebot import logger

from config import (
    SESSION_COMPACT_MAX_MESSAGES,
    SESSION_COMPACT_THRESHOLD_TOKENS,
    SESSION_CONTEXT_ENABLED,
    SESSION_IDLE_TIMEOUT_SECONDS,
)
from memory.prompt_builder import estimate_tokens


@dataclass
class SessionState:
    """单个群的会话压缩状态。

    summarized_up_to_id 为 0 表示会话尚未初始化——此时首次调用
    ``ensure_initialized()`` 会把它对齐到当前尾巴起点，即「本场会话从现在开始」，
    避免把整个历史当作待压缩内容。
    """

    summarized_up_to_id: int = 0
    summary: str = ""
    last_activity: float = field(default_factory=time.monotonic)
    compact_count: int = 0
    # 已压缩的消息条数（仅用于日志与诊断）
    compacted_messages: int = 0


_sessions: dict[int, SessionState] = {}


def _state(group_id: int) -> SessionState:
    """取（或懒创建）某群的会话状态。"""
    if group_id not in _sessions:
        _sessions[group_id] = SessionState()
    return _sessions[group_id]


def touch(group_id: int) -> None:
    """记录该群有活动（收到消息或自己发言时调用）。

    只更新时间戳，不做任何 DB 访问——它在消息热路径上被每条消息调用。
    """
    if not SESSION_CONTEXT_ENABLED:
        return
    _state(group_id).last_activity = time.monotonic()


def ensure_initialized(group_id: int, tail_start_id: int) -> None:
    """会话首次使用时，把已压缩位置对齐到当前尾巴起点。

    否则待压缩区间会是 ``(0, 尾巴起点)``——即全部历史消息，
    第一次压缩就会试图吞下整个群的聊天记录。
    """
    if not SESSION_CONTEXT_ENABLED:
        return
    state = _state(group_id)
    if state.summarized_up_to_id == 0 and tail_start_id > 0:
        state.summarized_up_to_id = tail_start_id
        logger.debug(f"[Session] 群 {group_id} 会话初始化，起点对齐到消息 {tail_start_id}")


def get_summary(group_id: int) -> str:
    """取当前会话摘要（覆盖尾巴之前的内容）；无则空串。"""
    if not SESSION_CONTEXT_ENABLED:
        return ""
    return _sessions.get(group_id, SessionState()).summary


def pending_bounds(group_id: int, tail_start_id: int) -> tuple[int, int] | None:
    """返回待压缩的消息 id 区间 ``(exclusive_low, exclusive_high)``；无待压缩则 None。

    区间是 ``summarized_up_to_id < id < tail_start_id``：左开保证不重复压缩，
    右开保证不与尾巴重叠。
    """
    if not SESSION_CONTEXT_ENABLED:
        return None
    state = _sessions.get(group_id)
    if state is None or state.summarized_up_to_id <= 0:
        return None
    if tail_start_id <= state.summarized_up_to_id + 1:
        return None
    return state.summarized_up_to_id, tail_start_id


def should_compact(pending_text: str) -> bool:
    """待压缩文本是否已达到触发阈值。"""
    if not SESSION_CONTEXT_ENABLED or not pending_text.strip():
        return False
    return estimate_tokens(pending_text) >= SESSION_COMPACT_THRESHOLD_TOKENS


def compact_message_limit() -> int:
    """单次压缩最多喂入的消息条数。"""
    return max(1, SESSION_COMPACT_MAX_MESSAGES)


def apply_summary(group_id: int, summary: str, up_to_id: int, message_count: int = 0) -> None:
    """写入新摘要并推进已压缩位置。

    summary 为空时**不推进** up_to_id：LLM 调用失败时，这批消息应当留待下次重试，
    而不是被静默跳过。模型判定「这段无可摘要内容」的情形请调用
    ``skip_range()`` 推进位置（两者区别处理，否则噪音消息会永远堆在待压缩区间）。
    """
    if not SESSION_CONTEXT_ENABLED:
        return
    text = (summary or "").strip()
    if not text:
        logger.debug(f"[Session] 群 {group_id} 压缩产出为空，保留待压缩区间待下次重试")
        return
    state = _state(group_id)
    state.summary = text
    state.summarized_up_to_id = max(state.summarized_up_to_id, up_to_id)
    state.compact_count += 1
    state.compacted_messages += max(0, message_count)
    logger.info(
        f"🗜️ [Session] 群 {group_id} 会话压缩完成"
        f"（第 {state.compact_count} 次，累计 {state.compacted_messages} 条，"
        f"摘要 {estimate_tokens(text)} tokens，已压缩至消息 {state.summarized_up_to_id}）"
    )


def skip_range(group_id: int, up_to_id: int, message_count: int = 0) -> None:
    """跳过一段无可摘要内容的消息：推进位置但保留原摘要。

    与 ``apply_summary("")`` 的区别是**故意的**：
    - 模型判定「这段全是寒暄/刷屏，没什么可留的」→ 本函数，推进位置；
    - LLM 调用失败 → apply_summary 传空，不推进，留待下次重试。
    两者都当成不推进的话，噪音消息会永远堆在待压缩区间里反复触发压缩。
    """
    if not SESSION_CONTEXT_ENABLED:
        return
    state = _state(group_id)
    state.summarized_up_to_id = max(state.summarized_up_to_id, up_to_id)
    state.compacted_messages += max(0, message_count)
    logger.debug(
        f"[Session] 群 {group_id} 跳过 {message_count} 条无摘要价值的消息"
        f"（已压缩至 {state.summarized_up_to_id}）"
    )


def is_idle(group_id: int, timeout: float | None = None) -> bool:
    """该群会话是否已空闲超时。"""
    state = _sessions.get(group_id)
    if state is None:
        return False
    limit = SESSION_IDLE_TIMEOUT_SECONDS if timeout is None else timeout
    return (time.monotonic() - state.last_activity) >= limit


def idle_groups(timeout: float | None = None) -> list[int]:
    """返回所有已空闲超时且仍持有会话状态的群号。"""
    if not SESSION_CONTEXT_ENABLED:
        return []
    return [gid for gid in list(_sessions) if is_idle(gid, timeout)]


def end_session(group_id: int) -> bool:
    """结束会话：清空状态。返回是否确实结束了一个进行中的会话。

    仅当该群曾有过压缩或有过摘要时才算「进行中的会话」——
    否则每次空闲检查都会对所有静默的群报告一次结束。
    """
    state = _sessions.pop(group_id, None)
    if state is None:
        return False
    had_content = bool(state.summary) or state.compact_count > 0
    if had_content:
        logger.info(
            f"💤 [Session] 群 {group_id} 会话结束"
            f"（共压缩 {state.compact_count} 次 / {state.compacted_messages} 条）"
        )
    return had_content


def session_stats(group_id: int) -> dict:
    """会话状态快照（供日志与测试）。"""
    state = _sessions.get(group_id)
    if state is None:
        return {"active": False}
    return {
        "active": True,
        "summarized_up_to_id": state.summarized_up_to_id,
        "summary_tokens": estimate_tokens(state.summary),
        "compact_count": state.compact_count,
        "compacted_messages": state.compacted_messages,
        "idle_seconds": round(time.monotonic() - state.last_activity, 1),
    }


def reset_state() -> None:
    """清空全部会话状态（供测试使用）。"""
    _sessions.clear()
