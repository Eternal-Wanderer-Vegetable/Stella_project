# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Startup reconciliation for interrupted config commits and lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from corona.config_store import ConfigStore, ConfigStoreError
from corona.operations import (
    _append_event,
    _now,
    ensure_operation_schema,
    program_fingerprint,
)


@dataclass(frozen=True)
class StartupDecision:
    action: str
    revision_id: str
    start_core: bool
    operation_id: str | None = None
    error_code: str | None = None


class RecoveryManager:
    def __init__(self, store: ConfigStore) -> None:
        self.store = store
        ensure_operation_schema(store)

    def prepare_startup(self, controller_boot_id: str) -> StartupDecision:
        """Select one immutable revision and bound any automatic recovery to one try."""
        self.store.recover_pending_transactions()
        active = self._active_operation()
        state = self.store.state()
        if active is None:
            return StartupDecision(
                action="normal",
                revision_id=state.applied_revision,
                start_core=state.desired_core == "running",
            )

        operation_id = active["operation_id"]
        kind = active["kind"]
        phase = active["phase"]
        target_id = active["target_revision"] or state.applied_revision
        previous_id = active["previous_applied_revision"] or state.applied_revision
        if kind == "core_stop":
            self._transition(operation_id, "succeeded")
            self.store.set_desired_core("stopped")
            return StartupDecision(
                "core_stopped", state.applied_revision, False, operation_id
            )

        if kind == "core_start":
            if active["controller_start_attempted"]:
                self._transition(operation_id, "failed", "interrupted_core_start")
                return StartupDecision(
                    "failed",
                    state.applied_revision,
                    False,
                    operation_id,
                    "interrupted_core_start",
                )
            self._transition(operation_id, "starting", controller_start_attempted=True)
            return StartupDecision(
                "core_start", state.applied_revision, True, operation_id
            )

        if phase in {"accepted", "validating", "prepared"}:
            self._transition(operation_id, "failed", "interrupted_before_core_stop")
            return StartupDecision(
                "normal",
                state.applied_revision,
                state.desired_core == "running",
                operation_id,
                "interrupted_before_core_stop",
            )

        if kind == "restart" and active["restart_scope"] == "corona":
            if active["program_fingerprint"] != program_fingerprint(
                self.store.project_root
            ):
                self._transition(operation_id, "failed", "program_version_changed")
                return StartupDecision(
                    "failed",
                    previous_id,
                    False,
                    operation_id,
                    "program_version_changed",
                )
            if phase == "starting_previous" or active["recovery_attempted"]:
                self._transition(
                    operation_id, "failed", "controller_recovery_interrupted"
                )
                return StartupDecision(
                    "failed",
                    previous_id,
                    False,
                    operation_id,
                    "controller_recovery_interrupted",
                )
            if phase == "awaiting_controller_restart":
                if active["controller_boot_id"] == controller_boot_id:
                    return StartupDecision(
                        "controller_wait",
                        state.applied_revision,
                        False,
                        operation_id,
                        "controller_restart_incomplete",
                    )
                if not active["controller_start_attempted"]:
                    self._transition(
                        operation_id, "starting", controller_start_attempted=True
                    )
                    return StartupDecision(
                        "controller_target", target_id, True, operation_id
                    )
                if not active["recovery_attempted"]:
                    return self._prepare_previous(
                        active,
                        previous_id,
                        controller_boot_id,
                        error_code="controller_target_start_interrupted",
                    )
                self._transition(
                    operation_id, "failed", "controller_recovery_interrupted"
                )
                return StartupDecision(
                    "failed",
                    previous_id,
                    False,
                    operation_id,
                    "controller_recovery_interrupted",
                )
            if (
                phase in {"starting", "verifying"}
                and active["controller_start_attempted"]
            ):
                if not active["recovery_attempted"]:
                    return self._prepare_previous(
                        active,
                        previous_id,
                        controller_boot_id,
                        error_code="controller_target_start_interrupted",
                    )
                self._transition(
                    operation_id, "failed", "controller_recovery_interrupted"
                )
                return StartupDecision(
                    "failed",
                    previous_id,
                    False,
                    operation_id,
                    "controller_recovery_interrupted",
                )
            if phase in {"draining", "stopping"}:
                return self._prepare_previous(
                    active,
                    previous_id,
                    controller_boot_id,
                    error_code="controller_restart_interrupted",
                )
            return StartupDecision(
                "controller_wait",
                state.applied_revision,
                False,
                operation_id,
                "controller_restart_incomplete",
            )

        if phase == "starting_previous" or active["recovery_attempted"]:
            self._transition(
                operation_id, "failed", "previous_config_recovery_interrupted"
            )
            return StartupDecision(
                "failed",
                previous_id,
                False,
                operation_id,
                "previous_config_recovery_interrupted",
            )

        if active["program_fingerprint"] != program_fingerprint(
            self.store.project_root
        ):
            self._transition(operation_id, "failed", "program_version_changed")
            return StartupDecision(
                "normal",
                state.applied_revision,
                state.desired_core == "running",
                operation_id,
                "program_version_changed",
            )
        return self._prepare_previous(
            active,
            previous_id,
            controller_boot_id,
            error_code="operation_interrupted",
        )

    def _prepare_previous(
        self,
        active: dict[str, Any],
        previous_id: str,
        controller_boot_id: str,
        *,
        error_code: str,
    ) -> StartupDecision:
        operation_id = active["operation_id"]
        # Persist the one-attempt fence before touching the source file.
        self._transition(
            operation_id, "restoring_config", error_code, recovery_attempted=True
        )
        target_id = active["target_revision"]
        transaction_id = (
            self.store.transaction_for_revision(target_id) if target_id else None
        )
        if transaction_id:
            try:
                result = self.store.restore_transaction_if_unchanged(transaction_id)
                if not result.get("restored") and result.get("reason") in {
                    "external_env_edit",
                    "external_source_edit",
                }:
                    self.store.refresh_external_edits()
            except ConfigStoreError:
                pass
        try:
            self.store.get_revision(previous_id)
        except ConfigStoreError:
            self._transition(operation_id, "failed", "previous_revision_unavailable")
            return StartupDecision(
                "failed",
                previous_id,
                False,
                operation_id,
                "previous_revision_unavailable",
            )
        self._transition(operation_id, "starting_previous", error_code)
        return StartupDecision(
            "core_previous", previous_id, True, operation_id, error_code
        )

    def _active_operation(self) -> dict[str, Any] | None:
        with self.store._connect() as conn:
            row = conn.execute(
                """SELECT operation_id,kind,phase,target_revision,previous_applied_revision,
                          controller_boot_id,restart_scope,recovery_attempted,
                          controller_start_attempted,program_fingerprint
                   FROM control_operations WHERE phase NOT IN ('succeeded','rolled_back','failed')
                   ORDER BY created_at LIMIT 1"""
            ).fetchone()
        return dict(row) if row is not None else None

    def _transition(
        self,
        operation_id: str,
        phase: str,
        error_code: str | None = None,
        *,
        recovery_attempted: bool | None = None,
        controller_start_attempted: bool | None = None,
    ) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            assignments = ["phase=?", "error_code=?", "updated_at=?"]
            values: list[Any] = [phase, error_code, _now()]
            if recovery_attempted is not None:
                assignments.append("recovery_attempted=?")
                values.append(int(recovery_attempted))
            if controller_start_attempted is not None:
                assignments.append("controller_start_attempted=?")
                values.append(int(controller_start_attempted))
            values.append(operation_id)
            row = conn.execute(
                f"UPDATE control_operations SET {', '.join(assignments)} WHERE operation_id=?",
                values,
            )
            if row.rowcount:
                _append_event(conn, operation_id, phase, {"error_code": error_code})
            conn.commit()
