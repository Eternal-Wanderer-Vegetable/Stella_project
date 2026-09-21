# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP 会话客户端：一个 Server 的连接、发现、调用与重连（方案 §7.4）。

## 会话接缝

真正的 JSON-RPC / 传输细节交给 MCP SDK（``mcp.ClientSession`` + 对应传输），但
**SDK 依赖是可选的**（pyproject 的 ``mcp`` extra）：所有 SDK import 都发生在
:meth:`McpServerClient._default_factory` 里，SDK 缺失时该 Server 进入 degraded，
其余 Server 与 Stella 本体不受影响。

测试与 fake 传输通过构造参数 ``session_factory`` 注入：它是一个
``factory(config) -> 异步上下文管理器``，进入时 yield 一个「会话鸭子」——

    await session.initialize() -> 任意（只判成功/失败）
    await session.list_tools() -> 带 .tools 列表的对象（元素含 .name/.description/.inputSchema）
    await session.call_tool(name, arguments) -> 带 .content/.isError 的对象
    session.set_tools_changed_callback(cb)

会话的**关闭**由 factory 的上下文管理器负责（AsyncExitStack 统一收口），会话鸭子
本身不需要 close。

## 并发与失败隔离

- 同一 Server 的连接 / 刷新 / 关闭由 ``_lifecycle_lock`` 串行（方案 §7.4.7：
  未验证的 Server 不做并发初始化）；工具调用不持该锁，只捕获当时的会话引用，
  会话换掉后旧调用以异常收场并按传输失败处理。
- ``McpToolError``（Server 明确报错的调用）**不**触发重连——那是业务失败，连接是好的；
  超时与其余异常视为传输问题：会话作废、按指数退避重连（方案 §7.4.8）。
- 所有对外的错误文本都经 ``sanitize_error``，认证头、命令行与完整异常栈不出本模块
  （方案 §7.5）。
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from datetime import timedelta
from typing import Any

from capability.providers.mcp.model import (
    SERVER_DEGRADED,
    SERVER_DISABLED,
    SERVER_READY,
    SERVER_RECONNECTING,
    SERVER_STARTING,
    SERVER_STOPPED,
    TRANSPORT_HTTP,
    TRANSPORT_STDIO,
    ServerConfig,
    ServerStatus,
    ToolDescriptor,
    descriptor_from_remote,
    sanitize_error,
)


class McpClientError(RuntimeError):
    """连接层错误。``str(e)`` 已脱敏，可直接进日志与诊断。"""


class McpToolError(McpClientError):
    """Server 对一次 tools/call 明确返回错误（业务失败，连接不受影响）。"""


# factory(config) → 异步上下文管理器，yield 会话鸭子（见模块 docstring）
SessionFactory = Callable[[ServerConfig], Any]


def _tools_from_result(result: Any) -> list[tuple[str, str, Any]]:
    """从 list_tools 的返回里取出 ``[(name, description, inputSchema), ...]``（鸭子类型）。"""
    tools = getattr(result, "tools", None) or []
    out: list[tuple[str, str, Any]] = []
    for tool in tools:
        name = str(getattr(tool, "name", "") or "")
        description = str(getattr(tool, "description", "") or "")
        out.append((name, description, getattr(tool, "inputSchema", None)))
    return out


def _block_text(block: Any) -> str:
    """一个 content block → 受限文本（方案 §7.4.6）。

    text 块原样取；资源块取内嵌文本；其余类型只报类型名——图片/二进制不进
    Comes 的文本链路（摘要器与 prompt 都吃不了它们）。
    """
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        text = block.get("text")
        if isinstance(text, str):
            return text
        resource = block.get("resource")
        if isinstance(resource, dict) and isinstance(resource.get("text"), str):
            return resource["text"]
        return f"[{block.get('type') or 'content'}]"
    text = getattr(block, "text", None)
    if isinstance(text, str):
        return text
    resource = getattr(block, "resource", None)
    if resource is not None:
        inner = getattr(resource, "text", None)
        if isinstance(inner, str):
            return inner
    kind = getattr(block, "type", None) or type(block).__name__
    return f"[{kind}]"


def content_to_text(result: Any, max_chars: int) -> str:
    """tools/call 的返回 → 有字符上限的纯文本（方案 §3.4 的输出大小限制）。"""
    blocks = getattr(result, "content", None) or []
    parts = [_block_text(b) for b in blocks]
    text = "\n".join(p for p in parts if p)
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    return text


class McpServerClient:
    """一个 MCP Server 的生命周期所有者。由 ``McpServerManager`` 持有。"""

    def __init__(
        self,
        config: ServerConfig,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.config = config
        self._factory = session_factory or self._default_factory
        self.status = ServerStatus(
            state=SERVER_DISABLED if not config.enabled else SERVER_STOPPED,
        )
        self._catalog: dict[str, ToolDescriptor] = {}
        # 收到 tools/list_changed 后通知谁（Manager 转给 adapter 做 Registry 刷新）
        self.tools_changed_callback: Callable[[str], None] | None = None

        self._stack: AsyncExitStack | None = None
        self._session: Any | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._close_requested = False
        self._reconnect_task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None
        self._backoff = max(config.reconnect_base_seconds, 0.5)

    # ---------- 查询 ----------

    @property
    def server_id(self) -> str:
        return self.config.server_id

    @property
    def ready(self) -> bool:
        return self.status.state == SERVER_READY

    def catalog(self) -> list[ToolDescriptor]:
        return list(self._catalog.values())

    def tool(self, remote_name: str) -> ToolDescriptor | None:
        return self._catalog.get(remote_name)

    def status_dict(self) -> dict[str, Any]:
        return self.status.to_dict()

    # ---------- 生命周期 ----------

    async def start(self) -> None:
        """连接并完成初始发现。失败不抛出：记入状态并安排退避重连。

        MCP_ENABLED=false 或 server enabled=false 时停留在 disabled / stopped，
        什么都不做——「没启用」不是错误。
        """
        if not self.config.enabled:
            self.status.state = SERVER_DISABLED
            return
        self._close_requested = False
        await self._attempt_connect(first=True)

    async def close(self) -> None:
        """停机：不再重连，取消后台任务，关闭会话与传输（方案 §7.8 关闭顺序）。"""
        self._close_requested = True
        for task in (self._reconnect_task, self._refresh_task):
            if task is not None and not task.done():
                task.cancel()
        self._reconnect_task = None
        self._refresh_task = None
        async with self._lifecycle_lock:
            await self._teardown_session()
        self.status.state = SERVER_STOPPED

    async def _attempt_connect(self, first: bool = False) -> None:
        if self._close_requested:
            return
        self.status.state = SERVER_STARTING if first else SERVER_RECONNECTING
        try:
            await self._connect()
        except Exception as e:
            self._record_failure(e)
            delay = self._backoff
            self._backoff = min(self._backoff * 2, self.config.reconnect_max_seconds)
            self.status.backoff_seconds = delay
            self._schedule_reconnect(delay)

    async def _connect(self) -> None:
        async with self._lifecycle_lock:
            if self._session is not None or self._close_requested:
                return
            stack = AsyncExitStack()
            try:
                session = await stack.enter_async_context(self._factory(self.config))
                await asyncio.wait_for(
                    session.initialize(), timeout=self.config.connect_timeout,
                )
                result = await asyncio.wait_for(
                    session.list_tools(), timeout=self.config.connect_timeout,
                )
                session.set_tools_changed_callback(self._on_tools_changed_notification)
            except BaseException:
                await stack.aclose()
                raise
            self._stack = stack
            self._session = session
            now = time.time()
            self.status.state = SERVER_READY
            self.status.last_success_at = now
            self.status.last_tools_refresh_at = now
            self.status.last_error = ""
            self.status.backoff_seconds = 0.0
            # 目录最后应用：拒收工具的提示要留在 last_error 里，不能被上面的清空盖掉
            self._apply_catalog(_tools_from_result(result))
            self._backoff = max(self.config.reconnect_base_seconds, 0.5)

    async def _teardown_session(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        self._catalog.clear()
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as e:
                # 关闭失败不拦停机：stdio 子进程随进程组收尾，HTTP 连接随 socket 关闭
                self.status.last_error = sanitize_error(str(e))

    def _record_failure(self, exc: Exception) -> None:
        self.status.failure_count += 1
        self.status.last_error = sanitize_error(str(exc))
        # degraded 是「这次没连上但还会再试」；真正在等退避时由 reconnect 置为 reconnecting
        self.status.state = SERVER_DEGRADED

    def _schedule_reconnect(self, delay: float) -> None:
        if self._close_requested:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return

        async def _run() -> None:
            await asyncio.sleep(max(delay, 0.1))
            if not self._close_requested:
                self.status.state = SERVER_RECONNECTING
                await self._attempt_connect()

        self._reconnect_task = asyncio.create_task(_run())

    # ---------- 工具目录 ----------

    def _apply_catalog(self, entries: list[tuple[str, str, Any]]) -> None:
        catalog: dict[str, ToolDescriptor] = {}
        rejected: list[str] = []
        for name, description, schema in entries:
            descriptor = descriptor_from_remote(
                name,
                description,
                schema,
                max_schema_chars=self.config.max_schema_chars,
            )
            if descriptor is None:
                if name:
                    rejected.append(name)
                continue
            catalog[descriptor.name] = descriptor
        self._catalog = catalog
        self.status.tool_count = len(catalog)
        if rejected:
            self.status.last_error = sanitize_error(
                f"{len(rejected)} 个工具 schema 超限或非法被拒收: {', '.join(rejected[:5])}",
            )

    def _on_tools_changed_notification(self) -> None:
        """SDK 消息线程回调：收到 tools/list_changed 通知，安排一次刷新。"""
        if self._close_requested:
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            return

        async def _run() -> None:
            await self._refresh_tools()

        self._refresh_task = asyncio.create_task(_run())

    async def _refresh_tools(self) -> None:
        session = self._session
        if session is None or self._close_requested:
            return
        try:
            async with self._lifecycle_lock:
                if self._session is None:
                    return
                result = await asyncio.wait_for(
                    self._session.list_tools(), timeout=self.config.connect_timeout,
                )
                self._apply_catalog(_tools_from_result(result))
                self.status.last_tools_refresh_at = time.time()
                self.status.last_success_at = time.time()
        except Exception as e:
            # Server 断了才会在刷新时报错：走连接失败的退避路径
            self._record_failure(e)
            await self._teardown_session()
            self._schedule_reconnect(self._backoff)
            self._backoff = min(self._backoff * 2, self.config.reconnect_max_seconds)
            return
        callback = self.tools_changed_callback
        if callback is not None:
            with suppress(Exception):
                callback(self.server_id)

    # ---------- 调用 ----------

    async def call_tool(
        self,
        remote_name: str,
        arguments: dict[str, Any] | None,
        timeout: float | None = None,
    ) -> str:
        """调用一个远程工具，返回受限文本。失败统一抛 McpClientError（已脱敏）。"""
        if not self.config.enabled:
            raise McpClientError(f"MCP server {self.server_id} 未启用")
        session = self._session
        if session is None or self.status.state != SERVER_READY:
            raise McpClientError(f"MCP server {self.server_id} 当前不可用")
        if remote_name not in self._catalog:
            raise McpClientError(f"工具 {remote_name} 不在 {self.server_id} 的目录里")
        effective = timeout if timeout is not None else self.config.call_timeout
        try:
            result = await asyncio.wait_for(
                session.call_tool(remote_name, dict(arguments or {})),
                timeout=effective,
            )
        except asyncio.TimeoutError:
            self.status.failure_count += 1
            raise McpToolError(
                f"工具 {remote_name} 调用超时（{effective:.0f}s）",
            ) from None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # 传输层坏了：作废会话并安排重连，但给调用方的仍是脱敏后的失败
            self.status.failure_count += 1
            self.status.last_error = sanitize_error(str(e))
            await self._teardown_session()
            self._schedule_reconnect(self._backoff)
            self._backoff = min(self._backoff * 2, self.config.reconnect_max_seconds)
            raise McpClientError(f"MCP server {self.server_id} 连接中断") from None

        if getattr(result, "isError", False):
            self.status.failure_count += 1
            detail = content_to_text(result, 200)
            raise McpToolError(f"工具 {remote_name} 返回错误: {detail}" if detail else f"工具 {remote_name} 返回错误")
        self.status.call_count += 1
        self.status.last_success_at = time.time()
        return content_to_text(result, self.config.max_output_chars)

    # ---------- SDK 工厂 ----------

    def _default_factory(self, config: ServerConfig) -> Any:
        """真实传输工厂：stdio / Streamable HTTP，全部延迟 import MCP SDK。"""
        return self._sdk_session(config)

    @asynccontextmanager
    async def _sdk_session(self, config: ServerConfig):
        try:
            if config.transport == TRANSPORT_STDIO:
                async with self._sdk_stdio(config) as session:
                    yield session
            elif config.transport == TRANSPORT_HTTP:
                async with self._sdk_http(config) as session:
                    yield session
            else:
                raise McpClientError(f"不支持的传输方式: {config.transport}")
        except ImportError as e:
            raise McpClientError(
                "MCP SDK 未安装（可选依赖：pip install 'stella_project[mcp]'）",
            ) from e

    def _stdio_params(self, config: ServerConfig) -> tuple[str, list[str], dict[str, str]]:
        """stdio 启动参数。**无 shell**：command 是单个可执行文件，args 是参数数组
        （方案 §6.2；MCP SDK 的 stdio_client 同样不经过 shell）。"""
        env = dict(os.environ)
        env.update(config.env)
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        return config.command, list(config.args), env

    @asynccontextmanager
    async def _sdk_stdio(self, config: ServerConfig):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        command, args, env = self._stdio_params(config)
        params = StdioServerParameters(command=command, args=args, env=env)
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write, message_handler=self._sdk_message_handler) as session,
        ):
            yield _SdkSession(session)

    @staticmethod
    def _http_headers(config: ServerConfig) -> dict[str, str]:
        """HTTP 认证头。值**只**从环境变量读（方案 §6.2），缺失时在建立任何连接
        之前就失败——错误文本只含变量名，不含值。"""
        if not config.auth_env:
            return {}
        token = os.environ.get(config.auth_env, "")
        if not token:
            raise McpClientError(
                f"环境变量 {config.auth_env} 未设置，无法认证（值只从环境变量读，不落盘）",
            )
        return {"Authorization": f"Bearer {token}"}

    @asynccontextmanager
    async def _sdk_http(self, config: ServerConfig):
        headers = self._http_headers(config)
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(
                config.url,
                headers=headers or None,
                timeout=timedelta(seconds=config.connect_timeout),
            ) as (read, write, _get_session_id),
            ClientSession(read, write, message_handler=self._sdk_message_handler) as session,
        ):
            yield _SdkSession(session)

    def _sdk_message_handler(self, message: Any) -> None:
        """SDK 消息回调：只认 tools/list_changed 通知，其余一律忽略。"""
        try:
            if isinstance(message, BaseException):
                return
            root = getattr(message, "root", None)
            method = getattr(root, "method", None)
            if method == "notifications/tools/list_changed":
                self._on_tools_changed_notification()
        except Exception:
            pass


class _SdkSession:
    """把 ``mcp.ClientSession`` 包成会话鸭子（见模块 docstring 的接缝定义）。"""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._tools_changed_cb: Callable[[], None] | None = None

    def set_tools_changed_callback(self, cb: Callable[[], None]) -> None:
        self._tools_changed_cb = cb

    async def initialize(self) -> Any:
        return await self._session.initialize()

    async def list_tools(self) -> Any:
        return await self._session.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return await self._session.call_tool(name, arguments)


__all__ = [
    "McpClientError",
    "McpServerClient",
    "McpToolError",
    "content_to_text",
]
