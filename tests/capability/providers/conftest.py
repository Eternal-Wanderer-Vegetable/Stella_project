# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP client / manager 单测的共享夹具：会话鸭子 + 注入式工厂。

FakeSession 刻意按 ``capability/providers/mcp/client.py`` 模块 docstring 定义的
**接缝形状**实现（initialize / list_tools / call_tool / set_tools_changed_callback），
不 import MCP SDK——SDK 在测试环境里是可选依赖，缺了也必须全绿。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from capability.providers.mcp.model import ServerConfig


class FakeSession:
    """脚本化的 MCP 会话替身。"""

    def __init__(self) -> None:
        self.tools: list[Any] = []
        self.calls: list[tuple[str, dict]] = []
        self.initialize_calls = 0
        self.list_calls = 0
        self.close_calls = 0
        self.initialize_error: Exception | None = None
        self.list_error: Exception | None = None
        self.default_result: Any = SimpleNamespace(
            content=[SimpleNamespace(text="ok")],
            isError=False,
        )
        # 工具名 → 抛出的异常或返回值（覆盖 default_result）
        self.scripted: dict[str, Any] = {}
        self._tools_changed_cb: Any = None

    def set_tools_changed_callback(self, cb: Any) -> None:
        self._tools_changed_cb = cb

    def fire_tools_changed(self) -> None:
        if self._tools_changed_cb is not None:
            self._tools_changed_cb()

    async def initialize(self) -> Any:
        self.initialize_calls += 1
        if self.initialize_error is not None:
            raise self.initialize_error
        return SimpleNamespace(serverInfo=SimpleNamespace(name="fake", version="0"))

    async def list_tools(self) -> Any:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return SimpleNamespace(tools=list(self.tools))

    async def call_tool(self, name: str, arguments: dict) -> Any:
        self.calls.append((name, dict(arguments or {})))
        item = self.scripted.get(name)
        if isinstance(item, Exception):
            raise item
        if item is not None:
            return item
        return self.default_result

    # ---------- 测试辅助 ----------

    def add_tool(
        self,
        name: str,
        description: str = "",
        input_schema: Any = None,
    ) -> None:
        self.tools.append(
            SimpleNamespace(
                name=name,
                description=description,
                inputSchema=(
                    input_schema
                    if input_schema is not None
                    else {"type": "object", "properties": {}}
                ),
            ),
        )

    def text_result(self, *texts: str) -> Any:
        return SimpleNamespace(
            content=[SimpleNamespace(text=t) for t in texts],
            isError=False,
        )

    def error_result(self, text: str) -> Any:
        return SimpleNamespace(content=[SimpleNamespace(text=text)], isError=True)


@pytest.fixture
def fake_session() -> FakeSession:
    return FakeSession()


@pytest.fixture
def session_factory(fake_session: FakeSession):
    """``factory(config)`` 上下文管理器工厂，永远 yield 同一个 FakeSession。

    ``factory.session`` 是那个会话对象（预置工具、脚本化调用用）；
    ``factory.sessions`` 记录每次进入，供断言连接次数。
    """

    entered: list[FakeSession] = []

    @asynccontextmanager
    async def factory(config: ServerConfig):
        entered.append(fake_session)
        try:
            yield fake_session
        finally:
            fake_session.close_calls += 1

    factory.sessions = entered  # type: ignore[attr-defined]
    factory.session = fake_session  # type: ignore[attr-defined]
    yield factory


@pytest.fixture
def stdio_config() -> ServerConfig:
    return ServerConfig(
        server_id="brave",
        enabled=True,
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-brave-search"],
        allowed_tools=["search"],
        connect_timeout=1.0,
        call_timeout=1.0,
        reconnect_base_seconds=0.02,
        reconnect_max_seconds=0.1,
    )


@pytest.fixture
def http_config() -> ServerConfig:
    return ServerConfig(
        server_id="remote",
        enabled=True,
        transport="streamable_http",
        url="https://mcp.example.com/mcp",
        auth_env="STELLA_MCP_TEST_TOKEN",
        allowed_tools=["search", "fetch"],
        connect_timeout=1.0,
        call_timeout=1.0,
        reconnect_base_seconds=0.02,
        reconnect_max_seconds=0.1,
    )


async def wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """轮询 await 直到条件成立或超时（重连/刷新是后台任务，不能假设立即完成）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    return condition()
