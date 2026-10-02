# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""消息流程事件记录（计划 §6.2）：真实 span、关联与结果，旁路纪律。

与 :mod:`core.observability.turn_trace` 的关系：同一个诊断库
（``STELLA_HOME/turn_trace.db``）新增 ``message_traces / flow_events /
flow_spans / trace_relations / flow_specs`` 五张表；旧 ``trace_events``
与其 Turn API 原样保留（schema 1 永远可读）。``record_event`` 的签名与
行为零改动——这里只写新表。

核心纪律（计划 §2.3/§6.5 观测缺口逐条对应）：

- **真实事件**：``start``/``finish`` 成对；没有 finish 的事件在重启后
  读作 interrupted/unknown，绝不显示成 skipped/succeeded。
- **时钟**：duration 只由同进程 ``time.monotonic`` 计算；UTC 单独记录
  （``ts_utc``）。跨进程先后用 causal relation 表达，不伪造精确全局序。
- **有界 writer**：事件先进内存有界队列，单守护线程批量事务落库；队列
  满只递增 known-loss 计数，**绝不阻塞消息热路径、绝不上抛**。
- **fail-open**：观测失败不改变业务结果；任何 ``record_*`` 都不抛异常。
- **完整性诚实**：``complete`` 只有在 trace 正常关闭、无未闭合 span、
  且期间没有 known loss 时才为 1；其余一律 partial。
- **隐私**：summary/metrics 过 turn_trace 的敏感键清洗；不存原始
  prompt、平台句柄、Authorization 或 Agent 秘密。

用法（入口建 root，代码点开 span）::

    ctx = message_flow.begin_trace(root_kind="webchat", platform="webchat",
                                   scope="webchat", trace_id=ctx.trace_id)
    with message_flow.span(ctx, "web.session_lock"):
        ...
    message_flow.decision(ctx, "chat.daily_budget", status="blocked",
                          reason_code="pause_all")
    message_flow.end_trace(ctx, outcome="delivered")
"""

from __future__ import annotations

import contextlib
import itertools
import queue
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from typing_extensions import Self

from memory.timeutil import log_sqlite_error, utc_now

# 事件种类（计划 §6.2 event_kind）
KIND_START = "start"
KIND_FINISH = "finish"
KIND_DECISION = "decision"
KIND_LINK = "link"
KIND_CHECKPOINT = "checkpoint"
KIND_TRACE_END = "trace_end"

# span/decision 状态（计划 §6.2 status 枚举；业务 outcome 另存 summary，
# 不与 span 成功混淆）
ST_RUNNING = "running"
ST_WAITING = "waiting"
ST_SUCCEEDED = "succeeded"
ST_SKIPPED = "skipped"
ST_BLOCKED = "blocked"
ST_FAILED = "failed"
ST_CANCELLED = "cancelled"
ST_TIMED_OUT = "timed_out"
ST_UNKNOWN = "unknown"

FLOW_SCHEMA_VERSION = 1

# 队列与批量参数：有界是硬约束（计划 §6.5），热路径最多付出一次 put_nowait
_QUEUE_MAX = 8192
_BATCH_MAX = 256
_FLUSH_INTERVAL = 0.2

# 活跃 trace 注册表上限：防泄漏（正常结束不删除——异步派生还要回查），
# 超限淘汰最旧条目。
_ACTIVE_MAX = 512

_WRITER_STOP = object()


def _new_id() -> str:
    return uuid.uuid4().hex


# ============================================================
# 存储：与 turn_trace 同库（turn_trace.configure 决定路径）
# ============================================================

_flow_initialized: dict[str, bool] = {}


def db_path() -> Path:
    """flow 表所在库路径：跟随 turn_trace（测试注入临时库自动生效）。"""
    from core.observability import turn_trace

    p = turn_trace.current_db_path()
    if p is not None:
        return p
    from config import STELLA_HOME

    return Path(STELLA_HOME) / "turn_trace.db"


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS message_traces (
        trace_id TEXT PRIMARY KEY,
        root_kind TEXT NOT NULL DEFAULT '',
        platform TEXT NOT NULL DEFAULT '',
        scope TEXT NOT NULL DEFAULT '',
        source_message_key TEXT NOT NULL DEFAULT '',
        topology_version TEXT NOT NULL DEFAULT '',
        process_instance_id TEXT NOT NULL DEFAULT '',
        started_utc TEXT NOT NULL,
        ended_utc TEXT NOT NULL DEFAULT '',
        outcome TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'running',
        complete INTEGER NOT NULL DEFAULT 0,
        loss INTEGER NOT NULL DEFAULT 0,
        detail TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_message_traces_started "
    "ON message_traces (started_utc DESC)",
    "CREATE INDEX IF NOT EXISTS idx_message_traces_root "
    "ON message_traces (root_kind, started_utc DESC)",
    """
    CREATE TABLE IF NOT EXISTS flow_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        trace_id TEXT NOT NULL,
        span_id TEXT NOT NULL DEFAULT '',
        parent_span_id TEXT NOT NULL DEFAULT '',
        node_id TEXT NOT NULL,
        instance_key TEXT NOT NULL DEFAULT '',
        seq INTEGER NOT NULL DEFAULT 0,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '',
        reason_code TEXT NOT NULL DEFAULT '',
        ts_utc TEXT NOT NULL,
        duration_ms REAL,
        summary TEXT NOT NULL DEFAULT '',
        metrics TEXT NOT NULL DEFAULT '{}',
        complete INTEGER NOT NULL DEFAULT 1
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_flow_events_trace ON flow_events (trace_id, id)",
    """
    CREATE TABLE IF NOT EXISTS flow_spans (
        trace_id TEXT NOT NULL,
        span_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        instance_key TEXT NOT NULL DEFAULT '',
        parent_span_id TEXT NOT NULL DEFAULT '',
        seq INTEGER NOT NULL DEFAULT 0,
        started_utc TEXT NOT NULL DEFAULT '',
        ended_utc TEXT NOT NULL DEFAULT '',
        duration_ms REAL,
        status TEXT NOT NULL DEFAULT '',
        reason_code TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (trace_id, span_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trace_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_trace_id TEXT NOT NULL,
        child_trace_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        evidence TEXT NOT NULL DEFAULT '',
        created_utc TEXT NOT NULL,
        UNIQUE(parent_trace_id, child_trace_id, kind)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_trace_relations_child "
    "ON trace_relations (child_trace_id)",
    """
    CREATE TABLE IF NOT EXISTS flow_specs (
        topology_version TEXT PRIMARY KEY,
        spec_json TEXT NOT NULL,
        created_utc TEXT NOT NULL
    )
    """,
)


def _connect() -> sqlite3.Connection | None:
    """打开 flow 库并幂等建表；失败返回 None（旁路：绝不抛）。"""
    try:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10.0)
        key = str(path)
        if not _flow_initialized.get(key):
            for ddl in _SCHEMA:
                conn.execute(ddl)
            conn.commit()
            _flow_initialized[key] = True
        return conn
    except Exception as e:
        log_sqlite_error("message_flow._connect", e)
        return None


# ============================================================
# 有界 writer：单守护线程批量事务；队列满标 known loss
# ============================================================

class _Writer:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._dropped = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False

    # -- 提交侧（热路径：只做 put_nowait）--
    def submit(self, row: tuple) -> None:
        self._ensure_thread()
        try:
            self._q.put_nowait(row)
        except queue.Full:
            with self._lock:
                self._dropped += 1

    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def queue_size(self) -> int:
        return self._q.qsize()

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def flush(self, timeout: float = 5.0) -> None:
        """屏障：等队列里在它之前提交的行全部落库（测试与优雅关闭用）。"""
        if not self.alive():
            return
        barrier = threading.Event()
        try:
            self._q.put((None, barrier), timeout=timeout)
        except queue.Full:
            return
        barrier.wait(timeout)

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._q.put((_WRITER_STOP, None))
            self._thread.join(timeout=5.0)
            self._thread = None
            self._started = False

    # -- 消费侧 --
    def _ensure_thread(self) -> None:
        if self._started and self.alive():
            return
        with self._lock:
            if self._started and self.alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="message-flow-writer", daemon=True
            )
            self._thread.start()
            self._started = True

    def _run(self) -> None:  # pragma: no cover - 线程主循环（由 flush 驱动测试）
        while True:
            item, extra = self._q.get()
            if item is _WRITER_STOP:
                return
            batch: list[tuple] = []
            barrier = None
            if isinstance(extra, threading.Event):
                barrier = extra
            else:
                batch.append((item, extra))
            while len(batch) < _BATCH_MAX:
                try:
                    item2, extra2 = self._q.get_nowait()
                except queue.Empty:
                    break
                if item2 is _WRITER_STOP:
                    self._q.put((_WRITER_STOP, None))
                    break
                if isinstance(extra2, threading.Event):
                    barrier = extra2
                    break
                batch.append((item2, extra2))
            if batch:
                self._write_batch(batch)
            if barrier is not None:
                barrier.set()

    def _write_batch(self, batch: list[tuple]) -> None:
        conn = _connect()
        if conn is None:
            with self._lock:
                self._dropped += len(batch)
            return
        try:
            for table, values in batch:
                self._insert(conn, table, values)
            conn.commit()
        except Exception:
            # 单批失败整体重试一次（事务原子）；再失败按 known loss 处理
            try:
                conn.rollback()
                for table, values in batch:
                    self._insert(conn, table, values)
                conn.commit()
            except Exception as e2:
                log_sqlite_error("message_flow.writer", e2)
                with self._lock:
                    self._dropped += len(batch)
        finally:
            conn.close()

    @staticmethod
    def _insert(conn: sqlite3.Connection, table: str, v: tuple) -> None:
        if table == "trace":
            conn.execute(
                "INSERT OR REPLACE INTO message_traces (trace_id, root_kind, platform, "
                "scope, source_message_key, topology_version, process_instance_id, "
                "started_utc, ended_utc, outcome, status, complete, loss, detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", v)
        elif table == "trace_end":
            conn.execute(
                "UPDATE message_traces SET ended_utc=?, outcome=?, status=?, "
                "complete=?, loss=? WHERE trace_id=?", v)
        elif table == "event":
            conn.execute(
                "INSERT OR IGNORE INTO flow_events (event_id, trace_id, span_id, "
                "parent_span_id, node_id, instance_key, seq, kind, status, "
                "reason_code, ts_utc, duration_ms, summary, metrics, complete) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", v)
        elif table == "span":
            conn.execute(
                "INSERT OR REPLACE INTO flow_spans (trace_id, span_id, node_id, "
                "instance_key, parent_span_id, seq, started_utc, ended_utc, "
                "duration_ms, status, reason_code) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                v)
        elif table == "span_end":
            conn.execute(
                "UPDATE flow_spans SET ended_utc=?, duration_ms=?, status=?, "
                "reason_code=? WHERE trace_id=? AND span_id=?", v)
        elif table == "relation":
            conn.execute(
                "INSERT OR IGNORE INTO trace_relations (parent_trace_id, "
                "child_trace_id, kind, evidence, created_utc) VALUES (?,?,?,?,?)", v)
        elif table == "spec":
            conn.execute(
                "INSERT OR REPLACE INTO flow_specs (topology_version, spec_json, "
                "created_utc) VALUES (?,?,?)", v)


_writer = _Writer()


def flow_health() -> dict[str, Any]:
    """观测面自检：队列水位、known loss、writer 存活（不解释成业务失败）。"""
    return {
        "queue": _writer.queue_size(),
        "dropped": _writer.dropped(),
        "writer_alive": _writer.alive(),
        "schema_version": FLOW_SCHEMA_VERSION,
    }


def flush(timeout: float = 5.0) -> None:
    """等全部已提交事件落库（测试断言与优雅关闭用）。"""
    _writer.flush(timeout)


# ============================================================
# FlowContext 与 span
# ============================================================

def _scrub(value: Any) -> Any:
    from core.observability import turn_trace

    return turn_trace.scrub(value)


@dataclass
class FlowContext:
    """一次入口处理的身份与运行态（进程内；跨进程用显式 relation）。"""

    trace_id: str
    root_kind: str
    platform: str = ""
    scope: str = ""
    source_message_key: str = ""
    topology_version: str = ""
    process_instance_id: str = field(default_factory=lambda: _new_id()[:12])
    started_mono: float = field(default_factory=time.monotonic)
    started_utc: str = field(default_factory=lambda: utc_now().isoformat(timespec="milliseconds"))
    drops_at_start: int = 0
    outcome: str = ""
    ended: bool = False
    _seq: Iterator[int] = field(default_factory=itertools.count)
    _open_spans: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def next_seq(self) -> int:
        return next(self._seq)

    def open_count(self) -> int:
        return len(self._open_spans)


# 活跃 trace 注册：跨层取回（delivery 只有 trace_id；后台派生要找父）
_active: dict[str, FlowContext] = {}
_active_lock = threading.Lock()


def _register(ctx: FlowContext) -> None:
    with _active_lock:
        if len(_active) >= _ACTIVE_MAX:
            for old in list(_active)[: len(_active) - _ACTIVE_MAX + 1]:
                _active.pop(old, None)
        _active[ctx.trace_id] = ctx


def by_trace(trace_id: str) -> FlowContext | None:
    """按 trace_id 查活跃 context（不含已注册上限淘汰的旧 trace）。"""
    return _active.get(trace_id)


def by_source_key(key: str) -> FlowContext | None:
    """按 source_message_key 查活跃 context（跨层关联：task_id → trace）。"""
    if not key:
        return None
    for ctx in _active.values():
        if ctx.source_message_key == key and not ctx.ended:
            return ctx
    return None


def active_traces() -> list[str]:
    return list(_active)


def begin_trace(
    *,
    root_kind: str,
    platform: str = "",
    scope: str = "",
    source_message_key: str = "",
    trace_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> FlowContext:
    """入口建 root：写入 message_traces 行 + root span start 事件。

    ``trace_id`` 传入既有的接入追踪 ID（ctx.trace_id）即共用同一身份；
    缺省时新建。重复 root（同 trace 二次 begin）是编程错误但按幂等处理：
    返回已存在的 context，不重复写行。
    """
    from core.observability.flow_catalog import TOPOLOGY_VERSION

    if trace_id:
        found = _active.get(trace_id)
        if found is not None and not found.ended:
            return found
    ctx = FlowContext(
        trace_id=trace_id or _new_id(),
        root_kind=root_kind,
        platform=platform,
        scope=scope,
        source_message_key=source_message_key,
        topology_version=TOPOLOGY_VERSION,
        drops_at_start=_writer.dropped(),
    )
    _register(ctx)
    _writer.submit(("trace", (
        ctx.trace_id, root_kind, platform, scope, source_message_key,
        ctx.topology_version, ctx.process_instance_id, ctx.started_utc,
        "", "", "running", 0, 0,
        _dump(_scrub(detail or {})),
    )))
    _emit_span_start(ctx, span_id="root", node_id=root_kind,
                     parent_span_id="", instance_key="", summary="")
    return ctx


def end_trace(
    ctx: FlowContext,
    *,
    outcome: str = "",
    status: str = "closed",
    complete: bool | None = None,
) -> None:
    """关闭 root：trace_end 事件 + message_traces 终态。

    ``complete`` 缺省按「无未闭合 span 且期间无 known loss」计算；调用方
    可以显式给 False（如发送部分失败时仍关闭 root——root 同步结束与后台
    任务状态独立，计划 §3.2）。
    """
    if ctx.ended:
        return
    now_mono = time.monotonic()
    ctx.ended = True
    ctx.outcome = outcome
    ts = utc_now().isoformat(timespec="milliseconds")
    # 未闭合 span：进程内泄漏或异常路径漏配对——按 unknown 落终态事件，
    # 完整性归 partial（重启场景由 reader 按 status=running 判 interrupted）
    with ctx._lock:
        leaked = dict(ctx._open_spans)
        ctx._open_spans.clear()
    for span_id, state in leaked.items():
        _emit_event(ctx, kind=KIND_FINISH, node_id=state.node_id,
                    span_id=span_id, parent_span_id=state.parent,
                    instance_key=state.instance_key, status=ST_UNKNOWN,
                    reason_code="span_not_closed",
                    ts_utc=ts,
                    duration_ms=(now_mono - state.mono) * 1000.0)
        _writer.submit(("span", (
            ctx.trace_id, span_id, state.node_id, state.instance_key,
            state.parent, state.seq, state.ts, ts,
            (now_mono - state.mono) * 1000.0, ST_UNKNOWN, "span_not_closed")))
    loss = 1 if _writer.dropped() != ctx.drops_at_start else 0
    if complete is None:
        complete = not leaked and not loss
    root_duration = (now_mono - ctx.started_mono) * 1000.0
    _emit_event(ctx, kind=KIND_TRACE_END, node_id=ctx.root_kind, span_id="root",
                parent_span_id="", instance_key="", status=status,
                ts_utc=ts,
                duration_ms=root_duration,
                summary=outcome)
    _writer.submit(("span_end", (
        ts, root_duration, status, "", ctx.trace_id, "root")))
    _writer.submit(("trace_end", (
        ts, outcome, status, 1 if complete else 0, loss, ctx.trace_id)))


def _dump(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return "{}"


def _emit_event(
    ctx: FlowContext,
    *,
    kind: str,
    node_id: str,
    span_id: str = "",
    parent_span_id: str = "",
    instance_key: str = "",
    status: str = "",
    reason_code: str = "",
    ts_utc: str = "",
    duration_ms: float | None = None,
    summary: str = "",
    metrics: dict[str, Any] | None = None,
) -> str:
    """写一条事件（INSERT OR IGNORE：event_id 幂等，SSE 去重键）。"""
    event_id = _new_id()
    _writer.submit(("event", (
        event_id, ctx.trace_id, span_id, parent_span_id, node_id,
        instance_key, ctx.next_seq(), kind, status, reason_code,
        ts_utc or utc_now().isoformat(timespec="milliseconds"),
        None if duration_ms is None else round(duration_ms, 1),
        (summary or "")[:500], _dump(_scrub(metrics or {})), 1)))
    return event_id


def _emit_span_start(
    ctx: FlowContext,
    *,
    span_id: str,
    node_id: str,
    parent_span_id: str,
    instance_key: str,
    summary: str,
) -> str:
    ts = utc_now().isoformat(timespec="milliseconds")
    _emit_event(ctx, kind=KIND_START, node_id=node_id, span_id=span_id,
                parent_span_id=parent_span_id, instance_key=instance_key,
                status=ST_RUNNING, ts_utc=ts, summary=summary)
    _writer.submit(("span", (
        ctx.trace_id, span_id, node_id, instance_key, parent_span_id,
        ctx.next_seq(), ts, "", None, ST_RUNNING, "")))
    return span_id


@dataclass
class _SpanState:
    node_id: str
    parent: str
    instance_key: str
    mono: float
    ts: str
    seq: int


class FlowSpan:
    """span 句柄：``with`` 使用；异常→failed、取消→cancelled 自动落终态。"""

    __slots__ = ("_ctx", "_finished", "node_id", "span_id")

    def __init__(self, ctx: FlowContext, span_id: str, node_id: str) -> None:
        self._ctx = ctx
        self.span_id = span_id
        self.node_id = node_id
        self._finished = False

    def finish(
        self,
        *,
        status: str = ST_SUCCEEDED,
        reason_code: str = "",
        summary: str = "",
        metrics: dict[str, Any] | None = None,
    ) -> None:
        if self._finished or self._ctx.ended:
            self._finished = True
            return
        self._finished = True
        with self._ctx._lock:
            state = self._ctx._open_spans.pop(self.span_id, None)
        if state is None:
            return
        ts = utc_now().isoformat(timespec="milliseconds")
        _emit_event(
            self._ctx, kind=KIND_FINISH, node_id=state.node_id,
            span_id=self.span_id, parent_span_id=state.parent,
            instance_key=state.instance_key, status=status,
            reason_code=reason_code, ts_utc=ts,
            duration_ms=(time.monotonic() - state.mono) * 1000.0,
            summary=summary, metrics=metrics)
        _writer.submit(("span", (
            self._ctx.trace_id, self.span_id, state.node_id,
            state.instance_key, state.parent, state.seq, state.ts, ts,
            (time.monotonic() - state.mono) * 1000.0, status, reason_code)))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._finished:
            return False
        if exc_type is None:
            self.finish()
        elif issubclass(exc_type, asyncio_cancelled()):
            self.finish(status=ST_CANCELLED, reason_code="cancelled")
        else:
            self.finish(status=ST_FAILED,
                        reason_code=exc_type.__name__[:120],
                        summary=str(exc)[:300] if exc else "")
        return False  # 异常照常上抛：观测绝不吞业务异常


def asyncio_cancelled() -> tuple[type[BaseException], ...]:
    import asyncio

    return (asyncio.CancelledError,)


def span(
    ctx: FlowContext | None,
    node_id: str,
    *,
    parent: "FlowSpan | str | None" = None,
    instance_key: str = "",
    summary: str = "",
) -> FlowSpan:
    """开一个 span。``ctx`` 为 None（观测未接入/单测）时返回空操作 span。

    ``parent`` 缺省挂在 root 下；传 FlowSpan 或 span_id 显式建父子。
    """
    if ctx is None or ctx.ended:
        return FlowSpan(_NULL_CTX, "noop", node_id)
    parent_id = "root"
    if isinstance(parent, FlowSpan):
        parent_id = parent.span_id
    elif parent:
        parent_id = str(parent)
    span_id = _new_id()[:16]
    seq = ctx.next_seq()
    ts = utc_now().isoformat(timespec="milliseconds")
    with ctx._lock:
        ctx._open_spans[span_id] = _SpanState(
            node_id=node_id, parent=parent_id, instance_key=instance_key,
            mono=time.monotonic(), ts=ts, seq=seq)
    _emit_span_start(ctx, span_id=span_id, node_id=node_id,
                     parent_span_id=parent_id, instance_key=instance_key,
                     summary=summary)
    return FlowSpan(ctx, span_id, node_id)


def node(
    ctx: FlowContext | None,
    node_id: str,
    *,
    parent: "FlowSpan | str | None" = None,
    instance_key: str = "",
    summary: str = "",
) -> FlowSpan:
    """``with message_flow.node(ctx, "chat.group_lock"):``——FlowSpan 本身
    就是上下文管理器，这里只是语义化别名。"""
    return span(ctx, node_id, parent=parent, instance_key=instance_key,
                summary=summary)


def decision(
    ctx: FlowContext | None,
    node_id: str,
    *,
    status: str,
    reason_code: str = "",
    summary: str = "",
    metrics: dict[str, Any] | None = None,
    instance_key: str = "",
    span_id: str = "",
    parent_span_id: str = "",
) -> None:
    """无持续时长的决策点（早退、闸门、路由选择）：单条 decision 事件。"""
    if ctx is None or ctx.ended:
        return
    _emit_event(ctx, kind=KIND_DECISION, node_id=node_id,
                span_id=span_id, parent_span_id=parent_span_id,
                instance_key=instance_key, status=status,
                reason_code=reason_code, summary=summary, metrics=metrics)


def checkpoint(
    ctx: FlowContext | None,
    node_id: str,
    *,
    summary: str = "",
    metrics: dict[str, Any] | None = None,
    span_id: str = "",
) -> None:
    """过程事实（无终态语义）：如「已 spawn 整合，不等待结果」。"""
    if ctx is None or ctx.ended:
        return
    _emit_event(ctx, kind=KIND_CHECKPOINT, node_id=node_id, span_id=span_id,
                status=ST_SUCCEEDED, summary=summary, metrics=metrics)


def link(
    parent_trace_id: str,
    child_trace_id: str,
    *,
    kind: str = "spawned",
    evidence: str = "",
) -> None:
    """跨 trace 因果关系（多对多，计划 §3.2）：relation 行 + 双侧 link 事件。"""
    if not parent_trace_id or not child_trace_id or parent_trace_id == child_trace_id:
        return
    ts = utc_now().isoformat(timespec="milliseconds")
    _writer.submit(("relation", (parent_trace_id, child_trace_id, kind,
                                 evidence[:200], ts)))
    for tid, direction in ((parent_trace_id, "spawned"),
                           (child_trace_id, "spawned_by")):
        target = _active.get(tid)
        if target is not None and not target.ended:
            _emit_event(target, kind=KIND_LINK, node_id="trace.link",
                        instance_key=direction, summary=child_trace_id
                        if direction == "spawned" else parent_trace_id,
                        metrics={"related_trace": child_trace_id
                                 if direction == "spawned" else parent_trace_id,
                                 "relation": kind})


# ---- ChatContext 挂载（显式传递优先于环境隐式传播，计划 §6.2）----

_CTX_ATTR = "_message_flow_ctx"


def attach(chat_ctx: Any, flow_ctx: FlowContext | None) -> None:
    with contextlib.suppress(Exception):
        setattr(chat_ctx, _CTX_ATTR, flow_ctx)


def flow_of(chat_ctx: Any) -> FlowContext | None:
    """从 ChatContext 取 flow context；没有则按 trace_id 回查注册表。"""
    found = getattr(chat_ctx, _CTX_ATTR, None)
    if found is not None:
        return found
    trace_id = getattr(chat_ctx, "trace_id", "") or ""
    return by_trace(trace_id) if trace_id else None


def detach(chat_ctx: Any) -> None:
    with contextlib.suppress(Exception):
        if getattr(chat_ctx, _CTX_ATTR, None) is not None:
            setattr(chat_ctx, _CTX_ATTR, None)


_NULL_CTX = FlowContext(trace_id="noop", root_kind="noop", ended=True)


def prune(now: float | None = None) -> dict[str, int]:
    """flow 表保留清理：与 turn_trace 同口径（metadata 30 天；spec 永久）。"""
    del now
    out = {"traces": 0, "events": 0, "spans": 0}
    try:
        import datetime as _dt

        cutoff = (utc_now() - _dt.timedelta(days=30.0)).isoformat(
            timespec="milliseconds")
        conn = _connect()
        if conn is None:
            return out
        try:
            old = [r[0] for r in conn.execute(
                "SELECT trace_id FROM message_traces WHERE started_utc < ?",
                (cutoff,)).fetchall()]
            if old:
                marks = ",".join("?" * len(old))
                out["events"] = conn.execute(
                    f"DELETE FROM flow_events WHERE trace_id IN ({marks})",
                    old).rowcount or 0
                out["spans"] = conn.execute(
                    f"DELETE FROM flow_spans WHERE trace_id IN ({marks})",
                    old).rowcount or 0
                conn.execute(
                    f"DELETE FROM trace_relations WHERE parent_trace_id IN ({marks}) "
                    f"OR child_trace_id IN ({marks})", old + old)
                out["traces"] = conn.execute(
                    "DELETE FROM message_traces WHERE trace_id IN "
                    f"({marks})", old).rowcount or 0
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log_sqlite_error("message_flow.prune", e)
    return out
