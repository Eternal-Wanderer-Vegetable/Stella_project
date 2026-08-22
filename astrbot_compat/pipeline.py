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
            # 上游签名 filter(event, cfg)，cfg 传 None
            res = f.filter(event, None)
            if not res:
                return False
        except Exception as e:
            logger.warning(f"[pipeline] filter {f} 异常，已视为不命中: {e}")
            return False
    return True


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
        # 当 chain 发
        await event.send(r)
    elif hasattr(r, "chain"):
        # 兼容其它 MessageChain-like
        try:
            await event.send(r)  # type: ignore[arg-type]
        except Exception as e:
            logger.debug(f"[pipeline] _emit 忽略未知类型 {type(r)}: {e}")
    else:
        logger.debug(f"[pipeline] _emit 忽略未知返回类型 {type(r)}: {r!r}")


async def _invoke(handler_md: Any, event: AstrMessageEvent) -> Any:
    h = handler_md.handler
    # 对 partial 拆 func 判断 async
    func = h.func if isinstance(h, functools.partial) else h
    try:
        if inspect.isasyncgenfunction(func):
            async for r in h(event):
                await _emit(event, r)
        elif inspect.iscoroutinefunction(func):
            r = await h(event)
            await _emit(event, r)
        else:
            # 同步函数（可能返回 coroutine？）
            r = h(event)
            if inspect.isawaitable(r):
                r = await r
                await _emit(event, r)
            elif inspect.isasyncgen(r):
                # async generator instance (unlikely)
                async for rr in r:
                    await _emit(event, rr)
            else:
                await _emit(event, r)
    except Exception:
        raise


async def dispatch(nb_event: Any, bot: Any) -> bool:
    """主入口：OneBot 事件 -> AstrBot 插件分发，返回是否被处理."""
    event = await build_event(nb_event, bot)

    # 闸门前置：未 @ 时 command 永不响应（与上游一致）
    # 第一版统一要求 @，不做 ALL 例外
    if not event.is_at_or_wake_command:
        return False

    handlers = star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent)

    handled = False
    warned_pids: set[str] = set()

    for handler_md in handlers:
        # 检查 stop
        if event.is_stopped():
            break
        # filter 判定
        if not _passes_filters(handler_md, event):
            continue

        # 取 pid 供异常分流与日志
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
            await _invoke(handler_md, event)
            handled = True
        except StellaCompatNotSupported as e:
            logger.warning(f"[astrbot_compat] 插件 {pid} 依赖大模型能力：{e}")
            # 供状态矩阵与 GUI
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
            # 不打堆栈
            handled = True
        except Exception:
            logger.exception(f"[astrbot_compat] 插件 {pid} handler 执行异常")
            handled = True
            # 继续下一个 handler，不中断链

    return handled
