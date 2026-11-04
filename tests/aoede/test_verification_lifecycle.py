# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S2-01 one-shot verification lifecycle tests (2026-11-03 plan §6.4/§8.2).

Covers: reserve-before-send, active-claim uniqueness, ACK/deadline settlement,
conservative reply binding (third-party / unbound / evasive), terminal states
with tombstones, candidate CAS, startup recovery, and old-source replay
suppression with legitimate new-evidence allowance.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mneme.schema import create_memory_candidates_table
from mneme.verification import (
    REJECTION_TOMBSTONES_TABLE_DDL,
    VERIFICATION_ATTEMPTS_TABLE_DDL,
    MnemeVerificationStore,
)

CLAIM = {
    "owner_key": "space:g1",
    "audience": "CURRENT_SPACE",
    "fact_key": "fact:likes-hiking",
    "subject_key": "qq:1001",
}
SOURCES = {
    "source_row_ids": [11, 12],
    "source_digests": ("d1", "d2"),
}


def _store(tmp_path: Path) -> MnemeVerificationStore:
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    create_memory_candidates_table(conn)
    conn.execute(VERIFICATION_ATTEMPTS_TABLE_DDL)
    conn.execute(REJECTION_TOMBSTONES_TABLE_DDL)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_verification_attempts_active_claim"
        " ON memory_verification_attempts (owner_key, audience, fact_key, subject_key)"
        " WHERE state IN ('RESERVED','SENDING','PENDING_VERIFICATION','DELIVERY_UNKNOWN')"
    )
    conn.commit()
    conn.close()
    return MnemeVerificationStore(str(db))


def _open(store: MnemeVerificationStore, candidate_id: str = "cand-1") -> bool:
    return store.open_attempt(
        candidate_id=candidate_id,
        candidate_content_digest="digest-1",
        owner_type="SPACE",
        owner_key=CLAIM["owner_key"],
        subject_key=CLAIM["subject_key"],
        audience=CLAIM["audience"],
        fact_key=CLAIM["fact_key"],
        evidence_digest="edigest-1",
        evidence_ids=["e1", "e2"],
        **SOURCES,
        bot_ref="legacy-qq:10000",
        connection_id="legacy-qq:10000",
        conversation_key="qq:10000:group:1",
    )


def _insert_candidate(tmp_path: Path, candidate_id: str = "cand-1",
                      status: str = "OBSERVING") -> None:
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO memory_candidates (id, group_shared_space, user_id,"
        " type, content, importance, confidence, evidence, status,"
        " source_message_ids, owner_type, owner_key, subject_key, audience,"
        " fact_key) VALUES (?, 'space:g1', 1001, 'FACT', 'likes hiking', 0.8,"
        " 0.7, '', ?, '[11, 12]', 'SPACE', ?, ?, ?, ?)",
        (candidate_id, status, CLAIM["owner_key"], CLAIM["subject_key"],
         CLAIM["audience"], CLAIM["fact_key"]),
    )
    conn.commit()
    conn.close()


def _candidate_status(tmp_path: Path, candidate_id: str = "cand-1") -> str | None:
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def test_reserve_before_send_and_active_claim_uniqueness(tmp_path) -> None:
    store = _store(tmp_path)
    assert _open(store) is True
    # same claim, fresh candidate id: concurrent attempt must be refused
    assert _open(store, candidate_id="cand-2") is False
    # different claim: allowed
    assert store.open_attempt(
        candidate_id="cand-9",
        candidate_content_digest="d",
        owner_type="SPACE",
        owner_key="space:g1",
        subject_key="qq:1002",
        audience="CURRENT_SPACE",
        fact_key="fact:other",
        evidence_digest="e",
        evidence_ids=["e9"],
        source_row_ids=[99],
        source_digests=["d9"],
        bot_ref="b",
        connection_id="c",
        conversation_key="qq:10000:group:1",
    ) is True


def test_ack_sets_deadline_and_expiry_rejects_candidate(tmp_path) -> None:
    store = _store(tmp_path)
    _insert_candidate(tmp_path)
    assert _open(store) is True
    assert store.mark_sent("cand-1", ["m-1", "m-2"], verification_window_seconds=0.0)
    # bound explicit denial settles DENIED, writes tombstone, CAS-rejects
    verdict = store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-9",
        reply_to_message_id="m-1",
        text="不是了，早就卖了",
    )
    assert verdict == "DENIED"
    assert _candidate_status(tmp_path) == "REJECTED"
    # repeated settle is idempotent (terminal state, no second verdict)
    assert store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-10",
        reply_to_message_id="m-2",
        text="真的",
    ) is None
    # tombstone present
    tomb = store.claim_rejected(
        owner_key=CLAIM["owner_key"], audience=CLAIM["audience"],
        fact_key=CLAIM["fact_key"], subject_key=CLAIM["subject_key"],
    )
    assert tomb is not None


def test_unbound_and_third_party_replies_do_not_settle(tmp_path) -> None:
    store = _store(tmp_path)
    _insert_candidate(tmp_path)
    assert _open(store) is True
    # window=0 → deadline already due; unbound messages must still not settle early
    assert store.mark_sent("cand-1", ["m-1"], verification_window_seconds=0.0)
    # third party answers: wrong subject → ignored
    assert store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:9999",
        reply_message_id="m-3",
        reply_to_message_id="m-1",
        text="是的",
    ) is None
    # right subject, plain @ to bot (no reply binding) → still waiting
    assert store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-4",
        reply_to_message_id=None,
        text="嗯",
    ) is None
    # expiry resolves UNANSWERED with tombstone + rejection
    assert store.resolve_expired() != []
    assert _candidate_status(tmp_path) == "REJECTED"


def test_bound_affirmative_confirms_but_does_not_promote(tmp_path) -> None:
    store = _store(tmp_path)
    _insert_candidate(tmp_path)
    assert _open(store) is True
    assert store.mark_sent("cand-1", ["m-1"], verification_window_seconds=600.0)
    verdict = store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-5",
        reply_to_message_id="m-1",
        text="对的",
    )
    assert verdict == "CONFIRMED"
    # confirmation records the relation only; candidate status untouched
    # (no auto-promotion, no accepted evidence under current contract)
    assert _candidate_status(tmp_path) == "OBSERVING"
    # no tombstone for a confirmation
    assert store.claim_rejected(
        owner_key=CLAIM["owner_key"], audience=CLAIM["audience"],
        fact_key=CLAIM["fact_key"], subject_key=CLAIM["subject_key"],
    ) is None


def test_evasive_reply_is_unclear_and_terminal(tmp_path) -> None:
    store = _store(tmp_path)
    _insert_candidate(tmp_path)
    assert _open(store) is True
    assert store.mark_sent("cand-1", ["m-1"], verification_window_seconds=600.0)
    verdict = store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-6",
        reply_to_message_id="m-1",
        text="怎么说呢，不好说",
    )
    assert verdict == "UNCLEAR"
    assert _candidate_status(tmp_path) == "REJECTED"


def test_cancelled_and_unknown_settlement_states(tmp_path) -> None:
    store = _store(tmp_path)
    assert _open(store) is True
    assert store.mark_cancelled("cand-1", "all_segments_failed")
    # cancelled claim can be attempted again (nothing was delivered)
    assert _open(store, candidate_id="cand-1") is True
    assert store.mark_delivery_unknown("cand-1", "delivery_receipts_unresolved")
    # unknown occupies the claim: no re-ask while it is in flight
    assert _open(store, candidate_id="cand-1") is False


def test_startup_recovery_sending_becomes_delivery_unknown(tmp_path) -> None:
    store = _store(tmp_path)
    assert _open(store) is True
    # crash between reserve and ACK: state stuck at RESERVED/SENDING
    db = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE memory_verification_attempts SET state='SENDING'"
        " WHERE candidate_id='cand-1'"
    )
    conn.commit()
    conn.close()
    recovered = store.recover_on_startup()
    assert recovered["unknown"] == 1
    conn = sqlite3.connect(db)
    state = conn.execute(
        "SELECT state FROM memory_verification_attempts WHERE candidate_id='cand-1'"
    ).fetchone()[0]
    conn.close()
    assert state == "DELIVERY_UNKNOWN"


def test_old_source_replay_blocked_and_new_evidence_allowed(tmp_path) -> None:
    store = _store(tmp_path)
    assert _open(store) is True
    assert store.mark_sent("cand-1", ["m-1"], verification_window_seconds=0.0)
    assert store.resolve_expired()
    common = {
        "owner_key": CLAIM["owner_key"],
        "audience": CLAIM["audience"],
        "fact_key": CLAIM["fact_key"],
        "subject_key": CLAIM["subject_key"],
    }
    # A/B/A: same sources re-extracted under a new UUID → blocked
    assert store.resurrection_blocked(
        source_row_ids=[11, 12], source_digests=["d1", "d2"], **common
    ) is not None
    # subset replay → blocked
    assert store.resurrection_blocked(
        source_row_ids=[11], source_digests=["d1"], **common
    ) is not None
    # fresh, direct user-provided evidence (new row ids) → allowed
    assert store.resurrection_blocked(
        source_row_ids=[77, 78], source_digests=["d77", "d78"], **common
    ) is None


def test_cas_reject_does_not_overwrite_terminal_status(tmp_path) -> None:
    store = _store(tmp_path)
    _insert_candidate(tmp_path, status="CONFIRMED")
    assert _open(store) is True
    assert store.mark_sent("cand-1", ["m-1"], verification_window_seconds=0.0)
    store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-9",
        reply_to_message_id="m-1",
        text="不对",
    )
    # candidate already terminal: CAS must not downgrade it
    assert _candidate_status(tmp_path) == "CONFIRMED"


def test_negative_marker_in_long_sentence_is_denied(tmp_path) -> None:
    from mneme.verification import _classify_reply_text

    assert _classify_reply_text("嗯") == "CONFIRMED"
    assert _classify_reply_text("不玩那个了") == "DENIED"
    assert _classify_reply_text("你看这个新出的番真好看") == "UNCLEAR"
    assert _classify_reply_text("") == "UNCLEAR"


@pytest.mark.parametrize("state", ["PENDING_VERIFICATION"])
def test_late_reply_never_revives_old_attempt(tmp_path, state) -> None:
    store = _store(tmp_path)
    assert _open(store) is True
    assert store.mark_sent("cand-1", ["m-1"], verification_window_seconds=0.0)
    assert store.resolve_expired()
    # late reply after expiry: no attempt in flight → nothing to settle
    assert store.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key="qq:1001",
        reply_message_id="m-late",
        reply_to_message_id="m-1",
        text="对",
    ) is None
