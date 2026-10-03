# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""对象履历（计划 §6.1 entity_change / §6.6 对象视角）：append-only 状态事实。

候选、长期记忆、topic、effect、job、knowledge version、Cometa task 等
对象会经历多个流程；一条整合批次消费多个对象。这里只落**业务提交后的
状态变化事实**（commit 后确认，计划 §5：attempted/committed 分离），
不存原始业务内容——正文通过受控只读查询（记忆库/任务库）按 ID 读取。

- append-only：永不 UPDATE；纠错 = 新事件（tombstone）。
- 幂等：event_id 唯一，重复调用不重复落。
- 旁路：观测失败绝不影响业务事务（复用 message_flow 有界 writer）。

用法（业务提交成功后调用）::

    entity_history.record(
        "memory_candidate", cid, scope="shared", trace_id=root.trace_id,
        from_state="NEW", to_state="OBSERVING",
        version="policy:2026-09-27.0",
        changed_fields={"occurrence": 2}, content_digest=..., )
    entity_history.history("memory_candidate", cid)
"""

from __future__ import annotations

from typing import Any

from core.observability import message_flow
from core.observability.message_flow import _dump, _new_id, _scrub_deep, sanitize_text
from memory.timeutil import utc_now


def record(
    entity_type: str,
    entity_id: str,
    *,
    scope: str = "",
    trace_id: str = "",
    span_id: str = "",
    from_state: str = "",
    to_state: str = "",
    version: str = "",
    changed_fields: dict[str, Any] | None = None,
    content_digest: str = "",
    detail: dict[str, Any] | None = None,
) -> str:
    """落一条对象状态变化事实（业务 commit 之后调用；旁路绝不抛）。

    返回 event_id（失败返回 ""，不阻塞业务）。
    """
    if not entity_type or not entity_id:
        return ""
    try:
        event_id = _new_id()
        message_flow.submit_raw(("entity", (
            event_id,
            sanitize_text(entity_type)[:80],
            sanitize_text(entity_id)[:200],
            sanitize_text(scope)[:120],
            sanitize_text(trace_id)[:80],
            sanitize_text(span_id)[:40],
            sanitize_text(from_state)[:60],
            sanitize_text(to_state)[:60],
            sanitize_text(version)[:120],
            _dump(_scrub_deep(changed_fields or {})),
            sanitize_text(content_digest)[:80],
            utc_now().isoformat(timespec="milliseconds"),
            _dump(_scrub_deep(detail or {})),
        )))
        return event_id
    except Exception:
        return ""


def history(entity_type: str, entity_id: str, *, limit: int = 200) -> list[dict]:
    """按实体查状态变化事实（升序）；库不可读返回空（不猜）。"""
    conn = message_flow._connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT event_id, scope, trace_id, span_id, from_state, to_state, "
            "version, changed_fields, content_digest, ts_utc, detail "
            "FROM entity_events WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY id ASC LIMIT ?",
            (entity_type, entity_id, int(limit)),
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append({
            "event_id": r[0], "scope": r[1], "trace_id": r[2], "span_id": r[3],
            "from_state": r[4], "to_state": r[5], "version": r[6],
            "changed_fields": _loads(r[7]), "content_digest": r[8],
            "ts_utc": r[9], "detail": _loads(r[10]),
        })
    return out


def for_trace(trace_id: str, *, limit: int = 500) -> list[dict]:
    """按运行查本 run 触及的对象变化（对象视角 ↔ 运行视角互查）。"""
    conn = message_flow._connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT event_id, entity_type, entity_id, scope, from_state, "
            "to_state, version, content_digest, ts_utc "
            "FROM entity_events WHERE trace_id = ? ORDER BY id ASC LIMIT ?",
            (trace_id, int(limit)),
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [
        {
            "event_id": r[0], "entity_type": r[1], "entity_id": r[2],
            "scope": r[3], "from_state": r[4], "to_state": r[5],
            "version": r[6], "content_digest": r[7], "ts_utc": r[8],
        }
        for r in rows
    ]


def latest_state(entity_type: str, entity_id: str) -> dict | None:
    """实体最新一条状态事实（latest-state 查询；历史视角仍读 history）。"""
    conn = message_flow._connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT event_id, scope, from_state, to_state, version, ts_utc "
            "FROM entity_events WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (entity_type, entity_id),
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "event_id": row[0], "scope": row[1], "from_state": row[2],
        "to_state": row[3], "version": row[4], "ts_utc": row[5],
    }


def _loads(text: str | None) -> dict:
    import json

    try:
        parsed = json.loads(text or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}
