# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBot 插件分发管道（按 priority 降序）。"""

from __future__ import annotations

import functools
import inspect
import logging
from typing import Any

from .events import AstrMessageEvent, MessageChain, MessageEventResult, build_event
from .exceptions import StellaCompatNotSupported
from .registry import EventType, star_handlers_registry, star_map

logger = logging.getLogger("astrbot_compat.pipeline")


def _passes_filters(handler_md: Any, event: AstrMessageEvent) -> bool:
    filters = getattr(handler_md, "event_filters", []) or []
    for f in filters:
        try:
            res = f.filter(event, None)
            if not res:
                return False
        except Exception as e:
            logger.warning(f"[pipeline] filter {f} 异常，已视为不命中: {e}")
            return False
    return True


def _build_params(handler_md: Any, event: AstrMessageEvent) -> tuple[dict[str, Any] | None, str | None]:
    """按 handler_params 顺序切分 __cmd_args__，返回 (params, error)。"""
    params_spec: dict[str, Any] = getattr(handler_md, "handler_params", {}) or {}
    if not params_spec:
        try:
            event.set_extra("parsed_params", {})
        except Exception:
            pass
        return {}, None
    try:
        rest: str = event.get_extra("__cmd_args__", "") or ""
    except Exception:
        rest = ""
    rest = rest.strip()
    try:
        from .filters import GreedyStr
    except Exception:
        GreedyStr = None  # type: ignore

    items = list(params_spec.items())
    result: dict[str, Any] = {}
    tokens: list[str] = rest.split() if rest else []
    token_idx = 0
    for idx, (pname, pinfo) in enumerate(items):
        if isinstance(pinfo, tuple):
            if len(pinfo) == 2:
                ann, default = pinfo
            else:
                ann, default = pinfo[0], pinfo[1]
        else:
            ann, default = None, inspect.Parameter.empty
        has_default = default is not inspect.Parameter.empty
        is_greedy = False
        if GreedyStr is not None and ann is GreedyStr:
            is_greedy = True
        elif isinstance(ann, str) and ann == "GreedyStr":
            is_greedy = True
        elif ann is not None and getattr(ann, "__name__", "") == "GreedyStr":
            is_greedy = True

        if is_greedy:
            if token_idx < len(tokens):
                val: Any = " ".join(tokens[token_idx:])
                token_idx = len(tokens)
            else:
                if has_default:
                    val = default
                else:
                    val = ""
            result[pname] = val
        else:
            if token_idx < len(tokens):
                raw = tokens[token_idx]
                token_idx += 1
                if ann is int:
                    try:
                        val = int(raw)
                    except Exception:
                        return None, f"参数 {pname} 需要为整数， got '{raw}'"
                elif ann is float:
                    try:
                        val = float(raw)
                    except Exception:
                        return None, f"参数 {pname} 需要为数字， got '{raw}'"
                else:
                    val = raw
                result[pname] = val
            else:
                if has_default:
                    result[pname] = default
                else:
                    return None, f"缺少必需参数 {pname}"
    try:
        event.set_extra("parsed_params", dict(result))
    except Exception:
        pass
    return result, None


async def _emit(event: AstrMessageEvent, r: Any) -> None:
    if r is None:
        return
    if isinstance(r, MessageEventResult):
        await event.send(r)
    elif isinstance(r, MessageChain):
        await event.send(r)
    elif isinstance(r, str):
        await event.send(MessageChain().message(r))
    elif isinstance(r, list):
        await event.send(r)
    elif hasattr(r, "chain"):
        try:
            await event.send(r)  # type: ignore[arg-type]
        except Exception as e:
            logger.debug(f"[pipeline] _emit 忽略未知类型 {type(r)}: {e}")
    else:
        logger.debug(f"[pipeline] _emit 忽略未知返回类型 {type(r)}: {r!r}")


async def _flush_result(event: AstrMessageEvent) -> None:
    r = event.get_result()
    if r is None:
        return
    event.clear_result()
    chain = getattr(r, "chain", None)
    if not chain:
        return
    await event.send(r)


async def _invoke(handler_md: Any, event: AstrMessageEvent, params: dict[str, Any]) -> Any:
    h = handler_md.handler
    func = h.func if isinstance(h, functools.partial) else h
    try:
        if inspect.isasyncgenfunction(func):
            async for r in h(event, **params):
                await _emit(event, r)
                await _flush_result(event)
        elif inspect.iscoroutinefunction(func):
            r = await h(event, **params)
            await _emit(event, r)
            await _flush_result(event)
        else:
            r = h(event, **params)
            if inspect.isawaitable(r):
                r = await r
                await _emit(event, r)
                await _flush_result(event)
            elif inspect.isasyncgen(r):
                async for rr in r:
                    await _emit(event, rr)
                    await _flush_result(event)
            else:
                await _emit(event, r)
                await _flush_result(event)
        # 兜住只 set_result 的写法
        await _flush_result(event)
    except Exception:
        raise


async def dispatch(nb_event: Any, bot: Any) -> bool:
    """主入口：OneBot 事件 -> AstrBot 插件分发，返回是否向用户产出了回应."""
    try:
        is_tome = nb_event.is_tome() if hasattr(nb_event, "is_tome") else False
        if not is_tome:
            return False
    except Exception:
        return False

    handlers = star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent)
    if not handlers:
        return False

    event = await build_event(nb_event, bot)

    if not event.is_at_or_wake_command:
        return False

    handled = False
    warned_pids: set[str] = set()

    for handler_md in handlers:
        if event.is_stopped():
            break
        # ⑦ 清理上一个 handler 残留的 __cmd_args__
        try:
            event.set_extra("__cmd_args__", "")
        except Exception:
            pass
        # 跳过指令组桩
        if handler_md.extras_configs.get("is_group_stub"):
            continue
        if not _passes_filters(handler_md, event):
            continue

        params, err = _build_params(handler_md, event)
        if err is not None:
            try:
                await event.send(MessageChain().message(f"参数错误：{err}"))
            except Exception:
                pass
            handled = True
            continue
        if params is None:
            continue

        pid = ""
        try:
            mp = getattr(handler_md, "handler_module_path", "")
            md = star_map.get(mp) if mp else None
            if md is not None:
                pid = md.plugin_id or mp
            else:
                pid = mp or getattr(handler_md, "handler_full_name", "")
        except Exception:
            pid = getattr(handler_md, "handler_full_name", "")

        try:
            await _invoke(handler_md, event, params)
            if getattr(event, "_has_send_oper", False):
                handled = True
            # ⑤ 显式 stop / should_call_llm(False) 也算接管
            if event.is_stopped() or event.should_call_llm() is False:
                handled = True
        except StellaCompatNotSupported as e:
            logger.warning(f"[astrbot_compat] 插件 {pid} 依赖大模型能力：{e}")
            try:
                from .context import _MODEL_DEPENDENT_PLUGINS

                _MODEL_DEPENDENT_PLUGINS.add(pid)
            except Exception:
                pass
            if pid not in warned_pids:
                warned_pids.add(pid)
                try:
                    await event.send(MessageChain().message("这个插件需要依赖大模型能力，Stella 暂不支持"))
                except Exception:
                    pass
            handled = True
        except Exception:
            logger.exception(f"[astrbot_compat] 插件 {pid} handler 执行异常")
        finally:
            # 防止残留 result 被下一个 handler 重复发出
            try:
                event.clear_result()
            except Exception:
                pass

    return handled
