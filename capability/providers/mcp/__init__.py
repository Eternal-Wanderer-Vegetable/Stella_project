# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP Client 实现：model（数据）、client（单 Server 会话）、manager（多 Server）、
backend（Provider Runtime 接入）、tool（FunctionTool 适配）。

对外入口走包级：``from capability.providers.mcp import manager``（运行时单例）与
``McpBackend``。SDK（``mcp`` 包）是**可选依赖**——只有真实传输会 import 它，
单测与未启用 MCP 的部署完全不需要装。
"""

from capability.providers.mcp.backend import McpBackend
from capability.providers.mcp.manager import McpServerManager, manager

__all__ = [
    "McpBackend",
    "McpServerManager",
    "manager",
]
