# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP Tool → FunctionTool 适配器（方案 §7.5）。

每个 live 的 MCP 工具在 Comes 眼里就是一个普通的 ``FunctionTool``：``handler``
留空、``call()`` 被实现为一次 ``manager.call_tool``——这正是
``astrbot_compat/llm/tool.py::FunctionTool.call`` 预留的扩展点，``execute_tool``
对它的超时、异常与结果归一全部照旧复用（方案 §7.6：MCP 走同一条执行路径）。

边界纪律：

- ``name`` 是内部命名空间名（``mcp_<server>_<tool>``），与 ``llm_tools`` 及其他
  Server 的同名工具天然隔离；
- ``description`` 是**不可信文本**：截断后才进 ToolSet（长度在 model 层已剪）；
- ``call()`` 的失败统一转成 ``error: ...`` 文本（McpClientError 已脱敏），
  绝不把认证头、命令行或完整异常栈送回 Stella。
"""

from __future__ import annotations

from typing import Any

from astrbot_compat.llm.tool import FunctionTool
from capability.providers.mcp.client import McpClientError, McpServerClient
from capability.providers.mcp.model import ToolDescriptor

EMPTY_OBJECT_SCHEMA = {"type": "object", "properties": {}}


class McpFunctionTool(FunctionTool):
    """一个远程 MCP 工具的本地替身。schema 缺省时规范化为空 object schema。"""

    def __init__(
        self,
        *,
        name: str,
        descriptor: ToolDescriptor,
        client: McpServerClient,
    ) -> None:
        super().__init__(
            name=name,
            description=descriptor.description,
            parameters=descriptor.input_schema or EMPTY_OBJECT_SCHEMA,
        )
        self._descriptor = descriptor
        self._client = client

    @property
    def remote_tool_name(self) -> str:
        return self._descriptor.name

    @property
    def server_id(self) -> str:
        return self._client.server_id

    async def call(self, context: Any, **kwargs: Any) -> Any:
        _ = context  # MCP 工具不依赖聊天事件；参数全量透传给远程 Server
        try:
            return await self._client.call_tool(
                self._descriptor.name,
                kwargs,
            )
        except McpClientError as e:
            # execute_tool 会把异常转成 "error: ..." 回喂模型；这里只保证文本已脱敏
            return f"error: {e}"
        except Exception:  # 兜底：任何漏网异常也不得带出栈信息
            return f"error: MCP 工具 {self._descriptor.name} 调用失败"


__all__ = ["EMPTY_OBJECT_SCHEMA", "McpFunctionTool"]
