# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""聊天主处理管线。

Pipeline 定义了一次聊天消息的标准处理流程：先按优先级执行前置钩子（pre-hook，
常用于权限校验、主动发言判定、短路等），随后调用 LLM 后端生成回复，最后执行
后置钩子（post-hook，如输出解析、回复格式化、落库）。通过注册钩子与替换 LLM
后端，插件可以在不修改管线本体的情况下扩展行为。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from nonebot import logger

from config import MEMORY_V2_ENABLED
from core.context import ChatContext
from core.llm import PRIORITY_INTERACTIVE, RESOURCE_CHAT, acquire
from core.llm.base import LLMBackend

PreHook = Callable[[ChatContext], Awaitable[ChatContext | None]]
PostHook = Callable[[ChatContext], Awaitable[ChatContext | None]]

# 这些 intent 下 ctx.message 是**任务指令**而非用户输入，必须放在上下文之前。
# 否则模型会把上下文尾部的最近对话当成「当前要回应的内容」，转而去接那句话
# 而不是执行指令（2026-08-13 接错话 bug 的变体）。
_INSTRUCTION_INTENTS = frozenset({"proactive_at"})


def _compose_prompt(context_text: str, ctx: ChatContext) -> str:
    """把上下文段落与 ctx.message 按正确顺序拼成最终 user prompt。

    普通对话：上下文 → 当前输入。当前输入必须**显式标记**——它被拼在尾巴
    之后只是一行裸文本，模型无从判断其特殊地位，会转而回应尾巴里信号更强的
    话题（2026-08-16 实测：用户说「要玩应该先去玩边狱」，Bot 回了尾巴里
    别人在聊的周边毛绒玩偶）。

    指令型（见 _INSTRUCTION_INTENTS）：指令 → 上下文（上下文只是语气素材，
    不是待回应的内容）。
    """
    context_text = context_text or ""
    if ctx.intent in _INSTRUCTION_INTENTS:
        return f"{ctx.message}\n\n{context_text}" if context_text else ctx.message
    if not context_text:
        return ctx.message
    speaker = f"用户({ctx.user_id})" if ctx.user_id else "对方"
    return (
        f"{context_text}\n\n"
        f"【现在 {speaker} 对你说】{ctx.message}\n"
        f"请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。"
    )


class Pipeline:
    """主处理管线：把"钩子 + LLM 后端"组装成一条可复用的消息处理链路。

    使用方式：
        pipeline = Pipeline(timeout=90.0)
        pipeline.register_pre_hook(...)
        pipeline.register_post_hook(...)
        pipeline.set_llm_backend(backend)
        ctx = await pipeline.run(ctx)

    钩子按优先级（数字越大越先执行）排序；LLM 调用经调度器
    acquire(RESOURCE_CHAT) 串行访问共享的本地模型后端。
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
        for _, hook in self._pre_hooks:
            result = await hook(ctx)
            if result is not None:
                ctx = result

        # 钩子已生成回复（如重复消息去重、主动发言已被处理），无需再调 LLM
        if ctx.reply:
            return ctx

        if self._llm:
            user_prompt = ctx.message
            # 使用 structured context 经 memory.prompt_builder 构建更自然的 prompt
            if MEMORY_V2_ENABLED:
                # v2：分区注入（聊天素材 / 行为约束分离），并附带决策轨迹
                from memory.prompt_builder import build_v2_prompt_context

                user_prompt = _compose_prompt(
                    build_v2_prompt_context(
                        getattr(ctx, "short_term", "") or "",
                        getattr(ctx, "user_profile", "") or "",
                        getattr(ctx, "conversation_memories", []) or [],
                        getattr(ctx, "behavior_constraints", []) or [],
                        current_user_id=ctx.user_id,
                        mode=getattr(ctx, "memory_mode", "CASUAL_REPLY") or "CASUAL_REPLY",
                    ),
                    ctx,
                )
            else:
                from memory.prompt_builder import build_prompt_context

                short_term = getattr(ctx, "short_term", "") or ""
                user_profile = getattr(ctx, "user_profile", "") or ""
                memories_for_prompt = getattr(ctx, "memories_for_prompt", []) or []
                user_prompt = _compose_prompt(
                    build_prompt_context(
                        short_term,
                        user_profile,
                        memories_for_prompt,
                        current_user_id=ctx.user_id,
                    ),
                    ctx,
                )

            # 记录 LLM 诊断信息，供 thought 日志追溯该次调用用了哪个后端/模型
            ctx.llm_backend = getattr(self._llm, "backend_name", type(self._llm).__name__)
            ctx.llm_model = getattr(self._llm, "model", "") or getattr(self._llm, "site", "")
            ctx.system_prompt_len = len(self.system_prompt)
            ctx.prompt_log = user_prompt

            # 全局闸门：聊天主链路与压缩/候选提取共用同一 27B，经调度器 FIFO 串行。
            # 交互回复标记为高优先级意图（当前优先级未启用，仅按 FIFO 处理）。
            async with acquire(
                RESOURCE_CHAT, tag=f"reply:{ctx.group_id}", priority=PRIORITY_INTERACTIVE
            ):
                import time as _time
                _t0 = _time.monotonic()
                try:
                    raw = await asyncio.wait_for(
                        self._llm.generate(user_prompt, self.system_prompt),
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

        # 记忆系统 v2：记录本次回复的记忆决策轨迹（候选/过滤/最终/拒绝）
        if MEMORY_V2_ENABLED:
            try:
                from memory.trace import record_trace

                conv = getattr(ctx, "conversation_memories", []) or []
                behavior = getattr(ctx, "behavior_constraints", []) or []
                trace = getattr(ctx, "memory_trace", {}) or {}
                record_trace(
                    group_id=ctx.group_id,
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

        for _, hook in self._post_hooks:
            result = await hook(ctx)
            if result is not None:
                ctx = result

        return ctx
