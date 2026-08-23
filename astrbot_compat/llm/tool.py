# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""函数工具（对齐 astrbot.core.agent.tool 与 provider.func_tool_manager）。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("astrbot_compat.llm.tool")


@dataclass
class ToolSchema:
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}},
    )


@dataclass
class FunctionTool(ToolSchema):
    """一个可调用的工具。`handler` 优先于 `call()`。"""

    handler: Callable[..., Any] | None = None
    handler_module_path: str | None = None
    active: bool = True
    is_background_task: bool = False

    def __repr__(self) -> str:
        return (
            f"FuncTool(name={self.name}, parameters={self.parameters}, "
            f"description={self.description})"
        )

    async def call(self, context: Any, **kwargs: Any) -> Any:
        """没有 handler 的工具（如 MCP）需要自己实现这个。"""
        _ = (context, kwargs)
        raise NotImplementedError(
            "FunctionTool.call() 需由子类实现，或设置 handler 字段",
        )

    def openai_schema(self, omit_empty_parameter_field: bool = False) -> dict:
        body: dict[str, Any] = {"name": self.name, "description": self.description}
        props = (self.parameters or {}).get("properties") or {}
        if props or not omit_empty_parameter_field:
            body["parameters"] = self.parameters
        return {"type": "function", "function": body}


# 上游历史别名
FuncTool = FunctionTool


@dataclass
class ToolSet:
    """一组工具。`func_tool=` 参数收的就是它。"""

    tools: list[FunctionTool] = field(default_factory=list)

    def empty(self) -> bool:
        return not self.tools

    def add_tool(self, tool: FunctionTool) -> None:
        """同名去重：active 的胜出，都 active 时后来者胜出（对齐上游）。"""
        for i, existing in enumerate(self.tools):
            if existing.name != tool.name:
                continue
            if existing.active and not tool.active:
                return
            self.tools[i] = tool
            return
        self.tools.append(tool)

    def remove_tool(self, name: str) -> None:
        self.tools = [t for t in self.tools if t.name != name]

    def get_tool(self, name: str) -> FunctionTool | None:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def get_light_tool_set(self) -> ToolSet:
        """只保留名字与描述，用于 skills-like 场景。"""
        return ToolSet(
            tools=[
                FunctionTool(name=t.name, description=t.description)
                for t in self.tools
            ],
        )

    def get_param_only_tool_set(self) -> ToolSet:
        return ToolSet(
            tools=[
                FunctionTool(name=t.name, parameters=t.parameters) for t in self.tools
            ],
        )

    def add_func(
        self,
        name: str,
        func_args: list[dict],
        desc: str,
        handler: Callable[..., Any],
    ) -> None:
        """按上游的 (name, func_args, desc, handler) 形态登记一个工具。"""
        params: dict[str, Any] = {"type": "object", "properties": {}}
        required: list[str] = []
        for param in func_args or []:
            spec = {
                "type": param.get("type", "string"),
                "description": param.get("description", ""),
            }
            if "items" in param:
                spec["items"] = param["items"]
            params["properties"][param["name"]] = spec
            if param.get("required", True):
                required.append(param["name"])
        if required:
            params["required"] = required
        self.add_tool(
            FunctionTool(
                name=name,
                description=desc,
                parameters=params,
                handler=handler,
            ),
        )

    def remove_func(self, name: str) -> None:
        self.remove_tool(name)

    def get_func(self, name: str) -> FunctionTool | None:
        return self.get_tool(name)

    @property
    def func_list(self) -> list[FunctionTool]:
        return self.tools

    def openai_schema(self, omit_empty_parameter_field: bool = False) -> list[dict]:
        return [t.openai_schema(omit_empty_parameter_field) for t in self.tools]

    # 上游的历史命名
    def get_func_desc_openai_style(
        self,
        omit_empty_parameter_field: bool = False,
    ) -> list[dict]:
        return self.openai_schema(omit_empty_parameter_field)

    def names(self) -> list[str]:
        return [t.name for t in self.tools]

    def merge(self, other: ToolSet) -> None:
        for t in other.tools:
            self.add_tool(t)

    def __len__(self) -> int:
        return len(self.tools)

    def __bool__(self) -> bool:
        return bool(self.tools)

    def __iter__(self):
        return iter(self.tools)

    def __repr__(self) -> str:
        return f"ToolSet(tools={self.names()})"

    __str__ = __repr__


class FunctionToolManager(ToolSet):
    """全局工具注册表。`context.get_llm_tool_manager()` 返回的就是它。

    上游是 `FuncCall`，本身也是一个 ToolSet，所以直接继承。
    """

    def get_full_tool_set(self) -> ToolSet:
        """取当前激活的工具集合。"""
        return ToolSet(tools=[t for t in self.tools if t.active])

    def activate_llm_tool(self, name: str) -> bool:
        tool = self.get_tool(name)
        if tool is None:
            return False
        tool.active = True
        return True

    def deactivate_llm_tool(self, name: str) -> bool:
        tool = self.get_tool(name)
        if tool is None:
            return False
        tool.active = False
        return True

    def is_builtin_tool(self, name: str) -> bool:
        _ = name
        return False

    def iter_builtin_tools(self) -> list[FunctionTool]:
        return []


# 上游别名
FuncCall = FunctionToolManager


class BaseFunctionToolExecutor:
    """工具执行器基类（上游是 Generic，这里保留形状即可）。"""

    @classmethod
    async def execute(cls, tool: FunctionTool, run_context: Any, **tool_args: Any):
        raise NotImplementedError


# 模块级单例：与 star_handlers_registry 同理，必须是模块级，
# 否则多 import 路径会让注册表分裂。
llm_tools = FunctionToolManager()


__all__ = [
    "BaseFunctionToolExecutor",
    "FuncCall",
    "FuncTool",
    "FunctionTool",
    "FunctionToolManager",
    "ToolSchema",
    "ToolSet",
    "llm_tools",
]
