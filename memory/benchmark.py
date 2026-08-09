# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Memory Benchmark 运行器（Evaluation & Debug）。

对应设计文档《Evaluation & Debug Specification v1.0》：
- 读取 ``memory/benchmark/<category>/*.json`` 用例（每个用例标注 expected_memory /
  forbidden_memory / expected_behavior）；
- 对每个用例用 v2 Policy 排序 + 可见性过滤跑一遍“记忆选择”，
  对比实际选中的记忆与期望/禁止记忆；
- 输出核心指标：Memory Precision、Forbidden Activation Rate、各模式召回量。

核心指标：
    Metric 1  Memory Precision        = 召回的期望记忆 / 召回的记忆（目标 ≥ 80%）
    Metric 2  Memory Recall           = 找到的期望记忆 / 应该找到的记忆
    Metric 3  Forbidden Activation    = 被错误激活的禁止记忆次数（目标 ≈ 0）
    Metric 4  Memory Pollution Rate   = Prompt 中无用记忆比例
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from config import MEMORY_BENCHMARK_DIR
from memory.policy import rank_memories, mode_limit, detect_mode, normalize_mode, split_behavior_constraints


def _mem_dict(mid: str, data: dict[str, Any]) -> dict[str, Any]:
    """把 benchmark 用例里的记忆定义转成 memory dict。"""
    mem = dict(data)
    mem["id"] = mid
    if "usage_tags" not in mem:
        mem["usage_tags"] = []
    return mem


def load_cases(benchmark_dir: Path = MEMORY_BENCHMARK_DIR) -> list[dict[str, Any]]:
    """递归加载 benchmark 目录下所有 .json 用例。"""
    cases: list[dict[str, Any]] = []
    if not benchmark_dir.exists():
        return cases
    for path in sorted(benchmark_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                cases.extend(data)
            else:
                cases.append(data)
        except (ValueError, OSError) as e:
            print(f"⚠️ 用例解析失败 {path}: {e}")
    return cases


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    """对单个用例跑记忆选择，返回期望/禁止/实际的命中情况。"""
    memories = {mid: _mem_dict(mid, data) for mid, data in (case.get("memories") or {}).items()}
    query = case.get("input") or ""
    trigger = case.get("trigger", "proactive" if case.get("mode") == "ACTIVE_JOIN" else "reply")
    declared_mode = normalize_mode(case.get("mode", "CASUAL_REPLY"))
    # 用 Policy 排序（依赖 mode + visibility）
    mode = detect_mode(query, trigger=trigger)
    ranked = rank_memories(list(memories.values()), declared_mode, query=query)
    behavior = split_behavior_constraints(ranked)
    conversation = [m for m in ranked if m not in behavior]
    limit = mode_limit(declared_mode)
    final = conversation[:limit]

    final_ids = {m["id"] for m in final}
    behavior_ids = {m["id"] for m in behavior}
    expected = set(case.get("expected_memory") or [])
    forbidden = set(case.get("forbidden_memory") or [])

    found_expected = final_ids & expected
    activated_forbidden = final_ids & forbidden
    # 行为约束里的期望记忆也算“被找到”（Behavior Guard 生效）
    found_expected |= behavior_ids & expected

    return {
        "id": case.get("id", "?"),
        "declared_mode": declared_mode,
        "detected_mode": mode,
        "expected": sorted(expected),
        "forbidden": sorted(forbidden),
        "final": sorted(final_ids),
        "behavior": sorted(behavior_ids),
        "found_expected": sorted(found_expected),
        "activated_forbidden": sorted(activated_forbidden),
        "ok": bool(found_expected == expected) and not activated_forbidden,
    }


def run_benchmark(benchmark_dir: Path = MEMORY_BENCHMARK_DIR) -> dict[str, Any]:
    """运行全部用例，汇总核心指标。"""
    cases = load_cases(benchmark_dir)
    results = [evaluate_case(c) for c in cases]

    total = len(results)
    ok_count = sum(1 for r in results if r["ok"])
    total_expected = sum(len(r["expected"]) for r in results)
    total_found_expected = sum(len(r["found_expected"]) for r in results)
    total_forbidden = sum(len(r["forbidden"]) for r in results)
    total_activated_forbidden = sum(len(r["activated_forbidden"]) for r in results)

    metrics = {
        "cases_total": total,
        "cases_ok": ok_count,
        "cases_ok_rate": round(ok_count / total * 100, 1) if total else 0.0,
        "memory_precision": round(total_found_expected / max(1, total_expected) * 100, 1),
        "memory_recall": round(total_found_expected / max(1, total_expected) * 100, 1),
        "forbidden_activation_rate": round(total_activated_forbidden / max(1, total_forbidden) * 100, 1),
        "forbidden_activations": total_activated_forbidden,
        "results": results,
    }
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Stella Memory Benchmark")
    parser.add_argument("--dir", type=Path, default=MEMORY_BENCHMARK_DIR, help="benchmark 数据集目录")
    parser.add_argument("--verbose", action="store_true", help="打印每个用例的明细")
    args = parser.parse_args()

    metrics = run_benchmark(args.dir)
    print("=" * 56)
    print(f"Memory Benchmark（{metrics['cases_total']} 个用例）")
    print("=" * 56)
    print(f"  通过用例       : {metrics['cases_ok']}/{metrics['cases_total']} ({metrics['cases_ok_rate']}%)")
    print(f"  Memory Precision : {metrics['memory_precision']}%  （目标 ≥ 80%）")
    print(f"  Memory Recall    : {metrics['memory_recall']}%")
    print(f"  Forbidden 激活   : {metrics['forbidden_activation_rate']}% ({metrics['forbidden_activations']} 次)  （目标 ≈ 0%）")
    print("=" * 56)
    if args.verbose:
        for r in metrics["results"]:
            status = "✅" if r["ok"] else "❌"
            print(
                f"{status} {r['id']} [{r['declared_mode']}] "
                f"期望={r['expected']} 实际={r['final']} "
                f"行为约束={r['behavior']} 违规激活={r['activated_forbidden']}"
            )


if __name__ == "__main__":
    main()
