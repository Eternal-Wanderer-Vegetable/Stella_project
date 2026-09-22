# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""本机开发桥：Windows 命名管道 Docker 端点 → TCP（仅测试脚手架）。

``DockerSandboxExecutor`` 经 httpx 访问 Docker Engine HTTP API，而 httpx
没有 Windows 命名管道传输——按设计它对 npipe 端点报告「不可用，请配置
远程 runner」。本脚本让**本机集成测试**能在 Docker Desktop（npipe）上
运行：把管道字节流转发到一个本地 TCP 端口，runner 以
``DOCKER_HOST=http://127.0.0.1:<port>`` 访问。

实现注记（2026-09-22 真机调试结论）：

* 直连管道「写→读」顺序交换 100% 可靠；多线程双向泵会随机吞掉首个
  请求。因此每个请求做**顺序交换**：开管道 → 写请求 → 读取线程读到
  分帧完整 → 回写客户端（附加 ``Connection: close``）。
* Windows 管道句柄不支持 ``os.set_blocking(False)``，超时语义由「读取
  线程 + 主线程限时等待」实现；超时的句柄**只泄漏不关闭**（关闭可能
  与阻塞中的 os.read 竞争句柄号），守护线程随进程退出回收。
* 首字节 2.5s 未到视为撞上死实例，重开管道重发一次（该失败模式下请求
  未到达守护进程，重发安全；``/wait``、``/logs`` 长轮询不重试）。

它不是产品代码，也不是部署建议：生产/远程场景直接把 DOCKER_HOST 指向
sidecar/远程 runner（见 docs/skills.md）。桥只监听 127.0.0.1。

用法::

    python tests/sandbox/_npipe_bridge.py --port 2377 \
        --pipe //./pipe/docker_engine

    # 另一个终端
    set STELLA_DOCKER_TEST_ENDPOINT=http://127.0.0.1:2377
    python -m pytest tests/sandbox/test_docker_integration.py -v
"""

from __future__ import annotations

import argparse
import contextlib
import os
import socket
import sys
import threading
import time
from pathlib import Path

_CHUNK = 65536
_DEBUG = os.getenv("BRIDGE_DEBUG") == "1"
_HEAD_TIMEOUT = 2.5  # 首字节快速失败窗口（/wait、/logs 除外）
_POLL = 0.02
_MAX_TOTAL = 3600.0


_DUMP_DIR = os.getenv("BRIDGE_DUMP_DIR", "")


def _dbg(msg: str) -> None:
    if _DEBUG:
        print(
            f"[bridge {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True
        )


def _framing_complete(buf: bytes) -> bool:
    """响应是否已按 HTTP 分帧读完整。"""
    if b"\r\n\r\n" not in buf:
        return False
    head, body = buf.split(b"\r\n\r\n", 1)
    head_l = head.lower()
    status = int(head.split(b" ")[1]) if b" " in head.split(b"\r\n")[0] else 0
    if status == 204 or status == 304:
        return True
    if b"transfer-encoding: chunked" in head_l:
        return body.endswith(b"0\r\n\r\n")
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            try:
                return len(body) >= int(line.split(b":", 1)[1])
            except ValueError:
                return True
    return False  # 无长度无分帧：等 pipe EOF 兜底


def _client_closed(conn: socket.socket) -> bool:
    try:
        data = conn.recv(1, socket.MSG_PEEK)
    except BlockingIOError:
        return False
    except OSError:
        return True
    return data == b""


def _pipe_exchange(
    pipe_path: str,
    raw_request: bytes,
    conn: socket.socket,
    *,
    head_timeout: float,
) -> bytes | None:
    """顺序交换：写请求 → 读取线程读完整响应。失败返回 None。

    读取线程独占 fd 并在自己的 finally 里关闭；超时放弃时 fd **不关闭**
    （避免与阻塞中的 os.read 争用句柄号），守护线程随进程退出回收。
    """
    try:
        fd = os.open(pipe_path, os.O_RDWR | os.O_BINARY)
    except OSError as exc:
        _dbg(f"open failed: {exc!r}")
        return None
    try:
        view = memoryview(raw_request)
        while view:  # 写满为止：管道配额可能造成部分写
            written = os.write(fd, view)
            view = view[written:]
    except OSError as exc:
        _dbg(f"write failed: {exc!r}")
        os.close(fd)
        return None

    chunks: list[bytes] = []
    done = threading.Event()

    def _reader() -> None:
        try:
            buf = b""
            while True:
                data = os.read(fd, _CHUNK)
                if not data:
                    break
                buf += data
                if _framing_complete(buf):
                    chunks.append(buf)
                    return
                # 分帧头跨 chunk 时把累计缓冲放进 chunks 供主线程判断首字节
                chunks[:] = [buf]
        except OSError:
            pass
        finally:
            chunks[:] = [buf]
            # 必须先关 fd 再唤醒主线程：否则主线程放行的新连接可能 os.open
            # 到同一个句柄号，而这里迟到的 close 会抽走别人的句柄（真机踩坑）
            with contextlib.suppress(OSError):
                os.close(fd)
            done.set()

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    started = time.monotonic()
    while not done.wait(_POLL):
        if _client_closed(conn):
            _dbg("client closed mid-response")
            return None  # fd 由读取线程最终关闭/回收
        elapsed = time.monotonic() - started
        if not chunks and elapsed > head_timeout:
            _dbg(f"no first byte in {head_timeout}s（死实例，放弃）")
            return None  # fd 泄漏给守护线程：不 close，防止句柄号复用竞态
        if elapsed > _MAX_TOTAL:
            _dbg("total timeout")
            return None
    return b"".join(chunks)


def _is_long_poll(path: str) -> bool:
    return path.endswith(("/wait", "/logs", "/events"))


def handle(conn: socket.socket, pipe_path: str) -> None:
    """一条 TCP 连接：读一个请求 → 管道交换 → 带连接关闭语义回写。"""
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = conn.recv(_CHUNK)
            if not chunk:
                return
            head += chunk
            if len(head) > 1 << 20:
                return
        raw_head, body = head.split(b"\r\n\r\n", 1)
        content_length = 0
        path = raw_head.split(b"\r\n")[0].split(b" ")[1].decode("latin-1")
        for line in raw_head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                content_length = int(line.split(b":", 1)[1])
        while len(body) < content_length:
            chunk = conn.recv(_CHUNK)
            if not chunk:
                return
            body += chunk
        raw_request = raw_head + b"\r\n\r\n" + body
        _dbg(f"request {path} ({len(raw_request)}B)")

        head_timeout = _MAX_TOTAL if _is_long_poll(path) else _HEAD_TIMEOUT
        # 交换期切非阻塞：_client_closed 的 MSG_PEEK 在阻塞 socket 上没有
        # 数据时会永久挂起（而不是抛 BlockingIOError），把慢请求全部冻死
        conn.setblocking(False)
        response = _pipe_exchange(
            pipe_path, raw_request, conn, head_timeout=head_timeout
        )
        if response is None and _DUMP_DIR:
            import uuid as _uuid

            with contextlib.suppress(OSError):
                (Path(_DUMP_DIR) / f"fail-{_uuid.uuid4().hex[:8]}.bin").write_bytes(
                    raw_request
                )
        if response is None and not _is_long_poll(path) and not _client_closed(conn):
            # 死实例竞态：请求未被守护进程收到，重开管道重发一次
            _dbg(f"retry {path}")
            response = _pipe_exchange(
                pipe_path, raw_request, conn, head_timeout=head_timeout
            )
        if response is None:
            conn.setblocking(True)
            conn.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            return
        # 强制连接关闭语义：httpx 收完即关，不复用
        response = response.replace(b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n", 1)
        conn.setblocking(True)
        conn.sendall(response)
        _dbg(f"responded {len(response)}B")
    except (OSError, ValueError) as exc:
        _dbg(f"handler error: {exc!r}")
    finally:
        with contextlib.suppress(OSError):
            conn.close()


def serve(host: str, port: int, pipe_path: str) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(16)
    print(f"[bridge] {host}:{port} -> {pipe_path}（Ctrl-C 退出）", flush=True)
    while True:
        conn, _addr = server.accept()
        threading.Thread(target=handle, args=(conn, pipe_path), daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=2377)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--pipe", default="//./pipe/docker_engine")
    args = parser.parse_args()
    serve(args.host, args.port, args.pipe)


if __name__ == "__main__":
    main()
