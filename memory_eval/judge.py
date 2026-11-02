# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""LLM-as-judge：LoCoMo 协议判分（prompt 固定版本，温度 0）。"""

from __future__ import annotations

from typing import Any

JUDGE_PROMPT_VERSION = "locomo-judge-v1"

_JUDGE_INSTRUCTIONS = """You are grading a memory agent's response to a question about a very long multi-session conversation. Grade strictly and fairly.

QUESTION:
{question}

GROUND TRUTH ANSWER:
{gold}
{decoy_section}
RESPONSE TO GRADE:
{answer}

GRADING RULES:
1. Grade only whether the RESPONSE conveys the same key information as the ground truth. Paraphrasing, wording differences, extra polite filler, or answering in another language are all acceptable.
2. If the ground truth is an abstention case (the information is NOT stated in the conversation), grade CORRECT only when the response says the information is not available / it does not know / cannot find it. Grade INCORRECT if the response asserts any specific answer, even a plausible one.
3. Grade INCORRECT if the response contradicts the ground truth, asserts wrong key facts, or answers "I don't know" while the ground truth is a concrete answer.
4. Do not reward hedging on answerable questions.

Reply with exactly one word: CORRECT or INCORRECT."""


def build_judge_prompt(
    question: str,
    gold_answer: str | None,
    response: str,
    *,
    adversarial_answer: str | None = None,
) -> str:
    gold = str(gold_answer).strip() if gold_answer is not None else ""
    if not gold:
        gold = (
            "(abstention case — this information is NOT stated in the conversation; "
            "the correct behavior is to say the information is not available)"
        )
    decoy_section = ""
    if adversarial_answer:
        decoy_section = (
            f"\nKNOWN DECOY (a plausible but unsupported answer; giving it or any other\n"
            f"specific answer must be graded INCORRECT):\n{adversarial_answer.strip()}\n"
        )
    return _JUDGE_INSTRUCTIONS.format(
        question=question.strip(),
        gold=gold,
        decoy_section=decoy_section,
        answer=(response or "").strip() or "(empty response)",
    )


def parse_verdict(raw: str) -> dict[str, Any]:
    """解析 judge 输出；无法解析记 unparseable（按 incorrect 计并留痕）。"""
    text = (raw or "").strip()
    upper = text.upper()
    if upper.startswith("CORRECT") and not upper.startswith("CORRECTLY"):
        verdict = "correct"
    elif upper.startswith("INCORRECT"):
        verdict = "incorrect"
    elif "INCORRECT" in upper and "CORRECT" in upper:
        # 混合输出：取首个出现者
        verdict = "incorrect" if upper.find("INCORRECT") < upper.find("CORRECT") else "correct"
    elif "CORRECT" in upper:
        verdict = "correct"
    else:
        verdict = "unparseable"
    return {"verdict": verdict, "raw": text[:400]}
