# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""内部流程事件记录（计划 §6.1/§6.2）：真实 span、关联与结果，旁路纪律。

与 :mod:`core.observability.turn_trace` 的关系：同一个诊断库
（``STELLA_HOME/turn_trace.db``）承载 ``message_traces / flow_events /
flow_spans / trace_relations / flow_specs`` 五张表，schema 2 增量新增
``flow_run_loss``（per-run 损失账本）与 ``entity_events``（对象履历），
旧 ``trace_events`` 与其 Turn API 原样保留（schema 1 永远可读）。

核心纪律（计划 §2.2/§6.1 观测缺口逐条对应）：

- **真实事件**：``start``/``finish`` 成对；没有 finish 的事件在重启后
  读作 interrupted/unknown，绝不显示成 skipped/succeeded。
- **活跃判定（O01）**：``status='running'`` 不再由 reader 一律改判
  interrupted。进程化身（``process_instance_id`` = 进程级
  ``PROCESS_INCARNATION``）+ writer 心跳（``last_heartbeat_utc``）+
  已知终态共同判定：本进程在跑 → running；旧化身且心跳过期 → interrupted。
- **时钟**：duration 只由同进程 ``time.monotonic`` 计算；UTC 单独记录
  （``ts_utc``）。业务时间（``business_ts``）与观测时间独立。
- **有界 writer**：事件先进内存有界队列，单守护线程批量事务落库；队列
  满只递增 per-run 损失账本，**绝不阻塞消息热路径、绝不上抛**。
- **per-run 完整性（O03）**：损失按 trace 归账（``flow_run_loss``），
  不再用全局 drop 差值冒充。producer 结束只写 ``producer_ended`` 标记；
  writer 确认该 run 已提交行的事务后落最终 ``integrity``
  （complete/partial/unknown）——异步写失败会**纠正**已结束 run 的完整性。
- **fail-open**：观测失败不改变业务结果；任何 ``record_*`` 都不抛异常。
- **隐私（O07）**：summary/metrics 过敏感键清洗 + 字符串级脱敏
  （Authorization/Bearer/token/api-key 形状一律 <redacted>）；异常以稳定
  ``error_code``（异常类名）记录，不存原文秘密。
- **spec 归档（O08）**：首次 root 引用某拓扑版本时把随包 manifest 字节
  归档进 ``flow_specs``（INSERT OR IGNORE，同 digest 幂等），历史轨迹
  不因新版本丢拓扑。

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
import hashlib
import itertools
import queue
import re
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

# 完整性终值（writer 落账）：producer 结束 ≠ 持久化完整
INTEGRITY_COMPLETE = "complete"
INTEGRITY_PARTIAL = "partial"
INTEGRITY_UNKNOWN = "unknown"

FLOW_SCHEMA_VERSION = 3

# spec 归档规范化标识（修复计划 §6.2）：digest = canonical payload 的完整
# 64 位 SHA-256（排除 source_revision、排序键、紧凑 UTF-8），与生成器
# content_hash 同一算法；archived payload 即该 canonical 形态。
SPEC_CANONICALIZATION = "stella-flow-content-v1"

# 身份完整性（修复计划 §6.1）：exact=规范身份齐备；legacy_partial=旧键缺
# 字段；conflict=补充时与可信值冲突；missing=无任何身份。空串=未标注。
IDENTITY_EXACT = "exact"
IDENTITY_LEGACY_PARTIAL = "legacy_partial"
IDENTITY_CONFLICT = "conflict"
IDENTITY_MISSING = "missing"

# spec 绑定完整性（修复计划 §6.2）：与 runtime integrity 分别表达。
SPEC_BINDING_EXACT = "exact"
SPEC_BINDING_LEGACY = "legacy_unverified"
SPEC_BINDING_MISSING = "missing"
SPEC_BINDING_INVALID = "invalid"

# 进程化身：每次进程启动唯一（活跃判定 O01 的第一信号）。
PROCESS_INCARNATION = uuid.uuid4().hex[:12]

# 队列与批量参数：有界是硬约束（计划 §6.5），热路径最多付出一次 put_nowait
_QUEUE_MAX = 8192
_BATCH_MAX = 256
_FLUSH_INTERVAL = 0.2
# writer 心跳间隔（秒）：空闲时为 running run 刷新 last_heartbeat_utc
_HEARTBEAT_INTERVAL = 15.0

# 活跃 trace 注册表上限：防泄漏（正常结束不删除——异步派生还要回查），
# 超限淘汰最旧条目。
_ACTIVE_MAX = 512

_WRITER_STOP = object()

# 字符串级脱敏（O07）：秘密形状一律打码——键 + 后随值（"Authorization: Bearer
# sk-xxx" / "token=abc" 整段消失），宁多不漏。
_REDACT_RE = re.compile(
    r"(?i)\b(authorization|bearer|api[_-]?key|apikey|token|access[_-]?token|"
    r"refresh[_-]?token|secret|password|passwd|credential)s?\b"
    r"(?:\s*[:=：]?\s*[^\s,;\"'}]+){1,2}"
)
_REDACTED = "<redacted>"


def _new_id() -> str:
    return uuid.uuid4().hex


def sanitize_text(value: Any) -> str:
    """字符串级脱敏（O07）：秘密形状打码、截断到事件 summary 上限。

    所有进入 summary/error 文本的渠道统一走这里；metrics 里的字符串值
    也经此处理。纯键名清洗（turn_trace.scrub）之外的第二道防线。
    """
    text = str(value or "")
    if not text:
        return ""
    text = _REDACT_RE.sub(_REDACTED, text)
    return text[:500]


def error_code_of(exc: BaseException | type[BaseException] | None) -> str:
    """稳定错误码（O07）：异常类名本身，不含消息文本（消息可能带秘密）。"""
    if exc is None:
        return ""
    if isinstance(exc, BaseException):
        return type(exc).__name__[:120]
    try:
        return exc.__name__[:120]
    except AttributeError:
        return sanitize_text(exc)[:120]


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
        detail TEXT NOT NULL DEFAULT '{}',
        process_kind TEXT NOT NULL DEFAULT '',
        origin TEXT NOT NULL DEFAULT '',
        trigger TEXT NOT NULL DEFAULT '',
        route TEXT NOT NULL DEFAULT '',
        business_ts TEXT NOT NULL DEFAULT '',
        last_heartbeat_utc TEXT NOT NULL DEFAULT '',
        spec_digest TEXT NOT NULL DEFAULT '',
        producer_ended INTEGER NOT NULL DEFAULT 0,
        integrity TEXT NOT NULL DEFAULT '',
        lost_events INTEGER NOT NULL DEFAULT 0,
        persisted_events INTEGER NOT NULL DEFAULT 0,
        conversation_key TEXT NOT NULL DEFAULT '',
        bot_id TEXT NOT NULL DEFAULT '',
        conversation_kind TEXT NOT NULL DEFAULT '',
        peer_id TEXT NOT NULL DEFAULT '',
        storage_session_id INTEGER,
        source_message_id TEXT NOT NULL DEFAULT '',
        identity_state TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_message_traces_identity "
    "ON message_traces (conversation_key, started_utc DESC)",
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
        complete INTEGER NOT NULL DEFAULT 1,
        attempt INTEGER NOT NULL DEFAULT 0,
        fact_kind TEXT NOT NULL DEFAULT '',
        error_code TEXT NOT NULL DEFAULT ''
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
        attempt INTEGER NOT NULL DEFAULT 0,
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
    """
    CREATE TABLE IF NOT EXISTS flow_run_loss (
        trace_id TEXT NOT NULL,
        lost INTEGER NOT NULL DEFAULT 0,
        reason TEXT NOT NULL DEFAULT '',
        first_seen_utc TEXT NOT NULL,
        last_seen_utc TEXT NOT NULL,
        PRIMARY KEY (trace_id, first_seen_utc)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT '',
        trace_id TEXT NOT NULL DEFAULT '',
        span_id TEXT NOT NULL DEFAULT '',
        from_state TEXT NOT NULL DEFAULT '',
        to_state TEXT NOT NULL DEFAULT '',
        version TEXT NOT NULL DEFAULT '',
        changed_fields TEXT NOT NULL DEFAULT '{}',
        content_digest TEXT NOT NULL DEFAULT '',
        ts_utc TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_entity_events_entity "
    "ON entity_events (entity_type, entity_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_entity_events_trace "
    "ON entity_events (trace_id)",
    # spec 不可变归档（修复计划 §6.2，schema 3）：按内容 digest 精确绑定，
    # 同 topology_version 不同内容可并存；保留旧 flow_specs 不重建。
    """
    CREATE TABLE IF NOT EXISTS flow_spec_blobs (
        spec_digest TEXT PRIMARY KEY,
        topology_version TEXT NOT NULL,
        manifest_schema INTEGER NOT NULL,
        canonicalization TEXT NOT NULL,
        spec_json TEXT NOT NULL,
        archived_at_utc TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_flow_spec_blobs_version "
    "ON flow_spec_blobs (topology_version, spec_digest)",
)

# 旧库增量迁移（schema 1/2 → 3）：幂等 ALTER，缺列才补（计划 §9.2 additive）
_MIGRATIONS: dict[str, tuple[str, ...]] = {
    "message_traces": (
        "process_kind TEXT NOT NULL DEFAULT ''",
        "origin TEXT NOT NULL DEFAULT ''",
        "trigger TEXT NOT NULL DEFAULT ''",
        "route TEXT NOT NULL DEFAULT ''",
        "business_ts TEXT NOT NULL DEFAULT ''",
        "last_heartbeat_utc TEXT NOT NULL DEFAULT ''",
        "spec_digest TEXT NOT NULL DEFAULT ''",
        "producer_ended INTEGER NOT NULL DEFAULT 0",
        "integrity TEXT NOT NULL DEFAULT ''",
        "lost_events INTEGER NOT NULL DEFAULT 0",
        "persisted_events INTEGER NOT NULL DEFAULT 0",
        # schema 3（修复计划 §6.1）：规范会话身份列；storage_session_id 保持
        # 可空（未知 = NULL，绝不伪造 0）
        "conversation_key TEXT NOT NULL DEFAULT ''",
        "bot_id TEXT NOT NULL DEFAULT ''",
        "conversation_kind TEXT NOT NULL DEFAULT ''",
        "peer_id TEXT NOT NULL DEFAULT ''",
        "storage_session_id INTEGER",
        "source_message_id TEXT NOT NULL DEFAULT ''",
        "identity_state TEXT NOT NULL DEFAULT ''",
    ),
    "flow_events": (
        "attempt INTEGER NOT NULL DEFAULT 0",
        "fact_kind TEXT NOT NULL DEFAULT ''",
        "error_code TEXT NOT NULL DEFAULT ''",
    ),
    "flow_spans": ("attempt INTEGER NOT NULL DEFAULT 0",),
}


def _migrate(conn: sqlite3.Connection) -> None:
    """把旧表补齐 schema 2 的列；新库直接建表无需迁移。"""
    for table, columns in _MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue
        for col_def in columns:
            col_name = col_def.split()[0]
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")


def _connect() -> sqlite3.Connection | None:
    """打开 flow 库并幂等建表/迁移；失败返回 None（旁路：绝不抛）。"""
    try:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10.0)
        key = str(path)
        if not _flow_initialized.get(key):
            # 顺序（旧库迁移正确性）：先建缺失表 → 再 ALTER 补列 → 最后建
            # 索引。索引若在补列前创建，旧库会因缺列而失败（schema 3 教训）。
            for ddl in _SCHEMA:
                if ddl.lstrip().startswith("CREATE TABLE"):
                    conn.execute(ddl)
            _migrate(conn)
            for ddl in _SCHEMA:
                if not ddl.lstrip().startswith("CREATE TABLE"):
                    conn.execute(ddl)
            conn.commit()
            _flow_initialized[key] = True
        return conn
    except Exception as e:
        log_sqlite_error("message_flow._connect", e)
        return None


# ============================================================
# 有界 writer：单守护线程批量事务；队列满/写失败按 per-run 账本归账
# ============================================================

class _Writer:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
        self._dropped = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = False
        # 队列拒绝/写失败但尚未落账本的 per-run 损失（trace_id → 行数）
        self._pending_loss: dict[str, int] = {}
        self._last_heartbeat = 0.0

    # -- 提交侧（热路径：只做 put_nowait）--
    def submit(self, row: tuple) -> None:
        self._ensure_thread()
        try:
            self._q.put_nowait(row)
        except queue.Full:
            trace_id = _row_trace_id(row)
            with self._lock:
                self._dropped += 1
                if trace_id:
                    self._pending_loss[trace_id] = (
                        self._pending_loss.get(trace_id, 0) + 1)

    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def pending_loss(self) -> dict[str, int]:
        with self._lock:
            return dict(self._pending_loss)

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
            try:
                item, extra = self._q.get(timeout=_HEARTBEAT_INTERVAL)
            except queue.Empty:
                # 空闲唤醒：为在跑 run 跳一次心跳（长静默 run 的 O01 活性）
                self._heartbeat_tick()
                continue
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
            # 心跳按间隔节流（15s）：逐批 UPDATE+commit 的 fsync 会把吞吐
            # 压掉一个量级（容量基准实测），心跳只需秒级新鲜度（O01 判定
            # 阈值 120s）
            self._heartbeat_tick()
            if barrier is not None:
                barrier.set()

    def _heartbeat_tick(self, *, force: bool = False) -> None:
        """为在跑 run 刷新心跳（O01）：空闲与活跃各按间隔节流。"""
        now_mono = time.monotonic()
        if not force and (now_mono - self._last_heartbeat) < _HEARTBEAT_INTERVAL:
            return
        self._last_heartbeat = now_mono
        conn = _connect()
        if conn is None:
            return
        try:
            conn.execute(
                "UPDATE message_traces SET last_heartbeat_utc=? "
                "WHERE status='running' AND producer_ended=0 "
                "AND process_instance_id=?",
                (utc_now().isoformat(timespec="milliseconds"),
                 PROCESS_INCARNATION))
            conn.commit()
        except Exception as e:  # pragma: no cover - 心跳失败旁路
            log_sqlite_error("message_flow.heartbeat", e)
        finally:
            conn.close()

    def _write_batch(self, batch: list[tuple]) -> None:
        conn = _connect()
        if conn is None:
            self._record_loss(batch, "storage_unavailable")
            return
        ended_traces: dict[str, tuple[int, bool]] = {}
        touched: set[str] = set()
        try:
            self._apply_batch(conn, batch, ended_traces, touched)
            self._drain_pending_loss(conn)
            conn.commit()
        except Exception:
            # 整批失败 → 逐 run 分组重试：单 run 失败只归账到自己，
            # 绝不污染同批其他 run 的完整性（O03 不串线）
            with contextlib.suppress(Exception):
                conn.rollback()
            for _group_trace, rows in _group_by_trace(batch):
                group_ended: dict[str, tuple[int, bool]] = {}
                group_touched: set[str] = set()
                try:
                    self._apply_batch(conn, rows, group_ended, group_touched)
                    self._drain_pending_loss(conn)
                    conn.commit()
                    ended_traces.update(group_ended)
                    touched.update(group_touched)
                except Exception as e2:
                    with contextlib.suppress(Exception):
                        conn.rollback()
                    log_sqlite_error("message_flow.writer", e2)
                    self._record_loss(rows, "writer_error")
        finally:
            conn.close()
        # 提交确认后落最终完整性（O03）：producer_ended + integrity 终值
        if ended_traces:
            self._finalize_runs(ended_traces)
        if touched:
            self._touch_heartbeats(touched)

    def _apply_batch(
        self,
        conn: sqlite3.Connection,
        batch: list[tuple],
        ended: dict[str, tuple[int, bool]],
        touched: set[str],
    ) -> None:
        for table, values in batch:
            trace_id = self._insert(conn, table, values)
            if trace_id:
                touched.add(trace_id)
                if table == "trace_end":
                    # complete 列由 producer 计算（未闭合 span 事实），
                    # 完整性终值由本 writer 在提交确认后落（O03）
                    ended[trace_id] = (
                        self._persisted_high_water(conn, trace_id),
                        bool(values[3]),
                    )

    @staticmethod
    def _persisted_high_water(conn: sqlite3.Connection, trace_id: str) -> int:
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM flow_events WHERE trace_id=?",
                (trace_id,)).fetchone()
            return int(row[0] or 0)
        except Exception:
            return 0

    def _finalize_runs(self, ended: dict[str, tuple[int, bool]]) -> None:
        """事务确认后落 producer 终态：producer_ended=1 + integrity 终值。

        ``complete`` 是 producer 的未闭合 span 事实；账本里有损失或 producer
        自报不完整 → partial。账本不可写时显式 unknown，绝不冒充完整。
        """
        conn = _connect()
        if conn is None:
            return
        try:
            for trace_id, (high_water, producer_complete) in ended.items():
                lost = conn.execute(
                    "SELECT COALESCE(SUM(lost), 0) FROM flow_run_loss "
                    "WHERE trace_id=?", (trace_id,)).fetchone()[0]
                lost += self.pending_loss().get(trace_id, 0)
                if lost:
                    integrity = INTEGRITY_PARTIAL
                elif producer_complete:
                    integrity = INTEGRITY_COMPLETE
                else:
                    integrity = INTEGRITY_PARTIAL
                conn.execute(
                    "UPDATE message_traces SET producer_ended=1, "
                    "persisted_events=?, lost_events=?, integrity=? "
                    "WHERE trace_id=?",
                    (high_water, lost, integrity, trace_id))
            conn.commit()
        except Exception as e:  # pragma: no cover - 终态落账失败旁路
            log_sqlite_error("message_flow.finalize", e)
        finally:
            conn.close()

    def _record_loss(self, batch: list[tuple], reason: str) -> None:
        """写失败/存储不可用 → per-run 损失归账（账本 + trace 行纠正）。"""
        counts: dict[str, int] = {}
        for row in batch:
            trace_id = _row_trace_id(row)
            if trace_id:
                counts[trace_id] = counts.get(trace_id, 0) + 1
        if not counts:
            return
        with self._lock:
            for trace_id, n in counts.items():
                self._pending_loss[trace_id] = (
                    self._pending_loss.get(trace_id, 0) + n)
        conn = _connect()
        if conn is None:
            return
        try:
            self._drain_pending_loss(conn)
            conn.commit()
        except Exception as e:  # pragma: no cover - 账本不可用旁路
            log_sqlite_error("message_flow.loss_ledger", e)
        finally:
            conn.close()

    def _drain_pending_loss(self, conn: sqlite3.Connection) -> None:
        """把内存暂存的 per-run 损失写进账本并纠正 trace 行完整性。"""
        with self._lock:
            pending = self._pending_loss
            self._pending_loss = {}
        if not pending:
            return
        ts = utc_now().isoformat(timespec="milliseconds")
        for trace_id, lost in pending.items():
            if lost <= 0:
                continue
            conn.execute(
                "INSERT INTO flow_run_loss (trace_id, lost, reason, "
                "first_seen_utc, last_seen_utc) VALUES (?,?,?,?,?) "
                "ON CONFLICT(trace_id, first_seen_utc) DO NOTHING",
                (trace_id, lost, "queue_full_or_write_failure", ts, ts))
            conn.execute(
                "UPDATE message_traces SET lost_events=COALESCE(lost_events,0)+?, "
                "loss=1, complete=0, integrity=? WHERE trace_id=?",
                (lost, INTEGRITY_PARTIAL, trace_id))

    @staticmethod
    def _touch_heartbeats(trace_ids: set[str]) -> None:
        conn = _connect()
        if conn is None:
            return
        try:
            conn.execute(
                "UPDATE message_traces SET last_heartbeat_utc=? "
                "WHERE status='running' AND process_instance_id=? "
                f"AND trace_id IN ({','.join('?' * len(trace_ids))})",
                (utc_now().isoformat(timespec="milliseconds"),
                 PROCESS_INCARNATION, *trace_ids))
            conn.commit()
        except Exception:  # pragma: no cover
            pass
        finally:
            conn.close()

    def _insert(self, conn: sqlite3.Connection, table: str, v: tuple) -> str:
        """写一行；返回归属 trace_id（per-run 账本用），无归属返回 ''。"""
        if table == "bundle":
            # owned root bundle（修复计划 §6.2）：spec prerequisite + trace 行
            # + root start 在同一事务单元；重试整组重放，不留半提交。
            trace_id = str(v[0])
            for inner_table, inner_values in v[1]:
                self._insert(conn, inner_table, inner_values)
            return trace_id
        if table == "trace":
            conn.execute(
                "INSERT OR REPLACE INTO message_traces (trace_id, root_kind, "
                "platform, scope, source_message_key, topology_version, "
                "process_instance_id, started_utc, ended_utc, outcome, status, "
                "complete, loss, detail, process_kind, origin, trigger, route, "
                "business_ts, last_heartbeat_utc, spec_digest, "
                "conversation_key, bot_id, conversation_kind, peer_id, "
                "storage_session_id, source_message_id, identity_state) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", v)
            return v[0]
        if table == "trace_end":
            conn.execute(
                "UPDATE message_traces SET ended_utc=?, outcome=?, status=?, "
                "complete=?, loss=? WHERE trace_id=?", v)
            return v[5]
        if table == "event":
            conn.execute(
                "INSERT OR IGNORE INTO flow_events (event_id, trace_id, span_id, "
                "parent_span_id, node_id, instance_key, seq, kind, status, "
                "reason_code, ts_utc, duration_ms, summary, metrics, complete, "
                "attempt, fact_kind, error_code) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", v)
            return v[1]
        if table == "span":
            conn.execute(
                "INSERT OR REPLACE INTO flow_spans (trace_id, span_id, node_id, "
                "instance_key, parent_span_id, seq, started_utc, ended_utc, "
                "duration_ms, status, reason_code, attempt) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", v)
            return v[0]
        if table == "span_end":
            conn.execute(
                "UPDATE flow_spans SET ended_utc=?, duration_ms=?, status=?, "
                "reason_code=? WHERE trace_id=? AND span_id=?", v)
            return v[4]
        if table == "relation":
            conn.execute(
                "INSERT OR IGNORE INTO trace_relations (parent_trace_id, "
                "child_trace_id, kind, evidence, created_utc) VALUES (?,?,?,?,?)",
                v)
            return v[0]
        if table == "spec":
            conn.execute(
                "INSERT OR IGNORE INTO flow_specs (topology_version, spec_json, "
                "created_utc) VALUES (?,?,?)", v)
            return ""
        if table == "spec_blob":
            # 不可变内容归档（修复计划 §6.2）：同 digest 幂等；不同内容必然
            # 产生不同 digest（SHA-256），不存在同键不同内容覆盖。
            conn.execute(
                "INSERT OR IGNORE INTO flow_spec_blobs (spec_digest, "
                "topology_version, manifest_schema, canonicalization, "
                "spec_json, archived_at_utc) VALUES (?,?,?,?,?,?)", v)
            return ""
        if table == "trace_identity":
            # 幂等身份补充（修复计划 §6.1）：只允许空→可信；冲突由调用方
            # 标 conflict 后在这里保持原值不变。
            (trace_id, conv_key, bot_id, kind, peer_id, storage_id,
             source_msg_id, identity_state) = v
            conn.execute(
                "UPDATE message_traces SET "
                "conversation_key = CASE WHEN conversation_key='' THEN ? "
                "  ELSE conversation_key END, "
                "bot_id = CASE WHEN bot_id='' THEN ? ELSE bot_id END, "
                "conversation_kind = CASE WHEN conversation_kind='' THEN ? "
                "  ELSE conversation_kind END, "
                "peer_id = CASE WHEN peer_id='' THEN ? ELSE peer_id END, "
                "storage_session_id = COALESCE(storage_session_id, ?), "
                "source_message_id = CASE WHEN source_message_id='' THEN ? "
                "  ELSE source_message_id END, "
                "identity_state = CASE WHEN ? != '' THEN ? ELSE identity_state END "
                "WHERE trace_id = ?",
                (conv_key, bot_id, kind, peer_id, storage_id, source_msg_id,
                 identity_state, identity_state, trace_id))
            return trace_id
        if table == "entity":
            conn.execute(
                "INSERT OR IGNORE INTO entity_events (event_id, entity_type, "
                "entity_id, scope, trace_id, span_id, from_state, to_state, "
                "version, changed_fields, content_digest, ts_utc, detail) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", v)
            return v[4]
        return ""


def _group_by_trace(batch: list[tuple]) -> list[tuple[str, list[tuple]]]:
    """按归属 run 分组（保持原顺序）；无归属行归入 "" 组（如 spec 归档）。"""
    groups: dict[str, list[tuple]] = {}
    order: list[str] = []
    for row in batch:
        tid = _row_trace_id(row)
        if tid not in groups:
            groups[tid] = []
            order.append(tid)
        groups[tid].append(row)
    return [(tid, groups[tid]) for tid in order]


def _row_trace_id(row: tuple) -> str:
    """从待写行提取归属 trace_id（队列满时 per-run 归账用）。"""
    try:
        table, values = row
        if table == "bundle":
            return str(values[0])
        if table == "trace_identity":
            return str(values[0])
        if table == "trace":
            return str(values[0])
        if table == "trace_end":
            return str(values[5])
        if table == "event":
            return str(values[1])
        if table in ("span", "entity"):
            if table == "span":
                return str(values[0])
            return str(values[4])
        if table == "span_end":
            return str(values[4])
        if table == "relation":
            return str(values[0])
    except (ValueError, IndexError):
        pass
    return ""


_writer = _Writer()


def flow_health() -> dict[str, Any]:
    """观测面自检：队列水位、known loss、writer 存活（不解释成业务失败）。"""
    return {
        "queue": _writer.queue_size(),
        "dropped": _writer.dropped(),
        "pending_loss": _writer.pending_loss(),
        "writer_alive": _writer.alive(),
        "process_incarnation": PROCESS_INCARNATION,
        "schema_version": FLOW_SCHEMA_VERSION,
    }


def flush(timeout: float = 5.0) -> None:
    """等全部已提交事件落库（测试断言与优雅关闭用）。"""
    _writer.flush(timeout)


def submit_raw(row: tuple) -> None:
    """直接向 writer 提交一行（对象履历 entity_history 复用同一通道）。"""
    _writer.submit(row)


# ============================================================
# FlowContext 与 span
# ============================================================

def _scrub(value: Any) -> Any:
    from core.observability import turn_trace

    return turn_trace.scrub(value)


def _scrub_deep(value: Any) -> Any:
    """键清洗 + 字符串值脱敏（O07：metrics 里的文本也要过第二道防线）。"""
    cleaned = _scrub(value)
    if isinstance(cleaned, dict):
        return {k: _scrub_deep(v) for k, v in cleaned.items()}
    if isinstance(cleaned, list):
        return [_scrub_deep(v) for v in cleaned]
    if isinstance(cleaned, str):
        return sanitize_text(cleaned)
    return cleaned


@dataclass
class FlowContext:
    """一次入口处理的身份与运行态（进程内；跨进程用显式 relation）。"""

    trace_id: str
    root_kind: str
    entry_node: str = ""
    platform: str = ""
    scope: str = ""
    source_message_key: str = ""
    topology_version: str = ""
    process_instance_id: str = field(default_factory=lambda: PROCESS_INCARNATION)
    process_kind: str = ""
    origin: str = ""
    trigger: str = ""
    route: str = ""
    business_ts: str = ""
    spec_digest: str = ""
    # 规范会话身份（修复计划 §6.1）：preprocessor 阶段即可从事件字段填写，
    # matcher 拿到注册表 ref 后经 update_trace_identity 幂等补充 storage ID
    conversation_key: str = ""
    bot_id: str = ""
    conversation_kind: str = ""
    peer_id: str = ""
    storage_session_id: int | None = None
    source_message_id: str = ""
    identity_state: str = ""
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
    """按 source_message_key 查活跃 context（跨层关联：task_id → trace）。

    同键多次命中（同事件重入的旧 ctx 未及时清理）时取最新注册的活跃项。
    """
    if not key:
        return None
    found: FlowContext | None = None
    for ctx in _active.values():
        if ctx.source_message_key == key and not ctx.ended:
            found = ctx
    return found


def active_traces() -> list[str]:
    return list(_active)


# ---- spec 归档（O08 + 修复计划 §6.2）：不可变内容 digest 精确归档 ----

# 缓存 topology_version → (spec_digest, canonical_json, manifest_schema)；
# None 表示该版本无随包 spec（binding missing，不归档 {}）。
_spec_cache: dict[str, tuple[str, str, int] | None] = {}


def spec_digest_of(payload: dict) -> str:
    """canonical payload 的完整 64 位 SHA-256（stella-flow-content-v1）。

    与生成器 content_hash 同一算法：排除 source_revision（构建独立
    provenance，不参与内容身份）、排序键、紧凑 UTF-8 JSON。
    """
    body = {k: v for k, v in payload.items() if k != "source_revision"}
    return hashlib.sha256(json_dumps(body).encode("utf-8")).hexdigest()


def _bundled_spec(version: str) -> tuple[str, str, int] | None:
    """随包 manifest → (digest, canonical payload, manifest_schema)。

    canonical payload 保存进归档；source_revision 只作独立 provenance。
    失配/丢失返回 None（binding missing，**不归档 {}**，修复计划 §6.2）。
    """
    if version in _spec_cache:
        return _spec_cache[version]
    bundled: tuple[str, str, int] | None = None
    try:
        flows_dir = Path(__file__).resolve().parent / "flows"
        if flows_dir.exists():
            for path in sorted(flows_dir.glob("message-flow.*.json")):
                data = json_loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("topology_version") == version:
                    payload = {k: v for k, v in data.items()
                               if k != "source_revision"}
                    digest = spec_digest_of(payload)
                    schema = int(payload.get("schema_version") or 0)
                    bundled = (digest, json_dumps(payload), schema)
                    break
    except Exception:
        bundled = None
    _spec_cache[version] = bundled
    return bundled


def _bundled_spec_json(version: str) -> str | None:
    """旧接口：随包 manifest 的 canonical JSON（无版本时 None）。"""
    found = _bundled_spec(version)
    return found[1] if found else None


def json_loads(text: str) -> Any:
    import json

    return json.loads(text)


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def begin_trace(
    *,
    root_kind: str,
    platform: str = "",
    scope: str = "",
    source_message_key: str = "",
    trace_id: str | None = None,
    detail: dict[str, Any] | None = None,
    process_kind: str = "",
    origin: str = "",
    trigger: str = "",
    business_ts: str = "",
    conversation_key: str = "",
    bot_id: str = "",
    conversation_kind: str = "",
    peer_id: str = "",
    storage_session_id: int | None = None,
    source_message_id: str = "",
) -> FlowContext:
    """入口建 root：写入 message_traces 行 + root span start 事件。

    ``trace_id`` 传入既有的接入追踪 ID（ctx.trace_id）即共用同一身份；
    缺省时新建。重复 root（同 trace 二次 begin）是编程错误但按幂等处理：
    返回已存在的 context，不重复写行。

    新增身份字段（计划 §6.1 root/run 合同）：``process_kind`` 流程族
    （缺省沿用 root_kind 的 legacy 映射）、``origin`` 运行来源
    （message/timer/worker/spawn/startup）、``trigger`` 业务触发键、
    ``business_ts`` 业务事件时间（与观测时钟独立）。

    规范会话身份（修复计划 §6.1）：``conversation_key/bot_id/
    conversation_kind/peer_id/source_message_id`` 由调用方从事件字段直接
    填写（preprocessor 无业务库即可填）；``storage_session_id`` 由注册表
    分配后经 :func:`update_trace_identity` 幂等补充。identity_state 由此
    推导：有 conversation_key → exact；仅 legacy scope → legacy_partial；
    全空 → missing。

    spec 归档（修复计划 §6.2）：owned bundle 在同一提交单元内落
    spec prerequisite（flow_spec_blobs 按 digest）+ legacy flow_specs +
    trace 行 + root start；批失败按 trace 分组整包重放，绝不产生
    「root 已建、spec 丢失」的半提交。
    """
    from core.observability.flow_catalog import TOPOLOGY_VERSION

    if trace_id:
        found = _active.get(trace_id)
        if found is not None and not found.ended:
            return found
    from core.observability.flow_catalog import ENTRY_ROOTS

    if conversation_key:
        identity_state = IDENTITY_EXACT
    elif scope:
        identity_state = IDENTITY_LEGACY_PARTIAL
    else:
        identity_state = IDENTITY_MISSING
    ctx = FlowContext(
        trace_id=trace_id or _new_id(),
        root_kind=root_kind,
        # root span 的语义节点 = 目录里的入口节点（计划 §6.3）：root_kind 是
        # 存储/筛选用的事实键，画布上的身份是入口节点 ID（可被打标签）。
        entry_node=ENTRY_ROOTS.get(root_kind, root_kind),
        platform=platform,
        scope=scope,
        source_message_key=source_message_key,
        topology_version=TOPOLOGY_VERSION,
        process_kind=process_kind or root_kind,
        origin=origin,
        trigger=trigger,
        business_ts=business_ts,
        conversation_key=conversation_key,
        bot_id=bot_id,
        conversation_kind=conversation_kind,
        peer_id=peer_id,
        storage_session_id=storage_session_id,
        source_message_id=source_message_id,
        identity_state=identity_state,
        drops_at_start=_writer.dropped(),
    )
    _register(ctx)
    ts = ctx.started_utc
    bundled = _bundled_spec(TOPOLOGY_VERSION)
    if bundled is not None:
        spec_digest, spec_json, manifest_schema = bundled
        ctx.spec_digest = spec_digest
    else:
        spec_digest, spec_json, manifest_schema = "", "", 0
    # owned bundle：spec prerequisite 先于 root 行，同一事务单元
    bundle: list[tuple[str, tuple]] = []
    if bundled is not None:
        bundle.append(("spec_blob", (
            spec_digest, TOPOLOGY_VERSION, manifest_schema,
            SPEC_CANONICALIZATION, spec_json, ts)))
        bundle.append(("spec", (TOPOLOGY_VERSION, spec_json, ts)))
    bundle.append(("trace", (
        ctx.trace_id, root_kind, platform, scope, source_message_key,
        ctx.topology_version, ctx.process_instance_id, ctx.started_utc,
        "", "", "running", 0, 0,
        _dump(_scrub(detail or {})),
        ctx.process_kind, ctx.origin, ctx.trigger, ctx.route,
        ctx.business_ts, ctx.started_utc, spec_digest,
        conversation_key, bot_id, conversation_kind, peer_id,
        storage_session_id, source_message_id, identity_state,
    )))
    root_start = _root_start_rows(ctx)
    bundle.extend(root_start)
    _writer.submit(("bundle", (ctx.trace_id, bundle)))
    return ctx


def update_trace_identity(
    ctx: FlowContext | None,
    *,
    conversation_key: str | None = None,
    bot_id: str | None = None,
    conversation_kind: str | None = None,
    peer_id: str | None = None,
    storage_session_id: int | None = None,
    source_message_id: str | None = None,
) -> bool:
    """幂等补充可信身份（修复计划 §6.1）：只允许空→可信，冲突拒绝。

    matcher 拿到已注册 ConversationRef 后调用；不重建 root，写同 trace 的
    metadata update。任何字段与已持有的可信值冲突 → 整体拒绝并标
    ``identity_state=conflict``（保持原值），返回 False；全部兼容返回
    True。``None`` 字段跳过。DB lookup/query 只读场景不得调用本接口。
    """
    if ctx is None or ctx.ended:
        return False
    provided = {
        "conversation_key": conversation_key,
        "bot_id": bot_id,
        "conversation_kind": conversation_kind,
        "peer_id": peer_id,
        "source_message_id": source_message_id,
    }
    conflict = False
    updates: dict[str, str] = {}
    for name, value in provided.items():
        if value is None or value == "":
            continue
        current = getattr(ctx, name)
        if current == "":
            updates[name] = str(value)
        elif current != str(value):
            conflict = True
    if (storage_session_id is not None
            and ctx.storage_session_id is not None
            and int(ctx.storage_session_id) != int(storage_session_id)):
        conflict = True
    if conflict:
        ctx.identity_state = IDENTITY_CONFLICT
        _writer.submit(("trace_identity", (
            ctx.trace_id, "", "", "", "", None, "", IDENTITY_CONFLICT)))
        return False
    for name, value in updates.items():
        setattr(ctx, name, value)
    if storage_session_id is not None and ctx.storage_session_id is None:
        ctx.storage_session_id = int(storage_session_id)
    if ctx.identity_state != IDENTITY_EXACT:
        ctx.identity_state = IDENTITY_EXACT
    _writer.submit(("trace_identity", (
        ctx.trace_id, ctx.conversation_key, ctx.bot_id, ctx.conversation_kind,
        ctx.peer_id,
        None if ctx.storage_session_id is None else int(ctx.storage_session_id),
        ctx.source_message_id, IDENTITY_EXACT)))
    return True


def _root_start_rows(ctx: FlowContext) -> list[tuple[str, tuple]]:
    """root span start 的事件行 + span 行（owned bundle 的尾部成员）。"""
    ts = ctx.started_utc
    event_id = _new_id()
    event_row = ("event", (
        event_id, ctx.trace_id, "root", "", ctx.entry_node,
        "", ctx.next_seq(), KIND_START, ST_RUNNING,
        "", ts, None, "", _dump({}), 1, 0, "", ""))
    span_row = ("span", (
        ctx.trace_id, "root", ctx.entry_node, "", "",
        ctx.next_seq(), ts, "", None, ST_RUNNING, "", 0))
    return [event_row, span_row]


def end_trace(
    ctx: FlowContext,
    *,
    outcome: str = "",
    status: str = "closed",
    complete: bool | None = None,
) -> None:
    """关闭 root：trace_end 事件 + message_traces producer 终态。

    ``complete`` 缺省按「无未闭合 span」计算；持久化完整性由 writer 在
    事务确认后落 ``integrity``（O03：producer 结束 ≠ persisted complete，
    异步写失败会纠正本 run 的完整性）。调用方可以显式给 False（如发送
    部分失败时仍关闭 root——root 同步结束与后台任务状态独立，计划 §3.2）。
    """
    if ctx.ended:
        return
    now_mono = time.monotonic()
    ctx.ended = True
    ctx.outcome = outcome
    ts = utc_now().isoformat(timespec="milliseconds")
    # 未闭合 span：进程内泄漏或异常路径漏配对——按 unknown 落终态事件，
    # 完整性归 partial（活跃判定由 incarnation/heartbeat 处理，O01）
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
            (now_mono - state.mono) * 1000.0, ST_UNKNOWN, "span_not_closed",
            state.attempt)))
    if complete is None:
        complete = not leaked
    root_duration = (now_mono - ctx.started_mono) * 1000.0
    _emit_event(ctx, kind=KIND_TRACE_END, node_id=ctx.entry_node or ctx.root_kind,
                span_id="root",
                parent_span_id="", instance_key="", status=status,
                ts_utc=ts,
                duration_ms=root_duration,
                summary=outcome)
    _writer.submit(("span_end", (
        ts, root_duration, status, "", ctx.trace_id, "root")))
    # loss 列只是 producer 视角的粗信号（保留兼容）；权威账本在
    # flow_run_loss + lost_events/integrity（writer 提交确认后落，O03）
    _writer.submit(("trace_end", (
        ts, outcome, status, 1 if complete else 0, 0, ctx.trace_id)))


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
    attempt: int = 0,
    fact_kind: str = "",
    error_code: str = "",
) -> str:
    """写一条事件（INSERT OR IGNORE：event_id 幂等，SSE 去重键）。

    summary/metrics 在唯一出口统一脱敏（O07）：文本秘密形状打码、错误以
    ``error_code`` 稳定记录，原文不落库。
    """
    event_id = _new_id()
    _writer.submit(("event", (
        event_id, ctx.trace_id, span_id, parent_span_id, node_id,
        instance_key, ctx.next_seq(), kind, status,
        sanitize_text(reason_code), ts_utc or utc_now().isoformat(timespec="milliseconds"),
        None if duration_ms is None else round(duration_ms, 1),
        sanitize_text(summary), _dump(_scrub_deep(metrics or {})), 1,
        attempt, fact_kind, error_code)))
    return event_id


def _emit_span_start(
    ctx: FlowContext,
    *,
    span_id: str,
    node_id: str,
    parent_span_id: str,
    instance_key: str,
    summary: str,
    attempt: int = 0,
) -> str:
    ts = utc_now().isoformat(timespec="milliseconds")
    _emit_event(ctx, kind=KIND_START, node_id=node_id, span_id=span_id,
                parent_span_id=parent_span_id, instance_key=instance_key,
                status=ST_RUNNING, ts_utc=ts, summary=summary, attempt=attempt)
    _writer.submit(("span", (
        ctx.trace_id, span_id, node_id, instance_key, parent_span_id,
        ctx.next_seq(), ts, "", None, ST_RUNNING, "", attempt)))
    return span_id


@dataclass
class _SpanState:
    node_id: str
    parent: str
    instance_key: str
    mono: float
    ts: str
    seq: int
    attempt: int = 0


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
        error_code: str = "",
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
            summary=summary, metrics=metrics,
            attempt=state.attempt, error_code=error_code)
        _writer.submit(("span", (
            self._ctx.trace_id, self.span_id, state.node_id,
            state.instance_key, state.parent, state.seq, state.ts, ts,
            (time.monotonic() - state.mono) * 1000.0, status, reason_code,
            state.attempt)))

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
                        summary=str(exc)[:300] if exc else "",
                        error_code=error_code_of(exc_type))
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
    attempt: int = 0,
) -> FlowSpan:
    """开一个 span。``ctx`` 为 None（观测未接入/单测）时返回空操作 span。

    ``parent`` 缺省挂在 root 下；传 FlowSpan 或 span_id 显式建父子。
    ``attempt``：同一节点的第 N 次尝试（重试/重入，计划 §6.1 instance 合同）。
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
            mono=time.monotonic(), ts=ts, seq=seq, attempt=attempt)
    _emit_span_start(ctx, span_id=span_id, node_id=node_id,
                     parent_span_id=parent_id, instance_key=instance_key,
                     summary=summary, attempt=attempt)
    return FlowSpan(ctx, span_id, node_id)


def node(
    ctx: FlowContext | None,
    node_id: str,
    *,
    parent: "FlowSpan | str | None" = None,
    instance_key: str = "",
    summary: str = "",
    attempt: int = 0,
) -> FlowSpan:
    """``with message_flow.node(ctx, "chat.group_lock"):``——FlowSpan 本身
    就是上下文管理器，这里只是语义化别名。"""
    return span(ctx, node_id, parent=parent, instance_key=instance_key,
                summary=summary, attempt=attempt)


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
    attempt: int = 0,
    fact_kind: str = "",
    error_code: str = "",
) -> None:
    """无持续时长的决策点（早退、闸门、路由选择）：单条 decision 事件。"""
    if ctx is None or ctx.ended:
        return
    _emit_event(ctx, kind=KIND_DECISION, node_id=node_id,
                span_id=span_id, parent_span_id=parent_span_id,
                instance_key=instance_key, status=status,
                reason_code=reason_code, summary=summary, metrics=metrics,
                attempt=attempt, fact_kind=fact_kind, error_code=error_code)


def checkpoint(
    ctx: FlowContext | None,
    node_id: str,
    *,
    summary: str = "",
    metrics: dict[str, Any] | None = None,
    span_id: str = "",
    fact_kind: str = "",
) -> None:
    """过程事实（无终态语义）：如「已 spawn 整合，不等待结果」。"""
    if ctx is None or ctx.ended:
        return
    _emit_event(ctx, kind=KIND_CHECKPOINT, node_id=node_id, span_id=span_id,
                status=ST_SUCCEEDED, summary=summary, metrics=metrics,
                fact_kind=fact_kind)


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
    out = {"traces": 0, "events": 0, "spans": 0, "entity_events": 0}
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
                out["entity_events"] = conn.execute(
                    f"DELETE FROM entity_events WHERE trace_id IN ({marks})",
                    old).rowcount or 0
                conn.execute(
                    f"DELETE FROM trace_relations WHERE parent_trace_id IN ({marks}) "
                    f"OR child_trace_id IN ({marks})", old + old)
                conn.execute(
                    f"DELETE FROM flow_run_loss WHERE trace_id IN ({marks})",
                    old)
                out["traces"] = conn.execute(
                    "DELETE FROM message_traces WHERE trace_id IN "
                    f"({marks})", old).rowcount or 0
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        log_sqlite_error("message_flow.prune", e)
    return out
