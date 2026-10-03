#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M6 性能与容量基准（计划 §6.7.4/§13.14 硬件项）。

三项，全部用临时目录、零生产写入：

1. **100k 消息数据集导出**：合成生产形 DB → ``export_dataset`` 只读导出，
   测墙钟与产物行数（验收规模：数据集 100k 消息）。
2. **长跑 backlog 排空**：writer 持续负载（突发 + 稳态）后停止生产者，
   轮询直到队列排空，核对 0 悬失、全部 run 落终态完整性。
3. **prune 保留清理**：过期 run 清理计数与 spec 保留。

输出 ``--output`` JSON 报告（供汇总报告引用）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def bench_dataset_100k(work: Path) -> dict:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    from core.evaluation.dataset import export_dataset

    db = work / "big.db"
    conn = sqlite3.connect(db)
    with conn:
        conn.execute(
            """CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT,
            content TEXT, source_kind TEXT DEFAULT 'PASSIVE', msg_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        rows = []
        base = 1780000000.0
        for i in range(100_000):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(base + i * 7))
            rows.append((str(1000 + i % 5), str(2000 + i % 40),
                         f"消息内容样本 {i % 500}", "PASSIVE", i + 1, ts))
            if len(rows) >= 10_000:
                conn.executemany(
                    "INSERT INTO group_messages (group_id, user_id, content, "
                    "source_kind, msg_id, timestamp) VALUES (?,?,?,?,?,?)", rows)
                rows = []
        if rows:
            conn.executemany(
                "INSERT INTO group_messages (group_id, user_id, content, "
                "source_kind, msg_id, timestamp) VALUES (?,?,?,?,?,?)", rows)
    conn.close()

    t0 = time.monotonic()
    manifest = export_dataset(db, work / "ds100k")
    seconds = time.monotonic() - t0
    exported = manifest["exported"]
    jsonl_mb = (work / "ds100k" / "messages.jsonl").stat().st_size / 1e6
    return {
        "bench": "dataset_export_100k",
        "exported": exported,
        "seconds": round(seconds, 2),
        "rows_per_second": int(exported / max(seconds, 1e-9)),
        "jsonl_mb": round(jsonl_mb, 1),
    }


def bench_long_run_drain(work: Path) -> dict:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    from core.observability import message_flow, turn_trace

    turn_trace.configure(work / "turn_trace.db")
    try:
        # 场景 A（持续负载）：200 并发 run × 50 行，5K 行/s——生产行数量级；
        # 场景 B（突发过载）：0.2s 内再压 26K 行——有界队列按设计丢包
        roots = []
        for r in range(200):
            roots.append(message_flow.begin_trace(
                root_kind="webchat", trace_id=f"lr-{r}"))
        t0 = time.monotonic()
        for round_no in range(25):
            for r, ctx in enumerate(roots):
                with message_flow.span(ctx, "lr.node",
                                       instance_key=f"seg:{round_no}"):
                    pass
                message_flow.decision(ctx, "lr.gate", status="allowed")
            time.sleep(0.08)  # ≈5K 行/s 持续负载
        sustained_seconds = time.monotonic() - t0
        sustained_dropped = message_flow._writer.dropped()
        for ctx in roots:
            message_flow.end_trace(ctx, outcome="done")
        # 阶段屏障：持续组排空后才开始突发（隔离两场景的完整性账本）
        deadline0 = time.monotonic() + 60.0
        while time.monotonic() < deadline0:
            message_flow.flush(timeout=2.0)
            if message_flow._writer.queue_size() == 0:
                break
        # 突发过载：独立 run 组（不污染持续组的完整性账本）
        burst_roots = [
            message_flow.begin_trace(root_kind="webchat", trace_id=f"lb-{r}")
            for r in range(200)]
        burst_t0 = time.monotonic()
        for round_no in range(25):
            for ctx in burst_roots:
                with message_flow.span(ctx, "lr.burst",
                                       instance_key=f"seg:{round_no}"):
                    pass
                message_flow.decision(ctx, "lr.gate", status="allowed")
        burst_seconds = time.monotonic() - burst_t0
        for ctx in burst_roots:
            message_flow.end_trace(ctx, outcome="done")
        for ctx in roots:
            message_flow.end_trace(ctx, outcome="done")

        # backlog 排空：轮询直到队列清空（上限 120s）
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            message_flow.flush(timeout=2.0)
            if message_flow._writer.queue_size() == 0:
                break
        drain_seconds = time.monotonic() - t0 - sustained_seconds
        health = message_flow.flow_health()

        conn = sqlite3.connect(work / "turn_trace.db")
        finalized = conn.execute(
            "SELECT COUNT(*) FROM message_traces WHERE integrity='complete'"
        ).fetchone()[0]
        partial = conn.execute(
            "SELECT COUNT(*) FROM message_traces WHERE integrity='partial'"
        ).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM flow_events").fetchone()[0]
        conn.close()
        return {
            "bench": "long_run_backlog_drain",
            "runs": 200,
            "sustained": {
                "profile": "200 runs x 50 rows @ ~5K rows/s（生产行数量级）",
                "seconds": round(sustained_seconds, 2),
                "dropped": sustained_dropped,
            },
            "burst_overload": {
                "profile": "26K rows in a 0.2s burst（远超生产行数量级）",
                "seconds": round(burst_seconds, 2),
                "dropped_total": health["dropped"],
                "note": "有界队列按设计丢弃并按 run 归账；热路径不受影响",
            },
            "drain_seconds": round(drain_seconds, 2),
            "queue_after": health["queue"],
            "integrity_complete": finalized,
            "integrity_partial": partial,
            "events_persisted": events,
        }
    finally:
        message_flow.flush()
        turn_trace.configure(None)


def bench_prune(work: Path) -> dict:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    from core.observability import message_flow, turn_trace

    turn_trace.configure(work / "prune.db")
    try:
        old = message_flow.begin_trace(root_kind="webchat", trace_id="old-1")
        message_flow.end_trace(old)
        fresh = message_flow.begin_trace(root_kind="webchat", trace_id="new-1")
        message_flow.end_trace(fresh)
        message_flow.flush()
        # 把 old-1 的 started_utc 拨到 40 天前
        conn = sqlite3.connect(work / "prune.db")
        conn.execute(
            "UPDATE message_traces SET started_utc='2026-08-20T00:00:00.000' "
            "WHERE trace_id='old-1'")
        conn.commit()
        conn.close()
        counts = message_flow.prune()
        kept = _trace_count(work / "prune.db")
        return {
            "bench": "prune_retention",
            "pruned": counts,
            "traces_kept": kept,
        }
    finally:
        message_flow.flush()
        turn_trace.configure(None)


def _trace_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM message_traces").fetchone()[0]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--skip-100k", action="store_true")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="stella-perf-") as tmp:
        work = Path(tmp)
        report = {"date": "2026-10-03"}
        if not args.skip_100k:
            report["dataset_100k"] = bench_dataset_100k(work)
        report["long_run_drain"] = bench_long_run_drain(work)
        report["prune"] = bench_prune(work)

    payload = json.dumps(report, ensure_ascii=False, indent=1)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"report written: {args.output}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
