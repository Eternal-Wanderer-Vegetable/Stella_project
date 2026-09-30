# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Codex 原始事件 → AgentEvent 归一器（方案 §6.7 的映射表）。

两条入口，各有契约：

- :func:`notification_to_event`：**运行时主路径**。SDK 0.147.0 的 typed
  ``Notification``（dataclass，method + pydantic payload）→ BackendEvent。
  方法名/payload 类型以 M0 录制的 fixture 为契约
  （tests/cometa/fixtures/codex_events.jsonl，2026-09-30 于
  openai-codex 0.147.0 + codex-cli 0.147.0 实录）；
- :func:`normalize_event` / :func:`normalize_jsonl`：**fixture 重放路径**。
  JSONL dict → BackendEvent，供契约测试不经 SDK 重放录制的事件。

M0 实录确认的方法名（App Server v2）::

    turn/started          TurnStartedNotification
    item/started          ItemStartedNotification   (item.type: userMessage|agentMessage|
                                                     commandExecution|mcpToolCall|fileChange|...)
    item/completed        ItemCompletedNotification
    item/agentMessage/delta  AgentMessageDeltaNotification {delta, item_id}
    turn/completed        TurnCompletedNotification (turn.items 内含 agentMessage 最终答复)
    error                 ErrorNotification {error{message, additional_details}, will_retry}

未知 kind 一律降级 ``phase``（raw_kind 保留，payload 截断脱敏）——保留事实、
不臆造语义；``completed``/``failed``/``interrupted`` 是三个不同的终态信号，
**不能只检查进程 exit code**（§6.7）。
"""

from __future__ import annotations

import json
from dataclasses import fields as dc_fields
from dataclasses import is_dataclass
from datetime import datetime

from cometa.backends.base import backend_event
from cometa.models import utc_now

# 原始事件里可作为「原生事件 ID」的字段（按序取第一个非空）。
_EVENT_ID_FIELDS = ("id", "event_id", "call_id", "item_id")

# App Server v2 的方法名 → 归一 kind（M0 2026-09-30 实录）。
_KNOWN_KINDS = {
    "turn/started": "phase",
    "item/started": "phase",
    "item/updated": "phase",
    "item/completed": "item_completed",
    "item/agentMessage/delta": "message_delta",
    "turn/completed": "completed",
    "turn/failed": "failed",
    "turn/interrupted": "interrupted",
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
    """把一条 JSONL 原始事件映射为 ``(归一kind, payload)``（fixture 重放路径）。"""
    if not isinstance(raw, dict):
        return None
    raw_kind = str(raw.get("method") or raw.get("type") or raw.get("kind") or "").strip()
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
    elif kind == "failed":
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        err = inner.get("error") or {}
        payload = {
            "error": str(
                err.get("message") if isinstance(err, dict) else (err or inner.get("error") or "unknown")
            )[:500],
            "raw_kind": raw_kind,
        }
    elif kind == "item_completed":
        # 条目完成 ≠ 轮次完成：agentMessage 的完成是该条目的权威值（message_final），
        # 其余条目类型降 phase（§6.7：完成事件才是该 item 权威值）
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        item = inner.get("item") if isinstance(inner.get("item"), dict) else {}
        if str(item.get("type") or "") == "agentMessage":
            return "message_final", {"text": str(item.get("text") or ""),
                                     "raw_kind": raw_kind}
        return "phase", {"kind": "item_completed",
                         "item_type": str(item.get("type") or "unknown"),
                         "raw_kind": raw_kind}
    elif kind == "completed":
        # turn/completed 不等于成功：失败轮次也走这个方法投递（SDK 同源语义），
        # 归一器必须看 payload.turn.status（§6.7：不能只看进程 exit code 的同款纪律）
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        turn = inner.get("turn") if isinstance(inner.get("turn"), dict) else {}
        status = str(turn.get("status") or "")
        if status == "failed":
            err = turn.get("error") or {}
            message = str(err.get("message") if isinstance(err, dict) else "")[:500]
            return "failed", {"error": message or "turn failed", "raw_kind": raw_kind}
        if status == "interrupted":
            return "interrupted", {"raw_kind": raw_kind}
        text = ""
        for item in turn.get("items") or []:
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = str(item.get("text") or "")
        return "completed", {"text": text, "raw_kind": raw_kind}
    elif raw_kind == "error":
        # 重放路径的 error 语义与运行时 notification_to_event 对齐：
        # will_retry=True → 重连进度；False → 终局失败（§6.7）。
        inner = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
        err = inner.get("error") or {}
        message = str(err.get("message") if isinstance(err, dict) else "")[:300]
        details = str(err.get("additional_details") if isinstance(err, dict) else "")[:200]
        if inner.get("will_retry"):
            return "phase", {"phase": "backend_reconnecting",
                              "detail": f"{message} {details}".strip(),
                              "raw_kind": raw_kind}
        return "failed", {"error": f"{message} {details}".strip() or "unknown",
                          "raw_kind": raw_kind}
    return kind, payload


def normalize_event(raw: dict):
    """JSONL 原始事件 → :class:`BackendEvent`（fixture 重放用）。"""
    normalized = normalize_one(raw)
    if normalized is None:
        return None
    kind, payload = normalized
    occurred = _occurred_at(raw)
    return backend_event(
        kind,
        payload,
        backend_event_id=_event_id(raw),
        occurred_at=occurred or utc_now(),
        raw_kind=str(raw.get("method") or raw.get("type") or ""),
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


# ============================================================
# 运行时主路径：typed Notification → BackendEvent
# ============================================================


def _payload_model(notification):
    """Notification.payload 是 pydantic 模型（dataclass Notification 的字段）。"""
    return getattr(notification, "payload", None)


def _enum_value(value) -> str:
    """枚举/字符串统一取值：str(enum) 在 py3.11+ 是 'Class.member' 形式，
    直接比较会漏（M0 合成测试抓到 TurnStatus）。"""
    return str(getattr(value, "value", value) or "")


def _item_to_event_kind(item) -> tuple[str, dict]:
    """item/completed 里的 ThreadItem → 归一 kind + payload（§6.7：完成事件是
    该 item 的权威值）。

    SDK 的 items 是包装器：真身在 ``ThreadItem.root``（M0 合成测试抓到）。
    """
    item = getattr(item, "root", item)
    itype = str(getattr(item, "type", "") or "")
    text = str(getattr(item, "text", "") or "")
    if itype == "agentMessage":
        return "message_final", {"text": text}
    if itype == "commandExecution":
        return "command_record", {
            "command": str(getattr(item, "command", "") or ""),
            "exit_code": getattr(item, "exit_code", None),
            "status": str(getattr(item, "status", "") or ""),
            "output": str(getattr(item, "aggregated_output", "") or "")[:300],
            "file": None,
        }
    if itype == "mcpToolCall":
        return "command_record", {
            "command": f"mcp:{getattr(item, 'server', '')}/{getattr(item, 'tool', '')}",
            "status": str(getattr(item, "status", "") or ""),
            "output": str(getattr(item, "result", "") or "")[:300],
        }
    if itype == "fileChange":
        return "command_record", {"command": "fileChange", "file": None,
                                  "output": str(getattr(item, "cwd", "") or "")[:120]}
    if itype == "webSearch":
        return "command_record", {"command": f"webSearch: {getattr(item, 'query', '')}"[:200]}
    if itype == "userMessage":
        return "phase", {"detail": "输入已受理"}
    return "phase", {"detail": itype or "unknown item"}


def notification_to_event(notification):
    """SDK ``Notification`` → :class:`BackendEvent`（运行时主路径，M0 契约）。

    **按 payload 类型分派**（与 SDK 自身的 _collect_turn_result 同语义），
    method 字符串只作未知事件的 raw 记录：

    - ``TurnStartedNotification`` → phase；
    - ``ItemCompletedNotification`` → 按 item.type 分派（agentMessage →
      message_final，命令/MCP/文件/搜索 → command_record，userMessage →
      phase 回执）；``ItemStartedNotification`` → phase（完成事件才是权威值）；
    - ``AgentMessageDeltaNotification`` → message_delta（executor 有界合并）；
    - ``ThreadTokenUsageUpdatedNotification`` → usage（token 计量）；
    - ``ErrorNotification`` → will_retry=True 视为 phase（后端重连中），
      False 视为 failed；
    - ``TurnCompletedNotification`` → **检查 turn.status**：failed/interrupted
      是失败/中断（SDK 把失败轮次也经 turn/completed 投递），completed 才是
      completed，最终答复从 turn.items 提取；
    - 未知 → phase（raw_kind 保留，不臆造语义）。
    """
    from openai_codex.generated import v2_all

    method = str(getattr(notification, "method", "") or "")
    payload = _payload_model(notification)
    occurred = utc_now()

    if isinstance(payload, v2_all.ThreadTokenUsageUpdatedNotification):
        usage = getattr(payload, "token_usage", None)
        total = getattr(usage, "total", None)
        return backend_event("usage", {
            "tokens_in": getattr(total, "input_tokens", None) if total else None,
            "tokens_out": getattr(total, "output_tokens", None) if total else None,
        }, backend_event_id=None, occurred_at=occurred, raw_kind=method)

    if isinstance(payload, v2_all.AgentMessageDeltaNotification):
        return backend_event("message_delta", {
            "delta": str(getattr(payload, "delta", "") or ""),
            "item_id": str(getattr(payload, "item_id", "") or ""),
        }, backend_event_id=None, occurred_at=occurred, raw_kind=method)

    if isinstance(payload, v2_all.ItemStartedNotification):
        item = getattr(payload, "item", None)
        kind, detail = _item_to_event_kind(item)
        if kind == "message_final":
            kind = "phase"  # 开始不算权威值；完成事件才是（§6.7）
        return backend_event(kind, {"kind": "item_started", **detail},
                             backend_event_id=str(getattr(item, "id", "") or "") or None,
                             occurred_at=occurred, raw_kind=method)

    if isinstance(payload, v2_all.ItemCompletedNotification):
        item = getattr(payload, "item", None)
        kind, detail = _item_to_event_kind(item)
        return backend_event(kind, {"kind": "item_completed", **detail},
                             backend_event_id=str(getattr(item, "id", "") or "") or None,
                             occurred_at=occurred, raw_kind=method)

    if isinstance(payload, v2_all.TurnStartedNotification):
        turn = getattr(payload, "turn", None)
        return backend_event("phase", {"phase": "turn_started",
                                       "turn_id": str(getattr(turn, "id", "") or "")},
                             backend_event_id=None, occurred_at=occurred, raw_kind=method)

    if isinstance(payload, v2_all.TurnCompletedNotification):
        turn = getattr(payload, "turn", None)
        status = _enum_value(getattr(turn, "status", ""))
        if status == "failed":
            # 失败轮次也经 turn/completed 投递（SDK _raise_for_failed_turn 同源）
            err = getattr(turn, "error", None)
            message = str(getattr(err, "message", "") or "turn failed")
            return backend_event("failed", {"error": message},
                                 backend_event_id=None, occurred_at=occurred,
                                 raw_kind=method or "turn/completed:failed")
        if status == "interrupted":
            return backend_event("interrupted", {"error": "backend turn interrupted"},
                                 backend_event_id=None, occurred_at=occurred,
                                 raw_kind=method or "turn/completed:interrupted")
        final_text = ""
        for item in getattr(turn, "items", None) or []:
            item = getattr(item, "root", item)
            if str(getattr(item, "type", "") or "") == "agentMessage":
                final_text = str(getattr(item, "text", "") or "")
        return backend_event("completed", {"text": final_text},
                             backend_event_id=None, occurred_at=occurred, raw_kind=method)

    if isinstance(payload, v2_all.ErrorNotification):
        message = str(getattr(payload.error, "message", "") or "")
        details = str(getattr(payload.error, "additional_details", "") or "")
        if getattr(payload, "will_retry", False):
            return backend_event(
                "phase",
                {"phase": "backend_reconnecting",
                 "detail": f"{message} {details}".strip()[:300]},
                backend_event_id=None, occurred_at=occurred, raw_kind=method)
        return backend_event("failed", {"error": f"{message} {details}".strip()[:500]},
                             backend_event_id=None, occurred_at=occurred,
                             raw_kind=method or "error")

    # 未知：保留事实，不臆造语义（§6.7）
    fields = {f.name: str(getattr(payload, f.name, ""))[:120]
              for f in dc_fields(payload)} if is_dataclass(payload) else {}
    return backend_event("phase", {"kind": "unknown", "raw_kind": method, "detail": fields},
                         backend_event_id=None, occurred_at=occurred, raw_kind=method)


__all__ = ["normalize_event", "normalize_jsonl", "normalize_one", "notification_to_event"]
