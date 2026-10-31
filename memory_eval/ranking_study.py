# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""检索排序校准研究（MBENCH-002 Next-3）：多权重假设下的证据召回分解。

思路：生产 hybrid 检索的 ``trace.ranked_all`` 已带每候选的**加权**分数部件
（``parts = {ctx, usg, sem, rec, conf, imp}``，见 ``memory/policy.py:_rank_score``）。
用生产权重反推未加权特征向量后，即可在不改生产代码的前提下按任意权重假设
重排同一候选池，回答「QA 型检索失败卡在哪个维度」：

- 每个问题只做一次真实检索（池与特征与生产完全一致）；
- 对比指标：证据行（gold-*）的 ``rank@K``（K=3/5/10，忽略阈值）与
  ``pack@limit``（生产阈值+limit 后是否入包）、最佳证据行平均排名。

用法（仓库根目录）：
    python -m memory_eval.ranking_study --workdir E:/stella/runs/memory-eval/locomo-smoke-oracle \
        --data-dir memory/benchmark/_public/locomo/adapted \
        --embedding-model text-embedding-qwen3-embedding-0.6b --out report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from memory_eval.scenarios import load_scenarios

# 生产权重（config/settings.py MEMORY_SCORE_W_*，改动须同步）
PRODUCTION_WEIGHTS = {
    "ctx": 0.25, "usg": 0.20, "sem": 0.35, "rec": 0.10, "conf": 0.05, "imp": 0.05,
}

WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "production": dict(PRODUCTION_WEIGHTS),
    "qa_sem_heavy": {"ctx": 0.10, "usg": 0.05, "sem": 0.70, "rec": 0.05, "conf": 0.05, "imp": 0.05},
    "no_recency": {"ctx": 0.25, "usg": 0.20, "sem": 0.45, "rec": 0.0, "conf": 0.05, "imp": 0.05},
    "no_ctx": {"ctx": 0.0, "usg": 0.20, "sem": 0.60, "rec": 0.10, "conf": 0.05, "imp": 0.05},
    "sem_only": {"ctx": 0.0, "usg": 0.0, "sem": 1.0, "rec": 0.0, "conf": 0.0, "imp": 0.0},
}

TOPK = (3, 5, 10)


def unweighted_features(parts: dict[str, float]) -> dict[str, float] | None:
    """从加权部件反推未加权特征；缺部件或生产权重为 0 时返回 None（该行跳过）。"""
    feats: dict[str, float] = {}
    for dim, w in PRODUCTION_WEIGHTS.items():
        if dim not in parts:
            return None
        if w <= 0.0:
            feats[dim] = 0.0
            continue
        feats[dim] = float(parts[dim]) / w
    return feats


def rerank_ids(rows: list[dict[str, Any]], preset: dict[str, float]) -> list[tuple[str, float]]:
    """按假设权重重排 ranked_all 行；返回 [(id, 新分)] 分数降序。

    缺部件的行（如 embedding 回退后 sem 被丢弃）跳过重排——调用方应核对
    skipped 计数，避免把「语义通道失效」误读成「权重无效」。
    """
    scored: list[tuple[str, float]] = []
    for row in rows:
        feats = unweighted_features(row.get("parts") or {})
        if feats is None:
            continue
        score = sum(preset[dim] * feats[dim] for dim in preset)
        scored.append((str(row.get("id")), score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def best_gold_rank(order: list[str], gold_ids: set[str]) -> int | None:
    for idx, mid in enumerate(order, start=1):
        if mid in gold_ids:
            return idx
    return None


def study_one_query(rows: list[dict[str, Any]], gold_ids: set[str]) -> dict[str, Any] | None:
    """单个问题的多预设指标；无证据行（adversarial）返回 None。"""
    if not gold_ids:
        return None
    in_pack = {str(r.get("id")) for r in rows if r.get("cut") == ""}
    ranked_rows = sum(
        1 for r in rows if unweighted_features(r.get("parts") or {}) is not None
    )
    out: dict[str, Any] = {
        "gold_count": len(gold_ids),
        "pool_size": len(rows),
        "rows_ranked": ranked_rows,
    }
    for name, preset in WEIGHT_PRESETS.items():
        scored = rerank_ids(rows, preset)
        order = [mid for mid, _ in scored]
        best = best_gold_rank(order, gold_ids)
        out[name] = {
            "best_gold_rank": best,
            "ev_in_topk": {f"top{k}": bool(best is not None and best <= k) for k in TOPK},
            "ev_in_pack_production_thresh": bool(gold_ids & in_pack),
        }
    return out


async def run_study(
    workdir: Path,
    data_dir: Path,
    *,
    embedding_model: str | None,
    scenarios_limit: int = 0,
) -> dict[str, Any]:
    """对 workdir 下每个场景库执行研究；返回可 JSON 化的报告。"""
    import memory.retrieval_v2 as retrieval_v2
    from config.spaces import resolve_space
    from memory.embeddings import EmbeddingService

    scenarios = load_scenarios(data_dir, limit=scenarios_limit or None)

    service = None
    if embedding_model:
        from config import MEMORY_EMBEDDING_BASE_URL, MEMORY_EMBEDDING_TIMEOUT

        service = EmbeddingService(
            MEMORY_EMBEDDING_BASE_URL, embedding_model, MEMORY_EMBEDDING_TIMEOUT
        )

    agg: dict[str, dict[str, Any]] = {
        name: {"queries": 0, "ev_in_topk": {f"top{k}": 0 for k in TOPK},
               "ev_in_pack_production_thresh": 0, "best_gold_rank_sum": 0,
               "best_gold_rank_n": 0}
        for name in WEIGHT_PRESETS
    }
    per_query: list[dict[str, Any]] = []
    old = (retrieval_v2.DB_PATH, retrieval_v2.MEMORY_V2_ENABLED, retrieval_v2.RAG_ENABLED)
    try:
        for scenario in scenarios:
            sid = scenario["scenario_id"]
            db_path = workdir / sid / f"{sid}.db"
            if not db_path.exists():
                print(f"  跳过 {sid}（库不存在）")
                continue
            retrieval_v2.DB_PATH = db_path
            retrieval_v2.MEMORY_V2_ENABLED = True
            retrieval_v2.RAG_ENABLED = True
            retrieval_v2._CACHE.clear()
            space = resolve_space(int(scenario["group_id"]))
            done = 0
            for qa in scenario.get("qa") or []:
                gold = {f"gold-{d}" for d in qa.get("evidence_dia_ids") or []}
                if not gold:
                    continue
                result = await retrieval_v2.retrieve_memories_emb(
                    space, None, qa["question"], trigger="reply", service=service
                )
                rows = (result.trace or {}).get("ranked_all") or []
                outcome = study_one_query(rows, gold)
                if outcome is None:
                    continue
                outcome.update({"scenario": sid, "qid": qa["qid"],
                                "category_name": qa.get("category_name")})
                per_query.append(outcome)
                for name in WEIGHT_PRESETS:
                    slot = outcome[name]
                    agg[name]["queries"] += 1
                    for k in TOPK:
                        if slot["ev_in_topk"][f"top{k}"]:
                            agg[name]["ev_in_topk"][f"top{k}"] += 1
                    if slot["ev_in_pack_production_thresh"]:
                        agg[name]["ev_in_pack_production_thresh"] += 1
                    if slot["best_gold_rank"] is not None:
                        agg[name]["best_gold_rank_sum"] += slot["best_gold_rank"]
                        agg[name]["best_gold_rank_n"] += 1
                done += 1
                if done % 50 == 0:
                    print(f"  {sid}: {done} queries studied")
            retrieval_v2._CACHE.clear()
    finally:
        retrieval_v2.DB_PATH, retrieval_v2.MEMORY_V2_ENABLED, retrieval_v2.RAG_ENABLED = old
        retrieval_v2._CACHE.clear()

    summary = {}
    for name, slot in agg.items():
        n = max(1, slot["queries"])
        summary[name] = {
            "queries": slot["queries"],
            "ev_in_topk": {k: f"{v}/{slot['queries']} ({round(v / n * 100, 1)}%)"
                           for k, v in slot["ev_in_topk"].items()},
            "ev_in_pack_production_thresh": slot["ev_in_pack_production_thresh"],
            "mean_best_gold_rank": (
                round(slot["best_gold_rank_sum"] / slot["best_gold_rank_n"], 2)
                if slot["best_gold_rank_n"] else None
            ),
        }
    return {"queries": len(per_query), "summary": summary, "per_query": per_query}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检索排序校准研究（多权重假设证据召回）")
    parser.add_argument("--workdir", type=Path, required=True,
                        help="评测运行目录（含 <scenario>/<scenario>.db 与 gold 注入）")
    parser.add_argument("--data-dir", type=Path,
                        default=Path("memory/benchmark/_public/locomo/adapted"))
    parser.add_argument("--conversations", type=int, default=0, help="只研究前 N 段（0=全部）")
    parser.add_argument("--embedding-model", default=None, help="hybrid 语义分模型（缺省 rule 语义）")
    parser.add_argument("--out", type=Path, default=None, help="JSON 报告输出路径")
    args = parser.parse_args(argv)

    # 仓库约定：config 导入前把 STELLA_HOME 指向临时目录（研究只读场景库）
    import os
    import tempfile

    os.environ.setdefault("STELLA_HOME", tempfile.mkdtemp(prefix="stella-ranking-study-"))

    report = asyncio.run(run_study(
        args.workdir, args.data_dir,
        embedding_model=args.embedding_model,
        scenarios_limit=args.conversations,
    ))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"✅ 报告：{args.out}")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
