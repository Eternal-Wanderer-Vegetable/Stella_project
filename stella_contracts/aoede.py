# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Neutral Aoede / Mneme contracts (ports and immutable DTOs).

Aoede is the proactive participation subsystem (whether/when/whom to speak,
opportunity timing, budgets, one-shot verification scheduling). Mneme is the
memory subsystem (sources, retrieval, evidence, candidate lifecycle). Neither
package imports the other; both depend only on this module.

Import safety contract: this module is stdlib-only. It must not import
NoneBot, SQLite bindings beyond :mod:`sqlite3`-free helpers, ``config``,
``memory``, ``mneme``, or ``aoede``, and it must not read files, environment
variables, or start threads at import time (2026-11-03 plan §3/§S1-01).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

CONTRACT_VERSION = 1

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")

#: Actions an opportunity may plan (plan §6.2 step 5).
ACTIONS = frozenset({"REACT", "CONTRIBUTE", "ASK", "CONTINUE", "SKIP"})

#: Timing-layer outcomes (plan §6.2 step 3).
TIMING_DECISIONS = frozenset({"SPEAK", "WAIT", "DROP"})

#: Verification attempt lifecycle states (plan §6.4).
ATTEMPT_STATES = frozenset(
    {
        "RESERVED",
        "SENDING",
        "PENDING_VERIFICATION",
        "CONFIRMED",
        "DENIED",
        "UNANSWERED",
        "UNCLEAR",
        "CANCELLED",
        "DELIVERY_UNKNOWN",
    }
)

#: States that close an attempt permanently.
TERMINAL_ATTEMPT_STATES = frozenset(
    {"CONFIRMED", "DENIED", "UNANSWERED", "UNCLEAR", "CANCELLED"}
)

#: Settlement verdicts reported by :meth:`MnemeCandidatePort.settle`.
SETTLEMENT_STATUSES = frozenset({"applied", "rejected", "conflict", "unavailable"})


class AoedeContractError(ValueError):
    """A value does not satisfy the Aoede/Mneme contract."""


def _require_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise AoedeContractError(f"invalid {name}: must match {_ID_PATTERN.pattern!r}")


def _require_state(value: str, allowed: frozenset[str], name: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise AoedeContractError(f"invalid {name}: {value!r} not in {sorted(allowed)}")


@dataclass(frozen=True)
class ScopedIdentity:
    """Opaque, fully scoped identity of one conversation/target.

    All fields are opaque strings; raw integers (QQ group/user ids) must be
    stringified and prefixed by the caller. Sharing a numeric group id across
    connections or bots is a contract violation (plan §6.2 identity rule).
    """

    connection_id: str
    bot_ref: str
    conversation_key: str
    subject_key: str = ""

    def __post_init__(self) -> None:
        _require_id(self.connection_id, "connection_id")
        _require_id(self.bot_ref, "bot_ref")
        _require_id(self.conversation_key, "conversation_key")
        if self.subject_key:
            _require_id(self.subject_key, "subject_key")

    @property
    def budget_scope(self) -> str:
        """Budget bucket key: same connection+bot+conversation shares one budget."""
        return f"{self.connection_id}|{self.bot_ref}|{self.conversation_key}"


@dataclass(frozen=True)
class ParticipationOpportunity:
    """One in-flight chance for Aoede to speak (plan §6.2).

    Exactly one opportunity may be in flight per conversation; a new valid
    human message bumps ``context_revision`` and merges the candidate rather
    than stacking a second opportunity.
    """

    opportunity_id: str
    identity: ScopedIdentity
    trigger_message_key: str
    context_revision: int
    topic_revision: int
    created_at: float
    expires_at: float
    action: str = "CONTRIBUTE"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_id(self.opportunity_id, "opportunity_id")
        _require_id(self.trigger_message_key, "trigger_message_key")
        if isinstance(self.context_revision, bool) or self.context_revision < 0:
            raise AoedeContractError("context_revision must be a non-negative int")
        if isinstance(self.topic_revision, bool) or self.topic_revision < 0:
            raise AoedeContractError("topic_revision must be a non-negative int")
        if self.action not in ACTIONS:
            raise AoedeContractError(f"invalid action: {self.action!r}")
        if self.expires_at <= self.created_at:
            raise AoedeContractError("expires_at must be after created_at")


@dataclass(frozen=True)
class MemoryQuery:
    """A scoped, topic-typed retrieval request into Mneme (plan §6.3)."""

    identity: ScopedIdentity
    topic_query: str
    budget_items: int = 8
    deadline: float | None = None
    scope_versions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.budget_items, bool) or self.budget_items < 0:
            raise AoedeContractError("budget_items must be a non-negative int")


@dataclass(frozen=True)
class MemoryMaterials:
    """Retrieval result partition (plan §6.3 MnemeMemoryPort).

    ``materials`` holds only memory already cleared for the audience;
    ``constraints`` holds boundary/privacy memory as constraints only.
    ``status`` reports scope epochs so callers can re-validate before send.
    Empty materials are a normal value (context-only participation), never an
    error; ``unavailable=True`` marks retrieval failure as typed unavailable.
    """

    materials: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    status: Mapping[str, Any] = field(default_factory=dict)
    scope_epochs: Mapping[str, int] = field(default_factory=dict)
    unavailable: bool = False
    unavailable_reason: str = ""

    def __post_init__(self) -> None:
        if self.unavailable and not self.unavailable_reason:
            raise AoedeContractError("unavailable requires unavailable_reason")


@dataclass(frozen=True)
class CandidateSnapshot:
    """Immutable view of one Mneme candidate offered for verification.

    Carries the evidence-set digest and generation so Aoede can never be
    tricked into re-asking an old candidate under a fresh id (plan §6.4).
    """

    candidate_id: str
    generation: int
    content: str
    memory_type: str
    fact_key: str
    claim_key: str
    evidence_digest: str
    evidence_ids: tuple[str, ...]
    source_row_ids: tuple[int, ...]
    source_digests: tuple[str, ...]
    owner_type: str
    owner_key: str
    audience: str
    captured_scope_versions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_id(self.candidate_id, "candidate_id")
        if isinstance(self.generation, bool) or self.generation < 1:
            raise AoedeContractError("generation must be a positive int")
        if len(self.evidence_ids) != len(self.source_row_ids) or len(
            self.evidence_ids
        ) != len(self.source_digests):
            raise AoedeContractError("evidence ids/row ids/digests length mismatch")


@dataclass(frozen=True)
class VerificationAttempt:
    """Durable one-shot verification record (plan §6.4 minimum fields).

    ``state`` walks RESERVED → SENDING → PENDING_VERIFICATION → a terminal
    state. ``question_message_ids`` lists every physical fragment id so
    settlement can bind a user reply to this attempt and nothing else.
    """

    attempt_id: str
    opportunity_id: str
    snapshot: CandidateSnapshot
    identity: ScopedIdentity
    question_message_ids: tuple[str, ...] = ()
    state: str = "RESERVED"
    deadline: float | None = None
    lease_owner: str = ""
    lease_expiry: float | None = None
    settlement_operation_id: str = ""

    def __post_init__(self) -> None:
        _require_id(self.attempt_id, "attempt_id")
        _require_id(self.opportunity_id, "opportunity_id")
        _require_state(self.state, ATTEMPT_STATES, "attempt state")


@dataclass(frozen=True)
class SettlementOutcome:
    """Result of settling a user reply (or expiry) against an attempt."""

    status: str
    attempt_id: str
    reason: str = ""

    def __post_init__(self) -> None:
        _require_state(self.status, SETTLEMENT_STATUSES, "settlement status")
        _require_id(self.attempt_id, "attempt_id")


@dataclass(frozen=True)
class BudgetReservation:
    """Result of an atomic budget reserve (plan §6.5).

    ``granted=False`` with a reason means the opportunity must not generate
    or send. ``unknown=True`` means the budget store could not be reached and
    the caller must fail closed.
    """

    operation_id: str
    scope_key: str
    granted: bool = False
    unknown: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        _require_id(self.operation_id, "operation_id")
        if self.unknown and self.granted:
            raise AoedeContractError("a reservation cannot be both granted and unknown")


@dataclass(frozen=True)
class DeliveryReceipt:
    """Per-segment outbound receipt fed back to Aoede for settlement."""

    segment_index: int
    message_id: str
    status: str
    error_code: str = ""


@runtime_checkable
class ClockPort(Protocol):
    """Injected clock: wall time (UTC epoch seconds) and monotonic time."""

    def now(self) -> float: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class MnemeMemoryPort(Protocol):
    """Aoede's read-only view of Mneme retrieval (plan §6.3)."""

    def retrieve(self, query: MemoryQuery) -> MemoryMaterials: ...


@runtime_checkable
class MnemeCandidatePort(Protocol):
    """Candidate lifecycle operations Aoede may request from Mneme.

    Aoede never touches candidate tables directly and never writes
    confidence or promotion decisions; only Mneme validates evidence.
    """

    def offer(
        self,
        identity: ScopedIdentity,
        topic_query: str,
        subject_key: str,
        audience: str,
    ) -> CandidateSnapshot | None: ...

    def open_attempt(
        self,
        snapshot: CandidateSnapshot,
        identity: ScopedIdentity,
        opportunity_id: str,
        deadline: float,
    ) -> VerificationAttempt: ...

    def mark_sent(
        self,
        attempt_id: str,
        question_message_ids: Sequence[str],
        sent_at: float,
        verification_window_seconds: float,
    ) -> VerificationAttempt: ...

    def mark_delivery_unknown(self, attempt_id: str, at: float) -> VerificationAttempt: ...

    def settle(
        self,
        attempt_id: str,
        reply_message_key: str,
        reply_text: str,
        reply_sender_key: str,
        at: float,
    ) -> SettlementOutcome: ...

    def resolve_expiry(self, attempt_id: str, at: float) -> SettlementOutcome: ...

    def recover_overdue(self, at: float) -> Sequence[VerificationAttempt]: ...


@runtime_checkable
class AoedeBudgetPort(Protocol):
    """Atomic persistent proactive budget (plan §6.5).

    One bucket per :attr:`ScopedIdentity.budget_scope`; all autonomous
    proactive kinds share it. Operations are idempotent per ``operation_id``.
    """

    def reserve(
        self,
        identity: ScopedIdentity,
        operation_id: str,
        kind: str,
    ) -> BudgetReservation: ...

    def commit(self, operation_id: str, identity: ScopedIdentity) -> BudgetReservation: ...

    def release(self, operation_id: str, identity: ScopedIdentity) -> BudgetReservation: ...

    def resolve_unknown(self, operation_id: str, identity: ScopedIdentity) -> BudgetReservation: ...


@runtime_checkable
class HostGenerationPort(Protocol):
    """Host-side generation entry (RuntimeFacade/TurnService adapter)."""

    def generate(
        self,
        opportunity: ParticipationOpportunity,
        materials: MemoryMaterials,
        *,
        deadline: float | None = None,
    ) -> Any: ...


@runtime_checkable
class HostDeliveryPort(Protocol):
    """Host-side delivery entry (existing Outbound pipeline adapter)."""

    def deliver(
        self,
        opportunity: ParticipationOpportunity,
        lines: Sequence[str],
        *,
        deadline: float | None = None,
    ) -> Sequence[DeliveryReceipt]: ...


@runtime_checkable
class UnitOfWorkPort(Protocol):
    """Single transaction spanning Aoede settlement and Mneme writes.

    Implementations must provide one ``BEGIN IMMEDIATE``-backed transaction
    so "send settlement + candidate terminal state" commits atomically;
    repositories sharing it must not call ``conn.commit`` themselves.
    """

    def transaction(self) -> Any: ...


__all__ = [
    "ACTIONS",
    "ATTEMPT_STATES",
    "CONTRACT_VERSION",
    "SETTLEMENT_STATUSES",
    "TERMINAL_ATTEMPT_STATES",
    "TIMING_DECISIONS",
    "AoedeBudgetPort",
    "AoedeContractError",
    "BudgetReservation",
    "CandidateSnapshot",
    "ClockPort",
    "DeliveryReceipt",
    "HostDeliveryPort",
    "HostGenerationPort",
    "MemoryMaterials",
    "MemoryQuery",
    "MnemeCandidatePort",
    "MnemeMemoryPort",
    "ParticipationOpportunity",
    "ScopedIdentity",
    "SettlementOutcome",
    "UnitOfWorkPort",
    "VerificationAttempt",
]
