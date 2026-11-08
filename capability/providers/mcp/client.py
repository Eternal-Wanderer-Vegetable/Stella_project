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


class _SessionTerminatedError(Exception):
    """内部信号：Server 不再认这个会话，调用方应重建会话后重试。"""


class _ToolNotListedError(Exception):
    """内部信号：工具不在本地目录里；目录可能已过时（Server 或 Host 重启），重建后再查一次。"""


# factory(config) → 异步上下文管理器，yield 会话鸭子（见模块 docstring）
SessionFactory = Callable[[ServerConfig], Any]

# 会话属主任务收尾的等待上限；超时就取消它（关闭失败不拦停机）
_OWNER_CLOSE_TIMEOUT_SECONDS = 10.0


def _is_protocol_error(exc: BaseException) -> bool:
    """Server 用 JSON-RPC error 回答了这次请求（参数不合 schema、方法不存在……）。

    这说明连接是好的、对端也在正常应答，只是这次调用本身被拒绝——应当按工具错误
    处理，不能当作传输中断去拆会话。SDK 是可选依赖，所以按类型名兜底识别。
    """
    try:
        from mcp.shared.exceptions import McpError
    except ImportError:  # pragma: no cover - SDK 未安装时只剩鸭子识别
        McpError = None  # noqa: N806
    if McpError is not None and isinstance(exc, McpError):
        return True
    return type(exc).__name__ == "McpError"


def _is_session_terminated(exc: BaseException) -> bool:
    """Streamable HTTP：Server 对带旧会话 ID 的请求回了 404（会话已过期或被关闭）。

    SDK 把它转成 ``McpError(code=32600, "Session terminated")``，且请求根本没被
    Server 处理——按 MCP 规范，客户端此时应重新初始化会话，重试是安全的。
    Server 侧常见原因是空闲超时（rmcp 默认 5 分钟）。
    """
    if not _is_protocol_error(exc):
        return False
    error = getattr(exc, "error", None)
    code = getattr(error, "code", None)
    message = str(getattr(error, "message", "") or exc).strip().lower()
    return code in (32600, -32600) and message == "session terminated"


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
        # 会话由一个专属任务持有：传输与会话的异步上下文在它里面进入、也在它里面退出。
        # SDK（anyio）的 cancel scope 必须在同一任务内进出；从别的任务关闭，会把
        # 取消打到当初进入它的任务上——Bot 进程里那就是 NoneBot 的 lifespan 任务。
        self._owner_task: asyncio.Task | None = None
        self._owner_closing: asyncio.Event | None = None
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
            loop = asyncio.get_running_loop()
            ready: asyncio.Future = loop.create_future()
            closing = asyncio.Event()
            owner = asyncio.create_task(
                self._own_session(ready, closing),
                name=f"mcp-session-{self.server_id}",
            )
            try:
                session, result = await asyncio.shield(ready)
            except BaseException:
                closing.set()
                if not owner.done():
                    owner.cancel()
                with suppress(BaseException):
                    await owner
                raise
            if owner.done():
                # 交出会话后、登记前传输就已失效
                raise McpClientError(f"MCP server {self.server_id} 会话在就绪后立即中断")
            self._owner_task = owner
            self._owner_closing = closing
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

    async def _own_session(self, ready: asyncio.Future, closing: asyncio.Event) -> None:
        """会话属主任务：进入传输与会话 → 交出会话 → 等待关闭 → 在本任务内退出。

        传输层在会话存活期间崩溃（SDK 的 task group 抛错）时，取消只会落在本任务，
        不会波及调用方或启动它的任务；这里把会话标记为失效并安排重连。
        """
        try:
            async with AsyncExitStack() as stack:
                session = await stack.enter_async_context(self._factory(self.config))
                await asyncio.wait_for(
                    session.initialize(), timeout=self.config.connect_timeout,
                )
                result = await asyncio.wait_for(
                    session.list_tools(), timeout=self.config.connect_timeout,
                )
                session.set_tools_changed_callback(self._on_tools_changed_notification)
                ready.set_result((session, result))
                await closing.wait()
        except BaseException as e:
            if not ready.done():
                # 连接阶段失败：交给 _connect 走既有的退避重连
                if isinstance(e, Exception):
                    ready.set_exception(e)
                else:
                    ready.set_exception(McpClientError(f"MCP server {self.server_id} 会话任务被取消"))
                return
            if not closing.is_set() and self._owner_task is asyncio.current_task():
                # 会话存活期间传输层失效
                self._session = None
                self._owner_task = None
                self._owner_closing = None
                self._catalog.clear()
                self._record_failure(e if isinstance(e, Exception) else McpClientError("会话任务被取消"))
                self._schedule_reconnect(self._backoff)
                self._backoff = min(self._backoff * 2, self.config.reconnect_max_seconds)
            if not isinstance(e, Exception) and not isinstance(e, asyncio.CancelledError):
                raise

    async def _teardown_session(self) -> None:
        owner, closing = self._owner_task, self._owner_closing
        self._owner_task = None
        self._owner_closing = None
        stack, self._stack = self._stack, None
        self._session = None
        self._catalog.clear()
        if owner is not None and closing is not None:
            # 只通知属主任务自己收尾；绝不在当前任务里退出它进入的上下文
            closing.set()
            if owner is not asyncio.current_task():
                done, _ = await asyncio.wait({owner}, timeout=_OWNER_CLOSE_TIMEOUT_SECONDS)
                if not done:
                    owner.cancel()
                    await asyncio.wait({owner}, timeout=1.0)
                    self.status.last_error = sanitize_error("MCP 会话关闭超时，已强制取消")
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
        """调用一个远程工具，返回受限文本。失败统一抛 McpClientError（已脱敏）。

        Server 报会话已终止（空闲超时等）时，重建会话后重试一次：该请求未被 Server
        处理，重试不会重复执行工具。工具不在本地目录时同样重建一次：Host 重启后目录
        曾被清空，而旧会话已失效、收不到目录变化通知，不重建就会一直报“不在目录里”。
        """
        if not self.config.enabled:
            raise McpClientError(f"MCP server {self.server_id} 未启用")
        for attempt in range(2):
            session = self._session
            if session is None or self.status.state != SERVER_READY:
                raise McpClientError(f"MCP server {self.server_id} 当前不可用")
            try:
                return await self._call_once(session, remote_name, arguments, timeout)
            except _SessionTerminatedError:
                if attempt:
                    raise McpClientError(
                        f"MCP server {self.server_id} 会话已终止，重建后仍不可用",
                    ) from None
                await self._renew_session(session)
            except _ToolNotListedError:
                if attempt:
                    raise McpClientError(
                        f"工具 {remote_name} 不在 {self.server_id} 的目录里",
                    ) from None
                await self._renew_session(session)
        raise McpClientError(f"MCP server {self.server_id} 当前不可用")  # pragma: no cover

    async def _renew_session(self, stale: Any) -> None:
        """丢弃已被 Server 终止的会话并立即重连（并发调用只重建一次）。"""
        self.status.last_error = sanitize_error("会话已被 Server 终止，正在重建")
        if self._session is stale:
            await self._teardown_session()
        await self._attempt_connect()

    async def _call_once(
        self,
        session: Any,
        remote_name: str,
        arguments: dict[str, Any] | None,
        timeout: float | None,
    ) -> str:
        if remote_name not in self._catalog:
            raise _ToolNotListedError
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
            if _is_session_terminated(e):
                raise _SessionTerminatedError from None
            if _is_protocol_error(e):
                # 对端用 JSON-RPC error 拒绝了这次调用（如参数不合 schema）：连接完好，
                # 按工具错误返回，会话保留，错误文本带回给 agent 以便改参重试
                self.status.failure_count += 1
                detail = sanitize_error(str(e))[:200]
                raise McpToolError(
                    f"工具 {remote_name} 被拒绝: {detail}" if detail else f"工具 {remote_name} 被拒绝",
                ) from None
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
