# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""McpServerClient 的单测（方案 §9：initialize、tools/list、tools/call、超时、
错误、断线重连、工具列表变化、密钥不进日志）。

全部跑在注入的 FakeSession 上，不 import MCP SDK——SDK 是可选依赖，缺了也必须全绿。
真实传输只测配置层：stdio 不经过 shell、HTTP 认证只从环境变量取值。
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from capability.providers.mcp.client import (
    McpClientError,
    McpServerClient,
    McpToolError,
    content_to_text,
)
from capability.providers.mcp.model import (
    SERVER_DEGRADED,
    SERVER_DISABLED,
    SERVER_READY,
    SERVER_STOPPED,
)
from tests.capability.providers.conftest import wait_for


async def _start(client: McpServerClient) -> None:
    await client.start()
    assert await wait_for(lambda: client.status.state == SERVER_READY), client.status


# ---------- 连接与发现 ----------


async def test_start_initializes_and_builds_catalog(stdio_config, session_factory):
    session_factory.session.add_tool(
        "search",
        "web search",
        {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
    )
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)

    assert client.ready
    assert session_factory.session.initialize_calls == 1
    assert session_factory.session.list_calls == 1
    tools = {d.name: d for d in client.catalog()}
    assert set(tools) == {"search"}
    assert tools["search"].input_schema["required"] == ["q"]
    status = client.status_dict()
    assert status["state"] == SERVER_READY
    assert status["tool_count"] == 1
    assert status["last_tools_refresh_at"] > 0
    assert status["last_error"] == ""


async def test_initialize_failure_degrades_then_reconnects(stdio_config, session_factory):
    """连不上不抛出：状态 degraded、安排退避重连，恢复后自动 ready（方案 §7.4.8）。"""
    session_factory.session.initialize_error = RuntimeError("connection refused")
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await client.start()

    assert client.status.state == SERVER_DEGRADED
    assert client.status.failure_count == 1
    assert client.status.last_error  # 进了状态，供诊断

    session_factory.session.initialize_error = None
    session_factory.session.add_tool("search")
    assert await wait_for(lambda: client.ready)
    # 重连是一次全新的连接（退出旧上下文、再次进入工厂）
    assert len(session_factory.sessions) >= 2
    assert [d.name for d in client.catalog()] == ["search"]


async def test_unsupported_transport_degrades_without_sdk(stdio_config):
    """transport 拼错只影响这一个 Server，错误信息可读且不抛出（不触达 SDK）。"""
    stdio_config.transport = "http+sse-legacy"
    client = McpServerClient(stdio_config)  # 默认工厂：不 import SDK 就能拒掉
    await client.start()
    assert client.status.state == SERVER_DEGRADED
    assert "不支持的传输方式" in client.status.last_error


async def test_disabled_server_never_connects(stdio_config, session_factory):
    stdio_config.enabled = False
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await client.start()
    assert client.status.state == SERVER_DISABLED
    assert session_factory.sessions == []


# ---------- tools/list 变化 ----------


async def test_tools_changed_notification_refreshes_catalog(stdio_config, session_factory):
    session_factory.session.add_tool("search")
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)

    notified: list[str] = []
    client.tools_changed_callback = notified.append

    session_factory.session.add_tool("fetch")  # 远端目录变了
    session_factory.session.fire_tools_changed()

    assert await wait_for(lambda: "fetch" in {d.name for d in client.catalog()})
    assert notified == [stdio_config.server_id]
    assert client.status.tool_count == 2


async def test_oversize_schema_tool_is_rejected_not_truncated(stdio_config, session_factory):
    """schema 超预算的工具整体拒收（截断的 schema 会让模型按残缺参数表编参数）。"""
    stdio_config.max_schema_chars = 50
    session_factory.session.add_tool(
        "fat",
        "desc",
        {"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(50)}},
    )
    session_factory.session.add_tool("lean")
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)

    assert [d.name for d in client.catalog()] == ["lean"]
    assert "fat" in client.status.last_error


async def test_long_description_is_clipped(stdio_config, session_factory):
    session_factory.session.add_tool("chatty", description="很" * 2000)
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)
    descriptor = client.tool("chatty")
    assert descriptor is not None
    assert len(descriptor.description) <= 500
    assert descriptor.description.endswith("…")


# ---------- tools/call ----------


async def test_call_tool_returns_text_and_records(http_config, session_factory):
    session_factory.session.scripted["search"] = session_factory.session.text_result(
        "part1",
        "part2",
    )
    client = McpServerClient(http_config, session_factory=session_factory)
    await _start(client)
    client._apply_catalog([("search", "", None)])

    text = await client.call_tool("search", {"q": "x"})
    assert text == "part1\npart2"
    assert client.status.call_count == 1
    assert client.status.failure_count == 0
    assert session_factory.session.calls == [("search", {"q": "x"})]


async def test_call_tool_output_is_bounded(http_config, session_factory):
    """输出大小限制（方案 §3.4）：超大结果截断，不原样进 Comes。"""
    http_config.max_output_chars = 10
    session_factory.session.scripted["search"] = session_factory.session.text_result("x" * 500)
    client = McpServerClient(http_config, session_factory=session_factory)
    await _start(client)
    client._apply_catalog([("search", "", None)])

    text = await client.call_tool("search", {})
    assert len(text) == 10 and text.endswith("…")


async def test_call_tool_is_error_raises_sanitized(stdio_config, session_factory):
    """Server 明确报错的调用 → McpToolError，连接不受影响（方案 §7.4）。"""
    session_factory.session.scripted["boom"] = session_factory.session.error_result(
        "quota exceeded",
    )
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)
    client._apply_catalog([("boom", "", None)])

    with pytest.raises(McpToolError, match="quota exceeded"):
        await client.call_tool("boom", {})
    assert client.status.failure_count == 1
    assert client.status.call_count == 0
    assert client.ready  # 业务失败不断线


async def test_call_tool_timeout_is_tool_error(stdio_config, session_factory):
    stdio_config.call_timeout = 0.05
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)
    client._apply_catalog([("slow", "", None)])

    async def _slow(name, args):
        await asyncio.sleep(1.0)
        return session_factory.session.default_result

    session_factory.session.call_tool = _slow
    with pytest.raises(McpToolError, match="超时"):
        await client.call_tool("slow", {})


async def test_transport_failure_tears_down_and_reconnects(stdio_config, session_factory):
    """传输层错误：会话作废、错误脱敏、退避重连后恢复（方案 §7.4.8）。"""
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)
    client._apply_catalog([("search", "", None)])

    async def _transport_boom(name, args):
        raise RuntimeError("broken pipe http://10.0.0.1:9999/mcp?token=abc")

    session_factory.session.call_tool = _transport_boom
    with pytest.raises(McpClientError, match="连接中断"):
        await client.call_tool("search", {})

    # 异常文本里的 URL 与 query 参数不得进状态
    assert "token=abc" not in client.status.last_error
    assert "http://" not in client.status.last_error

    # 会话方法上的补丁随重连后的调用恢复（同一对象，去掉补丁即为正常行为）
    del session_factory.session.call_tool
    assert await wait_for(lambda: client.ready)


async def test_call_before_ready_or_disabled_raises(stdio_config, session_factory):
    client = McpServerClient(stdio_config, session_factory=session_factory)
    with pytest.raises(McpClientError):
        await client.call_tool("search", {})

    stdio_config.enabled = False
    disabled = McpServerClient(stdio_config, session_factory=session_factory)
    await disabled.start()
    assert disabled.status.state == SERVER_DISABLED
    with pytest.raises(McpClientError, match="未启用"):
        await disabled.call_tool("search", {})


async def test_call_unknown_tool_raises(stdio_config, session_factory):
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)
    with pytest.raises(McpClientError, match="不在"):
        await client.call_tool("nope", {})


async def test_close_stops_background_tasks_and_is_idempotent(stdio_config, session_factory):
    client = McpServerClient(stdio_config, session_factory=session_factory)
    await _start(client)
    await client.close()
    assert client.status.state == SERVER_STOPPED
    assert session_factory.session.close_calls >= 1
    await client.close()


# ---------- 内容规范化 ----------


def test_content_to_text_merges_blocks_and_bounds():
    result = SimpleNamespace(
        content=[
            SimpleNamespace(text="line1"),
            SimpleNamespace(type="image"),  # 无 text 的块只报类型，不装进文本
            "raw string",
        ],
        isError=False,
    )
    assert content_to_text(result, 500) == "line1\n[image]\nraw string"
    assert content_to_text(result, 5).endswith("…")


def test_content_to_text_reads_embedded_resource_text():
    result = SimpleNamespace(
        content=[SimpleNamespace(resource=SimpleNamespace(text="file body"))],
        isError=False,
    )
    assert content_to_text(result, 500) == "file body"


# ---------- 真实传输的配置层（不 import SDK） ----------


def test_stdio_params_are_list_args_without_shell(stdio_config):
    """stdio 永远 command + args 数组，不存在 shell 字符串（方案 §6.2）。"""
    client = McpServerClient(stdio_config)
    command, args, env = client._stdio_params(stdio_config)
    assert command == "npx"
    assert isinstance(args, list) and args == stdio_config.args
    assert env is not os.environ  # 拷贝，不共享


def test_shell_metachar_command_is_rejected_by_config():
    from capability.providers.mcp.model import ServerConfig

    cfg = ServerConfig(server_id="evil", enabled=True, command="sh -c 'rm -rf /'")
    problems = cfg.validate()
    assert any("shell" in p for p in problems)


def test_http_auth_env_missing_fails_before_any_io(http_config, monkeypatch):
    """auth_env 指向的环境变量没设：连接前就失败，只提变量名不提值。"""
    monkeypatch.delenv("STELLA_MCP_TEST_TOKEN", raising=False)
    client = McpServerClient(http_config)
    with pytest.raises(McpClientError, match="STELLA_MCP_TEST_TOKEN"):
        client._http_headers(http_config)


def test_http_auth_env_present_builds_bearer_header(http_config, monkeypatch):
    monkeypatch.setenv("STELLA_MCP_TEST_TOKEN", "super-secret-token")
    client = McpServerClient(http_config)
    headers = client._http_headers(http_config)
    assert headers == {"Authorization": "Bearer super-secret-token"}
    # 状态面永远不出现值
    assert "super-secret-token" not in str(client.status_dict())
