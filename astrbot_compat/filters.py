# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""过滤器与装饰器（兼容 AstrBot api/event/filter）。"""

from __future__ import annotations

import enum
import inspect
import re
from typing import Any, Callable


from .registry import EventType, StarHandlerMetadata, star_handlers_registry


# ============================================================
# 枚举与 GreedyStr
# ============================================================


class GreedyStr(str):
    """贪婪字符串参数（占据剩余所有文本）。"""


class EventMessageType(enum.Flag):
    GROUP_MESSAGE = enum.auto()
    PRIVATE_MESSAGE = enum.auto()
    OTHER_MESSAGE = enum.auto()
    ALL = GROUP_MESSAGE | PRIVATE_MESSAGE | OTHER_MESSAGE


class PermissionType(enum.Enum):
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class PlatformAdapterType(enum.Flag):
    AIOCQHTTP = enum.auto()
    QQOFFICIAL = enum.auto()
    WECHATPADPRO = enum.auto()
    TELEGRAM = enum.auto()
    DISCORD = enum.auto()
    LARK = enum.auto()
    DINGTALK = enum.auto()
    WECOM = enum.auto()
    SLACK = enum.auto()
    WEBCHAT = enum.auto()
    SATORI = enum.auto()
    MISSKEY = enum.auto()
    ALL = (
        AIOCQHTTP
        | QQOFFICIAL
        | WECHATPADPRO
        | TELEGRAM
        | DISCORD
        | LARK
        | DINGTALK
        | WECOM
        | SLACK
        | WEBCHAT
        | SATORI
        | MISSKEY
    )


# ============================================================
# 过滤器类
# ============================================================


class HandlerFilter:
    """过滤器抽象基类。"""

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        return True


class CommandFilter(HandlerFilter):
    def __init__(
        self,
        name: str,
        alias: set[str] | None = None,
        priority: int = 0,
        desc: str | None = None,
        parent_names: list[str] | None = None,
    ) -> None:
        self.name = name
        self.alias = alias or set()
        self.priority = priority
        self.desc = desc
        self.parent_names = parent_names
        # 完整指令名列表
        if parent_names:
            base = [name] + sorted(self.alias)
            # parent_names 已是完整路径
            self.full_names: list[str] = []
            for p in parent_names:
                for c in base:
                    self.full_names.append(f"{p} {c}")
        else:
            self.full_names = [name] + sorted(self.alias)
        # 按长度降序，优先匹配更长指令（二级指令优先）
        self.full_names.sort(key=len, reverse=True)

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        try:
            msg = event.get_message_str() if hasattr(event, "get_message_str") else str(getattr(event, "message_str", ""))
        except Exception:
            msg = ""
        s = msg.strip()
        if s.startswith("/"):
            s = s[1:].lstrip()
        if not s:
            return False
        for fn in self.full_names:
            if s == fn or s.startswith(fn + " "):
                rest = s[len(fn):].strip()
                try:
                    event.set_extra("__cmd_args__", rest)
                except Exception:
                    pass
                return True
        return False


class CommandGroupFilter(HandlerFilter):
    def __init__(
        self,
        name: str,
        alias: set[str] | None = None,
        priority: int = 0,
        parent_names: list[str] | None = None,
    ) -> None:
        self.name = name
        self.alias = alias or set()
        self.priority = priority
        self.parent_names = parent_names
        if parent_names:
            base = [name] + sorted(self.alias)
            self.full_names: list[str] = []
            for p in parent_names:
                for c in base:
                    self.full_names.append(f"{p} {c}")
        else:
            self.full_names = [name] + sorted(self.alias)
        self.full_names.sort(key=len, reverse=True)

    def get_complete_names(self) -> list[str]:
        return list(self.full_names)

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        try:
            msg = event.get_message_str() if hasattr(event, "get_message_str") else str(getattr(event, "message_str", ""))
        except Exception:
            msg = ""
        s = msg.strip()
        if s.startswith("/"):
            s = s[1:].lstrip()
        if not s:
            return False
        for fn in self.full_names:
            if s == fn or s.startswith(fn + " "):
                return True
        return False


class RegexFilter(HandlerFilter):
    def __init__(self, pattern: str, flags: int = 0, priority: int = 0) -> None:
        self.pattern = pattern
        self.flags = flags
        self.priority = priority
        try:
            self._compiled = re.compile(pattern, flags)
        except Exception:
            self._compiled = None

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        try:
            msg = event.get_message_str() if hasattr(event, "get_message_str") else str(getattr(event, "message_str", ""))
        except Exception:
            msg = ""
        if self._compiled is None:
            try:
                return bool(re.search(self.pattern, msg, self.flags))
            except Exception:
                return False
        return bool(self._compiled.search(msg))


class EventMessageTypeFilter(HandlerFilter):
    def __init__(self, event_type: EventMessageType, priority: int = 0) -> None:
        self.event_type = event_type
        self.priority = priority

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        if self.event_type == EventMessageType.ALL:
            return True
        try:
            is_private = event.is_private_chat() if hasattr(event, "is_private_chat") else False
        except Exception:
            is_private = False
        need = EventMessageType.PRIVATE_MESSAGE if is_private else EventMessageType.GROUP_MESSAGE
        return bool(self.event_type & need)


class PermissionTypeFilter(HandlerFilter):
    def __init__(self, permission_type: PermissionType, raise_error: bool = True) -> None:
        self.permission_type = permission_type
        self.raise_error = raise_error

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        if self.permission_type == PermissionType.ADMIN:
            try:
                return bool(event.is_admin() if hasattr(event, "is_admin") else False)
            except Exception:
                return False
        return True


class PlatformAdapterTypeFilter(HandlerFilter):
    def __init__(self, platform_adapter_type: PlatformAdapterType) -> None:
        self.platform_adapter_type = platform_adapter_type

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        return bool(self.platform_adapter_type & PlatformAdapterType.AIOCQHTTP)


class CustomFilter(HandlerFilter):
    """供插件继承的自定义过滤器基类。"""

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        raise NotImplementedError


class _CustomFilterWrapper(HandlerFilter):
    """内部包装器：持有插件传进来的 custom_filter_cls 实例信息。"""

    def __init__(self, custom_filter_cls: type[HandlerFilter], *args: Any, **kwargs: Any) -> None:
        self.custom_filter_cls = custom_filter_cls
        self.args = args
        self.kwargs = kwargs
        try:
            self._inst = custom_filter_cls(*args, **kwargs)
        except Exception:
            self._inst = None

    def filter(self, event: Any, cfg: Any = None) -> bool:  # noqa: ARG002
        if self._inst is None:
            return False
        try:
            return bool(self._inst.filter(event, cfg))
        except Exception:
            return False


# ============================================================
# 内部共用函数
# ============================================================


def _get_or_create_handler_md(func: Callable, event_type: EventType) -> StarHandlerMetadata:
    existing = getattr(func, "__astrbot_handler_md__", None)
    if existing is not None:
        return existing  # type: ignore[return-value]
    handler_full_name = f"{func.__module__}_{func.__name__}"
    md = StarHandlerMetadata(
        event_type=event_type,
        handler_full_name=handler_full_name,
        handler_name=func.__name__,
        handler_module_path=func.__module__,
        handler=func,
        event_filters=[],
        extras_configs={},
        handler_params={},
        desc="",
    )
    try:
        setattr(func, "__astrbot_handler_md__", md)
    except AttributeError:
        pass
    star_handlers_registry.append(md)
    return md


def _append_filter(func: Callable, event_type: EventType, filter_obj: HandlerFilter) -> Callable:
    md = _get_or_create_handler_md(func, event_type)
    md.event_filters.append(filter_obj)
    return func


def _resort() -> None:
    star_handlers_registry.sort(key=lambda m: m.get_priority(), reverse=True)


def _parse_handler_params(func: Callable, md: StarHandlerMetadata) -> None:
    try:
        sig = inspect.signature(func, eval_str=True)  # type: ignore[call-arg]
    except Exception:
        sig = inspect.signature(func)
    params = list(sig.parameters.values())
    remaining = params[2:] if len(params) >= 2 else []
    for idx, p in enumerate(remaining):
        ann = p.annotation if p.annotation is not inspect.Parameter.empty else None
        default = p.default
        is_greedy = False
        if ann is GreedyStr:
            is_greedy = True
        elif isinstance(ann, str) and ann == "GreedyStr":
            is_greedy = True
        if is_greedy and idx != len(remaining) - 1:
            raise ValueError("GreedyStr 必须是最后一个参数")
        md.handler_params[p.name] = (ann, default)


def _make_hook(event_type: EventType) -> Callable:
    def hook(*args: Any, **kwargs: Any) -> Any:
        # 先判 callable，再处理 int 位置参数（优先级）
        priority = kwargs.pop("priority", 0)
        if args and callable(args[0]) and not kwargs:
            func = args[0]
            md = _get_or_create_handler_md(func, event_type)  # type: ignore[arg-type]
            if priority:
                md.extras_configs["priority"] = priority
                _resort()
            return func
        if args and isinstance(args[0], int) and not kwargs:
            priority = int(args[0])

        def decorator(func: Callable) -> Callable:
            md = _get_or_create_handler_md(func, event_type)
            if priority:
                md.extras_configs["priority"] = priority
                _resort()
            return func

        return decorator

    return hook


# ============================================================
# 带参数装饰器
# ============================================================


def command(
    name: str,
    alias: set[str] | list[str] | str | None = None,
    priority: int = 0,
    desc: str | None = None,
) -> Callable:
    if alias is None:
        alias_set: set[str] = set()
    elif isinstance(alias, str):
        alias_set = {alias}
    elif isinstance(alias, (list, set, tuple)):
        alias_set = set(alias)
    else:
        alias_set = {str(alias)}

    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        if priority:
            md.extras_configs["priority"] = priority
            _resort()
        if desc is not None:
            md.desc = desc
        filt = CommandFilter(name, alias_set, priority, desc)
        md.event_filters.append(filt)
        _parse_handler_params(func, md)
        return func

    return decorator


class _RegisteringCommandable:
    def __init__(self, group_filter: CommandGroupFilter):
        self.group_filter = group_filter

    def command(
        self,
        name: str,
        alias: set[str] | list[str] | str | None = None,
        priority: int = 0,
        desc: str | None = None,
    ) -> Callable:
        if alias is None:
            alias_set: set[str] = set()
        elif isinstance(alias, str):
            alias_set = {alias}
        elif isinstance(alias, (list, set, tuple)):
            alias_set = set(alias)
        else:
            alias_set = {str(alias)}

        def decorator(func: Callable) -> Callable:
            md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
            if priority:
                md.extras_configs["priority"] = priority
                _resort()
            if desc is not None:
                md.desc = desc
            filt = CommandFilter(
                name, alias_set, priority, desc, parent_names=self.group_filter.get_complete_names()
            )
            md.event_filters.append(filt)
            _parse_handler_params(func, md)
            return func

        return decorator

    def group(
        self,
        name: str,
        alias: set[str] | list[str] | str | None = None,
        priority: int = 0,
    ) -> Any:
        if alias is None:
            alias_set: set[str] = set()
        elif isinstance(alias, str):
            alias_set = {alias}
        elif isinstance(alias, (list, set, tuple)):
            alias_set = set(alias)
        else:
            alias_set = {str(alias)}
        filt = CommandGroupFilter(name, alias_set, priority, parent_names=self.group_filter.get_complete_names())

        # 创建桩的 md（不执行）
        def _stub(func: Callable) -> _RegisteringCommandable:
            md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
            md.extras_configs["is_group_stub"] = True
            if priority:
                md.extras_configs["priority"] = priority
                _resort()
            md.event_filters.append(filt)
            return _RegisteringCommandable(filt)

        # 为了支持 @group 加括号的两种写法，这里返回一个可调用对象
        # 上游是直接 decorator 返回对象，本实现简化：group() 必须带括号
        # 但为了兼容 @math_g.group 不带参数的错误用法，返回 _stub 作为装饰器
        return _stub


def command_group(
    name: str,
    alias: set[str] | list[str] | str | None = None,
    priority: int = 0,
) -> Callable:
    if alias is None:
        alias_set: set[str] = set()
    elif isinstance(alias, str):
        alias_set = {alias}
    elif isinstance(alias, (list, set, tuple)):
        alias_set = set(alias)
    else:
        alias_set = {str(alias)}

    def decorator(func: Callable) -> Any:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        md.extras_configs["is_group_stub"] = True
        if priority:
            md.extras_configs["priority"] = priority
            _resort()
        filt = CommandGroupFilter(name, alias_set, priority)
        md.event_filters.append(filt)
        return _RegisteringCommandable(filt)

    return decorator


def regex(pattern: str, flags: int = 0, priority: int = 0) -> Callable:
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        if priority:
            md.extras_configs["priority"] = priority
            _resort()
        filt = RegexFilter(pattern, flags, priority)
        md.event_filters.append(filt)
        return func

    return decorator


def event_message_type(event_type: EventMessageType, priority: int = 0) -> Callable:
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        if priority:
            md.extras_configs["priority"] = priority
            _resort()
        filt = EventMessageTypeFilter(event_type, priority)
        md.event_filters.append(filt)
        return func

    return decorator


def permission_type(permission_type: PermissionType, raise_error: bool = True) -> Callable:  # noqa: A001
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        filt = PermissionTypeFilter(permission_type, raise_error)
        md.event_filters.append(filt)
        return func

    return decorator


def platform_adapter_type(platform_adapter_type: PlatformAdapterType) -> Callable:  # noqa: A001
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        filt = PlatformAdapterTypeFilter(platform_adapter_type)
        md.event_filters.append(filt)
        return func

    return decorator


def custom_filter(custom_filter_cls: type[HandlerFilter], *args: Any, **kwargs: Any) -> Callable:
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        filt = _CustomFilterWrapper(custom_filter_cls, *args, **kwargs)
        md.event_filters.append(filt)
        return func

    return decorator


def llm_tool(name: str | None = None) -> Callable:
    """注册为 llm_tool（仅注册，不分发）。"""

    if callable(name):
        func = name  # type: ignore[assignment]
        _get_or_create_handler_md(func, EventType.OnCallingFuncToolEvent)
        return func  # type: ignore[return-value]

    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.OnCallingFuncToolEvent)
        if name is not None:
            md.extras_configs["tool_name"] = name
        return func

    return decorator


# ============================================================
# 无参钩子装饰器（14 个，平铺）
# ============================================================

after_message_sent = _make_hook(EventType.OnAfterMessageSentEvent)
on_astrbot_loaded = _make_hook(EventType.OnAstrBotLoadedEvent)
on_platform_loaded = _make_hook(EventType.OnPlatformLoadedEvent)
on_llm_request = _make_hook(EventType.OnLLMRequestEvent)
on_llm_response = _make_hook(EventType.OnLLMResponseEvent)
on_waiting_llm_request = _make_hook(EventType.OnWaitingLLMRequestEvent)
on_agent_begin = _make_hook(EventType.OnAgentBeginEvent)
on_agent_done = _make_hook(EventType.OnAgentDoneEvent)
on_decorating_result = _make_hook(EventType.OnDecoratingResultEvent)
on_using_llm_tool = _make_hook(EventType.OnUsingLLMToolEvent)
on_llm_tool_respond = _make_hook(EventType.OnLLMToolRespondEvent)
on_plugin_error = _make_hook(EventType.OnPluginErrorEvent)
on_plugin_loaded = _make_hook(EventType.OnPluginLoadedEvent)
on_plugin_unloaded = _make_hook(EventType.OnPluginUnloadedEvent)
