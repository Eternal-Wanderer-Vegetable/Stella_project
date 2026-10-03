#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""观测开销基线（计划 §6.7.4 M0）：实测日常语义 profile 的热路径成本。

合同：producer 侧（begin_trace/span/decision/checkpoint/end_trace）只做
put_nowait，p95 额外延迟应 ≤ 5ms；writer 吞吐单独报告。这不是验收门槛
的最终锁定——门槛数值以本脚本在目标硬件上的输出为准（计划 §12）。

用法::

    python scripts/benchmark_flow_overhead.py [--ops 20000]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.observability import message_flow, turn_trace


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * p / 100))
    return ordered[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ops", type=int, default=20000,
                        help="每项测量的操作次数")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        turn_trace.configure(Path(tmp) / "turn_trace.db")
        try:
            _run(args.ops)
        finally:
            message_flow.flush()
            turn_trace.configure(None)
    return 0


def _run(ops: int) -> None:
    n = ops
    # ---- 基线：空循环 ----
    t0 = time.perf_counter()
    for _ in range(n):
        pass
    baseline = (time.perf_counter() - t0) / n * 1e6

    # ---- begin/end trace（producer 侧，不含落库）----
    latencies: list[float] = []
    for i in range(min(n, 2000)):
        t0 = time.perf_counter()
        ctx = message_flow.begin_trace(root_kind="webchat", trace_id=f"bm-{i}")
        message_flow.end_trace(ctx)
        latencies.append((time.perf_counter() - t0) * 1e6)
    _report("begin+end_trace", latencies, baseline)

    # ---- span + decision + checkpoint（单 trace 内热路径）----
    ctx = message_flow.begin_trace(root_kind="webchat", trace_id="bm-hot")
    latencies = []
    for i in range(n):
        t0 = time.perf_counter()
        with message_flow.span(ctx, "bm.node", instance_key=f"i:{i % 64}"):
            pass
        message_flow.decision(ctx, "bm.gate", status="allowed")
        message_flow.checkpoint(ctx, "bm.fact", summary="x")
        latencies.append((time.perf_counter() - t0) * 1e6)
    message_flow.end_trace(ctx)
    _report("span+decision+checkpoint", latencies, baseline, per_group=3)

    # ---- writer 吞吐（落库侧，与热路径分离）----
    t0 = time.perf_counter()
    message_flow.flush(60.0)
    flush_seconds = time.perf_counter() - t0
    total_events = n * 3 + 4000
    print(f"writer flush: {total_events} rows in {flush_seconds:.2f}s "
          f"({total_events / max(flush_seconds, 1e-9):.0f} rows/s)")
    health = message_flow.flow_health()
    print(f"health: dropped={health['dropped']} queue={health['queue']} "
          f"writer_alive={health['writer_alive']}")
    print("note: 合成持续突发（~750K rows/s 提交）远超落库速率时有界队列按设计"
          "饱和丢弃——热路径延迟不受影响，损失进 per-run 账本；真实消息分布"
          "为稀疏突发，不构成稳态饱和（计划 §6.5 有界非阻塞合同）")


def _report(name: str, latencies: list[float], baseline_us: float,
            per_group: int = 1) -> None:
    per_op = [v / per_group for v in latencies]
    p50 = _percentile(per_op, 50)
    p95 = _percentile(per_op, 95)
    p99 = _percentile(per_op, 99)
    mean = statistics.fmean(per_op)
    print(f"{name}: n={len(per_op)} mean={mean:.1f}us p50={p50:.1f}us "
          f"p95={p95:.1f}us p99={p99:.1f}us "
          f"(budget 5000us: {'OK' if p95 <= 5000 else 'OVER'})")


if __name__ == "__main__":
    raise SystemExit(main())
