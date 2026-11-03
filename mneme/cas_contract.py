# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Typed, versioned CAS serialization shared with the Rust memory backend."""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Mapping, Sequence
from typing import Any

CAS_SCHEMA_VERSION = 1
_DOMAIN = b"stella-cas-v1\0"


def _length(value: int) -> bytes:
    if value < 0 or value >= 1 << 64:
        raise ValueError("CAS field length is outside u64")
    return value.to_bytes(8, "big", signed=False)


def _typed_payload(value: Any) -> tuple[bytes, bytes]:
    if value is None:
        return b"n", b""
    if isinstance(value, bool):
        return b"b", b"\x01" if value else b"\x00"
    if isinstance(value, int):
        try:
            return b"i", struct.pack(">q", value)
        except struct.error as exc:
            raise ValueError("CAS integer is outside i64") from exc
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("CAS float must be finite")
        normalized = 0.0 if value == 0.0 else value
        return b"f", struct.pack(">d", normalized)
    if isinstance(value, str):
        return b"s", value.encode("utf-8")
    raise TypeError(f"unsupported CAS value type: {type(value).__name__}")


def encode_cas_object(object_type: str, fields: Sequence[tuple[str, Any]]) -> bytes:
    """Encode ordered typed fields without relying on JSON/dict serialization."""
    try:
        kind = object_type.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("CAS object type must be ASCII") from exc
    out = bytearray(_DOMAIN + kind + b"\0" + _length(len(fields)))
    for name, value in fields:
        name_bytes = name.encode("utf-8")
        tag, payload = _typed_payload(value)
        out.extend(_length(len(name_bytes)))
        out.extend(name_bytes)
        out.extend(tag)
        out.extend(_length(len(payload)))
        out.extend(payload)
    return bytes(out)


def digest_cas_object(object_type: str, fields: Sequence[tuple[str, Any]]) -> str:
    return hashlib.sha256(encode_cas_object(object_type, fields)).hexdigest()


def scope_versions_digest(versions: Mapping[str, int]) -> str:
    ordered = sorted(versions.items(), key=lambda item: item[0].encode("utf-8"))
    fields: list[tuple[str, Any]] = [("scope_count", len(ordered))]
    for index, (key, version) in enumerate(ordered):
        fields.extend(((f"scope.{index}.key", key), (f"scope.{index}.version", int(version))))
    return digest_cas_object("scope_versions", fields)


def evidence_set_digest(records: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(records, key=lambda row: str(row["id"]).encode("utf-8"))
    fields: list[tuple[str, Any]] = [("evidence_count", len(ordered))]
    record_fields = (
        "id",
        "source_row_id",
        "source_conversation_key",
        "source_digest",
        "fact_subject_key",
        "owner_key",
        "audience",
        "fact_key",
        "verification_status",
        "assessment_version",
        "candidate_link_active",
        "claim_state_active",
    )
    for row in ordered:
        for key in record_fields:
            fields.append((f"evidence.{key}", row.get(key)))
    return digest_cas_object("evidence_set", fields)


def candidate_digest(
    candidate: Mapping[str, Any], *, verification_status: str, evidence_digest: str
) -> str:
    group = str(candidate.get("group_shared_space") or "")
    fields = (
        ("candidate_id", str(candidate.get("id") or "")),
        ("group_shared_space", group),
        ("user_id", str(candidate.get("user_id") or "")),
        ("memory_type", str(candidate.get("type") or "FACT")),
        ("content", str(candidate.get("content") or "")),
        ("status", str(candidate.get("status") or "NEW")),
        ("importance", float(candidate.get("importance") or 0.0)),
        ("confidence", float(candidate.get("confidence") or 0.0)),
        ("occurrence_count", int(candidate.get("occurrence_count") or 1)),
        ("source_kinds", str(candidate.get("source_kinds") or '["PASSIVE"]')),
        ("source_kind", str(candidate.get("source_kind") or "PASSIVE")),
        ("source_message_ids", str(candidate.get("source_message_ids") or "[]")),
        ("owner_type", str(candidate.get("owner_type") or "SPACE")),
        ("owner_key", str(candidate.get("owner_key") or f"space:{group}")),
        ("subject_key", str(candidate.get("subject_key") or "")),
        ("audience", str(candidate.get("audience") or "CURRENT_SPACE")),
        ("source_conversation_key", str(candidate.get("source_conversation_key") or "")),
        ("fact_key", str(candidate.get("fact_key") or "")),
        ("policy_version", str(candidate.get("policy_version") or "")),
        ("usage_tags", str(candidate.get("usage_tags") or "[]")),
        ("visibility", str(candidate.get("visibility") or "OPEN")),
        ("behavior_rule", str(candidate.get("behavior_rule") or "")),
        ("verification_status", verification_status),
        ("evidence_digest", evidence_digest),
    )
    return digest_cas_object("promotion_candidate", fields)
