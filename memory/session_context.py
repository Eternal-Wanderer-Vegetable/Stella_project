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
    SESSION_SUMMARY_MAX_TOKENS,
)
from memory.prompt_builder import estimate_tokens
from memory.summary_packet import (
    SummaryPacket,
    render_summary_packet,
    validate_summary_packet,
)


@dataclass
class SessionState:
    """单个群的会话压缩状态。

    summarized_up_to_id 为 0 表示会话尚未初始化——此时首次调用
    ``ensure_initialized()`` 会把它对齐到当前尾巴起点，即「本场会话从现在开始」，
    避免把整个历史当作待压缩内容。

    v16（多人身份修复计划 §6.4）：reset_generation 在会话重置时递增；
    identity_revision 跟踪最近一次观察到的会话身份版本（由 build_context
    写入）。async 压缩在 await 前捕获 (generation, identity_revision,
    summarized_up_to_id, tail_start_id)，提交前比较——任一不匹配即丢弃结果，
    不推进位置（CAS；防止更名/重置期间旧摘要或 skip 覆盖新状态）。
    """

    summarized_up_to_id: int = 0
    # 进程重启后旧自由摘要自然消失；运行时只接受可验证 packet。
    summary: SummaryPacket | str | None = None
    last_activity: float = field(default_factory=time.monotonic)
    compact_count: int = 0
    # 已压缩的消息条数（仅用于日志与诊断）
    compacted_messages: int = 0
    # 会话重置代数（reset 时 +1）与最近观察到的身份版本（CAS 用）
    reset_generation: int = 0
    identity_revision: int = 0
    summary_revision: int = 0


_sessions: dict[int, SessionState] = {}
_summary_revision_by_group: dict[int, int] = {}


def _state(group_id: int) -> SessionState:
    """取（或懒创建）某群的会话状态。"""
    if group_id not in _sessions:
        revision = _summary_revision_by_group.get(group_id, -1) + 1
        _summary_revision_by_group[group_id] = revision
        _sessions[group_id] = SessionState(summary_revision=revision)
    return _sessions[group_id]


def _advance_summary_revision(group_id: int, state: SessionState) -> int:
    revision = max(
        state.summary_revision,
        _summary_revision_by_group.get(group_id, -1),
    ) + 1
    state.summary_revision = revision
    _summary_revision_by_group[group_id] = revision
    return revision


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


def get_summary_snapshot(group_id: int) -> tuple[str, int, str, bool]:
    """返回已验证摘要文本、单调 revision、格式及有效性。

    每次缓存读取前都走同一验证入口。旧自由文本、格式漂移、digest 错误或超预算
    packet 会被清除并递增 revision，避免暖缓存继续返回旧摘要。
    """
    if not SESSION_CONTEXT_ENABLED:
        return "", -1, "disabled", True
    state = _sessions.get(group_id)
    if state is None:
        return "", _summary_revision_by_group.get(group_id, -1), "none", True
    packet = state.summary
    if packet is None:
        return "", state.summary_revision, "none", True
    if not isinstance(packet, SummaryPacket) or not validate_summary_packet(packet):
        state.summary = None
        revision = _advance_summary_revision(group_id, state)
        logger.warning(
            f"[Session] 群 {group_id} 清除无效/旧格式压缩摘要（revision={revision}）"
        )
        return "", revision, "invalid", False
    text = render_summary_packet(packet)
    if not text or estimate_tokens(text) > SESSION_SUMMARY_MAX_TOKENS:
        state.summary = None
        revision = _advance_summary_revision(group_id, state)
        logger.warning(
            f"[Session] 群 {group_id} 清除超预算压缩摘要（revision={revision}）"
        )
        return "", revision, "invalid", False
    return text, state.summary_revision, packet.format_version, True


def get_summary(group_id: int) -> str:
    """取当前已验证 packet 的服务端渲染文本；无效/无摘要返回空串。"""
    return get_summary_snapshot(group_id)[0]


def get_summary_packet(group_id: int) -> SummaryPacket | None:
    """取当前合法 packet；旧自由文本或损坏包在读取时失效。"""
    get_summary_snapshot(group_id)
    state = _sessions.get(group_id)
    return state.summary if state and isinstance(state.summary, SummaryPacket) else None


def invalidate_summary(group_id: int, reason: str) -> None:
    """失效会话身份/packet 资格并单调递增 revision。"""
    state = _sessions.get(group_id)
    if state is None or state.summary is None:
        return
    state.summary = None
    revision = _advance_summary_revision(group_id, state)
    logger.warning(
        f"[Session] 群 {group_id} 丢弃压缩 packet（{reason}; revision={revision}）"
    )


def summary_revision(group_id: int) -> int:
    """独立于 compact_count 的单调摘要版本，覆盖清空及 end/rebuild。"""
    state = _sessions.get(group_id)
    if state is not None:
        return state.summary_revision
    return _summary_revision_by_group.get(group_id, -1)


def summary_version(group_id: int) -> int:
    """会话摘要的版本号，供会话上下文缓存编入 key。

    - 无状态返回 -1（从未初始化）；
    - 有状态返回 compact_count：apply_summary 每写一次摘要必 +1，
      end_session 清空后回到 -1（无状态）→ 0（新状态）也必然变化。

    覆盖 skip_range 的场景：它只推进位置不改摘要文本，摘要不变则
    short_term 组装结果不变，版本不递增是**正确**的（内容没变就不该失效）。
    """
    state = _sessions.get(group_id)
    if state is None:
        return -1
    return state.compact_count


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


def apply_summary(
    group_id: int,
    summary: SummaryPacket | str,
    up_to_id: int,
    message_count: int = 0,
) -> None:
    """写入已验证 SummaryPacket 并推进已压缩位置。

    summary 为空时**不推进** up_to_id：LLM 调用失败时，这批消息应当留待下次重试，
    而不是被静默跳过。模型判定「这段无可摘要内容」的情形请调用
    ``skip_range()`` 推进位置（两者区别处理，否则噪音消息会永远堆在待压缩区间）。
    """
    if not SESSION_CONTEXT_ENABLED:
        return
    if not isinstance(summary, SummaryPacket):
        logger.debug(f"[Session] 群 {group_id} 压缩结果不是 SummaryPacket，保留待压缩区间")
        return
    text = render_summary_packet(summary)
    if (
        not validate_summary_packet(summary)
        or not text
        or estimate_tokens(text) > SESSION_SUMMARY_MAX_TOKENS
    ):
        logger.warning(f"[Session] 群 {group_id} SummaryPacket 校验/预算失败，水位不推进")
        return
    state = _state(group_id)
    if (
        summary.source_low_id != state.summarized_up_to_id
        or summary.source_watermark != up_to_id
        or (message_count > 0 and message_count != summary.source_row_count)
    ):
        logger.warning(f"[Session] 群 {group_id} SummaryPacket 区间/计数不匹配，水位不推进")
        return
    state.summary = summary
    state.summarized_up_to_id = max(state.summarized_up_to_id, up_to_id)
    state.compact_count += 1
    state.compacted_messages += max(0, message_count)
    revision = _advance_summary_revision(group_id, state)
    logger.info(
        f"🗜️ [Session] 群 {group_id} 会话压缩完成"
        f"（第 {state.compact_count} 次，累计 {state.compacted_messages} 条，"
        f"摘要 {estimate_tokens(text)} tokens，revision={revision}，"
        f"已压缩至消息 {state.summarized_up_to_id}）"
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
    state = _sessions.get(group_id)
    if state is None:
        return False
    had_content = bool(get_summary(group_id)) or state.compact_count > 0
    _advance_summary_revision(group_id, state)
    _sessions.pop(group_id, None)
    if had_content:
        logger.info(
            f"💤 [Session] 群 {group_id} 会话结束"
            f"（共压缩 {state.compact_count} 次 / {state.compacted_messages} 条）"
        )
    return had_content


# ── reset generation / identity revision（多人身份修复计划 §6.4 CAS） ──


def bump_reset_generation(group_id: int) -> int:
    """会话重置：代数 +1。在途压缩提交前的 CAS 会因此拒绝旧结果。"""
    state = _state(group_id)
    state.reset_generation += 1
    state.summarized_up_to_id = 0
    state.summary = None
    revision = _advance_summary_revision(group_id, state)
    logger.info(
        f"🔄 [Session] 群 {group_id} 会话重置（generation={state.reset_generation}, "
        f"summary_revision={revision}）"
    )
    return state.reset_generation


def observe_identity_revision(group_id: int, revision: int) -> None:
    """记录本轮观察到的身份版本（build_context 每轮调用；零 DB）。

    **不为观察创建状态**：无状态的会话保持「从未初始化」语义
    （summary_version 仍为 -1），compact 的 CAS 只需覆盖已初始化会话。
    """
    state = _sessions.get(group_id)
    if state is None:
        return
    state.identity_revision = max(state.identity_revision, int(revision or 0))


def compact_guard(group_id: int) -> tuple[int, int, int]:
    """捕获 CAS 快照 ``(reset_generation, identity_revision, summarized_up_to_id)``。"""
    state = _sessions.get(group_id)
    if state is None:
        return (0, 0, 0)
    return (state.reset_generation, state.identity_revision, state.summarized_up_to_id)


def compact_guard_ok(group_id: int, guard: tuple[int, int, int]) -> bool:
    """提交前比较：任一维度变化即 False（丢弃结果，不推进位置，下轮重试）。"""
    return compact_guard(group_id) == tuple(guard)


def session_stats(group_id: int) -> dict:
    """会话状态快照（供日志与测试）。"""
    state = _sessions.get(group_id)
    if state is None:
        return {"active": False}
    return {
        "active": True,
        "summarized_up_to_id": state.summarized_up_to_id,
        "summary_tokens": estimate_tokens(get_summary(group_id)),
        "compact_count": state.compact_count,
        "compacted_messages": state.compacted_messages,
        "summary_revision": state.summary_revision,
        "reset_generation": state.reset_generation,
        "summary_format": (
            state.summary.format_version
            if isinstance(state.summary, SummaryPacket)
            else "none"
        ),
        "idle_seconds": round(time.monotonic() - state.last_activity, 1),
    }


def reset_state() -> None:
    """清空全部会话状态（供测试使用）。"""
    _sessions.clear()
    _summary_revision_by_group.clear()
