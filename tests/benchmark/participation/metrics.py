# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""benchmark 指标计算：把回放产生的决策序列按场景（scenarios.toml）汇总。

输入是 runner 产出的决策列表（dict，字段同 participation_decisions.jsonl +
velocity_count / matched_signals 等），输出场景通过矩阵 + 分布统计。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from memory.participation.tables import load_tables


@dataclass
class ScenarioResult:
    name: str
    passed: bool | None
    detail: str
    samples: int = 0
    metrics: dict[str, float] = field(default_factory=dict)


def load_scenarios(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _scenario(conf: dict[str, Any], key: str) -> dict[str, Any] | None:
    s = conf.get(key)
    if not isinstance(s, dict) or not s.get("enabled", True):
        return None
    return s


def _trigger_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    hit = sum(1 for r in rows if r.get("decision") == "ALLOW_LLM")
    return hit / len(rows)


def evaluate(
    decisions: list[dict[str, Any]],
    scenarios_path: Path,
    tables_dir: Path,
) -> list[ScenarioResult]:
    """对决策序列跑全部场景，返回结果列表（顺序 A~F）。"""
    conf = load_scenarios(scenarios_path)
    tables = load_tables(tables_dir)
    results: list[ScenarioResult] = []

    scores = [d["final_score"] for d in decisions]
    baseline = statistics.fmean(scores) if scores else 0.0

    # A：Hard Trigger 旁路。回放时 AT_MENTION 消息本来就不进评分层；
    # 这里校验决策序列里不存在 is_tome 标记（防未来误挂到 AT_MENTION 上）。
    if _scenario(conf, "scenario_a_hard_trigger_bypass"):
        bad = [d for d in decisions if d.get("is_tome")]
        results.append(ScenarioResult(
            "A 被明确发问（Hard Trigger 旁路）",
            len(bad) == 0,
            f"评分点中出现 {len(bad)} 条 AT_MENTION 消息（应为 0）",
            samples=len(decisions),
        ))

    # B：高速刷屏
    s = _scenario(conf, "scenario_b_high_velocity")
    if s:
        rows = [d for d in decisions if d.get("velocity_count", 0) >= s["high_velocity_at"]]
        rate = _trigger_rate(rows)
        ok = rate <= s["max_trigger_rate"]
        results.append(ScenarioResult(
            "B 高速刷屏不抢话", ok,
            f"高速点 {len(rows)} 个，触发率 {rate:.1%}（上限 {s['max_trigger_rate']:.0%}）",
            samples=len(rows), metrics={"trigger_rate": rate},
        ))

    # C：强社交钩子
    s = _scenario(conf, "scenario_c_social_hook")
    if s:
        rows = [d for d in decisions if "strong_social_hook" in (d.get("reason_flags") or [])]
        cand = sum(1 for r in rows if r.get("decision") in ("CANDIDATE", "ALLOW_LLM"))
        rate = cand / len(rows) if rows else 0.0
        ok = rate >= s["min_candidate_rate"]
        results.append(ScenarioResult(
            "C 强社交钩子有机会", ok,
            f"钩子点 {len(rows)} 个，CANDIDATE+ 占比 {rate:.1%}"
            f"（下限 {s['min_candidate_rate']:.0%}）",
            samples=len(rows), metrics={"candidate_rate": rate},
        ))

    # D：感兴趣但无机会 → 允许沉默
    s = _scenario(conf, "scenario_d_interested_no_opportunity")
    if s:
        kw = tuple(k.lower() for a in tables.topics.interests for k in a.keywords)
        rows = [
            d for d in decisions
            if any(k in (d.get("text") or "").lower() for k in kw)
            and not any(f in (d.get("reason_flags") or [])
                        for f in ("open_question", "question_to_group", "strong_social_hook"))
        ]
        silence = 1.0 - _trigger_rate(rows)
        ok = silence >= s["min_silence_rate"]
        results.append(ScenarioResult(
            "D 感兴趣无机会可沉默", ok,
            f"兴趣陈述点 {len(rows)} 个，沉默率 {silence:.1%}"
            f"（下限 {s['min_silence_rate']:.0%}）",
            samples=len(rows), metrics={"silence_rate": silence},
        ))

    # E：刚说过话 → 降分
    s = _scenario(conf, "scenario_e_recent_speech")
    if s:
        win = s["within_seconds"]
        rows = [
            d for d in decisions
            if d.get("seconds_since_spoke") is not None and d["seconds_since_spoke"] <= win
        ]
        local = statistics.fmean([r["final_score"] for r in rows]) if rows else 0.0
        ratio = local / baseline if baseline > 0 else 0.0
        ok = ratio <= s["max_score_ratio"]
        results.append(ScenarioResult(
            "E 刚说过话降分", ok,
            f"发言后 {win}s 内 {len(rows)} 个评分点，均值 {local:.1f} / 基线 {baseline:.1f}"
            f" = {ratio:.2f}（上限 {s['max_score_ratio']})",
            samples=len(rows), metrics={"score_ratio": ratio},
        ))

    # F：话题过期绝不触发
    s = _scenario(conf, "scenario_f_topic_expired")
    if s:
        rows = [d for d in decisions if d.get("topic_status") in ("COOLING", "EXPIRED")]
        rate = _trigger_rate(rows)
        ok = rate <= s["max_trigger_rate"]
        results.append(ScenarioResult(
            "F 话题过期不复活", ok,
            f"过期状态评分点 {len(rows)} 个，触发率 {rate:.1%}（上限 0）",
            samples=len(rows), metrics={"trigger_rate": rate},
        ))

    return results


def distribution(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """分数与分项分布（报告附表）。"""
    if not decisions:
        return {}
    keys = (
        "relevance", "opportunity", "social_opportunity", "topic_involvement",
        "silence_bonus", "recent_speech_penalty", "velocity_penalty",
        "repetition_penalty", "expired_penalty", "final_score",
    )
    dist: dict[str, Any] = {}
    for k in keys:
        vals = [d.get(k, 0.0) or 0.0 for d in decisions]
        dist[k] = {
            "mean": round(statistics.fmean(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
        }
    levels: dict[str, int] = {}
    for d in decisions:
        levels[d.get("decision", "?")] = levels.get(d.get("decision", "?"), 0) + 1
    dist["decision_counts"] = levels
    return dist


def write_report(
    results: list[ScenarioResult],
    decisions: list[dict[str, Any]],
    out_md: Path,
    *,
    source_desc: str,
    tables_desc: str,
) -> None:
    """输出 markdown 摘要报告 + 同名 .jsonl 决策明细（可 diff 两次运行）。"""
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 参与评分 benchmark 报告",
        "",
        f"- 数据源：{source_desc}",
        f"- 打分表：{tables_desc}",
        f"- 评分点：{len(decisions)} 个",
        "",
        "## 场景通过矩阵",
        "",
        "| 场景 | 结果 | 样本 | 说明 |",
        "|---|---|---:|---|",
    ]
    for r in results:
        verdict = "✅ PASS" if r.passed else "❌ FAIL" if r.passed is False else "⏭ SKIP"
        lines.append(f"| {r.name} | {verdict} | {r.samples} | {r.detail} |")
    lines += ["", "## 分数与分项分布", "", "```json", repr(distribution(decisions)), "```", ""]
    out_md.write_text("\n".join(lines), encoding="utf-8")

    import json

    detail = out_md.with_suffix(".jsonl")
    with detail.open("w", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
