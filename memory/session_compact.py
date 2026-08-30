# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话上下文压缩的执行侧（Session Compact）。

与 memory/session_context.py 的分工：后者管状态与判定（纯逻辑、可离线单测），
本模块负责取待压缩消息、调 LLM、把结果写回状态。

**用哪个模型由配置决定**（角色 ``COMPACT``，见 core/llm/registry.py）：

- 纯本地默认绑到主聊天端点。压缩必须快——它在每次回复之后异步触发——而整合
  模型跑在 CPU 上单次 20~60 秒，27B 在 GPU 上约 2 秒。这也是改造前的行为。
- 切在线后按 D2 绑到**记忆域端点**，与整合、提取共用同一个 API key，
  于是共用同一份前缀缓存。

闸门跟着端点绑定走（``gate_of(ROLE_COMPACT)``）：绑主聊天端点就与主聊天串行
共享同一块显存，绑独立的在线端点就真正并行——这条不需要本模块做任何判断。

压缩 prompt 沿用捕获层的**防编造原则**：压不出内容就输出「无」，
宁可丢上下文也不能编造对话里没出现过的内容。
"""
from __future__ import annotations

import asyncio
import sqlite3

from nonebot import logger

from config import (
    DB_PATH,
    SESSION_SUMMARY_MAX_TOKENS,
)
from core.llm import ROLE_COMPACT, acquire, backend_for, gate_of
from core.llm.base import LLMBackend
from core.llm.usage_store import budget_blocked
from memory import session_context as sc

# 温度与生成上限现在是端点×角色配置的一部分：
# LLM_ROLE_COMPACT_TEMPERATURE（默认 0.3，信息提炼而非创作，稳定优先）、
# LLM_ROLE_COMPACT_MAX_TOKENS（默认 0 = 由 SESSION_SUMMARY_MAX_TOKENS 推导，
# prompt 里已按字数约束，上限只防极端情况下无限生成）。

# 正在压缩的群：同一群不并发压缩，否则两次调用会基于同一起点各自推进
_in_flight: set[int] = set()
_tasks: set[asyncio.Task] = set()


def pending_tasks() -> set[asyncio.Task]:
    """返回在途压缩任务集合的副本（供优雅停止等待收尾）。"""
    return set(_tasks)


# 前缀缓存约束（2026-08-28 起）：可变的 {existing} / {messages} 必须排在最后。
# {max_chars} 由 SESSION_SUMMARY_MAX_TOKENS 推导、每次调用相同，属于固定前缀。
# 数据之后只保留一行输出格式提醒——它不进缓存，但只有十几个 token，
# 换来「最后一条指令」的位置优势，避免模型在回顾前加「好的，这是回顾：」之类前缀。
# 理由与守卫详见 memory/consolidation_prompt.py 的同名说明。
COMPACT_PROMPT = """你的任务：把一段群聊对话的较早部分压缩成一段简短的回顾，供你稍后继续对话时参考。


要求：
- 输出一段连续的自然语言，不要分条、不要输出 JSON
- 保留：谁说过的关键信息、正在讨论的话题、已达成的结论、尚未解决的问题
- 舍弃：寒暄、表情、刷屏、重复的附和
- 标注「我」的是你自己说过的话，回顾时同样保留（否则你会忘记自己说过什么）
- 不要推断任何人的动机或心理状态，只记录实际说过的话
- **严禁编造对话中没有出现过的内容**
- 如果这段对话确实没有任何值得保留的内容，只输出一个字：无
- 控制在 {max_chars} 字以内

===== 以上为固定规则；以下是本次待压缩的数据 =====
{existing}
对话内容：
{messages}

直接输出回顾文本，不要任何解释或前缀。"""

EXISTING_SUMMARY_BLOCK = """
这是你之前对更早内容的回顾，需要与下面的新内容**合并成一段**（不要分成两段，也不要丢弃其中的关键信息）：
{summary}
"""


def build_compact_prompt(messages: str, existing_summary: str = "") -> str:
    """拼装压缩 prompt。存在旧摘要时要求合并，避免摘要越积越多。"""
    existing = (
        EXISTING_SUMMARY_BLOCK.format(summary=existing_summary.strip())
        if existing_summary.strip()
        else ""
    )
    # 中文按 1.5 token/字估算（与 prompt_builder.estimate_tokens 一致）
    max_chars = max(50, int(SESSION_SUMMARY_MAX_TOKENS / 1.5))
    return COMPACT_PROMPT.format(existing=existing, messages=messages, max_chars=max_chars)


def _get_backend() -> LLMBackend | None:
    """压缩用的后端；角色 ``COMPACT`` 没绑到可用端点时返回 ``None``。

    不在本模块缓存实例：``core.llm.registry`` 已按角色缓存，再存一份会在
    ``registry.reset_state()``（改配置后重载）之后继续用旧端点——那种 bug
    表现为「GUI 改完保存了但摘要还发去旧地址」，极难查。

    返回 ``None`` 而不是抛异常：压缩是异步后台任务，抛异常只会变成一行
    warning，反而不如显式判空后给一条能照着改的日志。
    """
    return backend_for(ROLE_COMPACT)


def fetch_pending_messages(
    group_id: int, low_id: int, high_id: int, limit: int
) -> tuple[str, int, int]:
    """取待压缩消息（``low_id < id < high_id``），返回 (文本, 实际处理到的 id, 条数)。

    区间左右均为开区间：左侧排除已压缩的，右侧排除尾巴（防止同一段对话
    在摘要与尾巴里各出现一次）。

    条数超过 limit 时只取**最旧的 limit 条**并返回其末尾 id，
    剩余部分留给下一次压缩，保证增量推进而非一次吞下全部。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT id, user_id, content, source_kind FROM group_messages "
            "WHERE group_id = ? AND id > ? AND id < ? ORDER BY id ASC LIMIT ?",
            (str(group_id), low_id, high_id, limit),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [Compact] 读取待压缩消息失败: {e}")
        return "", low_id, 0

    lines: list[str] = []
    max_id = low_id
    for mid, uid, content, kind in rows:
        max_id = mid
        text = (content or "").strip()
        if not text:
            continue
        lines.append(f"我: {text}" if kind == "BOT_SELF" else f"用户({uid}): {text}")

    return "\n".join(lines), max_id, len(lines)


def _is_empty_result(text: str) -> bool:
    """模型是否判定「无可摘要内容」。

    容忍常见变体：无 / 无。/ （无）/ 空串。不做模糊匹配——
    「无法确定…」这类正常回顾不应被误判为空。
    """
    stripped = (text or "").strip().strip("（）()。.、 \n")
    return stripped in ("", "无", "None", "none")


async def compact_once(group_id: int, tail_start_id: int) -> bool:
    """执行一次会话压缩；返回是否实际推进了压缩位置。

    调用方无需判断时机——本函数内部会检查区间与阈值，不满足直接返回 False。
    """
    # 每日 token 预算：撞破之后不再花钱做压缩。返回 False 即「未推进压缩位置」，
    # 这批消息留在待压缩区间等下一个预算周期——与「端点未配置」同一条降级路径。
    blocked = budget_blocked(ROLE_COMPACT)
    if blocked:
        logger.warning(f"⚠️ [Compact] 群 {group_id} 跳过压缩：已被预算拦下（{blocked}）")
        return False

    bounds = sc.pending_bounds(group_id, tail_start_id)
    if bounds is None:
        return False
    low_id, high_id = bounds

    messages, max_id, count = fetch_pending_messages(
        group_id, low_id, high_id, sc.compact_message_limit()
    )
    if count == 0:
        # 区间内全是空内容消息：直接跳过，避免反复重试
        if max_id > low_id:
            sc.skip_range(group_id, max_id, 0)
        return False

    if not sc.should_compact(messages):
        return False

    existing = sc.get_summary(group_id)
    prompt = build_compact_prompt(messages, existing)
    logger.info(f"🗜️ [Compact] 群 {group_id} 开始压缩 {count} 条消息（至 id {max_id}）")

    backend = _get_backend()
    if backend is None:
        logger.warning(
            f"⚠️ [Compact] 群 {group_id} 跳过压缩：COMPACT 角色没有可用端点"
            "（LLM_ROLE_COMPACT_ENDPOINT 指向的槽未配 BASE_URL）。"
            "运行 python -m deploy doctor 查看解析结果。"
        )
        return False

    try:
        async with acquire(gate_of(ROLE_COMPACT), tag=f"compact:{group_id}"):
            result = await backend.generate(prompt)
    except Exception as e:
        # 调用失败**不推进**位置，这批消息留待下次重试
        logger.warning(f"⚠️ [Compact] 群 {group_id} 压缩失败（保留待重试）: {e}")
        return False

    if _is_empty_result(result):
        # 模型判定无可摘要内容：推进位置但保留旧摘要，
        # 与调用失败区别对待，否则噪音消息会永远堆在待压缩区间
        sc.skip_range(group_id, max_id, count)
        return True

    sc.apply_summary(group_id, result, max_id, count)
    return True


def schedule_compact(group_id: int, tail_start_id: int) -> None:
    """在后台异步触发一次压缩（不等待）。

    压缩放在回复发出**之后**：不阻塞当前回复，摘要从下一轮开始生效。
    同一群不并发压缩——两次调用会基于同一起点各自推进，导致重复或跳过。
    """
    if group_id in _in_flight:
        logger.debug(f"[Compact] 群 {group_id} 已有压缩任务在跑，跳过本次触发")
        return

    async def _run() -> None:
        _in_flight.add(group_id)
        try:
            await compact_once(group_id, tail_start_id)
        except Exception:
            logger.exception(f"❌ [Compact] 群 {group_id} 压缩任务异常")
        finally:
            _in_flight.discard(group_id)

    task = asyncio.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def reset_state() -> None:
    """清空进程内状态（供测试使用）。"""
    global _backend
    _backend = None
    _in_flight.clear()
