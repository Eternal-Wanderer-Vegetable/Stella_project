# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Provider 抽象与 Stella 实现（对齐 astrbot.core.provider.provider）。"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from astrbot_compat.exceptions import StellaCompatNotSupported

from .entities import (
    LLMResponse,
    ProviderMeta,
    ProviderType,
    TokenUsage,
    ToolCallsResult,
)
from .message import to_openai_dict
from .tool import ToolSet

logger = logging.getLogger("astrbot_compat.llm.provider")


def _settings() -> Any:
    from config import settings

    return settings


class AbstractProvider:
    """Provider 抽象基类。"""

    def __init__(self, provider_config: dict) -> None:
        self.model_name = ""
        self.provider_config = provider_config or {}

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name

    def get_model(self) -> str:
        return self.model_name

    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            id=self.provider_config.get("id", "default"),
            model=self.get_model(),
            type=self.provider_config.get("type", "openai"),
            provider_type=ProviderType.CHAT_COMPLETION,
        )

    async def test(self) -> None:
        """探活。默认什么都不做。"""


class Provider(AbstractProvider):
    """对话型 Provider。"""

    def __init__(self, provider_config: dict, provider_settings: dict | None = None) -> None:
        super().__init__(provider_config)
        self.provider_settings = provider_settings or {}

    def get_current_key(self) -> str:
        return self.provider_config.get("key", [""])[0] if self.provider_config.get("key") else ""

    def get_keys(self) -> list[str]:
        return self.provider_config.get("key", [""]) or [""]

    def set_key(self, key: str) -> None:
        self.provider_config["key"] = [key]

    async def get_models(self) -> list[str]:
        raise NotImplementedError

    async def text_chat(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        extra_user_content_parts: list | None = None,
        tool_choice: str = "auto",
        request_max_retries: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        raise NotImplementedError

    async def text_chat_stream(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        tool_choice: str = "auto",
        request_max_retries: int | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMResponse, None]:
        # 上游用这个技巧保证基类方法本身就是异步生成器（否则类型不对）
        if False:  # pragma: no cover
            yield None  # type: ignore[misc]
        raise NotImplementedError

    async def pop_record(self, context: list) -> None:
        """弹掉最早的一对非 system 记录（上游用它做上下文裁剪）。"""
        removed = 0
        i = 0
        while i < len(context) and removed < 2:
            if context[i].get("role") == "system":
                i += 1
                continue
            context.pop(i)
            removed += 1


# ============================================================
# 非对话型 provider：只保留形状，方法抛 NotSupported
# ============================================================


class STTProvider(AbstractProvider):
    def __init__(self, provider_config: dict, provider_settings: dict | None = None) -> None:
        super().__init__(provider_config)
        self.provider_settings = provider_settings or {}

    async def get_text(self, audio_url: str) -> str:
        _ = audio_url
        raise StellaCompatNotSupported("STTProvider.get_text")


class TTSProvider(AbstractProvider):
    def __init__(self, provider_config: dict, provider_settings: dict | None = None) -> None:
        super().__init__(provider_config)
        self.provider_settings = provider_settings or {}

    def support_stream(self) -> bool:
        return False

    async def get_audio(self, text: str) -> str:
        _ = text
        raise StellaCompatNotSupported("TTSProvider.get_audio")


class EmbeddingProvider(AbstractProvider):
    async def get_embedding(self, text: str) -> list[float]:
        _ = text
        raise StellaCompatNotSupported("EmbeddingProvider.get_embedding")

    async def get_embeddings(self, text: list[str]) -> list[list[float]]:
        _ = text
        raise StellaCompatNotSupported("EmbeddingProvider.get_embeddings")

    def get_dim(self) -> int:
        raise StellaCompatNotSupported("EmbeddingProvider.get_dim")


class RerankProvider(AbstractProvider):
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list:
        _ = (query, documents, top_n)
        raise StellaCompatNotSupported("RerankProvider.rerank")


# ============================================================
# Stella 实现
# ============================================================


def _estimate_message_tokens(m: dict) -> int:
    """估算单条消息的 token 数。复用 memory 侧现成的估算器，不引新依赖。"""
    from memory.prompt_builder import estimate_tokens

    total = 0
    content = m.get("content")
    if isinstance(content, str):
        total += estimate_tokens(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                total += estimate_tokens(block.get("text", ""))
            else:
                # 图片块按经验值计，避免 base64 正文被当成文本估爆
                total += 800
    if m.get("tool_calls"):
        total += estimate_tokens(json.dumps(m["tool_calls"], ensure_ascii=False))
    return total + 4  # 每条消息的固定开销


def _estimate_messages_tokens(messages: list[dict]) -> int:
    return sum(_estimate_message_tokens(m) for m in messages)


def _estimate_tools_tokens(tools: list[dict]) -> int:
    from memory.prompt_builder import estimate_tokens

    return estimate_tokens(json.dumps(tools, ensure_ascii=False)) if tools else 0


def trim_messages(
    messages: list[dict],
    budget: int,
    reserved: int = 0,
) -> tuple[list[dict], int]:
    """把 messages 裁到预算内，返回 (裁剪后的消息, 丢弃条数)。

    规则与上游 `Provider.pop_record` 一致：**system 消息永不丢**，从最早的非
    system 消息开始**成对**丢弃；最后一条消息（当前这轮的用户输入）也保留，
    丢掉它请求就没意义了。

    成对丢而不是逐条丢，是为了别把一问一答拆散：只丢掉 user 会留下一句没有提问的
    assistant 回答，只丢掉带 tool_calls 的 assistant 更会让后面的 tool 消息变成
    孤儿——严格的 OpenAI 兼容服务端会直接 400。
    """
    limit = max(budget - reserved, 0)
    kept = list(messages)
    # 逐条成本只算一次：每轮重算整份消息会让长历史退化成 O(n²)
    costs = [_estimate_message_tokens(m) for m in kept]
    total = sum(costs)
    dropped = 0
    while total > limit:
        victims = [i for i, m in enumerate(kept[:-1]) if m.get("role") != "system"][:2]
        if not victims:
            break
        for i in reversed(victims):
            total -= costs.pop(i)
            kept.pop(i)
            dropped += 1
    return kept, dropped


class StellaChatProvider(Provider):
    """把 AstrBot 的 provider 契约接到 Stella 的本地模型上。

    刻意**不注入** Stella 的人格与记忆：插件的回复不该带 Stella 的语气，
    否则用户分不清是谁在说话。插件没给 system_prompt 时只注入一句最小的锚
    （ASTRBOT_LLM_SYSTEM_PROMPT），避免本地模型输出风格漂移。
    """

    def __init__(self, provider_config: dict | None = None) -> None:
        s = _settings()
        cfg = provider_config or {
            "id": "stella",
            "type": "openai_chat_completion",
            "api_base": s.ASTRBOT_LLM_BASE_URL,
            "key": [s.ASTRBOT_LLM_API_KEY] if s.ASTRBOT_LLM_API_KEY else [""],
        }
        super().__init__(cfg, {})
        self.model_name = s.ASTRBOT_LLM_MODEL

    def get_current_key(self) -> str:
        return _settings().ASTRBOT_LLM_API_KEY

    def set_key(self, key: str) -> None:
        self.provider_config["key"] = [key]

    async def get_models(self) -> list[str]:
        return [self.model_name] if self.model_name else []

    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            id="stella",
            model=self.get_model(),
            type="openai_chat_completion",
            provider_type=ProviderType.CHAT_COMPLETION,
        )

    # ---------- 组装 ----------

    def _resolve_system_prompt(self, system_prompt: str | None) -> str:
        """插件给了就用插件的；没给才注入插件专属人格；配置为空串则不发 system。"""
        if system_prompt:
            return system_prompt
        return _settings().ASTRBOT_LLM_SYSTEM_PROMPT

    async def _build_messages(
        self,
        *,
        prompt: str | None,
        image_urls: list[str] | None,
        contexts: list | None,
        system_prompt: str | None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None,
        extra_user_content_parts: list | None,
    ) -> list[dict]:
        from .entities import ProviderRequest

        messages: list[dict] = []
        sys_text = self._resolve_system_prompt(system_prompt)
        if sys_text:
            messages.append({"role": "system", "content": sys_text})

        for ctx in contexts or []:
            messages.append(to_openai_dict(ctx))

        if tool_calls_result:
            results = (
                [tool_calls_result]
                if isinstance(tool_calls_result, ToolCallsResult)
                else list(tool_calls_result)
            )
            for r in results:
                messages.extend(r.to_openai_messages())

        if prompt or image_urls or extra_user_content_parts:
            req = ProviderRequest(
                prompt=prompt,
                image_urls=list(image_urls or []),
                extra_user_content_parts=list(extra_user_content_parts or []),
            )
            messages.append(await req.assemble_context())
        return messages

    def _prepare_tools(self, func_tool: ToolSet | None) -> list[dict] | None:
        if not func_tool or func_tool.empty():
            return None
        s = _settings()
        tools = [t for t in func_tool.tools if t.active]
        if len(tools) > s.ASTRBOT_LLM_MAX_TOOLS:
            logger.warning(
                f"[astrbot_llm] 工具数 {len(tools)} 超过 ASTRBOT_LLM_MAX_TOOLS="
                f"{s.ASTRBOT_LLM_MAX_TOOLS}，已截断。被丢弃："
                f"{[t.name for t in tools[s.ASTRBOT_LLM_MAX_TOOLS:]]}",
            )
            tools = tools[: s.ASTRBOT_LLM_MAX_TOOLS]
        return [t.openai_schema() for t in tools] or None

    def _apply_budget(self, messages: list[dict], tools: list[dict] | None) -> list[dict]:
        s = _settings()
        tool_cost = _estimate_tools_tokens(tools or [])
        reply_budget = s.ASTRBOT_LLM_MAX_TOKENS
        kept, dropped = trim_messages(
            messages,
            s.ASTRBOT_LLM_MAX_CONTEXT_TOKENS,
            reserved=tool_cost + reply_budget,
        )
        est = _estimate_messages_tokens(kept) + tool_cost
        if dropped:
            logger.warning(
                f"[astrbot_llm] 上下文超预算，已丢弃最早的 {dropped} 条非 system 消息"
                f"（上限 {s.ASTRBOT_LLM_MAX_CONTEXT_TOKENS}，工具占 {tool_cost}，"
                f"回复预留 {reply_budget}）",
            )
        logger.info(
            f"[astrbot_llm] 请求估算 {est} token"
            f"（消息 {len(kept)} 条，工具 {len(tools or [])} 个）",
        )
        return kept

    # ---------- 调用 ----------

    async def text_chat(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        extra_user_content_parts: list | None = None,
        tool_choice: str = "auto",
        request_max_retries: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        _ = (audio_urls, request_max_retries)
        if audio_urls:
            logger.warning("[astrbot_llm] 暂不支持音频输入，已忽略 audio_urls")
        messages = await self._build_messages(
            prompt=prompt,
            image_urls=image_urls,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
            extra_user_content_parts=extra_user_content_parts,
        )
        tools = self._prepare_tools(func_tool)
        messages = self._apply_budget(messages, tools)
        raw = await self._request(messages, tools, tool_choice, model, session_id, kwargs)
        return _response_from_raw(raw)

    async def text_chat_stream(
        self,
        prompt: str | None = None,
        session_id: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        func_tool: ToolSet | None = None,
        contexts: list | None = None,
        system_prompt: str | None = None,
        tool_calls_result: ToolCallsResult | list[ToolCallsResult] | None = None,
        model: str | None = None,
        tool_choice: str = "auto",
        request_max_retries: int | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[LLMResponse, None]:
        """流式输出。最后一次 yield 是完整结果（与上游一致）。"""
        _ = (audio_urls, request_max_retries)
        from core.llm import PRIORITY_INTERACTIVE, RESOURCE_CHAT, acquire
        from core.llm.openai_client import chat_completion_stream

        messages = await self._build_messages(
            prompt=prompt,
            image_urls=image_urls,
            contexts=contexts,
            system_prompt=system_prompt,
            tool_calls_result=tool_calls_result,
            extra_user_content_parts=None,
        )
        tools = self._prepare_tools(func_tool)
        messages = self._apply_budget(messages, tools)
        s = _settings()

        buffer = ""
        async with acquire(
            RESOURCE_CHAT,
            tag=f"plugin-llm-stream:{session_id or '-'}",
            priority=PRIORITY_INTERACTIVE,
        ):
            async for chunk in chat_completion_stream(
                messages,
                base_url=s.ASTRBOT_LLM_BASE_URL,
                model=model or self.model_name,
                api_key=s.ASTRBOT_LLM_API_KEY,
                tools=tools,
                tool_choice=tool_choice,
                temperature=s.ASTRBOT_LLM_TEMPERATURE,
                max_tokens=s.ASTRBOT_LLM_MAX_TOKENS,
                extra_body=kwargs.get("extra_body"),
            ):
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or ""
                if not piece:
                    continue
                buffer += piece
                yield LLMResponse(role="assistant", completion_text=piece, is_chunk=True)
        yield LLMResponse(role="assistant", completion_text=buffer, is_chunk=False)

    async def _request(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        tool_choice: str,
        model: str | None,
        session_id: str | None,
        kwargs: dict,
    ) -> dict:
        """经调度器排队后发请求。

        走 chat 闸门是硬要求：本地只有一块 GPU，主聊天 / 记忆压缩 / 插件调用
        必须 FIFO 串行，否则插件一调用就和主对话抢显存。
        """
        from core.llm import PRIORITY_INTERACTIVE, RESOURCE_CHAT, acquire
        from core.llm.openai_client import chat_completion

        s = _settings()
        async with acquire(
            RESOURCE_CHAT,
            tag=f"plugin-llm:{session_id or '-'}",
            priority=PRIORITY_INTERACTIVE,
        ):
            return await chat_completion(
                messages,
                base_url=s.ASTRBOT_LLM_BASE_URL,
                model=model or self.model_name,
                api_key=s.ASTRBOT_LLM_API_KEY,
                tools=tools,
                tool_choice=tool_choice,
                temperature=s.ASTRBOT_LLM_TEMPERATURE,
                max_tokens=s.ASTRBOT_LLM_MAX_TOKENS,
                extra_body=kwargs.get("extra_body"),
            )


def _response_from_raw(raw: dict) -> LLMResponse:
    """把 OpenAI 原始响应解成 LLMResponse。"""
    choice = (raw.get("choices") or [{}])[0]
    msg = choice.get("message") or {}

    names: list[str] = []
    args: list[dict] = []
    ids: list[str] = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        names.append(fn.get("name", ""))
        raw_args = fn.get("arguments") or "{}"
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except ValueError:
            logger.warning(f"[astrbot_llm] 工具参数不是合法 JSON，按空参处理: {raw_args!r}")
            parsed = {}
        args.append(parsed)
        ids.append(tc.get("id", ""))

    usage_raw = raw.get("usage") or {}
    usage = TokenUsage(
        input_other=usage_raw.get("prompt_tokens", 0) or 0,
        output=usage_raw.get("completion_tokens", 0) or 0,
    )
    return LLMResponse(
        role=msg.get("role") or "assistant",
        completion_text=msg.get("content") or "",
        tools_call_name=names,
        tools_call_args=args,
        tools_call_ids=ids,
        reasoning_content=msg.get("reasoning_content"),
        raw_completion=raw,
        id=raw.get("id"),
        usage=usage,
    )


__all__ = [
    "AbstractProvider",
    "EmbeddingProvider",
    "Provider",
    "RerankProvider",
    "STTProvider",
    "StellaChatProvider",
    "TTSProvider",
    "trim_messages",
]
