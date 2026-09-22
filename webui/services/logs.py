# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""结构化日志读取（方案 §6.9 日志页 / §8.3 SSE 协议）。

**不做共享广播器**：每个 SSE 连接独立 tail 日志文件（每 0.4s 询问一次
增量），没有订阅注册、没有慢消费者队列要管理——单管理员面板下多开的
连接就是多几个文件句柄，最简单的实现就是最稳的实现。日志写入热路径
（loguru 文件 sink）完全不被触碰。

断点续传：帧 id = 该行结束处的**字节偏移**，客户端重连带 Last-Event-ID
即从上次位置继续；文件变小（轮转）则回到 0 重放。不完整的尾行留在
缓冲，凑齐再发——绝不发半行 JSON。

历史接口读文件尾部；行解析失败按 ``{"raw": ...}`` 透传，不丢行。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import config.settings as settings

POLL_INTERVAL = 0.4
HEARTBEAT_INTERVAL = 15.0


def log_path() -> Path:
    return Path(settings.STELLA_JSON_LOG_PATH)


def _parse_line(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"raw": raw}
    except (ValueError, TypeError):
        return {"raw": raw}


def history(*, tail: int = 500, level: str | None = None) -> dict:
    """文件尾部 N 行（旧→新）。解析失败的行原样保留为 {"raw": ...}。"""
    path = log_path()
    items: list[dict] = []
    if path.exists():
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    items.append(_parse_line(raw.rstrip("\n")))
        except OSError:
            items = []
    if level:
        items = [i for i in items if i.get("level") == level.upper()]
    return {"path": str(path), "items": items[-int(tail):]}


def _sse(frame_id: int, payload: dict) -> str:
    return f"id: {frame_id}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def live(
    offset: int = 0, *, level: str | None = None
) -> AsyncIterator[str]:
    """SSE 增量流。``offset`` 为字节偏移（0 = 文件头；配合 Last-Event-ID）。"""
    path = log_path()
    pos = max(0, int(offset))
    pending = b""
    fh: Any = None
    last_beat = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            beat_due = now - last_beat >= HEARTBEAT_INTERVAL
            if path.exists():
                try:
                    size = path.stat().st_size
                except OSError:
                    size = pos
                if size < pos:  # 轮转/截断：从头重放
                    pos = 0
                    pending = b""
                    if fh is not None:
                        fh.close()
                        fh = None
                if fh is None:
                    try:
                        fh = path.open("rb")
                        fh.seek(pos)
                    except OSError:
                        fh = None
                if fh is not None:
                    chunk = fh.read()
                    if chunk:
                        pending += chunk
                    while b"\n" in pending:
                        raw_line, pending = pending.split(b"\n", 1)
                        pos += len(raw_line) + 1
                        record = _parse_line(raw_line.decode("utf-8", errors="replace"))
                        if level and record.get("level") != level.upper():
                            continue
                        yield _sse(pos, record)
                        last_beat = time.monotonic()
                        beat_due = False
            if beat_due:
                yield ": heartbeat\n\n"
                last_beat = now
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        if fh is not None:
            fh.close()
