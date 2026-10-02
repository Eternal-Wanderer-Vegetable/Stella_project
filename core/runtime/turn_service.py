# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""聊天轮次服务：从 ``Pipeline.run`` 提取的三个可独立测试阶段（迁移计划 M2）。

阶段划分（docs/plans/2026-09-27-gitnexus-plan-cortico-runtime-migration.md §6.2）：

- ``prepare_turn``：pre hooks → 直回短路 → Planner → 调用上限守卫 →
  记忆/工具/知识/技能注入与 prompt 组装 → 预算裁剪。产出 :class:`TurnPlan`，
  ``outcome`` 是有类型的结果（``generate | direct | silent | budget_limited``），
  **绝不**把「没有内容」补成兜底回复（WAIT 语义，PDG 约束）。
- ``generate_reply``：仅封装 LLM 闸门排队、单次 ``generate`` 与超时/异常兜底。
  Cortico 的 ResponseClient 经薄桥调用的就是这一层（不含整个 Pipeline）。
- ``finalize_turn``：记忆决策 trace 与后置 hooks（解析→过滤→分行→日志）。

行为与提取前逐分支一致；``tests/runtime/fixtures/legacy_traces/`` 的冻结
oracle 是回归基准（任何差异都说明提取破坏了行为）。旧 ``Pipeline`` 改为
本服务的兼容门面（``core/pipeline.py``），公开签名与注册接口不变。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from nonebot import logger

from config import MEMORY_V2_ENABLED, PLANNER_MAX_LLM_CALLS_PER_TURN
from core.context import ChatContext
from core.context_budget import fit_prompt_to_window
from core.llm import PRIORITY_INTERACTIVE, ROLE_CHAT, acquire, gate_of
from core.llm.base import LLMBackend

PreHook = Callable[[ChatContext], Awaitable[ChatContext | None]]
PostHook = Callable[[ChatContext], Awaitable[ChatContext | None]]

# 这些 intent 下 ctx.message 是**任务指令**而非用户输入，必须放在上下文之前。
# 否则模型会把上下文尾部的最近对话当成「当前要回应的内容」，转而去接那句话
# 而不是执行指令（2026-08-13 接错话 bug 的变体）。
_INSTRUCTION_INTENTS = frozenset({"proactive_at"})

# prepare 的有类型决策结果。budget_limited = 调用次数已达硬上限（结构保险分支，
# 正常装配下 Planner 会给回复留名额）；no_backend = 未装配 LLM（测试/降级）；
# 两者都仍会走 finalize（产出兜底 lines），与 silent（完全静默、跳过 finalize）
# 是不同结果——「empty/failure 与 silent 分离」的 PDG 约束。
GENERATE = "generate"
DIRECT = "direct"
SILENT = "silent"
BUDGET_LIMITED = "budget_limited"
NO_BACKEND = "no_backend"

# prepare 与 generate 之间传递最终 prompt 的 ctx 暂存键（每轮独立，避免共享
# 服务实例上的并发串扰）。仅进程内瞬态，不属于 ChatContext JSON 投影。
_PENDING_PROMPT_KEY = "_turn_pending_prompt"
_PENDING_SYSTEM_KEY = "_turn_pending_system_prompt"


def _flow_of(ctx: ChatContext):
    """消息流程 context（计划 §6.2）：未接入/已结束返回 None（全部空转）。"""
    try:
        from core.observability import message_flow

        found = message_flow.flow_of(ctx)
        return None if (found is None or found.ended) else found
    except Exception:
        return None


def _flow_span(fctx, node_id: str, **kw):
    try:
        from core.observability import message_flow

        return message_flow.span(fctx, node_id, **kw)
    except Exception:
        import contextlib

        return contextlib.nullcontext()


def _flow_decision(fctx, node_id: str, **kw) -> None:
    try:
        from core.observability import message_flow

        message_flow.decision(fctx, node_id, **kw)
    except Exception:
        pass


def _flow_hook_node(hook_name: str) -> str:
    """钩子名 → 语义节点 ID；未知扩展钩子给动态 ID（UI 标 unmapped）。"""
    try:
        from core.observability import flow_catalog

        mapped = flow_catalog.HOOK_NODE_IDS.get(hook_name)
        if mapped:
            return mapped
    except Exception:
        pass
    return f"hook.custom:{hook_name}"


def pending_system_prompt(ctx: ChatContext) -> str:
    """读取 prepare_turn 暂存的系统提示词（runtime facade 的生成 provider 用）。

    与暂存键同一通道：未经 prepare_turn 的 ctx（或 resolver 产出为空）返回空串。
    facade 的默认 provider 不经 generate_reply，靠它拿到经 system_prompt_resolver
    按空间解析过的那份系统提示词。
    """
    return str(getattr(ctx, _PENDING_SYSTEM_KEY, "") or "")


def _tool_result_section(ctx: ChatContext) -> str:
    """把 Comes 的结果摘要渲染成一个 prompt 段落；无结果返回空串。

    只吃 ``ctx.tool_summaries``（已压缩），**绝不碰 Result.data**。
    方案第 3.1 节说「工具描述会污染聊天上下文」——几千字的工具原始返回同样会，
    原样拼进来会把记忆与对话上下文一起挤出 8192 的工作窗口。

    措辞要点：明确标注这是**刚刚查到的真实数据**。不标注的话，模型会把它当成
    上下文里又一段别人说的话，进而复述、质疑甚至反驳它。
    """
    summaries = [s.strip() for s in (getattr(ctx, "tool_summaries", None) or []) if s and s.strip()]
    if not summaries:
        return ""
    if len(summaries) == 1:
        body = summaries[0]
    else:
        body = "\n".join(f"- {s}" for s in summaries)
    return f"【刚刚查到的信息（真实数据，回答时以此为准）】\n{body}"


def _knowledge_evidence_section(ctx: ChatContext) -> str:
    """把知识库证据渲染成带编号引用的 prompt 段落；无证据返回空串。

    与 ``_tool_result_section`` 的分界（三轨分离，docs/knowledge-base.md）：
    证据只来自 ``ctx.knowledge_evidence``，渲染前先过**证据专属预算**
    （``fit_evidence_to_budget``：条数 + token 双上限），不占工具摘要的预算，
    也不受工具摘要的影响。

    引用形态：``[1]《标题》 节路径 > ¶段（资料库:名）``。编号让 Stella 能在
    回复里注明出处（"据《运维手册》[1]……"），这是引用式注入的意义——
    给答案，同时给答案的来源。
    """
    from config import KNOWLEDGE_EVIDENCE_MAX_ITEMS, KNOWLEDGE_EVIDENCE_MAX_TOKENS
    from core.context_budget import fit_evidence_to_budget

    evidence = getattr(ctx, "knowledge_evidence", None) or []
    if not evidence:
        return ""
    budgeted = fit_evidence_to_budget(
        evidence,
        max_items=int(KNOWLEDGE_EVIDENCE_MAX_ITEMS),
        max_tokens=int(KNOWLEDGE_EVIDENCE_MAX_TOKENS),
    )
    if not budgeted:
        return ""
    blocks: list[str] = []
    for idx, item in enumerate(budgeted, start=1):
        citation = str(item.get("citation") or item.get("doc_title") or "资料库摘录")
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        blocks.append(f"[{idx}] {citation}\n{text}")
    if not blocks:
        return ""
    return (
        "【资料库检索结果（真实文档摘录，回答时可引用并在句末标注 [编号]）】\n"
        + "\n\n".join(blocks)
    )


def _skill_result_section(ctx: ChatContext) -> str:
    """把 Skills 的结果摘要渲染成 prompt 段落；无结果返回空串。

    与 ``_tool_result_section`` 同一纪律（plan §6.3）：只吃
    ``ctx.skill_summaries``（编排器已压缩截断），**绝不**碰 SkillResult
    里的原始动作输出。产物只以 workspace 相对路径列出（供模型口头告知
    用户「生成了什么文件」），宿主路径从这里开始就不存在。
    """
    summaries = [s.strip() for s in (getattr(ctx, "skill_summaries", None) or []) if s and s.strip()]
    if not summaries:
        return ""
    body = "\n".join(f"- {s}" for s in summaries)
    artifacts = getattr(ctx, "skill_artifacts", None) or []
    artifact_lines = [
        f"  · {getattr(a, 'path', '')}" for a in artifacts if getattr(a, "path", "")
    ]
    if artifact_lines:
        body += "\n【本次生成的工作区文件】\n" + "\n".join(artifact_lines)
    return f"【技能执行结果（刚按说明书执行的真实结果）】\n{body}"


def _compose_prompt(context_text: str, ctx: ChatContext, social_text: str = "") -> str:
    """把上下文段落与 ctx.message 按正确顺序拼成最终 user prompt。

    ``social_text``（计划 §6.5 可选插槽）是带来源的低权限数据块：普通对话里
    紧挨知识证据（同为「回答这句话的证据」，离当前输入近）；指令型 intent
    里跟在任务指令之后（词义解释帮助理解指令）。为空时完全不参与拼接——
    既有 prompt 字节不变。

    普通对话：上下文 → 工具结果 → 知识证据 → 当前输入。当前输入必须**显式标记**
    ——它被拼在尾巴之后只是一行裸文本，模型无从判断其特殊地位，会转而回应
    尾巴里信号更强的话题（2026-08-16 实测：用户说「要玩应该先去玩边狱」，
    Bot 回了尾巴里别人在聊的周边毛绒玩偶）。

    指令型（见 _INSTRUCTION_INTENTS）：指令 → 工具结果 → 知识证据 → 上下文
    （上下文只是语气素材，不是待回应的内容）。

    工具结果与知识证据都是「回答这句话的证据」，必须离当前输入近；证据在后
    （离输入最近）：它带编号引用、是本轮最权威的素材。而「请回应这句话」的
    指令必须留在最后一行，否则模型会把它当成又一段背景而不是本次任务。
    """
    context_text = context_text or ""
    tool_text = _tool_result_section(ctx)
    knowledge_text = _knowledge_evidence_section(ctx)
    skill_text = _skill_result_section(ctx)
    if ctx.intent in _INSTRUCTION_INTENTS:
        parts = [ctx.message, tool_text, knowledge_text, skill_text, social_text, context_text]
        return "\n\n".join(p for p in parts if p)
    if not context_text and not tool_text and not knowledge_text and not skill_text and not social_text:
        return ctx.message
    speaker = f"用户({ctx.user_id})" if ctx.user_id else "对方"
    head = "\n\n".join(
        p for p in (context_text, tool_text, knowledge_text, skill_text, social_text) if p
    )
    return (
        f"{head}\n\n"
        f"【现在 {speaker} 对你说】{ctx.message}\n"
        f"请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。"
    )


@dataclass
class TurnPlan:
    """prepare_turn 的产出：带类型的轮次决策与更新后的上下文。"""

    ctx: ChatContext
    outcome: str  # GENERATE | DIRECT | SILENT | BUDGET_LIMITED


class TurnService:
    """把"钩子 + LLM 后端"组装成一条可复用的消息处理链路（三个阶段可独立调用）。

    使用方式：
        service = TurnService(timeout=90.0)
        service.register_pre_hook(...)
        service.register_post_hook(...)
        service.set_llm_backend(backend)
        ctx = await service.run(ctx)          # 完整轮次
        # 或分阶段：
        plan = await service.prepare_turn(ctx)
        if plan.outcome == GENERATE:
            ctx = await service.generate_reply(plan.ctx)
            ctx = await service.finalize_turn(ctx)

    钩子按优先级（数字越大越先执行）排序；LLM 调用经调度器
    acquire(gate_of(ROLE_CHAT)) 排队——纯本地时那把闸门并发度 1，即串行访问
    共享的本地模型后端。
    """

    def __init__(self, timeout: float = 90.0):
        """初始化管线。

        参数:
            timeout: 单次 LLM 生成的超时时间（秒），超时按异常兜底处理。
        """
        # 钩子以 (priority, callable) 二元组存放，便于按优先级稳定排序
        self._pre_hooks: list[tuple[int, PreHook]] = []
        self._post_hooks: list[tuple[int, PostHook]] = []
        self._llm: LLMBackend | None = None
        self._timeout = timeout
        self.system_prompt: str = ""
        self.system_prompt_resolver = None
        # 受限 Planner（设计阶段五）：None = 无深度路径（测试/降级装配）。
        self._planner: Any | None = None

    def set_planner(self, planner: Any) -> None:
        """挂上受限 Planner（core.planner.RestrictedPlanner 或测试替身）。

        类型刻意写 Any：core 不 import 具体实现（planner 依赖 config 的
        PLANNER_* 旋钮），只鸭子类型调用 ``await planner.maybe_plan(ctx)``。
        """
        self._planner = planner

    def register_pre_hook(self, hook: PreHook, priority: int = 10):
        """注册前置钩子，并按其优先级降序排列。

        参数:
            hook: 接收 ChatContext、返回新的/修改后的 ChatContext 的协程函数；
            priority: 越大越先执行。
        """
        self._pre_hooks.append((priority, hook))
        # 降序排序：priority 大的钩子先执行
        self._pre_hooks.sort(key=lambda x: x[0], reverse=True)

    def register_post_hook(self, hook: PostHook, priority: int = 10):
        """注册后置钩子，并按其优先级降序排列。

        参数:
            hook: 接收 ChatContext、返回新的/修改后的 ChatContext 的协程函数；
            priority: 越大越先执行。
        """
        self._post_hooks.append((priority, hook))
        # 降序排序：priority 大的钩子先执行
        self._post_hooks.sort(key=lambda x: x[0], reverse=True)

    def set_llm_backend(self, backend: LLMBackend):
        """设置管线使用的 LLM 后端实现。

        参数:
            backend: 实现了 LLMBackend.generate 的实例（本地或在线）。
        """
        self._llm = backend

    async def prepare_turn(self, ctx: ChatContext) -> TurnPlan:
        """阶段一：pre hooks、直回短路、Planner 与 prompt 组装/预算。

        返回的 :class:`TurnPlan` 说明本轮走向；``DIRECT`` 与 ``SILENT``
        表示轮次已经结束（不再生成、也不再 finalize），``BUDGET_LIMITED``
        表示跳过生成但仍需 finalize（与 legacy 的行为一致）。
        """
        fctx = _flow_of(ctx)
        with _flow_span(fctx, "prepare.hooks") as hooks_span:
            for _, hook in self._pre_hooks:
                hook_name = getattr(hook, "__name__", "hook")
                node_id = _flow_hook_node(hook_name)
                with _flow_span(fctx, node_id, parent=hooks_span,
                                instance_key=hook_name):
                    result = await hook(ctx)
                    if result is not None:
                        ctx = result

        # 钩子已生成回复（如重复消息去重、主动发言已被处理），无需再调 LLM
        if ctx.reply:
            _flow_decision(fctx, "prepare.direct", status="succeeded",
                           reason_code="hook_reply")
            return TurnPlan(ctx, DIRECT)

        # ── 受限 Planner（设计阶段五）：本地触发判定零 LLM，命中才进深度路径 ──
        # Planner 异常只能降级为快速路径（少几条补充记忆），不能吞掉回复。
        if self._planner is not None:
            try:
                ctx = await self._planner.maybe_plan(ctx)
            except Exception as e:
                logger.warning(f"[Planner] 规划异常（按快速路径继续）: {e}")
                _flow_decision(fctx, "planner.preflight", status="failed",
                               reason_code="planner_error")
            if getattr(ctx, "planner_wait", False):
                # WAIT：本轮不回复、不轮询 LLM，等后续消息事件重新驱动。
                logger.info(f"[Planner] 群 {ctx.group_id} 本轮等待更多消息，不回复")
                _flow_decision(fctx, "prepare.silent", status="skipped",
                               reason_code="planner_wait")
                return TurnPlan(ctx, SILENT)

        if not self._llm:
            _flow_decision(fctx, "prepare.backend_budget", status="blocked",
                           reason_code="no_backend")
            return TurnPlan(ctx, NO_BACKEND)

        # 深度路径 LLM 硬上限：Planner 消耗的名额从同一上限里扣。
        # 正常装配下 Planner 会给 Replyer 留 1 个名额，这里是结构保险。
        if ctx.llm_call_count >= PLANNER_MAX_LLM_CALLS_PER_TURN:
            logger.warning(
                f"[Planner] 本轮 LLM 调用已达上限 {PLANNER_MAX_LLM_CALLS_PER_TURN}，跳过回复生成"
            )
            _flow_decision(fctx, "prepare.backend_budget", status="blocked",
                           reason_code="call_budget")
            return TurnPlan(ctx, BUDGET_LIMITED)

        user_prompt = ctx.message
        context_text = ""
        # 使用 structured context 经 memory.prompt_builder 构建更自然的 prompt
        with _flow_span(fctx, "prompt.memory"):
            if MEMORY_V2_ENABLED:
                # v2：分区注入（聊天素材 / 行为约束分离），并附带决策轨迹
                from memory.prompt_builder import build_v2_prompt_context

                context_text = build_v2_prompt_context(
                    getattr(ctx, "short_term", "") or "",
                    getattr(ctx, "user_profile", "") or "",
                    getattr(ctx, "conversation_memories", []) or [],
                    getattr(ctx, "behavior_constraints", []) or [],
                    current_user_id=ctx.user_id,
                    mode=getattr(ctx, "memory_mode", "CASUAL_REPLY") or "CASUAL_REPLY",
                    preferred_address=getattr(ctx, "preferred_address", None),
                )
                user_prompt = _compose_prompt(context_text, ctx)
            else:
                from memory.prompt_builder import build_prompt_context

                short_term = getattr(ctx, "short_term", "") or ""
                user_profile = getattr(ctx, "user_profile", "") or ""
                memories_for_prompt = getattr(ctx, "memories_for_prompt", []) or []
                context_text = build_prompt_context(
                    short_term,
                    user_profile,
                    memories_for_prompt,
                    current_user_id=ctx.user_id,
                    preferred_address=getattr(ctx, "preferred_address", None),
                )
                user_prompt = _compose_prompt(context_text, ctx)

        # 记录 LLM 诊断信息，供 thought 日志追溯该次调用用了哪个后端/模型
        ctx.llm_backend = getattr(self._llm, "backend_name", type(self._llm).__name__)
        ctx.llm_model = getattr(self._llm, "model", "") or getattr(self._llm, "site", "")
        system_prompt = self.system_prompt
        if self.system_prompt_resolver is not None:
            system_prompt = self.system_prompt_resolver(ctx)
        # ── 社交插槽（计划 §6.5）：先有无学习基线，再按剩余预算放可选片段 ──
        # 可选学习先裁、不靠通用截断碰运气；任何异常退回基线（可选增强纪律）。
        with _flow_span(fctx, "prompt.parts", instance_key="social_slot"):
            try:
                from core.social.context_builder import (
                    build_social_block,
                    social_context_snapshot,
                )

                baseline_prompt = _compose_prompt(context_text, ctx)
                social_text, social_selection = build_social_block(
                    ctx, baseline_prompt=baseline_prompt, system_prompt=system_prompt
                )
                if social_text:
                    user_prompt = _compose_prompt(context_text, ctx, social_text=social_text)
                    ctx.social_context_snapshot = social_context_snapshot(social_selection)
            except Exception as e:
                logger.debug(f"[Social] 上下文插槽失败（按无学习基线继续）: {e}")

        with _flow_span(fctx, "prompt.fit"):
            budgeted = fit_prompt_to_window(user_prompt, system_prompt)
        _flow_decision(fctx, "prompt.fit", status="succeeded",
                       metrics={
                           "estimated_tokens": budgeted.estimated_tokens,
                           "budget_tokens": budgeted.budget_tokens,
                           "truncated": bool(budgeted.truncated),
                       })
        # 预算快照（计划 §6.5/§6.8）：实际裁掉的资产与原因 + 可重放输入档
        try:
            from core.observability import turn_trace

            turn_trace.record_event(
                trace_id=ctx.trace_id, turn_id=ctx.turn_id, stage="budget",
                status="ok",
                scope=f"qq:{ctx.group_id}",
                metrics={
                    "estimated_tokens": budgeted.estimated_tokens,
                    "budget_tokens": budgeted.budget_tokens,
                    "window_tokens": budgeted.window_tokens,
                    "truncated": budgeted.truncated,
                    "social_snapshot": bool(getattr(ctx, "social_context_snapshot", "")),
                },
                detailed={
                    "system_prompt": system_prompt,
                    "user_prompt": budgeted.prompt,
                    "budget_tokens": budgeted.budget_tokens,
                    "estimated_tokens": budgeted.estimated_tokens,
                    "context_window_tokens": budgeted.window_tokens,
                    "truncated": budgeted.truncated,
                    "social_snapshot": getattr(ctx, "social_context_snapshot", ""),
                }
                if turn_trace.detailed_enabled_for_scope(f"qq:{ctx.group_id}") else None,
            )
        except Exception:
            pass
        user_prompt = budgeted.prompt
        ctx.context_window_tokens = budgeted.window_tokens
        ctx.prompt_budget_tokens = budgeted.budget_tokens
        ctx.prompt_estimated_tokens = budgeted.estimated_tokens
        ctx.prompt_truncated = budgeted.truncated
        ctx.system_prompt_len = len(system_prompt)
        ctx.prompt_log = user_prompt
        setattr(ctx, _PENDING_PROMPT_KEY, user_prompt)
        setattr(ctx, _PENDING_SYSTEM_KEY, system_prompt)
        return TurnPlan(ctx, GENERATE)

    async def generate_reply(self, ctx: ChatContext) -> ChatContext:
        """阶段二：闸门排队 + 单次 generate + 超时/异常兜底。

        前置条件：``prepare_turn`` 返回 ``GENERATE``（最终 prompt 已按
        BC-6 与预算估算同源暂存在 ctx 上）。调用次数恰好 +1（含超时/异常路径）。
        """
        user_prompt = getattr(ctx, _PENDING_PROMPT_KEY)
        system_prompt = getattr(ctx, _PENDING_SYSTEM_KEY)

        # 闸门资源名 = CHAT 角色绑定的端点槽：纯本地部署下压缩/候选提取绑同一
        # 个槽，于是与主链路 FIFO 串行共用 27B；把它们分到不同端点后同一行
        # 代码自动变成并行。交互回复标记为高优先级意图（当前优先级未启用，
        # 仅按 FIFO 处理）。
        async with acquire(
            gate_of(ROLE_CHAT), tag=f"reply:{ctx.group_id}", priority=PRIORITY_INTERACTIVE
        ):
            import time as _time
            _t0 = _time.monotonic()
            try:
                ctx.llm_call_count += 1
                raw = await asyncio.wait_for(
                    self._llm.generate(user_prompt, system_prompt),
                    timeout=self._timeout,
                )
                ctx.llm_elapsed = _time.monotonic() - _t0
                ctx.raw_output = raw
            except asyncio.TimeoutError:
                # 超时兜底：产出"卡顿"回复而非崩溃，保证用户能得到反馈
                ctx.llm_elapsed = _time.monotonic() - _t0
                logger.error("LLM 执行超时")
                ctx.raw_output = "<thought>卡顿了一下</thought><action>NONE</action><reply>......？</reply>"
            except Exception as e:
                # 任何异常都回退到兜底回复，不让异常击穿整条消息链路
                ctx.llm_elapsed = _time.monotonic() - _t0
                logger.error(f"LLM 执行异常: {e}")
                ctx.raw_output = "<thought>系统异常</thought><action>NONE</action><reply>......？</reply>"
        return ctx

    async def finalize_turn(self, ctx: ChatContext) -> ChatContext:
        """阶段三：记忆决策 trace（V2）与后置 hooks。"""
        fctx = _flow_of(ctx)
        with _flow_span(fctx, "finalize.trace") as fin_span:
            await self._finalize_trace(ctx)
            ctx = await self._run_post_hooks(ctx, fctx, fin_span)
        return ctx

    async def _finalize_trace(self, ctx: ChatContext) -> None:
        # 记忆系统 v2：记录本次回复的记忆决策轨迹（候选/过滤/最终/拒绝）
        if MEMORY_V2_ENABLED:
            try:
                from memory.trace import record_trace

                conv = getattr(ctx, "conversation_memories", []) or []
                behavior = getattr(ctx, "behavior_constraints", []) or []
                trace = getattr(ctx, "memory_trace", {}) or {}
                record_trace(
                    group_id=ctx.group_id,
                    group_shared_space=getattr(ctx, "group_shared_space", ""),
                    user_id=ctx.user_id,
                    message=ctx.message,
                    mode=trace.get("mode") or getattr(ctx, "memory_mode", ""),
                    trigger=ctx.trigger,
                    candidates=[
                        {"id": cid} for cid in (trace.get("candidates") or [])
                    ],
                    final=conv,
                    behavior=behavior,
                    rejected=[
                        {"id": cid} for cid in (trace.get("rejected_ids") or [])
                    ],
                    prompt_snapshot=ctx.prompt_log,
                    output=ctx.raw_output,
                )
            except Exception as e:
                logger.debug(f"📊 [Pipeline] 记录决策追踪失败: {e}")

        return ctx

    async def _run_post_hooks(self, ctx: ChatContext, fctx, parent_span) -> ChatContext:
        """后置钩子链：优先级降序；每个钩子一个子 span（计划 §6.3 D）。"""
        for _, hook in self._post_hooks:
            hook_name = getattr(hook, "__name__", "hook")
            try:
                from core.observability import flow_catalog

                node_id = flow_catalog.POST_HOOK_NODE_IDS.get(hook_name)                     or f"hook.custom:{hook_name}"
            except Exception:
                node_id = f"hook.custom:{hook_name}"
            with _flow_span(fctx, node_id, parent=parent_span,
                            instance_key=hook_name):
                result = await hook(ctx)
                if result is not None:
                    ctx = result
        return ctx

    async def run(self, ctx: ChatContext) -> ChatContext:
        """对一次聊天执行完整管线，返回处理完成的上下文。

        参数:
            ctx: 处理起点，携带事件输入与当前状态；
        返回:
            处理后的 ChatContext；若前置钩子已填好 reply（如已被拦截/已回复）
            则提前返回，不再调用 LLM。

        指令型 intent（如 proactive_at：见 _INSTRUCTION_INTENTS）下 ctx.message
        是任务指令而非用户输入，会被 _compose_prompt 前置到上下文之前。
        """
        plan = await self.prepare_turn(ctx)
        if plan.outcome in (DIRECT, SILENT):
            # 直回与 WAIT：轮次立即结束，与 legacy 一致不执行后置 hooks
            return plan.ctx
        if plan.outcome in (BUDGET_LIMITED, NO_BACKEND):
            # 与 legacy 一致：跳过生成但仍执行 trace 与后置 hooks（split_lines
            # 会产出兜底 lines）。只有 budget 分支写 llm_backend（legacy 原样）。
            ctx = plan.ctx
            if plan.outcome == BUDGET_LIMITED:
                ctx.llm_backend = getattr(self._llm, "backend_name", type(self._llm).__name__)
            return await self.finalize_turn(ctx)
        ctx = await self.generate_reply(plan.ctx)
        return await self.finalize_turn(ctx)
