# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Golden vectors for the versioned Python/Rust promotion CAS wire format."""

from memory.cas_contract import (
    candidate_digest,
    digest_cas_object,
    evidence_set_digest,
)


def test_typed_cas_scalar_golden_vector():
    assert digest_cas_object(
        "parity_fixture",
        [("null", None), ("flag", True), ("signed", -42), ("float", -0.0), ("text", "偏好/é")],
    ) == "4e04306101fb4a12abbafa7fda468398cb1dfef05a2b5a1bcdd2556e857b85ed"


def test_evidence_set_golden_vector():
    record = {
        "id": "e-2",
        "source_row_id": 2,
        "source_conversation_key": "conv",
        "source_digest": "a" * 64,
        "fact_subject_key": "qq:7",
        "owner_key": "space:1",
        "audience": "CURRENT_SPACE",
        "fact_key": "claim:v1:x",
        "verification_status": "accepted",
        "assessment_version": "2026-10-08.1",
        "candidate_link_active": True,
        "claim_state_active": True,
    }
    assert evidence_set_digest([record]) == (
        "8a74529eb1d8f50a173f638cebd941af07a297fef8500b7bab61ce78dec15a22"
    )


def test_candidate_digest_golden_vector():
    candidate = {
        "id": "c-1",
        "group_shared_space": "1",
        "user_id": "7",
        "type": "PREFERENCE",
        "content": "我喜欢桌游",
        "status": "NEW",
        "importance": 0.7,
        "confidence": 0.8,
        "occurrence_count": 2,
        "source_kinds": '["AT_MENTION"]',
        "source_kind": "AT_MENTION",
        "source_message_ids": '["1","2"]',
        "owner_type": "SPACE",
        "owner_key": "space:1",
        "subject_key": "",
        "audience": "CURRENT_SPACE",
        "source_conversation_key": "conv",
        "fact_key": "claim:v1:x",
        "policy_version": "v1",
        "usage_tags": '["PERSONALIZE"]',
        "visibility": "OPEN",
        "behavior_rule": "",
    }
    assert candidate_digest(
        candidate, verification_status="accepted", evidence_digest="b" * 64
    ) == "7215ae62ec241daca6fe74cfa778fc00633685034207baf2620434c8b46d764d"


def test_typed_cas_distinguishes_null_empty_and_boolean_integer():
    assert digest_cas_object("fixture", [("value", None)]) != digest_cas_object(
        "fixture", [("value", "")]
    )
    assert digest_cas_object("fixture", [("value", True)]) != digest_cas_object(
        "fixture", [("value", 1)]
    )
