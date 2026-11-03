# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MBENCH-004 P1-2：证据合同离线对照（A0–A3），不修改生产代码。

对照对象：`memory_eval/annotation/locomo-contract-gold.jsonl`（202 条人工标注，
label ∈ MUST/MAY/MUST_NOT_CAPTURE，文本锚定到 gitignored 候选池）。

四个验收配置（作用域=对同一批候选的「验收」阶段；抽取阶段固定不变）：
- A0：生产证据合同现状——`memory.evidence_contract` 的刻板句型 fullmatch
  （自我陈述 + 一般偏好，中英），canonical value 须一致。
- A1：扩展句型规则——在 A0 句型族之外增加 身份(我是/我有/I am/I have)、
  计划(我打算/我想/我计划/I'm planning/I want to)、能力(我会/I can/I play)、
  过去事件(我以前/我曾经/I used to/I went) 等锚定句型；仍要求句型 fullmatch。
- A2：A1 + 语义过滤——拒绝条件/假设/传闻句、含引号的转述、问句、
  第二人称宾语（评价他人的“我喜欢你…”）、占位符残留。
- A3：A2 + 时间/主体约束——为通过项标注 fact_time（past/current/future）与
  subject（self/other），计划类必须有将来标记，过去标记不升格为当前事实。

指标（对照 202 条 gold）：
- MUST_CAPTURE Recall（按类别分解）；
- MUST_NOT 误验收数（错误晋升风险，目标 0）；
- MAY 验收数（参考）；
- 精确率代理 = (MUST+MAY 命中) / 全部验收。

用法：
    python -m memory_eval.contract_study --gold memory_eval/annotation/locomo-contract-gold.jsonl \
        --pool memory/benchmark/_public/locomo/annotation/candidate-pool.jsonl --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from memory.evidence_contract import (
    _PREFERENCE_PATTERN,
    _PREFERENCE_PATTERN_EN,
    _SELF_REPORT_PATTERNS,
)

# ── A1：扩展句型（锚定、带 value 捕获组；zh+en）──────────────────────
_A1_PATTERNS: dict[str, re.Pattern] = {
    # 身份与长期状态
    "identity.am": re.compile(r"我是(?P<value>[^，。！？!?；;]+)[。！!]?", re.IGNORECASE),
    "identity.have": re.compile(r"我有(?P<value>[^，。！？!?；;]+)[。！!]?", re.IGNORECASE),
    "identity.en_am": re.compile(r"I am (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    "identity.en_have": re.compile(r"I have (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    "identity.nickname": _SELF_REPORT_PATTERNS["profile.nickname"],
    "identity.nickname_en": _SELF_REPORT_PATTERNS["profile.nickname.en"],
    # 计划与意图
    "plan.intend": re.compile(r"我打算(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "plan.want": re.compile(r"我想(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "plan.will": re.compile(r"我要(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "plan.doing": re.compile(r"我正在(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "plan.en_gonna": re.compile(r"I(?:'m| am) (?:going to|planning (?:on|to)|thinking of (?:going|working|putting|creating|building)) (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    "plan.en_want": re.compile(r"I want to (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    # 能力与习惯
    "ability.can": re.compile(r"我会(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "ability.en_can": re.compile(r"I can (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    "ability.en_play": re.compile(r"I (?:play|sing) (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    # 偏好（沿用生产）
    "pref.zh": _PREFERENCE_PATTERN,
    "pref.en": _PREFERENCE_PATTERN_EN,
    # 过去事件
    "past.used_to": re.compile(r"我(?:以前|曾经)(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "past.en_used": re.compile(r"I used to (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    "past.en_went": re.compile(r"I went to (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
    "past.en_had": re.compile(r"I had (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE),
}

# ── A2：语义过滤 ─────────────────────────────────────────────────────
_CONDITIONAL = re.compile(
    r"如果|要是|假如|倘若|可能|也许|听说|据说|好像|传闻|角色扮演|扮演|假装|开玩笑|玩笑|"
    r"\b(?:if|maybe|perhaps|supposedly|heard that|roleplay|pretend|joking)\b",
    re.IGNORECASE,
)
_SECOND_PERSON = re.compile(r"你|您|\byou\b|\byour\b", re.IGNORECASE)
_QUESTION = re.compile(r"[？?]\s*$")
_PLACEHOLDER = re.compile(r"\bX\b(?![a-zA-Z])")
_MIN_VALUE_LEN = 2

# ── A3：时间标记 ─────────────────────────────────────────────────────
_PAST_MARK = re.compile(r"以前|曾经|去年|上周|昨天|小时候|十年前|三年前|4年|五年|used to|last |yesterday|ago", re.IGNORECASE)
_FUTURE_MARK = re.compile(r"打算|想要|计划|下个月|下周|准备|即将|将|planning|going to|next |will|this month", re.IGNORECASE)


def _a0_accept(content: str) -> tuple[bool, str, str, str, str]:
    """A0：生产刻板句型（自我陈述 + 一般偏好），value 须与句型捕获一致。"""
    t = content.strip()
    for predicate, pattern in _SELF_REPORT_PATTERNS.items():
        m = pattern.fullmatch(t)
        if m:
            return True, f"a0:{predicate}", (m.groupdict().get("value") or "").strip(), "unspecified", "self"
    for pattern in (_PREFERENCE_PATTERN, _PREFERENCE_PATTERN_EN):
        m = pattern.fullmatch(t)
        if m:
            return True, "a0:preference.general", (m.groupdict().get("value") or "").strip(), "unspecified", "self"
    return False, "", "", "", ""


def _match_any(patterns: dict[str, re.Pattern], text: str) -> tuple[bool, str, str]:
    """返回 (matched, family, value)。优先 fullmatch，其次 search（A1 起允许）。"""
    t = text.strip()
    for family, pattern in patterns.items():
        m = pattern.fullmatch(t)
        if m:
            return True, family, (m.groupdict().get("value") or "").strip()
    for family, pattern in patterns.items():
        m = pattern.search(t)
        if m:
            return True, family, (m.groupdict().get("value") or "").strip()
    return False, "", ""


def _a1_accept(content: str) -> tuple[bool, str, str, str, str]:
    ok, family, value, _t, _s = _a0_accept(content)
    if ok:
        return True, family, value, "unspecified", "self"
    matched, family2, value2 = _match_any(_A1_PATTERNS, content)
    return matched, family2, value2, "unspecified", "self"


def _a2_accept(content: str) -> tuple[bool, str, str, str, str]:
    """A2：A1 + 语义过滤（条件/传闻/引号/问句/第二人称宾语/占位符/过短值）。"""
    t = content.strip()
    ok, family, value, _t, _s = _a1_accept(t)
    if not ok:
        return False, "", "", "", ""
    if _CONDITIONAL.search(t):
        return False, "rejected:conditional", value, "", ""
    if _QUESTION.search(t):
        return False, "rejected:question", value, "", ""
    if _PLACEHOLDER.search(t):
        return False, "rejected:placeholder", value, "", ""
    if len(value) < _MIN_VALUE_LEN:
        return False, "rejected:too_short", value, "", ""
    # 第二人称宾语：评价他人的「我喜欢你…」不是说话者偏好（identity.have 的
    # “我有你…”同理）；allow 例外：值段以「自己」开头等第一人称回指
    if _SECOND_PERSON.search(value) and "自己" not in value:
        return False, "rejected:second_person", value, "", ""
    return True, family, value, "current", "self"


def _a3_accept(content: str) -> tuple[bool, str, str, str, str]:
    """A3：A2 + 时间/主体标注；过去标记不升格为当前事实（打 past 标签照常验收）。"""
    t = content.strip()
    ok, family, value, _t0, _s0 = _a2_accept(t)
    if not ok:
        return False, family, value, "", ""
    if _PAST_MARK.search(t):
        fact_time = "past"
    elif _FUTURE_MARK.search(t):
        fact_time = "future"
    else:
        fact_time = "current"
    subject = "self"
    return True, family, value, fact_time, subject


def _shipped_accept(content: str) -> tuple[bool, str, str, str, str]:
    """shipped 配置：直接走生产合同语义（消双实现漂移）。

    推断 kind/predicate/value 后调用生产 ``_semantic_contract_matches``，
    再套生产 A2 值段过滤器（len<2 / 占位符 / 第二人称宾语）——与
    assess_candidate 的语义段同源。
    """
    import re as _re

    from memory import evidence_contract as ec
    from memory.evidence_contract import (
        _MIN_VALUE_LEN,
        _semantic_contract_matches,
    )

    t = content.strip()
    second_person = _re.compile(r"你|您|you|your", _re.IGNORECASE)
    placeholder = _re.compile(r"X(?![a-zA-Z])")

    families: list[tuple[str, str, Any]] = [
        ("self_report", predicate, pattern)
        for predicate, pattern in ec._SELF_REPORT_PATTERNS.items()
    ]
    families.append(("explicit_preference", "preference.general", ec._PREFERENCE_PATTERN))
    families.append(
        ("explicit_preference", "preference.general", ec._PREFERENCE_PATTERN_EN)
    )
    for kind in ("identity_state", "plan_intent", "ability_habit", "past_event"):
        table = {
            "identity_state": ec._IDENTITY_STATE_PATTERNS,
            "plan_intent": ec._PLAN_INTENT_PATTERNS,
            "ability_habit": ec._ABILITY_HABIT_PATTERNS,
            "past_event": ec._PAST_EVENT_PATTERNS,
        }[kind]
        families.extend((kind, predicate, pattern) for predicate, pattern in table.items())

    for kind, predicate, pattern in families:
        matched, value = ec._match_value_pattern(pattern, t)
        if not matched:
            continue
        polarity = "positive"
        if kind == "explicit_preference":
            m2 = pattern.fullmatch(t) or pattern.search(t)
            cue_text = (m2.groupdict().get("cue") or "").lower() if m2 else ""
            polarity = (
                "negative"
                if cue_text in {"不喜欢", "讨厌", "don't like", "dislike"}
                else "positive"
            )
        # 生产 A2 值段过滤器
        if len(value) < _MIN_VALUE_LEN:
            return False, "shipped:too_short", value, "", ""
        if placeholder.search(value):
            return False, "shipped:placeholder", value, "", ""
        if second_person.search(value):
            return False, "shipped:second_person", value, "", ""
        if _semantic_contract_matches(
            t, predicate=predicate, canonical_value=value,
            polarity=polarity, statement_kind=kind,
        ):
            return True, f"shipped:{predicate}", value, "unspecified", "self"
    return False, "", "", "", ""


SHIPPED_CONFIGS = {"A0": _a0_accept, "A1": _a1_accept, "A2": _a2_accept, "A3": _a3_accept}


def evaluate(gold_path: Path, pool_path: Path) -> dict[str, Any]:
    gold = [json.loads(ln) for ln in gold_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    pool = {json.loads(ln)["sample_key"]: json.loads(ln)
            for ln in pool_path.read_text(encoding="utf-8").splitlines() if ln.strip()}
    configs = {"A0": _a0_accept, "A1": _a1_accept, "A2": _a2_accept, "A3": _a3_accept}
    configs["shipped"] = _shipped_accept
    out: dict[str, Any] = {"gold_size": len(gold), "configs": {}}
    for name, fn in configs.items():
        must_n = must_hit = 0
        must_hits_by_cat: dict[str, list[int]] = {}
        mustnot_n = mustnot_hit = 0
        may_n = may_hit = 0
        accepted = 0
        per_q = []
        for g in gold:
            r = pool[g["sample_key"]]
            content = r["content"] or ""
            ok, family, _value, _ft, _sj = fn(content)
            label = g["label"]
            if label == "MUST_CAPTURE":
                must_n += 1
                must_hit += ok
                must_hits_by_cat.setdefault(g["category"], [0, 0])
                must_hits_by_cat[g["category"]][0] += ok
                must_hits_by_cat[g["category"]][1] += 1
            elif label == "MUST_NOT_CAPTURE":
                mustnot_n += 1
                mustnot_hit += ok
            else:
                may_n += 1
                may_hit += ok
            accepted += ok
            per_q.append({"sample_key": g["sample_key"], "label": label,
                          "category": g["category"], "accepted": bool(ok),
                          "family": family})
        precision_proxy = round((must_hit + may_hit) / accepted * 100, 1) if accepted else None
        must_recall_by_cat = {
            cat: f"{hits}/{n} ({round(hits / n * 100, 1)}%)"
            for cat, (hits, n) in sorted(must_hits_by_cat.items())
        }
        out["configs"][name] = {
            "accepted": accepted,
            "must_recall": f"{must_hit}/{must_n} ({round(must_hit / must_n * 100, 1)}%)",
            "must_recall_by_category": must_recall_by_cat,
            "must_not_false_accept": f"{mustnot_hit}/{mustnot_n}",
            "may_accepted": f"{may_hit}/{may_n}",
            "precision_proxy": precision_proxy,
        }
        if name == "A3":
            out["configs"][name]["per_question"] = per_q
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="证据合同离线对照（A0–A3）")
    parser.add_argument("--gold", type=Path,
                        default=Path("memory_eval/annotation/locomo-contract-gold.jsonl"))
    parser.add_argument("--pool", type=Path,
                        default=Path("memory/benchmark/_public/locomo/annotation/candidate-pool.jsonl"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    import os
    import tempfile

    os.environ.setdefault("STELLA_HOME", tempfile.mkdtemp(prefix="stella-contract-study-"))

    report = evaluate(args.gold, args.pool)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
