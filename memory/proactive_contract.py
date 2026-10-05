# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动验证合同 - 候选验证的来源证据与服务端问题模板。

按计划 §6.5，主动验证不允许模型自由改写事实主体或引用不相关背景。
服务端从候选和来源消息生成合同，模型只能选择预设的问题变体。

复核整改（F11）：

- ``validate_contract_consistency`` 真正重算候选内容 digest（与整合器
  fact_key 同一归一化）、检查候选仍在册、逐条核验来源行存在且作者一致——
  「同 ID 改写内容」「来源为空」不再放行；
- 合同显式绑定 ``selected_target_user_id``；``validate_bridge_event`` 比较
  桥接主体与**选定目标**（不是事实对象），消息 ID 必须在服务端构建的
  近期消息集合内——Nox 主体的真实承接不再被拒，伪造桥接不再被收。
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from typing import Literal


def compute_candidate_digest(candidate: dict) -> str:
    """候选内容 digest：与整合器 fact_key 同一归一化（type + 小心去空内容）。"""
    type_ = str(candidate.get("type") or "")
    content = str(candidate.get("content") or "")
    return hashlib.sha256(
        f"{type_}:{content.strip().lower()}".encode()
    ).hexdigest()[:16]


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
class VerificationContract:
    """候选验证合同 - 绑定来源证据与可验证问题。

    Attributes:
        candidate_id: 候选 ID
        recording_author_id: 记录作者（可能不等于事实主体）
        fact_subject_id: 事实主体 UID
        fact_object_id: 事实对象 UID（若适用）
        selected_target_user_id: **选定发送目标**（pick_target 的产出；桥接
            与发送一致性都对这个字段校验，复核 F11 修复）
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
    selected_target_user_id: int = 0
    contract_version: str = "2026-10-05.2"
    question_variants: list[QuestionVariant] = field(default_factory=list)
    bridge_event_requirement: bool = False


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
    recent_event_digests: list[str] = field(default_factory=list)


def validate_contract_consistency(
    contract: VerificationContract,
    current_candidate: dict,
    conn: sqlite3.Connection | None = None,
) -> tuple[bool, str]:
    """验证合同与当前候选一致性（发送前必经；复核 F11 落地）。

    检查：
    - candidate_id 匹配
    - 内容 digest 重算比对（同 ID 改写内容 → content_changed）
    - 候选仍在册（DEPRECATED/REVOKED 拒绝）
    - 目标已绑定
    - 来源行逐条存在、作者一致、非 Bot（conn 提供时服务端查证）

    Returns:
        (is_valid, reason)
    """
    if contract.candidate_id != current_candidate.get("id"):
        return False, "candidate_id_mismatch"

    digest = compute_candidate_digest(current_candidate)
    if contract.candidate_content_digest and digest != contract.candidate_content_digest:
        return False, "content_changed"

    status = str(current_candidate.get("status") or "").strip().lower()
    if status in ("deprecated", "revoked", "invalid"):
        return False, "candidate_inactive"

    if contract.selected_target_user_id <= 0:
        return False, "target_unbound"

    if conn is not None and contract.source_row_ids:
        try:
            for row_id in contract.source_row_ids:
                row = conn.execute(
                    "SELECT user_id, source_kind FROM group_messages WHERE id = ?",
                    (int(row_id),),
                ).fetchone()
                if row is None:
                    return False, f"source_row_missing:{row_id}"
                author, source_kind = str(row[0] or ""), str(row[1] or "")
                if source_kind == "BOT_SELF":
                    return False, f"source_is_bot:{row_id}"
                if author and author != str(contract.recording_author_id):
                    return False, f"source_author_mismatch:{row_id}"
        except sqlite3.OperationalError as e:
            return False, f"source_lookup_failed:{e}"

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
    server_recent: dict[int, str] | None = None,
) -> tuple[bool, str]:
    """验证桥接事件是否合法（复核 F11 修复）。

    桥接事件要求：
    - 必须属于**选定发送目标**（不是事实对象——14:09 现场的错位比较）
    - 必须在近期消息范围内
    - 消息 ID 必须出现在服务端核验集合中（编造 ID/摘要拒绝）

    Args:
        bridge: 模型声明的桥接证据
        contract: 当前合同
        server_recent: 服务端构建的 {消息行ID: 内容digest}（同轮同会话、
            作者=选定目标）；None 时跳过集合核验（调用方自担）

    Returns:
        (is_valid, reason)
    """
    if not contract.bridge_event_requirement:
        # 不需要桥接，直接通过
        return True, "not_required"

    if bridge is None:
        return False, "bridge_missing"

    if bridge.target_user_id != contract.selected_target_user_id:
        return False, "bridge_target_mismatch"

    if not bridge.recent_message_ids:
        return False, "bridge_no_evidence"

    if server_recent is not None:
        for message_id in bridge.recent_message_ids:
            if int(message_id) not in server_recent:
                return False, f"bridge_message_unverified:{message_id}"
        if bridge.recent_event_digests:
            for digest in bridge.recent_event_digests:
                if digest not in server_recent.values():
                    return False, f"bridge_digest_unverified:{digest}"

    return True, "ok"


def select_question_variant(
    contract: VerificationContract,
    has_bridge: bool,
) -> QuestionVariant | None:
    """选择合适的问题变体（计划 §6.5）。

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
