# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""指标聚合：判分正确率、证据覆盖代理、捕获漏斗、成本汇总。"""

from __future__ import annotations

from typing import Any

GRAM = 4


def grams(text: str, n: int = GRAM) -> set[str]:
    t = (text or "").lower()
    return {t[i : i + n] for i in range(max(0, len(t) - n + 1))}


def has_gram_overlap(text: str, corpus_grams: set[str], n: int = GRAM) -> bool:
    """内容级覆盖代理：text 与语料存在任一 n-gram 交集。"""
    g = grams(text, n)
    return bool(g) and bool(g & corpus_grams)


def coverage_flags(
    qa: dict[str, Any],
    evidence_texts: dict[str, str],
    contents: list[str],
) -> dict[str, Any]:
    """一个 QA 对一组候选内容（memories / 检索包）的证据覆盖代理。"""
    evidence = [evidence_texts[d] for d in qa.get("evidence_dia_ids") or [] if d in evidence_texts]
    corpus = grams(" \n ".join(contents))
    return {
        "evidence_turns": len(evidence),
        "evidence_covered": sum(1 for t in evidence if has_gram_overlap(t, corpus)),
        "covered": bool(evidence) and any(has_gram_overlap(t, corpus) for t in evidence),
    }


def _accuracy(rows: list[dict[str, Any]]) -> float | None:
    graded = [r for r in rows if r.get("verdict") in ("correct", "incorrect", "unparseable")]
    if not graded:
        return None
    hits = sum(1 for r in graded if r.get("verdict") == "correct")
    return round(hits / len(graded) * 100, 1)


def aggregate_qa(results: list[dict[str, Any]]) -> dict[str, Any]:
    """按类别聚合判分结果（unparseable 计入 incorrect，另留计数）。"""
    by_category: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_category.setdefault(str(r.get("category_name") or "unknown"), []).append(r)
    categories = {
        name: {
            "total": len(rows),
            "accuracy": _accuracy(rows),
            "unparseable": sum(1 for r in rows if r.get("verdict") == "unparseable"),
        }
        for name, rows in sorted(by_category.items())
    }
    adversarial = by_category.get("adversarial") or []
    return {
        "total": len(results),
        "accuracy": _accuracy(results),
        "unparseable": sum(1 for r in results if r.get("verdict") == "unparseable"),
        "errors": sum(1 for r in results if r.get("verdict") == "error"),
        "by_category": categories,
        "adversarial_abstention_accuracy": _accuracy(adversarial),
        "write_coverage_memories": _mean([r.get("write_coverage_memories") for r in results]),
        "write_coverage_candidates": _mean([r.get("write_coverage_candidates") for r in results]),
        "retrieval_evidence_coverage": _mean([r.get("retrieval_evidence_coverage") for r in results]),
        "pack_memory_count_avg": _mean([r.get("pack_memory_count") for r in results]),
        "pack_chars_avg": _mean([r.get("pack_chars") for r in results]),
    }


def _mean(values: list[Any]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 3)


def aggregate_run(per_scenario: list[dict[str, Any]]) -> dict[str, Any]:
    """跨场景汇总：整体 accuracy（按 QA 条目合并）+ 漏斗/成本合计。"""
    all_results = [r for s in per_scenario for r in (s.get("qa_results") or [])]
    summary = aggregate_qa(all_results)
    summary["scenarios"] = len(per_scenario)
    summary["funnel_totals"] = {
        "candidates_total": sum((s.get("funnel") or {}).get("candidates_total", 0) for s in per_scenario),
        "memories_total": sum((s.get("funnel") or {}).get("memories_total", 0) for s in per_scenario),
        "memories_active": sum((s.get("funnel") or {}).get("memories_active", 0) for s in per_scenario),
    }
    return summary
