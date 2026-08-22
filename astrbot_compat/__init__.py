# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""本模块为兼容 AstrBot 插件 API 而**独立实现**，仅参考上游的接口形状（
AstrBot, AGPL-3.0, AstrBotDevs），未拷贝其实现代码。本项目与 AstrBot 项目无
隐含关系，不保证全量插件可用。"""

from .base import Star, StarTools
from .config import AstrBotConfig
from .context import Context, get_context
from .exceptions import StellaCompatError, StellaCompatNotSupported
from .loader import (
    get_failed_plugins,
    initialize_plugins,
    load_all_plugins,
    terminate_plugins,
)
from .registry import (
    EventType,
    StarHandlerMetadata,
    StarHandlerRegistry,
    StarMetadata,
    star_handlers_registry,
    star_map,
    star_registry,
)
from .shim import install_shim, uninstall_shim

__all__ = [
    "AstrBotConfig",
    "Context",
    "EventType",
    "Star",
    "StarHandlerMetadata",
    "StarHandlerRegistry",
    "StarMetadata",
    "StarTools",
    "StellaCompatError",
    "StellaCompatNotSupported",
    "get_context",
    "get_failed_plugins",
    "initialize_plugins",
    "install_shim",
    "load_all_plugins",
    "star_handlers_registry",
    "star_map",
    "star_registry",
    "terminate_plugins",
    "uninstall_shim",
]
