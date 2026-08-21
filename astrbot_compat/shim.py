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
)

_PACKAGE_NAMES = frozenset({"astrbot", "astrbot.api", "astrbot.api.event"})

_INSTALLED = False

ASTRBOT_COMPAT_VERSION_FALLBACK = "4.27.0"


def _make_module(name: str, is_package: bool = False) -> ModuleType:
    mod = ModuleType(name)
    mod.__doc__ = "AstrBot API 兼容层（Stella astrbot_compat 提供，非官方）"
    mod.__stella_compat__ = True  # type: ignore[attr-defined]
    if is_package:
        mod.__path__ = []  # type: ignore[attr-defined]
    return mod


def _bind(name: str, mod: ModuleType) -> None:
    sys.modules[name] = mod
    if "." in name:
        parent_name, _, leaf = name.rpartition(".")
        parent = sys.modules[parent_name]
        setattr(parent, leaf, mod)


def _make_placeholder(api_name: str) -> type:
    """返回一个占位类，实例化或属性访问时抛 StellaCompatNotSupported。"""
    from .exceptions import StellaCompatNotSupported

    short = api_name.rsplit(".", 1)[-1]

    class _Meta(type):
        def __getattr__(cls, name: str) -> Any:  # type: ignore[override]
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            raise StellaCompatNotSupported(f"{api_name}.{name}")

    class _Placeholder(metaclass=_Meta):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise StellaCompatNotSupported(api_name)

        def __getattr__(self, name: str) -> Any:
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            raise StellaCompatNotSupported(f"{api_name}.{name}")

    _Placeholder.__name__ = short
    _Placeholder.__qualname__ = short
    return _Placeholder


def _make_deprecated_register() -> Any:
    def _register(*args: Any, **kwargs: Any) -> Any:
        # @register 不带括号：@register
        if len(args) == 1 and callable(args[0]) and not kwargs:
            cls = args[0]
            logger.warning("[astrbot_compat] @register 装饰器已废弃，继承 Star 即可自动注册")
            cls.__astrbot_register_meta__ = {"args": (), "kwargs": {}}  # type: ignore[attr-defined]
            return cls

        def decorator(cls: Any) -> Any:
            logger.warning("[astrbot_compat] @register 装饰器已废弃，继承 Star 即可自动注册")
            # 存储元数据供 loader 回退（name/author/desc/version/repo）
            cls.__astrbot_register_meta__ = {"args": args, "kwargs": kwargs}  # type: ignore[attr-defined]
            return cls

        return decorator

    return _register


def install_shim() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    existing = sys.modules.get("astrbot")
    if existing is not None and not getattr(existing, "__stella_compat__", False):
        logger.error(
            "检测到真实的 astrbot 包已被导入，为避免破坏它，"
            "Stella 兼容层不再注入；请卸载 astrbot 包后重试"
        )
        return

    for name in _MODULE_NAMES:
        _bind(name, _make_module(name, is_package=(name in _PACKAGE_NAMES)))

    api = sys.modules["astrbot.api"]
    star_mod = sys.modules["astrbot.api.star"]
    event_mod = sys.modules["astrbot.api.event"]
    filter_mod = sys.modules["astrbot.api.event.filter"]
    provider_mod = sys.modules["astrbot.api.provider"]
    message_components_mod = sys.modules["astrbot.api.message_components"]
    platform_mod = sys.modules["astrbot.api.platform"]

    # --- astrbot.api.star
    from .base import Star, StarTools
    from .registry import StarMetadata

    star_mod.Star = Star  # type: ignore[attr-defined]
    star_mod.StarTools = StarTools  # type: ignore[attr-defined]
    star_mod.StarMetadata = StarMetadata  # type: ignore[attr-defined]
    star_mod.register = _make_deprecated_register()  # type: ignore[attr-defined]
    from .context import Context as _Context

    star_mod.Context = _Context  # type: ignore[attr-defined]

    # --- astrbot.api.event.filter：把 filters 模块的公开名字全部搬过去
    from . import filters as _f

    for _name in (
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
        "HandlerFilter",
        "GreedyStr",
        "CommandFilter",
        "CommandGroupFilter",
        "RegexFilter",
        "EventMessageTypeFilter",
        "PermissionTypeFilter",
        "PlatformAdapterTypeFilter",
    ):
        setattr(filter_mod, _name, getattr(_f, _name))

    # --- astrbot.api.event：此刻只能绑 filter 与占位
    event_mod.filter = filter_mod  # type: ignore[attr-defined]
    for _ename, _eapi in (
        ("AstrMessageEvent", "astrbot.api.event.AstrMessageEvent"),
        ("MessageChain", "astrbot.api.event.MessageChain"),
        ("MessageEventResult", "astrbot.api.event.MessageEventResult"),
        ("EventResultType", "astrbot.api.event.EventResultType"),
        ("ResultContentType", "astrbot.api.event.ResultContentType"),
        ("CommandResult", "astrbot.api.event.CommandResult"),
    ):
        setattr(event_mod, _ename, _make_placeholder(_eapi))

    # --- astrbot.api
    api.logger = logging.getLogger("astrbot_compat.plugin")  # type: ignore[attr-defined]
    from .config import AstrBotConfig as _AstrBotConfig

    api.AstrBotConfig = _AstrBotConfig  # type: ignore[attr-defined]
    star_mod.AstrBotConfig = _AstrBotConfig  # type: ignore[attr-defined]
    for _aname, _aapi in (
        ("sp", "astrbot.api.sp"),
        ("html_renderer", "astrbot.api.html_renderer"),
        ("FunctionTool", "astrbot.api.FunctionTool"),
        ("ToolSet", "astrbot.api.ToolSet"),
        ("BaseFunctionToolExecutor", "astrbot.api.BaseFunctionToolExecutor"),
        ("agent", "astrbot.api.agent"),
        ("llm_tool", "astrbot.api.llm_tool"),
    ):
        setattr(api, _aname, _make_placeholder(_aapi))

    # --- astrbot.api.message_components
    for _mname, _mapi in (
        ("Plain", "astrbot.api.message_components.Plain"),
        ("Image", "astrbot.api.message_components.Image"),
        ("At", "astrbot.api.message_components.At"),
        ("AtAll", "astrbot.api.message_components.AtAll"),
        ("Face", "astrbot.api.message_components.Face"),
        ("Reply", "astrbot.api.message_components.Reply"),
        ("Forward", "astrbot.api.message_components.Forward"),
        ("Json", "astrbot.api.message_components.Json"),
    ):
        setattr(message_components_mod, _mname, _make_placeholder(_mapi))

    # --- astrbot.api.platform
    for _pname, _papi in (
        ("AstrBotMessage", "astrbot.api.platform.AstrBotMessage"),
        ("MessageMember", "astrbot.api.platform.MessageMember"),
        ("MessageType", "astrbot.api.platform.MessageType"),
        ("PlatformMetadata", "astrbot.api.platform.PlatformMetadata"),
    ):
        setattr(platform_mod, _pname, _make_placeholder(_papi))

    # --- astrbot.api.provider
    for _prname, _prapi in (
        ("Provider", "astrbot.api.provider.Provider"),
        ("ProviderRequest", "astrbot.api.provider.ProviderRequest"),
        ("LLMResponse", "astrbot.api.provider.LLMResponse"),
    ):
        setattr(provider_mod, _prname, _make_placeholder(_prapi))

    _INSTALLED = True
    # 版本号优先读配置
    try:
        from config.settings import ASTRBOT_COMPAT_VERSION

        ver = ASTRBOT_COMPAT_VERSION
    except Exception:
        ver = ASTRBOT_COMPAT_VERSION_FALLBACK
    logger.info(f"[astrbot_compat] astrbot.* API shim 已注入（兼容声称版本 {ver}）")


def uninstall_shim() -> None:
    """仅供单测使用。生产代码不得调用（弹了之后已 import 的插件模块里的引用仍指向旧对象，star_map 会分裂）。"""
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
