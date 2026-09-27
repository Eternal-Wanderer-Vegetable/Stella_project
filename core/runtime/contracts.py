# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Python ↔ Node 运行时桥的版本化协议（迁移计划 §6.4 / M3）。

帧格式：NDJSON——每行一个 JSON 对象；stdout 专属协议，日志一律走 stderr。
Envelope 最少字段：``v``（协议版本）、``id``（请求/响应关联）、``kind``、
``method``/``params``（请求）、``result``/``error``（响应）、``ts``。

安全约束：
- 帧大小有上限（``MAX_FRAME_BYTES``），超限即断链（有界失败）；
- 不序列化 ``raw_event``/``bot`` 等平台句柄（投影白名单见 ChatContext）；
- 带副作用的请求携带 ``owner_epoch`` 与 ``turn_id``，旧 epoch 的请求被拒。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 4 * 1024 * 1024

# ---- 方法名（Python ↔ Node 双向） ----
M_HELLO = "runtime.hello"
M_SESSION_ENSURE = "session.ensure"
M_TURN_SUBMIT = "turn.submit"
M_TURN_CANCEL = "turn.cancel"
M_SESSION_RESET = "session.reset"
M_RUNTIME_DRAIN = "runtime.drain"
M_RUNTIME_SHUTDOWN = "runtime.shutdown"
M_PROVIDER_RESPOND = "provider.respond"  # Node → Python

# ---- 错误码 ----
E_PROTOCOL = "E_PROTOCOL"  # 帧不可解析/字段缺失
E_UNSUPPORTED = "E_UNSUPPORTED"  # 方法或版本不支持
E_KEY = "E_KEY"  # 会话键未注册/epoch 过期
E_CANCELLED = "E_CANCELLED"
E_DEADLINE = "E_DEADLINE"
E_PROVIDER = "E_PROVIDER"  # provider.respond 侧失败
E_HOST_GONE = "E_HOST_GONE"  # Node 进程死亡/断管
E_FRAME_TOO_LARGE = "E_FRAME_TOO_LARGE"
E_BUSY = "E_BUSY"  # 同会话已有在途轮次且禁止排队


@dataclass
class Envelope:
    """一帧协议消息。``kind``: request | response | event。"""

    id: str
    kind: str
    method: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        obj = {"v": PROTOCOL_VERSION, "id": self.id, "kind": self.kind, "ts": self.ts}
        if self.method is not None:
            obj["method"] = self.method
        if self.params:
            obj["params"] = self.params
        if self.result is not None:
            obj["result"] = self.result
        if self.error is not None:
            obj["error"] = self.error
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def request(method: str, params: dict[str, Any] | None = None) -> Envelope:
    return Envelope(id=uuid.uuid4().hex, kind="request", method=method, params=params or {})


def response(req_id: str, result: dict[str, Any] | None = None) -> Envelope:
    return Envelope(id=req_id, kind="response", result=result or {})


def error_response(req_id: str, code: str, message: str, retryable: bool = False) -> Envelope:
    return Envelope(id=req_id, kind="response", error={"code": code, "message": message, "retryable": retryable})


def parse_frame(line: str) -> Envelope:
    """把一行文本解析成 Envelope；任何不合法都抛 :class:`ProtocolError`。"""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(E_PROTOCOL, f"帧不是合法 JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ProtocolError(E_PROTOCOL, "帧必须是 JSON 对象")
    if obj.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(E_UNSUPPORTED, f"协议版本不支持: {obj.get('v')!r}")
    kind = obj.get("kind")
    if kind not in ("request", "response", "event"):
        raise ProtocolError(E_PROTOCOL, f"kind 非法: {kind!r}")
    if not isinstance(obj.get("id"), str) or not obj["id"]:
        raise ProtocolError(E_PROTOCOL, "id 缺失")
    env = Envelope(
        id=obj["id"],
        kind=kind,
        method=obj.get("method"),
        params=obj.get("params") or {},
        result=obj.get("result"),
        error=obj.get("error"),
        ts=float(obj.get("ts") or time.time()),
    )
    if kind == "request" and not env.method:
        raise ProtocolError(E_PROTOCOL, "request 缺 method")
    return env


class ProtocolError(Exception):
    """协议层错误；``code`` 是 E_* 常量。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def encode_frame(env: Envelope) -> bytes:
    """序列化成一帧（含换行符），超限即拒（有界失败，不悄悄分段）。"""
    raw = env.to_json().encode("utf-8")
    if len(raw) + 1 > MAX_FRAME_BYTES:
        raise ProtocolError(E_FRAME_TOO_LARGE, f"帧超过 {MAX_FRAME_BYTES} 字节上限")
    return raw + b"\n"
