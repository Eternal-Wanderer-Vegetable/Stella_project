# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBot 插件分发管道。

唤醒判定照搬上游 `WakingCheckStage`：对**每一条**消息都跑一遍 handler 的 filter，
任一 filter 组通过即视为唤醒。因此 `@filter.regex` / `@filter.event_message_type`
这类不依赖 @ 的监听器能正常工作，而 `CommandFilter` 自己会检查 `is_at_or_wake_command`。
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import json
import logging
from typing import Any

from .events import (
    AstrMessageEvent,
    MessageChain,
    MessageEventResult,
    ResultContentType,
    build_event,
)
from .exceptions import StellaCompatNotSupported
from .filters import CommandGroupFilter, PermissionTypeFilter
from .llm.entities import ProviderRequest
from .registry import EventType, StarHandlerMetadata, star_handlers_registry, star_map

logger = logging.getLogger("astrbot_compat.pipeline")


def _plugin_name(handler_md: StarHandlerMetadata) -> str:
    meta = star_map.get(handler_md.handler_module_path)
    if meta is not None and meta.name:
        return meta.name
    return handler_md.handler_module_path or handler_md.handler_full_name


def _plugin_id(handler_md: StarHandlerMetadata) -> str:
    meta = star_map.get(handler_md.handler_module_path)
    if meta is not None:
        return meta.plugin_id
    return handler_md.handler_module_path or handler_md.handler_full_name


async def _emit(event: AstrMessageEvent, r: Any) -> None:
    """把 handler 的返回值 / yield 值发出去。"""
    if r is None:
        return
    if isinstance(r, ProviderRequest):
        # 插件 yield 出 LLM 请求：交给 agent 执行（复刻上游 ProcessStage 的分流）
        event.set_extra("provider_request", r)
        await run_provider_request(event, r)
        return
    if isinstance(r, (MessageChain, str, list)):
        await event.send(r)
        return
    if hasattr(r, "chain"):
        await event.send(r)
        return
    logger.debug(f"[pipeline] 忽略未知返回类型 {type(r)}: {r!r}")


async def run_provider_request(event: AstrMessageEvent, req: ProviderRequest) -> bool:
    """执行一个 ProviderRequest，把模型回复发给用户。返回是否真的发了东西。

    钩子顺序照抄上游：OnWaitingLLMRequest → OnLLMRequest → (工具循环，内部触发
    OnAgentBegin / OnUsingLLMTool / OnLLMToolRespond / OnLLMResponse / OnAgentDone)
    → OnDecoratingResult。任一钩子里 stop_event() 都会中断。
    """
    from .llm.agent import call_event_hook, response_to_chain, run_tool_loop
    from .llm.manager import get_provider_manager

    provider = get_provider_manager().provider
    if provider is None:
        logger.warning("[pipeline] 插件请求 LLM，但 ASTRBOT_LLM_ENABLED=false")
        with contextlib.suppress(Exception):
            await event.send(MessageChain().message("插件需要大模型能力，但当前未启用"))
        return True

    if await call_event_hook(event, EventType.OnWaitingLLMRequestEvent):
        return True
    # 上游：req.conversation 存在时用它的历史作为上下文
    _apply_conversation_history(req)
    if await call_event_hook(event, EventType.OnLLMRequestEvent, req):
        return True

    try:
        resp = await run_tool_loop(provider, req, event)
    except StellaCompatNotSupported:
        raise
    except Exception as e:
        logger.exception("[pipeline] LLM 请求失败")
        with contextlib.suppress(Exception):
            await event.send(MessageChain().message(f"大模型请求失败：{e}"))
        return True

    if event.is_stopped():
        return True

    chain = response_to_chain(resp)
    if chain.chain:
        event.set_result(
            MessageEventResult(chain=list(chain.chain)).set_result_content_type(
                ResultContentType.LLM_RESULT,
            ),
        )
    if await call_event_hook(event, EventType.OnDecoratingResultEvent):
        return True
    await _flush_result(event)
    await _persist_conversation(event, req, resp)
    return True


def _apply_conversation_history(req: ProviderRequest) -> None:
    """挂了 conversation 时，用它的历史当上下文（上游 build_main_agent 的行为）。"""
    if req.conversation is None or req.contexts:
        return
    try:
        history = json.loads(req.conversation.history or "[]")
    except (ValueError, TypeError):
        history = []
    if isinstance(history, list):
        req.contexts = history


async def _persist_conversation(
    event: AstrMessageEvent,
    req: ProviderRequest,
    resp: Any,
) -> None:
    """把这一轮追加进 conversation。

    与上游一致：**没挂 conversation 就不落库**——插件自己 yield 的请求默认不带
    conversation，历史由插件自行管理。

    注意 `req.contexts` 在 run_tool_loop 里已经并入了本轮的用户消息，这里只补
    assistant 那条，别重复追加 prompt。
    """
    if req.conversation is None:
        return
    with contextlib.suppress(Exception):
        from .conversation import get_conversation_manager

        history = list(req.contexts or [])
        text = getattr(resp, "completion_text", "") or ""
        if text:
            history.append({"role": "assistant", "content": text})
        await get_conversation_manager().update_conversation(
            event.unified_msg_origin,
            req.conversation.cid,
            history=history,
        )


async def _flush_result(event: AstrMessageEvent) -> None:
    """把 handler 通过 set_result 挂上的结果发出去。"""
    r = event.get_result()
    if r is None:
        return
    event.clear_result()
    if not getattr(r, "chain", None):
        return
    await event.send(r)


async def _invoke(
    handler_md: StarHandlerMetadata,
    event: AstrMessageEvent,
    params: dict[str, Any],
) -> None:
    h = handler_md.handler
    func = h.func if isinstance(h, functools.partial) else h
    if inspect.isasyncgenfunction(func):
        async for r in h(event, **params):
            await _emit(event, r)
            await _flush_result(event)
    elif inspect.iscoroutinefunction(func):
        await _emit(event, await h(event, **params))
        await _flush_result(event)
    else:
        r = h(event, **params)
        if inspect.isawaitable(r):
            await _emit(event, await r)
        elif inspect.isasyncgen(r):
            async for rr in r:
                await _emit(event, rr)
                await _flush_result(event)
        else:
            await _emit(event, r)
    # 兜住只 set_result 不 yield 的写法
    await _flush_result(event)


async def _run_filters(
    handler_md: StarHandlerMetadata,
    event: AstrMessageEvent,
) -> tuple[bool, str | None]:
    """跑一个 handler 的全部 filter（AND）。

    返回 (是否通过, 需要回复给用户的提示)。提示非空时表示应中止整条事件。
    """
    permission_not_pass = False
    permission_raise_error = False
    for f in handler_md.event_filters:
        try:
            if isinstance(f, PermissionTypeFilter):
                if not f.filter(event, None):
                    permission_not_pass = True
                    permission_raise_error = f.raise_error
                continue
            if not f.filter(event, None):
                return False, None
        except Exception as e:
            # 上游把 filter 抛出的异常（多为参数校验失败）回显给用户并终止事件
            return False, f"插件 {_plugin_name(handler_md)}: {e}"
    if permission_not_pass:
        if not permission_raise_error:
            return False, None
        return False, (
            f"您(ID: {event.get_sender_id()})的权限不足以使用此指令。"
        )
    return True, None


def _is_group_stub(handler_md: StarHandlerMetadata) -> bool:
    if handler_md.extras_configs.get("is_group_stub"):
        return True
    return any(isinstance(f, CommandGroupFilter) for f in handler_md.event_filters)


async def collect_handlers(
    event: AstrMessageEvent,
) -> list[tuple[StarHandlerMetadata, dict[str, Any]]]:
    """按上游 WakingCheckStage 的语义挑出该事件应执行的 handler 及其参数。

    副作用：命中任一 handler 时把 `event.is_wake` 置 True；权限不足或 filter 抛错时
    会向用户发送提示并 `stop_event()`。
    """
    all_handlers = star_handlers_registry.get_handlers_by_event_type(
        EventType.AdapterMessageEvent,
        plugins_name=event.plugins_name,
    )
    logger.info(f"[pipeline_debug] collect_handlers message_str={event.message_str!r} total_handlers={len(all_handlers)} waiting_filters={len([h for h in all_handlers if h.event_filters])}")
    for h in all_handlers:
        logger.info(f"[pipeline_debug] handler={h.handler_full_name} filters={len(h.event_filters)} types={[type(f).__name__ for f in h.event_filters]}")
    activated: list[tuple[StarHandlerMetadata, dict[str, Any]]] = []
    for handler_md in all_handlers:
        if not handler_md.event_filters:
            continue
        event._extras.pop("parsed_params", None)
        passed, notice = await _run_filters(handler_md, event)
        logger.info(f"[pipeline_debug] filter handler={handler_md.handler_full_name} passed={passed} notice={notice!r}")
        if notice is not None:
            with contextlib.suppress(Exception):
                await event.send(MessageChain().message(notice))
            event.stop_event()
            return []
        if not passed:
            continue
        event.is_wake = True
        if _is_group_stub(handler_md):
            logger.info(f"[pipeline_debug] handler {handler_md.handler_full_name} is group stub, skipped")
            continue
        activated.append((handler_md, dict(event.get_extra("parsed_params", {}) or {})))
    event._extras.pop("parsed_params", None)
    logger.info(f"[pipeline_debug] activated={len(activated)} {[h.handler_full_name for h,_ in activated]}")
    return activated


async def dispatch(nb_event: Any, bot: Any) -> bool:
    """主入口：OneBot 事件 -> AstrBot 插件分发，返回是否已向用户产出回应。"""
    total = len(star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent))
    logger.info(f"[pipeline_debug] dispatch total_handlers={total} registry_len={len(star_handlers_registry)}")
    if not star_handlers_registry.get_handlers_by_event_type(
        EventType.AdapterMessageEvent,
    ):
        logger.info("[pipeline_debug] no handlers, return False")
        return False

    try:
        event = await build_event(nb_event, bot)
    except Exception as e:
        logger.warning(f"[pipeline] 构造事件失败: {e}")
        return False

    activated = await collect_handlers(event)
    if event.is_stopped():
        # 权限提示 / filter 报错已经回复过用户，视为已接管
        return True
    if not activated:
        return False

    handled = False
    warned_pids: set[str] = set()

    for handler_md, params in activated:
        if event.is_stopped():
            break
        event.set_extra("parsed_params", params)
        pid = _plugin_id(handler_md)
        try:
            await _invoke(handler_md, event, params)
            if event._has_send_oper or event.is_stopped() or event.call_llm is False:
                handled = True
        except StellaCompatNotSupported as e:
            logger.warning(f"[astrbot_compat] 插件 {pid} 依赖大模型能力：{e}")
            with contextlib.suppress(Exception):
                from .context import _MODEL_DEPENDENT_PLUGINS

                _MODEL_DEPENDENT_PLUGINS.add(pid)
            if pid not in warned_pids:
                warned_pids.add(pid)
                with contextlib.suppress(Exception):
                    await event.send(
                        MessageChain().message("这个插件需要依赖大模型能力，Stella 暂不支持"),
                    )
            handled = True
        except Exception:
            logger.exception(f"[astrbot_compat] 插件 {pid} handler 执行异常")
            await _notify_plugin_error(event, handler_md)
        finally:
            # 防止残留 result 被下一个 handler 重复发出
            with contextlib.suppress(Exception):
                event.clear_result()

    if handled:
        # 上游在 respond 阶段发完消息后触发这个钩子
        with contextlib.suppress(Exception):
            from .llm.agent import call_event_hook

            await call_event_hook(event, EventType.OnAfterMessageSentEvent)

    return handled


async def _notify_plugin_error(
    event: AstrMessageEvent,
    handler_md: StarHandlerMetadata,
) -> None:
    """触发 OnPluginErrorEvent 钩子，让插件有机会自行处理报错。"""
    import traceback

    hooks = star_handlers_registry.get_handlers_by_event_type(
        EventType.OnPluginErrorEvent,
    )
    if not hooks:
        return
    tb = traceback.format_exc()
    for hook in hooks:
        with contextlib.suppress(Exception):
            await _call_hook(
                hook,
                event,
                _plugin_name(handler_md),
                handler_md.handler_name,
                None,
                tb,
            )


async def _call_hook(hook: StarHandlerMetadata, *args: Any) -> None:
    """尽力而为地调用一个钩子：按其签名截断多余参数。"""
    h = hook.handler
    func = h.func if isinstance(h, functools.partial) else h
    try:
        sig = inspect.signature(func)
        # partial 已绑定 self，参数表要跳过它
        n = len(sig.parameters) - (1 if isinstance(h, functools.partial) else 0)
    except (TypeError, ValueError):
        n = len(args)
    call_args = args[: max(n, 0)]
    r = h(*call_args)
    if inspect.isasyncgen(r):
        async for _ in r:
            pass
    elif inspect.isawaitable(r):
        await r


async def emit_hook(event_type: EventType, *args: Any) -> None:
    """对外暴露的生命周期钩子触发入口（on_astrbot_loaded 等）。"""
    for hook in star_handlers_registry.get_handlers_by_event_type(event_type):
        try:
            await _call_hook(hook, *args)
        except Exception as e:
            logger.warning(f"[pipeline] 钩子 {hook.handler_full_name} 执行异常: {e}")
