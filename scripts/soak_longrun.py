#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""小时级长跑验证（计划 §13.14 M6 硬件项）：持续观测负载 + 水位采样 + 排空。

设计（全部在临时目录，零生产写入）：

- 负载：约 ``--runs-per-tick`` 个 run / ``--tick-seconds`` 秒，每 run
  ~40 行事件（span+decision+finish），持续 ``--minutes`` 分钟——生产行数
  量级的稳态压力；
- 采样（每 tick）：writer 队列水位、known loss、进程 RSS（ctypes
  GetProcessMemoryInfo，无 psutil 依赖）、诊断库体积、累计 run 数；
- 周期维护：每 ``--prune-every`` tick 跑一次 ``message_flow.prune()``
  （保留策略与生产同口径：30 天；长跑里主要验证幂等与不误删）；
- 收官：停生产者 → 排空（轮询队列至 0，上限 10 分钟）→ 核对全部 run
  integrity → prune → 最终库体积。

报告增量写 ``--output``（JSON），中途被杀也保留已完成采样。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _rss_mb() -> float:
    """当前进程 RSS（MB）：Windows PSAPI，无第三方依赖。"""
    if os.name != "nt":
        return -1.0

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_uint32),
            ("PageFaultCount", ctypes.c_uint32),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    pmc = ProcessMemoryCounters()
    pmc.cb = ctypes.sizeof(pmc)
    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    k32.GetCurrentProcess.restype = ctypes.c_void_p  # 64 位伪句柄，不可截断
    handle = k32.GetCurrentProcess()
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ProcessMemoryCounters), ctypes.c_uint32]
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
        return -1.0
    return pmc.WorkingSetSize / (1024.0 * 1024.0)


def _db_size_mb(db: Path) -> float:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total / (1024.0 * 1024.0)


def _counts(db: Path) -> tuple[int, int, int]:
    conn = sqlite3.connect(db)
    try:
        traces = conn.execute("SELECT COUNT(*) FROM message_traces").fetchone()[0]
        complete = conn.execute(
            "SELECT COUNT(*) FROM message_traces WHERE integrity='complete'"
        ).fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM flow_events").fetchone()[0]
        return traces, complete, events
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=float, default=60.0)
    parser.add_argument("--runs-per-tick", type=int, default=3)
    parser.add_argument("--tick-seconds", type=float, default=10.0)
    parser.add_argument("--prune-every", type=int, default=60,
                        help="每 N 个 tick 跑一次 prune（0=从不）")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keep-home", action="store_true")
    args = parser.parse_args()

    import sys

    sys.path.insert(0, str(PROJECT_ROOT))
    from core.observability import message_flow, turn_trace

    home = Path(tempfile.mkdtemp(prefix="stella-soak-"))
    db = home / "turn_trace.db"
    turn_trace.configure(db)

    report: dict = {
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "minutes": args.minutes,
            "runs_per_tick": args.runs_per_tick,
            "tick_seconds": args.tick_seconds,
        },
        "samples": [],
    }
    deadline = time.monotonic() + args.minutes * 60.0
    tick = 0
    runs_total = 0
    prune_calls = 0
    try:
        while time.monotonic() < deadline:
            tick += 1
            t0 = time.monotonic()
            for r in range(args.runs_per_tick):
                ctx = message_flow.begin_trace(
                    root_kind="webchat", trace_id=f"soak-{tick}-{r}")
                for seg in range(20):
                    with message_flow.span(ctx, "soak.node",
                                           instance_key=f"seg:{seg}"):
                        pass
                    message_flow.decision(ctx, "soak.gate", status="allowed")
                message_flow.end_trace(ctx, outcome="done")
                runs_total += 1
            if args.prune_every and tick % args.prune_every == 0:
                message_flow.prune()
                prune_calls += 1
            traces, complete, events = _counts(db)
            health = message_flow.flow_health()
            report["samples"].append({
                "tick": tick,
                "elapsed_s": round(time.monotonic() - (deadline - args.minutes * 60.0), 1),
                "runs": runs_total,
                "queue": health["queue"],
                "dropped": health["dropped"],
                "rss_mb": round(_rss_mb(), 1),
                "db_mb": round(_db_size_mb(db), 2),
                "traces": traces,
                "integrity_complete": complete,
                "events": events,
                "tick_ms": round((time.monotonic() - t0) * 1000, 1),
                "prune_calls": prune_calls,
            })
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
            remain = args.tick_seconds - (time.monotonic() - t0)
            if remain > 0:
                time.sleep(remain)

        # ── 收官：排空 + 完整性核对 + prune ──
        t_drain = time.monotonic()
        drain_deadline = t_drain + 600.0
        while time.monotonic() < drain_deadline:
            message_flow.flush(timeout=5.0)
            if message_flow._writer.queue_size() == 0:
                break
            time.sleep(0.5)
        drain_seconds = time.monotonic() - t_drain
        message_flow.prune()
        prune_calls += 1
        traces, complete, events = _counts(db)
        health = message_flow.flow_health()
        report["final"] = {
            "runs_total": runs_total,
            "drain_seconds": round(drain_seconds, 1),
            "queue_after": health["queue"],
            "dropped_total": health["dropped"],
            "traces": traces,
            "integrity_complete": complete,
            "integrity_other": traces - complete,
            "events_persisted": events,
            "db_mb_final": round(_db_size_mb(db), 2),
            "prune_calls": prune_calls,
            "rss_mb_final": round(_rss_mb(), 1),
        }
        # 判定：零丢失 + 全部 complete + 队列排空 + RSS 无失控增长
        first_rss = report["samples"][0]["rss_mb"] if report["samples"] else 0
        last_rss = report["samples"][-1]["rss_mb"] if report["samples"] else 0
        rss_growth = last_rss - first_rss
        report["verdict"] = {
            "zero_loss": health["dropped"] == 0,
            "all_complete": traces == complete,
            "drained": health["queue"] == 0,
            "rss_growth_mb": round(rss_growth, 1),
            "rss_ok": rss_growth < 200.0,  # 1 小时稳态增长上限（经验门槛）
        }
        report["verdict_pass"] = all(
            v for k, v in report["verdict"].items() if k != "rss_growth_mb")
    finally:
        message_flow.flush()
        turn_trace.configure(None)
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(report.get("final"), ensure_ascii=False, indent=1))
    print("verdict:", report.get("verdict"))
    print("pass:", report.get("verdict_pass"))
    if not args.keep_home:
        import shutil

        shutil.rmtree(home, ignore_errors=True)
    return 0 if report.get("verdict_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
