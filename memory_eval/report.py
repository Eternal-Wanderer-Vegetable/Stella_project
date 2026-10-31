# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""评测报告：运行指纹 + JSON 报告 + Markdown 摘要。"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "memory-eval-report/1"


def git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
    except Exception:
        return None


def build_run_meta(args: Any, index: dict[str, Any], llm: Any | None, judge: Any | None) -> dict[str, Any]:
    from memory.schema import SCHEMA_VERSION

    return {
        "report_schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_head": git_head(),
        "memory_schema_version": SCHEMA_VERSION,
        "dataset": {
            "name": "snap-research/locomo",
            "revision": "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376",
            "index_sha256": (index.get("source") or {}).get("sha256"),
            "license": "CC-BY-NC-4.0",
        },
        "channel": getattr(args, "mode", None),
        "write_mode": getattr(args, "consolidation", "live"),
        "gold_injection": bool(getattr(args, "inject_gold", False)),
        "qa_sample_per_category": getattr(args, "qa_sample", 0) or None,
        "seed": getattr(args, "seed", 0),
        "answer_model": llm.cost_summary() if llm is not None else None,
        "judge_model": judge.cost_summary() if judge is not None else None,
        "consolidation": {
            "role": "ROLE_CONSOLIDATION（生产 backend_for 装配）",
            "extract_role": "ROLE_EXTRACT（按配置可用则启用）",
        },
        "prompts": {
            "answer": "memory-eval-answer-v1",
            "judge": "locomo-judge-v1",
        },
    }


def write_report(out_dir: Path, run_meta: dict[str, Any], per_scenario: list[dict[str, Any]],
                 summary: dict[str, Any]) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        **run_meta,
        "summary": summary,
        "scenarios": [
            {
                "scenario_id": s.get("scenario_id"),
                "funnel": s.get("funnel"),
                "consolidation_calls": s.get("consolidation_calls"),
                "qa_total": len(s.get("qa_results") or []),
                "aggregate": s.get("aggregate"),
            }
            for s in per_scenario
        ],
    }
    json_path = out_dir / "memory_eval_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path = out_dir / "memory_eval_report.md"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: dict[str, Any]) -> str:
    s = report.get("summary") or {}
    lines = [
        "# memory_eval 运行摘要",
        "",
        f"- 生成时间：{report.get('generated_at')} ｜ git HEAD：`{report.get('git_head')}`",
        f"- 数据集：{report['dataset']['name']} @ {report['dataset']['revision'][:12]}…"
        f"（sha256 {str(report['dataset']['index_sha256'])[:12]}…）",
        f"- 检索通道：{report.get('channel')} ｜ QA 抽样：{report.get('qa_sample_per_category') or '全量'}"
        f" ｜ seed：{report.get('seed')}",
        f"- answer 模型：{(report.get('answer_model') or {}).get('model')} @ "
        f"{(report.get('answer_model') or {}).get('base_url')}",
        f"- judge 模型：{(report.get('judge_model') or {}).get('model')}",
        "",
        "## 总体",
        "",
        f"- QA 总数：{s.get('total')} ｜ J-accuracy：**{s.get('accuracy')}%**"
        f" ｜ unparseable：{s.get('unparseable')} ｜ errors：{s.get('errors')}",
        f"- adversarial 弃答正确率：{s.get('adversarial_abstention_accuracy')}%",
        f"- 写侧覆盖（memories / candidates）：{s.get('write_coverage_memories')} / "
        f"{s.get('write_coverage_candidates')}",
        f"- 检索证据覆盖（n-gram 代理）：{s.get('retrieval_evidence_coverage')}",
        f"- 记忆包均值：{s.get('pack_memory_count_avg')} 条 / {s.get('pack_chars_avg')} 字符",
        f"- 捕获漏斗合计：{s.get('funnel_totals')}",
        "",
        "## 分类别",
        "",
        "| 类别 | 数量 | accuracy | unparseable |",
        "| --- | --- | --- | --- |",
    ]
    for name, row in (s.get("by_category") or {}).items():
        lines.append(f"| {name} | {row.get('total')} | {row.get('accuracy')}% | {row.get('unparseable')} |")
    lines += ["", "## 分场景", "", "| 场景 | 候选 | 记忆(active) | QA | accuracy |", "| --- | --- | --- | --- | --- |"]
    for sc in report.get("scenarios") or []:
        funnel = sc.get("funnel") or {}
        agg = sc.get("aggregate") or {}
        lines.append(
            f"| {sc.get('scenario_id')} | {funnel.get('candidates_total')} | "
            f"{funnel.get('memories_active')} | {sc.get('qa_total')} | {agg.get('accuracy')}% |"
        )
    lines += [
        "",
        "## 已知局限",
        "",
        "- 证据合同只接受窄句型（居住/来自/称呼/雇主/一般偏好），非句型事实当前版本不可晋升；"
        "漏斗与写侧覆盖负责把低召回归因到具体环节。",
        "- LoCoMo gold 约 6% 已知噪声（Penfield Labs 独立审计，2026）；judge 与被测同源自评偏差。",
        "- 回放把数月压缩到小时级：时间敏感指标（recency 权重、TTL）与生产存在差异；"
        "记忆确认时间已按会话时间回填以缓解。",
        "- 语言为英文（数据集原样），结论限定为英文域外部参照。",
    ]
    return "\n".join(lines) + "\n"
