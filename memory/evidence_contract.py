# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Server-owned source binding and conservative semantic evidence assessment.

Model-provided fields are proposals. This module resolves them against exact rows in
``group_messages`` and creates the only accepted evidence contract promotion may use.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from typing import Any

LEGACY_ASSESSMENT_VERSION = "2026-10-08.1"
ASSESSMENT_VERSION = "2026-10-21.1"
SUPPORTED_ASSESSMENT_VERSIONS = frozenset(
    {LEGACY_ASSESSMENT_VERSION, ASSESSMENT_VERSION}
)
EVIDENCE_STATUSES = frozenset(
    {"accepted", "rejected", "unknown", "legacy_unverified", "superseded"}
)
_SOURCE_DOMAIN = b"stella-memory-source-v1\0"
_CLAIM_DOMAIN = b"stella-memory-claim-v1\0"
_SOURCE_COLUMNS = (
    "id",
    "group_id",
    "user_id",
    "content",
    "source_kind",
    "timestamp",
    "msg_id",
    "conversation_key",
    "bot_id",
    "reply_to_msg_id",
    "reply_target_user_id",
    "mentioned_user_ids_json",
    "logical_message_id",
    "part_index",
    "origin_msg_id",
    "reply_recipient_user_id",
    "subject_key",
    "connection_id",
)
_ACCEPTED_KINDS = frozenset({"self_report", "explicit_preference"})
_CONDITIONAL = re.compile(
    r"如果|要是|假如|倘若|可能|也许|听说|据说|好像|传闻|角色扮演|扮演|假装|开玩笑|玩笑|"
    r"\b(?:if|maybe|perhaps|supposedly|heard that|roleplay|pretend|joking)\b",
    re.IGNORECASE,
)
_QUOTE_MARKS = frozenset("\"'“”‘’「」『』《》〈〉")
_SELF_REPORT_PATTERNS = {
    "profile.residence": re.compile(
        r"我(?:目前|现在)?(?:住在|居住在)(?P<value>[^，。！？!?；;]+)[。！!]?"
    ),
    "profile.origin": re.compile(r"我(?:来自|出生于)(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "profile.nickname": re.compile(r"我叫(?P<value>[^，。！？!?；;]+)[。！!]?"),
    "profile.employer": re.compile(r"我在(?P<value>[^，。！？!?；;]+?)工作[。！!]?"),
    "profile.residence.en": re.compile(
        r"I live in (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE
    ),
    "profile.origin.en": re.compile(
        r"(?:I am from|I'm from) (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE
    ),
    "profile.nickname.en": re.compile(
        r"My name is (?P<value>[^.!?;]+)[.!]?", re.IGNORECASE
    ),
}
_PREFERENCE_PATTERN = re.compile(
    r"我(?P<cue>喜欢|偏好|不喜欢|讨厌)(?P<value>[^，。！？!?；;]+)[。！]?"
)
_PREFERENCE_PATTERN_EN = re.compile(
    r"I (?P<cue>like|prefer|don't like|dislike) (?P<value>[^.!?;]+)[.!]?",
    re.IGNORECASE,
)


def _semantic_contract_matches(
    span: str, *, predicate: str, canonical_value: str, polarity: str, statement_kind: str
) -> bool:
    """Accept only narrow, explicit utterance forms with mechanically bound meaning."""
    expected_value = canonical_value.strip()
    if statement_kind == "self_report":
        pattern = _SELF_REPORT_PATTERNS.get(predicate)
        if pattern is None or polarity != "positive":
            return False
        match = pattern.fullmatch(span.strip())
        return bool(match and match.group("value").strip() == expected_value)
    if statement_kind != "explicit_preference" or predicate != "preference.general":
        return False
    match = _PREFERENCE_PATTERN.fullmatch(span.strip()) or _PREFERENCE_PATTERN_EN.fullmatch(
        span.strip()
    )
    if not match or match.group("value").strip() != expected_value:
        return False
    cue = match.group("cue").lower()
    observed_polarity = (
        "negative"
        if cue in {"不喜欢", "讨厌", "don't like", "dislike"}
        else "positive"
    )
    return observed_polarity == polarity


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + canonical_json(value).encode("utf-8")).hexdigest()


def parse_source_ids(value: Any) -> tuple[int, ...] | None:
    """Parse a non-empty, unique list of positive SQLite row IDs."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(value, list) or not value:
        return None
    ids: list[int] = []
    for item in value:
        if isinstance(item, bool):
            return None
        if isinstance(item, int):
            message_id = item
        elif isinstance(item, str) and item.isdecimal():
            message_id = int(item)
        else:
            return None
        if message_id <= 0:
            return None
        ids.append(message_id)
    if len(ids) != len(set(ids)):
        return None
    return tuple(ids)


def _snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in _SOURCE_COLUMNS:
        if column not in row:
            continue
        value = row[column]
        # Additive identity columns must not rewrite historical snapshot digests.
        if column in {"subject_key", "connection_id"} and not str(value or "").strip():
            continue
        if column in {"id", "part_index"}:
            result[column] = int(value or 0)
        else:
            result[column] = str(value or "")
    return result


def supports_assessment_version(value: Any) -> bool:
    """Whether a stored assessment has a validator for its version."""
    return str(value or "") in SUPPORTED_ASSESSMENT_VERSIONS


def _source_subject(rows: list[dict[str, Any]], *, bot_id: str) -> tuple[str, str, str]:
    """Resolve identity from source rows only; proposal fields cannot set identity."""
    from core.transport.keys import decode_subject_key_v2

    subjects = {str(row.get("subject_key") or "").strip() for row in rows}
    connections = {str(row.get("connection_id") or "").strip() for row in rows}
    authors = {str(row.get("user_id") or "").strip() for row in rows}
    if len(authors) != 1 or "" in authors:
        return "", "", "source_author_mismatch"
    author = next(iter(authors))
    if subjects == {""} and connections == {""}:
        conversations = {str(row.get("conversation_key") or "") for row in rows}
        if (
            len(conversations) == 1
            and next(iter(conversations)).startswith("qq:")
            and author.isdecimal()
            and int(author) > 0
        ):
            return f"qq:{author}", f"legacy-qq:{bot_id}" if bot_id else "", ""
        return "", "", "source_subject_unknown"
    if "" in subjects or "" in connections or len(subjects) != 1 or len(connections) != 1:
        return "", "", "source_identity_mismatch"
    subject = next(iter(subjects))
    connection = next(iter(connections))
    if not subject.startswith("u2."):
        return "", "", "source_subject_invalid"
    try:
        _domain, subject_author = decode_subject_key_v2(subject)
    except (TypeError, ValueError):
        return "", "", "source_subject_invalid"
    if subject_author != author:
        return "", "", "source_author_mismatch"
    conversation_keys = {str(row.get("conversation_key") or "") for row in rows}
    conversation_key = next(iter(conversation_keys), "")
    if conversation_key.startswith("c2."):
        from core.transport.keys import decode_conversation_key_v2

        try:
            source_bot, _scene = decode_conversation_key_v2(conversation_key)
        except (TypeError, ValueError):
            return "", "", "source_conversation_invalid"
        if source_bot.connection_id != connection or source_bot.self_id != bot_id:
            return "", "", "source_connection_mismatch"
    return subject, connection, ""


def _source_owner_key(
    subject_key: str, connection_id: str, bot_id: str, raw_user_id: str
) -> str:
    if subject_key.startswith("u2.") and connection_id:
        from memory.ownership import person_owner_key_for_subject

        return person_owner_key_for_subject(connection_id, subject_key)
    if subject_key.startswith("qq:") and bot_id and raw_user_id.isdecimal():
        from memory.ownership import person_owner_key

        return person_owner_key("qq", bot_id, raw_user_id)
    return ""


def source_digest(snapshot: Mapping[str, Any]) -> str:
    return _hash(_SOURCE_DOMAIN, dict(snapshot))


def _qualifiers(value: Any) -> Any | None:
    if value is None:
        return []
    if isinstance(value, (str, int, float, bool)):
        return None
    try:
        encoded = canonical_json(value)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > 4096:
        return None
    return value


def _resolve_sources(
    conn,
    *,
    group_id: int,
    source_ids: tuple[int, ...],
    allowed_batch_ids: set[int],
    expected_conversation_key: str,
    expected_bot_id: str,
) -> tuple[list[dict[str, Any]], str, str, str]:
    if not set(source_ids).issubset(allowed_batch_ids):
        return [], "", "", "rejected:source_outside_batch"
    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(group_messages)").fetchall()
    }
    required = {"id", "group_id", "user_id", "content"}
    if not required.issubset(columns):
        return [], "", "", "unknown:source_schema_incomplete"
    selected = [name for name in _SOURCE_COLUMNS if name in columns]
    marks = ",".join("?" for _ in source_ids)
    rows = conn.execute(
        f"SELECT {', '.join(selected)} FROM group_messages "
        f"WHERE group_id = ? AND id IN ({marks}) ORDER BY id ASC",
        (str(group_id), *source_ids),
    ).fetchall()
    resolved = [_snapshot(dict(zip(selected, row, strict=True))) for row in rows]
    if {int(row["id"]) for row in resolved} != set(source_ids):
        return [], "", "", "rejected:source_missing_or_wrong_group"
    if any(not str(row.get("content") or "").strip() for row in resolved):
        return [], "", "", "rejected:source_empty"

    conversations = {str(row.get("conversation_key") or "").strip() for row in resolved}
    known_conversations = {value for value in conversations if value}
    if len(known_conversations) > 1 or (known_conversations and "" in conversations):
        return [], "", "", "rejected:conversation_mismatch"
    conversation_key = next(iter(known_conversations), "")
    if not conversation_key and group_id > 0:
        conversation_key = f"legacy:group:{group_id}"
    if not conversation_key:
        return [], "", "", "unknown:conversation_missing"
    if expected_conversation_key and conversation_key != expected_conversation_key:
        return [], "", "", "rejected:conversation_mismatch"

    bots = {str(row.get("bot_id") or "").strip() for row in resolved}
    known_bots = {value for value in bots if value}
    if len(known_bots) > 1 or (known_bots and "" in bots):
        return [], "", "", "rejected:bot_mismatch"
    bot_id = next(iter(known_bots), "")
    if expected_bot_id and bot_id and bot_id != expected_bot_id:
        return [], "", "", "rejected:bot_mismatch"
    bot_id = bot_id or expected_bot_id
    return resolved, conversation_key, bot_id, ""


def assess_candidate(
    conn,
    candidate: Mapping[str, Any],
    *,
    group_id: int,
    allowed_batch_ids: set[int],
    expected_conversation_key: str = "",
    expected_bot_id: str = "",
) -> dict[str, Any]:
    """Resolve a model proposal to source snapshots and a server-owned status.

    Acceptance is deliberately narrow: the claim must bind to a supported literal
    utterance form, exclude ambiguity/conditionals, and be authored by the same
    stable QQ subject. Everything else remains unknown or rejected evidence.
    """
    source_ids = parse_source_ids(candidate.get("source_message_ids"))
    if source_ids is None:
        return {"status": "rejected", "reason": "source_ids_invalid", "sources": []}
    rows, conversation_key, bot_id, source_error = _resolve_sources(
        conn,
        group_id=group_id,
        source_ids=source_ids,
        allowed_batch_ids=allowed_batch_ids,
        expected_conversation_key=expected_conversation_key,
        expected_bot_id=expected_bot_id,
    )
    if source_error:
        status, reason = source_error.split(":", 1)
        return {"status": status, "reason": reason, "sources": []}

    resolved_subject, resolved_connection, identity_error = _source_subject(
        rows, bot_id=bot_id
    )

    def unassessed(
        status: str, reason: str, subject_override: str | None = None
    ) -> dict[str, Any]:
        sources = []
        for row in rows:
            author_id = str(row.get("user_id") or "").strip()
            subject = (
                subject_override
                if subject_override is not None
                else resolved_subject
                if author_id and author_id == str(candidate.get("user_id") or "")
                else ""
            )
            snapshot_hash = source_digest(row)
            provenance = {
                "assessment_version": ASSESSMENT_VERSION,
                "source_snapshot_version": 2
                if row.get("subject_key") and row.get("connection_id")
                else 1,
                "verification_status": status,
                "assessment_reason": reason,
                "recording_author_key": subject,
                "fact_object_key": subject,
                "conversation_key": conversation_key,
                "bot_id": bot_id,
                "source_snapshot": row,
            }
            sources.append(
                {
                    "source_row_id": int(row["id"]),
                    "source_conversation_key": conversation_key,
                    "source_digest": snapshot_hash,
                    "fact_subject_key": subject,
                    "verification_status": status,
                    "provenance_json": canonical_json(provenance),
                    "source_kind": str(row.get("source_kind") or "PASSIVE").upper(),
                    "snapshot": row,
                }
            )
        return {
            "status": status,
            "reason": reason,
            "fact_subject_key": resolved_subject,
            "owner_key": _source_owner_key(
                resolved_subject, resolved_connection, bot_id, str(candidate.get("user_id") or "")
            ),
            "sources": sources,
        }

    if expected_bot_id and any(not str(row.get("bot_id") or "").strip() for row in rows):
        return unassessed("unknown", "source_bot_missing")

    uid = str(candidate.get("user_id") or "").strip()
    if not uid:
        return unassessed("rejected", "subject_id_invalid")
    if identity_error:
        return unassessed("unknown", identity_error)
    if resolved_subject.startswith("qq:") and (not uid.isdecimal() or int(uid) <= 0):
        return unassessed("unknown", "legacy_subject_id_invalid")
    contract = candidate.get("verification_contract")
    if not isinstance(contract, dict):
        return unassessed("unknown", "contract_missing")
    allowed_contract_keys = {
        "fact_subject_user_id",
        "predicate_key",
        "canonical_value",
        "polarity",
        "statement_kind",
        "temporal_qualifiers",
        "context_qualifiers",
        "supports",
    }
    if set(contract) != allowed_contract_keys:
        return unassessed("unknown", "contract_shape_invalid")

    predicate = contract.get("predicate_key")
    canonical_value = contract.get("canonical_value")
    polarity = contract.get("polarity")
    statement_kind = contract.get("statement_kind")
    supports = contract.get("supports")
    temporal = _qualifiers(contract.get("temporal_qualifiers"))
    context = _qualifiers(contract.get("context_qualifiers"))
    if (
        not isinstance(predicate, str)
        or not re.fullmatch(r"[a-z][a-z0-9_.:-]{0,95}", predicate)
        or not isinstance(canonical_value, str)
        or not canonical_value.strip()
        or len(canonical_value) > 160
        or polarity not in {"positive", "negative"}
        or not isinstance(statement_kind, str)
        or temporal is None
        or context is None
        or not isinstance(supports, list)
        or len(supports) != len(source_ids)
    ):
        return unassessed("unknown", "contract_fields_invalid")

    support_by_id: dict[int, str] = {}
    for support in supports:
        if not isinstance(support, dict) or set(support) != {
            "source_message_id",
            "exact_support_span",
        }:
            return unassessed("unknown", "support_shape_invalid")
        raw_id = support.get("source_message_id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            return unassessed("unknown", "support_id_invalid")
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError):
            return unassessed("unknown", "support_id_invalid")
        span = support.get("exact_support_span")
        if message_id in support_by_id or not isinstance(span, str) or not span.strip():
            return unassessed("unknown", "support_duplicate_or_empty")
        support_by_id[message_id] = span
    if set(support_by_id) != set(source_ids):
        return unassessed("rejected", "support_source_set_mismatch")

    content = str(candidate.get("content") or "").strip()
    if not content or any(span != content for span in support_by_id.values()):
        return unassessed("rejected", "content_not_exact_support")
    if canonical_value not in content:
        return unassessed("unknown", "canonical_value_not_supported")

    subject_key = resolved_subject
    if subject_key.startswith("qq:") and subject_key != f"qq:{uid}":
        return unassessed("unknown", "source_subject_mismatch", subject_key)
    if subject_key.startswith("u2."):
        from core.transport.keys import decode_subject_key_v2

        try:
            _identity_domain, source_user_id = decode_subject_key_v2(subject_key)
        except (TypeError, ValueError):
            return unassessed("unknown", "source_subject_invalid")
        if source_user_id != uid:
            return unassessed("unknown", "source_subject_mismatch", subject_key)
    source_records: list[dict[str, Any]] = []
    assessment_reasons: list[str] = []
    for row in rows:
        author_id = str(row.get("user_id") or "").strip()
        source_kind = str(row.get("source_kind") or "PASSIVE").strip().upper()
        span = support_by_id[int(row["id"])]
        if source_kind not in {"AT_MENTION", "PASSIVE", "PRIVATE_DIRECT", "BOT_SELF"}:
            return unassessed("unknown", "source_kind_unrecognized", subject_key)
        if source_kind == "BOT_SELF":
            return unassessed("rejected", "bot_speech_source")
        if span not in str(row.get("content") or ""):
            return unassessed("rejected", "support_span_not_in_source")
        if author_id != uid:
            return unassessed("unknown", "author_is_not_fact_subject")
        source_records.append({"snapshot": row, "digest": source_digest(row)})

    if contract.get("fact_subject_user_id") != uid:
        assessment_reasons.append("fact_subject_mismatch")
    if statement_kind not in _ACCEPTED_KINDS:
        assessment_reasons.append("statement_kind_not_accepted")
    if statement_kind == "self_report" and str(candidate.get("type") or "FACT").upper() != "FACT":
        assessment_reasons.append("self_report_type_mismatch")
    if (
        statement_kind == "explicit_preference"
        and str(candidate.get("type") or "").upper() != "PREFERENCE"
    ):
        assessment_reasons.append("preference_type_mismatch")
    for span in support_by_id.values():
        if _CONDITIONAL.search(span) or any(mark in span for mark in _QUOTE_MARKS):
            assessment_reasons.append("conditional_quoted_or_roleplay")
        if span.rstrip().endswith(("?", "？")):
            assessment_reasons.append("question_not_accepted")
        if not _semantic_contract_matches(
            span,
            predicate=str(predicate),
            canonical_value=canonical_value,
            polarity=str(polarity),
            statement_kind=statement_kind,
        ):
            assessment_reasons.append("semantic_contract_not_bound_to_supported_form")

    status = "accepted" if not assessment_reasons else "unknown"
    claim_payload = {
        "version": 1,
        "owner_key": str(candidate.get("owner_key") or ""),
        "audience": str(candidate.get("audience") or ""),
        "fact_subject_key": subject_key,
        "predicate_key": predicate,
        "canonical_value": canonical_value,
        "polarity": polarity,
        "statement_kind": statement_kind,
        "temporal_qualifiers": temporal,
        "context_qualifiers": context,
    }
    claim_key = "claim:v1:" + _hash(_CLAIM_DOMAIN, claim_payload)

    provenance_base = {
        "assessment_version": ASSESSMENT_VERSION,
        "source_snapshot_version": 2
        if all(row.get("subject_key") and row.get("connection_id") for row in rows)
        else 1,
        "verification_status": status,
        "recording_author_key": subject_key,
        "fact_object_key": subject_key,
        "predicate_key": predicate,
        "canonical_value": canonical_value,
        "polarity": polarity,
        "statement_kind": statement_kind,
        "temporal_qualifiers": temporal,
        "context_qualifiers": context,
        "exact_support_span": content,
        "conversation_key": conversation_key,
        "bot_id": bot_id,
        "claim_key": claim_key,
        "assessment_reasons": sorted(set(assessment_reasons)),
    }
    sources = []
    for item in source_records:
        snapshot = item["snapshot"]
        source_provenance = {
            **provenance_base,
            "source_snapshot": snapshot,
            "source_id": int(snapshot["id"]),
        }
        sources.append(
            {
                "source_row_id": int(snapshot["id"]),
                "source_conversation_key": conversation_key,
                "source_digest": item["digest"],
                "fact_subject_key": subject_key,
                "verification_status": status,
                "provenance_json": canonical_json(source_provenance),
                "source_kind": str(snapshot.get("source_kind") or "PASSIVE").upper(),
                "snapshot": snapshot,
            }
        )

    return {
        "status": status,
        "reason": ";".join(sorted(set(assessment_reasons))) or "accepted",
        "fact_subject_key": subject_key,
        "owner_key": _source_owner_key(subject_key, resolved_connection, bot_id, uid),
        "claim_key": claim_key,
        "conversation_key": conversation_key,
        "bot_id": bot_id,
        "sources": sources,
        "provenance": provenance_base,
    }


def verify_source_snapshot(
    snapshot: Mapping[str, Any], expected_digest: str, *, conn=None
) -> bool:
    """Re-hash a stored snapshot and optionally prove it still matches SQLite."""
    try:
        if source_digest(snapshot) != expected_digest:
            return False
        if conn is None:
            return True
        keys = tuple(snapshot)
        if (
            not keys
            or not {"id", "group_id"}.issubset(keys)
            or not set(keys).issubset(_SOURCE_COLUMNS)
        ):
            return False
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(group_messages)").fetchall()
        }
        if not set(keys).issubset(columns):
            return False
        quoted = ", ".join(f'"{name}"' for name in keys)
        row = conn.execute(
            f"SELECT {quoted} FROM group_messages WHERE id = ? AND group_id = ?",
            (int(snapshot["id"]), str(snapshot["group_id"])),
        ).fetchone()
        if row is None:
            return False
        current = {}
        for name, value in zip(keys, row, strict=True):
            current[name] = (
                int(value or 0)
                if name in {"id", "part_index"}
                else str(value or "")
            )
        return current == dict(snapshot)
    except (sqlite3.Error, TypeError, ValueError, KeyError):
        return False
