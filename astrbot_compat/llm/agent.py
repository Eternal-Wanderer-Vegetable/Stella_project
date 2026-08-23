# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""工具调用循环与 LLM 生命周期钩子。

只复刻插件真正依赖的契约，不做上游那套（MCP / handoff / live mode / 后台任务）。
关键约定全部照抄上游，注释里标了出处，因为它们不直观：

- 工具函数收到的是 `(event, **已过滤的参数)`——模型可能给出 schema 里没有的参数，
  上游会丢弃多余的再调用。
- 工具返回 str → 回喂模型；返回 None → 把 event 上挂的结果直接发给用户，
  并告诉模型「无返回值或已直接回复」。
- `on_using_llm_tool` 收到的是**过滤后**的参数，`on_llm_tool_respond` 收到的是
  **未过滤**的，且触发前先 clear_result()。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

from astrbot_compat.registry import EventType, star_handlers_registry, star_map

from .entities import LLMResponse, ProviderRequest, ToolCallsResult
from .message import AssistantMessageSegment, ToolCallMessageSegment
from .tool import FunctionTool, ToolSet

logger = logging.getLogger("astrbot_compat.llm.agent")

NO_RETURN_NOTICE = "The tool has no return value, or has sent the result directly to the user."


# ============================================================
# 运行上下文（对齐 astrbot.core.agent.run_context / astr_agent_context）
# ============================================================


@dataclass
class AstrAgentContext:
    context: Any
    event: Any
    extra: dict[str, str] = field(default_factory=dict)

    # 允许插件写 AstrAgentContext[...]（上游泛型写法）
    def __class_getitem__(cls, _item: Any) -> Any:
        return cls


@dataclass
class ContextWrapper:
    context: Any
    messages: list = field(default_factory=list)
    tool_call_timeout: int = 120

    # 允许插件写 ContextWrapper[AstrAgentContext]（上游泛型写法）
    def __class_getitem__(cls, _item: Any) -> Any:
        return cls


AgentContextWrapper = ContextWrapper


class BaseAgentRunHooks:
    """插件可继承的 agent 钩子基类（上游形状）。"""

    async def on_agent_begin(self, run_context: ContextWrapper) -> None: ...

    async def on_tool_start(
        self,
        run_context: ContextWrapper,
        tool: FunctionTool,
        tool_args: dict | None,
    ) -> None: ...

    async def on_tool_end(
        self,
        run_context: ContextWrapper,
        tool: FunctionTool,
        tool_args: dict | None,
        tool_result: Any,
    ) -> None: ...

    async def on_agent_done(
        self,
        run_context: ContextWrapper,
        llm_response: LLMResponse,
    ) -> None: ...


# ============================================================
# 钩子分发
# ============================================================


async def call_event_hook(event: Any, hook_type: EventType, *args: Any) -> bool:
    """触发一类钩子。返回 True 表示事件已被终止，调用方应停止后续处理。

    与上游一致：钩子必须是 `async def`（异步生成器不行），异常吞掉只记日志。
    """
    for handler_md in star_handlers_registry.get_handlers_by_event_type(
        hook_type,
        plugins_name=getattr(event, "plugins_name", None),
    ):
        h = handler_md.handler
        func = h.func if isinstance(h, functools.partial) else h
        if not inspect.iscoroutinefunction(func):
            logger.warning(
                f"[astrbot_llm] 钩子 {handler_md.handler_full_name} 不是 async def，已跳过"
                "（上游要求钩子必须是协程函数）",
            )
            continue
        try:
            meta = star_map.get(handler_md.handler_module_path)
            logger.debug(
                f"hook({hook_type.name}) -> "
                f"{meta.name if meta else handler_md.handler_module_path}"
                f" - {handler_md.handler_name}",
            )
            await h(event, *args)
        except Exception:
            logger.exception(f"[astrbot_llm] 钩子 {handler_md.handler_full_name} 执行异常")
        if event.is_stopped():
            return True
    return False


# ============================================================
# 工具执行
# ============================================================


def _filter_args(tool: FunctionTool, raw_args: dict) -> dict:
    """丢掉 schema 里没声明的参数。

    上游行为：模型偶尔会编出多余参数，直接传给插件会 TypeError。
    只有带 handler 且声明了 properties 的工具才过滤（MCP 工具全量透传）。
    """
    if tool.handler is None:
        return dict(raw_args)
    expected = (tool.parameters or {}).get("properties") or {}
    if not expected:
        return dict(raw_args)
    valid = {k: v for k, v in raw_args.items() if k in expected}
    extra = set(raw_args) - set(valid)
    if extra:
        logger.debug(f"[astrbot_llm] 工具 {tool.name} 丢弃了多余参数: {sorted(extra)}")
    return valid


async def _drain(result: Any, event: Any) -> Any:
    """把 handler 的返回值归一成 str | None。异步生成器逐个消费。"""
    if inspect.isasyncgen(result):
        last = None
        async for item in result:
            if item is None:
                continue
            if isinstance(item, str):
                last = item
            else:
                # yield 出 MessageEventResult / MessageChain：挂到 event 上直接发
                event.set_result(item)
        return last
    if inspect.isawaitable(result):
        return await result
    return result


async def execute_tool(
    tool: FunctionTool,
    event: Any,
    args: dict,
    timeout: float,
) -> str:
    """执行一个工具，返回要回喂给模型的文本。"""
    try:
        if tool.handler is not None:
            call = tool.handler(event, **args)
        else:
            call = tool.call(ContextWrapper(context=event), **args)
        result = await asyncio.wait_for(_drain(call, event), timeout=timeout)
    # 必须写 asyncio.TimeoutError：Python 3.10 下它与内置 TimeoutError 是两个
    # 不相干的类（3.11 起才合并），写内置的会在 3.10 上漏接。
    except asyncio.TimeoutError:
        logger.warning(f"[astrbot_llm] 工具 {tool.name} 执行超时（{timeout}s）")
        return f"error: tool {tool.name} timed out after {timeout}s"
    except Exception as e:
        logger.exception(f"[astrbot_llm] 工具 {tool.name} 执行异常")
        return f"error: {e!s}"

    if isinstance(result, str) and result:
        return result
    return NO_RETURN_NOTICE


# ============================================================
# 主循环
# ============================================================


def _tool_message(call_id: str, name: str, content: str) -> ToolCallMessageSegment:
    return ToolCallMessageSegment(tool_call_id=call_id, name=name, content=content)


async def _flush_direct_result(event: Any) -> None:
    """工具没有返回值时，把它挂在 event 上的结果直接发给用户。"""
    result = event.get_result()
    if result is None or not getattr(result, "chain", None):
        return
    event.clear_result()
    await event.send(result)


async def run_tool_loop(
    provider: Any,
    req: ProviderRequest,
    event: Any,
    *,
    max_steps: int | None = None,
    tool_timeout: float | None = None,
    hooks: BaseAgentRunHooks | None = None,
) -> LLMResponse:
    """带工具调用的对话循环，返回最终的 LLMResponse。"""
    from config import settings

    steps = max_steps if max_steps is not None else settings.ASTRBOT_LLM_MAX_TOOL_STEPS
    timeout = tool_timeout if tool_timeout is not None else settings.ASTRBOT_LLM_TOOL_TIMEOUT
    run_context = ContextWrapper(
        context=AstrAgentContext(context=None, event=event),
        tool_call_timeout=int(timeout),
    )

    if hooks:
        await hooks.on_agent_begin(run_context)
    if await call_event_hook(event, EventType.OnAgentBeginEvent, run_context):
        return LLMResponse(role="assistant", completion_text="")

    tool_set: ToolSet | None = req.func_tool
    resp: LLMResponse = LLMResponse(role="assistant", completion_text="")

    # 把这一轮的用户输入先并进 contexts。
    # 必须在循环外做一次：工具调用后的第二轮如果还靠 prompt= 传，用户的问题就
    # 只剩下工具结果、原始提问会消失，模型会答非所问。
    if req.prompt or req.image_urls or req.extra_user_content_parts:
        req.contexts = [*(req.contexts or []), await req.assemble_context()]

    for _step in range(max(steps, 1)):
        resp = await provider.text_chat(
            session_id=req.session_id,
            func_tool=tool_set,
            contexts=req.contexts,
            system_prompt=req.system_prompt,
            tool_calls_result=req.tool_calls_result,
            model=req.model,
        )
        if not resp.tools_call_name:
            break
        if tool_set is None:
            logger.warning("[astrbot_llm] 模型请求调用工具，但本次请求没有带工具集")
            break

        blocks: list[ToolCallMessageSegment] = []
        for idx, name in enumerate(resp.tools_call_name):
            call_id = resp.tools_call_ids[idx] if idx < len(resp.tools_call_ids) else ""
            raw_args = resp.tools_call_args[idx] if idx < len(resp.tools_call_args) else {}
            tool = tool_set.get_tool(name)
            if tool is None:
                blocks.append(
                    _tool_message(
                        call_id,
                        name,
                        f"error: Tool {name} not found. Available tools are: "
                        f"{tool_set.names()}",
                    ),
                )
                continue

            valid = _filter_args(tool, raw_args or {})
            if hooks:
                await hooks.on_tool_start(run_context, tool, valid)
            # 上游：on_using_llm_tool 收到的是过滤后的参数
            await call_event_hook(event, EventType.OnUsingLLMToolEvent, tool, valid)

            content = await execute_tool(tool, event, valid, timeout)
            if content == NO_RETURN_NOTICE:
                await _flush_direct_result(event)

            if hooks:
                await hooks.on_tool_end(run_context, tool, raw_args, content)
            # 上游：触发前先 clear_result，且传的是未过滤的参数
            event.clear_result()
            await call_event_hook(
                event,
                EventType.OnLLMToolRespondEvent,
                tool,
                raw_args,
                content,
            )
            blocks.append(_tool_message(call_id, name, content))

        info = AssistantMessageSegment(
            content=resp.completion_text or None,
            tool_calls=resp.to_openai_tool_calls_model(),
        )
        req.append_tool_calls_result(ToolCallsResult(info, blocks))

        if event.is_stopped():
            break
    else:
        logger.warning(
            f"[astrbot_llm] 工具调用达到上限 {steps} 轮仍未收敛，停止循环",
        )

    await call_event_hook(event, EventType.OnLLMResponseEvent, resp)
    if hooks:
        await hooks.on_agent_done(run_context, resp)
    await call_event_hook(event, EventType.OnAgentDoneEvent, run_context, resp)
    return resp


def response_to_chain(resp: LLMResponse):
    """把 LLMResponse 转成可直接发送的 MessageChain。"""
    from astrbot_compat.events import MessageChain

    if resp.result_chain is not None:
        return resp.result_chain
    text = (resp.completion_text or "").strip()
    return MessageChain().message(text) if text else MessageChain()


__all__ = [
    "NO_RETURN_NOTICE",
    "AgentContextWrapper",
    "AstrAgentContext",
    "BaseAgentRunHooks",
    "ContextWrapper",
    "call_event_hook",
    "execute_tool",
    "response_to_chain",
    "run_tool_loop",
]
