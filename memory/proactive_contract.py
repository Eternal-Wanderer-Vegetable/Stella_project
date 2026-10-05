# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动验证合同 - 候选验证的来源证据与服务端问题模板。

按计划 §6.5，主动验证不允许模型自由改写事实主体或引用不相关背景。
服务端从候选和来源消息生成合同，模型只能选择预设的问题变体。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class VerificationContract:
    """候选验证合同 - 绑定来源证据与可验证问题。
    
    Attributes:
        candidate_id: 候选 ID
        recording_author_id: 记录作者（可能不等于事实主体）
        fact_subject_id: 事实主体 UID
        fact_object_id: 事实对象 UID（若适用）
        predicate_type: 谓词类型（self_alias / address_preference / relationship）
        polarity: 极性（positive / negative / unknown）
        source_conversation_key: 来源会话规范键
        source_row_ids: 来源消息行 ID 列表
        candidate_content_digest: 候选内容摘要（sha256 前16字符）
        contract_version: 合同版本（用于追踪格式变化）
        question_variants: 服务端生成的问题变体列表
        bridge_event_requirement: 是否需要桥接事件（需要时模型必须提供）
    """
    
    candidate_id: int
    recording_author_id: int
    fact_subject_id: int
    fact_object_id: int | None
    predicate_type: Literal["self_alias", "address_preference", "relationship", "attribute", "other"]
    polarity: Literal["positive", "negative", "unknown"]
    source_conversation_key: str
    source_row_ids: list[int]
    candidate_content_digest: str
    contract_version: str = "2026-10-05.1"
    question_variants: list[QuestionVariant] = field(default_factory=list)
    bridge_event_requirement: bool = False


@dataclass
class QuestionVariant:
    """服务端生成的问题变体。
    
    模型只能选择一个 variant_id，不能自由改写主体或对象。
    """
    
    variant_id: str  # 例如 "variant_A"
    question_template: str  # 例如 "你平时会叫{object_display_name}{candidate_term}吗？"
    filled_question: str  # 实际填充后的问题文本
    requires_bridge: bool  # 此变体是否需要桥接事件


@dataclass
class BridgeEvidence:
    """桥接事件证据 - 用于验证模型提供的近期事件确实属于目标用户。
    
    Attributes:
        target_user_id: 目标用户 UID
        conversation_key: 会话键
        recent_message_ids: 目标用户近期消息 ID（可验证集合）
        recent_event_digests: 近期事件摘要（用于模糊匹配）
    """
    
    target_user_id: int
    conversation_key: str
    recent_message_ids: list[int]
    recent_event_digests: list[str]


def validate_contract_consistency(
    contract: VerificationContract,
    current_candidate: dict,
) -> tuple[bool, str]:
    """验证合同与当前候选一致性。
    
    在发送前检查：
    - candidate_id 匹配
    - 内容 digest 未变化
    - 来源消息仍然存在
    
    Returns:
        (is_valid, reason)
    """
    if contract.candidate_id != current_candidate.get("id"):
        return False, "candidate_id_mismatch"
    
    # TODO: 实际实现需要计算当前候选内容的 digest 并比对
    # if contract.candidate_content_digest != compute_digest(current_candidate["content"]):
    #     return False, "content_changed"
    
    return True, "ok"


def can_generate_question(
    contract: VerificationContract,
    source_messages_available: bool,
) -> tuple[bool, str]:
    """判断是否可以为此合同生成问题。
    
    不可发送的情况：
    - 来源消息已清理
    - 事实主体不明
    - 谓词类型不支持
    - 极性未知且无法询问
    
    Returns:
        (can_send, skip_reason)
    """
    if not source_messages_available:
        return False, "source_missing"
    
    if contract.fact_subject_id <= 0:
        return False, "subject_unknown"
    
    if contract.predicate_type == "other":
        return False, "predicate_unsupported"
    
    if contract.polarity == "unknown" and not contract.question_variants:
        return False, "no_valid_template"
    
    return True, "ok"


def validate_bridge_event(
    bridge: BridgeEvidence | None,
    contract: VerificationContract,
) -> tuple[bool, str]:
    """验证桥接事件是否合法（R5 §6.5）。
    
    桥接事件要求：
    - 必须属于目标用户
    - 必须在近期消息范围内
    - 不能引用无关用户的动作
    
    Returns:
        (is_valid, reason)
    """
    if not contract.bridge_event_requirement:
        # 不需要桥接，直接通过
        return True, "not_required"
    
    if bridge is None:
        return False, "bridge_missing"
    
    if bridge.target_user_id != contract.fact_object_id:
        return False, "bridge_target_mismatch"
    
    if not bridge.recent_message_ids:
        return False, "bridge_no_evidence"
    
    return True, "ok"


def select_question_variant(
    contract: VerificationContract,
    has_bridge: bool,
) -> QuestionVariant | None:
    """选择合适的问题变体（R5 §6.5）。
    
    选择规则：
    - 如果有桥接事件，优先选择需要桥接的变体
    - 如果没有桥接，只能选择不需要桥接的变体
    - 如果没有合法变体，返回 None（跳过发送）
    """
    if not contract.question_variants:
        return None
    
    # 优先选择匹配桥接要求的变体
    for variant in contract.question_variants:
        if variant.requires_bridge == has_bridge:
            return variant
    
    # 如果没有完美匹配，且不需要桥接，选择第一个不需要桥接的变体
    if not has_bridge:
        for variant in contract.question_variants:
            if not variant.requires_bridge:
                return variant
    
    return None
