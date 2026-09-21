# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP 适配层的单测（方案 §9：命名空间、同名工具、allowlist、只读/副作用策略、
差量同步与 registry.version）。"""

from __future__ import annotations

from capability.adapters.mcp import (
    install_mcp_runtime,
    on_tools_changed,
    reset_mcp_sync,
    sync_mcp_providers,
)
from capability.providers.mcp.client import McpServerClient
from capability.providers.mcp.manager import McpServerManager
from capability.providers.mcp.model import SERVER_READY, ServerConfig
from capability.registry import (
    KIND_ASTRBOT_TOOL,
    KIND_MCP,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
    provider_claim_key,
)
from capability.registry import registry as singleton_registry


def _mcp_provider(capability_id: str, server: str, tool: str, priority: int = 0):
    from capability.providers.mcp.model import mcp_tool_name

    return CapabilityProvider(
        provider_id=f"mcp:{server}:{tool}",
        capability_id=capability_id,
        kind=KIND_MCP,
        tool_name=mcp_tool_name(server, tool),
        server_id=server,
        remote_tool_name=tool,
        priority=priority,
    )


def _capability(capability_id: str, providers: list[CapabilityProvider]) -> Capability:
    return Capability(
        id=capability_id,
        domain="information",
        description=f"{capability_id} 描述",
        examples=["帮我搜一下"],
        providers=providers,
    )


def _ready_client(
    server_id: str,
    tools: list[tuple[str, str]],
    *,
    allowed: list[str] | None = None,
) -> McpServerClient:
    config = ServerConfig(
        server_id=server_id,
        enabled=True,
        transport="stdio",
        command="npx",
        allowed_tools=[name for name, _ in tools] if allowed is None else allowed,
    )
    client = McpServerClient(config)
    client.status.state = SERVER_READY
    client._apply_catalog(
        [(name, f"{name} 描述", {"type": "object", "properties": {}}) for name, _ in tools],
    )
    return client


def _manager_with(*clients: McpServerClient) -> McpServerManager:
    manager = McpServerManager()
    for client in clients:
        manager._clients[client.server_id] = client
    return manager


# ---------- 命名空间 ----------


def test_same_named_tools_on_two_servers_get_distinct_namespaces():
    """两个 Server 的同名远程工具：内部名、认领键都不同，健康度与调用不串线。"""
    reg = CapabilityRegistry()
    reg.register(
        _capability(
            "web.search",
            [_mcp_provider("web.search", "brave", "search"), _mcp_provider("web.search", "bing", "search")],
        ),
    )
    providers = reg.find_providers("web.search")
    names = {p.tool_name for p in providers}
    assert names == {"mcp_brave_search", "mcp_bing_search"}
    keys = {provider_claim_key(p) for p in providers}
    assert keys == {"mcp:brave:search", "mcp:bing:search"}


# ---------- 路由策略 ----------


def test_mcp_provider_routes_only_when_server_ready_and_allowlisted():
    """live = Server ready + 工具在目录 + 在白名单（方案 §3.3 的默认拒绝）。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "search")]))

    # 未接线 Runtime（离线进程）：routable 不过滤进程状态
    assert [c.id for c in reg.routable()] == ["web.search"]

    manager = _manager_with(_ready_client("brave", [("search", "search 描述")]))
    install_mcp_runtime(manager=manager, target=reg)
    assert [c.id for c in reg.routable()] == ["web.search"]

    # Server 掉线：不路由，但声明保留
    manager.client("brave").status.state = "degraded"
    assert reg.routable() == []
    assert reg.get("web.search") is not None
    assert reg.get("web.search").providers  # 声明没被删

    # 恢复后自动点亮（is_live 是查询时判定，不需要重建注册表）
    manager.client("brave").status.state = SERVER_READY
    assert [c.id for c in reg.routable()] == ["web.search"]


def test_empty_allowlist_blocks_routing_but_not_explicit_calls():
    """allowed_tools 为空：全部发现、全部不可路由；显式 resolve 仍可用（方案 §3.3）。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "search")]))
    manager = _manager_with(_ready_client("brave", [("search", "d")], allowed=[]))
    install_mcp_runtime(manager=manager, target=reg)

    assert reg.routable() == []
    runtime = reg._provider_runtime
    tool = runtime.resolve(reg.get("web.search").providers[0])
    assert tool is not None and tool.name == "mcp_brave_search"


def test_unlisted_remote_tool_is_missing_for_backend():
    """目录里没有的远程工具：不可路由、resolve 为 None、走 Comes 的 missing 语义。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "gone")]))
    manager = _manager_with(_ready_client("brave", [("search", "d")]))
    install_mcp_runtime(manager=manager, target=reg)

    assert reg.routable() == []


# ---------- install_mcp_runtime ----------


def test_install_mcp_runtime_wires_registry_and_is_idempotent():
    reg = CapabilityRegistry()
    runtime = install_mcp_runtime(manager=_manager_with(), target=reg)
    assert runtime.backend_of(KIND_ASTRBOT_TOOL) is not None
    assert runtime.backend_of(KIND_MCP) is not None
    assert reg._provider_runtime is runtime

    again = install_mcp_runtime(manager=_manager_with(), target=reg)
    assert again is runtime


# ---------- 差量同步 ----------


def test_sync_removes_vanished_tool_and_restores_it():
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "search")]))
    client = _ready_client("brave", [("search", "d")])
    manager = _manager_with(client)
    install_mcp_runtime(manager=manager, target=reg)

    # 目录里工具消失 → Provider 被摘除、认领键释放
    client._apply_catalog([])
    stats = sync_mcp_providers(target=reg, manager=manager)
    assert stats["removed"] == 1
    assert reg.get("web.search").providers == []
    assert reg.claimed_by_provider(_mcp_provider("web.search", "brave", "search")) is None

    # 工具回来 → 从台账补回
    client._apply_catalog([("search", "d", {"type": "object", "properties": {}})])
    stats = sync_mcp_providers(target=reg, manager=manager)
    assert stats["restored"] == 1
    assert [p.provider_id for p in reg.get("web.search").providers] == ["mcp:brave:search"]


def test_sync_does_not_delete_declarations_when_server_not_ready():
    """Server 没 ready 时目录不可信：不许据此删声明（方案 §6.3 的「不删声明」）。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "search")]))
    client = _ready_client("brave", [("search", "d")])
    client.status.state = "degraded"
    manager = _manager_with(client)
    install_mcp_runtime(manager=manager, target=reg)

    stats = sync_mcp_providers(target=reg, manager=manager)
    assert stats == {"removed": 0, "restored": 0}
    assert reg.get("web.search").providers  # 声明还在


def test_sync_skips_unconfigured_server():
    """Server 没配置：声明留给 Runtime 判定，不删也不补。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "ghost", "search")]))
    manager = _manager_with()  # 没有 ghost
    install_mcp_runtime(manager=manager, target=reg)

    stats = sync_mcp_providers(target=reg, manager=manager)
    assert stats == {"removed": 0, "restored": 0}
    assert reg.get("web.search").providers


def test_sync_never_auto_declares_new_catalog_tools():
    """目录新增的、从未声明过的工具不自动变成 Provider（声明优先，方案 §3.3）。"""
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "search")]))
    client = _ready_client("brave", [("search", "d"), ("brand_new", "d")])
    manager = _manager_with(client)
    install_mcp_runtime(manager=manager, target=reg)

    sync_mcp_providers(target=reg, manager=manager)
    assert [p.remote_tool_name for p in reg.get("web.search").providers] == ["search"]


def test_on_tools_changed_bumps_version():
    reset_mcp_sync()
    v0 = singleton_registry.version
    on_tools_changed("brave")
    assert singleton_registry.version > v0


def test_reset_mcp_sync_clears_ledger():
    reg = CapabilityRegistry()
    reg.register(_capability("web.search", [_mcp_provider("web.search", "brave", "search")]))
    client = _ready_client("brave", [])
    manager = _manager_with(client)
    install_mcp_runtime(manager=manager, target=reg)

    sync_mcp_providers(target=reg, manager=manager)
    assert reg.get("web.search").providers == []  # 被摘了，进了台账

    # 台账清空后，工具回来也不会补（声明已被部署者语义上撤掉——热重载重建后的语义）
    reset_mcp_sync()
    client._apply_catalog([("search", "d", {"type": "object", "properties": {}})])
    stats = sync_mcp_providers(target=reg, manager=manager)
    assert stats["restored"] == 0


# ---------- astrbot 与 mcp 混合能力 ----------


def test_mixed_capability_uses_first_live_provider_schema_in_runtime():
    """同一能力混排两种 provider：Runtime 各自分派，健康度互不影响（方案 §7.2）。"""
    reg = CapabilityRegistry()
    cap = _capability(
        "hybrid.query",
        [
            _mcp_provider("hybrid.query", "brave", "search", priority=10),
            CapabilityProvider(
                provider_id="hybrid.query#local_tool",
                capability_id="hybrid.query",
                kind=KIND_ASTRBOT_TOOL,
                tool_name="local_tool",
            ),
        ],
    )
    reg.register(cap)

    from astrbot_compat.llm.tool import FunctionTool, llm_tools

    llm_tools.add_tool(FunctionTool(name="local_tool", description="x"))

    manager = _manager_with(_ready_client("brave", [("search", "d")]))
    install_mcp_runtime(manager=manager, target=reg)
    assert [c.id for c in reg.routable()] == ["hybrid.query"]

    # MCP 侧掉线，astrbot 侧仍在：能力仍可路由
    manager.client("brave").status.state = "degraded"
    assert [c.id for c in reg.routable()] == ["hybrid.query"]
