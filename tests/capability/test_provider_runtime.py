# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Provider Runtime 的契约单测（方案 §9：AstrBot/MCP backend 的 resolve、schema、
live、status 契约）。"""

from __future__ import annotations

from capability.providers import (
    AstrbotToolBackend,
    ProviderBackend,
    ProviderRuntime,
    provider_runtime,
)
from capability.providers.mcp.backend import McpBackend
from capability.providers.mcp.client import McpServerClient
from capability.providers.mcp.manager import McpServerManager
from capability.providers.mcp.model import SERVER_READY, ServerConfig
from capability.registry import (
    KIND_ASTRBOT_TOOL,
    KIND_MCP,
    CapabilityProvider,
    provider_claim_key,
)


def _astrbot_provider(tool: str):
    return CapabilityProvider(
        provider_id=f"c#{tool}", capability_id="c", kind=KIND_ASTRBOT_TOOL, tool_name=tool,
    )


def _mcp_provider(server: str = "brave", tool: str = "search", tool_name: str = "mcp_brave_search"):
    return CapabilityProvider(
        provider_id=f"mcp:{server}:{tool}",
        capability_id="c",
        kind=KIND_MCP,
        tool_name=tool_name,
        server_id=server,
        remote_tool_name=tool,
    )


def _register_llm_tool(name: str, *, active: bool = True):
    from astrbot_compat.llm.tool import FunctionTool, llm_tools

    tool = FunctionTool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    tool.active = active
    llm_tools.add_tool(tool)
    return tool


# ---------- provider_claim_key ----------


def test_claim_key_is_backend_aware():
    assert provider_claim_key(_astrbot_provider("get_weather")) == "get_weather"
    assert provider_claim_key(_mcp_provider()) == "mcp:brave:search"
    # 同名远程工具、不同 Server：键不同，互不认领（方案 §6.1 的唯一性要求）
    assert provider_claim_key(_mcp_provider(server="other")) != provider_claim_key(_mcp_provider())


def test_claim_key_none_without_identifiers():
    assert provider_claim_key(_astrbot_provider("")) is None
    assert provider_claim_key(_mcp_provider(server="brave", tool="")) is None
    assert provider_claim_key(_mcp_provider(server="", tool="search")) is None


# ---------- AstrbotToolBackend ----------


def test_astrbot_backend_resolves_live_tools():
    tool = _register_llm_tool("get_weather")
    backend = AstrbotToolBackend()

    assert backend.resolve(_astrbot_provider("get_weather")) is tool
    assert backend.schema(_astrbot_provider("get_weather"))["required"] == ["q"]
    assert backend.is_live(_astrbot_provider("get_weather")) is True


def test_astrbot_backend_missing_and_inactive_tools():
    _register_llm_tool("off", active=False)
    backend = AstrbotToolBackend()

    assert backend.resolve(_astrbot_provider("absent")) is None
    assert backend.is_live(_astrbot_provider("absent")) is False
    assert backend.resolve(_astrbot_provider("off")) is None
    assert backend.is_live(_astrbot_provider("off")) is False
    assert backend.schema(_astrbot_provider("absent")) == {}


# ---------- McpBackend ----------


def _ready_manager(*, allowed: list[str] | None = None) -> tuple[McpServerManager, McpServerClient]:
    config = ServerConfig(
        server_id="brave",
        enabled=True,
        transport="stdio",
        command="npx",
        allowed_tools=["search"] if allowed is None else allowed,
    )
    client = McpServerClient(config)
    client.status.state = SERVER_READY
    client._apply_catalog(
        [
            (
                "search",
                "web search",
                {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "required": ["q"],
                },
            ),
        ],
    )
    manager = McpServerManager()
    manager._clients["brave"] = client
    return manager, client


def test_mcp_backend_resolve_and_schema():
    manager, _ = _ready_manager()
    backend = McpBackend(manager)

    tool = backend.resolve(_mcp_provider())
    assert tool is not None
    assert tool.name == "mcp_brave_search"
    assert tool.remote_tool_name == "search"
    assert tool.parameters["required"] == ["q"]
    assert backend.schema(_mcp_provider())["type"] == "object"


def test_mcp_backend_is_live_respects_allowlist():
    """is_live 服务路由：白名单外（含空白名单）不可路由；resolve 服务显式调用，不受白名单限制。"""
    manager, _ = _ready_manager()
    backend = McpBackend(manager)
    assert backend.is_live(_mcp_provider()) is True

    empty_manager, _ = _ready_manager(allowed=[])
    empty_backend = McpBackend(empty_manager)
    assert empty_backend.is_live(_mcp_provider()) is False
    # 空白名单下仍可显式解析调用（方案 §3.3：保留发现与显式调用能力）
    assert empty_backend.resolve(_mcp_provider()) is not None


def test_mcp_backend_not_ready_is_not_live():
    manager, client = _ready_manager()
    client.status.state = "degraded"
    backend = McpBackend(manager)
    assert backend.is_live(_mcp_provider()) is False
    assert backend.resolve(_mcp_provider()) is None
    assert backend.schema(_mcp_provider()) == {}


def test_mcp_backend_status_is_structured_and_redacted():
    manager, client = _ready_manager()
    client.status.last_error = "boom http://10.0.0.1?token=abc"
    backend = McpBackend(manager)

    status = backend.status(_mcp_provider())
    assert status["server_id"] == "brave"
    assert status["remote_tool"] == "search"
    assert status["tool_state"] == "ok"
    assert status["server_state"] == SERVER_READY
    assert "token=abc" not in status["last_error"]


# ---------- ProviderRuntime 分派 ----------


def test_runtime_dispatches_by_kind():
    runtime = ProviderRuntime()
    runtime.register_backend(AstrbotToolBackend())
    runtime.register_backend(McpBackend(_ready_manager()[0]))

    assert runtime.backend_of(KIND_ASTRBOT_TOOL) is not None
    assert runtime.backend_of(KIND_MCP) is not None
    assert runtime.resolve(_astrbot_provider("absent")) is None
    assert runtime.resolve(_mcp_provider()).name == "mcp_brave_search"
    assert runtime.is_live(_mcp_provider()) is True
    assert bool(runtime)


def test_runtime_without_backend_passes_everything_through():
    """没接线的 kind 全部放行（离线进程的缺省语义，对齐探针缺省）。"""
    runtime = ProviderRuntime()
    assert not runtime
    assert runtime.is_live(_astrbot_provider("anything")) is True
    assert runtime.is_live(_mcp_provider()) is True
    assert runtime.schema(_mcp_provider()) == {}
    assert runtime.status(_mcp_provider()) == {}
    assert runtime.resolve(_mcp_provider()) is None


def test_runtime_swallows_backend_exceptions():
    """backend 抛异常不得外溢：is_live 按放行处理，schema/status 回空。"""
    runtime = ProviderRuntime()

    class _Boom:
        kind = KIND_MCP

        def resolve(self, provider):
            raise RuntimeError("boom")

        def schema(self, provider):
            raise RuntimeError("boom")

        def is_live(self, provider):
            raise RuntimeError("boom")

        def status(self, provider):
            raise RuntimeError("boom")

    runtime.register_backend(_Boom())
    assert runtime.is_live(_mcp_provider()) is True
    assert runtime.schema(_mcp_provider()) == {}
    assert runtime.status(_mcp_provider()) == {}


def test_runtime_replaces_same_kind_and_reset_clears():
    runtime = ProviderRuntime()
    runtime.register_backend(McpBackend(_ready_manager()[0]))
    replacement = McpBackend(_ready_manager()[0])
    runtime.register_backend(replacement)
    assert runtime.backend_of(KIND_MCP) is replacement

    runtime.reset()
    assert not runtime
    assert runtime.backend_of(KIND_MCP) is None


def test_runtime_singleton_is_shared():
    import capability.providers as pkg

    assert pkg.provider_runtime is provider_runtime


def test_backends_satisfy_the_protocol():
    """两个实现都满足 ProviderBackend 协议（runtime_checkable 鸭子检查）。"""
    assert isinstance(AstrbotToolBackend(), ProviderBackend)
    assert isinstance(McpBackend(), ProviderBackend)
