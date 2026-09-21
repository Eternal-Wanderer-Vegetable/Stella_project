# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP backend：把 ProviderBackend 协议接到 McpServerManager（方案 §7.1）。

判定语义（与 Provider Runtime 的契约对齐）：

- ``is_live`` = Server ready **且** 远程工具在目录里 **且** 在路由白名单内——它
  服务的是 ``registry.routable()``，所以把「白名单外不可路由」也算进来（方案 §3.3
  的默认拒绝策略在这里执行）；
- ``resolve`` = Server ready 且工具在目录里，**不查白名单**——它服务的是 Comes 的
  显式执行（按 capability id 指定），白名单只拦自然语言路由，不拦显式调用；
- 全部方法不抛异常（Runtime 已有兜底，但 backend 自己也不让异常出界）。
"""

from __future__ import annotations

from typing import Any

from capability.providers.mcp.client import McpServerClient
from capability.providers.mcp.manager import McpServerManager
from capability.providers.mcp.model import ServerStatus, ToolDescriptor
from capability.providers.mcp.tool import McpFunctionTool
from capability.registry import KIND_MCP, CapabilityProvider


def _manager_of(manager: McpServerManager | None) -> McpServerManager:
    if manager is not None:
        return manager
    from capability.providers.mcp.manager import manager as default_manager

    return default_manager


class McpBackend:
    """kind=mcp 的 ProviderBackend 实现。"""

    kind = KIND_MCP

    def __init__(self, manager: McpServerManager | None = None) -> None:
        self._manager_ref = manager

    def _client(self, provider: CapabilityProvider) -> McpServerClient | None:
        manager = _manager_of(self._manager_ref)
        return manager.client(provider.server_id)

    def _descriptor(self, provider: CapabilityProvider) -> ToolDescriptor | None:
        client = self._client(provider)
        if client is None or not client.ready:
            return None
        return client.tool(provider.remote_tool_name)

    def resolve(self, provider: CapabilityProvider) -> Any:
        descriptor = self._descriptor(provider)
        client = self._client(provider)
        if descriptor is None or client is None:
            return None
        return McpFunctionTool(
            name=provider.tool_name or provider.provider_id,
            descriptor=descriptor,
            client=client,
        )

    def schema(self, provider: CapabilityProvider) -> dict[str, Any]:
        descriptor = self._descriptor(provider)
        if descriptor is None:
            return {}
        return descriptor.input_schema or {}

    def is_live(self, provider: CapabilityProvider) -> bool:
        descriptor = self._descriptor(provider)
        if descriptor is None:
            return False
        client = self._client(provider)
        if client is None:
            return False
        return client.config.tool_allowed(provider.remote_tool_name)

    def status(self, provider: CapabilityProvider) -> dict[str, Any]:
        """Provider 视角的脱敏状态（inventory 快照用，方案 §7.9 的字段面）。"""
        client = self._client(provider)
        server_state = ServerStatus().state
        server: dict[str, Any] = {}
        if client is not None:
            server = client.status_dict()
            server_state = server.get("state", server_state)
        descriptor = self._descriptor(provider)
        return {
            "server_id": provider.server_id,
            "remote_tool": provider.remote_tool_name,
            "tool_state": "ok" if descriptor is not None else "missing",
            "server_state": server_state,
            "last_error": server.get("last_error", ""),
            "call_count": server.get("call_count", 0),
            "failure_count": server.get("failure_count", 0),
            "backoff_seconds": server.get("backoff_seconds", 0.0),
        }


__all__ = ["McpBackend"]
