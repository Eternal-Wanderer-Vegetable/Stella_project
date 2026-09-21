# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Provider Runtime：把「provider → 工具」的解析抽象成可插拔的 backend。

MCP Provider 引入前，``CapabilityProvider`` 只有一种实现方式（``astrbot_tool``），
Comes、hooks、registry 都直接去查 ``llm_tools``。MCP 工具的实现在另一个进程边界
（子进程或远程 HTTP）后面，有自己独立的连接、重连与工具目录生命周期，不可能塞进
``llm_tools``（方案 §3.1：混入插件注册表会让热重载和存活探针产生错误耦合）。

于是把这层查询抽成 backend 协议：

```
CapabilityProvider(kind)
      │  ProviderRuntime（按 kind 分派）
      ├── AstrbotToolBackend   → astrbot_compat.llm.tool.llm_tools（现有行为）
      └── McpBackend           → McpServerManager（stdio / Streamable HTTP）
```

依赖纪律：本包与 ``registry.py`` **不许在模块顶层 import** ``astrbot_compat`` 或
``mcp``——Runtime 是接口层，实现细节（工具注册表、MCP SDK）由各 backend 自己
延迟导入。``registry`` 亦然：它不 import 本包，进程接线（装哪个 backend）由
``capability/adapters/mcp.py`` 在启动期完成。

**单例纪律与 ``capability.registry`` 同理**（见那份 docstring）：``provider_runtime``
必须模块级——放类里或函数里，不同 import 路径会各拿一份，表现为「Manager 明明
ready 了 Comes 却说工具不可用」。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from capability.registry import CapabilityProvider


@runtime_checkable
class ProviderBackend(Protocol):
    """一种 provider 实现方式对外提供的最小查询面。

    四个方法的语义由实现方保证与 ``comes/executor.resolve_tools`` 和
    ``registry._tool_live`` 的既有判据**逐条对齐**：``resolve`` 返回 None 就是
    「工具此刻不可用」（等价于旧的查不到 / ``active=False``）；``is_live`` 为 False
    的 provider 不进 ``routable()`` 候选集。对不齐的表现是「路由挑中了它，Comes
    立刻回一句失败」——用户看到的是答非所问，而两边日志各自都觉得自己没错。
    """

    kind: str

    def resolve(self, provider: CapabilityProvider) -> Any:
        """解析成可执行的 FunctionTool；不可用返回 None（不抛异常）。"""
        ...

    def schema(self, provider: CapabilityProvider) -> dict[str, Any]:
        """工具的参数 schema（OpenAI function 形态）；不可用时返回空 dict。"""
        ...

    def is_live(self, provider: CapabilityProvider) -> bool:
        """provider 指向的实现此刻是否真的存在。不许抛异常。"""
        ...

    def status(self, provider: CapabilityProvider) -> dict[str, Any]:
        """结构化诊断状态，可进状态接口响应体——**不得含凭据与自由文本**。"""
        ...


from capability.providers.registry import (
    AstrbotToolBackend,
    ProviderRuntime,
    provider_runtime,
)

# 注意：本包**不许**把 ``registry``（子模块名）放进 ``__all__`` 或用 ``from ...
# import registry`` 引别名——回归测试钉死了「包入口不得遮蔽子模块」
# （capability/__init__ 就为此修过，见 tests/capability/test_registry.py）。

__all__ = [
    "AstrbotToolBackend",
    "ProviderBackend",
    "ProviderRuntime",
    "provider_runtime",
]
