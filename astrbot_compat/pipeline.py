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


def _build_params(handler_md: Any, event: AstrMessageEvent) -> dict[str, Any] | None:
    """按 handler_params 顺序切分 __cmd_args__，缺必需参数则返回 None 跳过."""
    params_spec: dict[str, Any] = getattr(handler_md, "handler_params", {}) or {}
    if not params_spec:
        return {}
    # 取剩余文本
    try:
        rest: str = event.get_extra("__cmd_args__", "") or ""
    except Exception:
        rest = ""
    # 保留原始 rest 用于 GreedyStr 拼接
    rest = rest.strip()
    # 导入 GreedyStr 与 Parameter
    try:
        from .filters import GreedyStr
    except Exception:
        GreedyStr = None  # type: ignore

    # 有序列表
    items = list(params_spec.items())
    result: dict[str, Any] = {}

    # 将 rest 按空白切分，但 GreedyStr 需要原始剩余
    # 先按空白切分 tokens
    tokens: list[str] = rest.split() if rest else []

    token_idx = 0
    for idx, (pname, pinfo) in enumerate(items):
        # pinfo 可能是 (ann, default) 2元或 3元，兼容
        if isinstance(pinfo, tuple):
            if len(pinfo) == 2:
                ann, default = pinfo
            else:
                ann, default = pinfo[0], pinfo[1]
        else:
            ann, default = None, inspect.Parameter.empty
        has_default = default is not inspect.Parameter.empty

        # 判定是否 GreedyStr
        is_greedy = False
        if GreedyStr is not None and ann is GreedyStr:
            is_greedy = True
        elif isinstance(ann, str) and ann == "GreedyStr":
            is_greedy = True
        elif ann is not None and getattr(ann, "__name__", "") == "GreedyStr":
            is_greedy = True

        if is_greedy:
            # 吃掉剩余全部（保留原始空格）
            # 计算剩余 tokens 从 token_idx 开始重新拼接
            if token_idx < len(tokens):
                # 需要从 rest 中切出剩余部分：按 token_idx 之前的 tokens 长度来切
                # 简化：用 " ".join(tokens[token_idx:])
                val: Any = " ".join(tokens[token_idx:])
                token_idx = len(tokens)
            else:
                # 无剩余，若有默认值则用默认值，否则用空串
                if has_default:
                    val = default
                else:
                    val = ""
            # GreedyStr 必为 str 子类，无需转换
            result[pname] = val
        else:
            if token_idx < len(tokens):
                raw = tokens[token_idx]
                token_idx += 1
                # 类型转换
                if ann is int:
                    try:
                        val = int(raw)
                    except Exception:
                        logger.debug(f"[pipeline] 参数 {pname} int 转换失败: {raw}")
                        return None
                elif ann is float:
                    try:
                        val = float(raw)
                    except Exception:
                        logger.debug(f"[pipeline] 参数 {pname} float 转换失败: {raw}")
                        return None
                else:
                    val = raw
                result[pname] = val
            else:
                # 无剩余 token
                if has_default:
                    result[pname] = default
                else:
                    logger.debug(f"[pipeline] 参数 {pname} 缺失且无默认值，跳过 handler {handler_md.handler_name}")
                    return None
    return result


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


async def _invoke(handler_md: Any, event: AstrMessageEvent, params: dict[str, Any]) -> Any:
    h = handler_md.handler
    func = h.func if isinstance(h, functools.partial) else h
    try:
        if inspect.isasyncgenfunction(func):
            async for r in h(event, **params):
                await _emit(event, r)
        elif inspect.iscoroutinefunction(func):
            r = await h(event, **params)
            await _emit(event, r)
        else:
            r = h(event, **params)
            if inspect.isawaitable(r):
                r = await r
                await _emit(event, r)
            elif inspect.isasyncgen(r):
                async for rr in r:
                    await _emit(event, rr)
            else:
                await _emit(event, r)
    except Exception:
        raise


async def dispatch(nb_event: Any, bot: Any) -> bool:
    """主入口：OneBot 事件 -> AstrBot 插件分发，返回是否向用户产出了回应."""
    # ⑥ 前置闸门：未 @ 时直接返回，避免 chain 转换开销
    try:
        is_tome = nb_event.is_tome() if hasattr(nb_event, "is_tome") else False
        if not is_tome:
            return False
    except Exception:
        return False

    # ⑦ handlers 为空时直接返回，避免 build_event 开销
    handlers = star_handlers_registry.get_handlers_by_event_type(EventType.AdapterMessageEvent)
    if not handlers:
        return False

    event = await build_event(nb_event, bot)

    # 双保险：event 层再检一次
    if not event.is_at_or_wake_command:
        return False

    handled = False
    warned_pids: set[str] = set()

    for handler_md in handlers:
        if event.is_stopped():
            break
        if not _passes_filters(handler_md, event):
            continue

        # ② 参数注入：缺必需参数则跳过
        params = _build_params(handler_md, event)
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
            # ③ handled 语义：仅当已产出回应才算处理
            if getattr(event, "_has_send_oper", False):
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
            # 不置 handled，让 Stella 正常回话

    return handled
