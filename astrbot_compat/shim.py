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
    # 上游官方推荐的通配导入入口，插件常写 from astrbot.api.all import *
    "astrbot.api.all",
    "astrbot.core",
    "astrbot.core.message",
    "astrbot.core.message.components",
    "astrbot.core.star",
    "astrbot.core.star.filter",
    # 上游 filter 实现所在的子模块，插件常直接 from astrbot.core.star.filter.command import GreedyStr
    "astrbot.core.star.filter.command",
    "astrbot.core.star.filter.regex",
    "astrbot.core.star.filter.event_message_type",
    "astrbot.core.star.filter.permission_type",
    "astrbot.core.star.filter.custom_filter",
    "astrbot.core.platform",
    "astrbot.core.provider",
    "astrbot.core.provider.entities",
    # 上游拼写错误的历史模块，老插件在 import 它
    "astrbot.core.provider.entites",
    "astrbot.core.agent",
    "astrbot.core.agent.tool",
    # 上游 agent 运行上下文真类所在模块，插件常直接 from ...astr_agent_context import AstrAgentContext
    "astrbot.core.astr_agent_context",
    "astrbot.core.agent.message",
    "astrbot.core.agent.run_context",
    "astrbot.core.agent.hooks",
    "astrbot.core.db",
    "astrbot.core.db.po",
)

_PACKAGE_NAMES = frozenset(
    {
        "astrbot",
        "astrbot.api",
        "astrbot.api.event",
        "astrbot.core",
        "astrbot.core.message",
        "astrbot.core.star",
        "astrbot.core.star.filter",
        "astrbot.core.provider",
        "astrbot.core.agent",
        "astrbot.core.db",
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

    core_submodules = tuple(
        sys.modules[f"astrbot.core.star.filter.{leaf}"]
        for leaf in (
            "command",
            "regex",
            "event_message_type",
            "permission_type",
            "custom_filter",
        )
    )
    for mod in (filter_mod, core_filter_mod, *core_submodules):
        for name in _FILTER_EXPORTS:
            setattr(mod, name, getattr(_f, name))
    # core 包上同名子模块属性优先于装饰器：插件写 from astrbot.core.star.filter.command import GreedyStr
    # 时需要拿到模块；装饰器仍从 astrbot.api.event.filter 导入（上游插件的惯用路径）。
    for sub in core_submodules:
        setattr(core_filter_mod, sub.__name__.rsplit(".", 1)[-1], sub)


def _install_api_all(all_mod: ModuleType) -> None:
    """astrbot.api.all：聚合各公开子模块的全部非下划线属性。

    必须在其他 _install_* 之后调用，保证聚合到的是最终对象。
    """
    sources = (
        "astrbot.api",
        "astrbot.api.star",
        "astrbot.api.event",
        "astrbot.api.event.filter",
        "astrbot.api.message_components",
        "astrbot.api.platform",
        "astrbot.api.provider",
    )
    exported: list[str] = []
    for src_name in sources:
        src = sys.modules[src_name]
        for name, value in vars(src).items():
            if name.startswith("_") or isinstance(value, ModuleType):
                continue
            if not hasattr(all_mod, name):
                setattr(all_mod, name, value)
                exported.append(name)
    all_mod.__all__ = exported


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
    from . import llm as _l
    from .config import AstrBotConfig
    from .preferences import sp

    api.logger = logging.getLogger("astrbot_compat.plugin")
    api.AstrBotConfig = AstrBotConfig
    api.sp = sp
    api.FunctionTool = _l.FunctionTool
    api.ToolSet = _l.ToolSet
    api.BaseFunctionToolExecutor = _l.BaseFunctionToolExecutor
    for attr, api_name in (
        ("html_renderer", "astrbot.api.html_renderer"),
        ("agent", "astrbot.api.agent"),
    ):
        setattr(api, attr, _make_placeholder(api_name))
    # llm_tool 必须指向真实现（硬约束：注册要成功）
    api.llm_tool = _f.llm_tool


def _install_provider(provider_mod: ModuleType, *core_mods: ModuleType) -> None:
    """astrbot.api.provider 与 astrbot.core.provider.entities 的真类。"""
    from . import llm as _l
    from .po import Personality

    names = (
        "Provider",
        "AbstractProvider",
        "STTProvider",
        "TTSProvider",
        "EmbeddingProvider",
        "RerankProvider",
        "ProviderRequest",
        "ProviderMeta",
        "ProviderMetaData",
        "ProviderType",
        "LLMResponse",
        "TokenUsage",
        "ToolCallsResult",
        "RerankResult",
        "AssistantMessageSegment",
        "ToolCallMessageSegment",
    )
    for mod in (provider_mod, *core_mods):
        for name in names:
            setattr(mod, name, getattr(_l, name))
        mod.Personality = Personality
    # llm_tools 是全局注册表单例，只挂在 core.provider 下（与上游一致）
    for mod in core_mods:
        mod.llm_tools = _l.llm_tools


def _install_agent(
    agent_mod: ModuleType,
    tool_mod: ModuleType,
    message_mod: ModuleType,
    run_context_mod: ModuleType,
    hooks_mod: ModuleType,
) -> None:
    from . import llm as _l

    for name in (
        "FunctionTool",
        "FuncTool",
        "ToolSet",
        "ToolSchema",
        "FunctionToolManager",
        "FuncCall",
        "BaseFunctionToolExecutor",
    ):
        setattr(tool_mod, name, getattr(_l, name))
        setattr(agent_mod, name, getattr(_l, name))

    for name in (
        "ContentPart",
        "TextPart",
        "ThinkPart",
        "ImageURLPart",
        "Message",
        "ToolCall",
        "AssistantMessageSegment",
        "ToolCallMessageSegment",
        "UserMessageSegment",
        "SystemMessageSegment",
    ):
        setattr(message_mod, name, getattr(_l, name))

    run_context_mod.ContextWrapper = _l.ContextWrapper
    run_context_mod.NoContext = _l.ContextWrapper
    hooks_mod.BaseAgentRunHooks = _l.BaseAgentRunHooks
    agent_mod.BaseAgentRunHooks = _l.BaseAgentRunHooks
    agent_mod.ContextWrapper = _l.ContextWrapper


def _install_astr_agent_context(aac_mod: ModuleType) -> None:
    from . import llm as _l

    aac_mod.AstrAgentContext = _l.AstrAgentContext
    aac_mod.ContextWrapper = _l.ContextWrapper
    aac_mod.AgentContextWrapper = _l.AgentContextWrapper


def _install_db(db_mod: ModuleType, po_mod: ModuleType) -> None:
    from .po import Conversation, Personality

    po_mod.Conversation = Conversation
    po_mod.Personality = Personality
    db_mod.po = po_mod


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
    _install_provider(
        m["astrbot.api.provider"],
        m["astrbot.core.provider"],
        m["astrbot.core.provider.entities"],
        # 上游的历史拼写错误，老插件在 import
        m["astrbot.core.provider.entites"],
    )
    _install_agent(
        m["astrbot.core.agent"],
        m["astrbot.core.agent.tool"],
        m["astrbot.core.agent.message"],
        m["astrbot.core.agent.run_context"],
        m["astrbot.core.agent.hooks"],
    )
    _install_db(m["astrbot.core.db"], m["astrbot.core.db.po"])
    _install_astr_agent_context(m["astrbot.core.astr_agent_context"])
    _install_api_all(m["astrbot.api.all"])
    # 上游 astrbot.api.all 挂在 astrbot.api 下
    m["astrbot.api"].all = m["astrbot.api.all"]

    # astrbot.core.message.components 也挂到 astrbot.core.message 上
    m["astrbot.core.message"].components = m["astrbot.core.message.components"]
    m["astrbot.core"].message_components = m["astrbot.api.message_components"]
    # 上游把 sp / logger 也挂在 astrbot.core 与顶层 astrbot 上
    from .preferences import sp as _sp

    m["astrbot.core"].sp = _sp
    m["astrbot"].sp = _sp
    m["astrbot"].logger = m["astrbot.api"].logger
    m["astrbot.core"].logger = m["astrbot.api"].logger

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
