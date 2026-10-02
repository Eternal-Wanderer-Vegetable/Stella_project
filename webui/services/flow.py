# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""消息流程取数（计划 §6.5/§6.6）：message_traces / flow_events 只读投影。

诚实边界（计划 §2.3）：
- ``complete`` 按存储原样返回；``status='running'`` 且久无事件的 trace 由
  reader 标 ``interrupted``（进程重启后未闭合的 root），绝不显示成成功。
- 事件按 ``id`` 增量拉取（SSE/轮询共用），``event_id`` 做客户端去重键。
- spec 缺失（旧版本/未随包）显式返回 null，由前端标 unmapped，不猜。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.observability.flow_catalog import TOPOLOGY_VERSION

# running 且超过该时长无任何事件 → interrupted（重启残留）
_INTERRUPTED_AFTER_SECONDS = 3600.0


def _trace_db():
    from core.observability import message_flow

    return message_flow.db_path()


def _connect_ro():
    from webui.db import connect_ro

    return connect_ro(_trace_db())


def _loads(text: str | None, default):
    try:
        parsed = json.loads(text or "")
        return parsed if parsed is not None else default
    except (ValueError, TypeError):
        return default


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def messages(
    *,
    platform: str | None = None,
    root_kind: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """消息轨迹列表（含无 Turn 的被动/命令/过滤路径）。"""
    conn = _connect_ro()
    if conn is None or not _table_exists(conn, "message_traces"):
        return {"total": 0, "items": []}
    try:
        conds, params = [], []
        if platform:
            conds.append("platform = ?")
            params.append(platform)
        if root_kind:
            conds.append("root_kind = ?")
            params.append(root_kind)
        if outcome:
            conds.append("outcome = ?")
            params.append(outcome)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM message_traces {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT trace_id, root_kind, platform, scope, source_message_key, "
            "started_utc, ended_utc, outcome, status, complete, loss, detail "
            f"FROM message_traces {where} "
            "ORDER BY started_utc DESC, trace_id DESC LIMIT ? OFFSET ?",
            (*params, int(limit), int(offset)),
        ).fetchall()
        items = []
        for r in rows:
            item = {
                "trace_id": r[0], "root_kind": r[1], "platform": r[2],
                "scope": r[3], "source_message_key": r[4],
                "started_utc": r[5], "ended_utc": r[6], "outcome": r[7],
                "status": r[8], "complete": bool(r[9]), "loss": bool(r[10]),
            }
            if item["status"] == "running":
                item["status"] = "interrupted"
            items.append(item)
        return {"total": int(total), "items": items}
    except Exception:
        return {"total": 0, "items": []}
    finally:
        conn.close()


def message_detail(trace_id: str) -> dict | None:
    """单条轨迹：root 元数据 + span 投影 + 双向关联 + 事件计数。"""
    conn = _connect_ro()
    if conn is None or not _table_exists(conn, "message_traces"):
        return None
    try:
        row = conn.execute(
            "SELECT trace_id, root_kind, platform, scope, source_message_key, "
            "topology_version, process_instance_id, started_utc, ended_utc, "
            "outcome, status, complete, loss, detail "
            "FROM message_traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if row is None:
            return None
        spans = conn.execute(
            "SELECT span_id, node_id, instance_key, parent_span_id, seq, "
            "started_utc, ended_utc, duration_ms, status, reason_code "
            "FROM flow_spans WHERE trace_id = ? ORDER BY seq ASC",
            (trace_id,),
        ).fetchall()
        relations = conn.execute(
            "SELECT parent_trace_id, child_trace_id, kind, evidence FROM "
            "trace_relations WHERE parent_trace_id = ? OR child_trace_id = ? "
            "ORDER BY id ASC",
            (trace_id, trace_id),
        ).fetchall()
        counts = conn.execute(
            "SELECT COUNT(*), MAX(id) FROM flow_events WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    finally:
        conn.close()
    item = {
        "trace_id": row[0], "root_kind": row[1], "platform": row[2],
        "scope": row[3], "source_message_key": row[4],
        "topology_version": row[5], "process_instance_id": row[6],
        "started_utc": row[7], "ended_utc": row[8], "outcome": row[9],
        "status": row[10], "complete": bool(row[11]), "loss": bool(row[12]),
        "detail": _loads(row[13], {}),
        "event_count": int(counts[0] or 0),
        "high_watermark": int(counts[1] or 0),
        "spans": [
            {
                "span_id": sp[0], "node_id": sp[1], "instance_key": sp[2],
                "parent_span_id": sp[3], "seq": sp[4],
                "started_utc": sp[5], "ended_utc": sp[6],
                "duration_ms": sp[7], "status": sp[8], "reason_code": sp[9],
            }
            for sp in spans
        ],
        "relations": [
            {
                "direction": "out" if r[0] == trace_id else "in",
                "trace_id": r[1] if r[0] == trace_id else r[0],
                "kind": r[2], "evidence": r[3],
            }
            for r in relations
        ],
    }
    if item["status"] == "running":
        item["status"] = "interrupted"
    return item


def events_after(trace_id: str, *, after_id: int = 0, limit: int = 500) -> list[dict]:
    """按自增 id 增量取事件（SSE 去重/补漏共用；升序）。"""
    conn = _connect_ro()
    if conn is None or not _table_exists(conn, "flow_events"):
        return []
    try:
        rows = conn.execute(
            "SELECT id, event_id, span_id, parent_span_id, node_id, "
            "instance_key, seq, kind, status, reason_code, ts_utc, "
            "duration_ms, summary, metrics "
            "FROM flow_events WHERE trace_id = ? AND id > ? "
            "ORDER BY id ASC LIMIT ?",
            (trace_id, int(after_id), int(limit)),
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [
        {
            "row_id": r[0], "event_id": r[1], "span_id": r[2],
            "parent_span_id": r[3], "node_id": r[4], "instance_key": r[5],
            "seq": r[6], "kind": r[7], "status": r[8], "reason_code": r[9],
            "ts_utc": r[10], "duration_ms": r[11], "summary": r[12],
            "metrics": _loads(r[13], {}),
        }
        for r in rows
    ]


def spec(version: str) -> dict | None:
    """静态拓扑 manifest：先查归档表，再回退随包文件；缺版本显式 None。"""
    conn = _connect_ro()
    if conn is not None and _table_exists(conn, "flow_specs"):
        try:
            row = conn.execute(
                "SELECT spec_json FROM flow_specs WHERE topology_version = ?",
                (version,),
            ).fetchone()
            if row is not None:
                return _loads(row[0], None)
        except Exception:
            pass
    return _bundled_spec(version)


def latest_spec_version() -> str:
    """当前进程可用的最新拓扑版本（随包常量；归档可能更新）。"""
    conn = _connect_ro()
    if conn is not None and _table_exists(conn, "flow_specs"):
        try:
            row = conn.execute(
                "SELECT topology_version FROM flow_specs "
                "ORDER BY created_utc DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                return str(row[0])
        except Exception:
            pass
    return TOPOLOGY_VERSION


def _bundled_spec(version: str) -> dict | None:
    """随包发布的 manifest（core/observability/flows/message-flow.*.json）。"""
    try:
        flows_dir = Path(__file__).resolve().parents[2] / "core" / "observability" / "flows"
        if not flows_dir.exists():
            return None
        for path in sorted(flows_dir.glob("message-flow.*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("topology_version") == version:
                return data
    except Exception:
        return None
    return None
