# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""后端注册表：内置显式映射 ``backend_type -> factory``（方案 §6.6）。

注册方式刻意保守：新增第三方适配器由**部署者**安装和登记（在 cometa.toml
声明 type，registry 显式注册工厂），绝不允许群聊传 Python import 路径或
任意 executable——那等于把远程代码执行开放给聊天入口。首版不需要动态
插件市场。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from cometa.config import BackendConfig

from .base import AgentBackend

_LOGGER = logging.getLogger("cometa.backends.registry")

BackendFactory = Callable[[BackendConfig], Any]


class BackendRegistry:
    """类型 → 工厂的显式映射。executor/worker 从这里取后端实例。"""

    def __init__(self) -> None:
        self._factories: dict[str, BackendFactory] = {}

    def register_type(self, type_name: str, factory: BackendFactory) -> None:
        if not type_name or not callable(factory):
            raise ValueError("backend type 与 factory 必须非空")
        self._factories[type_name] = factory

    def known_types(self) -> list[str]:
        return sorted(self._factories)

    def create(self, backend: BackendConfig) -> AgentBackend:
        """按配置构造后端实例。未知 type 抛错（fail-closed，不静默换实现）。"""
        factory = self._factories.get(backend.type)
        if factory is None:
            raise KeyError(
                f"未登记的后端类型 {backend.type!r}（backend_id={backend.backend_id}）；"
                "cometa 不允许运行时动态加载"
            )
        return factory(backend)


def default_registry() -> BackendRegistry:
    """内置注册表：fake 永远可用（测试/验收基线）；codex 在 SDK 缺失时
    probe 返回 incompatible，不在这里就失败——注册 ≠ 可用。"""
    from .codex import CodexBackend
    from .fake import FakeBackend

    registry = BackendRegistry()
    registry.register_type("fake", lambda cfg: FakeBackend(cfg))
    registry.register_type("codex", lambda cfg: CodexBackend(cfg))
    return registry


__all__ = ["BackendFactory", "BackendRegistry", "default_registry"]
