# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Memory Benchmark 运行器（Evaluation & Debug）。

对应设计文档《Evaluation & Debug Specification v1.0》：
- 读取 ``memory/benchmark/<category>/*.json`` 用例（每个用例标注 expected_memory /
  forbidden_memory / expected_behavior）；
- 对每个用例把记忆写入临时 SQLite，调 ``memory.retrieval_v2.retrieve_memories()``
  走**生产检索路径**（含 SQL Visibility 预过滤 / Usage 过滤 / Ranking / Behavior Guard），
  最后对比实际选中的记忆与期望/禁止记忆；
- 输出核心指标：Memory Precision、Memory Recall、Forbidden Activation、
  Memory Pollution Rate、Mode 检测准确率。

核心指标：
    Metric 1  Memory Precision        = 找到的期望记忆 /（会话召回 + 行为约束召回）（目标 ≥ 80%）
    Metric 2  Memory Recall           = 找到的期望记忆 / 应该找到的记忆
    Metric 3  Forbidden Activation    = 被错误激活的禁止记忆次数（目标 ≈ 0）
    Metric 4  Memory Pollution Rate   = 1 - Precision（Prompt 中无用记忆比例）
    Metric 5  Mode Detection Accuracy = 检测到的 mode 与用例标注一致的占比
    Metric 6  Behavior Guard Hit      = 期望记忆中经 Behavior Guard 命中的比例
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from config import MEMORY_BENCHMARK_DIR
from memory.policy import detect_mode, normalize_mode


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
            items = data if isinstance(data, list) else [data]
            cases.extend(items)
        except (ValueError, OSError) as e:
            print(f"⚠️ 用例解析失败 {path}: {e}")
    # id 重复是标注事故：尽早报错，避免静默把不同用例的期望/禁止混在一起
    seen: set[str] = set()
    for c in cases:
        cid = c.get("id", "?")
        if cid in seen:
            raise ValueError(f"benchmark 用例 id 重复: {cid!r}")
        seen.add(cid)
    return cases


def _scenario_ids(case: dict[str, Any]) -> tuple[int, int]:
    """从用例 scenario 里取群/用户 ID（用于写临时库并启动检索）。"""
    scenario = case.get("scenario") or {}
    try:
        group_id = int(scenario.get("group_id", 1))
    except (TypeError, ValueError):
        group_id = 1
    try:
        user_id = int(scenario.get("user_id", 0))
    except (TypeError, ValueError):
        user_id = 0
    return group_id, user_id


def _write_case_db(db_path: Path, case: dict[str, Any]) -> tuple[int, int]:
    """把用例记忆写进临时 SQLite，返回 (group_id, user_id)。

    背景：evaluate_case 必须走生产路径，即 retrieval_v2._fetch_candidates 内的
    SQL Visibility 预过滤（_allowed_visibility_clause）。否则 RESTRICTED 记忆会在
    普通模式绕过 SQL 直接进 rank_memories，测的是一条比生产更宽松的路径。
    memories 表直接复用 memory.schema 的规范 DDL，避免与生产 schema 漂移。
    """
    db_path.unlink(missing_ok=True)
    group_id, user_id = _scenario_ids(case)
    conn = sqlite3.connect(db_path)
    try:
        from memory import schema

        schema.create_memories_table(conn)
        for mid, data in (case.get("memories") or {}).items():
            mem = _mem_dict(mid, data)
            conn.execute(
                "INSERT INTO memories (id, group_id, user_id, type, content, importance, "
                "confidence, status, usage_tags, visibility, trigger_data, behavior_rule, "
                "last_accessed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)",
                (
                    mid,
                    str(group_id),
                    str(user_id),
                    mem.get("type") or "FACT",
                    mem.get("content") or "",
                    0.5 if mem.get("importance") is None else mem["importance"],
                    0.7 if mem.get("confidence") is None else mem["confidence"],
                    json.dumps(mem.get("usage_tags") or [], ensure_ascii=False),
                    mem.get("visibility") or "OPEN",
                    mem.get("trigger_data"),
                    mem.get("behavior_rule"),
                    "2026-08-09 10:00:00",
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return group_id, user_id


def evaluate_case(case: dict[str, Any], work_dir: Path | None = None, seq: int = 0) -> dict[str, Any]:
    """对单个用例跑生产检索路径，返回期望/禁止/实际的命中情况。

    生产路径：写入临时库后调 memory.retrieval_v2.retrieve_memories()，
    真实走一遍 SQL Visibility 预过滤 + Usage 过滤 + Ranking + Behavior Guard。
    mode 由检索入口自行检测，检测结果用于排序（不再用用例标注的 declared_mode）。
    seq 用于保证 temp 库文件名唯一，避免 id 缺失/重名的用例共用同一 db 路径。
    """
    import memory.retrieval_v2 as retrieval_v2

    manager: Any = None
    if work_dir is None:
        manager = tempfile.TemporaryDirectory(prefix="stella_benchmark_")
        work_dir = Path(manager.name)
    try:
        db_path = work_dir / f"case_{seq}_{case.get('id', 'case')}.db"
        group_id, user_id = _write_case_db(db_path, case)
        query = case.get("input") or ""
        trigger = case.get("trigger", "proactive" if case.get("mode") == "ACTIVE_JOIN" else "reply")
        declared_mode = normalize_mode(case.get("mode", "CASUAL_REPLY"))

        # 临时把 retrieval_v2 指向本用例的临时库，结束后恢复现场
        old_db, old_v2, old_rag = (
            retrieval_v2.DB_PATH,
            retrieval_v2.MEMORY_V2_ENABLED,
            retrieval_v2.RAG_ENABLED,
        )
        try:
            retrieval_v2.DB_PATH = db_path
            retrieval_v2.MEMORY_V2_ENABLED = True
            # 故意关掉 RAG/FTS：保证 benchmark 结果可复现（注意 FTS 分支是盲区）
            retrieval_v2.RAG_ENABLED = False
            # _CACHE 按 (db 路径, 群, 用户, trigger, mode) 全局缓存 5 分钟，
            # 用例之间必须清空，否则同名/缺失 id 的用例会吃到上一用例的缓存。
            retrieval_v2._CACHE.clear()
            result = retrieval_v2.retrieve_memories(group_id, user_id, query, trigger=trigger)
        finally:
            retrieval_v2.DB_PATH = old_db
            retrieval_v2.MEMORY_V2_ENABLED = old_v2
            retrieval_v2.RAG_ENABLED = old_rag

        detected_mode = result.mode or detect_mode(query, trigger=trigger)
        conversation = result.conversation_memories
        behavior = result.behavior_constraints

        final_ids = {m["id"] for m in conversation}
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
            "detected_mode": detected_mode,
            "expected": sorted(expected),
            "forbidden": sorted(forbidden),
            "final": sorted(final_ids),
            "behavior": sorted(behavior_ids),
            "found_expected": sorted(found_expected),
            "activated_forbidden": sorted(activated_forbidden),
            "ok": bool(found_expected == expected) and not activated_forbidden,
        }
    finally:
        if manager is not None:
            manager.cleanup()


def run_benchmark(benchmark_dir: Path = MEMORY_BENCHMARK_DIR) -> dict[str, Any]:
    """运行全部用例，汇总核心指标。"""
    cases = load_cases(benchmark_dir)
    with tempfile.TemporaryDirectory(prefix="stella_benchmark_") as tmp:
        work_dir = Path(tmp)
        results = [evaluate_case(c, work_dir, i) for i, c in enumerate(cases)]

    total = len(results)
    ok_count = sum(1 for r in results if r["ok"])
    total_expected = sum(len(r["expected"]) for r in results)
    total_found_expected = sum(len(r["found_expected"]) for r in results)
    # 分母 = 会话召回 + 行为约束召回：行为约束里的期望记忆是“正确激活”（Behavior Guard），
    # 不能只算分子不算分母，否则会把 precision 虚高甚至推到 100% 以上。
    total_retrieved = sum(len(r["final"]) + len(r["behavior"]) for r in results)
    total_behavior_hits = sum(len(set(r["behavior"]) & set(r["expected"])) for r in results)
    total_forbidden = sum(len(r["forbidden"]) for r in results)
    total_activated_forbidden = sum(len(r["activated_forbidden"]) for r in results)
    mode_correct = sum(1 for r in results if r["declared_mode"] == r["detected_mode"])

    # Precision 的分母是“实际召回条数”，Recall 的分母才是“期望条数”
    precision_pct = round(total_found_expected / max(1, total_retrieved) * 100, 1)

    return {
        "cases_total": total,
        "cases_ok": ok_count,
        "cases_ok_rate": round(ok_count / total * 100, 1) if total else 0.0,
        "memory_precision": precision_pct,
        "memory_recall": round(total_found_expected / max(1, total_expected) * 100, 1),
        # Metric 4 Memory Pollution Rate = 1 - Precision（Prompt 中无用记忆比例）
        "memory_pollution_rate": round(max(0.0, 100.0 - precision_pct), 1),
        # Metric 5 Mode Detection Accuracy：检测到的 mode 是否与用例标注一致
        "mode_accuracy": round(mode_correct / total * 100, 1) if total else 0.0,
        # Metric 6 Behavior Guard Hit：期望记忆中靠 Behavior Guard 命中的比例
        "behavior_guard_hit_rate": round(total_behavior_hits / max(1, total_expected) * 100, 1),
        "forbidden_activation_rate": round(total_activated_forbidden / max(1, total_forbidden) * 100, 1),
        "forbidden_activations": total_activated_forbidden,
        "results": results,
    }


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
    print(f"  Pollution Rate   : {metrics['memory_pollution_rate']}%")
    print(f"  Behavior Guard   : {metrics['behavior_guard_hit_rate']}%")
    print(f"  Mode 检测准确率  : {metrics['mode_accuracy']}%")
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
