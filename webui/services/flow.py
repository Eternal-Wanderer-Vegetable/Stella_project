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


# ============================================================
# 输入 / 输出（用户验收：页面要能看到消息进去什么样、回复出来什么样）
# ============================================================

# 可产生回复的 root：窗口内找 BOT_SELF 落库行
_REPLY_ROOTS = {"qq_chat", "proactive", "webchat"}
# 有用户输入的 root：输入行按来源键/窗口匹配
_INPUT_ROOTS = {"qq_passive", "qq_chat", "qq_command", "webchat"}
_OUTPUT_WINDOW_FALLBACK_SECONDS = 900
_OUTPUT_MAX_LINES = 20


def _norm_key(iso: str) -> str:
    """ISO UTC 串 → SQLite timestamp 同形（"YYYY-MM-DD HH:MM:SS"）以便字典序比较。"""
    return (iso or "").replace("T", " ")[:19]


def _window_end(started_utc: str, ended_utc: str) -> str:
    if ended_utc:
        return _norm_key(ended_utc)
    import datetime as _dt

    base = _dt.datetime.fromisoformat(_norm_key(started_utc))
    return (base + _dt.timedelta(seconds=_OUTPUT_WINDOW_FALLBACK_SECONDS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _group_id_of(scope: str, root_kind: str) -> str | None:
    if root_kind == "webchat":
        return "-1"
    if scope.startswith("qq:"):
        return scope.split(":", 1)[1]
    return None


def message_io(trace_id: str) -> dict | None:
    """一条轨迹的真实输入（用户消息）与输出（确认送达的 BOT_SELF 回复行）。

    内容来自记忆库 ``group_messages``（会话页同一来源，鉴权相同）：
    输入按 (group, msg_id) 精确命中（QQ）或窗口内首条非 BOT_SELF 行
    （WebChat，msg_id 恒为 0）；输出 = 轨迹时间窗内的 BOT_SELF 行——
    只有确认送达的片段才会落库，空输出 ≠ 发送失败（备注说明）。
    命令回复不经 BOT_SELF 落库，输出为空属预期。
    """
    conn = _connect_ro()
    if conn is None or not _table_exists(conn, "message_traces"):
        return None
    try:
        row = conn.execute(
            "SELECT root_kind, scope, source_message_key, started_utc, ended_utc "
            "FROM message_traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    root_kind, scope, source_key, started_utc, ended_utc = row
    notes: list[str] = []
    # 命令回复不经 BOT_SELF 落库，唯一的记录通道是流程事件里的
    # command.reply 检查点（发送文本摘要，≤500 字）
    command_lines: list[str] = []
    try:
        tconn = _connect_ro()
        if tconn is not None and _table_exists(tconn, "flow_events"):
            try:
                command_lines = [
                    r[0]
                    for r in tconn.execute(
                        "SELECT summary FROM flow_events WHERE trace_id = ? "
                        "AND node_id = 'command.reply' AND kind = 'checkpoint' "
                        "ORDER BY id ASC LIMIT ?",
                        (trace_id, _OUTPUT_MAX_LINES),
                    ).fetchall()
                    if r[0]
                ]
            finally:
                tconn.close()
    except Exception:
        command_lines = []
    started_key = _norm_key(started_utc)
    end_key = _window_end(started_utc, ended_utc)
    group_id = _group_id_of(scope, root_kind)

    mem = _memory_conn()
    if mem is None:
        return {
            "input": None,
            "output": {
                "lines": command_lines[:_OUTPUT_MAX_LINES],
                "count": len(command_lines[:_OUTPUT_MAX_LINES]),
            },
            "notes": ["记忆库不可读，无法展示消息内容"],
        }
    try:
        inp = None
        if root_kind in _INPUT_ROOTS and group_id is not None:
            if root_kind == "webchat":
                row_in = mem.execute(
                    "SELECT user_id, content, msg_id FROM group_messages "
                    "WHERE group_id = ? AND source_kind != 'BOT_SELF' "
                    "AND timestamp >= ? ORDER BY id ASC LIMIT 1",
                    (group_id, started_key),
                ).fetchone()
            else:
                parts = (source_key or "").split(":")
                try:
                    msg_id = int(parts[3]) if len(parts) >= 4 else None
                except ValueError:
                    msg_id = None
                row_in = None
                if msg_id is not None:
                    row_in = mem.execute(
                        "SELECT user_id, content, msg_id FROM group_messages "
                        "WHERE group_id = ? AND msg_id = ? ORDER BY id DESC LIMIT 1",
                        (group_id, msg_id),
                    ).fetchone()
            if row_in is not None:
                inp = {"user_id": row_in[0], "content": row_in[1], "msg_id": row_in[2]}
        elif root_kind == "proactive":
            notes.append("主动发言：无用户输入")

        lines: list[str] = []
        if root_kind in _REPLY_ROOTS and group_id is not None:
            rows_out = mem.execute(
                "SELECT content FROM group_messages WHERE group_id = ? "
                "AND source_kind = 'BOT_SELF' AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY id ASC LIMIT ?",
                (group_id, started_key, end_key, _OUTPUT_MAX_LINES + 1),
            ).fetchall()
            lines = [r[0] for r in rows_out[:_OUTPUT_MAX_LINES]]
            if len(rows_out) > _OUTPUT_MAX_LINES:
                notes.append(f"仅展示前 {_OUTPUT_MAX_LINES} 行")
        elif root_kind in ("consolidate", "compact", "cometa_task", "effect"):
            notes.append("后台任务：无消息输入输出")
    finally:
        mem.close()

    if root_kind == "qq_passive":
        notes.append("被动消息：仅记录，不产生回复")
    if command_lines:
        lines = (lines + command_lines)[:_OUTPUT_MAX_LINES]
    if root_kind == "qq_command" and not lines:
        notes.append("该命令没有可展示的回复（未回复或发送失败）")
    if root_kind in _REPLY_ROOTS and not lines:
        notes.append("时间窗内没有确认送达的回复行（未回复或全部未送达）")
    return {
        "input": inp,
        "output": {"lines": lines, "count": len(lines)},
        "notes": notes,
    }


def _memory_conn():
    """记忆库只读连接（与 conversations 服务同一来源）；缺表返回 None。"""
    from pathlib import Path

    import config.settings as settings
    from webui.db import connect_ro

    conn = connect_ro(Path(settings.DB_PATH))
    if conn is None:
        return None
    if not _table_exists(conn, "group_messages"):
        conn.close()
        return None
    return conn
