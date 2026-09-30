# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Codex 原始事件 → AgentEvent 归一器（方案 §6.7 的映射表）。

⚠️ M0 门禁（方案 §12.1 假设 1）：本模块的映射以**录制 fixture** 为契约
（tests/cometa/fixtures/codex_events.jsonl），fixture 必须在冻结的
SDK/runtime 版本上重新录制。官方 SDK 的事件名与 payload 在未经 M0 探针
验证前一律按「未知事件」降级处理——保留事实、不臆造语义：

- 重复事件（同 ``id``）→ 去重；
- 乱序事件 → 保留原始顺序（cometa 不重排历史，恢复时记录事件缺口）；
- 未知 kind → ``phase`` 事件（raw_kind 保留，payload 截断脱敏）；
- ``completed``/``failed``/``interrupted`` 是三个不同的终态信号，
  **不能只检查进程 exit code**（§6.7）；
- 消息增量 → ``message_delta``（executor 有界合并，绝不把中间消息当最终答复）。

映射表（§6.7「后端事实 → cometa 归一行为」）在 normalize_one 的 docstring。
"""

from __future__ import annotations

import json
from datetime import datetime

from cometa.models import utc_now

from .base import backend_event

# 原始事件里可作为「原生事件 ID」的字段（按序取第一个非空）。
_EVENT_ID_FIELDS = ("id", "event_id", "call_id", "item_id")

# 已知 kind → 归一 kind。键名以 M0 录制的 fixture 为准；未列出的全部降级 phase。
_KNOWN_KINDS = {
    "thread.started": "phase",
    "turn.started": "phase",
    "item.started": "phase",
    "item.completed": "command_record",
    "item.updated": "phase",
    "agent_message.delta": "message_delta",
    "agent_message.completed": "message_final",
    "exec.command.begin": "command_record",
    "exec.command.end": "command_record",
    "patch.apply.begin": "command_record",
    "patch.apply.end": "command_record",
    "web.search.begin": "command_record",
    "web.search.end": "command_record",
    "elicitation.request": "input_request",
    "approval.request": "approval_request",
    "turn.completed": "completed",
    "turn.failed": "failed",
    "turn.interrupted": "interrupted",
    "error": "failed",
}

# payload 截断：原始事件不进聊天上下文，只留有界证据。
_MAX_PAYLOAD_STR = 500
_MAX_PAYLOAD_ENTRIES = 16


def _sanitize(value, depth: int = 0):
    if isinstance(value, str):
        return value if len(value) <= _MAX_PAYLOAD_STR else value[:_MAX_PAYLOAD_STR] + "…"
    if isinstance(value, dict):
        if depth >= 3:
            return "…"
        return {
            str(k)[:64]: _sanitize(v, depth + 1)
            for k, v in list(value.items())[:_MAX_PAYLOAD_ENTRIES]
        }
    if isinstance(value, (list, tuple)):
        if depth >= 3:
            return "…"
        return [_sanitize(v, depth + 1) for v in value[:_MAX_PAYLOAD_ENTRIES]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_PAYLOAD_STR]


def _event_id(raw: dict) -> str | None:
    for field in _EVENT_ID_FIELDS:
        value = raw.get(field)
        if value:
            return str(value)
    return None


def _occurred_at(raw: dict) -> datetime | None:
    ts = raw.get("timestamp") or raw.get("ts")
    if isinstance(ts, (int, float)):
        from datetime import datetime as _dt

        try:
            return _dt.fromtimestamp(float(ts) / 1000 if float(ts) > 1e11 else float(ts))
        except (ValueError, OverflowError, OSError):
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            return None
    return None


def normalize_one(raw: dict) -> tuple[str, dict] | None:
    """把一条原始事件映射为 ``(归一kind, payload)``。

    映射表（方案 §6.7）：

    ============ ============================================
    后端事实      cometa 归一行为
    ============ ============================================
    会话/轮次创建 session_id / turn_id 由适配器保存，非本函数
    item 开始     phase（完成事件才是该 item 的权威值）
    消息增量      message_delta（有界缓冲）
    命令/搜索记录  command_record（脱敏证据）
    请求信息/审批  input_request / approval_request（不自动同意）
    轮次完成      completed（executor 校验后才落业务终态）
    轮次失败      failed
    轮次中断      interrupted
    未知事件      phase + raw_kind（保留事实，不臆造）
    ============ ============================================
    """
    if not isinstance(raw, dict):
        return None
    raw_kind = str(raw.get("type") or raw.get("kind") or "").strip()
    if not raw_kind:
        return None
    kind = _KNOWN_KINDS.get(raw_kind, "phase")
    payload = _sanitize(raw.get("payload") if isinstance(raw.get("payload"), dict) else raw)
    payload.setdefault("raw_kind", raw_kind)
    if kind == "message_delta":
        delta = raw.get("delta") or (raw.get("payload") or {}).get("delta") or ""
        payload = {"delta": str(delta)[:_MAX_PAYLOAD_STR], "raw_kind": raw_kind}
    elif kind == "message_final":
        text = raw.get("text") or (raw.get("payload") or {}).get("text") or ""
        payload = {"text": str(text), "raw_kind": raw_kind}
    elif kind in ("input_request", "approval_request"):
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        payload = {
            "backend_request_id": str(
                inner.get("request_id") or inner.get("call_id") or _event_id(raw) or ""
            ),
            "question": str(inner.get("question") or inner.get("prompt") or "")[:500],
            "options": [
                str(o) for o in (inner.get("options") or [])[:8]
            ],
            "raw_kind": raw_kind,
        }
    elif kind == "failed":
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        payload = {
            "error": str(inner.get("error") or inner.get("message") or "unknown")[:500],
            "raw_kind": raw_kind,
        }
    elif kind == "completed":
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        payload = {
            "text": str(inner.get("text") or inner.get("last_agent_message") or ""),
            "raw_kind": raw_kind,
        }
    return kind, payload


def normalize_event(raw: dict):
    """原始事件 → :class:`BackendEvent`（保留原生 ID 与时间戳供去重/补读）。"""
    normalized = normalize_one(raw)
    if normalized is None:
        return None
    kind, payload = normalized
    return backend_event(
        kind,
        payload,
        backend_event_id=_event_id(raw),
        occurred_at=_occurred_at(raw) or utc_now(),
        raw_kind=str(raw.get("type") or raw.get("kind") or ""),
    )


def normalize_jsonl(text: str) -> list:
    """JSONL fixture → BackendEvent 列表；坏行跳过（不中断整个流）。"""
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        event = normalize_event(raw)
        if event is not None:
            events.append(event)
    return events


__all__ = ["normalize_event", "normalize_jsonl", "normalize_one"]
