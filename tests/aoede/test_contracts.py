# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""S1-01 contract tests for stella_contracts.aoede (plan §7 S1-01).

Checks the neutral port module is import-safe (no NoneBot/config/memory/
aoede/mneme side effects), DTO validation rejects malformed identities, and
fake port implementations satisfy the runtime-checkable protocols.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _identity(**overrides):
    from stella_contracts.aoede import ScopedIdentity

    fields = {
        "connection_id": "legacy-qq:10000",
        "bot_ref": "legacy-qq:10000",
        "conversation_key": "qq:10000:group:12345",
        "subject_key": "qq:67890",
    }
    fields.update(overrides)
    return ScopedIdentity(**fields)


def test_contract_import_is_side_effect_free() -> None:
    """Importing the contract module must not pull runtime subsystems in."""
    code = (
        "import sys; import stella_contracts.aoede; "
        "banned = ('nonebot', 'config', 'memory', 'mneme', 'aoede', 'sqlite3.util'); "
        "leaked = [m for m in sys.modules if m.split('.')[0] in banned]; "
        "print(leaked); assert not leaked, leaked"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


def test_contract_module_never_imports_subsystems() -> None:
    """Source-level dependency direction: contracts import neither side."""
    source = (PROJECT_ROOT / "stella_contracts" / "aoede.py").read_text(
        encoding="utf-8"
    )
    for banned in ("import aoede", "import mneme", "from aoede", "from mneme",
                   "from memory", "import memory", "from config", "import nonebot"):
        assert banned not in source, banned


def test_scoped_identity_and_budget_scope() -> None:
    identity = _identity()
    assert identity.budget_scope == "legacy-qq:10000|legacy-qq:10000|qq:10000:group:12345"
    # distinct bots in the same group must not share a budget bucket
    other_bot = _identity(bot_ref="legacy-qq:20000")
    assert other_bot.budget_scope != identity.budget_scope


def test_scoped_identity_rejects_raw_integers() -> None:
    import pytest

    from stella_contracts.aoede import AoedeContractError

    with pytest.raises(AoedeContractError):
        _identity(conversation_key=12345)  # type: ignore[arg-type]


def test_opportunity_validation() -> None:
    import pytest

    from stella_contracts.aoede import AoedeContractError, ParticipationOpportunity

    opp = ParticipationOpportunity(
        opportunity_id="opp-1",
        identity=_identity(subject_key=""),
        trigger_message_key="qq:10000:group:12345:msg:42",
        context_revision=1,
        topic_revision=0,
        created_at=1000.0,
        expires_at=1015.0,
        action="CONTRIBUTE",
        reason_codes=("warmup_passed",),
    )
    assert opp.action == "CONTRIBUTE"
    with pytest.raises(AoedeContractError):
        ParticipationOpportunity(
            opportunity_id="opp-2",
            identity=_identity(subject_key=""),
            trigger_message_key="m",
            context_revision=0,
            topic_revision=0,
            created_at=1000.0,
            expires_at=1000.0,  # expiry not after creation
        )
    with pytest.raises(AoedeContractError):
        ParticipationOpportunity(
            opportunity_id="opp-3",
            identity=_identity(subject_key=""),
            trigger_message_key="m",
            context_revision=0,
            topic_revision=0,
            created_at=1000.0,
            expires_at=1015.0,
            action="YELL",  # not in ACTIONS
        )


def test_candidate_snapshot_length_mismatch_rejected() -> None:
    import pytest

    from stella_contracts.aoede import AoedeContractError, CandidateSnapshot

    with pytest.raises(AoedeContractError):
        CandidateSnapshot(
            candidate_id="cand-1",
            generation=1,
            content="likes hiking",
            memory_type="FACT",
            fact_key="fact:1",
            claim_key="fact:1",
            evidence_digest="digest-1",
            evidence_ids=("e1", "e2"),
            source_row_ids=(11,),
            source_digests=("d1", "d2"),
            owner_type="SPACE",
            owner_key="space:g",
            audience="CURRENT_SPACE",
        )


def test_attempt_states_and_settlement_validation() -> None:
    import pytest

    from stella_contracts.aoede import (
        AoedeContractError,
        CandidateSnapshot,
        SettlementOutcome,
        VerificationAttempt,
    )

    snapshot = CandidateSnapshot(
        candidate_id="cand-1",
        generation=3,
        content="likes hiking",
        memory_type="FACT",
        fact_key="fact:1",
        claim_key="fact:1",
        evidence_digest="digest-1",
        evidence_ids=("e1",),
        source_row_ids=(11,),
        source_digests=("d1",),
        owner_type="SPACE",
        owner_key="space:g",
        audience="CURRENT_SPACE",
    )
    attempt = VerificationAttempt(
        attempt_id="att-1",
        opportunity_id="opp-1",
        snapshot=snapshot,
        identity=_identity(subject_key=""),
        state="PENDING_VERIFICATION",
        deadline=1300.0,
    )
    assert attempt.state == "PENDING_VERIFICATION"
    with pytest.raises(AoedeContractError):
        SettlementOutcome(status="maybe", attempt_id="att-1")


def test_memory_materials_unavailable_requires_reason() -> None:
    import pytest

    from stella_contracts.aoede import AoedeContractError, MemoryMaterials

    assert MemoryMaterials().unavailable is False
    with pytest.raises(AoedeContractError):
        MemoryMaterials(unavailable=True)


def test_fake_ports_satisfy_protocols() -> None:
    """Fake implementations must typecheck against the runtime protocols."""
    from stella_contracts.aoede import (
        AoedeBudgetPort,
        ClockPort,
        MnemeCandidatePort,
        MnemeMemoryPort,
    )

    class FakeClock:
        def now(self) -> float:
            return 0.0

        def monotonic(self) -> float:
            return 0.0

    class FakeMemory:
        def retrieve(self, query):
            from stella_contracts.aoede import MemoryMaterials

            return MemoryMaterials()

    class FakeCandidates:
        def offer(self, identity, topic_query, subject_key, audience):
            return None

        def open_attempt(self, snapshot, identity, opportunity_id, deadline):
            raise NotImplementedError

        def mark_sent(self, attempt_id, question_message_ids, sent_at,
                      verification_window_seconds):
            raise NotImplementedError

        def mark_delivery_unknown(self, attempt_id, at):
            raise NotImplementedError

        def settle(self, attempt_id, reply_message_key, reply_text,
                   reply_sender_key, at):
            raise NotImplementedError

        def resolve_expiry(self, attempt_id, at):
            raise NotImplementedError

        def recover_overdue(self, at):
            return ()

    class FakeBudget:
        def reserve(self, identity, operation_id, kind):
            raise NotImplementedError

        def commit(self, operation_id, identity):
            raise NotImplementedError

        def release(self, operation_id, identity):
            raise NotImplementedError

        def resolve_unknown(self, operation_id, identity):
            raise NotImplementedError

    assert isinstance(FakeClock(), ClockPort)
    assert isinstance(FakeMemory(), MnemeMemoryPort)
    assert isinstance(FakeCandidates(), MnemeCandidatePort)
    assert isinstance(FakeBudget(), AoedeBudgetPort)
