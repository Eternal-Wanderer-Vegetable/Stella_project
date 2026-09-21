# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP Server Manager：多 Server 的生命周期、故障隔离与统一调用入口（方案 §7.4）。

Manager 是 MCP 在 Stella 里的**唯一**运行时入口：backend、inventory、deploy CLI
都通过它（或它持有的 client）看 Server，没有第二扇门——状态只有一份，三处才不会
各说各话（与 capability/inventory.py 的「同一数据源」是同一条纪律）。

故障隔离是硬约束（方案 §7.6）：一个 Server 连不上、调用炸了、甚至配置写错了，
都只表现为那个 Server 的 Provider 不可用；Comes、主 Pipeline 与其余 Server 照常。
所以这里没有一条路径会向外抛 MCP 的异常——``start`` 逐 Server 收编异常，
``call_tool`` 把失败翻译成 :class:`McpClientError` 交由 FunctionTool 层转成
``error: ...`` 文本。

``manager`` 是模块级单例（与 ``llm_tools`` / ``registry`` 同理，见
capability/registry.py 的 docstring）。**不随 AstrBot 插件热重载重启**（方案 §7.8）：
它连的是外部进程/端点，与插件注册表没有从属关系。
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from capability.providers.mcp.client import (
    McpClientError,
    McpServerClient,
    SessionFactory,
)
from capability.providers.mcp.model import (
    SERVER_DEGRADED,
    SERVER_DISABLED,
    SERVER_READY,
    ServerConfig,
    load_mcp_configs,
)


class McpServerManager:
    """持有全部 McpServerClient；负责配置装载、启停编排与状态汇总。"""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._clients: dict[str, McpServerClient] = {}
        self._configs: dict[str, ServerConfig] = {}
        self._started = False
        # 会话工厂（测试注入点）；None = client 用默认 SDK 工厂
        self._session_factory = session_factory
        # tools/list_changed 通知的下游（capability/adapters/mcp.py 在启动时装上）
        self.tools_changed_callback: Any = None

    # ---------- 配置 ----------

    def load_config(self, path: Path | None = None) -> dict[str, ServerConfig]:
        """（重新）读配置文件。只记录，不改变已在运行的 Server。"""
        self._configs = load_mcp_configs(path)
        return self._configs

    def configs(self) -> dict[str, ServerConfig]:
        return dict(self._configs)

    # ---------- 启停 ----------

    async def start(self, path: Path | None = None) -> dict[str, str]:
        """按配置启动全部 enabled Server，返回 ``server_id → 初始状态``。

        必须先读 :attr:`MCP_ENABLED <config.settings.MCP_ENABLED>`（由调用方判断，
        本方法不读 settings 以便单测）。单个 Server 启动失败只记日志与状态，
        不拦其余 Server，也不抛出（方案 §7.6 的故障隔离）。
        """
        self.load_config(path)
        self._clients = {}
        results: dict[str, str] = {}
        for server_id, config in self._configs.items():
            if not config.enabled:
                results[server_id] = SERVER_DISABLED
                continue
            problems = config.validate()
            if problems:
                client = self._new_client(config)
                client.status.state = SERVER_DEGRADED
                client.status.last_error = "; ".join(problems)
                self._clients[server_id] = client
                results[server_id] = client.status.state
                _logger().warning(
                    f"⚠️ [MCP] Server {server_id} 配置非法，保持 degraded: {problems}",
                )
                continue
            client = self._new_client(config)
            self._clients[server_id] = client
            try:
                await client.start()
            except Exception as e:  # client.start 自身不抛；这里是最后一道保险
                client.status.state = SERVER_DEGRADED
                client.status.last_error = str(e)
            results[server_id] = client.status.state
        self._started = True
        ready = [sid for sid, st in results.items() if st == SERVER_READY]
        degraded = [sid for sid, st in results.items() if st not in (SERVER_READY, SERVER_DISABLED)]
        _logger().info(
            f"🔌 [MCP] 启动完成：{len(ready)} ready / {len(degraded)} degraded"
            f"（{', '.join(f'{sid}={st}' for sid, st in sorted(results.items()))}）",
        )
        return results

    async def close(self) -> None:
        """全部 Server 收尾（bot 关闭钩子调用；幂等）。"""
        for client in self._clients.values():
            try:
                await client.close()
            except Exception as e:
                _logger().warning(f"⚠️ [MCP] Server {client.server_id} 关闭异常: {e}")
        self._clients = {}
        self._started = False

    def _new_client(self, config: ServerConfig) -> McpServerClient:
        client = McpServerClient(config, session_factory=self._session_factory)
        client.tools_changed_callback = self._on_tools_changed
        return client

    def _on_tools_changed(self, server_id: str) -> None:
        callback = self.tools_changed_callback
        if callback is None:
            return
        with contextlib.suppress(Exception):
            callback(server_id)

    # ---------- 查询与调用 ----------

    def client(self, server_id: str) -> McpServerClient | None:
        return self._clients.get(server_id)

    def list_servers(self) -> list[str]:
        return sorted(self._clients)

    def status(self) -> dict[str, dict[str, Any]]:
        """全部 Server 的脱敏状态（inventory / 状态接口 / CLI 共用这一份）。"""
        return {sid: c.status_dict() for sid, c in sorted(self._clients.items())}

    def catalog(self, server_id: str) -> list[Any]:
        client = self._clients.get(server_id)
        return client.catalog() if client is not None else []

    async def call_tool(
        self,
        server_id: str,
        remote_tool: str,
        arguments: dict[str, Any] | None,
        timeout: float | None = None,
    ) -> str:
        """调用指定 Server 的指定远程工具。失败抛 McpClientError（已脱敏）。

        允许在 Server 未 ready 时抛错而不是排队等待：Comes 的调用有自己的任务级
        超时，让一次坏调用快速失败好过占着超时窗口。
        """
        client = self._clients.get(server_id)
        if client is None:
            raise McpClientError(f"MCP server {server_id} 未配置")
        return await client.call_tool(remote_tool, arguments, timeout=timeout)


def _logger():
    from nonebot import logger

    return logger


# 模块级单例。必须模块级——理由同 capability.registry 的 docstring。
manager = McpServerManager()


__all__ = [
    "McpServerManager",
    "manager",
]
