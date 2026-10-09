# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""可验证的抽取式会话摘要包。

模型只选择服务端生成的证据 ref；摘要正文始终由这里从完整来源行渲染，
不接受模型改写的作者、对象、条件或事实陈述。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

SUMMARY_PACKET_FORMAT = "2026-10-08.1"
_PACKET_DOMAIN = b"stella-summary-packet-v1\0"
_EVIDENCE_DOMAIN = b"stella-summary-evidence-v1\0"


@dataclass(frozen=True, slots=True)
class SummarySourceMessage:
    """一条未经摘要改写的数据库来源行；content 按原文保存。"""

    message_id: int
    author_id: str
    source_kind: str
    content: str
    timestamp: str = ""
    platform_message_id: str = ""
    part_index: int = 0
    recipient_id: str = ""
    origin_msg_id: str = ""
    reply_to_msg_id: str = ""
    reply_target_user_id: str = ""
    mentioned_user_ids: tuple[str, ...] = ()
    mentioned_user_ids_json: str = ""
    logical_message_id: str = ""


@dataclass(frozen=True, slots=True)
class SummaryEvidence:
    """模型可选择的完整逻辑发言单元。"""

    ref_id: str
    source_digest: str
    conversation_key: str
    bot_id: str
    messages: tuple[SummarySourceMessage, ...]

    @property
    def source_ids(self) -> tuple[int, ...]:
        return tuple(message.message_id for message in self.messages)


@dataclass(frozen=True, slots=True)
class SummaryPacket:
    """服务端验证后提交的 extractive packet。"""

    format_version: str
    conversation_key: str
    bot_id: str
    source_guard: tuple[int, int, int]
    source_low_id: int
    source_high_id: int
    source_watermark: int
    source_row_count: int
    entries: tuple[SummaryEvidence, ...]
    digest: str


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _message_payload(message: SummarySourceMessage) -> dict[str, Any]:
    return asdict(message)


def _evidence_digest(
    conversation_key: str,
    bot_id: str,
    messages: tuple[SummarySourceMessage, ...],
) -> str:
    payload = {
        "conversation_key": conversation_key,
        "bot_id": bot_id,
        "messages": [_message_payload(message) for message in messages],
    }
    return hashlib.sha256(_EVIDENCE_DOMAIN + _json_bytes(payload)).hexdigest()


def build_summary_evidence(
    conversation_key: str,
    bot_id: str,
    messages: tuple[SummarySourceMessage, ...] | list[SummarySourceMessage],
) -> SummaryEvidence:
    """从一组完整来源行建立稳定 ref 和 source digest。"""
    frozen_messages = tuple(messages)
    source_digest = _evidence_digest(conversation_key, bot_id, frozen_messages)
    return SummaryEvidence(
        ref_id="ref_" + source_digest[:32],
        source_digest=source_digest,
        conversation_key=conversation_key,
        bot_id=bot_id,
        messages=frozen_messages,
    )


def _packet_payload(
    *,
    format_version: str,
    conversation_key: str,
    bot_id: str,
    source_guard: tuple[int, int, int],
    source_low_id: int,
    source_high_id: int,
    source_watermark: int,
    source_row_count: int,
    entries: tuple[SummaryEvidence, ...],
) -> dict[str, Any]:
    return {
        "format_version": format_version,
        "conversation_key": conversation_key,
        "bot_id": bot_id,
        "source_guard": list(source_guard),
        "source_low_id": source_low_id,
        "source_high_id": source_high_id,
        "source_watermark": source_watermark,
        "source_row_count": source_row_count,
        "entries": [
            {
                "ref_id": entry.ref_id,
                "source_digest": entry.source_digest,
                "conversation_key": entry.conversation_key,
                "bot_id": entry.bot_id,
            }
            for entry in entries
        ],
    }


def build_summary_packet(
    *,
    conversation_key: str,
    bot_id: str,
    source_guard: tuple[int, int, int],
    source_low_id: int,
    source_high_id: int,
    source_watermark: int,
    source_row_count: int,
    entries: tuple[SummaryEvidence, ...] | list[SummaryEvidence],
) -> SummaryPacket:
    frozen_entries = tuple(entries)
    payload = _packet_payload(
        format_version=SUMMARY_PACKET_FORMAT,
        conversation_key=conversation_key,
        bot_id=bot_id,
        source_guard=tuple(source_guard),
        source_low_id=source_low_id,
        source_high_id=source_high_id,
        source_watermark=source_watermark,
        source_row_count=source_row_count,
        entries=frozen_entries,
    )
    digest = hashlib.sha256(_PACKET_DOMAIN + _json_bytes(payload)).hexdigest()
    return SummaryPacket(
        format_version=SUMMARY_PACKET_FORMAT,
        conversation_key=conversation_key,
        bot_id=bot_id,
        source_guard=tuple(source_guard),
        source_low_id=source_low_id,
        source_high_id=source_high_id,
        source_watermark=source_watermark,
        source_row_count=source_row_count,
        entries=frozen_entries,
        digest=digest,
    )


def validate_summary_evidence(evidence: SummaryEvidence) -> bool:
    if not isinstance(evidence, SummaryEvidence):
        return False
    if not evidence.conversation_key or not evidence.messages:
        return False
    ids: list[int] = []
    for message in evidence.messages:
        if not isinstance(message, SummarySourceMessage):
            return False
        if (
            isinstance(message.message_id, bool)
            or not isinstance(message.message_id, int)
            or message.message_id <= 0
            or not message.author_id.strip()
            or not message.source_kind.strip()
            or not isinstance(message.content, str)
            or not message.content.strip()
            or isinstance(message.part_index, bool)
            or not isinstance(message.part_index, int)
            or message.part_index < 0
            or not isinstance(message.mentioned_user_ids, tuple)
            or any(not isinstance(uid, str) for uid in message.mentioned_user_ids)
        ):
            return False
        if message.source_kind == "BOT_SELF" and (
            not evidence.bot_id or message.author_id != evidence.bot_id
        ):
            return False
        ids.append(message.message_id)
    if ids != sorted(set(ids)):
        return False
    expected = _evidence_digest(evidence.conversation_key, evidence.bot_id, evidence.messages)
    return (
        evidence.source_digest == expected
        and evidence.ref_id == "ref_" + expected[:32]
    )


def validate_summary_packet(
    packet: SummaryPacket,
    *,
    conversation_key: str | None = None,
    bot_id: str | None = None,
) -> bool:
    if not isinstance(packet, SummaryPacket):
        return False
    if (
        packet.format_version != SUMMARY_PACKET_FORMAT
        or not packet.conversation_key
        or (conversation_key is not None and packet.conversation_key != conversation_key)
        or (bot_id is not None and packet.bot_id != bot_id)
        or len(packet.source_guard) != 3
        or any(isinstance(part, bool) or not isinstance(part, int) or part < 0 for part in packet.source_guard)
        or packet.source_low_id != packet.source_guard[2]
        or packet.source_high_id <= packet.source_low_id
        or not packet.source_low_id < packet.source_watermark < packet.source_high_id
        or isinstance(packet.source_row_count, bool)
        or not isinstance(packet.source_row_count, int)
        or packet.source_row_count <= 0
        or not packet.entries
    ):
        return False
    refs: set[str] = set()
    source_ids: set[int] = set()
    for entry in packet.entries:
        if (
            not validate_summary_evidence(entry)
            or entry.conversation_key != packet.conversation_key
            or entry.bot_id != packet.bot_id
            or entry.ref_id in refs
            or source_ids.intersection(entry.source_ids)
        ):
            return False
        refs.add(entry.ref_id)
        source_ids.update(entry.source_ids)
    payload = _packet_payload(
        format_version=packet.format_version,
        conversation_key=packet.conversation_key,
        bot_id=packet.bot_id,
        source_guard=packet.source_guard,
        source_low_id=packet.source_low_id,
        source_high_id=packet.source_high_id,
        source_watermark=packet.source_watermark,
        source_row_count=packet.source_row_count,
        entries=packet.entries,
    )
    expected = hashlib.sha256(_PACKET_DOMAIN + _json_bytes(payload)).hexdigest()
    return packet.digest == expected


def render_summary_evidence(evidence: SummaryEvidence) -> str:
    """Render exact source text plus its trusted author/recipient metadata."""
    if not validate_summary_evidence(evidence):
        return ""
    first = evidence.messages[0]
    role = "Bot" if first.source_kind == "BOT_SELF" else "用户"
    author = f"{role}({first.author_id})"
    bubbles = [
        {
            "row_id": message.message_id,
            "platform_message_id": message.platform_message_id,
            "part": message.part_index,
            "kind": message.source_kind,
            "text": message.content,
            "timestamp": message.timestamp,
            "recipient_id": message.recipient_id,
            "origin_msg_id": message.origin_msg_id,
            "reply_to_msg_id": message.reply_to_msg_id,
            "reply_target_user_id": message.reply_target_user_id,
            "mentioned_user_ids": list(message.mentioned_user_ids),
            "mentioned_user_ids_json": message.mentioned_user_ids_json,
        }
        for message in evidence.messages
    ]
    return (
        f"REF {evidence.ref_id} | conversation={evidence.conversation_key} "
        f"bot={evidence.bot_id or 'unknown'} author={author} "
        f"source_ids={','.join(map(str, evidence.source_ids))} "
        f"source_sha256={evidence.source_digest} | "
        + json.dumps(bubbles, ensure_ascii=False, separators=(",", ":"))
    )


def render_summary_packet(packet: SummaryPacket) -> str:
    """Render a validated packet for the next model turn/context."""
    if not validate_summary_packet(packet):
        return ""
    lines = [
        f"[SummaryPacket {packet.format_version}; conversation={packet.conversation_key}; "
        f"bot={packet.bot_id or 'unknown'}; digest={packet.digest}]"
    ]
    lines.extend(render_summary_evidence(entry) for entry in packet.entries)
    return "\n".join(line for line in lines if line)
