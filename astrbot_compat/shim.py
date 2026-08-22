# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""把 astrbot.* 假模块注入 sys.modules。"""

from __future__ import annotations

import logging
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)

_MODULE_NAMES = (
    "astrbot",
    "astrbot.api",
    "astrbot.api.star",
    "astrbot.api.event",
    "astrbot.api.event.filter",
    "astrbot.api.message_components",
    "astrbot.api.platform",
    "astrbot.api.provider",
    "astrbot.core",
    "astrbot.core.message",
    "astrbot.core.message.components",
    "astrbot.core.star",
    "astrbot.core.star.filter",
    "astrbot.core.platform",
)

_PACKAGE_NAMES = frozenset(
    {
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.core",
        "astrbot.core.message",
        "astrbot.core.star",
    },
)

_INSTALLED = False

ASTRBOT_COMPAT_VERSION_FALLBACK = "4.27.0"

# astrbot.api.event.filter 对外暴露的名字
_FILTER_EXPORTS = (
    "command",
    "command_group",
    "regex",
    "event_message_type",
    "permission_type",
    "platform_adapter_type",
    "custom_filter",
    "llm_tool",
    "after_message_sent",
    "on_astrbot_loaded",
    "on_platform_loaded",
    "on_llm_request",
    "on_llm_response",
    "on_waiting_llm_request",
    "on_agent_begin",
    "on_agent_done",
    "on_decorating_result",
    "on_using_llm_tool",
    "on_llm_tool_respond",
    "on_plugin_error",
    "on_plugin_loaded",
    "on_plugin_unloaded",
    "EventMessageType",
    "PermissionType",
    "PlatformAdapterType",
    "CustomFilter",
    "CustomFilterAnd",
    "CustomFilterOr",
    "CustomFilterMeta",
    "HandlerFilter",
    "GreedyStr",
    "CommandFilter",
    "CommandGroupFilter",
    "RegexFilter",
    "EventMessageTypeFilter",
    "PermissionTypeFilter",
    "PlatformAdapterTypeFilter",
    "RegisteringCommandable",
)

# astrbot.api.message_components / astrbot.core.message.components 的真类
_COMPONENT_EXPORTS = (
    "BaseMessageComponent",
    "ComponentType",
    "Plain",
    "Image",
    "Record",
    "Video",
    "File",
    "Face",
    "At",
    "AtAll",
    "Reply",
    "Poke",
    "Forward",
    "Node",
    "Nodes",
    "Json",
    "Music",
    "Share",
    "Location",
    "Dice",
    "RPS",
    "Shake",
    "Contact",
    "Unknown",
)

# astrbot.api.platform 的真类
_PLATFORM_EXPORTS = (
    "AstrBotMessage",
    "AstrMessageEvent",
    "Group",
    "MessageMember",
    "MessageType",
    "MessageSession",
    "MessageSesion",
    "PlatformMetadata",
)


def _make_module(name: str, is_package: bool = False) -> ModuleType:
    mod = ModuleType(name)
    mod.__doc__ = "AstrBot API 兼容层（Stella astrbot_compat 提供，非官方）"
    mod.__stella_compat__ = True
    if is_package:
        mod.__path__ = []
    return mod


def _bind(name: str, mod: ModuleType) -> None:
    sys.modules[name] = mod
    if "." in name:
        parent_name, _, leaf = name.rpartition(".")
        parent = sys.modules[parent_name]
        setattr(parent, leaf, mod)


def _make_placeholder(api_name: str) -> type:
    """返回一个占位类，实例化或属性访问时抛 StellaCompatNotSupported。"""
    from .exceptions import (
        StellaCompatNotSupported,
        StellaCompatUnsupportedAttribute,
    )

    short = api_name.rsplit(".", 1)[-1]

    class _Meta(type):
        def __getattr__(cls, name: str) -> Any:
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            raise StellaCompatUnsupportedAttribute(f"{api_name}.{name}")

    class _Placeholder(metaclass=_Meta):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = (args, kwargs)
            raise StellaCompatNotSupported(api_name)

        def __getattr__(self, name: str) -> Any:
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            raise StellaCompatUnsupportedAttribute(f"{api_name}.{name}")

    _Placeholder.__name__ = short
    _Placeholder.__qualname__ = short
    return _Placeholder


def _make_deprecated_register() -> Any:
    def _register(*args: Any, **kwargs: Any) -> Any:
        # @register 不带括号
        if len(args) == 1 and callable(args[0]) and not kwargs:
            cls = args[0]
            logger.warning("[astrbot_compat] @register 装饰器已废弃，继承 Star 即可自动注册")
            cls.__astrbot_register_meta__ = {"args": (), "kwargs": {}}
            return cls

        def decorator(cls: Any) -> Any:
            logger.warning("[astrbot_compat] @register 装饰器已废弃，继承 Star 即可自动注册")
            # 存储元数据供 loader 回退（name/author/desc/version/repo）
            cls.__astrbot_register_meta__ = {"args": args, "kwargs": kwargs}
            return cls

        return decorator

    return _register


def _install_star(star_mod: ModuleType, core_star_mod: ModuleType) -> None:
    from .base import Star, StarTools
    from .config import AstrBotConfig
    from .context import Context
    from .registry import (
        EventType,
        StarHandlerMetadata,
        StarMetadata,
        star_handlers_registry,
        star_map,
        star_registry,
    )

    for mod in (star_mod, core_star_mod):
        mod.Star = Star
        mod.StarTools = StarTools
        mod.StarMetadata = StarMetadata
        mod.Context = Context
        mod.AstrBotConfig = AstrBotConfig
        mod.register = _make_deprecated_register()
        mod.star_map = star_map
        mod.star_registry = star_registry
        mod.EventType = EventType
        mod.StarHandlerMetadata = StarHandlerMetadata
        mod.star_handlers_registry = star_handlers_registry


def _install_filters(filter_mod: ModuleType, core_filter_mod: ModuleType) -> None:
    from . import filters as _f

    for mod in (filter_mod, core_filter_mod):
        for name in _FILTER_EXPORTS:
            setattr(mod, name, getattr(_f, name))


def _install_events(event_mod: ModuleType, filter_mod: ModuleType) -> None:
    from .events import (
        AstrMessageEvent,
        CommandResult,
        EventResultType,
        MessageChain,
        MessageEventResult,
        ResultContentType,
    )

    event_mod.filter = filter_mod
    event_mod.AstrMessageEvent = AstrMessageEvent
    event_mod.MessageChain = MessageChain
    event_mod.MessageEventResult = MessageEventResult
    event_mod.EventResultType = EventResultType
    event_mod.ResultContentType = ResultContentType
    event_mod.CommandResult = CommandResult
    event_mod.EventResult = MessageEventResult  # 历史别名


def _install_components(*mods: ModuleType) -> None:
    from . import components as _c

    for mod in mods:
        for name in _COMPONENT_EXPORTS:
            setattr(mod, name, getattr(_c, name))


def _install_platform(*mods: ModuleType) -> None:
    from . import events as _e

    for mod in mods:
        for name in _PLATFORM_EXPORTS:
            setattr(mod, name, getattr(_e, name))
        mod.Platform = _make_placeholder("astrbot.api.platform.Platform")
        mod.register_platform_adapter = _make_placeholder(
            "astrbot.api.platform.register_platform_adapter",
        )


def _install_api(api: ModuleType) -> None:
    from . import filters as _f
    from .config import AstrBotConfig

    api.logger = logging.getLogger("astrbot_compat.plugin")
    api.AstrBotConfig = AstrBotConfig
    for attr, api_name in (
        ("sp", "astrbot.api.sp"),
        ("html_renderer", "astrbot.api.html_renderer"),
        ("FunctionTool", "astrbot.api.FunctionTool"),
        ("ToolSet", "astrbot.api.ToolSet"),
        ("BaseFunctionToolExecutor", "astrbot.api.BaseFunctionToolExecutor"),
        ("agent", "astrbot.api.agent"),
    ):
        setattr(api, attr, _make_placeholder(api_name))
    # llm_tool 必须指向真实现（硬约束：注册要成功，只是不分发）
    api.llm_tool = _f.llm_tool


def _install_provider(provider_mod: ModuleType) -> None:
    for name in (
        "Provider",
        "ProviderRequest",
        "ProviderMetaData",
        "ProviderType",
        "LLMResponse",
        "STTProvider",
        "Personality",
    ):
        setattr(provider_mod, name, _make_placeholder(f"astrbot.api.provider.{name}"))


def install_shim() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    existing = sys.modules.get("astrbot")
    if existing is not None and not getattr(existing, "__stella_compat__", False):
        logger.error(
            "检测到真实的 astrbot 包已被导入，为避免破坏它，"
            "Stella 兼容层不再注入；请卸载 astrbot 包后重试",
        )
        return

    for name in _MODULE_NAMES:
        _bind(name, _make_module(name, is_package=(name in _PACKAGE_NAMES)))

    m = sys.modules
    _install_star(m["astrbot.api.star"], m["astrbot.core.star"])
    _install_filters(m["astrbot.api.event.filter"], m["astrbot.core.star.filter"])
    _install_events(m["astrbot.api.event"], m["astrbot.api.event.filter"])
    _install_components(
        m["astrbot.api.message_components"],
        m["astrbot.core.message.components"],
        m["astrbot.api.platform"],
    )
    _install_platform(m["astrbot.api.platform"], m["astrbot.core.platform"])
    _install_api(m["astrbot.api"])
    _install_provider(m["astrbot.api.provider"])

    # astrbot.core.message.components 也挂到 astrbot.core.message 上
    m["astrbot.core.message"].components = m["astrbot.core.message.components"]
    m["astrbot.core"].message_components = m["astrbot.api.message_components"]

    _INSTALLED = True
    try:
        from config.settings import ASTRBOT_COMPAT_VERSION

        ver = ASTRBOT_COMPAT_VERSION
    except Exception:
        ver = ASTRBOT_COMPAT_VERSION_FALLBACK
    logger.info(f"[astrbot_compat] astrbot.* API shim 已注入（兼容声称版本 {ver}）")


def uninstall_shim() -> None:
    """仅供单测使用。

    生产代码不得调用：弹掉之后，已 import 的插件模块里的引用仍指向旧对象，
    star_map 会分裂。
    """
    global _INSTALLED
    for name in reversed(_MODULE_NAMES):
        sys.modules.pop(name, None)
    # 清注册表，避免单测之间互相污染
    try:
        from .registry import star_handlers_registry, star_map, star_registry

        star_registry.clear()
        star_map.clear()
        star_handlers_registry.clear()
    except Exception:
        pass
    _INSTALLED = False
