# SPDX-License-Identifier: AGPL-3.0
"""统一的聊天上下文预算。

主聊天模型通常运行在 8192 tokens 工作窗口中。这里不负责理解内容，
只负责在 Pipeline 调用模型前给输入、输出和估算误差留下硬边界。
"""

from __future__ import annotations

from dataclasses import dataclass

from config import (
    LLM_CONTEXT_SAFETY_TOKENS,
    LLM_CONTEXT_WINDOW_TOKENS,
    LLM_OUTPUT_RESERVE_TOKENS,
)

TRUNCATION_NOTICE = "【前文已按上下文预算压缩】"


def estimate_tokens(text: str) -> int:
    """保守估算中文和普通文本的 token 数。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_words = len([word for word in text.split() if word])
    return int(cjk * 1.5 + other_words * 1.3)


@dataclass(frozen=True)
class PromptBudgetResult:
    prompt: str
    estimated_tokens: int
    budget_tokens: int
    window_tokens: int
    truncated: bool


def _tail_for_tokens(text: str, token_budget: int) -> str:
    if token_budget <= 0:
        return ""
    if estimate_tokens(text) <= token_budget:
        return text
    # 中文估算按 1.5 token/字；再缩短一成，避免估算误差顶满预算。
    char_limit = max(1, int(token_budget / 1.65))
    return text[-char_limit:]


def _fit_prompt(prompt: str, token_budget: int) -> str:
    if estimate_tokens(prompt) <= token_budget:
        return prompt

    marker = "【现在 "
    if marker in prompt:
        context, current = prompt.split(marker, 1)
        current = marker + current
        notice = TRUNCATION_NOTICE + "\n"
        current_budget = max(1, token_budget - estimate_tokens(notice))
        # 当前输入位于尾部，优先保证它完整；背景只取尾部。
        current = _tail_for_tokens(current, current_budget)
        context_budget = max(
            0,
            token_budget - estimate_tokens(notice) - estimate_tokens(current),
        )
        context = _tail_for_tokens(context, context_budget)
        return notice + context + ("\n\n" if context else "") + current

    notice = TRUNCATION_NOTICE + "\n"
    return notice + _tail_for_tokens(
        prompt, max(1, token_budget - estimate_tokens(notice))
    )


def fit_prompt_to_window(
    prompt: str,
    system_prompt: str = "",
    *,
    context_window_tokens: int = LLM_CONTEXT_WINDOW_TOKENS,
    output_reserve_tokens: int = LLM_OUTPUT_RESERVE_TOKENS,
    safety_tokens: int = LLM_CONTEXT_SAFETY_TOKENS,
) -> PromptBudgetResult:
    """把 user prompt 压到工作窗口内，保留输出和估算安全余量。"""
    budget = max(
        1,
        int(context_window_tokens)
        - int(output_reserve_tokens)
        - int(safety_tokens)
        - estimate_tokens(system_prompt),
    )
    fitted = _fit_prompt(prompt or "", budget)
    return PromptBudgetResult(
        prompt=fitted,
        estimated_tokens=estimate_tokens(fitted),
        budget_tokens=budget,
        window_tokens=int(context_window_tokens),
        truncated=fitted != (prompt or ""),
    )
