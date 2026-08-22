# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""注册表骨架：EventType / StarMetadata / StarHandlerMetadata / StarHandlerRegistry。"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any


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

    name: str = ""
    author: str = ""
    desc: str = ""
    version: str = ""
    repo: str | None = None
    display_name: str | None = None
    short_desc: str | None = None
    support_platforms: list[str] = field(default_factory=list)
    astrbot_version: str | None = None
    logo_path: str | None = None
    i18n: dict[str, dict] = field(default_factory=dict)
    pages: list[dict] = field(default_factory=list)
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
        """`author/name`。与上游一致：只把 name/author 内部的斜杠换掉，保留分隔符。"""
        p_name = (self.name or "unknown").lower().replace("/", "_")
        p_author = (self.author or "unknown").lower().replace("/", "_")
        return f"{p_author}/{p_name}"

    def __str__(self) -> str:
        return f"Plugin {self.name} ({self.version}) by {self.author}: {self.desc}"

    def __repr__(self) -> str:
        return self.__str__()


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
    desc: str = ""
    enabled: bool = True

    def get_priority(self) -> int:
        try:
            return int(self.extras_configs.get("priority", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def __lt__(self, other: StarHandlerMetadata) -> bool:
        return self.get_priority() < other.get_priority()


class StarHandlerRegistry(list):
    """handler 注册表（按 priority 降序排列，priority 大的先执行）。

    与 NoneBot 相反：数值越大优先级越高，先执行。
    """

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._by_full_name: dict[str, StarHandlerMetadata] = {}

    def append(self, md: StarHandlerMetadata) -> None:
        md.extras_configs.setdefault("priority", 0)
        super().append(md)
        self._by_full_name[md.handler_full_name] = md
        self.resort()

    def resort(self) -> None:
        self.sort(key=lambda m: m.get_priority(), reverse=True)

    def clear(self) -> None:
        super().clear()
        self._by_full_name.clear()

    def remove(self, md: StarHandlerMetadata) -> None:
        self._by_full_name.pop(md.handler_full_name, None)
        with_removed = [h for h in self if h is not md]
        super().clear()
        super().extend(with_removed)

    def get_handler_by_full_name(self, full_name: str) -> StarHandlerMetadata | None:
        return self._by_full_name.get(full_name)

    def get_handlers_by_event_type(
        self,
        event_type: EventType,
        only_activated: bool = True,
        plugins_name: list[str] | None = None,
    ) -> list[StarHandlerMetadata]:
        """按事件类型取 handler，默认只返回已启用插件的已启用 handler。"""
        result: list[StarHandlerMetadata] = []
        for md in self:
            if md.event_type != event_type or not md.enabled:
                continue
            meta = star_map.get(md.handler_module_path)
            if only_activated and not (meta is not None and meta.activated):
                continue
            if plugins_name is not None and plugins_name != ["*"]:
                if meta is None:
                    continue
                if meta.name not in plugins_name and not meta.reserved:
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
