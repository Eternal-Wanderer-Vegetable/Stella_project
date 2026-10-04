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

# 结构化预算的格式版本（多人身份修复计划 §6.4/§6.5）：trace 快照与离线回放
# 按版本分派 v1 generic / v2 parts。
BUDGET_FORMAT_VERSION = 2

# 预算不足时的丢弃顺序（计划 §6.4）：可选证据 → 带归属记忆 → 画像 → 当前
# 正文只裁正文。history **不整节丢弃**——按行边界从最旧一个逻辑单元让位；
# identity/当前输入 envelope 受保护，绝不静默删身份。
_PART_DROP_ORDER = ("evidence", "memories", "profile")


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


# ── 结构化预算（多人身份修复计划 §6.4） ───────────────────────────────
# 与 fit_prompt_to_window 的关系：后者是 generic 兜底（旧消费者/回放 v1 保留，
# 逐字不动）；本入口吃**命名分节**，按语义丢弃整节，身份 capsule 与当前输入
# 信封受保护——用户正文里的「【现在 」等 marker 只是数据，不影响块定位。


@dataclass(frozen=True)
class ConversationPromptParts:
    """一次聊天回复 prompt 的结构化分节（顺序即最终拼装顺序）。

    identity_block（QQ 身份行 + capsule + addressing）与当前输入（envelope
    头 + 正文）受保护；history/memories/profile/evidence 按 _PART_DROP_ORDER
    整节丢弃。instruction_first=True（proactive_at 等指令型 intent）时当前
    正文排在最前——与 _compose_prompt 的指令分支同形。
    """

    identity_block: str = ""
    behavior_text: str = ""
    time_text: str = ""
    history_text: str = ""
    profile_text: str = ""
    memories_text: str = ""
    evidence_text: str = ""  # tool/knowledge/skill/social 预渲染
    current_speaker: str = ""  # 用户(xxx) / 对方
    current_body: str = ""
    instruction_first: bool = False


@dataclass(frozen=True)
class FitPartsResult:
    prompt: str
    estimated_tokens: int
    budget_tokens: int
    window_tokens: int
    truncated: bool
    over_protected: bool  # True = 受保护最小集已超预算（调用方走 DIRECT 简短回复）
    dropped: tuple[str, ...]
    parts_snapshot: dict


def _current_input_block(parts: ConversationPromptParts, body: str) -> str:
    speaker = parts.current_speaker or "对方"
    return (
        f"【现在 {speaker} 对你说】{body}\n"
        f"请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。"
    )


def _assemble_parts(
    parts: ConversationPromptParts, body: str, sections: list[tuple[str, str]]
) -> str:
    context_head = "\n\n".join(
        text for name, text in sections if text and name != "evidence"
    )
    evidence = next((t for n, t in sections if n == "evidence"), "")
    if parts.instruction_first:
        # 指令型 intent：指令 → 证据 → 上下文——与 _compose_prompt 同形
        return "\n\n".join(p for p in (parts.current_body, evidence, context_head) if p)
    head = "\n\n".join(p for p in (context_head, evidence) if p)
    if not head:
        return parts.current_body
    return f"{head}\n\n{_current_input_block(parts, body)}"


def fit_conversation_parts(
    parts: ConversationPromptParts,
    system_prompt: str = "",
    *,
    context_window_tokens: int = LLM_CONTEXT_WINDOW_TOKENS,
    output_reserve_tokens: int = LLM_OUTPUT_RESERVE_TOKENS,
    safety_tokens: int = LLM_CONTEXT_SAFETY_TOKENS,
) -> FitPartsResult:
    """结构化预算：整节丢弃 + 受保护身份/输入，最后带全部标签重算总量。

    丢弃顺序（计划 §6.4）：evidence → memories → profile → history；history
    仍超时按**行边界**从最旧一行让位（行 = tail 的逻辑单元/摘要行），绝不切
    半行；再超时只裁当前正文（尾部保留、作者/对象字段不切）。受保护最小集
    （identity + envelope 头 + 一行正文）仍超预算 → ``over_protected=True``，
    调用方应走 DIRECT 的「输入过长，请简化」，不调用超额 LLM。正文中的
    「【现在 」等 marker 只是数据，不影响块定位。
    """
    budget = max(
        1,
        int(context_window_tokens)
        - int(output_reserve_tokens)
        - int(safety_tokens)
        - estimate_tokens(system_prompt),
    )
    notice = TRUNCATION_NOTICE + "\n"
    notice_tokens = estimate_tokens(notice)

    texts = {
        "identity": parts.identity_block or "",
        "behavior": parts.behavior_text or "",
        "time": parts.time_text or "",
        "history": parts.history_text or "",
        "profile": parts.profile_text or "",
        "memories": parts.memories_text or "",
        "evidence": parts.evidence_text or "",
    }
    body = parts.current_body or ""

    def _current_t(b: str) -> int:
        # 指令型：正文本身就是当前输入块；普通型：带 envelope 头
        if parts.instruction_first:
            return estimate_tokens(b)
        return estimate_tokens(_current_input_block(parts, b))

    sizes = {name: estimate_tokens(text) for name, text in texts.items()}
    total = sum(sizes.values()) + _current_t(body)

    snapshot: dict = {
        "budget_format_version": BUDGET_FORMAT_VERSION,
        "budget_tokens": budget,
        "parts": {
            name: {"original_tokens": tokens, "kept_tokens": tokens}
            for name, tokens in sizes.items()
        },
        "identity_tokens": sizes["identity"],
        "current_tokens": _current_t(body),
        "current_sender_id": parts.current_speaker,
        "instruction_first": bool(parts.instruction_first),
        "dropped": [],
    }

    if total <= budget:
        prompt = _assemble_parts(parts, body, list(texts.items()))
        return FitPartsResult(
            prompt=prompt,
            estimated_tokens=estimate_tokens(prompt),
            budget_tokens=budget,
            window_tokens=int(context_window_tokens),
            truncated=False,
            over_protected=False,
            dropped=(),
            parts_snapshot=snapshot,
        )

    dropped: list[str] = []

    # Phase 1：按语义优先级整节丢弃（行为约束 behavior 不在丢弃序列——
    # 安全/功能优先级沿用既有分区预算的约定）
    for name in _PART_DROP_ORDER:
        if total <= budget:
            break
        if sizes[name] > 0:
            total -= sizes[name]
            sizes[name] = 0
            texts[name] = ""
            dropped.append(name)
            snapshot["parts"][name]["kept_tokens"] = 0

    # Phase 2：history 按**行边界**从最旧让位（行 = 逻辑单元/摘要行）
    if total > budget and sizes["history"] > 0:
        lines = texts["history"].split("\n")
        while len(lines) > 1 and total > budget:
            removed = lines.pop(0)
            total -= estimate_tokens(removed) + 1
        texts["history"] = "\n".join(lines)
        sizes["history"] = estimate_tokens(texts["history"])
        snapshot["parts"]["history"]["kept_tokens"] = sizes["history"]
        if "history" not in dropped:
            dropped.append("history")

    # Phase 3：当前正文只裁正文（尾部保留），作者/对象字段不切
    trimmed_body = False
    if total > budget and body:
        header_tokens = _current_t("")
        body_allowance = budget - sum(sizes.values()) - header_tokens
        trimmed = _tail_for_tokens(body, max(1, body_allowance))
        if trimmed != body:
            total = total - _current_t(body) + _current_t(trimmed)
            body = trimmed
            trimmed_body = True
            snapshot["current_body_trimmed"] = True

    over_protected = total > budget
    if over_protected:
        # 受保护最小集超预算：拼出可发送的最小 prompt 并置位——调用方走
        # DIRECT 简短回复，不调用超额 LLM。
        dropped.append("__over_protected__")
        snapshot["dropped"] = dropped
        prompt = notice + _assemble_parts(
            parts, body, [("identity", texts["identity"])]
        )
        return FitPartsResult(
            prompt=prompt,
            estimated_tokens=estimate_tokens(prompt),
            budget_tokens=budget,
            window_tokens=int(context_window_tokens),
            truncated=True,
            over_protected=True,
            dropped=tuple(dropped),
            parts_snapshot=snapshot,
        )

    order = ["identity", "behavior", "time", "history", "profile", "memories", "evidence"]
    sections = [(name, texts[name]) for name in order]
    prompt = _assemble_parts(parts, body, sections)
    prompt = notice + prompt  # truncated=True 时统一带压缩提示
    snapshot["dropped"] = dropped
    return FitPartsResult(
        prompt=prompt,
        estimated_tokens=estimate_tokens(prompt),
        budget_tokens=budget,
        window_tokens=int(context_window_tokens),
        truncated=True,
        over_protected=False,
        dropped=tuple(dropped),
        parts_snapshot=snapshot,
    )


def fit_evidence_to_budget(
    evidence: list[dict],
    *,
    max_items: int,
    max_tokens: int,
    text_key: str = "text",
) -> list[dict]:
    """知识证据的独立预算（KNOWLEDGE_EVIDENCE_MAX_ITEMS / MAX_TOKENS）。

    与 ``fit_prompt_to_window`` 的关系：后者是**兜底**（整份 prompt 超窗时的
    粗暴截断），本函数是**前置**硬边界——证据在渲染前就被限条数、限 token，
    正常情况下根本轮不到兜底动手。顺序保持不变（检索序即相关序），
    超预算的尾部整条丢弃而不是截半条——半句引用比没有引用更误导。
    """
    if not evidence:
        return []
    limited = evidence[: max(0, int(max_items))]
    kept: list[dict] = []
    used = 0
    for item in limited:
        text = str(item.get(text_key, "") or "")
        cost = estimate_tokens(text) + 20  # 20 ≈ 引用行与格式开销
        if kept and used + cost > int(max_tokens):
            break
        # 第一条永远保留（即使单条超预算）：宁可给一条长证据，不给空段
        kept.append(item)
        used += cost
        if used >= int(max_tokens):
            break
    return kept
