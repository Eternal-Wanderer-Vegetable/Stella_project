from __future__ import annotations

import asyncio
from typing import Callable, Optional, Awaitable
from nonebot import logger
from core.context import ChatContext
from core.llm.base import LLMBackend
from core.llm import chat_llm_lock


PreHook = Callable[[ChatContext], Awaitable[Optional[ChatContext]]]
PostHook = Callable[[ChatContext], Awaitable[Optional[ChatContext]]]


class Pipeline:
    def __init__(self, timeout: float = 90.0):
        self._pre_hooks: list[tuple[int, PreHook]] = []
        self._post_hooks: list[tuple[int, PostHook]] = []
        self._llm: Optional[LLMBackend] = None
        self._timeout = timeout
        self.system_prompt: str = ""

    def register_pre_hook(self, hook: PreHook, priority: int = 10):
        self._pre_hooks.append((priority, hook))
        self._pre_hooks.sort(key=lambda x: x[0], reverse=True)

    def register_post_hook(self, hook: PostHook, priority: int = 10):
        self._post_hooks.append((priority, hook))
        self._post_hooks.sort(key=lambda x: x[0], reverse=True)

    def set_llm_backend(self, backend: LLMBackend):
        self._llm = backend

    async def run(self, ctx: ChatContext) -> ChatContext:
        for _, hook in self._pre_hooks:
            result = await hook(ctx)
            if result is not None:
                ctx = result

        if ctx.reply:
            return ctx

        if self._llm:
            user_prompt = ctx.message
            # 使用 structured context 经 memory.prompt_builder 构建更自然的 prompt
            from memory.prompt_builder import build_prompt_context
            short_term = getattr(ctx, "short_term", "") or ""
            user_profile = getattr(ctx, "user_profile", "") or ""
            memories_for_prompt = getattr(ctx, "memories_for_prompt", []) or []
            user_prompt = build_prompt_context(short_term, user_profile, memories_for_prompt) + "\n" + ctx.message

            # 记录 LLM 诊断信息
            ctx.llm_backend = getattr(self._llm, "backend_name", type(self._llm).__name__)
            ctx.llm_model = getattr(self._llm, "model", "") or getattr(self._llm, "site", "")
            ctx.system_prompt_len = len(self.system_prompt)
            ctx.prompt_log = user_prompt

            async with chat_llm_lock:
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
                    ctx.llm_elapsed = _time.monotonic() - _t0
                    logger.error("LLM 执行超时")
                    ctx.raw_output = "<thought>卡顿了一下</thought><action>NONE</action><reply>......？</reply>"
                except Exception as e:
                    ctx.llm_elapsed = _time.monotonic() - _t0
                    logger.error(f"LLM 执行异常: {e}")
                    ctx.raw_output = "<thought>系统异常</thought><action>NONE</action><reply>......？</reply>"

        for _, hook in self._post_hooks:
            result = await hook(ctx)
            if result is not None:
                ctx = result

        return ctx
