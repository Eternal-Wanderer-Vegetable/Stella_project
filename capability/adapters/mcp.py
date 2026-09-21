# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP 工具目录 → Capability Provider 的进程接线与差量同步（方案 §7.8）。

四个入口，全部只该发生在 **Bot 进程**：

1. ``install_mcp_runtime()``：把 AstrbotToolBackend + McpBackend 装进 Provider
   Runtime，再把 Runtime 装进注册表。之后 ``routable()`` / ``resolve_tools`` /
   ``build_tool_tasks`` 都按 kind 分派，不再各自去查 ``llm_tools``。
2. ``start_mcp_runtime()``：读 ``config/mcp.toml``、启动 Manager、完成初始发现。
   **必须发生在 capability bootstrap 之前**：装配时 ``routable()`` 的统计要把
   MCP Provider 的真实可用性算进去。
3. ``sync_mcp_providers()``：tools/list 的差量对齐（启动一次 + 每次
   tools/list_changed 一次，见 ``on_tools_changed``）。远程工具从目录里消失的
   Provider 从能力上摘掉（连带认领键）；重新出现时补回。摘除不等于删声明——
   磁盘上的 TOML 一字不动，进程内用「声明台账」记录摘掉过什么，工具回来才补得回。
4. ``close_mcp_runtime()``：停机收尾。

边界（方案 §7.8 / §10）：MCP Manager 的生命周期**不**绑定 AstrBot 插件热重载——
插件重载重建的是混合 Capability 声明，声明重新解析后由 Runtime 在查询时重新判定
live 状态；Manager 连着的外部进程/端点与插件注册表没有从属关系，跟着插件重启只会
平白断线。热重载重建声明后由 ``reset_mcp_sync()`` + ``sync_mcp_providers()``
重建台账。
"""

from __future__ import annotations

from typing import Any

from capability.providers import AstrbotToolBackend, ProviderRuntime, provider_runtime
from capability.providers.mcp.backend import McpBackend
from capability.providers.mcp.manager import McpServerManager
from capability.providers.mcp.manager import manager as default_manager
from capability.providers.mcp.model import SERVER_READY
from capability.registry import (
    KIND_MCP,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry

# 摘掉的声明先记在这里（provider_id → 声明本体），工具回到目录时按它补回。
# 进程内状态，磁盘声明才是跨重启的真相；bootstrap / 热重载时整体重建。
_removed_declarations: dict[str, CapabilityProvider] = {}


def _logger():
    from nonebot import logger

    return logger


def _settings() -> Any:
    from config import settings

    return settings


def install_mcp_runtime(
    manager: McpServerManager | None = None,
    target: CapabilityRegistry | None = None,
    runtime: ProviderRuntime | None = None,
) -> ProviderRuntime:
    """进程接线：注册两个 backend 并把 Runtime 装进注册表。幂等，可重复调用。

    ``runtime`` 参数供测试隔离（默认用模块级单例——单测里用 ``reset()`` 清理）。
    """
    runtime = runtime if runtime is not None else provider_runtime
    runtime.reset()
    runtime.register_backend(AstrbotToolBackend())
    runtime.register_backend(McpBackend(manager))
    (target if target is not None else _default_registry).set_provider_runtime(runtime)
    return runtime


async def start_mcp_runtime(manager: McpServerManager | None = None) -> dict[str, str]:
    """读配置并启动 MCP Manager，返回 ``server_id → 初始状态``。

    ``MCP_ENABLED=false``（默认）时直接返回空 dict——MCP 整层不启动，Stella 的
    其余行为一字不变（方案 §6.2：首次启用必须由部署者显式配置）。
    """
    mgr = manager if manager is not None else default_manager
    if not bool(_settings().MCP_ENABLED):
        _logger().info("🔌 [MCP] MCP_ENABLED=false，MCP 层未启动")
        return {}
    mgr.tools_changed_callback = on_tools_changed
    return await mgr.start()


async def close_mcp_runtime(manager: McpServerManager | None = None) -> None:
    """停机钩子：先停接受新调用，再逐 Server 收尾（client 内部保证顺序）。"""
    mgr = manager if manager is not None else default_manager
    await mgr.close()


def reset_mcp_sync() -> None:
    """清空声明台账。bootstrap / 热重载重建声明后调用——台账只服务「本轮进程里
    摘掉过什么」，跨重建保留会把用户已删掉的声明又补回来。"""
    _removed_declarations.clear()


def sync_mcp_providers(
    target: CapabilityRegistry | None = None,
    manager: McpServerManager | None = None,
) -> dict[str, int]:
    """已声明的 MCP Provider ↔ Manager 目录做一次差量对齐（幂等）。

    - 工具在目录里、Provider 在能力上：无事；
    - 工具不在目录里、Provider 在能力上：**摘除** Provider 并释放认领，同时记入
      台账（Server 未 ready 时不据目录删——目录为空更可能是没连上而不是工具没了）；
    - 工具在目录里、Provider 不在能力上但**在台账里**：补回。

    目录里新增的、从未声明过的工具**不**自动变成 Provider（方案 §3.3：声明优先，
    缺省不路由）；它们只出现在 Manager 目录与诊断清单里。
    """
    reg = target if target is not None else _default_registry
    mgr = manager if manager is not None else default_manager
    stats = {"removed": 0, "restored": 0}

    # 先做快照台账补全：当前在册的 MCP 声明都记一份形态（幂等，已记的不覆盖）
    for capability in reg.all():
        for provider in capability.providers:
            if provider.kind == KIND_MCP and provider.provider_id not in _removed_declarations:
                _removed_declarations[provider.provider_id] = provider

    for capability in reg.all():
        declared = [p for p in capability.providers if p.kind == KIND_MCP]
        # server 集合必须包含台账里的：全部 Provider 被摘光的能力也要等在原地，
        # 否则工具恢复时没有任何循环会跑到它头上
        ledger = [
            p for p in _removed_declarations.values() if p.capability_id == capability.id
        ]
        servers = {p.server_id for p in [*declared, *ledger]}
        for server_id in sorted(servers):
            client = mgr.client(server_id)
            if client is None:
                continue  # Server 未配置：留给 Runtime 判定，不删声明
            if client.status.state != SERVER_READY:
                continue  # 目录不可信（可能只是没连上），不动
            live_remote = {d.name for d in client.catalog()}
            for provider in declared:
                if provider.server_id != server_id:
                    continue
                if provider.remote_tool_name not in live_remote and reg.remove_provider(
                    capability.id, provider.provider_id,
                ):
                    stats["removed"] += 1
                    _logger().warning(
                        f"⚠️ [MCP] {capability.id} 的 provider {provider.provider_id} "
                        f"指向的工具已不在 {server_id} 的目录里，已摘除（目录恢复后自动补回）",
                    )
            # 补回：台账里有、能力上没有、且工具确实回来了
            for provider_id, removed in list(_removed_declarations.items()):
                if (
                    removed.capability_id == capability.id
                    and removed.server_id == server_id
                    and removed.remote_tool_name in live_remote
                    and not any(
                        p.provider_id == provider_id for p in capability.providers
                    )
                ) and reg.add_provider(capability.id, removed):
                    stats["restored"] += 1
                    _removed_declarations.pop(provider_id, None)
                    _logger().info(
                        f"🔌 [MCP] {capability.id} 的 provider {provider_id} "
                        f"已随 {server_id} 目录恢复而补回",
                    )

    if stats["removed"] or stats["restored"]:
        reg.bump_version()
    return stats


def on_tools_changed(server_id: str) -> None:
    """tools/list_changed 通知的落点（装在 ``manager.tools_changed_callback`` 上）。

    任何失败都必须吞掉：这是聊天链路之外的通知路径，坏 here 不能影响工具调用本身。
    """
    try:
        sync_mcp_providers(manager=default_manager)
    except Exception as e:
        _logger().warning(f"⚠️ [MCP] {server_id} 的工具目录同步失败（跳过）: {e}")
    else:
        # 目录内容变了（哪怕没动 Provider），Router 的候选集缓存也要重算一次
        _default_registry.bump_version()


__all__ = [
    "close_mcp_runtime",
    "install_mcp_runtime",
    "on_tools_changed",
    "reset_mcp_sync",
    "start_mcp_runtime",
    "sync_mcp_providers",
]
