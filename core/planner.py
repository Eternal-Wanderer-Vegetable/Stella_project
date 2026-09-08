# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""受限 Planner（《Stella 拟人化插话与低成本运行改进方案 v1.0》阶段五）。

深度回复路径的编排器。绝大多数消息不经过这里——本地零 LLM 的
``detect_trigger`` 判定命中才启动（设计第 7 节的启动条件）：

- 历史指代 / 需要旧事件或 Episode：消息包含「上次/之前/还记得」类指涉，
  尾巴里的短期上下文大概率不够，允许 Planner 发起一次深度记忆查询；
- 当前话题存在歧义：极短消息 + 指代词（「那个怎么样了」），单次快速
  检索拿到的记忆容易接错对象；
- 高插话机会但表达方式不明确：主动插话时是否「现在说」交给 Planner
  判定（PLANNER_PROACTIVE_WAIT_ENABLED，默认关，见 settings 注释）；
- 需要等待更多消息：Planner 输出 WAIT——只标记 TurnRuntime 进入 WAITING，
  **不轮询 LLM**，后续消息事件自然重新驱动整条链路；
- 需要工具：**不在 Planner 职责内**。Capability Router → Comes 已在每条
  消息上独立判定与执行（capability/hooks.py），结果经 tool_summaries 压缩
  回填，Planner 不重复派发。

硬限制（设计第 7 节，全部程序化强制）：

    普通路径：最多 1 次 LLM（不经过本模块）
    深度路径：最多 2 次 LLM（Planner 1 次 + Replyer 1 次）
    每轮最多 1 次深度记忆查询（本地 SQLite，零 LLM）
    Planner 最多 2 轮（PLANNER_MAX_ROUNDS；LLM 名额先耗尽则更少）
    wait 不轮询 LLM
    工具结果必须压缩后回填（_compress_memories，进 ctx.tool_summaries）

``query_memory`` 优先调用 Stella 本地检索（memory/retrieval_v2），工具只
返回压缩后的事实、时间、参与者、置信度——延迟导入，core 不在 import 期
依赖 memory（与 core/pipeline.py 同一惯例）。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from nonebot import logger

from config import (
    PLANNER_CONTEXT_MAX_TOKENS,
    PLANNER_ENABLED,
    PLANNER_MAX_LLM_CALLS_PER_TURN,
    PLANNER_MAX_ROUNDS,
    PLANNER_MAX_TOOL_CALLS_PER_TURN,
    PLANNER_PROACTIVE_WAIT_ENABLED,
    PLANNER_QUERY_MEMORY_MAX_LINES,
    PLANNER_TIMEOUT,
)
from core.context import ChatContext
from core.context_budget import estimate_tokens, fit_prompt_to_window
from core.llm import PRIORITY_INTERACTIVE, ROLE_CHAT, acquire, gate_of
from core.llm.base import LLMBackend
from core.llm.usage_store import budget_blocked

# 这些 intent 下 ctx.message 是任务指令而非用户内容（见 core/pipeline.py 的
# _INSTRUCTION_INTENTS），对指令文本做指代/歧义分析只会误触发。
_INSTRUCTION_INTENTS = frozenset({"proactive_at"})

# ── 本地触发判定（零 LLM） ──
# 历史指代/旧事件：命中即认为尾巴内的短期上下文可能不够，允许一次深度检索。
_HISTORY_REFERENCE = re.compile(
    r"上次|上回|之前|刚才|前几天|那天|以前|当时|还记得|记得|说过|讲过|提过|聊过"
)
# 话题歧义：极短 + 指代/追问词，缺少可检索的实词。
_AMBIGUOUS_MAX_CHARS = 12
_DEIXIS = re.compile(r"那个|这个|它|咋|怎么|什么意思|然后呢|后来呢|怎么样")


@dataclass(frozen=True)
class PlannerTrigger:
    """一次本地触发判定（kind 写进 ctx.planner_trigger 供日志追踪）。"""

    kind: str
    reason: str


def detect_trigger(message: str, *, trigger: str, intent: str = "") -> PlannerTrigger | None:
    """零 LLM 判定是否进入深度路径。返回 None 表示走快速路径。

    刻意保守：判错的代价是不必要的 1 次 Planner LLM（成本），漏判的代价是
    回复接错记忆（体验）——指代/歧义模式词优先保召回，其余一律放行快速路径。
    """
    if intent in _INSTRUCTION_INTENTS:
        return None
    text = (message or "").strip()
    if not text:
        return None
    if _HISTORY_REFERENCE.search(text):
        return PlannerTrigger("history_reference", "消息包含历史指代")
    if trigger == "proactive":
        if PLANNER_PROACTIVE_WAIT_ENABLED:
            return PlannerTrigger("proactive_unclear", "主动插话，表达时机交给 Planner 判定")
        return None
    if len(text) <= _AMBIGUOUS_MAX_CHARS and _DEIXIS.search(text):
        return PlannerTrigger("ambiguity", "极短消息+指代词，话题存在歧义")
    return None


# ── Planner 的固定 prompt（前缀稳定：系统提示词 + 固定动作表在前，动态在后） ──
PLANNER_SYSTEM_PROMPT = (
    "你是 Stella 的回复规划器。只做决策，不与用户对话。\n"
    "读取触发原因、最近对话与当前消息，从三个动作中选一个，严格按格式只输出一行：\n"
    "<action>REPLY</action> —— 现有上下文已足够，直接回复\n"
    "<action>QUERY_MEMORY: 检索词</action> —— 需要回忆更早的信息，给出 3~12 字的检索词\n"
    "<action>WAIT</action> —— 现在不适合说话，等后续消息（仅主动发言时有效）\n"
    "不要输出其他任何内容。"
)

_ACTION_RE = re.compile(
    r"<action>\s*(REPLY|QUERY_MEMORY|WAIT)\s*(?:[:：]\s*(?P<query>[^<]*?))?\s*</action>",
    re.IGNORECASE,
)


def parse_action(raw: str) -> tuple[str, str]:
    """解析 Planner 输出。返回 (动作, 检索词)；解析失败按 REPLY 处理（安全默认）。"""
    text = (raw or "").strip()
    if not text:
        return "REPLY", ""
    m = _ACTION_RE.search(text)
    if m:
        action = m.group(1).upper()
        return action, (m.group("query") or "").strip()
    # 容错：模型偶尔丢标签，只输出动作词
    for line in text.splitlines():
        line = line.strip()
        if line.upper().startswith("QUERY_MEMORY"):
            return "QUERY_MEMORY", line.split(":", 1)[-1].strip() if ":" in line else ""
        if line.upper().startswith(("REPLY", "WAIT")):
            return line.upper().split()[0], ""
    return "REPLY", ""


def _compress_memories(memories: list[dict]) -> str:
    """把深度检索结果压缩成进 prompt 的文本（验收项：工具结果必须压缩后回填）。

    每条一行，只保留：事实（截断）、时间、参与者、置信度。上限
    PLANNER_QUERY_MEMORY_MAX_LINES 行——这是「补充回忆」不是记忆倾倒。
    """
    lines: list[str] = []
    for mem in memories[: max(0, PLANNER_QUERY_MEMORY_MAX_LINES)]:
        content = (mem.get("content") or "").strip()
        if not content:
            continue
        if len(content) > 80:
            content = content[:80] + "…"
        when = (mem.get("last_confirmed_at") or mem.get("last_accessed_at") or "").strip()
        who = mem.get("user_id") or "群"
        try:
            confidence = f"{float(mem.get('confidence') or 0.0):.2f}"
        except (TypeError, ValueError):
            confidence = "?"
        lines.append(f"事实：{content}｜时间：{when or '未知'}｜参与者：用户{who}｜置信度：{confidence}")
    if not lines:
        return ""
    return "[深度记忆] " + "；".join(lines)


class RestrictedPlanner:
    """挂在 Pipeline 上的受限规划器（见模块 docstring 的硬限制）。"""

    def __init__(self, backend: LLMBackend, timeout: float = PLANNER_TIMEOUT):
        self._backend = backend
        self._timeout = timeout

    async def maybe_plan(self, ctx: ChatContext) -> ChatContext:
        """Pipeline 在回复 LLM 之前调用。只在本地触发命中时消耗 LLM 名额。"""
        if not PLANNER_ENABLED or self._backend is None:
            return ctx
        trig = detect_trigger(ctx.message, trigger=ctx.trigger, intent=ctx.intent)
        if trig is None:
            return ctx
        ctx.planner_trigger = trig.kind

        # 每日预算：与 handle_chat 同一判定，被拦时连 Planner 也不该花。
        if budget_blocked(ROLE_CHAT):
            return ctx

        for _ in range(max(1, PLANNER_MAX_ROUNDS)):
            # 给 Replyer 至少留 1 个名额；名额不足就不再规划。
            if ctx.llm_call_count >= PLANNER_MAX_LLM_CALLS_PER_TURN - 1:
                return ctx
            raw = await self._ask(ctx, trig)
            action, query = parse_action(raw)
            ctx.planner_action = action

            if action == "WAIT":
                # 仅主动路径可等：@ 是硬触发，不能被吞（ReplyGate 同一原则）。
                if ctx.trigger == "proactive":
                    ctx.planner_wait = True
                    logger.info(f"⏳ [Planner] 群 {ctx.group_id} 决定等待更多消息（{trig.reason}）")
                return ctx
            if action == "QUERY_MEMORY" and query:
                if ctx.deep_tool_calls < PLANNER_MAX_TOOL_CALLS_PER_TURN:
                    summary = self._query_memory(ctx, query)
                    if summary:
                        ctx.tool_summaries.append(summary)
                    ctx.deep_tool_calls += 1
                # 深度查询后直接进 Replyer（LLM 名额只剩 1），不再有第二轮规划。
                return ctx
            return ctx  # REPLY / 解析失败：安全默认，直接快速回复
        return ctx

    # ── 内部 ──

    def _build_prompt(self, ctx: ChatContext, trig: PlannerTrigger) -> str:
        """动态区：触发原因 + 最近对话摘要（截断）+ 当前消息。"""
        context = (getattr(ctx, "short_term", "") or "").strip()
        if context and estimate_tokens(context) > PLANNER_CONTEXT_MAX_TOKENS:
            keep = max(1, int(PLANNER_CONTEXT_MAX_TOKENS / 1.65))
            context = context[-keep:]
        speaker = f"用户({ctx.user_id})" if ctx.user_id else "（主动发言，无人提问）"
        parts = [
            f"触发原因：{trig.reason}",
            f"最近对话（背景，可能不完整）：\n{context}" if context else "最近对话：无",
            f"【现在 {speaker} 说】{ctx.message}",
            "请输出你的动作（一行）。",
        ]
        return "\n\n".join(p for p in parts if p)

    async def _ask(self, ctx: ChatContext, trig: PlannerTrigger) -> str:
        """一次 Planner LLM 调用：走 CHAT 闸门排队、过 ContextBudget、计名次。"""
        prompt = self._build_prompt(ctx, trig)
        budgeted = fit_prompt_to_window(prompt, PLANNER_SYSTEM_PROMPT)
        async with acquire(
            gate_of(ROLE_CHAT), tag=f"planner:{ctx.group_id}", priority=PRIORITY_INTERACTIVE
        ):
            try:
                ctx.llm_call_count += 1
                return await asyncio.wait_for(
                    self._backend.generate(budgeted.prompt, PLANNER_SYSTEM_PROMPT),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("⏳ [Planner] 规划超时，按直接回复处理")
                return "REPLY"
            except Exception as e:
                logger.warning(f"⚠️ [Planner] 规划调用失败，按直接回复处理: {e}")
                return "REPLY"

    def _query_memory(self, ctx: ChatContext, query: str) -> str:
        """一次深度记忆查询：优先本地检索（retrieval_v2），结果压缩后回填。

        检索词来自 Planner 的改写，与原始消息不同——Phase 3 的话题化缓存 key
        会自然落进新桶，不会复用快速路径按原文检索的结果。
        """
        try:
            from config.spaces import resolve_space
            from memory.retrieval_v2 import retrieve_memories

            space = ctx.group_shared_space or resolve_space(ctx.group_id)
            result = retrieve_memories(space, ctx.user_id, query, trigger=ctx.trigger)
            summary = _compress_memories(result.conversation_memories or [])
            if not summary:
                logger.info(f"🔍 [Planner] 深度查询无命中（检索词：{query!r}）")
            return summary
        except Exception as e:
            # 检索失败只损失补充记忆，不能拖垮整条回复链路
            logger.warning(f"⚠️ [Planner] query_memory 异常（跳过）: {e}")
            return ""
