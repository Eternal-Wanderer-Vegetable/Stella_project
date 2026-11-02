# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MBENCH-004 P3：证据充分性判断与可靠弃答（B0–B4 对照）。

P3-1 三态分类（P3-1 证据充分性）：
- SUPPORTED：记忆中存在与问题直接对应、可支持所需事实的陈述 → 正常作答；
- INSUFFICIENT：缺少必要证据 → 弃答（固定文本）；
- AMBIGUOUS：近似相关、冲突或不确定 → 保守作答（strict 指令）。

判断输入是**整包**（question + 记忆包表示），要求模型显式核对多条证据是否
合起来足以支持，而非只看最高检索分。

对照格（同 304 题，组合检索配置）：
- B0：无保护（既有 qamode-paired 运行）；
- B1：strict prompt（既有 ablation-combined-guard 运行）；
- B2：检索分数门控——top_score < τ 时强制弃答。可离线仿真：
      门内问题沿用 B0 的判定，门外按「可回答题判错/对抗题判对」计；
- B3：LLM 充分性验证器（``--sufficiency-guard``）：INSUFFICIENT → 弃答；
- B4：B3 + strict prompt（``--sufficiency-guard --abstention-guard``）。

B2 的离线仿真与 B3/B4 的运行入口见 runner 与本模块 ``simulate_b2``。
"""

from __future__ import annotations

import json
from typing import Any

SUFFICIENCY_PROMPT_VERSION = "sufficiency-verifier-v1"

_VERIFIER_INSTRUCTIONS = (
    "你是记忆问答的证据充分性审核员。给你一个问题和一组候选记忆，"
    "判断这组记忆**合起来**是否足以直接支持回答该问题所需的事实。"
    "判定标准：\n"
    "SUPPORTED — 记忆中存在与问题直接对应的陈述，其内容足以推出答案；\n"
    "INSUFFICIENT — 记忆中没有与问题直接对应的内容（只有主题相近的无关信息也算不足）；\n"
    "AMBIGUOUS — 有部分相关或相互冲突的信息，不足以确定地回答。\n"
    "注意：多条证据必须合并核对是否完整；不要因为某条记忆与问题主题相近就判 SUPPORTED。\n"
    "只输出一个 JSON 对象，格式严格为：{\"verdict\": \"SUPPORTED\"} 或 "
    "{\"verdict\": \"INSUFFICIENT\"} 或 {\"verdict\": \"AMBIGUOUS\"}。"
    "不要使用 sufficient 布尔字段，不要输出 reason 或其他字段。"
)

FORCED_ABSTENTION_TEXT = "记忆中没有相关信息。"


def build_verifier_prompt(question: str, pack_text: str) -> str:
    return (
        f"{pack_text}\n\n---\n问题：{question}\n\n"
        "请按系统规则输出这组记忆对该问题的充分性判定 JSON。"
    )


def _json_segments(text: str) -> list[str]:
    """粗提取所有 {...} 平衡片段（容忍 ``` 围栏与前后杂文本）。"""
    segments = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                segments.append(text[start : i + 1])
                start = -1
    return segments


def parse_verdict_output(raw: str) -> str:
    """解析验证器输出为三态之一；无法解析时保守判 AMBIGUOUS。

    兼容两种实测输出形态：{"verdict": "..."} 与 {"sufficient": true/false}
    （reasoning 模型的 schema 漂移），再退回词面匹配。
    """
    text = (raw or "").strip()
    for segment in _json_segments(text):
        try:
            obj = json.loads(segment)
        except ValueError:
            continue
        if isinstance(obj, dict):
            v = str(obj.get("verdict") or "").upper()
            if v in ("SUPPORTED", "INSUFFICIENT", "AMBIGUOUS"):
                return v
            suff = obj.get("sufficient")
            if isinstance(suff, bool):
                return "SUPPORTED" if suff else "INSUFFICIENT"
    upper = text.upper()
    if "INSUFFICIENT" in upper:
        return "INSUFFICIENT"
    if "AMBIGUOUS" in upper:
        return "AMBIGUOUS"
    if "SUPPORTED" in upper:
        return "SUPPORTED"
    return "AMBIGUOUS"


def simulate_b2(
    records: list[dict[str, Any]],
    tau_grid: list[float],
) -> list[dict[str, Any]]:
    """B2 检索分数门控的离线仿真：top_score < τ 的问题强制弃答。

    门内问题沿用原判定（同提示词同模型，行为不变）；门外按弃答文本计：
    可回答题 = incorrect，对抗题 = correct。返回每个 τ 的指标行。
    """
    rows = []
    for tau in tau_grid:
        answerable_n = answerable_hits = 0
        adv_n = adv_hits = 0
        gated = 0
        for r in records:
            is_answerable = bool(r.get("gold_answer"))
            top = float(r.get("top_score") or 0.0)
            if top < tau:
                gated += 1
                if is_answerable:
                    answerable_n += 1  # 强制弃答 → 可回答题判错
                else:
                    adv_n += 1
                    adv_hits += 1  # 强制弃答 → 对抗题正确
                continue
            if is_answerable:
                answerable_n += 1
                answerable_hits += r.get("verdict") == "correct"
            else:
                adv_n += 1
                adv_hits += r.get("verdict") == "correct"
        rows.append({
            "tau": tau,
            "gated": gated,
            "answerable_accuracy": round(answerable_hits / answerable_n * 100, 1) if answerable_n else None,
            "abstention_accuracy": round(adv_hits / adv_n * 100, 1) if adv_n else None,
        })
    return rows
