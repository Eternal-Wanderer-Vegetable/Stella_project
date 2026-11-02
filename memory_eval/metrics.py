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


def evidence_metrics(
    retrieved_ids: list[str],
    gold_evidence_ids: set[str],
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> dict[str, Any]:
    """基于 gold 证据 ID 的精确检索指标（MBENCH-003 P0-3）。

    ``retrieved_ids`` 必须是按排序次序排列的检索结果（包内次序即生产排序）。
    - ``any@K``：前 K 内命中任一 gold 证据（Any-Evidence Recall@K）；
    - ``all@K``：前 K 覆盖全部 gold 证据（All-Evidence Recall@K / 证据完整覆盖，
      多跳与多事实问题的真实就绪度）；
    - ``mrr``：最佳证据排名的倒数（MRR）。
    n-gram 代理（:func:`coverage_flags`）保留作诊断，不作为合格判定。
    """
    if not gold_evidence_ids:
        return {}
    rank_of: dict[str, int] = {}
    for idx, mid in enumerate(retrieved_ids, start=1):
        if mid in gold_evidence_ids and mid not in rank_of:
            rank_of[mid] = idx
    best = min(rank_of.values()) if rank_of else None
    return {
        "any@K": {f"@{k}": bool(best is not None and best <= k) for k in ks},
        "all@K": {
            f"@{k}": bool(gold_evidence_ids <= set(retrieved_ids[:k])) for k in ks
        },
        "mrr": round(1.0 / best, 4) if best else 0.0,
        "evidence_completeness": round(len(rank_of) / len(gold_evidence_ids), 4),
        "best_rank": best,
    }


def _accuracy(rows: list[dict[str, Any]]) -> float | None:
    graded = [r for r in rows if r.get("verdict") in ("correct", "incorrect", "unparseable")]
    if not graded:
        return None
    hits = sum(1 for r in graded if r.get("verdict") == "correct")
    return round(hits / len(graded) * 100, 1)


def aggregate_qa(results: list[dict[str, Any]]) -> dict[str, Any]:
    """按类别聚合判分结果；含可回答题/弃答拆分与 gold-ID 精确证据指标。"""
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
    answerable = [r for r in results if r.get("gold_answer")]
    answerable_hits = sum(1 for r in answerable if r.get("verdict") == "correct")
    # 精确证据指标（gold ID 匹配；仅可回答题计入）
    ev_ks = (1, 3, 5, 10)
    ev_any = {f"@{k}": 0 for k in ev_ks}
    ev_all = {f"@{k}": 0 for k in ev_ks}
    ev_mrr_sum = 0.0
    ev_n = 0
    for r in answerable:
        gold = {f"gold-{d}" for d in r.get("evidence_dia_ids") or []}
        if not gold:
            continue
        m = evidence_metrics(list(r.get("retrieved_ids") or []), gold, ev_ks)
        for k in ev_ks:
            if m["any@K"][f"@{k}"]:
                ev_any[f"@{k}"] += 1
            if m["all@K"][f"@{k}"]:
                ev_all[f"@{k}"] += 1
        ev_mrr_sum += m["mrr"]
        ev_n += 1
    return {
        "total": len(results),
        "accuracy": _accuracy(results),
        "unparseable": sum(1 for r in results if r.get("verdict") == "unparseable"),
        "errors": sum(1 for r in results if r.get("verdict") == "error"),
        "answerable_total": len(answerable),
        "answerable_accuracy": (
            round(answerable_hits / len(answerable) * 100, 1) if answerable else None
        ),
        "abstention_accuracy": _accuracy(adversarial),
        "evidence_recall": {
            "any@K": {k: (round(v / ev_n * 100, 1) if ev_n else None) for k, v in ev_any.items()},
            "all@K": {k: (round(v / ev_n * 100, 1) if ev_n else None) for k, v in ev_all.items()},
            "mrr": round(ev_mrr_sum / ev_n, 3) if ev_n else None,
        },
        "by_category": categories,
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
