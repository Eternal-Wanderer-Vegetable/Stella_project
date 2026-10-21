# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Bounded, in-process recovery facts for endpoint, provider, link and storage scopes.

The registry records passive outcomes and grants short active-probe leases. It is
diagnostic/control state only: it never invokes a dependency and never retries a
business operation. Callers keep their existing fail-closed and fallback rules.
"""

from __future__ import annotations

import hashlib
import random
import re
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from gravitas.contracts import HealthValue, ScopeKind


class StorageDomain(str, Enum):
    MEMORY = "memory"
    SOCIAL = "social"
    COMETA = "cometa"
    SCHEDULING = "scheduling"
    KNOWLEDGE = "knowledge"
    OBSERVABILITY = "observability"


class FailureKind(str, Enum):
    TRANSIENT = "transient"
    CONFIGURATION = "configuration"
    AUTHORIZATION = "authorization"
    CONTENTION = "contention"
    READ_ONLY = "read_only"
    DISK_FULL = "disk_full"
    UNAVAILABLE = "unavailable"
    CORRUPT = "corrupt"


_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_RETRYABLE = {FailureKind.TRANSIENT, FailureKind.CONTENTION, FailureKind.UNAVAILABLE}


@dataclass(frozen=True, slots=True)
class DependencyScope:
    kind: ScopeKind
    identifier: str

    def __post_init__(self) -> None:
        if self.kind not in {
            ScopeKind.ENDPOINT,
            ScopeKind.PROVIDER,
            ScopeKind.CONNECTION,
            ScopeKind.STORAGE,
        }:
            raise ValueError("recovery scope must identify one dependency")
        if not isinstance(self.identifier, str) or not _SAFE_SCOPE.fullmatch(self.identifier):
            raise ValueError("dependency scope identifier is not a safe bounded token")
        if self.kind is ScopeKind.STORAGE and self.identifier not in {
            item.value for item in StorageDomain
        }:
            raise ValueError("unknown storage domain")


@dataclass(frozen=True, slots=True)
class AttemptFence:
    scope: DependencyScope
    sequence: int


@dataclass(frozen=True, slots=True)
class ProbeLease:
    scope: DependencyScope
    lease_id: str
    expires_at: float
    generation: int


@dataclass(frozen=True, slots=True)
class DependencyFact:
    scope: DependencyScope
    health: HealthValue
    failure_kind: str
    consecutive_failures: int
    revision: int
    last_attempt_at: float | None
    last_probe_at: float | None
    last_success_at: float | None
    next_probe_at: float | None
    probe_in_flight: bool
    probes_in_window: int

    def to_dict(self, *, now: float) -> dict[str, Any]:
        return {
            "scope_kind": self.scope.kind.value,
            "scope_id": self.scope.identifier,
            "health": self.health.value,
            "failure_kind": self.failure_kind,
            "consecutive_failures": self.consecutive_failures,
            "revision": self.revision,
            "last_attempt_age_seconds": _age(now, self.last_attempt_at),
            "last_probe_age_seconds": _age(now, self.last_probe_at),
            "last_success_age_seconds": _age(now, self.last_success_at),
            "next_probe_in_seconds": _remaining(now, self.next_probe_at),
            "probe_in_flight": self.probe_in_flight,
            "probes_in_window": self.probes_in_window,
        }


@dataclass(slots=True)
class _Entry:
    scope: DependencyScope
    health: HealthValue = HealthValue.UNKNOWN
    failure_kind: str = ""
    failures: int = 0
    revision: int = 0
    attempt_sequence: int = 0
    latest_attempt_sequence: int = 0
    last_attempt_at: float | None = None
    last_probe_at: float | None = None
    last_success_at: float | None = None
    next_probe_at: float | None = None
    probe_lease: ProbeLease | None = None
    probe_times: deque[float] | None = None
    touched_at: float = 0.0


class DependencyRecovery:
    """Thread-safe finite state store with fenced outcomes and bounded probes."""

    def __init__(
        self,
        *,
        clock=time.monotonic,
        seed: int | None = None,
        max_scopes: int = 512,
        probe_window_seconds: float = 60.0,
        max_probes_per_scope: int = 3,
        global_probe_budget: int = 16,
        probe_lease_seconds: float = 10.0,
        base_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 300.0,
        jitter_fraction: float = 0.2,
    ) -> None:
        if max_scopes < 1 or max_probes_per_scope < 1 or global_probe_budget < 1:
            raise ValueError("recovery bounds must be positive")
        if probe_window_seconds <= 0 or probe_lease_seconds <= 0:
            raise ValueError("probe timings must be positive")
        if base_backoff_seconds <= 0 or max_backoff_seconds < base_backoff_seconds:
            raise ValueError("invalid backoff bounds")
        if not 0 <= jitter_fraction < 1:
            raise ValueError("jitter_fraction must be in [0, 1)")
        self._clock = clock
        self._rng = random.Random(seed)
        self._max_scopes = int(max_scopes)
        self._probe_window = float(probe_window_seconds)
        self._max_probes_per_scope = int(max_probes_per_scope)
        self._global_probe_budget = int(global_probe_budget)
        self._probe_lease_seconds = float(probe_lease_seconds)
        self._base_backoff = float(base_backoff_seconds)
        self._max_backoff = float(max_backoff_seconds)
        self._jitter_fraction = float(jitter_fraction)
        self._entries: OrderedDict[DependencyScope, _Entry] = OrderedDict()
        self._global_probe_times: deque[float] = deque()
        self._overflow_count = 0
        self._lock = threading.RLock()

    def begin_attempt(
        self, scope: DependencyScope, *, now: float | None = None
    ) -> AttemptFence | None:
        """Fence older in-flight outcomes when a newer business request starts."""
        at = self._now(now)
        with self._lock:
            entry = self._entry(scope, at)
            if entry is None:
                return None
            entry.attempt_sequence += 1
            entry.latest_attempt_sequence = entry.attempt_sequence
            entry.last_attempt_at = at
            entry.touched_at = at
            entry.revision += 1
            entry.probe_lease = None
            return AttemptFence(scope, entry.attempt_sequence)

    def record_attempt_result(
        self,
        fence: AttemptFence | None,
        *,
        success: bool,
        failure_kind: FailureKind | None = None,
        now: float | None = None,
    ) -> bool:
        """Apply a passive business result only if no later request superseded it."""
        if fence is None:
            return False
        at = self._now(now)
        with self._lock:
            entry = self._entries.get(fence.scope)
            if entry is None or entry.latest_attempt_sequence != fence.sequence:
                return False
            entry.revision += 1
            entry.probe_lease = None
            self._apply_result(entry, success, failure_kind, at, is_probe=False)
            return True

    def claim_probe(
        self,
        scope: DependencyScope,
        *,
        now: float | None = None,
        min_interval_seconds: float = 0.0,
        lease_seconds: float | None = None,
    ) -> ProbeLease | None:
        """Grant one expiring half-open lease inside per-scope and global budgets."""
        at = self._now(now)
        interval = max(0.0, float(min_interval_seconds))
        ttl = self._probe_lease_seconds if lease_seconds is None else float(lease_seconds)
        if ttl <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._lock:
            entry = self._entry(scope, at)
            if entry is None:
                return None
            if scope.kind is ScopeKind.STORAGE:
                # SQLite health comes from module errors or an explicit
                # maintenance check; never run an implicit hot-path probe.
                return None
            self._trim(entry.probe_times, at)
            self._trim(self._global_probe_times, at)
            lease = entry.probe_lease
            if lease is not None:
                if at < lease.expires_at:
                    return None
                entry.probe_lease = None
            if entry.next_probe_at is not None and at < entry.next_probe_at:
                return None
            if entry.health is HealthValue.INVALID or (
                entry.health is HealthValue.FAILED
                and entry.failure_kind
                in {
                    FailureKind.CONFIGURATION.value,
                    FailureKind.AUTHORIZATION.value,
                    FailureKind.READ_ONLY.value,
                    FailureKind.DISK_FULL.value,
                    FailureKind.CORRUPT.value,
                }
            ):
                return None
            if entry.last_probe_at is not None and at - entry.last_probe_at < interval:
                return None
            if len(entry.probe_times) >= self._max_probes_per_scope:
                return None
            if len(self._global_probe_times) >= self._global_probe_budget:
                return None
            lease = ProbeLease(
                scope,
                uuid.uuid4().hex,
                at + ttl,
                entry.revision,
            )
            entry.probe_lease = lease
            entry.touched_at = at
            entry.probe_times.append(at)
            self._global_probe_times.append(at)
            return lease

    def finish_probe(
        self,
        lease: ProbeLease,
        *,
        success: bool,
        failure_kind: FailureKind | None = None,
        now: float | None = None,
        next_probe_delay: float | None = None,
    ) -> bool:
        """Commit a probe result only while its lease and generation remain current."""
        at = self._now(now)
        with self._lock:
            entry = self._entries.get(lease.scope)
            if entry is None or entry.probe_lease != lease:
                return False
            if at >= lease.expires_at or entry.revision != lease.generation:
                entry.probe_lease = None
                return False
            entry.revision += 1
            entry.probe_lease = None
            self._apply_result(
                entry,
                success,
                failure_kind,
                at,
                is_probe=True,
                next_probe_delay=next_probe_delay,
            )
            return True

    def abandon_probe(
        self,
        lease: ProbeLease,
        *,
        now: float | None = None,
        retry_after: float = 1.0,
    ) -> bool:
        """Release a probe lease without converting queue pressure/cancellation to failure."""
        at = self._now(now)
        with self._lock:
            entry = self._entries.get(lease.scope)
            if entry is None or entry.probe_lease != lease:
                return False
            entry.probe_lease = None
            entry.last_probe_at = at
            entry.next_probe_at = at + max(0.0, float(retry_after))
            entry.touched_at = at
            return True

    def record_storage_failure(
        self,
        domain: StorageDomain | str,
        error: BaseException,
        *,
        now: float | None = None,
    ) -> bool:
        """Record only actionable SQLite failures; lock contention is not corruption."""
        try:
            parsed_domain = StorageDomain(domain)
        except ValueError:
            return False
        failure = classify_storage_failure(error)
        if failure is None:
            return False
        at = self._now(now)
        scope = DependencyScope(ScopeKind.STORAGE, parsed_domain.value)
        with self._lock:
            entry = self._entry(scope, at)
            if entry is None:
                return False
            entry.revision += 1
            entry.probe_lease = None
            self._apply_result(entry, False, failure, at, is_probe=False)
            # Storage has no automatic probe schedule; a caller must perform
            # an explicit maintenance check before reporting recovery.
            entry.next_probe_at = None
            return True

    def mark_storage_maintenance_success(
        self,
        domain: StorageDomain | str,
        *,
        check_passed: bool,
        now: float | None = None,
    ) -> bool:
        """Clear a storage fact only after an explicit caller-owned maintenance check."""
        if not check_passed:
            return False
        try:
            parsed_domain = StorageDomain(domain)
        except ValueError:
            return False
        at = self._now(now)
        scope = DependencyScope(ScopeKind.STORAGE, parsed_domain.value)
        with self._lock:
            entry = self._entry(scope, at)
            if entry is None:
                return False
            entry.revision += 1
            entry.probe_lease = None
            self._apply_result(entry, True, None, at, is_probe=False)
            return True

    def fact(
        self, scope: DependencyScope, *, now: float | None = None
    ) -> DependencyFact:
        at = self._now(now)
        with self._lock:
            entry = self._entries.get(scope)
            if entry is None:
                return DependencyFact(scope, HealthValue.UNKNOWN, "", 0, 0, None, None, None, None, False, 0)
            self._trim(entry.probe_times, at)
            return self._fact(entry)

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        at = self._now(now)
        with self._lock:
            facts = []
            for entry in self._entries.values():
                self._trim(entry.probe_times, at)
                facts.append(self._fact(entry).to_dict(now=at))
            return {
                "facts": facts,
                "probe_budget_used": len(self._trim(self._global_probe_times, at)),
                "probe_budget_limit": self._global_probe_budget,
                "scope_limit": self._max_scopes,
                "scope_overflow_count": self._overflow_count,
                "incomplete": self._overflow_count > 0,
            }

    def _fact(self, entry: _Entry) -> DependencyFact:
        return DependencyFact(
            scope=entry.scope,
            health=entry.health,
            failure_kind=entry.failure_kind,
            consecutive_failures=entry.failures,
            revision=entry.revision,
            last_attempt_at=entry.last_attempt_at,
            last_probe_at=entry.last_probe_at,
            last_success_at=entry.last_success_at,
            next_probe_at=entry.next_probe_at,
            probe_in_flight=entry.probe_lease is not None,
            probes_in_window=len(entry.probe_times),
        )

    def _entry(self, scope: DependencyScope, at: float) -> _Entry | None:
        entry = self._entries.get(scope)
        if entry is not None:
            self._entries.move_to_end(scope)
            return entry
        if len(self._entries) >= self._max_scopes:
            evictable = next(
                (key for key, value in self._entries.items() if value.probe_lease is None),
                None,
            )
            if evictable is None:
                self._overflow_count += 1
                return None
            del self._entries[evictable]
            self._overflow_count += 1
        entry = _Entry(scope=scope, touched_at=at, probe_times=deque())
        self._entries[scope] = entry
        return entry

    def _apply_result(
        self,
        entry: _Entry,
        success: bool,
        failure_kind: FailureKind | None,
        at: float,
        *,
        is_probe: bool,
        next_probe_delay: float | None = None,
    ) -> None:
        entry.touched_at = at
        if is_probe:
            entry.last_probe_at = at
        if success:
            entry.health = HealthValue.HEALTHY
            entry.failure_kind = ""
            entry.failures = 0
            entry.last_success_at = at
            entry.next_probe_at = (
                at + max(0.0, float(next_probe_delay))
                if next_probe_delay is not None
                else None
            )
            return
        kind = failure_kind or FailureKind.TRANSIENT
        entry.failure_kind = kind.value
        entry.failures += 1
        if kind is FailureKind.CORRUPT:
            entry.health = HealthValue.INVALID
        elif kind in {
            FailureKind.CONFIGURATION,
            FailureKind.AUTHORIZATION,
            FailureKind.READ_ONLY,
            FailureKind.DISK_FULL,
        }:
            entry.health = HealthValue.FAILED
        else:
            entry.health = HealthValue.DEGRADED
        if kind not in _RETRYABLE:
            entry.next_probe_at = None
            return
        delay = self._backoff_delay(entry.failures)
        if next_probe_delay is not None:
            delay = max(delay, max(0.0, float(next_probe_delay)))
        entry.next_probe_at = at + delay

    def _backoff_delay(self, failure_count: int) -> float:
        base = min(self._base_backoff * 2 ** max(0, failure_count - 1), self._max_backoff)
        jitter = self._rng.uniform(-self._jitter_fraction, self._jitter_fraction)
        return max(0.0, min(self._max_backoff, base * (1.0 + jitter)))

    def _trim(self, values: deque[float] | None, now: float) -> deque[float]:
        if values is None:
            return deque()
        while values and now - values[0] >= self._probe_window:
            values.popleft()
        return values

    def _now(self, supplied: float | None) -> float:
        value = float(self._clock() if supplied is None else supplied)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("recovery clock must be finite")
        return value


def classify_dependency_failure(error: BaseException) -> FailureKind:
    """Classify without retaining error text, URLs, credentials or request content."""
    message = str(error).casefold()
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    if isinstance(error, PermissionError) or status in (401, 403) or any(
        marker in message
        for marker in ("unauthorized", "forbidden", "permission denied", "invalid api key")
    ):
        return FailureKind.AUTHORIZATION
    if isinstance(status, int) and 400 <= status < 500 and status not in {
        401, 402, 403, 408, 409, 425, 429,
    }:
        return FailureKind.CONFIGURATION
    if any(
        marker in message
        for marker in (
            "invalid model",
            "unknown model",
            "model not found",
            "invalid url",
            "missing api key",
            "bad request",
            "unsupported parameter",
        )
    ):
        return FailureKind.CONFIGURATION
    return FailureKind.TRANSIENT


def classify_storage_failure(error: BaseException) -> FailureKind | None:
    """Map explicit SQLite/OS failures while preserving locked != corrupt."""
    message = str(error).casefold()
    if isinstance(error, PermissionError) or any(
        marker in message for marker in ("readonly database", "read-only database", "permission denied")
    ):
        return FailureKind.READ_ONLY
    if "database or disk is full" in message or "disk is full" in message or "no space left" in message:
        return FailureKind.DISK_FULL
    if any(marker in message for marker in ("database is locked", "database is busy", "locked", "busy")):
        return FailureKind.CONTENTION
    if any(marker in message for marker in ("database disk image is malformed", "not a database", "database corruption")):
        return FailureKind.CORRUPT
    if any(marker in message for marker in ("disk i/o error", "unable to open database file", "input/output error")):
        return FailureKind.UNAVAILABLE
    return None


def endpoint_scope(endpoint: object) -> DependencyScope:
    slot = _safe_label(getattr(endpoint, "slot", "endpoint"), "endpoint")
    digest = _digest(f"{slot}:{id(endpoint)}")[:20]
    return DependencyScope(ScopeKind.ENDPOINT, f"{slot}:{digest}")


def provider_scope(provider_id: object, capability_id: object = "") -> DependencyScope:
    digest = _digest(f"{provider_id}\0{capability_id}")[:24]
    return DependencyScope(ScopeKind.PROVIDER, f"provider:{digest}")


def connection_scope(instance_ref: object) -> DependencyScope:
    return DependencyScope(ScopeKind.CONNECTION, f"connection:{_safe_label(instance_ref, 'unknown')}")


def storage_scope(domain: StorageDomain | str) -> DependencyScope:
    parsed = StorageDomain(domain)
    return DependencyScope(ScopeKind.STORAGE, parsed.value)


def connect_sqlite(
    domain: StorageDomain | str,
    database: str | bytes | Path,
    *args: Any,
    recovery: DependencyRecovery | None = None,
    **kwargs: Any,
) -> sqlite3.Connection:
    """Open a SQLite connection that records and re-raises domain-local failures."""
    parsed = StorageDomain(domain)
    manager = recovery or dependency_recovery

    class _ObservedCursor(sqlite3.Cursor):
        def execute(self, sql, parameters=()):
            try:
                return super().execute(sql, parameters)
            except sqlite3.Error as exc:
                manager.record_storage_failure(parsed, exc)
                raise

        def executemany(self, sql, seq_of_parameters):
            try:
                return super().executemany(sql, seq_of_parameters)
            except sqlite3.Error as exc:
                manager.record_storage_failure(parsed, exc)
                raise

        def executescript(self, sql_script):
            try:
                return super().executescript(sql_script)
            except sqlite3.Error as exc:
                manager.record_storage_failure(parsed, exc)
                raise

    class _ObservedConnection(sqlite3.Connection):
        def __init__(self, *connect_args, **connect_kwargs):
            super().__init__(*connect_args, **connect_kwargs)
            self._gravitas_domain = parsed
            self._gravitas_recovery = manager

        def cursor(self, factory=None):
            return super().cursor(factory or _ObservedCursor)

        def execute(self, sql, parameters=()):
            return self.cursor().execute(sql, parameters)

        def executemany(self, sql, seq_of_parameters):
            return self.cursor().executemany(sql, seq_of_parameters)

        def executescript(self, sql_script):
            return self.cursor().executescript(sql_script)

        def commit(self):
            try:
                return super().commit()
            except sqlite3.Error as exc:
                manager.record_storage_failure(parsed, exc)
                raise

    try:
        kwargs.pop("factory", None)
        return sqlite3.connect(
            database,
            *args,
            factory=_ObservedConnection,
            **kwargs,
        )
    except sqlite3.Error as exc:
        manager.record_storage_failure(parsed, exc)
        raise


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _safe_label(value: object, fallback: str) -> str:
    text = str(value or fallback).strip()
    if not _SAFE_SCOPE.fullmatch(text):
        return fallback
    return text[:64]


def _age(now: float, timestamp: float | None) -> float | None:
    return None if timestamp is None else round(max(0.0, now - timestamp), 3)


def _remaining(now: float, timestamp: float | None) -> float | None:
    return None if timestamp is None else round(max(0.0, timestamp - now), 3)


dependency_recovery = DependencyRecovery()


__all__ = [
    "AttemptFence",
    "DependencyFact",
    "DependencyRecovery",
    "DependencyScope",
    "FailureKind",
    "ProbeLease",
    "StorageDomain",
    "classify_dependency_failure",
    "classify_storage_failure",
    "connect_sqlite",
    "connection_scope",
    "dependency_recovery",
    "endpoint_scope",
    "provider_scope",
    "storage_scope",
]
