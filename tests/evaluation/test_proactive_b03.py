# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""B03 PITCH timing audit and coupled virtual-time mechanism tests."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

import aoede.budget as budget_module
import mneme.verification as verification_module
from aoede.budget import ProactiveBudgetStore
from aoede.opportunity import (
    DEFAULT_DEBOUNCE_SECONDS,
    DEFAULT_TTL_SECONDS,
)
from config import PROACTIVE_COOLDOWN
from core.evaluation.clock import VirtualClock
from mneme.schema import create_memory_candidates_table
from mneme.verification import (
    DEFAULT_VERIFICATION_WINDOW_SECONDS,
    MnemeVerificationStore,
)
from proactive_eval.b03 import build_synthetic_timing_sensitivity
from proactive_eval.pitch_windows import (
    audit_pitch_windows,
    load_pitch_windows,
    score_pitch_placements,
)
from proactive_eval.virtual_time import VirtualTimeDriver

CLAIM = {
    "owner_key": "space:g1",
    "audience": "CURRENT_SPACE",
    "fact_key": "fact:likes-hiking",
    "subject_key": "qq:1001",
}


class _ClockDateTime(datetime):
    source: VirtualTimeDriver | None = None

    @classmethod
    def now(cls, tz=None):
        if cls.source is None:
            return super().now(tz=tz)
        current = cls.source.now()
        return current.astimezone(tz) if tz is not None else current.replace(tzinfo=None)


def _install_virtual_utc(monkeypatch, driver: VirtualTimeDriver) -> None:
    monkeypatch.setattr(_ClockDateTime, "source", driver)
    monkeypatch.setattr(budget_module, "datetime", _ClockDateTime)
    monkeypatch.setattr(verification_module, "datetime", _ClockDateTime)


def _prepare_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    create_memory_candidates_table(conn)
    budget = ProactiveBudgetStore(str(db_path))
    verification = MnemeVerificationStore(str(db_path))
    budget.ensure_tables(conn)
    verification.ensure_tables(conn)
    conn.commit()
    conn.close()


def _insert_candidate(db_path: Path, candidate_id: str = "cand-1") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO memory_candidates (id, group_shared_space, user_id,"
        " type, content, importance, confidence, evidence, status,"
        " source_message_ids, owner_type, owner_key, subject_key, audience, fact_key)"
        " VALUES (?, 'space:g1', 1001, 'FACT', 'likes hiking', 0.8, 0.7, '',"
        " 'OBSERVING', '[11, 12]', 'SPACE', ?, ?, ?, ?)",
        (candidate_id, CLAIM["owner_key"], CLAIM["subject_key"], CLAIM["audience"],
         CLAIM["fact_key"]),
    )
    conn.commit()
    conn.close()


def _pitch_rows(tmp_path: Path) -> tuple[Path, str]:
    rows = [
        {
            "knowledge_item_id": "p1", "conversation_id": "c1", "n_turns": 8,
            "start_turn": 2, "end_turn": 8,
            "ground_truth": {"acceptable_windows": [[3, 5], [4, 6]], "do_not_surface": False},
            "individual_annotations": [{"do_not_surface": False}, {"do_not_surface": True}],
        },
        {
            "knowledge_item_id": "p2", "conversation_id": "c1", "n_turns": 8,
            "start_turn": 1, "end_turn": 8,
            "ground_truth": {"acceptable_windows": [[2, 2], [3, 3]], "do_not_surface": False},
            "individual_annotations": [{"do_not_surface": False}],
        },
        {
            "knowledge_item_id": "p3", "conversation_id": "c2", "n_turns": 4,
            "start_turn": 1, "end_turn": 4,
            "ground_truth": {"acceptable_windows": [], "do_not_surface": True},
            "individual_annotations": [],
        },
    ]
    path = tmp_path / "pitch.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    from proactive_eval.pitch_windows import sha256_file

    return path, sha256_file(path)


def test_pitch_intersections_preserve_full_denominator(tmp_path: Path) -> None:
    source, digest = _pitch_rows(tmp_path)
    report = audit_pitch_windows(
        source,
        expected_sha256=digest,
        revision="test-revision",
        license_name="MIT",
        expected_candidates=3,
        expected_conversations=2,
        expected_annotations=3,
    )
    assert report["counts"]["candidates"] == 3
    assert report["counts"]["scoreable_intersection_windows"] == 1
    assert report["counts"]["no_intersection_candidates"] == 2
    assert report["counts"]["candidates_with_any_do_not_surface_annotation"] == 1
    assert report["source"]["label_side"] == "scorer_only"
    assert "turns" not in report and "raw_ideal_response" not in report

    scored = score_pitch_placements(
        load_pitch_windows(source, expected_sha256=digest),
        {"p1": 3, "p2": 2, "p3": None},
    )
    assert scored["early"] == 1
    assert scored["missed"] == 0
    assert scored["no_intersection"] == 2
    assert scored["placement_on_no_intersection"] == 1


def test_pitch_rejects_bad_hash_and_keeps_every_placement_id(tmp_path: Path) -> None:
    source, digest = _pitch_rows(tmp_path)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_pitch_windows(source, expected_sha256="0" * 64)
    rows = load_pitch_windows(source, expected_sha256=digest)
    with pytest.raises(ValueError, match="placement ID mismatch"):
        score_pitch_placements(rows, {"p1": None})


async def test_virtual_time_driver_advances_utc_monotonic_and_timers_together() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    driver = VirtualTimeDriver(start=start)
    fired: list[tuple[float, datetime]] = []
    driver.call_later(3.0, lambda: fired.append((driver.monotonic(), driver.now())))
    await driver.advance(2.0)
    assert fired == []
    await driver.advance(1.0)
    assert fired == [(3.0, start + timedelta(seconds=3))]
    assert driver.wall_clock.now() == start + timedelta(seconds=3)
    assert driver.monotonic() == 3.0
    assert isinstance(driver.wall_clock, VirtualClock)
    with pytest.raises(ValueError, match="non-negative"):
        await driver.advance(-1)


async def test_budget_and_verification_deadlines_share_virtual_utc(
    tmp_path: Path, monkeypatch
) -> None:
    driver = VirtualTimeDriver(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _install_virtual_utc(monkeypatch, driver)
    db_path = tmp_path / "agent_memory.db"
    _prepare_db(db_path)
    budget = ProactiveBudgetStore(str(db_path))
    verification = MnemeVerificationStore(str(db_path))

    assert not budget.reserve("scope:g1", "op-empty", frequency_per_hour=1.0).granted
    await driver.advance(3599)
    assert not budget.reserve("scope:g1", "op-before-hour", frequency_per_hour=1.0).granted
    await driver.advance(1)
    assert budget.reserve("scope:g1", "op-hour", frequency_per_hour=1.0).granted
    assert budget.commit("op-hour")
    assert not budget.reserve("scope:g1", "op-capacity", frequency_per_hour=1.0).granted

    _insert_candidate(db_path)
    assert verification.open_attempt(
        candidate_id="cand-1",
        candidate_content_digest="digest-1",
        owner_type="SPACE",
        owner_key=CLAIM["owner_key"],
        subject_key=CLAIM["subject_key"],
        audience=CLAIM["audience"],
        fact_key=CLAIM["fact_key"],
        evidence_digest="evidence-1",
        evidence_ids=["e1"],
        source_row_ids=[11],
        source_digests=["d1"],
        bot_ref="legacy-qq:10000",
        connection_id="legacy-qq:10000",
        conversation_key="qq:10000:group:1",
        opportunity_id="opp-1",
    )
    assert verification.mark_sent(
        "cand-1", ["question-1"],
        verification_window_seconds=DEFAULT_VERIFICATION_WINDOW_SECONDS,
    )
    expired: list[list[str]] = []
    driver.call_later(
        DEFAULT_VERIFICATION_WINDOW_SECONDS,
        lambda: expired.append(verification.resolve_expired(now=driver.now())),
    )
    assert verification.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key=CLAIM["subject_key"],
        reply_message_id="unbound-before-deadline",
        reply_to_message_id=None,
        text="对的",
    ) is None
    await driver.advance(DEFAULT_VERIFICATION_WINDOW_SECONDS - 1)
    assert expired == []
    await driver.advance(1)
    assert len(expired) == 1 and len(expired[0]) == 1
    # A bound reply arriving after the deadline cannot revive the terminal attempt.
    assert verification.settle_reply(
        conversation_key="qq:10000:group:1",
        subject_key=CLAIM["subject_key"],
        reply_message_id="late-reply",
        reply_to_message_id="question-1",
        text="对的",
    ) is None
    tombstone = verification.claim_rejected(
        owner_key=CLAIM["owner_key"], audience=CLAIM["audience"],
        fact_key=CLAIM["fact_key"], subject_key=CLAIM["subject_key"],
    )
    assert tombstone is not None
    with sqlite3.connect(db_path) as conn:
        state = conn.execute(
            "SELECT status FROM memory_candidates WHERE id='cand-1'"
        ).fetchone()[0]
    assert state == "REJECTED"


def test_budget_and_verification_claims_are_single_winner_under_concurrency(
    tmp_path: Path, monkeypatch
) -> None:
    driver = VirtualTimeDriver(start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    _install_virtual_utc(monkeypatch, driver)
    db_path = tmp_path / "concurrent.db"
    _prepare_db(db_path)
    store = ProactiveBudgetStore(str(db_path))
    with sqlite3.connect(db_path) as conn:
        stamp = driver.now().isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO aoede_proactive_budget (scope_key,tokens,last_refill_utc,"
            "config_frequency,updated_at_utc) VALUES ('scope:g1',1.0,?,1.0,?)",
            (stamp, stamp),
        )
    barrier = Barrier(8)

    def reserve(index: int):
        barrier.wait(timeout=5)
        return store.reserve(
            "scope:g1", f"thread-op-{index}", frequency_per_hour=1.0
        ).granted

    with ThreadPoolExecutor(max_workers=8) as pool:
        grants = list(pool.map(reserve, range(8)))
    assert grants.count(True) == 1

    verify = MnemeVerificationStore(str(db_path))
    claim_barrier = Barrier(2)

    def open_claim(candidate_id: str) -> bool:
        claim_barrier.wait(timeout=5)
        return verify.open_attempt(
            candidate_id=candidate_id,
            candidate_content_digest=f"digest-{candidate_id}",
            owner_type="SPACE", owner_key=CLAIM["owner_key"],
            subject_key=CLAIM["subject_key"], audience=CLAIM["audience"],
            fact_key=CLAIM["fact_key"], evidence_digest="same-evidence",
            evidence_ids=["e1"], source_row_ids=[11], source_digests=["d1"],
            bot_ref="legacy-qq:10000", connection_id="legacy-qq:10000",
            conversation_key="qq:10000:group:1",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = list(pool.map(open_claim, ("cand-a", "cand-b")))
    assert attempts.count(True) == 1


async def test_generated_output_is_dropped_after_topic_revision_changes(monkeypatch) -> None:
    import contextlib

    import aoede.service as service

    revision = 0
    decisions = []
    sent = []

    class _ReplyGate:
        def evaluate(self, *_args, **_kwargs):
            return SimpleNamespace(allowed=True, path="proactive", score=1.0, reasons=())

        def start(self, *_args, **_kwargs):
            return None

        def finish(self, *_args, **_kwargs):
            return None

    class _Participation:
        def topic_revision(self, _group_id):
            return revision

    async def run_turn(_runtime_key, ctx):
        nonlocal revision
        ctx.lines = ["stale draft"]
        revision += 1
        return ctx

    host = SimpleNamespace(
        can_speak=lambda *_args: (True, ""),
        get_proactive=lambda: SimpleNamespace(should_speak=lambda _gid: True),
        group_locks={1: asyncio.Lock()},
        get_reply_gate=lambda: _ReplyGate(),
        register_group_ref=lambda _bot_id, _group_id: SimpleNamespace(
            conversation_key="qq:10000:group:1",
            storage_session_id=1,
            runtime_key="qq:10000:group:1",
        ),
        get_consolidator=lambda: SimpleNamespace(
            has_new_messages_to_consolidate=lambda *_args, **_kwargs: 0
        ),
        get_participation_manager=lambda: _Participation(),
        run_turn=run_turn,
        flow_span=lambda *_args, **_kwargs: contextlib.nullcontext(),
        flow_decision=lambda *args, **kwargs: decisions.append((args, kwargs)),
        flow_set_outcome=lambda *_args, **_kwargs: None,
        flow_checkpoint=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(service, "new_turn_deadline", lambda: None)
    monkeypatch.setattr("gravitas.controller.active_controller", lambda: None)

    async def scenario():
        await service.proactive_speak_impl(
            host,
            SimpleNamespace(self_id="10000"),
            1,
            intent="participation_TOPIC_INTEREST",
            skip_dice=True,
            decision=SimpleNamespace(group_id=1, mode="TOPIC_INTEREST"),
        )

    await scenario()
    assert any(kwargs.get("reason_code") == "stale_output" for _, kwargs in decisions)
    assert sent == []


async def test_frozen_mechanism_constants_match_loaded_report(tmp_path: Path) -> None:
    source, digest = _pitch_rows(tmp_path)
    report = audit_pitch_windows(
        source,
        expected_sha256=digest,
        revision="test-revision",
        license_name="MIT",
        expected_candidates=3,
        expected_conversations=2,
        expected_annotations=3,
    )
    report["timing_contract"] = {
        "opportunity_debounce_seconds": DEFAULT_DEBOUNCE_SECONDS,
        "opportunity_ttl_seconds": DEFAULT_TTL_SECONDS,
        "proactive_cooldown_seconds": PROACTIVE_COOLDOWN,
        "verification_window_seconds": DEFAULT_VERIFICATION_WINDOW_SECONDS,
        "pitch_window_unit": "turn",
        "synthetic_arrivals_used_as_pitch_truth": False,
    }
    report["synthetic_timing_sensitivity"] = (
        await build_synthetic_timing_sensitivity()
    )
    report = json.loads(json.dumps(report))
    schema = json.loads(
        Path("proactive_eval/schemas/pitch-window-audit-1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(report)
    assert report["timing_contract"] == {
        "opportunity_debounce_seconds": DEFAULT_DEBOUNCE_SECONDS,
        "opportunity_ttl_seconds": DEFAULT_TTL_SECONDS,
        "proactive_cooldown_seconds": PROACTIVE_COOLDOWN,
        "verification_window_seconds": DEFAULT_VERIFICATION_WINDOW_SECONDS,
        "pitch_window_unit": "turn",
        "synthetic_arrivals_used_as_pitch_truth": False,
    }
    assert len(report["synthetic_timing_sensitivity"]["intervals"]) == 3
