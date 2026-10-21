# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""In-process fact cache and shadow-only Gravitas control loop."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import asdict, dataclass

from gravitas.clock import ControlClock, SystemControlClock
from gravitas.config import GravitasConfig, GravitasMode
from gravitas.contracts import (
    HealthDimension,
    HealthFact,
    HealthValue,
    Operation,
    PolicySnapshot,
    ScopeKind,
    ScopeRef,
)
from gravitas.events import EventBuffer, EventKind
from gravitas.metrics import BoundedMetrics, ResourceMetrics
from gravitas.policy import (
    CaptureAdmission,
    MemoryBacklogGuard,
    MemoryBacklogSnapshot,
    OperationAdmission,
    PressureState,
    ResourcePolicyState,
    ResourceSignals,
    admit_background,
    evaluate_pressure,
)

SchedulerSource = Callable[[], object]
CaptureSource = Callable[[], object]

_STATUS_FACT_REASONS = frozenset(
    {"within_limit", "queue_saturated", "capture_ready", "capture_closed"}
)
_STATUS_FACT_SOURCES = frozenset({"core.llm.scheduler", "core.capture_gate"})


@dataclass(frozen=True, slots=True)
class FactCacheStats:
    fresh: int
    tracked: int
    rejected: int
    evicted: int
    incomplete: bool


class FactCache:
    """Bound health facts by active scope; reject replayed source sequences."""

    def __init__(self, *, max_scopes: int, ttl_seconds: float) -> None:
        if max_scopes < 1 or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("fact cache bounds must be positive")
        self._max_scopes = max_scopes
        self._ttl = ttl_seconds
        self._facts: OrderedDict[tuple[str, str, str, str], HealthFact] = OrderedDict()
        self._sequences: OrderedDict[tuple[str, str, str, str, str], int] = (
            OrderedDict()
        )
        self._max_sequences = max_scopes * len(HealthDimension)
        self._max_facts = max_scopes * len(HealthDimension) * 4
        self._rejected = 0
        self._evicted = 0
        self._incomplete = False

    def put(
        self,
        fact: HealthFact,
        *,
        now: float,
        active_scopes: set[tuple[str, str]] | None = None,
        expected_boot_id: str,
    ) -> bool:
        now = _finite(now, "now")
        active_scopes = active_scopes or set()
        self.prune(now)
        scope_id = (fact.scope.kind.value, fact.scope.key)
        if (
            not fact.is_fresh(now)
            or fact.observed_control_time > now
            or fact.source_boot_id == ""
            or fact.valid_for_seconds > self._ttl
            or fact.source_boot_id != expected_boot_id
        ):
            self._rejected += 1
            self._incomplete = True
            return False
        key = (
            fact.scope.kind.value,
            fact.scope.key,
            fact.source_id,
            fact.dimension.value,
        )
        sequence_key = (
            fact.source_id,
            fact.source_boot_id,
            fact.scope.kind.value,
            fact.scope.key,
            fact.dimension.value,
        )
        previous_sequence = self._sequences.get(sequence_key)
        if previous_sequence is not None and fact.source_sequence <= previous_sequence:
            self._rejected += 1
            return False
        if previous_sequence is None and len(self._sequences) >= self._max_sequences:
            evict_key = next(
                (
                    old_key
                    for old_key in self._sequences
                    if (old_key[2], old_key[3]) not in active_scopes
                ),
                None,
            )
            if evict_key is None:
                self._rejected += 1
                self._incomplete = True
                return False
            self._sequences.pop(evict_key, None)
            self._incomplete = True
        self._sequences[sequence_key] = fact.source_sequence
        self._sequences.move_to_end(sequence_key)
        existing = self._facts.get(key)
        if existing is not None:
            if existing.source_boot_id == fact.source_boot_id:
                if fact.source_sequence <= existing.source_sequence:
                    self._rejected += 1
                    return False
            else:
                self._facts.pop(key, None)

        if existing is None and len(self._facts) >= self._max_facts:
            evict_key = next(
                (
                    old_key
                    for old_key in self._facts
                    if (old_key[0], old_key[1]) not in active_scopes
                ),
                None,
            )
            if evict_key is None:
                self._rejected += 1
                self._incomplete = True
                return False
            self._facts.pop(evict_key, None)
            self._incomplete = True

        scopes = {(item[0], item[1]) for item in self._facts}
        if scope_id not in scopes and len(scopes) >= self._max_scopes:
            evict_scope = self._oldest_inactive_scope(active_scopes)
            if evict_scope is None:
                self._rejected += 1
                self._incomplete = True
                return False
            for old_key in tuple(self._facts):
                if (old_key[0], old_key[1]) == evict_scope:
                    self._facts.pop(old_key, None)
            self._evicted += 1
            self._incomplete = True

        self._facts[key] = fact
        self._facts.move_to_end(key)
        if fact.valid_for_seconds > self._ttl:
            self._incomplete = True
        return True

    def snapshot(self, *, now: float) -> tuple[HealthFact, ...]:
        now = _finite(now, "now")
        self.prune(now)
        return tuple(self._facts.values())

    def stats(self, *, now: float) -> FactCacheStats:
        facts = self.snapshot(now=now)
        return FactCacheStats(
            fresh=len(facts),
            tracked=len(self._facts),
            rejected=self._rejected,
            evicted=self._evicted,
            incomplete=self._incomplete,
        )

    def prune(self, now: float) -> None:
        now = _finite(now, "now")
        for key, fact in tuple(self._facts.items()):
            if not fact.is_fresh(now) or now - fact.observed_control_time > self._ttl:
                self._facts.pop(key, None)

    def _oldest_inactive_scope(
        self, active_scopes: set[tuple[str, str]]
    ) -> tuple[str, str] | None:
        for key in self._facts:
            scope = (key[0], key[1])
            if scope not in active_scopes:
                return scope
        return None


class GravitasController:
    """Collect bounded in-memory facts and publish a diagnostic policy snapshot.

    This G02 controller is deliberately shadow-only: it reads in-memory
    providers and produces cached diagnostics, but has no business-effect or
    admission callbacks.
    """

    def __init__(
        self,
        config: GravitasConfig,
        *,
        scheduler_source: SchedulerSource,
        capture_source: CaptureSource,
        mode: GravitasMode = GravitasMode.SHADOW,
        clock: ControlClock | None = None,
        controller_boot_id: str | None = None,
    ) -> None:
        if not isinstance(config, GravitasConfig):
            raise TypeError("config must be a GravitasConfig")
        if not callable(scheduler_source) or not callable(capture_source):
            raise TypeError("fact collectors must be callable")
        try:
            configured_mode = mode if isinstance(mode, GravitasMode) else GravitasMode(mode)
        except ValueError as exc:
            raise ValueError(f"invalid Gravitas mode: {mode!r}") from exc
        self.config = config
        self.configured_mode = configured_mode
        self.effective_mode = (
            GravitasMode.SHADOW
            if configured_mode is GravitasMode.ENFORCE
            else configured_mode
        )
        self.enforcement_refused = configured_mode is GravitasMode.ENFORCE
        self.clock = clock or SystemControlClock()
        self.controller_boot_id = controller_boot_id or uuid.uuid4().hex
        if (
            not isinstance(self.controller_boot_id, str)
            or not self.controller_boot_id
            or self.controller_boot_id != self.controller_boot_id.strip()
            or len(self.controller_boot_id) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in self.controller_boot_id)
        ):
            raise ValueError("controller_boot_id must be a bounded, trimmed string")
        self._scheduler_source = scheduler_source
        self._capture_source = capture_source
        self._metrics = BoundedMetrics(
            max_samples_per_resource=config.pressure.max_samples_per_resource,
            window_seconds=config.pressure.window_seconds,
            max_resources=config.pressure.max_active_scopes,
        )
        self._events = EventBuffer(config.pressure.event_ring_capacity)
        self._facts = FactCache(
            max_scopes=config.pressure.max_active_scopes,
            ttl_seconds=config.controller.fact_ttl_seconds,
        )
        self._source_sequences: dict[str, int] = {}
        self._pressure: dict[str, ResourcePolicyState] = {}
        self._backlog_guard = MemoryBacklogGuard(config.pressure)
        self._slot_to_group = {
            slot: resource.group_id
            for resource in config.resources
            for slot in resource.slots
        }
        self._resource_limits = {
            resource.group_id: resource.concurrency for resource in config.resources
        }
        self._policy_revision = 0
        self._last_signature: tuple[tuple[str, str, int, float | None], ...] | None = None
        self._policy: PolicySnapshot | None = None
        self._cached_status: dict[str, object] = self._make_status(
            now=self.clock.now(),
            scheduler_ok=False,
            capture_ok=False,
            resource_metrics={},
        )
        if self.enforcement_refused:
            self._events.append(
                EventKind.ENFORCEMENT_REFUSED,
                "coverage_incomplete",
                observed_at=self.clock.now(),
            )

    @property
    def facts(self) -> FactCache:
        return self._facts

    @property
    def events(self) -> EventBuffer:
        return self._events

    @property
    def policy(self) -> PolicySnapshot | None:
        return self._policy

    def tick(self) -> PolicySnapshot:
        """Collect one bounded sample and refresh the in-memory status cache."""
        now = _finite(self.clock.now(), "control_clock")
        self._current_active_scopes: set[tuple[str, str]] = set()
        scheduler_ok = self._collect_scheduler(now)
        capture_ok = self._collect_capture(now)
        resource_metrics: dict[str, ResourceMetrics] = {}
        for group_id in sorted(self._metrics.resource_ids):
            current = self._metrics.snapshot(group_id, now=now)
            if current is None:
                previous = self._pressure.get(group_id, ResourcePolicyState())
                result = evaluate_pressure(
                    previous,
                    ResourceSignals(queue_depth=None, oldest_wait_seconds=None),
                    self.config.pressure,
                    now=now,
                    background_token_limit=self.config.limits.background_queue,
                )
                self._pressure[group_id] = result.next_state
                continue
            resource_metrics[group_id] = current
            self._current_active_scopes.add((ScopeKind.RESOURCE.value, group_id))
            previous = self._pressure.get(
                group_id,
                ResourcePolicyState(
                    background_tokens=self.config.limits.background_queue
                ),
            )
            result = evaluate_pressure(
                previous,
                ResourceSignals(
                    queue_depth=current.waiting,
                    oldest_wait_seconds=current.oldest_wait_seconds,
                ),
                self.config.pressure,
                now=now,
                background_token_limit=self.config.limits.background_queue,
            )
            self._pressure[group_id] = result.next_state
            if result.changed:
                self._events.append(
                    EventKind.PRESSURE_TRANSITION,
                    result.reason_code,
                    observed_at=now,
                    resource_id=group_id,
                )
            self._record_scheduler_fact(
                group_id, current, now, self._current_active_scopes
            )
        metric_ids = set(self._metrics.resource_ids)
        for stale_id in tuple(self._pressure):
            if stale_id not in metric_ids:
                self._pressure.pop(stale_id, None)
        self._facts.prune(now)
        signature = tuple(
            sorted(
                (
                    resource_id,
                    state.state.value,
                    state.background_tokens,
                    state.last_aged_backend_at,
                )
                for resource_id, state in self._pressure.items()
            )
        )
        if signature != self._last_signature:
            self._policy_revision += 1
            self._last_signature = signature
        self._policy = PolicySnapshot(
            schema_version=1,
            controller_boot_id=self.controller_boot_id,
            policy_revision=self._policy_revision,
            config_digest=_config_digest(self.config),
            issued_at=now,
            valid_for_seconds=self.config.controller.fact_ttl_seconds,
            allowed_operations=tuple(item.value for item in Operation),
            resource_limits=tuple(sorted(self._resource_limits.items())),
            reason_codes=(
                "shadow_only"
                if self.effective_mode is GravitasMode.SHADOW
                else "off"
            ,),
        )
        self._events.append(
            EventKind.POLICY_PUBLISHED,
            "shadow_snapshot" if self.effective_mode is GravitasMode.SHADOW else "off_snapshot",
            observed_at=now,
        )
        self._cached_status = self._make_status(
            now=now,
            scheduler_ok=scheduler_ok,
            capture_ok=capture_ok,
            resource_metrics=resource_metrics,
        )
        return self._policy

    def cached_policy(self) -> PolicySnapshot | None:
        """Return the current cached snapshot without invoking any collector."""
        return self._policy

    def admit_background(
        self,
        resource_id: str,
        *,
        oldest_age_seconds: float | None,
        integrity_ok: bool,
    ) -> OperationAdmission:
        """Return a mode-aware admission for consolidation or Compact work."""
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError("resource_id must be a non-empty string")
        state = self._pressure.get(resource_id, ResourcePolicyState())
        result = admit_background(
            state,
            now=_finite(self.clock.now(), "control_clock"),
            oldest_age_seconds=oldest_age_seconds,
            aged_after_seconds=self.config.pressure.backlog_age_high_water_seconds,
            token_interval_seconds=self.config.pressure.background_token_interval_seconds,
            integrity_ok=integrity_ok,
        )
        enforcing = self.effective_mode is GravitasMode.ENFORCE
        if enforcing and result.allowed:
            self._pressure[resource_id] = result.next_state
        return OperationAdmission(
            allowed=result.allowed if enforcing else True,
            would_deny=not result.allowed,
            reason_code=result.reason_code if enforcing or not result.allowed else "shadow_only",
        )

    def admit_proactive(self, resource_id: str) -> OperationAdmission:
        """Proactive opportunities expire during pressure and are never queued."""
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError("resource_id must be a non-empty string")
        state = self._pressure.get(resource_id, ResourcePolicyState())
        would_deny = state.state is not PressureState.NORMAL
        enforcing = self.effective_mode is GravitasMode.ENFORCE
        return OperationAdmission(
            allowed=not (enforcing and would_deny),
            would_deny=would_deny,
            reason_code=(
                "proactive_paused_pressure"
                if would_deny
                else "within_limit"
            ) if enforcing or would_deny else "shadow_only",
        )

    def integrity_is_trusted(self, resource_id: str) -> bool:
        """Require a fresh, explicit healthy integrity fact for aged-work bypass."""
        now = _finite(self.clock.now(), "control_clock")
        return any(
            fact.scope.kind is ScopeKind.RESOURCE
            and fact.scope.key == resource_id
            and fact.dimension is HealthDimension.INTEGRITY
            and fact.value is HealthValue.HEALTHY
            and fact.is_fresh(now)
            and fact.source_boot_id == self.controller_boot_id
            for fact in self._facts.snapshot(now=now)
        )

    def admit_memory_capture(
        self,
        snapshot: MemoryBacklogSnapshot,
        *,
        wall_time: float,
    ) -> CaptureAdmission:
        """Intersect the independent pressure cap with CaptureGate readiness."""
        decision = self._backlog_guard.evaluate(
            snapshot, now=self.clock.now(), wall_time=wall_time
        )
        if self.effective_mode is GravitasMode.ENFORCE:
            if not decision.allowed:
                self._backlog_guard.record_gap(
                    decision.reason_code, wall_time=wall_time
                )
            return decision
        return CaptureAdmission(
            allowed=True,
            would_deny=decision.would_deny,
            reason_code=(
                f"shadow_{decision.reason_code}"
                if decision.would_deny
                else "shadow_only"
            ),
            state=decision.state,
        )

    def status_snapshot(self) -> dict[str, object]:
        """Return a copy of cached, low-cardinality diagnostics only."""
        payload = copy.deepcopy(self._cached_status)
        payload["memory_backpressure"] = self._backlog_guard.status()
        snapshot = self._policy
        now = self.clock.now()
        if snapshot is None:
            payload["snapshot_age_seconds"] = None
            payload["snapshot_valid"] = False
        else:
            payload["snapshot_age_seconds"] = round(
                max(0.0, now - snapshot.issued_at), 3
            )
            payload["snapshot_valid"] = (
                now >= snapshot.issued_at
                and now < snapshot.expires_at
                and snapshot.controller_boot_id == self.controller_boot_id
            )
        assessment = payload.get("assessment")
        if isinstance(assessment, dict):
            observed: dict[tuple[str, str], set[str]] = {}
            facts = assessment.get("facts")
            if not isinstance(facts, list):
                facts = []
                assessment["facts"] = facts
            for item in facts:
                if not isinstance(item, dict):
                    continue
                observed_at = item.pop("_observed_control_time", None)
                ttl = item.get("valid_for_seconds")
                if not isinstance(observed_at, (int, float)) or not isinstance(
                    ttl, (int, float)
                ):
                    item["age_seconds"] = None
                    item["fresh"] = False
                    continue
                age = now - observed_at
                item["age_seconds"] = round(max(0.0, age), 3)
                item["fresh"] = now >= observed_at and now < observed_at + ttl
                scope = item.get("scope")
                dimension = item.get("dimension")
                if item["fresh"] and isinstance(scope, dict) and isinstance(
                    dimension, str
                ):
                    observed.setdefault((scope["kind"], scope["id"]), set()).add(
                        dimension
                    )
            required = {item.value for item in HealthDimension}
            unassessed = []
            expected_scopes = [
                ({"kind": "resource", "id": resource_id})
                for resource_id in sorted(self._resource_limits)
            ] + [{"kind": "storage", "id": "memory_capture"}]
            for scope in expected_scopes:
                missing = sorted(required - observed.get((scope["kind"], scope["id"]), set()))
                if missing:
                    unassessed.append({"scope": scope, "dimensions": missing})
            unassessed.append({
                "scope": {"kind": "instance", "id": "policy"},
                "dimensions": ["applied_ack"],
            })
            assessment["unassessed"] = unassessed
            assessment["unassessed_count"] = len(unassessed)
            assessment["state"] = "complete" if not unassessed else "partial"
        return payload

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Tick on the configured cadence until shutdown is requested."""
        while stop_event is None or not stop_event.is_set():
            self.tick()
            await asyncio.sleep(self.config.controller.tick_seconds)

    def _collect_scheduler(self, now: float) -> bool:
        try:
            raw = self._scheduler_source()
        except Exception:
            self._events.append(
                EventKind.COLLECTOR_ERROR,
                "scheduler_unavailable",
                observed_at=now,
            )
            return False
        if not isinstance(raw, dict):
            self._events.append(
                EventKind.COLLECTOR_ERROR,
                "scheduler_invalid_snapshot",
                observed_at=now,
            )
            return False

        aggregated: dict[str, dict[str, int | None]] = {}
        scope_limit_reached = False
        for slot, raw_item in sorted(raw.items(), key=lambda item: str(item[0])):
            if not isinstance(slot, str) or not isinstance(raw_item, dict):
                self._events.append(
                    EventKind.COLLECTOR_ERROR,
                    "scheduler_invalid_entry",
                    observed_at=now,
                )
                continue
            group_id = self._slot_to_group.get(slot) or _slot_group(slot)
            if (
                group_id not in aggregated
                and len(aggregated) >= self.config.pressure.max_active_scopes
            ):
                scope_limit_reached = True
                continue
            values = aggregated.setdefault(
                group_id, {"waiting": 0, "holding": 0, "limit": 0}
            )
            for field in ("waiting", "holding", "limit"):
                value = raw_item.get(field)
                if not _optional_count(value):
                    values[field] = None
                elif values[field] is not None:
                    values[field] += value

        if scope_limit_reached:
            self._events.append(
                EventKind.METRIC_EVICTED,
                "active_scope_capacity_reached",
                observed_at=now,
            )

        for group_id, values in aggregated.items():
            waiting = values["waiting"]
            oldest_wait = 0.0 if waiting == 0 else None
            try:
                self._metrics.record(
                    group_id,
                    observed_at=now,
                    waiting=waiting,
                    holding=values["holding"],
                    limit=values["limit"],
                    oldest_wait_seconds=oldest_wait,
                )
            except ValueError:
                self._events.append(
                    EventKind.COLLECTOR_ERROR,
                    "scheduler_metric_invalid",
                    observed_at=now,
                    resource_id=group_id,
                )
        if self._metrics.dropped_samples:
            self._events.append(
                EventKind.METRIC_EVICTED,
                "metric_capacity_reached",
                observed_at=now,
            )
        return True

    def _collect_capture(self, now: float) -> bool:
        try:
            raw = self._capture_source()
        except Exception:
            self._events.append(
                EventKind.COLLECTOR_ERROR,
                "capture_gate_unavailable",
                observed_at=now,
            )
            return False
        if not isinstance(raw, dict):
            self._events.append(
                EventKind.COLLECTOR_ERROR,
                "capture_gate_invalid_snapshot",
                observed_at=now,
            )
            return False
        allowed = raw.get("allowed")
        state = raw.get("state")
        if not isinstance(allowed, bool) or state not in {
            "starting",
            "probing",
            "ready",
            "unavailable",
        }:
            self._events.append(
                EventKind.COLLECTOR_ERROR,
                "capture_gate_invalid_state",
                observed_at=now,
            )
            return False
        scope = ScopeRef(ScopeKind.STORAGE, "memory_capture", "core.capture_gate")
        self._put_fact(
            scope=scope,
            source_id="core.capture_gate",
            dimension=HealthDimension.AVAILABILITY,
            value=HealthValue.HEALTHY if allowed else HealthValue.DEGRADED,
            reason_code="capture_ready" if allowed else "capture_closed",
            now=now,
            metric_value=None,
            active_scopes=self._current_active_scopes
            | {(ScopeKind.STORAGE.value, "memory_capture")},
            expected_boot_id=self.controller_boot_id,
        )
        return True

    def _record_scheduler_fact(
        self,
        group_id: str,
        metrics: ResourceMetrics,
        now: float,
        active_scopes: set[tuple[str, str]],
    ) -> None:
        value = (
            HealthValue.SATURATED
            if metrics.waiting is not None
            and metrics.waiting >= self.config.pressure.enter_queue_depth
            else HealthValue.HEALTHY
        )
        scope = ScopeRef(ScopeKind.RESOURCE, group_id, "core.llm.scheduler")
        self._put_fact(
            scope=scope,
            source_id="core.llm.scheduler",
            dimension=HealthDimension.PRESSURE,
            value=value,
            reason_code="queue_saturated" if value is HealthValue.SATURATED else "within_limit",
            now=now,
            metric_value=(
                float(metrics.waiting) if metrics.waiting is not None else None
            ),
            active_scopes=active_scopes,
            expected_boot_id=self.controller_boot_id,
        )

    def _put_fact(
        self,
        *,
        scope: ScopeRef,
        source_id: str,
        dimension: HealthDimension,
        value: HealthValue,
        reason_code: str,
        now: float,
        metric_value: float | None,
        active_scopes: set[tuple[str, str]],
        expected_boot_id: str,
    ) -> None:
        sequence = self._source_sequences.get(source_id, 0) + 1
        self._source_sequences[source_id] = sequence
        fact = HealthFact(
            schema_version=1,
            scope=scope,
            dimension=dimension,
            value=value,
            reason_code=reason_code,
            source_id=source_id,
            source_boot_id=self.controller_boot_id,
            source_sequence=sequence,
            observed_control_time=now,
            valid_for_seconds=self.config.controller.fact_ttl_seconds,
            metric_value=metric_value,
        )
        if not self._facts.put(
            fact,
            now=now,
            active_scopes=active_scopes,
            expected_boot_id=expected_boot_id,
        ):
            self._events.append(
                EventKind.FACT_REJECTED,
                "fact_capacity_or_replay",
                observed_at=now,
                resource_id=(scope.key if scope.kind is ScopeKind.RESOURCE else None),
            )

    def _make_status(
        self,
        *,
        now: float,
        scheduler_ok: bool,
        capture_ok: bool,
        resource_metrics: dict[str, ResourceMetrics],
    ) -> dict[str, object]:
        facts = self._facts.stats(now=now)
        resources = []
        for resource_id, state in sorted(self._pressure.items()):
            metric = resource_metrics.get(resource_id)
            resources.append(
                {
                    "resource_id": resource_id,
                    "pressure": state.state.value,
                    "background_tokens": state.background_tokens,
                    "last_aged_backend_at": state.last_aged_backend_at,
                    "waiting": metric.waiting if metric else None,
                    "holding": metric.holding if metric else None,
                    "limit": metric.limit if metric else None,
                    "sample_count": metric.sample_count if metric else 0,
                    "p95_interactive_wait_seconds": (
                        metric.p95_interactive_wait_seconds if metric else None
                    ),
                    "p95_sample_count": metric.p95_sample_count if metric else 0,
                    "incomplete": metric.incomplete if metric else True,
                }
            )
        mode_reason = (
            "enforcement_refused"
            if self.enforcement_refused
            else "shadow_only"
            if self.effective_mode is GravitasMode.SHADOW
            else "off"
        )
        snapshot = self._policy
        snapshot_valid = bool(
            snapshot is not None
            and now >= snapshot.issued_at
            and now < snapshot.expires_at
            and snapshot.controller_boot_id == self.controller_boot_id
        )
        assessment_facts = []
        redacted_fact_count = 0
        for fact in self._facts.snapshot(now=now):
            scope = self._diagnostic_scope(fact.scope)
            if scope is None:
                redacted_fact_count += 1
                continue
            assessment_facts.append(
                {
                    "scope": scope,
                    "dimension": fact.dimension.value,
                    "value": fact.value.value,
                    "reason_code": (
                        fact.reason_code
                        if fact.reason_code in _STATUS_FACT_REASONS
                        else "unclassified"
                    ),
                    "source_id": (
                        fact.source_id
                        if fact.source_id in _STATUS_FACT_SOURCES
                        else "redacted"
                    ),
                    "_observed_control_time": fact.observed_control_time,
                    "valid_for_seconds": fact.valid_for_seconds,
                }
            )
        policy = self._policy
        assessment = {
            "scope": {"kind": "instance", "id": "controller"},
            "state": "partial",
            "facts": assessment_facts,
            "redacted_fact_count": redacted_fact_count,
            "unassessed": [],
            "unassessed_count": 0,
            "criteria": {
                "required_dimensions": [item.value for item in HealthDimension],
                "fact_ttl_seconds": self.config.controller.fact_ttl_seconds,
                "policy_ttl_seconds": (
                    policy.valid_for_seconds
                    if policy is not None
                    else self.config.controller.fact_ttl_seconds
                ),
                "pressure_enter_queue_depth": self.config.pressure.enter_queue_depth,
                "pressure_enter_oldest_wait_seconds": (
                    self.config.pressure.enter_oldest_wait_seconds
                ),
                "pressure_enter_consecutive_windows": (
                    self.config.pressure.enter_consecutive_windows
                ),
                "pressure_recover_queue_depth": self.config.pressure.recover_queue_depth,
                "pressure_recover_oldest_wait_seconds": (
                    self.config.pressure.recover_oldest_wait_seconds
                ),
                "pressure_recover_stable_seconds": (
                    self.config.pressure.recover_stable_seconds
                ),
            },
            "version": {
                "diagnostics_schema_version": 1,
                "config_schema_version": self.config.schema_version,
                "controller_boot_id": self.controller_boot_id,
                "policy_revision": self._policy_revision,
                "config_digest": (
                    policy.config_digest if policy is not None else _config_digest(self.config)
                ),
            },
            "applied_ack": {
                "state": "not_received",
                "reason_code": "adapter_ack_not_wired",
                "items": [],
            },
        }
        return {
            "schema_version": 1,
            "mode": self.effective_mode.value,
            "configured_mode": self.configured_mode.value,
            "enforcement_enabled": False,
            "reason_code": mode_reason,
            "controller_boot_id": self.controller_boot_id,
            "policy_revision": self._policy_revision,
            "snapshot_valid": snapshot_valid,
            "scheduler_collector_ok": scheduler_ok,
            "capture_collector_ok": capture_ok,
            "memory_backpressure": self._backlog_guard.status(),
            "facts": {
                "fresh": facts.fresh,
                "tracked": facts.tracked,
                "rejected": facts.rejected,
                "evicted": facts.evicted,
                "incomplete": facts.incomplete,
            },
            "resources": resources,
            "events": self._events.snapshot(),
            "assessment": assessment,
        }

    def _diagnostic_scope(self, scope: ScopeRef) -> dict[str, str] | None:
        """Allow only configured resource ids and the fixed capture scope."""
        if scope.kind is ScopeKind.RESOURCE and scope.key in self._resource_limits:
            return {"kind": "resource", "id": scope.key}
        if scope.kind is ScopeKind.STORAGE and scope.key == "memory_capture":
            return {"kind": "storage", "id": "memory_capture"}
        return None


def _config_digest(config: GravitasConfig) -> str:
    wire = asdict(config)
    payload = json.dumps(wire, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _slot_group(slot: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", slot.lower()).strip("_") or "unknown"
    return f"slot_{safe[:58]}"


def _optional_count(value: object) -> bool:
    return value is None or (
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
    )


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


_ACTIVE_CONTROLLER: GravitasController | None = None


def set_active_controller(controller: GravitasController | None) -> None:
    """Install the Bot-owned controller for synchronous, bounded admission checks."""
    global _ACTIVE_CONTROLLER
    if controller is not None and not isinstance(controller, GravitasController):
        raise TypeError("controller must be a GravitasController or None")
    _ACTIVE_CONTROLLER = controller


def active_controller() -> GravitasController | None:
    return _ACTIVE_CONTROLLER
