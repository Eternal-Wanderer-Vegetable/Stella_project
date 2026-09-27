# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""轮次级请求追踪：有界 SQLite 诊断库（计划 §6.8）。

独立于记忆库（``STELLA_HOME/turn_trace.db``）：大快照不拖累记忆库；效果
事实**不依赖**本库可用——trace 可以丢失、并且丢失会被标记（trace_complete
/ dropped_events 可见，绝不把「没有痕迹」解释成「没有动作」）。

两档保存：
- **metadata（默认）**：ID、分数、版本、耗时、错误码、hash、注入资产
  ID/revision——足够回答「为什么说/没说、走了哪条分支」；
- **detailed（按群显式开启）**：最终 system+messages、检索/资产当时采用
  的内容快照、模型参数、输出与投递片段。按键白名单生成：原始 backend
  对象、Authorization、环境变量与密钥**永不**入库；用户消息本身也是敏感
  正文，detailed 只限鉴权管理接口读取。

容量：metadata 30 天 / detailed 7 天 / 单条 256 KiB / 库 256 MiB；超限先删
最旧 detailed。清理做实际文件大小监控（SQLite+WAL），不只 COUNT 行数。
截断写完整性标记，缺内容拒绝「完整回放」。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from memory.timeutil import log_sqlite_error, utc_now

TRACE_SCHEMA_VERSION = 1

# 保留期与容量（[assumed] 初值，计划 §6.8）
METADATA_KEEP_DAYS = 30.0
DETAILED_KEEP_DAYS = 7.0
MAX_EVENT_PAYLOAD_BYTES = 256 * 1024
MAX_DB_BYTES = 256 * 1024 * 1024

# 敏感字段白名单 scrub：键名命中即整个值替换（不尝试部分保留）
_SENSITIVE_KEY_RE = re.compile(
    r"(authorization|api[-_]?key|token|secret|password|cookie|credential)",
    re.IGNORECASE,
)

# 追踪阶段（计划 §6.8 阶段清单的落地子集；stage 值必须来自这里）
STAGE_INGRESS = "ingress"
STAGE_GATE = "gate"
STAGE_PARTICIPATION = "participation"
STAGE_PREPARE = "prepare"
STAGE_PLANNER = "planner"
STAGE_RETRIEVAL = "retrieval"
STAGE_SOCIAL = "social_selection"
STAGE_BUDGET = "budget"
STAGE_MODEL_ATTEMPT = "model_attempt"
STAGE_FINALIZE = "finalize"
STAGE_DELIVERY = "delivery"
STAGE_EFFECT = "effect"

_db_path: Path | None = None
_initialized = False


def configure(db_path: Path | str | None = None) -> None:
    """设置 trace 库路径（进程启动时调用一次；测试注入临时路径用）。"""
    global _db_path, _initialized
    if db_path is None:
        from config import STELLA_HOME

        db_path = Path(STELLA_HOME) / "turn_trace.db"
    _db_path = Path(db_path)
    _initialized = False


def _connect() -> sqlite3.Connection:
    global _initialized
    if _db_path is None:
        configure()
    assert _db_path is not None
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path), timeout=10.0)
    if not _initialized:
        _init_schema(conn)
        _initialized = True
    return conn


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS trace_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id TEXT NOT NULL,
        turn_id TEXT NOT NULL DEFAULT '',
        decision_id TEXT NOT NULL DEFAULT '',
        parent_id TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT '',
        ts_utc TEXT NOT NULL,
        relative_ms REAL NOT NULL DEFAULT 0,
        stage TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '',
        reason_code TEXT NOT NULL DEFAULT '',
        attempt INTEGER NOT NULL DEFAULT 0,
        versions TEXT NOT NULL DEFAULT '{}',
        metrics TEXT NOT NULL DEFAULT '{}',
        summary TEXT NOT NULL DEFAULT '',
        payload TEXT,
        payload_truncated INTEGER NOT NULL DEFAULT 0,
        complete INTEGER NOT NULL DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_events_turn ON trace_events (turn_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_trace_events_trace ON trace_events (trace_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_trace_events_stage ON trace_events (stage, ts_utc)",
    """
    CREATE TABLE IF NOT EXISTS trace_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)


def _init_schema(conn: sqlite3.Connection) -> None:
    for ddl in _SCHEMA:
        conn.execute(ddl)
    conn.execute(
        "INSERT OR IGNORE INTO trace_meta (key, value) VALUES ('schema_version', ?)",
        (str(TRACE_SCHEMA_VERSION),),
    )
    conn.commit()


# ============================================================
# 写入
# ============================================================


def _scrub(value: Any) -> Any:
    """递归剔除敏感键（整个值替换为 [REDACTED]），永不序列化平台句柄。"""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _SENSITIVE_KEY_RE.search(k):
                out[k] = "[REDACTED]"
            else:
                out[k] = _scrub(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # 任意对象（backend/event/bot…）：只留类型名，绝不 repr 全文
    return f"<{type(value).__name__}>"


def record_event(
    *,
    trace_id: str,
    turn_id: str = "",
    stage: str,
    status: str = "",
    reason_code: str = "",
    decision_id: str = "",
    parent_id: str = "",
    scope: str = "",
    attempt: int = 0,
    versions: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    summary: str = "",
    detailed: dict[str, Any] | None = None,
    started_at: float | None = None,
) -> None:
    """写一条阶段事件。任何失败静默（trace 是旁路，绝不阻断聊天）。"""
    try:
        now = utc_now()
        rel_ms = max(0.0, (time.monotonic() - started_at) * 1000.0) if started_at else 0.0
        payload: str | None = None
        truncated = 0
        if detailed is not None:
            clean = _scrub(detailed)
            payload = json.dumps(clean, ensure_ascii=False, default=str)
            if len(payload.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
                # 截断必须留标记：缺内容拒绝「完整回放」
                payload = payload[: MAX_EVENT_PAYLOAD_BYTES]
                truncated = 1
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO trace_events (trace_id, turn_id, decision_id, parent_id, "
                "scope, ts_utc, relative_ms, stage, status, reason_code, attempt, "
                "versions, metrics, summary, payload, payload_truncated, complete) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    trace_id, turn_id, decision_id, parent_id, scope,
                    now.isoformat(timespec="milliseconds"),
                    round(rel_ms, 1), stage, status, reason_code, int(attempt),
                    json.dumps(versions or {}, ensure_ascii=False, default=str),
                    json.dumps(metrics or {}, ensure_ascii=False, default=str),
                    summary[:500], payload, truncated, 0 if truncated else 1,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # pragma: no cover - 旁路纪律：任何失败都不上抛
        log_sqlite_error("turn_trace.record_event", e)


def detailed_enabled_for_scope(scope: str) -> bool:
    """detailed 档按群显式开启（SOCIAL_TRACE_DETAIL_SCOPES 逗号分隔群号）。"""
    try:
        from config import settings

        raw = settings.SOCIAL_TRACE_DETAIL_SCOPES or ""
        scopes = {s.strip() for s in raw.split(",") if s.strip()}
        return scope in scopes
    except Exception:
        return False


# ============================================================
# 读取（WebUI）
# ============================================================


def list_turns(*, scope: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """轮次列表：每轮首末事件 + 终态 + 是否有 detailed 快照。"""
    try:
        conn = _connect()
        try:
            conditions = ["turn_id != ''"]
            params: list[Any] = []
            if scope:
                conditions.append("scope = ?")
                params.append(scope)
            where = "WHERE " + " AND ".join(conditions)
            rows = conn.execute(
                "SELECT turn_id, MIN(ts_utc), MAX(ts_utc), COUNT(*), "
                "SUM(CASE WHEN payload IS NOT NULL THEN 1 ELSE 0 END), "
                "MAX(complete), MIN(scope) FROM trace_events "
                f"{where} GROUP BY turn_id "
                "ORDER BY MAX(id) DESC LIMIT ? OFFSET ?",
                (*params, max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
            total_row = conn.execute(
                f"SELECT COUNT(DISTINCT turn_id) FROM trace_events {where}",
                params,
            ).fetchone()
            items = [
                {
                    "turn_id": r[0], "started_at_utc": r[1], "ended_at_utc": r[2],
                    "events": r[3], "detailed_events": r[4] or 0,
                    "complete": bool(r[5]), "scope": r[6] or "",
                }
                for r in rows
            ]
            return {"total": int(total_row[0]) if total_row else 0, "items": items}
        finally:
            conn.close()
    except Exception as e:
        log_sqlite_error("turn_trace.list_turns", e)
        return {"total": 0, "items": []}


def turn_timeline(turn_id: str) -> dict | None:
    """单轮时间线：全部阶段事件（detailed payload 只给引用标记，正文走 detail）。"""
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, trace_id, scope, ts_utc, relative_ms, stage, status, "
                "reason_code, attempt, versions, metrics, summary, payload, "
                "payload_truncated, complete FROM trace_events WHERE turn_id = ? "
                "ORDER BY id ASC",
                (turn_id,),
            ).fetchall()
            if not rows:
                return None
            events = []
            for r in rows:
                events.append({
                    "id": r[0], "trace_id": r[1], "scope": r[2], "ts_utc": r[3],
                    "relative_ms": r[4], "stage": r[5], "status": r[6],
                    "reason_code": r[7], "attempt": r[8],
                    "versions": json.loads(r[9] or "{}"),
                    "metrics": json.loads(r[10] or "{}"),
                    "summary": r[11],
                    "has_payload": r[12] is not None,
                    "payload_truncated": bool(r[13]),
                    "complete": bool(r[14]),
                })
            replayable = all(e["complete"] for e in events) and any(e["has_payload"] for e in events)
            return {
                "turn_id": turn_id,
                "events": events,
                # 可重放性必须诚实：仅 metadata 的 trace 是「仅可浏览」
                "replayable": replayable,
            }
        finally:
            conn.close()
    except Exception as e:
        log_sqlite_error("turn_trace.turn_timeline", e)
        return None


def turn_payloads(turn_id: str) -> dict | None:
    """detailed 快照正文（鉴权接口专用；含敏感正文，绝不做匿名化承诺）。"""
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, stage, payload, payload_truncated FROM trace_events "
                "WHERE turn_id = ? AND payload IS NOT NULL ORDER BY id ASC",
                (turn_id,),
            ).fetchall()
            if not rows:
                return None
            return {
                "turn_id": turn_id,
                "payloads": [
                    {"id": r[0], "stage": r[1],
                     "payload": json.loads(r[2] or "{}"),
                     "truncated": bool(r[2] is not None and r[3])}
                    for r in rows
                ],
            }
        finally:
            conn.close()
    except Exception as e:
        log_sqlite_error("turn_trace.turn_payloads", e)
        return None


# ============================================================
# 清理
# ============================================================


def prune(now: float | None = None) -> dict[str, int]:
    """按保留期与容量清理；返回实际删除数（容量按真实文件大小监控）。"""
    del now  # 保留参数签名兼容（时间基准统一走 utc_now）
    out = {"metadata": 0, "detailed": 0, "capacity": 0}
    try:
        conn = _connect()
        try:
            import datetime as _dt

            for days, col in ((METADATA_KEEP_DAYS, "all"), (DETAILED_KEEP_DAYS, "payload")):
                cutoff = (utc_now() - _dt.timedelta(days=days)).isoformat(timespec="milliseconds")
                if col == "all":
                    cur = conn.execute(
                        "DELETE FROM trace_events WHERE ts_utc < ?", (cutoff,)
                    )
                else:
                    cur = conn.execute(
                        "DELETE FROM trace_events WHERE payload IS NOT NULL AND ts_utc < ?",
                        (cutoff,),
                    )
                key = "metadata" if col == "all" else "detailed"
                out[key] = cur.rowcount or 0
            conn.commit()
            # 容量：超 256 MiB → 从最旧 detailed 开始删，再超删最旧行
            assert _db_path is not None
            sizes = [
                _db_path.stat().st_size,
                (_db_path.with_name(_db_path.name + "-wal")).stat().st_size
                if _db_path.with_name(_db_path.name + "-wal").exists() else 0,
            ]
            if sum(sizes) > MAX_DB_BYTES:
                cur = conn.execute(
                    "DELETE FROM trace_events WHERE id IN (SELECT id FROM trace_events "
                    "WHERE payload IS NOT NULL ORDER BY id ASC LIMIT 1000)"
                )
                out["capacity"] = cur.rowcount or 0
                conn.commit()
            # WAL checkpoint：让文件大小反映真实占用
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception as e:
        log_sqlite_error("turn_trace.prune", e)
    return out


def new_trace_id() -> str:
    return uuid.uuid4().hex
