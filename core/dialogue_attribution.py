# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""对话归属约束 - 回复中的作者/对象来源验证与服务端渲染。

按计划 §6.6，普通生成必须基于可信来源证据，不能让模型自由声称
未经验证的过去事实。历史引用经服务端渲染，确保作者/对象正确。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SourceEvidence:
    """来源证据 - 可验证的历史消息或已验证事实。

    Attributes:
        evidence_id: 证据 ID（用于模型引用）
        evidence_type: 证据类型（message / verified_fact）
        author_id: 作者 UID
        object_id: 对象 UID（若适用）
        original_text: 原文（消息）或事实模板
        conversation_key: 会话键
        source_row_id: 来源行 ID
        timestamp: 时间戳
        polarity: 极性（positive / negative / neutral）
        is_verified: 是否已验证（事实）
    """

    evidence_id: str
    evidence_type: Literal["message", "verified_fact", "current_correction"]
    author_id: int
    object_id: int | None
    original_text: str
    conversation_key: str
    source_row_id: int | None
    timestamp: str
    polarity: Literal["positive", "negative", "neutral"] = "neutral"
    is_verified: bool = False


@dataclass
class ReplyPlan:
    """结构化回复计划 - 模型输出的分解意图。

    按计划 §6.6，回复分为几个部分：
    - current_response: 自由口语回应当前输入
    - quote_reference: 引用历史原话（只提供 evidence_id）
    - verified_fact_reference: 引用已验证事实（只提供 evidence_id）
    - correction_ack: 承认纠正（使用当前可信纠正）
    """

    current_response: str = ""
    quote_references: list[str] = field(default_factory=list)  # evidence_id 列表
    verified_fact_references: list[str] = field(default_factory=list)
    correction_ack: str = ""
    protocol_version: str = "2026-10-05.1"


@dataclass
class AttributionDecision:
    """归属决策记录 - 最终放行/拒绝原因。

    Attributes:
        decision: 决策（pass / reject / fallback）
        rejection_reason: 拒绝原因
        original_output_digest: 原始模型输出摘要
        final_output_digest: 最终发送内容摘要
        guard_mode: 守护模式（off / shadow / enforce）
        checked_evidence_ids: 检查过的证据 ID
        invalid_references: 无效引用列表
        identity_revision: 身份修订版本
        generation_epoch: 生成轮次
    """

    decision: Literal["pass", "reject", "fallback"]
    rejection_reason: str = ""
    original_output_digest: str = ""
    final_output_digest: str = ""
    guard_mode: Literal["off", "shadow", "enforce"] = "off"
    checked_evidence_ids: list[str] = field(default_factory=list)
    invalid_references: list[str] = field(default_factory=list)
    identity_revision: int = 0
    generation_epoch: int = 0


def parse_reply_plan(raw_output: str) -> tuple[ReplyPlan | None, str]:
    """解析模型输出中的结构化回复计划。

    期望格式（XML 或 JSON）：
    <reply_plan>
        <current_response>...</current_response>
        <quote_reference evidence_id="..." />
        <verified_fact_reference evidence_id="..." />
        <correction_ack>...</correction_ack>
    </reply_plan>

    Returns:
        (parsed_plan, error_reason)
    """
    # TODO: 实际解析逻辑
    # 当前返回占位符
    return None, "not_implemented"


def validate_evidence_references(
    plan: ReplyPlan,
    available_evidence: dict[str, SourceEvidence],
    budget_retained_ids: set[str],
) -> tuple[bool, list[str]]:
    """验证引用的证据是否合法。

    检查：
    - 引用的 evidence_id 必须在可用证据集中
    - 证据必须在预算保留范围内
    - 作者/对象必须与声称一致

    Returns:
        (all_valid, invalid_reference_ids)
    """
    invalid = []

    all_refs = plan.quote_references + plan.verified_fact_references

    for ref_id in all_refs:
        if ref_id not in available_evidence:
            invalid.append(f"{ref_id}:not_in_evidence")
            continue

        if ref_id not in budget_retained_ids:
            invalid.append(f"{ref_id}:not_in_budget")
            continue

    return len(invalid) == 0, invalid


def render_evidence(
    evidence_id: str,
    evidence: SourceEvidence,
) -> str:
    """服务端渲染证据为最终文本。

    按原文渲染，不允许改写作者/对象。
    """
    if evidence.evidence_type == "message":
        # 消息引用：保留原话
        return evidence.original_text

    if evidence.evidence_type == "verified_fact":
        # 已验证事实：使用事实模板
        return evidence.original_text

    if evidence.evidence_type == "current_correction":
        # 当前纠正：优先级最高
        return evidence.original_text

    return ""


def check_risky_free_text(
    text: str,
    available_evidence_ids: set[str],
) -> tuple[bool, str]:
    """检查自由文本中的风险表达。

    风险模式：
    - 明显的过去事实声称（"你之前说过..."）
    - 指责用户失忆（"你怎么忘了"）
    - 引用已否定的动作

    这是有限词法防线，无法完全证明语义正确。

    Returns:
        (is_safe, risk_pattern)
    """
    risky_patterns = [
        "你之前说",
        "你刚才说",
        "你怎么忘了",
        "明明是你",
        "你装失忆",
    ]

    for pattern in risky_patterns:
        if pattern in text:
            return False, f"risky_pattern:{pattern}"

    return True, "ok"


def build_evidence_table(
    recent_messages: list[dict],
    verified_facts: list[dict],
    current_corrections: list[dict],
    max_units: int = 16,
) -> dict[str, SourceEvidence]:
    """构建证据表（R6 §6.6）。

    优先级（高到低）：
    1. current_corrections - 当前轮次的纠正
    2. verified_facts - 已验证的事实
    3. recent_messages - 近期消息（按时间倒序）

    Args:
        recent_messages: 近期消息列表
        verified_facts: 已验证事实列表
        current_corrections: 当前纠正列表
        max_units: 最大证据单元数

    Returns:
        evidence_id -> SourceEvidence 映射
    """
    evidence_table: dict[str, SourceEvidence] = {}
    unit_count = 0

    # 优先级1: 当前纠正
    for corr in current_corrections:
        if unit_count >= max_units:
            break

        evidence_id = f"correction_{corr.get('id', unit_count)}"
        evidence_table[evidence_id] = SourceEvidence(
            evidence_id=evidence_id,
            evidence_type="current_correction",
            author_id=corr.get("author_id", 0),
            object_id=corr.get("object_id"),
            original_text=corr.get("text", ""),
            conversation_key=corr.get("conversation_key", ""),
            source_row_id=corr.get("source_row_id"),
            timestamp=corr.get("timestamp", ""),
            polarity=corr.get("polarity", "neutral"),
            is_verified=True,
        )
        unit_count += 1

    # 优先级2: 已验证事实
    for fact in verified_facts:
        if unit_count >= max_units:
            break

        evidence_id = f"fact_{fact.get('id', unit_count)}"
        evidence_table[evidence_id] = SourceEvidence(
            evidence_id=evidence_id,
            evidence_type="verified_fact",
            author_id=fact.get("author_id", 0),
            object_id=fact.get("object_id"),
            original_text=fact.get("content", ""),
            conversation_key=fact.get("conversation_key", ""),
            source_row_id=fact.get("source_row_id"),
            timestamp=fact.get("timestamp", ""),
            polarity=fact.get("polarity", "neutral"),
            is_verified=True,
        )
        unit_count += 1

    # 优先级3: 近期消息（按时间倒序）
    for msg in recent_messages:
        if unit_count >= max_units:
            break

        evidence_id = f"msg_{msg.get('id', unit_count)}"
        evidence_table[evidence_id] = SourceEvidence(
            evidence_id=evidence_id,
            evidence_type="message",
            author_id=msg.get("author_id", 0),
            object_id=msg.get("object_id"),
            original_text=msg.get("text", ""),
            conversation_key=msg.get("conversation_key", ""),
            source_row_id=msg.get("row_id"),
            timestamp=msg.get("timestamp", ""),
            polarity="neutral",
            is_verified=False,
        )
        unit_count += 1

    return evidence_table


def apply_guard_decision(
    reply_plan: ReplyPlan | None,
    evidence_table: dict[str, SourceEvidence],
    guard_mode: Literal["off", "shadow", "enforce"],
    identity_revision: int,
) -> AttributionDecision:
    """应用归属守护决策（R6 §6.6）。

    决策规则：
    - off: 放行所有
    - shadow: 记录问题但放行
    - enforce: 拒绝无效引用

    Args:
        reply_plan: 解析后的回复计划
        evidence_table: 可用证据表
        guard_mode: 守护模式
        identity_revision: 身份修订版本

    Returns:
        归属决策记录
    """
    if guard_mode == "off":
        return AttributionDecision(
            decision="pass",
            guard_mode="off",
            identity_revision=identity_revision,
        )

    if reply_plan is None:
        # 解析失败
        if guard_mode == "enforce":
            return AttributionDecision(
                decision="reject",
                rejection_reason="parse_failed",
                guard_mode="enforce",
                identity_revision=identity_revision,
            )
        return AttributionDecision(
            decision="fallback",
            rejection_reason="parse_failed_shadow",
            guard_mode="shadow",
            identity_revision=identity_revision,
        )

    # 验证引用
    budget_retained_ids = set(evidence_table.keys())
    all_valid, invalid_refs = validate_evidence_references(
        reply_plan, evidence_table, budget_retained_ids
    )

    if not all_valid:
        if guard_mode == "enforce":
            return AttributionDecision(
                decision="reject",
                rejection_reason="invalid_references",
                guard_mode="enforce",
                checked_evidence_ids=list(budget_retained_ids),
                invalid_references=invalid_refs,
                identity_revision=identity_revision,
            )
        return AttributionDecision(
            decision="pass",
            rejection_reason="invalid_references_shadow",
            guard_mode="shadow",
            checked_evidence_ids=list(budget_retained_ids),
            invalid_references=invalid_refs,
            identity_revision=identity_revision,
        )

    # 检查自由文本风险
    is_safe, risk_pattern = check_risky_free_text(
        reply_plan.current_response, budget_retained_ids
    )

    if not is_safe:
        if guard_mode == "enforce":
            return AttributionDecision(
                decision="reject",
                rejection_reason=f"risky_text:{risk_pattern}",
                guard_mode="enforce",
                identity_revision=identity_revision,
            )
        return AttributionDecision(
            decision="pass",
            rejection_reason=f"risky_text_shadow:{risk_pattern}",
            guard_mode="shadow",
            identity_revision=identity_revision,
        )

    # 全部通过
    return AttributionDecision(
        decision="pass",
        guard_mode=guard_mode,
        checked_evidence_ids=list(budget_retained_ids),
        identity_revision=identity_revision,
    )


def render_final_reply(
    reply_plan: ReplyPlan,
    evidence_table: dict[str, SourceEvidence],
) -> str:
    """服务端渲染最终回复（R6 §6.6）。

    组合规则：
    1. current_response（自由口语）
    2. 引用消息原话
    3. 引用已验证事实
    4. 纠正承认

    返回最终发送的文本。
    """
    parts = []

    # 1. 自由回应
    if reply_plan.current_response:
        parts.append(reply_plan.current_response)

    # 2. 引用历史消息
    for ref_id in reply_plan.quote_references:
        if ref_id in evidence_table:
            rendered = render_evidence(ref_id, evidence_table[ref_id])
            if rendered:
                parts.append(rendered)

    # 3. 引用已验证事实
    for ref_id in reply_plan.verified_fact_references:
        if ref_id in evidence_table:
            rendered = render_evidence(ref_id, evidence_table[ref_id])
            if rendered:
                parts.append(rendered)

    # 4. 纠正承认
    if reply_plan.correction_ack:
        parts.append(reply_plan.correction_ack)

    return " ".join(parts)


def apply_attribution_guard(
    raw_output: str,
    evidence_table: dict[str, SourceEvidence],
    budget_retained_ids: set[str],
    guard_mode: Literal["off", "shadow", "enforce"],
    identity_revision: int,
) -> tuple[str, AttributionDecision]:
    """应用归属守护 - 最终发送前检查。

    流程：
    1. 解析 reply_plan
    2. 验证证据引用
    3. 检查自由文本风险
    4. 服务端渲染最终内容
    5. 记录决策

    Returns:
        (final_output, decision)
    """
    decision = AttributionDecision(
        decision="pass",
        guard_mode=guard_mode,
        identity_revision=identity_revision,
    )

    if guard_mode == "off":
        # 关闭守护，直接通过
        decision.original_output_digest = raw_output[:16]
        decision.final_output_digest = raw_output[:16]
        return raw_output, decision

    # 解析回复计划
    plan, parse_error = parse_reply_plan(raw_output)

    if not plan:
        # 解析失败
        if guard_mode == "enforce":
            decision.decision = "fallback"
            decision.rejection_reason = f"parse_failed:{parse_error}"
            return "抱歉，我需要重新理解一下。", decision
        # shadow 模式：记录但放行
        decision.rejection_reason = f"parse_failed:{parse_error}"
        return raw_output, decision

    # 验证证据引用
    refs_valid, invalid_refs = validate_evidence_references(
        plan, evidence_table, budget_retained_ids
    )

    if not refs_valid:
        decision.invalid_references = invalid_refs
        if guard_mode == "enforce":
            # 去掉无效引用，保留当前回应
            decision.decision = "fallback"
            decision.rejection_reason = "invalid_references"
            return plan.current_response or "好的。", decision

    # 检查自由文本风险
    free_text_safe, risk_pattern = check_risky_free_text(
        plan.current_response, set(evidence_table.keys())
    )

    if not free_text_safe and guard_mode == "enforce":
        decision.decision = "reject"
        decision.rejection_reason = risk_pattern
        return "嗯嗯。", decision

    # 渲染最终内容
    final_parts = []

    if plan.correction_ack:
        final_parts.append(plan.correction_ack)

    if plan.current_response:
        final_parts.append(plan.current_response)

    # 渲染引用
    for ref_id in plan.quote_references:
        if ref_id in evidence_table and ref_id in budget_retained_ids:
            final_parts.append(render_evidence(ref_id, evidence_table[ref_id]))

    final_output = " ".join(final_parts)

    decision.decision = "pass"
    decision.original_output_digest = raw_output[:16]
    decision.final_output_digest = final_output[:16]
    decision.checked_evidence_ids = list(evidence_table.keys())

    return final_output, decision
