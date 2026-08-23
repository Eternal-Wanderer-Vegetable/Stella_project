# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""过滤器与装饰器（兼容 AstrBot api/event/filter）。

装饰器一律接受 `**kwargs` 并原样存入 `extras_configs`，与上游一致——上游所有
`register_*` 都是 `**kwargs` 签名，插件传入未知关键字不会报错。
"""

from __future__ import annotations

import contextlib
import enum
import functools
import inspect
import logging
import re
import types
import typing
from abc import ABCMeta, abstractmethod
from collections.abc import Callable
from typing import Any

from .registry import EventType, StarHandlerMetadata, star_handlers_registry

logger = logging.getLogger("astrbot_compat.filters")

# ============================================================
# 枚举与 GreedyStr
# ============================================================


class GreedyStr(str):
    """贪婪字符串参数（占据剩余所有文本），必须是最后一个参数。"""

    __slots__ = ()


class EventMessageType(enum.Flag):
    GROUP_MESSAGE = enum.auto()
    PRIVATE_MESSAGE = enum.auto()
    OTHER_MESSAGE = enum.auto()
    ALL = GROUP_MESSAGE | PRIVATE_MESSAGE | OTHER_MESSAGE


class PermissionType(enum.Flag):
    """权限类型。上游是 Flag，允许 `ADMIN | MEMBER`。"""

    ADMIN = enum.auto()
    MEMBER = enum.auto()


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
# 过滤器基类
# ============================================================


class HandlerFilter:
    """过滤器抽象基类。"""

    def filter(self, event: Any, cfg: Any = None) -> bool:
        _ = (event, cfg)
        return True


class CustomFilterMeta(ABCMeta):
    """让 `FilterA & FilterB` / `FilterA | FilterB` 在类级别可用（对齐上游）。"""

    def __and__(cls, other):
        if not (isinstance(other, type) and issubclass(other, CustomFilter)):
            raise TypeError("Operands must be subclasses of CustomFilter.")
        return CustomFilterAnd(cls(), other())

    def __or__(cls, other):
        if not (isinstance(other, type) and issubclass(other, CustomFilter)):
            raise TypeError("Operands must be subclasses of CustomFilter.")
        return CustomFilterOr(cls(), other())


class CustomFilter(HandlerFilter, metaclass=CustomFilterMeta):
    """供插件继承的自定义过滤器基类。"""

    def __init__(self, raise_error: bool = True, **kwargs: Any) -> None:
        self.raise_error = raise_error
        self.extras = kwargs

    @abstractmethod
    def filter(self, event: Any, cfg: Any = None) -> bool:
        raise NotImplementedError

    def __and__(self, other):
        return CustomFilterAnd(self, other)

    def __or__(self, other):
        return CustomFilterOr(self, other)


class CustomFilterOr(CustomFilter):
    def __init__(self, filter1: CustomFilter, filter2: CustomFilter) -> None:
        super().__init__()
        self.filter1 = filter1
        self.filter2 = filter2

    def filter(self, event: Any, cfg: Any = None) -> bool:
        return self.filter1.filter(event, cfg) or self.filter2.filter(event, cfg)


class CustomFilterAnd(CustomFilter):
    def __init__(self, filter1: CustomFilter, filter2: CustomFilter) -> None:
        super().__init__()
        self.filter1 = filter1
        self.filter2 = filter2

    def filter(self, event: Any, cfg: Any = None) -> bool:
        return self.filter1.filter(event, cfg) and self.filter2.filter(event, cfg)


# ============================================================
# 指令参数解析（对齐上游 CommandFilter.validate_and_convert_params）
# ============================================================

_TRUE_WORDS = ("true", "yes", "1", "on")
_FALSE_WORDS = ("false", "no", "0", "off")

# 插件写了 `from __future__ import annotations` 时注解是字符串，
# 且 get_type_hints 可能因为名字不可解析而失败，这里兜住最常见的几种。
_STR_ANNOTATIONS: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "GreedyStr": GreedyStr,
    "filter.GreedyStr": GreedyStr,
}


def _resolve_annotation(ann: Any, hints: dict[str, Any], name: str) -> Any:
    """把可能是字符串的注解还原成真实类型。"""
    if name in hints:
        return hints[name]
    if isinstance(ann, str):
        key = ann.strip()
        if key in _STR_ANNOTATIONS:
            return _STR_ANNOTATIONS[key]
        # `int | None` 这类简单联合，取第一个可识别的非 None 分支
        parts = [p.strip() for p in key.split("|")]
        known = [_STR_ANNOTATIONS[p] for p in parts if p in _STR_ANNOTATIONS]
        if known and any(p in ("None", "NoneType") for p in parts):
            return known[0] | None
        if len(known) == 1 and len(parts) == 1:
            return known[0]
    return ann


def _unwrap_optional(annotation: Any) -> tuple:
    """去掉 Optional[T] / Union[T, None] / T|None，返回剩余类型。"""
    args = typing.get_args(annotation)
    non_none = [a for a in args if a is not type(None)]
    return tuple(non_none)


def _is_type_like(v: Any) -> bool:
    """判断 handler_params 的值是「类型注解」还是「默认值」。"""
    return (
        isinstance(v, (type, types.UnionType))
        or typing.get_origin(v) is typing.Union
        or v is inspect.Parameter.empty
    )


def _to_bool(raw: str, param_name: str) -> bool:
    low = str(raw).lower()
    if low in _TRUE_WORDS:
        return True
    if low in _FALSE_WORDS:
        return False
    raise ValueError(f"参数 {param_name} 必须是布尔值（true/false, yes/no, 1/0）。")


def _convert_one(raw: str, spec: Any, param_name: str) -> Any:
    """按 spec（类型注解或默认值）把一个 token 转成目标类型。"""
    if spec is None or spec is inspect.Parameter.empty:
        # 无注解无默认：数字自动转 int，其余保持字符串（对齐上游）
        return int(raw) if raw.lstrip("-").isdigit() else raw
    # 先处理「默认值」形态：用默认值的类型推断
    if not _is_type_like(spec):
        if isinstance(spec, bool):
            return _to_bool(raw, param_name)
        if isinstance(spec, str):
            return raw
        if isinstance(spec, int):
            return int(raw)
        if isinstance(spec, float):
            return float(raw)
        return raw
    # 再处理「类型注解」形态
    if spec is bool:
        return _to_bool(raw, param_name)
    if spec is str or spec is GreedyStr:
        return raw
    origin = typing.get_origin(spec)
    if origin in (typing.Union, types.UnionType):
        nn = _unwrap_optional(spec)
        if len(nn) == 1:
            return _convert_one(raw, nn[0], param_name)
        return raw
    if isinstance(spec, type):
        return spec(raw)
    return raw


def _describe_params(handler_params: dict[str, Any]) -> str:
    parts = []
    for k, v in handler_params.items():
        if isinstance(v, type):
            parts.append(f"{k}({v.__name__})")
        elif _is_type_like(v):
            parts.append(f"{k}({v})")
        else:
            parts.append(f"{k}({type(v).__name__})={v}")
    return ", ".join(parts)


def parse_handler_params(handler: Callable) -> dict[str, Any]:
    """把 handler 签名转成 `参数名 -> 注解或默认值`（对齐上游）。

    跳过前两个参数（self / event）。注解可能因 `from __future__ import annotations`
    变成字符串，这里逐级尝试 eval_str、get_type_hints、常见名字表。
    """
    try:
        signature = inspect.signature(handler, eval_str=True)
    except Exception:
        signature = inspect.signature(handler)
    hints: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        target = handler.func if isinstance(handler, functools.partial) else handler
        hints = typing.get_type_hints(target)

    params: dict[str, Any] = {}
    for idx, (k, v) in enumerate(signature.parameters.items()):
        if idx < 2:
            continue
        if v.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if v.default is inspect.Parameter.empty:
            params[k] = _resolve_annotation(v.annotation, hints, k)
        else:
            params[k] = v.default
    return params


def validate_and_convert_params(
    params: list[str],
    handler_params: dict[str, Any],
) -> dict[str, Any]:
    """把切好的 token 列表按 handler_params 转换成关键字参数字典。"""
    result: dict[str, Any] = {}
    items = list(handler_params.items())
    for i, (name, spec) in enumerate(items):
        if spec is GreedyStr:
            if i != len(items) - 1:
                raise ValueError(f"参数 '{name}' (GreedyStr) 必须是最后一个参数。")
            result[name] = " ".join(params[i:])
            return result
        if i >= len(params):
            if _is_type_like(spec):
                raise ValueError(f"必要参数缺失。该指令完整参数: {_describe_params(handler_params)}")
            result[name] = spec
            continue
        try:
            result[name] = _convert_one(params[i], spec, name)
        except ValueError as e:
            if str(e).startswith("参数 "):
                raise
            raise ValueError(
                f"参数 {name} 类型错误。完整参数: {_describe_params(handler_params)}",
            ) from e
    return result


# ============================================================
# 具体过滤器
# ============================================================


class CommandFilter(HandlerFilter):
    """标准指令过滤器。受唤醒前缀 / @ 约束（与上游一致）。"""

    def __init__(
        self,
        command_name: str,
        alias: set[str] | None = None,
        handler_md: StarHandlerMetadata | None = None,
        parent_command_names: list[str] | None = None,
    ) -> None:
        self.command_name = command_name
        self.name = command_name  # Stella 早期字段名
        self.alias = set(alias) if alias else set()
        self.parent_command_names = (
            parent_command_names if parent_command_names is not None else [""]
        )
        self.handler_params: dict[str, Any] = {}
        self.handler_md: StarHandlerMetadata | None = None
        self.custom_filter_list: list[CustomFilter] = []
        self._cmpl_cmd_names: list[str] | None = None
        if handler_md is not None:
            self.init_handler_md(handler_md)

    def init_handler_md(self, handler_md: StarHandlerMetadata) -> None:
        """解析 handler 签名：无默认值取注解，有默认值取默认值（对齐上游）。"""
        self.handler_md = handler_md
        self.handler_params = parse_handler_params(handler_md.handler)

    def get_handler_md(self) -> StarHandlerMetadata | None:
        return self.handler_md

    def add_custom_filter(self, custom_filter: CustomFilter) -> None:
        self.custom_filter_list.append(custom_filter)

    def custom_filter_ok(self, event: Any, cfg: Any) -> bool:
        return all(f.filter(event, cfg) for f in self.custom_filter_list)

    def get_complete_command_names(self) -> list[str]:
        if self._cmpl_cmd_names is not None:
            return self._cmpl_cmd_names
        names = [
            f"{parent} {cmd}" if parent else cmd
            for cmd in [self.command_name, *sorted(self.alias)]
            for parent in (self.parent_command_names or [""])
        ]
        # 长指令优先匹配，避免 "math" 抢在 "math add" 前面
        names.sort(key=len, reverse=True)
        self._cmpl_cmd_names = names
        return names

    # 兼容 Stella 早期字段名
    @property
    def full_names(self) -> list[str]:
        return self.get_complete_command_names()

    def equals(self, message_str: str) -> bool:
        return message_str in self.get_complete_command_names()

    def filter(self, event: Any, cfg: Any = None) -> bool:
        if not getattr(event, "is_at_or_wake_command", False):
            return False
        if not self.custom_filter_ok(event, cfg):
            return False
        message_str = re.sub(r"\s+", " ", event.get_message_str().strip())
        rest: str | None = None
        for full_cmd in self.get_complete_command_names():
            if message_str == full_cmd or message_str.startswith(f"{full_cmd} "):
                rest = message_str[len(full_cmd) :].strip()
                break
        if rest is None:
            return False
        tokens = [p for p in rest.split(" ") if p]
        params = validate_and_convert_params(tokens, self.handler_params)
        event.set_extra("parsed_params", params)
        return True


class CommandGroupFilter(HandlerFilter):
    """指令组过滤器。命中只表示「进入了这个组」，实际执行由子指令负责。"""

    def __init__(
        self,
        group_name: str,
        alias: set[str] | None = None,
        parent_group: CommandGroupFilter | None = None,
    ) -> None:
        self.group_name = group_name
        self.name = group_name
        self.alias = set(alias) if alias else set()
        self.parent_group = parent_group
        self.sub_command_filters: list[HandlerFilter] = []
        self.custom_filter_list: list[CustomFilter] = []
        self._cmpl_cmd_names: list[str] | None = None

    def add_sub_command_filter(self, f: HandlerFilter) -> None:
        self.sub_command_filters.append(f)

    def add_custom_filter(self, custom_filter: CustomFilter) -> None:
        self.custom_filter_list.append(custom_filter)

    def get_complete_command_names(self) -> list[str]:
        if self._cmpl_cmd_names is not None:
            return self._cmpl_cmd_names
        parents = (
            self.parent_group.get_complete_command_names() if self.parent_group else [""]
        )
        names = [
            f"{parent} {cmd}" if parent else cmd
            for cmd in [self.group_name, *sorted(self.alias)]
            for parent in parents
        ]
        names.sort(key=len, reverse=True)
        self._cmpl_cmd_names = names
        return names

    @property
    def full_names(self) -> list[str]:
        return self.get_complete_command_names()

    def filter(self, event: Any, cfg: Any = None) -> bool:
        if not getattr(event, "is_at_or_wake_command", False):
            return False
        if not all(f.filter(event, cfg) for f in self.custom_filter_list):
            return False
        message_str = re.sub(r"\s+", " ", event.get_message_str().strip())
        return any(
            message_str == full_cmd or message_str.startswith(f"{full_cmd} ")
            for full_cmd in self.get_complete_command_names()
        )


class RegexFilter(HandlerFilter):
    """正则过滤器。与上游一致：**不**受唤醒前缀 / @ 约束。"""

    def __init__(self, regex: str | re.Pattern, flags: int = 0) -> None:
        self.regex = re.compile(regex, flags) if isinstance(regex, str) else re.compile(regex)
        self.regex_str = self.regex.pattern
        self.pattern = self.regex_str

    def filter(self, event: Any, cfg: Any = None) -> bool:
        _ = cfg
        return bool(self.regex.search(event.get_message_str().strip()))


class EventMessageTypeFilter(HandlerFilter):
    def __init__(self, event_message_type: EventMessageType) -> None:
        self.event_message_type = event_message_type
        self.event_type = event_message_type  # Stella 早期字段名

    def filter(self, event: Any, cfg: Any = None) -> bool:
        _ = cfg
        from .events import MessageType

        mapping = {
            MessageType.GROUP_MESSAGE: EventMessageType.GROUP_MESSAGE,
            MessageType.FRIEND_MESSAGE: EventMessageType.PRIVATE_MESSAGE,
            MessageType.OTHER_MESSAGE: EventMessageType.OTHER_MESSAGE,
        }
        current = mapping.get(event.get_message_type())
        if current is None:
            return False
        return bool(current & self.event_message_type)


class PermissionTypeFilter(HandlerFilter):
    def __init__(self, permission_type: PermissionType, raise_error: bool = True) -> None:
        self.permission_type = permission_type
        self.raise_error = raise_error

    def filter(self, event: Any, cfg: Any = None) -> bool:
        _ = cfg
        if self.permission_type == PermissionType.ADMIN:
            return bool(event.is_admin())
        return True


class PlatformAdapterTypeFilter(HandlerFilter):
    def __init__(self, platform_adapter_type: PlatformAdapterType) -> None:
        self.platform_adapter_type = platform_adapter_type

    def filter(self, event: Any, cfg: Any = None) -> bool:
        _ = (event, cfg)
        return bool(self.platform_adapter_type & PlatformAdapterType.AIOCQHTTP)


# ============================================================
# 内部共用
# ============================================================


def _normalize_alias(alias: Any) -> set[str]:
    if alias is None:
        return set()
    if isinstance(alias, str):
        return {alias}
    if isinstance(alias, (list, set, tuple, frozenset)):
        return {str(a) for a in alias}
    return {str(alias)}


def get_handler_full_name(func: Callable) -> str:
    return f"{func.__module__}_{func.__name__}"


def _get_or_create_handler_md(
    func: Callable,
    event_type: EventType,
    **kwargs: Any,
) -> StarHandlerMetadata:
    """取或建 handler 元数据。未知关键字原样进 extras_configs（对齐上游）。"""
    existing = getattr(func, "__astrbot_handler_md__", None)
    if existing is None:
        existing = star_handlers_registry.get_handler_by_full_name(
            get_handler_full_name(func),
        )
    if existing is not None:
        if "desc" in kwargs:
            existing.desc = kwargs.pop("desc")
        existing.extras_configs.update(kwargs)
        if "priority" in kwargs:
            star_handlers_registry.resort()
        return existing

    md = StarHandlerMetadata(
        event_type=event_type,
        handler_full_name=get_handler_full_name(func),
        handler_name=func.__name__,
        handler_module_path=func.__module__,
        handler=func,
        event_filters=[],
    )
    # 上游默认拿 docstring 当描述，/help 类插件依赖这个
    if func.__doc__:
        md.desc = func.__doc__.strip()
    if "desc" in kwargs:
        md.desc = kwargs.pop("desc")
    md.extras_configs = dict(kwargs)
    md.extras_configs.setdefault("priority", 0)
    with contextlib.suppress(AttributeError):
        func.__astrbot_handler_md__ = md
    star_handlers_registry.append(md)
    return md


def _make_hook(event_type: EventType) -> Callable:
    """生成一个既能 `@hook` 也能 `@hook(...)` 使用的无参钩子装饰器。"""

    def hook(*args: Any, **kwargs: Any) -> Any:
        # @hook 直接贴在函数上
        if len(args) == 1 and callable(args[0]) and not kwargs:
            _get_or_create_handler_md(args[0], event_type)
            return args[0]
        # @hook(5) —— 历史写法，位置参数当优先级
        if args and isinstance(args[0], int):
            kwargs.setdefault("priority", int(args[0]))

        def decorator(func: Callable) -> Callable:
            _get_or_create_handler_md(func, event_type, **kwargs)
            return func

        return decorator

    return hook


# ============================================================
# 带参装饰器
# ============================================================


class RegisteringCommandable:
    """指令组级联注册的句柄（`@group.command(...)` / `@group.group(...)`）。"""

    def __init__(self, parent_group: CommandGroupFilter) -> None:
        self.parent_group = parent_group

    def command(self, name: str, alias: Any = None, **kwargs: Any) -> Callable:
        return _register_command(
            name,
            alias,
            parent_group=self.parent_group,
            **kwargs,
        )

    def group(self, name: str, alias: Any = None, **kwargs: Any) -> Callable:
        return _register_command_group(
            name,
            alias,
            parent_group=self.parent_group,
            **kwargs,
        )

    def custom_filter(self, custom_filter_cls: Any, *args: Any, **kwargs: Any) -> Callable:
        return custom_filter(custom_filter_cls, *args, _parent=self.parent_group, **kwargs)


def _register_command(
    name: str,
    alias: Any = None,
    parent_group: CommandGroupFilter | None = None,
    **kwargs: Any,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent, **kwargs)
        filt = CommandFilter(
            name,
            _normalize_alias(alias),
            parent_command_names=(
                parent_group.get_complete_command_names() if parent_group else None
            ),
        )
        filt.init_handler_md(md)
        if parent_group is not None:
            parent_group.add_sub_command_filter(filt)
            md.extras_configs["sub_command"] = True
        md.event_filters.append(filt)
        return func

    return decorator


def _register_command_group(
    name: str,
    alias: Any = None,
    parent_group: CommandGroupFilter | None = None,
    **kwargs: Any,
) -> Callable:
    def decorator(func: Callable) -> RegisteringCommandable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent, **kwargs)
        md.extras_configs["is_group_stub"] = True
        filt = CommandGroupFilter(name, _normalize_alias(alias), parent_group=parent_group)
        if parent_group is not None:
            parent_group.add_sub_command_filter(filt)
        md.event_filters.append(filt)
        return RegisteringCommandable(filt)

    return decorator


def command(name: str, alias: Any = None, **kwargs: Any) -> Callable:
    """注册一条指令。"""
    return _register_command(name, alias, **kwargs)


def command_group(name: str, alias: Any = None, **kwargs: Any) -> Callable:
    """注册一个指令组，返回值可继续 `.command()` / `.group()`。"""
    return _register_command_group(name, alias, **kwargs)


def regex(pattern: str | re.Pattern, flags: int = 0, **kwargs: Any) -> Callable:
    """正则监听。不受 @ / 唤醒前缀约束。"""

    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent, **kwargs)
        md.event_filters.append(RegexFilter(pattern, flags))
        return func

    return decorator


def event_message_type(event_message_type: EventMessageType, **kwargs: Any) -> Callable:
    """按消息类型监听（群聊 / 私聊 / 其他）。不受 @ 约束。"""

    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent, **kwargs)
        md.event_filters.append(EventMessageTypeFilter(event_message_type))
        return func

    return decorator


def permission_type(permission_type: PermissionType, raise_error: bool = True, **kwargs: Any) -> Callable:
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent, **kwargs)
        md.event_filters.append(PermissionTypeFilter(permission_type, raise_error))
        return func

    return decorator


def platform_adapter_type(platform_adapter_type: PlatformAdapterType, **kwargs: Any) -> Callable:
    def decorator(func: Callable) -> Callable:
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent, **kwargs)
        md.event_filters.append(PlatformAdapterTypeFilter(platform_adapter_type))
        return func

    return decorator


def custom_filter(custom_type_filter: Any, *args: Any, **kwargs: Any) -> Callable:
    """挂一个自定义过滤器。接受 CustomFilter 子类或其组合实例。"""
    parent_group: CommandGroupFilter | None = kwargs.pop("_parent", None)
    raise_error = args[0] if args else kwargs.pop("raise_error", True)

    if isinstance(custom_type_filter, (CustomFilterAnd, CustomFilterOr)):
        instance: CustomFilter = custom_type_filter
    elif isinstance(custom_type_filter, CustomFilter):
        instance = custom_type_filter
    else:
        instance = custom_type_filter(raise_error)

    def decorator(func: Callable) -> Callable:
        if isinstance(func, RegisteringCommandable):
            func.parent_group.add_custom_filter(instance)
            return func
        if parent_group is not None:
            parent_group.add_custom_filter(instance)
            return func
        md = _get_or_create_handler_md(func, EventType.AdapterMessageEvent)
        md.event_filters.append(instance)
        return func

    return decorator


# ============================================================
# llm_tool：docstring -> JSON schema
# ============================================================

# 上游把 Python 类型名映射到 JSON Schema 类型
_PY_TO_JSON_TYPE = {
    "string": "string",
    "str": "string",
    "number": "number",
    "float": "number",
    "int": "integer",
    "integer": "integer",
    "boolean": "boolean",
    "bool": "boolean",
    "object": "object",
    "dict": "object",
    "array": "array",
    "list": "array",
}

_ARG_LINE = re.compile(r"^\s*(\w+)\s*\(([^)]+)\)\s*:\s*(.*)$")
_ARGS_HEADER = re.compile(r"^\s*(Args|Arguments|参数)\s*:\s*$", re.IGNORECASE)
_OTHER_HEADER = re.compile(
    r"^\s*(Returns?|Raises?|Examples?|Note|Notes|Yields?|返回|异常|示例)\s*:\s*$",
    re.IGNORECASE,
)


def _json_type(raw: str) -> tuple[str, dict | None]:
    """把 `string` / `list[string]` 这类标注转成 JSON Schema 的 type（+ items）。"""
    raw = raw.strip().lower()
    m = re.match(r"^(list|array)\s*\[\s*(\w+)\s*\]$", raw)
    if m:
        inner = _PY_TO_JSON_TYPE.get(m.group(2), "string")
        return "array", {"type": inner}
    return _PY_TO_JSON_TYPE.get(raw, "string"), None


def parse_tool_docstring(doc: str | None) -> tuple[str, list[dict]]:
    """解析 llm_tool 的 docstring，返回 (描述, 参数列表)。

    只认上游文档规定的这一种格式，所以不引 docstring_parser 依赖::

        \"\"\"获取天气信息。

        Args:
            location(string): 地点
            days(list[string]): 哪几天
        \"\"\"
    """
    if not doc:
        return "", []
    lines = doc.strip().splitlines()
    desc_lines: list[str] = []
    args: list[dict] = []
    in_args = False
    seen_header = False
    for line in lines:
        if _ARGS_HEADER.match(line):
            in_args = True
            seen_header = True
            continue
        if _OTHER_HEADER.match(line):
            in_args = False
            seen_header = True
            continue
        if not in_args:
            # 描述只取第一个段标题之前的内容，Returns/Raises 段不算描述
            if not seen_header:
                desc_lines.append(line.strip())
            continue
        m = _ARG_LINE.match(line)
        if m is None:
            continue
        name, type_raw, description = m.groups()
        json_type, items = _json_type(type_raw)
        spec: dict[str, Any] = {
            "name": name,
            "type": json_type,
            "description": description.strip(),
        }
        if items:
            spec["items"] = items
        args.append(spec)
    return "\n".join(desc_lines).strip(), args


def llm_tool(name: str | None = None, **kwargs: Any) -> Callable:
    """把一个方法注册成 LLM 函数工具。

    工具函数的签名是 `async def tool(self, event, <llm 参数...>)`，参数类型必须写在
    docstring 的 Args 段里（见 `parse_tool_docstring`）。返回 str 会回喂给模型；
    返回 None 表示"没有返回值或已直接回复用户"。
    """
    if callable(name):
        func = name
        _register_llm_tool(func, None)
        return func

    def decorator(func: Callable) -> Callable:
        _register_llm_tool(func, name, **kwargs)
        return func

    return decorator


def _register_llm_tool(func: Callable, name: str | None, **kwargs: Any) -> None:
    from .llm.tool import llm_tools

    md = _get_or_create_handler_md(func, EventType.OnCallingFuncToolEvent, **kwargs)
    tool_name = name or func.__name__
    if name is not None:
        md.extras_configs["tool_name"] = name
    desc, args = parse_tool_docstring(func.__doc__)
    # handler 现在还是未绑定函数，loader 稍后会 functools.partial(self) 重绑；
    # 这里存 md 的引用，注册时取 md.handler，保证拿到的是最终那一个。
    llm_tools.add_func(tool_name, args, desc or tool_name, _LateBoundHandler(md))
    logger.debug(f"[astrbot_compat] 已登记函数工具 {tool_name}: {args}")


class _LateBoundHandler:
    """转发到 StarHandlerMetadata.handler。

    工具在**类体执行时**注册，那时 handler 还是未绑定函数；loader 加载插件时才会
    用 functools.partial(inst) 重绑。直接存函数会导致调用时缺 self，所以存元数据、
    调用时再取。
    """

    def __init__(self, md: StarHandlerMetadata) -> None:
        self._md = md
        self.__name__ = md.handler_name
        self.__module__ = md.handler_module_path

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._md.handler(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<LateBound {self._md.handler_full_name}>"


# ============================================================
# 无参钩子装饰器
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
