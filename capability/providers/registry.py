# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Provider Runtime Registry：按 provider 的 kind 把查询分派给对应 backend。

方案 §7.1。``ProviderRuntime`` 自己不认识任何一种实现细节：不 import
``astrbot_compat``、不 import ``mcp``——它只做分派与「没有 backend 时」的缺省语义。

缺省语义刻意与 ``CapabilityRegistry`` 的探针缺省**同构**：某 kind 没有 backend 时
``is_live`` 返回 True（不过滤）。理由与「探针装没装」一模一样：``deploy
plugin-scaffold`` / Router benchmark 这类离线进程不装 backend，那里该量的是声明
本身；把「没有 backend」当成「不可用」会让它们一起变成空跑。进程接线（Bot 启动时
注册哪些 backend）是 ``capability/adapters/mcp.py`` 的事。
"""

from __future__ import annotations

from typing import Any

from capability.providers import ProviderBackend
from capability.registry import KIND_ASTRBOT_TOOL, CapabilityProvider


class AstrbotToolBackend:
    """``astrbot_tool`` backend：包装现有 ``llm_tools``，行为与从前逐字一致。

    判据（查得到且 ``active``）必须与 ``comes/executor.resolve_tools`` 的遗留路径、
    ``capability/adapters/astrbot.py::install_tool_probe`` 三处保持同一句话——历史上
    这三处对不齐过，表现是「路由挑中了它，Comes 说工具不可用」。
    """

    kind = KIND_ASTRBOT_TOOL

    def _tools(self) -> Any:
        from astrbot_compat.llm.tool import llm_tools

        return llm_tools

    def resolve(self, provider: CapabilityProvider) -> Any:
        try:
            tool = self._tools().get_tool(provider.tool_name)
        except Exception:
            return None
        if tool is None or not getattr(tool, "active", True):
            return None
        return tool

    def schema(self, provider: CapabilityProvider) -> dict[str, Any]:
        tool = self.resolve(provider)
        params = getattr(tool, "parameters", None) if tool is not None else None
        return params if isinstance(params, dict) else {}

    def is_live(self, provider: CapabilityProvider) -> bool:
        return self.resolve(provider) is not None

    def status(self, provider: CapabilityProvider) -> dict[str, Any]:
        # 清单里的 astrbot 工具状态由 capability/inventory.py 直接查 llm_tools，
        # 这里没有额外信息可给；返回空 dict 让调用方沿用旧字段。
        _ = provider
        return {}


class ProviderRuntime:
    """kind → backend 的分派器。``provider_runtime`` 是模块级单例。"""

    def __init__(self) -> None:
        self._backends: dict[str, ProviderBackend] = {}

    def register_backend(self, backend: ProviderBackend) -> None:
        """登记一个 backend；同 kind 重复登记时后者胜出（重装进程接线用）。"""
        self._backends[backend.kind] = backend

    def backend_of(self, kind: str) -> ProviderBackend | None:
        return self._backends.get(kind)

    def resolve(self, provider: CapabilityProvider) -> Any:
        backend = self._backends.get(provider.kind)
        return backend.resolve(provider) if backend is not None else None

    def schema(self, provider: CapabilityProvider) -> dict[str, Any]:
        backend = self._backends.get(provider.kind)
        if backend is None:
            return {}
        try:
            schema = backend.schema(provider)
        except Exception:
            return {}
        return schema if isinstance(schema, dict) else {}

    def is_live(self, provider: CapabilityProvider) -> bool:
        """没有 backend 的 kind 不过滤（缺省语义见模块 docstring）。不许抛异常。"""
        backend = self._backends.get(provider.kind)
        if backend is None:
            return True
        try:
            return bool(backend.is_live(provider))
        except Exception:
            # backend 坏了不该把能力从路由里悄悄摘掉（那正是 bug_report_2026_9_2#1
            # 的反向事故）；按「未知」放行，Comes 执行失败时还有健康度记账兜底。
            return True

    def status(self, provider: CapabilityProvider) -> dict[str, Any]:
        backend = self._backends.get(provider.kind)
        if backend is None:
            return {}
        try:
            status = backend.status(provider)
        except Exception:
            return {}
        return status if isinstance(status, dict) else {}

    def reset(self) -> None:
        """清空全部 backend（测试用；进程接线重装时会先调它保证幂等）。"""
        self._backends.clear()

    def __bool__(self) -> bool:
        """装了至少一个 backend 才算「接线了」。

        Comes / hooks 用它区分「进程没接线（走遗留路径）」与「接线了（按 kind
        分派）」——空 Runtime 和没接线在这两处必须长得不一样，否则空 Runtime 会
        让所有 astrbot 工具都 resolve 成 None。
        """
        return bool(self._backends)

    def __repr__(self) -> str:
        return f"ProviderRuntime({sorted(self._backends)})"


# 模块级单例。必须模块级——理由见包 __init__ 的 docstring。
provider_runtime = ProviderRuntime()


__all__ = [
    "AstrbotToolBackend",
    "ProviderRuntime",
    "provider_runtime",
]
