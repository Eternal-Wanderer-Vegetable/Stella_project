# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""注册表骨架：EventType / StarMetadata / StarHandlerMetadata / StarHandlerRegistry。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from types import ModuleType
from typing import Callable


class EventType(enum.Enum):
    """AstrBot 事件类型枚举（16 项）。"""

    OnAstrBotLoadedEvent = "OnAstrBotLoadedEvent"
    OnPlatformLoadedEvent = "OnPlatformLoadedEvent"
    AdapterMessageEvent = "AdapterMessageEvent"
    OnWaitingLLMRequestEvent = "OnWaitingLLMRequestEvent"
    OnLLMRequestEvent = "OnLLMRequestEvent"
    OnLLMResponseEvent = "OnLLMResponseEvent"
    OnAgentBeginEvent = "OnAgentBeginEvent"
    OnAgentDoneEvent = "OnAgentDoneEvent"
    OnDecoratingResultEvent = "OnDecoratingResultEvent"
    OnCallingFuncToolEvent = "OnCallingFuncToolEvent"
    OnUsingLLMToolEvent = "OnUsingLLMToolEvent"
    OnLLMToolRespondEvent = "OnLLMToolRespondEvent"
    OnAfterMessageSentEvent = "OnAfterMessageSentEvent"
    OnPluginErrorEvent = "OnPluginErrorEvent"
    OnPluginLoadedEvent = "OnPluginLoadedEvent"
    OnPluginUnloadedEvent = "OnPluginUnloadedEvent"


@dataclass
class StarMetadata:
    """插件元数据（占位 / 完整）。"""

    name: str
    author: str
    desc: str
    version: str
    repo: str | None = None
    display_name: str | None = None
    short_desc: str | None = None
    support_platforms: list[str] = field(default_factory=list)
    astrbot_version: str | None = None
    pages: list | None = None
    star_cls_type: type | None = None
    star_cls: object | None = None
    module_path: str = ""
    module: ModuleType | None = None
    root_dir_name: str = ""
    reserved: bool = False
    activated: bool = True
    config: object | None = None
    star_handler_full_names: list[str] = field(default_factory=list)

    @property
    def plugin_id(self) -> str:
        return f"{(self.author or '').lower()}/{(self.name or '').lower()}".replace("/", "_")

    def __str__(self) -> str:
        return f"{self.name}({self.author}) v{self.version}"


@dataclass
class StarHandlerMetadata:
    """单个 handler 的注册信息。"""

    event_type: EventType
    handler_full_name: str
    handler_name: str
    handler_module_path: str
    handler: Callable
    event_filters: list = field(default_factory=list)
    extras_configs: dict = field(default_factory=dict)
    handler_params: dict = field(default_factory=dict)
    desc: str = ""

    def get_priority(self) -> int:
        return int(self.extras_configs.get("priority", 0) or 0)


class StarHandlerRegistry(list):
    """handler 注册表（按 priority 降序排列，priority 大的先执行）。

    与 NoneBot 相反：数值越大优先级越高，先执行。
    """

    def append(self, md: StarHandlerMetadata) -> None:  # type: ignore[override]
        super().append(md)
        self.sort(key=lambda m: m.get_priority(), reverse=True)

    def get_handler_by_full_name(self, full_name: str) -> StarHandlerMetadata | None:
        for md in self:
            if md.handler_full_name == full_name:
                return md
        return None

    def get_handlers_by_event_type(self, event_type: EventType) -> list[StarHandlerMetadata]:
        """只返回 activated 插件的 handler。"""
        result: list[StarHandlerMetadata] = []
        for md in self:
            if md.event_type != event_type:
                continue
            # 通过 module_path 查插件是否 activated
            meta = star_map.get(md.handler_module_path)
            if meta is not None and not meta.activated:
                continue
            result.append(md)
        return result

    def get_handlers_by_module_name(self, module_path: str) -> list[StarHandlerMetadata]:
        return [md for md in self if md.handler_module_path == module_path]


def star_handlers_full_name(module: str, name: str) -> str:
    return f"{module}_{name}"


# 模块级单例（必须是模块级，不能放类里，否则多 import 路径会分裂）
star_registry: list[StarMetadata] = []
star_map: dict[str, StarMetadata] = {}
star_handlers_registry = StarHandlerRegistry()
