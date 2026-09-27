# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Node 子进程桥：spawn host、NDJSON 帧读写、双向请求关联与崩溃检测（M3）。

- stdout 只跑协议；任何超限帧 / 断管 / 进程死亡 → :class:`BridgeBroken`，
  全部在途请求有界失败（不悬挂、不自动重试——重试语义归调用方）。
- 出站 ``provider.respond`` 由 ``provider_handler`` 处理：把最终 prompt 交给
  Python 侧真实 LLM 后端（薄桥），返回文本。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from core.runtime.contracts import (
    E_HOST_GONE,
    M_HELLO,
    MAX_FRAME_BYTES,
    Envelope,
    ProtocolError,
    encode_frame,
    error_response,
    parse_frame,
    request,
    response,
)

ProviderHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_HOST_ENTRY = _REPO_ROOT / "node_runtime" / "cortico" / "dist" / "host.mjs"


class BridgeBrokenError(Exception):
    """桥已断（进程死亡/断管/超限）。在途请求以此失败。"""

    code = E_HOST_GONE


# 兼容别名（计划文档用语）；新代码用 BridgeBrokenError
BridgeBroken = BridgeBrokenError


class NodeBridge:
    """一个 host 子进程对应一个 NodeBridge 实例（计划：单 Node host，M1 已验证）。"""

    def __init__(
        self,
        *,
        host_entry: Path | None = None,
        node_bin: str | None = None,
        provider_handler: ProviderHandler | None = None,
        host_config: dict[str, Any] | None = None,
        data_root: Path | None = None,
        secret: str = "fake-key",
        hello_timeout: float = 30.0,
        on_broken: Callable[["NodeBridge"], Awaitable[None]] | None = None,
    ) -> None:
        self._host_entry = Path(host_entry or os.environ.get("STELLA_CORTICO_HOST") or _DEFAULT_HOST_ENTRY)
        self._node_bin = node_bin or os.environ.get("STELLA_CORTICO_NODE") or shutil.which("node") or "node"
        self._provider_handler = provider_handler
        self._host_config = host_config or {}
        self._data_root = data_root
        self._secret = secret
        self._hello_timeout = hello_timeout
        self._on_broken = on_broken

        self._process: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None
        self._broken: BridgeBroken | None = None
        self.hello_info: dict[str, Any] = {}

    # ---- 生命周期 ----

    async def start(self) -> dict[str, Any]:
        if self._process is not None:
            raise RuntimeError("bridge 已启动")
        if not self._host_entry.exists():
            raise RuntimeError(
                f"host 产物不存在: {self._host_entry}（先运行 pnpm --dir node_runtime/cortico build）"
            )
        env = dict(os.environ)
        env["STELLA_RUNTIME_CONFIG"] = json.dumps(self._host_config, ensure_ascii=False)
        if self._data_root is not None:
            env["STELLA_RUNTIME_DATA_ROOT"] = str(self._data_root)
        env["STELLA_RUNTIME_SECRET"] = self._secret
        create = asyncio.subprocess
        flags = getattr(subprocess_flags(), "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self._process = await create.create_subprocess_exec(
            self._node_bin, str(self._host_entry),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            creationflags=flags,
            limit=MAX_FRAME_BYTES,
        )
        self._reader_task = asyncio.create_task(self._read_loop(), name="cortico-bridge-reader")
        self.hello_info = await self.request(M_HELLO, {}, timeout=self._hello_timeout)
        return self.hello_info

    async def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
        self._raise_if_broken()
        self._require_process()
        env = request(method, params or {})
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[env.id] = fut
        try:
            await self._write_frame(env)
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            raise
        finally:
            self._pending.pop(env.id, None)

    async def stop(self, shutdown_timeout: float = 8.0) -> None:
        proc = self._process
        if proc is None:
            return
        if proc.returncode is None and not self._broken:
            with contextlib.suppress(Exception):
                await self.request("runtime.shutdown", {}, timeout=shutdown_timeout)
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        await self._mark_broken(BridgeBrokenError("bridge stopped"))
        self._process = None

    # ---- 内部 ----

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None or self._broken:
            raise self._broken or BridgeBrokenError("bridge 未启动")
        return self._process

    def _raise_if_broken(self) -> None:
        if self._broken:
            raise self._broken

    async def _write_frame(self, env: Envelope) -> None:
        proc = self._require_process()
        assert proc.stdin is not None
        raw = encode_frame(env)  # 超限在此抛 ProtocolError
        async with self._write_lock:
            proc.stdin.write(raw)
            await proc.stdin.drain()

    async def _read_loop(self) -> None:
        proc = self._require_process()
        assert proc.stdout is not None
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    await self._mark_broken(BridgeBrokenError("host stdout 关闭（进程退出）"))
                    return
                if len(line) > MAX_FRAME_BYTES:
                    await self._mark_broken(BridgeBrokenError("host 帧超过上限"))
                    proc.kill()
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    env = parse_frame(text)
                except ProtocolError as e:
                    # 单帧损坏不判死：记录并继续（请求方超时兜底）
                    print(f"[cortico-bridge] 入站帧解析失败: {e}", file=sys.stderr)
                    continue
                self._dispatch(env)
        except Exception as e:  # pragma: no cover - 读循环异常兜底
            await self._mark_broken(BridgeBrokenError(f"读循环异常: {e}"))

    def _dispatch(self, env: Envelope) -> None:
        if env.kind == "response":
            fut = self._pending.pop(env.id, None)
            if fut is None or fut.done():
                return
            if env.error is not None:
                exc = ProtocolError(str(env.error.get("code", E_HOST_GONE)), str(env.error.get("message", "")))
                fut.set_exception(exc)
            else:
                fut.set_result(env.result or {})
            return
        if env.kind == "request" and env.method == "provider.respond":
            asyncio.get_running_loop().create_task(self._serve_provider(env))
            return
        # 未知 event/request：忽略（版本协商后不应出现）

    async def _serve_provider(self, env: Envelope) -> None:
        try:
            if self._provider_handler is None:
                raise RuntimeError("未注册 provider_handler")
            result = await asyncio.wait_for(self._provider_handler(env.params or {}), timeout=300.0)
            await self._write_frame(response(env.id, result))
        except Exception as e:
            retryable = not isinstance(e, (RuntimeError, ValueError))
            await self._write_frame(error_response(env.id, "E_PROVIDER", str(e), retryable))

    async def _mark_broken(self, exc: BridgeBroken) -> None:
        if self._broken is not None:
            return
        self._broken = exc
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()
        if self._on_broken is not None:
            with contextlib.suppress(Exception):
                await self._on_broken(self)

    @property
    def broken(self) -> BridgeBroken | None:
        return self._broken


def subprocess_flags():  # pragma: no cover - Windows-only 常量壳
    import subprocess

    return subprocess


def provider_prompt_text(params: dict[str, Any]) -> str:
    """从 provider.respond 参数中取最终 user prompt 文本（投影最后一条消息）。"""
    req = params.get("request") or {}
    input_items = req.get("input") or []
    for item in reversed(input_items):
        if isinstance(item, dict) and item.get("type") == "message" and item.get("role") == "user":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in ("input_text", "text"):
                    return str(part.get("text", ""))
    return ""
