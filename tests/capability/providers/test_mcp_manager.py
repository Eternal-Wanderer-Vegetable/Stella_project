# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""McpServerManager 的单测（方案 §9：多 Server 隔离、故障隔离、状态转移、
shutdown、stdio 不经过 shell）。"""

from __future__ import annotations

import pytest

from capability.providers.mcp.manager import McpServerManager
from capability.providers.mcp.model import (
    SERVER_DEGRADED,
    SERVER_DISABLED,
    SERVER_READY,
    SERVER_STOPPED,
    load_mcp_configs,
)
from tests.capability.providers.conftest import wait_for


def _toml(tmp_path, text: str):
    path = tmp_path / "mcp.toml"
    path.write_text(text, encoding="utf-8")
    return path


# ---------- 配置装载 ----------


def test_load_config_parses_plan_example(tmp_path):
    """方案 §6.2 的示例配置要能原样解析。"""
    path = _toml(
        tmp_path,
        """
[servers.brave]
enabled = true
transport = "streamable_http"
url = "https://example.com/mcp"
auth_env = "STELLA_MCP_BRAVE_TOKEN"
connect_timeout = 10
call_timeout = 30
allowed_tools = ["search"]

[servers.filesystem]
enabled = false
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "D:/data"]
env = {}
allowed_tools = ["read_file", "list_directory"]
""",
    )
    configs = load_mcp_configs(path)
    assert set(configs) == {"brave", "filesystem"}

    brave = configs["brave"]
    assert brave.enabled
    assert brave.transport == "streamable_http"
    assert brave.url == "https://example.com/mcp"
    assert brave.auth_env == "STELLA_MCP_BRAVE_TOKEN"  # 只存变量名，没有值
    assert brave.allowed_tools == ["search"]

    fs = configs["filesystem"]
    assert not fs.enabled
    assert fs.command == "npx"
    assert fs.args == ["-y", "@modelcontextprotocol/server-filesystem", "D:/data"]


def test_load_config_missing_file_is_empty(tmp_path):
    assert load_mcp_configs(tmp_path / "nope.toml") == {}


def test_load_config_broken_section_is_skipped(tmp_path):
    path = _toml(
        tmp_path,
        """
[servers.good]
enabled = true
transport = "streamable_http"
url = "https://example.com/mcp"

[servers.bad]
enabled = "yes sir"
transport = 3
""",
    )
    configs = load_mcp_configs(path)
    assert set(configs) == {"good", "bad"}  # 段不炸文件
    assert configs["good"].validate() == []
    assert configs["bad"].validate()  # 类型乱的字段落进 validate 的问题清单


# ---------- 启停与故障隔离 ----------


async def test_start_starts_enabled_and_skips_disabled(
    tmp_path,
    session_factory,
    fake_session,
):
    fake_session.add_tool("search")
    path = _toml(
        tmp_path,
        """
[servers.on]
enabled = true
transport = "stdio"
command = "npx"

[servers.off]
enabled = false
transport = "stdio"
command = "npx"
""",
    )
    manager = McpServerManager(session_factory=session_factory)
    results = await manager.start(path)

    assert results["on"] == SERVER_READY
    assert results["off"] == SERVER_DISABLED
    assert manager.client("on").ready
    assert manager.catalog("on")[0].name == "search"
    assert await manager.close() is None
    assert manager.client("on") is None  # close 清空 clients


async def test_invalid_config_stays_degraded_and_isolates(tmp_path, session_factory):
    """配置非法的 Server 不抛出、不拦其余 Server（方案 §7.6）。"""
    path = _toml(
        tmp_path,
        """
[servers.broken]
enabled = true
transport = "carrier_pigeon"

[servers.fine]
enabled = true
transport = "streamable_http"
url = "https://example.com/mcp"
""",
    )
    manager = McpServerManager(session_factory=session_factory)
    results = await manager.start(path)

    assert results["broken"] == SERVER_DEGRADED
    assert results["fine"] == SERVER_READY
    assert manager.client("broken").status.last_error  # 问题清单进了状态


async def test_connect_failure_is_isolated_per_server(
    stdio_config,
    http_config,
    fake_session,
):
    """一个 Server 连不上，另一个照常 ready（方案 §7.6 故障隔离）。"""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mixed_factory(config):
        if config.server_id == stdio_config.server_id:
            raise RuntimeError("connection refused")
        yield fake_session

    stdio_config.enabled = True
    http_config.enabled = True
    # 退避拉长：重连任务不在测试窗口里跑，状态断言才稳定
    stdio_config.reconnect_base_seconds = 30.0
    http_config.reconnect_base_seconds = 30.0

    manager = McpServerManager(session_factory=mixed_factory)
    for cfg in (stdio_config, http_config):
        client = manager._new_client(cfg)
        manager._clients[cfg.server_id] = client
        await client.start()

    assert manager.client("brave").status.state == SERVER_DEGRADED
    assert manager.client("remote").status.state == SERVER_READY
    await manager.close()


async def test_call_tool_routes_to_right_client(stdio_config, http_config, session_factory):
    stdio_config.enabled = True
    http_config.enabled = True
    manager = McpServerManager(session_factory=session_factory)
    for cfg in (stdio_config, http_config):
        client = manager._new_client(cfg)
        manager._clients[cfg.server_id] = client
        await client.start()
        client._apply_catalog([("search", "", None)])

    session_factory.session.scripted["search"] = session_factory.session.text_result("from-brave")
    text = await manager.call_tool("brave", "search", {"q": "x"})
    assert text == "from-brave"

    with pytest.raises(Exception, match="未配置"):
        await manager.call_tool("nope", "search", {})


async def test_status_is_redacted(stdio_config, session_factory):
    """Manager 的状态面是脱敏的：无 url、command、args、env、token。"""
    stdio_config.enabled = True
    stdio_config.args = ["--api-key", "sk-super-secret"]
    manager = McpServerManager(session_factory=session_factory)
    client = manager._new_client(stdio_config)
    manager._clients[stdio_config.server_id] = client
    await client.start()

    import json

    blob = json.dumps(manager.status(), ensure_ascii=False)
    assert "sk-super-secret" not in blob
    assert "--api-key" not in blob
    assert "brave" in blob  # server_id 在（标识符，非敏感）
    assert SERVER_READY in blob  # 状态在


async def test_close_is_idempotent_and_marks_stopped(stdio_config, session_factory):
    stdio_config.enabled = True
    manager = McpServerManager(session_factory=session_factory)
    client = manager._new_client(stdio_config)
    manager._clients[stdio_config.server_id] = client
    await client.start()
    await manager.close()
    assert manager.list_servers() == []
    await manager.close()
    assert client.status.state == SERVER_STOPPED


async def test_tools_changed_callback_propagates(stdio_config, session_factory):
    stdio_config.enabled = True
    manager = McpServerManager(session_factory=session_factory)
    client = manager._new_client(stdio_config)
    manager._clients[stdio_config.server_id] = client
    await client.start()

    seen: list[str] = []
    manager.tools_changed_callback = seen.append
    session_factory.session.add_tool("search")
    session_factory.session.fire_tools_changed()
    assert await wait_for(lambda: seen == ["brave"])
