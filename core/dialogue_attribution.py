# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""对话归属约束 - 回复中的作者/对象来源验证与服务端渲染。

按计划 §6.6，普通生成必须基于可信来源证据，不能让模型自由声称
未经验证的过去事实。历史引用经服务端渲染，确保作者/对象正确。

复核整改（F12）：

- ``parse_reply_plan`` 是真实协议解析器（versioned <reply_plan> 块），
  不再是 not_implemented 占位；malformed / 未知标签 / 多槽位都给出
  结构化错误；
- ``validate_evidence_references`` 校验**类型与可信度**：quote 只能引用
  message 证据、fact 只能引用 is_verified 的事实；
- ``render_evidence`` 带作者边界：消息引用渲染为「{作者}说过：「原文」」，
  作者展示名由服务端解析，模型供给的作者/正文一律不进渲染；
- correction_ack 是**开关不是内容**：承认文本由服务端从可信纠正证据按
  受限模板生成，模型无法借该槽输出任意（攻击性）句子；
- 风险词表补充 13:31 现场形状（「刚才是谁说」等）；词法仍只是可测防线，
  语义保证来自解析 + 服务端渲染的组合。
"""

from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Literal

# 回复计划协议版本（与 prompt_builder 注入的指令一致）
REPLY_PLAN_PROTOCOL_VERSION = "2026-10-05.2"
REPLY_ENVELOPE_PROTOCOL_VERSION = "2026-10-08.1"
_REPLY_ENVELOPE_SCHEMA_VERSION = 1
_MAX_REPLY_ENVELOPE_BYTES = 16 * 1024

_REPLY_PLAN_BLOCK = re.compile(
    r"<reply_plan\s+version=\"(?P<version>[\w.\-]+)\">(?P<body>.*?)</reply_plan>",
    re.DOTALL,
)
_INNER_TAG = re.compile(
    r"<(?P<close>/)?(?P<name>now|ref|fact|ack)"
    r"(?P<attrs>(?:\s+[a-zA-Z_]+=\"[^\"]*\")*)\s*(?P<selfclose>/)?>"
)
_ATTR = re.compile(r"([a-zA-Z_]+)=\"([^\"]*)\"")


@dataclass
class SourceEvidence:
    """来源证据 - 可验证的历史消息或已验证事实。

    Attributes:
        evidence_id: 证据 ID（用于模型引用）
        evidence_type: 证据类型（message / verified_fact / current_correction）
        author_id: 作者 UID
        object_id: 对象 UID（若适用）
        original_text: 原文（消息）或事实模板
        conversation_key: 会话键
        source_row_id: 来源行 ID
        timestamp: 时间戳
        polarity: 极性（positive / negative / neutral）
        is_verified: 是否已验证（事实）
        author_display: 作者可信展示名（服务端解析；渲染作者边界用）
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
    author_display: str = ""


@dataclass
class ReplyPlan:
    """结构化回复计划 - 模型输出的分解意图。

    按计划 §6.6，回复分为几个部分：
    - current_response: 自由口语回应当前输入（风险词检查覆盖）
    - quote_references: 引用历史原话（只提供 evidence_id；服务端渲染）
    - verified_fact_references: 引用已验证事实（只提供 evidence_id）
    - correction_ack: **开关**——是否附带纠正承认（内容由服务端模板生成）
    """

    current_response: str = ""
    quote_references: list[str] = field(default_factory=list)  # evidence_id 列表
    verified_fact_references: list[str] = field(default_factory=list)
    correction_ack: bool = False
    protocol_version: str = REPLY_PLAN_PROTOCOL_VERSION


@dataclass(frozen=True)
class ReplyEnvelope:
    """唯一解析后的回复对象；模型不能在 typed slots 中提供作者或原文。"""

    protocol_version: str
    kind: Literal["social", "quote", "facts", "correction", "clarify", "skip"]
    current: str = ""
    quote_evidence_ids: tuple[str, ...] = ()
    fact_evidence_ids: tuple[str, ...] = ()
    correction_ack: bool = False
    target_user_id: str = ""
    thought: str = ""
    action: str = "NONE"
    legacy: bool = False

    def to_projection(self) -> dict:
        """返回可跨 runtime boundary 的 JSON 值。"""
        return {
            "schema_version": _REPLY_ENVELOPE_SCHEMA_VERSION,
            "protocol_version": self.protocol_version,
            "kind": self.kind,
            "current": self.current,
            "quote_evidence_ids": list(self.quote_evidence_ids),
            "fact_evidence_ids": list(self.fact_evidence_ids),
            "correction_ack": self.correction_ack,
            "target_user_id": self.target_user_id,
            "thought": self.thought,
            "action": self.action,
            "legacy": self.legacy,
        }


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
    # Guard 只验证结构、来源引用与显式风险；自由社会回应不因此成为事实认证。
    semantic_status: str = "semantic_unverified"
    verified: bool = False


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


# ── 投影序列化（复核 F1：证据表过 ctx/跨进程桥） ────────────────────────


def evidence_projection(evidence_table: dict[str, SourceEvidence]) -> dict:
    """证据表 → JSON 安全 dict（ctx.attribution_evidence）。"""
    return {eid: vars(ev) for eid, ev in (evidence_table or {}).items()}


def evidence_table_from_projection(data: dict | None) -> dict[str, SourceEvidence]:
    """ctx.attribution_evidence → 证据表（旧/空投影返回空表，guard 按 off 处理）。"""
    table: dict[str, SourceEvidence] = {}
    for eid, raw in (data or {}).items():
        try:
            table[str(eid)] = SourceEvidence(
                evidence_id=str(raw.get("evidence_id") or eid),
                evidence_type=raw.get("evidence_type") or "message",
                author_id=int(raw.get("author_id") or 0),
                object_id=raw.get("object_id"),
                original_text=str(raw.get("original_text") or ""),
                conversation_key=str(raw.get("conversation_key") or ""),
                source_row_id=raw.get("source_row_id"),
                timestamp=str(raw.get("timestamp") or ""),
                polarity=raw.get("polarity") or "neutral",
                is_verified=bool(raw.get("is_verified")),
                author_display=str(raw.get("author_display") or ""),
            )
        except Exception:
            continue
    return table


def protocol_instructions(
    evidence_table: dict[str, SourceEvidence],
    budget_retained_ids: set[str],
    *,
    risk_context: dict | None = None,
) -> str:
    """生成唯一 ReplyEnvelope 协议及预算实际保留的证据表。"""
    usable = [
        ev for eid, ev in evidence_table.items() if eid in budget_retained_ids
    ]
    lines = [
        f"本轮回复协议（只允许一个 response 根元素，禁止块外文本；版本固定为 {REPLY_ENVELOPE_PROTOCOL_VERSION}）：",
        '<response version="2026-10-08.1">',
        "<thought>一句简短诊断；不作为回复发送</thought>",
        "<action>NONE</action>",
        '<reply kind="social"><current>对当前输入的正常回应</current></reply>',
        "</response>",
        "kind 只能为 social、quote、facts、correction、clarify、skip；social.current 只回应当前输入，",
        "不得声称未在服务端证据中支持的历史事实。quote/fact 只能填写下方证据 ID，作者、原文、对象由服务端渲染。",
        "correction 只能输出 <ack/>；clarify 和 skip 不带其他槽。不得输出作者名、用户 ID 或引用原文作为伪造槽。",
    ]
    if usable:
        lines.append("可用服务端证据（只可引用此表中预算保留的 ID）：")
    for ev in usable:
        if ev.evidence_type == "message":
            author = ev.author_display or f"用户({ev.author_id})"
            lines.append(
                f'- [msg] id={ev.evidence_id} 作者={html.escape(author, quote=False)}：'
                f'{html.escape(ev.original_text, quote=False)}'
            )
        elif ev.evidence_type == "verified_fact":
            lines.append(
                f"- [fact] id={ev.evidence_id}（已验证）："
                f"{html.escape(ev.original_text, quote=False)}"
            )
        else:
            author = ev.author_display or f"用户({ev.author_id})"
            lines.append(
                f"- [correction] id={ev.evidence_id} "
                f"作者={html.escape(author, quote=False)}："
                f"{html.escape(ev.original_text, quote=False)}"
            )
    risk = risk_context if isinstance(risk_context, dict) else {}
    if risk.get("target_resolution") == "exact" and risk.get("target_user_id"):
        lines.append(f"当前可信引用对象 ID 为 {risk['target_user_id']}；不得改写为其他对象。")
    lines.append(
        '引用示例：<reply kind="quote"><quote evidence_id="msg_3"/></reply>；'
        '事实示例：<reply kind="facts"><fact evidence_id="fact_1"/></reply>。'
        "协议错误或证据不足时由服务端转为澄清，不要在 XML 外补充说明。"
    )
    return "\n".join(lines)


def parse_reply_plan(raw_output: str) -> tuple[ReplyPlan | None, str]:
    """解析模型输出中的 versioned reply_plan（复核 F12：真实解析器）。

    协议（prompt 侧由 prompt_builder 注入）::

        <reply_plan version="2026-10-05.2">
        <now>自由口语回应</now>
        <ref id="msg_3"/>
        <fact id="fact_1"/>
        <ack/>
        </reply_plan>

    严格规则：块缺失 / 版本不符 / 多个 now / now 未闭合 / ref/fact 缺 id /
    出现未知标签 → (None, 原因)。块外文本（thought/action XML 等）忽略。

    Returns:
        (parsed_plan, error_reason)
    """
    text = raw_output or ""
    block = _REPLY_PLAN_BLOCK.search(text)
    if not block:
        return None, "reply_plan_not_found"
    version = block.group("version")
    if version != REPLY_PLAN_PROTOCOL_VERSION:
        return None, f"unsupported_version:{version}"
    body = block.group("body")
    plan = ReplyPlan(protocol_version=version)

    consumed: list[tuple[int, int]] = []
    now_count = 0
    for m in _INNER_TAG.finditer(body):
        name = m.group("name")
        closing = bool(m.group("close"))
        selfclose = bool(m.group("selfclose"))
        if closing:
            consumed.append(m.span())
            continue
        attrs = dict(_ATTR.findall(m.group("attrs") or ""))
        if name == "now":
            now_count += 1
            if now_count > 1:
                return None, "multiple_current_response"
            if selfclose:
                return None, "malformed_now_tag"
            close_tag = "</now>"
            end = body.find(close_tag, m.end())
            if end == -1:
                return None, "unclosed_now_tag"
            plan.current_response = body[m.end():end].strip()
            consumed.extend([m.span(), (m.end(), end), (end, end + len(close_tag))])
        elif name == "ref":
            evidence_id = attrs.get("id", "")
            if not evidence_id:
                return None, "ref_without_id"
            plan.quote_references.append(evidence_id)
            consumed.append(m.span())
        elif name == "fact":
            evidence_id = attrs.get("id", "")
            if not evidence_id:
                return None, "fact_without_id"
            plan.verified_fact_references.append(evidence_id)
            consumed.append(m.span())
        else:  # ack
            if not selfclose:
                end = body.find("</ack>", m.end())
                if end == -1:
                    return None, "unclosed_ack_tag"
                consumed.extend([m.span(), (m.end(), end), (end, end + len("</ack>"))])
            else:
                consumed.append(m.span())
            plan.correction_ack = True

    # 未消费部分不允许再有任何标签（未知协议即 malformed）
    leftover = "".join(
        body[start:end]
        for start, end in _subtract_spans(len(body), consumed)
    )
    if "<" in leftover or ">" in leftover:
        return None, "unknown_tag_in_plan"

    return plan, ""


def _tree_within_protocol_limits(root: ET.Element) -> bool:
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    seen = 0
    while stack:
        node, depth = stack.pop()
        seen += 1
        if depth > 8 or seen > 64:
            return False
        stack.extend((child, depth + 1) for child in list(node))
    return True


def _valid_action(value: str) -> bool:
    return value in {"NONE", "REPLY", "WAIT"} or bool(
        re.fullmatch(r"QUERY_MEMORY:\s*[^<>\r\n]{1,112}", value)
    )


def _parse_legacy_envelope(raw: str) -> tuple[ReplyEnvelope | None, str]:
    """解析受限旧 XML 形状；只兼容已知标签，不提取任意块外台词。"""
    try:
        wrapper = ET.fromstring(f"<legacy-root>{raw}</legacy-root>")
    except ET.ParseError:
        return None, "legacy_malformed_xml"
    if not _tree_within_protocol_limits(wrapper) or (wrapper.text or "").strip():
        return None, "legacy_protocol_limits"
    children = list(wrapper)
    if any((child.tail or "").strip() for child in children):
        return None, "legacy_outside_text"
    names = [child.tag for child in children]
    if any(name not in {"thought", "action", "reply", "reply_plan"} for name in names):
        return None, "legacy_unknown_tag"
    if any(names.count(name) > 1 for name in {"thought", "action", "reply", "reply_plan"}):
        return None, "legacy_duplicate_slot"
    if "reply" in names and "reply_plan" in names:
        return None, "legacy_conflicting_reply_slots"
    thought_node = next((node for node in children if node.tag == "thought"), None)
    action_node = next((node for node in children if node.tag == "action"), None)
    thought = (thought_node.text or "").strip() if thought_node is not None else ""
    action = (action_node.text or "NONE").strip() if action_node is not None else "NONE"
    if any(node.attrib or list(node) for node in (thought_node, action_node) if node is not None):
        return None, "legacy_nested_slot"
    if not _valid_action(action):
        return None, "legacy_unknown_action"

    plan_node = next((node for node in children if node.tag == "reply_plan"), None)
    if plan_node is not None:
        plan, error = parse_reply_plan(raw)
        if plan is None:
            return None, error
        kind = (
            "correction" if plan.correction_ack else
            "quote" if plan.quote_references else
            "facts" if plan.verified_fact_references else "social"
        )
        return ReplyEnvelope(
            protocol_version=plan.protocol_version,
            kind=kind,
            current=plan.current_response,
            quote_evidence_ids=tuple(plan.quote_references),
            fact_evidence_ids=tuple(plan.verified_fact_references),
            correction_ack=plan.correction_ack,
            thought=thought,
            action=action,
            legacy=True,
        ), ""

    reply_node = next((node for node in children if node.tag == "reply"), None)
    if reply_node is None or reply_node.attrib or list(reply_node):
        return None, "legacy_reply_missing_or_invalid"
    current = (reply_node.text or "").strip()
    if not current:
        return None, "legacy_reply_empty"
    return ReplyEnvelope(
        protocol_version="legacy-reply-v1", kind="social", current=current,
        thought=thought, action=action, legacy=True,
    ), ""


def parse_reply_envelope(raw_output: str) -> tuple[ReplyEnvelope | None, str]:
    """解析唯一 versioned ReplyEnvelope，拒绝 DTD、实体、额外台词与未知槽。

    只保留一个有界的旧 XML adapter，便于灰度期间识别历史格式；普通文本、
    块外内容和畸形回复都返回错误，调用方必须走受限服务器退路，不能回送 raw。
    """
    raw = str(raw_output or "")
    encoded = raw.encode("utf-8")
    if len(encoded) > _MAX_REPLY_ENVELOPE_BYTES:
        return None, "output_too_large"
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", raw, flags=re.IGNORECASE):
        return None, "forbidden_xml_declaration"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return _parse_legacy_envelope(raw)
    if root.tag != "response":
        return _parse_legacy_envelope(raw)
    if not _tree_within_protocol_limits(root):
        return None, "protocol_limits_exceeded"
    if root.attrib != {"version": REPLY_ENVELOPE_PROTOCOL_VERSION}:
        version = str(root.attrib.get("version") or "")
        return None, f"unsupported_version:{version}"
    if (root.text or "").strip():
        return None, "text_outside_reply_slots"
    children = list(root)
    if [child.tag for child in children] != ["thought", "action", "reply"]:
        return None, "invalid_root_slots"
    if any((child.tail or "").strip() for child in children):
        return None, "text_outside_reply_slots"

    thought_node, action_node, reply_node = children
    if any(node.attrib or list(node) for node in (thought_node, action_node)):
        return None, "invalid_diagnostic_slot"
    thought = (thought_node.text or "").strip()
    action = (action_node.text or "").strip()
    if len(thought) > 512 or not _valid_action(action):
        return None, "invalid_diagnostic_value"

    allowed_kinds = {"social", "quote", "facts", "correction", "clarify", "skip"}
    if set(reply_node.attrib) - {"kind", "target_user_id"}:
        return None, "unknown_reply_attribute"
    kind = str(reply_node.attrib.get("kind") or "")
    target_user_id = str(reply_node.attrib.get("target_user_id") or "")
    if kind not in allowed_kinds:
        return None, "unknown_reply_kind"
    if target_user_id and (not target_user_id.isdigit() or len(target_user_id) > 32):
        return None, "invalid_target_user_id"
    if (reply_node.text or "").strip():
        return None, "text_outside_typed_slots"

    current = ""
    current_seen = False
    quote_ids: list[str] = []
    fact_ids: list[str] = []
    correction_ack = False
    for child in list(reply_node):
        if (
            (child.tail or "").strip()
            or (child.tag != "current" and (child.text or "").strip())
            or list(child)
        ):
            return None, "invalid_typed_slot_content"
        if child.tag == "current":
            if child.attrib or current_seen:
                return None, "duplicate_or_attributed_current"
            current_seen = True
            current = (child.text or "").strip()
        elif child.tag in {"quote", "fact"}:
            if set(child.attrib) != {"evidence_id"}:
                return None, f"{child.tag}_without_evidence_id"
            evidence_id = str(child.attrib.get("evidence_id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", evidence_id):
                return None, f"{child.tag}_invalid_evidence_id"
            target_ids = quote_ids if child.tag == "quote" else fact_ids
            if evidence_id in target_ids:
                return None, "duplicate_evidence_id"
            target_ids.append(evidence_id)
        elif child.tag == "ack":
            if child.attrib or correction_ack or (child.text or "").strip():
                return None, "invalid_ack_slot"
            correction_ack = True
        else:
            return None, "unknown_typed_slot"

    if kind == "social" and (not current or quote_ids or fact_ids or correction_ack):
        return None, "invalid_social_slots"
    if kind == "quote" and (not quote_ids or fact_ids or correction_ack):
        return None, "invalid_quote_slots"
    if kind == "facts" and (not fact_ids or quote_ids or correction_ack):
        return None, "invalid_fact_slots"
    if kind == "correction" and (not correction_ack or quote_ids or fact_ids):
        return None, "invalid_correction_slots"
    if kind in {"clarify", "skip"} and (current or quote_ids or fact_ids or correction_ack):
        return None, f"invalid_{kind}_slots"

    return ReplyEnvelope(
        protocol_version=REPLY_ENVELOPE_PROTOCOL_VERSION,
        kind=kind, current=current, quote_evidence_ids=tuple(quote_ids),
        fact_evidence_ids=tuple(fact_ids), correction_ack=correction_ack,
        target_user_id=target_user_id, thought=thought, action=action,
    ), ""


def reply_envelope_from_projection(value: object) -> tuple[ReplyEnvelope | None, str]:
    """重建并校验 JSON 投影中的 ReplyEnvelope，拒绝未知/篡改槽位。"""
    fields = {
        "schema_version", "protocol_version", "kind", "current",
        "quote_evidence_ids", "fact_evidence_ids", "correction_ack",
        "target_user_id", "thought", "action", "legacy",
    }
    if not isinstance(value, dict):
        return None, "invalid_envelope_projection"
    if set(value) != fields:
        return None, "unknown_envelope_projection_field"
    if (
        type(value.get("schema_version")) is not int
        or value.get("schema_version") != _REPLY_ENVELOPE_SCHEMA_VERSION
    ):
        return None, "invalid_envelope_projection"
    string_fields = ("protocol_version", "kind", "current", "target_user_id", "thought", "action")
    if any(not isinstance(value.get(name), str) for name in string_fields):
        return None, "invalid_envelope_projection"
    kind = value.get("kind")
    if kind not in {"social", "quote", "facts", "correction", "clarify", "skip"}:
        return None, "unknown_reply_kind"
    quote_ids = value.get("quote_evidence_ids")
    fact_ids = value.get("fact_evidence_ids")
    if not isinstance(quote_ids, list) or not isinstance(fact_ids, list):
        return None, "invalid_evidence_projection"
    if len(quote_ids) + len(fact_ids) > 60:
        return None, "too_many_evidence_slots"
    if any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", item)
        for item in [*quote_ids, *fact_ids]
    ):
        return None, "invalid_evidence_projection"
    if len(set(quote_ids)) != len(quote_ids) or len(set(fact_ids)) != len(fact_ids):
        return None, "duplicate_evidence_id"
    if type(value.get("correction_ack")) is not bool:
        return None, "invalid_correction_projection"
    if type(value.get("legacy")) is not bool:
        return None, "invalid_legacy_projection"
    if (
        len(value["current"].encode("utf-8")) > _MAX_REPLY_ENVELOPE_BYTES
        or len(value["thought"]) > 512
    ):
        return None, "projection_value_too_large"
    try:
        envelope = ReplyEnvelope(
            protocol_version=str(value.get("protocol_version") or ""),
            kind=kind,
            current=str(value.get("current") or ""),
            quote_evidence_ids=tuple(str(item) for item in quote_ids),
            fact_evidence_ids=tuple(str(item) for item in fact_ids),
            correction_ack=value.get("correction_ack") is True,
            target_user_id=str(value.get("target_user_id") or ""),
            thought=str(value.get("thought") or ""),
            action=str(value.get("action") or ""),
            legacy=value.get("legacy") is True,
        )
    except (TypeError, ValueError):
        return None, "invalid_envelope_projection"
    if envelope.legacy:
        if envelope.protocol_version not in {REPLY_PLAN_PROTOCOL_VERSION, "legacy-reply-v1"}:
            return None, "unsupported_version"
    elif envelope.protocol_version != REPLY_ENVELOPE_PROTOCOL_VERSION:
        return None, "unsupported_version"
    if not _valid_action(envelope.action) or len(envelope.thought) > 512:
        return None, "invalid_diagnostic_value"
    if envelope.target_user_id and (
        not envelope.target_user_id.isdigit() or len(envelope.target_user_id) > 32
    ):
        return None, "invalid_target_user_id"
    if not envelope.legacy:
        valid_slots = {
            "social": bool(envelope.current)
            and not envelope.quote_evidence_ids and not envelope.fact_evidence_ids
            and not envelope.correction_ack,
            "quote": bool(envelope.quote_evidence_ids)
            and not envelope.fact_evidence_ids and not envelope.correction_ack,
            "facts": bool(envelope.fact_evidence_ids)
            and not envelope.quote_evidence_ids and not envelope.correction_ack,
            "correction": envelope.correction_ack
            and not envelope.quote_evidence_ids and not envelope.fact_evidence_ids,
            "clarify": not envelope.current and not envelope.quote_evidence_ids
            and not envelope.fact_evidence_ids and not envelope.correction_ack,
            "skip": not envelope.current and not envelope.quote_evidence_ids
            and not envelope.fact_evidence_ids and not envelope.correction_ack,
        }
        if not valid_slots.get(envelope.kind, False):
            return None, "invalid_typed_reply_projection"
    return envelope, ""


def _subtract_spans(total: int, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """返回 spans 覆盖之外的区间。"""
    spans = sorted(spans)
    result: list[tuple[int, int]] = []
    pos = 0
    for start, end in spans:
        if start < pos:
            continue
        if start > pos:
            result.append((pos, start))
        pos = max(pos, end)
    if pos < total:
        result.append((pos, total))
    return result


def validate_evidence_references(
    plan: ReplyPlan,
    available_evidence: dict[str, SourceEvidence],
    budget_retained_ids: set[str],
) -> tuple[bool, list[str]]:
    """验证引用的证据是否合法（复核 F12：类型与可信度校验）。

    检查：
    - 引用的 evidence_id 必须在可用证据集与预算保留范围内
    - quote 引用只能指向 message 证据（原话边界由服务端渲染）
    - fact 引用只能指向 is_verified 的 verified_fact 证据
      （普通消息冒充已验证事实拒绝）

    Returns:
        (all_valid, invalid_reference_ids)
    """
    invalid = []

    for ref_id in plan.quote_references:
        if ref_id not in available_evidence:
            invalid.append(f"{ref_id}:not_in_evidence")
            continue
        if ref_id not in budget_retained_ids:
            invalid.append(f"{ref_id}:not_in_budget")
            continue
        if available_evidence[ref_id].evidence_type != "message":
            invalid.append(f"{ref_id}:quote_requires_message")

    for ref_id in plan.verified_fact_references:
        if ref_id not in available_evidence:
            invalid.append(f"{ref_id}:not_in_evidence")
            continue
        if ref_id not in budget_retained_ids:
            invalid.append(f"{ref_id}:not_in_budget")
            continue
        evidence = available_evidence[ref_id]
        if evidence.evidence_type != "verified_fact" or not evidence.is_verified:
            invalid.append(f"{ref_id}:fact_requires_verified")

    return len(invalid) == 0, invalid


def render_evidence(
    evidence_id: str,
    evidence: SourceEvidence,
) -> str:
    """服务端渲染证据为最终文本（复核 F12：作者边界）。

    消息引用渲染为「{作者}说过：「原文」」——作者展示名是服务端解析的
    可信值（author_display 为空时退回 UID），模型供给的作者/正文不进渲染。
    事实/纠正证据本身是服务端模板，原样使用。
    """
    if evidence.evidence_type == "message":
        author = evidence.author_display or f"用户({evidence.author_id})"
        return f"{author}说过：「{evidence.original_text}」"

    if evidence.evidence_type in ("verified_fact", "current_correction"):
        return evidence.original_text

    return ""


_CORRECTION_ACK_FALLBACK = "抱歉，刚才是我搞混了。"
_ATTRIBUTION_CLARIFY = "我不确定你指的是哪位或哪句话，可以再发一次原话吗？"


def render_correction_ack(evidence_table: dict[str, SourceEvidence]) -> str:
    """从可信纠正证据生成受限承认模板（复核 F12：ack 是开关不是内容）。"""
    for evidence in evidence_table.values():
        if evidence.evidence_type == "current_correction":
            author = evidence.author_display or f"用户({evidence.author_id})"
            return f"抱歉，刚才是我搞混了，{author}说得对。"
    return _CORRECTION_ACK_FALLBACK


def check_risky_free_text(
    text: str,
    available_evidence_ids: set[str],
) -> tuple[bool, str]:
    """检查自由文本中的风险表达。

    风险模式（有限词法防线，含 13:31 现场形状）：
    - 把 Bot 原话翻成用户说的（「谁说我脏手」类作者倒置）
    - 指责用户失忆/甩锅
    - 明显的过去事实声称（"你之前说过..."）

    这是有限词法防线，无法完全证明语义正确；语义保证来自
    解析 + 服务端渲染的组合（计划 §6.6 边界声明）。

    Returns:
        (is_safe, risk_pattern)
    """
    risky_patterns = [
        "你之前说",
        "你刚才说",
        "你怎么忘了",
        "明明是你",
        "你装失忆",
        "装失忆",
        "甩锅",
        # 13:31 现场形状：「刚才是谁说我脏手来着？」
        "刚才是谁说",
        "谁说我",
        "我什么时候说过",
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
    """构建证据表（计划 §6.6）。

    优先级（高到低）：
    1. current_corrections - 当前轮次的纠正
    2. verified_facts - 已验证事实
    3. recent_messages - 近期消息（按时间倒序）

    Args:
        recent_messages: 近期消息列表（dict：id/text/author_id/author_display/
            object_id/row_id/conversation_key/timestamp）
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
            author_display=corr.get("author_display", ""),
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
            author_display=fact.get("author_display", ""),
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
            author_display=msg.get("author_display", ""),
        )
        unit_count += 1

    return evidence_table


def _decide(
    reply_plan: ReplyPlan | ReplyEnvelope | None,
    parse_error: str,
    evidence_table: dict[str, SourceEvidence],
    budget_retained_ids: set[str],
    guard_mode: Literal["off", "shadow", "enforce"],
    identity_revision: int,
    generation_epoch: int = 0,
    risk_context: dict | None = None,
) -> tuple[ReplyPlan | None, AttributionDecision, str]:
    """guard 共同决策核（legacy/native 两条路径共用，复核 F1 的前提）。

    返回 (生效 plan, 决策, 最终文本)。shadow 记录问题但产出与 enforce
    相同的**安全**文本（去掉无效引用/风险段），不原样放行危险内容。
    """
    decision = AttributionDecision(
        decision="pass",
        guard_mode=guard_mode,
        identity_revision=identity_revision,
        generation_epoch=generation_epoch,
    )

    envelope = reply_plan if isinstance(reply_plan, ReplyEnvelope) else None
    legacy = envelope.legacy if envelope is not None else True
    reply_kind = envelope.kind if envelope is not None else "social"
    if envelope is not None:
        reply_plan = ReplyPlan(
            current_response=envelope.current,
            quote_references=list(envelope.quote_evidence_ids),
            verified_fact_references=list(envelope.fact_evidence_ids),
            correction_ack=envelope.correction_ack,
            protocol_version=envelope.protocol_version,
        )

    if reply_plan is None:
        if guard_mode == "enforce":
            decision.decision = "fallback"
            decision.rejection_reason = f"parse_failed:{parse_error}"
            return None, decision, "抱歉，我需要重新理解一下。"
        decision.rejection_reason = f"parse_failed_shadow:{parse_error}"
        return None, decision, ""

    if (
        envelope is not None
        and envelope.legacy
        and envelope.protocol_version == "legacy-reply-v1"
        and guard_mode in {"shadow", "enforce"}
    ):
        # A bare legacy <reply> has no typed intent or evidence provenance. Do
        # not let its compatibility parse bypass the final attribution gate.
        decision.decision = "fallback"
        decision.rejection_reason = "legacy_untyped_reply_requires_clarification"
        decision.semantic_status = "deterministic_clarification"
        return reply_plan, decision, _ATTRIBUTION_CLARIFY

    if envelope is not None and not legacy:
        risk = risk_context if isinstance(risk_context, dict) else {}
        signals = {str(item) for item in (risk.get("signal_codes") or [])}
        target_resolution = str(risk.get("target_resolution") or "unknown")
        trusted_target = str(risk.get("target_user_id") or "")
        claimed_target = envelope.target_user_id
        target_mismatch = bool(
            claimed_target and (not trusted_target or claimed_target != trusted_target)
        )
        unresolved_reply_target = (
            "reply_relation" in signals
            and target_resolution in {"ambiguous", "unknown"}
        )
        current_correction = "current_correction" in signals
        server_high_risk = signals - {"current_correction", "reply_relation"}
        if reply_kind == "skip":
            decision.decision = "reject"
            decision.rejection_reason = "model_skip"
            return reply_plan, decision, ""
        if current_correction:
            decision.decision = "fallback"
            decision.rejection_reason = "server_current_correction_template"
            decision.semantic_status = "deterministic_render"
            return reply_plan, decision, render_correction_ack(evidence_table)
        if unresolved_reply_target or target_mismatch:
            decision.decision = "fallback"
            decision.rejection_reason = (
                "reply_target_unresolved" if unresolved_reply_target
                else "reply_target_mismatch"
            )
            decision.semantic_status = "deterministic_clarification"
            return reply_plan, decision, _ATTRIBUTION_CLARIFY
        if server_high_risk:
            decision.decision = "fallback"
            decision.rejection_reason = "server_attribution_risk:" + ",".join(sorted(server_high_risk))
            decision.semantic_status = "deterministic_clarification"
            return reply_plan, decision, _ATTRIBUTION_CLARIFY
        if reply_kind == "clarify":
            decision.decision = "fallback"
            decision.rejection_reason = "typed_clarification"
            decision.semantic_status = "deterministic_clarification"
            return reply_plan, decision, _ATTRIBUTION_CLARIFY
        if reply_kind == "correction":
            decision.decision = "fallback"
            decision.rejection_reason = "correction_without_server_evidence"
            decision.semantic_status = "deterministic_clarification"
            return reply_plan, decision, _ATTRIBUTION_CLARIFY
        if reply_kind in {"quote", "facts"}:
            all_valid, invalid_refs = validate_evidence_references(
                reply_plan, evidence_table, budget_retained_ids
            )
            decision.invalid_references = list(invalid_refs)
            if not all_valid:
                decision.decision = "fallback"
                decision.rejection_reason = "invalid_references"
                decision.semantic_status = "deterministic_clarification"
                return reply_plan, decision, _ATTRIBUTION_CLARIFY
            rendered = []
            ref_ids = (
                reply_plan.quote_references if reply_kind == "quote"
                else reply_plan.verified_fact_references
            )
            for ref_id in ref_ids:
                item = render_evidence(ref_id, evidence_table[ref_id])
                if item:
                    rendered.append(item)
            if not rendered:
                decision.decision = "fallback"
                decision.rejection_reason = "empty_verified_render"
                decision.semantic_status = "deterministic_clarification"
                return reply_plan, decision, _ATTRIBUTION_CLARIFY
            decision.decision = "fallback"
            decision.rejection_reason = "typed_server_render"
            decision.semantic_status = "deterministic_render"
            decision.checked_evidence_ids = list(ref_ids)
            return reply_plan, decision, " ".join(rendered)

    parts: list[str] = []
    all_valid, invalid_refs = validate_evidence_references(
        reply_plan, evidence_table, budget_retained_ids
    )
    decision.invalid_references = list(invalid_refs)

    if not all_valid:
        decision.rejection_reason = "invalid_references"

    is_safe, risk_pattern = check_risky_free_text(
        reply_plan.current_response, set(evidence_table.keys())
    )
    if not is_safe:
        decision.rejection_reason = decision.rejection_reason or risk_pattern

    if guard_mode == "enforce":
        if not is_safe:
            # 风险文本零容忍：reject 且不产出内容
            decision.decision = "reject"
            decision.rejection_reason = decision.rejection_reason or risk_pattern
            return reply_plan, decision, ""
        if not all_valid:
            # 复核计划 §6.6：去掉无证据引用，保留合格当前回应
            decision.decision = "fallback"
            return reply_plan, decision, reply_plan.current_response

    # 组装（shadow 与干净路径共用）：承认模板 → 安全当前回应 → 合法引用
    if reply_plan.correction_ack:
        parts.append(render_correction_ack(evidence_table))
    clean_now = reply_plan.current_response if is_safe else ""
    if clean_now:
        parts.append(clean_now)
    valid_refs = (
        set(reply_plan.quote_references + reply_plan.verified_fact_references)
        if all_valid
        else set()
    )
    for ref_id in reply_plan.quote_references + reply_plan.verified_fact_references:
        if ref_id in valid_refs and ref_id in evidence_table and ref_id in budget_retained_ids:
            rendered = render_evidence(ref_id, evidence_table[ref_id])
            if rendered:
                parts.append(rendered)

    decision.checked_evidence_ids = list(evidence_table.keys())
    return reply_plan, decision, " ".join(parts)


def apply_guard_decision(
    reply_plan: ReplyPlan | None,
    evidence_table: dict[str, SourceEvidence],
    guard_mode: Literal["off", "shadow", "enforce"],
    identity_revision: int,
    generation_epoch: int = 0,
    parse_error: str = "",
) -> AttributionDecision:
    """应用归属守护决策（R6 §6.6；复核 F12 后为共享决策核的薄包装）。

    决策规则：
    - off: 放行所有（不检查）
    - shadow: 记录问题，但同样产出安全文本供比对
    - enforce: 拒绝无效引用/风险文本，回退受限输出
    """
    if guard_mode == "off":
        return AttributionDecision(
            decision="pass",
            guard_mode="off",
            identity_revision=identity_revision,
            generation_epoch=generation_epoch,
        )
    _, decision, _ = _decide(
        reply_plan, parse_error, evidence_table, set(evidence_table.keys()),
        guard_mode, identity_revision, generation_epoch,
    )
    return decision


def render_final_reply(
    reply_plan: ReplyPlan,
    evidence_table: dict[str, SourceEvidence],
) -> str:
    """服务端渲染最终回复（R6 §6.6；shadow 比对/工具用途）。

    组合规则：纠正承认模板 → 当前回应 → 服务端渲染的合法引用。
    """
    parts: list[str] = []
    if reply_plan.correction_ack:
        parts.append(render_correction_ack(evidence_table))
    if reply_plan.current_response:
        parts.append(reply_plan.current_response)
    for ref_id in reply_plan.quote_references + reply_plan.verified_fact_references:
        if ref_id in evidence_table:
            rendered = render_evidence(ref_id, evidence_table[ref_id])
            if rendered:
                parts.append(rendered)
    return " ".join(parts)


def apply_attribution_guard(
    raw_output: str | ReplyEnvelope | dict,
    evidence_table: dict[str, SourceEvidence],
    budget_retained_ids: set[str],
    guard_mode: Literal["off", "shadow", "enforce"],
    identity_revision: int,
    generation_epoch: int = 0,
    risk_context: dict | None = None,
    parse_error: str = "",
) -> tuple[str, AttributionDecision]:
    """应用归属守护 - 最终发送前检查（复核 F12/F1：完整管线）。

    流程：解析 reply_plan → 验证证据引用（类型+预算）→ 风险词检查 →
    服务端渲染（ack 走受限模板）→ 记录决策与 digest。

    Returns:
        (final_output, decision)。guard_mode=off 时原样返回；
        shadow/enforce 下解析失败或危险内容返回受限安全文本。
    """
    raw_text = raw_output if isinstance(raw_output, str) else repr(raw_output)
    decision = AttributionDecision(
        decision="pass",
        guard_mode=guard_mode,
        identity_revision=identity_revision,
        generation_epoch=generation_epoch,
        original_output_digest=_digest(raw_text),
    )

    if guard_mode == "off" and isinstance(raw_output, str):
        decision.final_output_digest = decision.original_output_digest
        return raw_output, decision

    if isinstance(raw_output, ReplyEnvelope):
        plan, error = raw_output, ""
    elif isinstance(raw_output, str):
        plan, error = parse_reply_envelope(raw_output)
    else:
        plan, error = reply_envelope_from_projection(raw_output)
    error = parse_error or error
    _, decision, final_output = _decide(
        plan, error, evidence_table, budget_retained_ids,
        guard_mode, identity_revision, generation_epoch,
        risk_context=risk_context,
    )
    decision.original_output_digest = _digest(raw_text)
    decision.final_output_digest = _digest(final_output)
    return final_output, decision
