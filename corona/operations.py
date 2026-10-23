# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Persistent, idempotent Corona operations serialized across core lifecycle work."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corona.config_store import ConfigStore, ConfigStoreError, _restart_scope
from stella_contracts.config import ConfigRevision

TERMINAL_PHASES = frozenset({"succeeded", "rolled_back", "failed"})
ACTIVE_PHASES = frozenset(
    {
        "accepted",
        "validating",
        "prepared",
        "draining",
        "stopping",
        "starting",
        "verifying",
        "restoring_config",
        "starting_previous",
        "awaiting_controller_restart",
    }
)


class OperationError(RuntimeError):
    """The operation request conflicts with persisted control state."""

    def __init__(self, code: str, *, active_operation: str | None = None):
        super().__init__(code)
        self.code = code
        self.active_operation = active_operation


class OperationManager:
    def __init__(
        self,
        store: ConfigStore,
        supervisor: Any,
        *,
        controller_shutdown: Callable[[], None] | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self.supervisor = supervisor
        self.controller_shutdown = controller_shutdown
        self.fault_hook = fault_hook
        self._lock = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task] = {}
        self._ensure_schema()

    def set_controller_shutdown(self, callback: Callable[[], None] | None) -> None:
        self.controller_shutdown = callback

    async def accept(
        self,
        kind: str,
        *,
        target_revision: str | None = None,
        idempotency_key: str | None = None,
        actor: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        if kind not in {"apply", "restart", "core_start", "core_stop"}:
            raise OperationError("operation_kind_invalid")
        actor_json = _actor(actor)
        current = self.store.state()
        if kind == "apply":
            target_revision = target_revision or current.desired_revision
            if target_revision != current.desired_revision:
                raise OperationError("revision_conflict")
        elif kind == "restart":
            target_revision = target_revision or current.desired_revision
        elif kind == "core_start":
            target_revision = current.applied_revision
        else:
            target_revision = current.applied_revision

        try:
            revision, _ = self.store.get_revision(target_revision)
        except ConfigStoreError as exc:
            raise OperationError(exc.code) from exc
        record = self.store.revision_record(target_revision) or {}
        changed_keys = record.get("changed_keys", [])
        restart_scope = _restart_scope(changed_keys) if changed_keys else "nucleus"
        if kind in {"core_start", "core_stop"}:
            restart_scope = "nucleus"
        content = json.dumps(
            {"kind": kind, "target_revision": target_revision},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        key = _normalize_idempotency_key(idempotency_key)

        async with self._lock:
            with self.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if key:
                    prior = conn.execute(
                        "SELECT operation_id,request_digest FROM control_operations WHERE idempotency_key=?",
                        (key,),
                    ).fetchone()
                    if prior is not None:
                        if prior["request_digest"] != digest:
                            conn.rollback()
                            raise OperationError("idempotency_conflict")
                        conn.commit()
                        return self.get(prior["operation_id"])
                latest_desired = conn.execute(
                    "SELECT value FROM control_meta WHERE key='desired_revision'"
                ).fetchone()
                if (
                    kind in {"apply", "restart"}
                    and latest_desired is not None
                    and latest_desired[0] != target_revision
                ):
                    conn.rollback()
                    raise OperationError("revision_conflict")
                active = conn.execute(
                    "SELECT operation_id FROM control_operations WHERE phase NOT IN ('succeeded','rolled_back','failed') ORDER BY created_at LIMIT 1"
                ).fetchone()
                if active is not None:
                    conn.rollback()
                    raise OperationError(
                        "operation_in_progress", active_operation=active[0]
                    )
                operation_id = secrets.token_urlsafe(24)
                now = _now()
                conn.execute(
                    """INSERT INTO control_operations
                    (operation_id,kind,phase,target_revision,previous_applied_revision,
                     controller_boot_id,restart_scope,idempotency_key,request_digest,program_fingerprint,actor_json,
                     error_code,recovery_attempted,controller_start_attempted,generation_id,
                     created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,0,0,NULL,?,?)""",
                    (
                        operation_id,
                        kind,
                        "accepted",
                        target_revision,
                        current.applied_revision,
                        getattr(self.supervisor.bootstrap, "controller_boot_id", ""),
                        restart_scope,
                        key,
                        digest,
                        program_fingerprint(self.store.project_root),
                        json.dumps(actor_json, sort_keys=True),
                        now,
                        now,
                    ),
                )
                _append_event(conn, operation_id, "accepted", {"kind": kind})
                conn.commit()
            if kind == "core_start":
                self.store.set_desired_core("running")
            elif kind == "core_stop":
                self.store.set_desired_core("stopped")
            self._fault("operation_accepted")
            self._tasks[operation_id] = asyncio.create_task(
                self._run(operation_id, revision), name=f"corona-operation-{kind}"
            )
            return self.get(operation_id)

    def get(self, operation_id: str) -> dict[str, Any] | None:
        row = self._one(
            """SELECT operation_id,kind,phase,target_revision,previous_applied_revision,
                      restart_scope,error_code,recovery_attempted,generation_id,created_at,updated_at
               FROM control_operations WHERE operation_id=?""",
            (operation_id,),
        )
        if row is None:
            return None
        result = _public_operation(row)
        result["applied_revision"] = self.store.state().applied_revision
        return result

    def last_operation(self) -> dict[str, Any] | None:
        row = self._one(
            "SELECT operation_id FROM control_operations ORDER BY created_at DESC LIMIT 1"
        )
        return self.get(row[0]) if row is not None else None

    def events(
        self, operation_id: str, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        if self.get(operation_id) is None:
            raise OperationError("operation_not_found")
        rows = self._all(
            "SELECT sequence,phase,data_json,created_at FROM control_operation_events WHERE operation_id=? AND sequence>? ORDER BY sequence",
            (operation_id, max(0, int(after_sequence))),
        )
        return [
            {
                "id": int(row[0]),
                "phase": row[1],
                "data": json.loads(row[2]),
                "created_at": row[3],
            }
            for row in rows
        ]

    async def wait(
        self, operation_id: str, timeout: float = 10.0
    ) -> dict[str, Any] | None:
        task = self._tasks.get(operation_id)
        if task is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, timeout))
        return self.get(operation_id)

    def active_operation(self) -> dict[str, Any] | None:
        row = self._one(
            """SELECT operation_id,kind,phase,target_revision,previous_applied_revision,
                      controller_boot_id,restart_scope,error_code,recovery_attempted,
                      controller_start_attempted,generation_id,actor_json,created_at,updated_at
               FROM control_operations WHERE phase NOT IN ('succeeded','rolled_back','failed')
               ORDER BY created_at LIMIT 1"""
        )
        if row is None:
            return None
        result = dict(row)
        result["actor"] = json.loads(result.pop("actor_json"))
        return result

    def transition(
        self,
        operation_id: str,
        phase: str,
        *,
        error_code: str | None = None,
        recovery_attempted: bool | None = None,
        controller_start_attempted: bool | None = None,
    ) -> None:
        if phase not in ACTIVE_PHASES | TERMINAL_PHASES:
            raise OperationError("operation_phase_invalid")
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            values = [phase, error_code, _now()]
            sets = ["phase=?", "error_code=?", "updated_at=?"]
            if recovery_attempted is not None:
                sets.append("recovery_attempted=?")
                values.append(int(recovery_attempted))
            if controller_start_attempted is not None:
                sets.append("controller_start_attempted=?")
                values.append(int(controller_start_attempted))
            values.append(operation_id)
            result = conn.execute(
                f"UPDATE control_operations SET {', '.join(sets)} WHERE operation_id=?",
                values,
            )
            if result.rowcount != 1:
                conn.rollback()
                raise OperationError("operation_not_found")
            snapshot = self.supervisor.snapshot
            generation_id = getattr(snapshot, "generation_id", None)
            if generation_id:
                conn.execute(
                    "UPDATE control_operations SET generation_id=? WHERE operation_id=?",
                    (generation_id, operation_id),
                )
            _append_event(
                conn,
                operation_id,
                phase,
                {
                    "error_code": error_code,
                    "generation_id": generation_id,
                    "recovery_attempted": recovery_attempted,
                },
            )
            conn.commit()

    async def finalize_startup_recovery(self, decision: Any, snapshot: Any) -> None:
        """Resolve a persisted operation after a controller-level restart."""
        if decision is None or not getattr(decision, "operation_id", None):
            return
        operation_id = decision.operation_id
        action = decision.action
        target_revision = decision.revision_id
        operation = self.get(operation_id)
        if operation is None or operation["terminal"]:
            return
        if action in {"normal", "controller_wait", "failed", "core_stopped"}:
            return
        if (
            getattr(snapshot, "phase", None) == "ready"
            and getattr(snapshot, "revision_id", None) == target_revision
        ):
            self.store.set_applied_revision(target_revision)
            if action == "controller_target":
                self.store.set_desired_core("running")
                self.transition(operation_id, "succeeded")
            elif action in {"core_previous", "controller_previous"}:
                self.transition(
                    operation_id,
                    "rolled_back",
                    error_code=decision.error_code or "interrupted_operation",
                )
            elif action == "core_start":
                self.store.set_desired_core("running")
                self.transition(operation_id, "succeeded")
            return
        if action == "controller_target":
            await self._recover_previous(
                operation_id,
                target_revision,
                operation.get("previous_applied_revision")
                or self.store.state().applied_revision,
                decision.error_code or "new_revision_not_ready",
            )
            return
        self.store.set_desired_core("stopped")
        self.transition(
            operation_id,
            "failed",
            error_code=decision.error_code or "startup_recovery_failed",
        )

    async def _run(self, operation_id: str, accepted_revision: ConfigRevision) -> None:
        row = self._one(
            "SELECT kind,target_revision,previous_applied_revision,restart_scope FROM control_operations WHERE operation_id=?",
            (operation_id,),
        )
        if row is None:
            return
        kind, target_id, previous_id, scope = row
        drained = False
        try:
            if kind == "core_stop":
                self.transition(operation_id, "stopping")
                await self.supervisor.stop(operation_id=operation_id)
                self.store.set_desired_core("stopped")
                self.transition(operation_id, "succeeded")
                return
            if kind == "core_start":
                self.transition(operation_id, "validating")
                revision, path = self.store.get_revision(target_id)
                self.store.validate_revision(revision)
                self.supervisor.select_revision(revision, path)
                self.transition(operation_id, "starting")
                snapshot = await self.supervisor.start_once()
                if not _ready_for(snapshot, target_id):
                    raise OperationError("core_start_failed")
                self.store.set_applied_revision(target_id)
                self.store.set_desired_core("running")
                self.transition(operation_id, "succeeded")
                return

            self.transition(operation_id, "validating")
            revision, revision_file = self.store.get_revision(target_id)
            self.store.validate_revision(revision)
            if revision.revision_id != accepted_revision.revision_id:
                raise OperationError("revision_changed")
            self._fault("operation_validated")
            self.transition(operation_id, "prepared")
            if scope == "corona":
                self._preflight_corona(revision_file)
            if (
                kind == "apply"
                and target_id == previous_id
                and getattr(self.supervisor.snapshot, "phase", None) == "ready"
            ):
                self.store.set_applied_revision(target_id)
                self.transition(operation_id, "succeeded")
                return

            if getattr(self.supervisor.snapshot, "phase", None) == "ready":
                self.transition(operation_id, "draining")
                try:
                    await self.supervisor.drain_core(operation_id)
                    drained = True
                except Exception:
                    # A missing ACK may mean Nucleus accepted the drain but the
                    # reply was lost. Reuse its idempotency id, stop the owned
                    # tree, then enter the single previous-config recovery path.
                    try:
                        await self.supervisor.stop(operation_id=operation_id)
                    finally:
                        drained = True
                    raise
                self._fault("operation_drained")
                self.transition(operation_id, "stopping")
                await self.supervisor.stop(
                    operation_id=operation_id, already_drained=True
                )
            else:
                self.transition(operation_id, "stopping")
                await self.supervisor.stop(operation_id=operation_id)
                drained = True
            self._fault("operation_core_stopped")
            if scope == "corona":
                self.transition(operation_id, "awaiting_controller_restart")
                self._fault("operation_awaiting_controller_restart")
                if self.controller_shutdown is None:
                    raise OperationError("controller_restart_unavailable")
                self.controller_shutdown()
                return

            self.supervisor.select_revision(revision, revision_file)
            self.transition(operation_id, "starting")
            self._fault("operation_before_target_start")
            snapshot = await self.supervisor.start_once()
            self.transition(operation_id, "verifying")
            if not _ready_for(snapshot, target_id):
                raise OperationError("new_revision_not_ready")
            self.store.set_applied_revision(target_id)
            self.store.set_desired_core("running")
            self._fault("operation_after_target_start")
            self.transition(operation_id, "succeeded")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = (
                exc.code
                if isinstance(exc, (OperationError, ConfigStoreError))
                else "operation_failed"
            )
            if not drained:
                self.transition(operation_id, "failed", error_code=code)
                return
            await self._recover_previous(operation_id, target_id, previous_id, code)

    async def _recover_previous(
        self, operation_id: str, target_id: str, previous_id: str, cause: str
    ) -> None:
        self.transition(
            operation_id, "restoring_config", error_code=cause, recovery_attempted=True
        )
        transaction_id = self.store.transaction_for_revision(target_id)
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
            previous, previous_path = self.store.get_revision(previous_id)
            self.store.validate_revision(previous)
            self.supervisor.select_revision(previous, previous_path)
        except (ConfigStoreError, OperationError):
            self.store.set_desired_core("stopped")
            self.transition(
                operation_id,
                "failed",
                error_code="previous_revision_unavailable",
                recovery_attempted=True,
            )
            return
        self.transition(
            operation_id, "starting_previous", error_code=cause, recovery_attempted=True
        )
        self._fault("operation_before_previous_start")
        try:
            snapshot = await self.supervisor.start_once()
            self._fault("operation_after_previous_start")
        except Exception:
            snapshot = None
        if _ready_for(snapshot, previous_id):
            self.store.set_applied_revision(previous_id)
            self.store.set_desired_core("running")
            self.transition(
                operation_id, "rolled_back", error_code=cause, recovery_attempted=True
            )
        else:
            self.store.set_desired_core("stopped")
            self.transition(
                operation_id,
                "failed",
                error_code="previous_revision_start_failed",
                recovery_attempted=True,
            )

    def _preflight_corona(self, revision_file: Path) -> None:
        import os

        from corona.bootstrap import prepare_corona_bootstrap
        from stella_bootstrap.config import CONFIG_REVISION_FILE_ENV

        environ = dict(os.environ)
        environ[CONFIG_REVISION_FILE_ENV] = str(revision_file)
        environ["STELLA_INSTANCE_ID"] = self.store.instance_id
        prepare_corona_bootstrap(environ, project_root=self.store.project_root)

    def _ensure_schema(self) -> None:
        ensure_operation_schema(self.store)

    def _transition_if_active(
        self, operation_id: str, phase: str, *, error_code: str | None = None
    ) -> None:
        row = self._one(
            "SELECT phase FROM control_operations WHERE operation_id=?", (operation_id,)
        )
        if row is None or row[0] in TERMINAL_PHASES:
            return
        self.transition(operation_id, phase, error_code=error_code)

    def _one(self, sql: str, params: tuple = ()):
        with self.store._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()):
        with self.store._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _fault(self, boundary: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(boundary)


def _append_event(conn, operation_id: str, phase: str, data: dict[str, Any]) -> None:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence),0)+1 FROM control_operation_events WHERE operation_id=?",
        (operation_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO control_operation_events(operation_id,sequence,phase,data_json,created_at) VALUES(?,?,?,?,?)",
        (operation_id, int(row[0]), phase, json.dumps(data, sort_keys=True), _now()),
    )


def _public_operation(row) -> dict[str, Any]:
    return {
        "operation_id": row[0],
        "kind": row[1],
        "phase": row[2],
        "target_revision": row[3],
        "previous_applied_revision": row[4],
        "applied_revision": row[4] if row[2] in TERMINAL_PHASES else None,
        "restart_scope": row[5],
        "error_code": row[6],
        "recovery_attempted": bool(row[7]),
        "generation_id": row[8],
        "terminal": row[2] in TERMINAL_PHASES,
        "created_at": row[9],
        "updated_at": row[10],
    }


def _ready_for(snapshot: Any, revision_id: str) -> bool:
    return (
        getattr(snapshot, "phase", None) == "ready"
        and getattr(snapshot, "revision_id", None) == revision_id
        and bool(getattr(snapshot, "generation_id", None))
        and bool(getattr(snapshot, "pid", None))
    )


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > 128 or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise OperationError("idempotency_key_invalid")
    return value


def _actor(actor: Mapping[str, str] | None) -> dict[str, str]:
    if not actor:
        return {"via": "unknown"}
    return {
        key: value[:128]
        for key in ("username", "via")
        if isinstance((value := actor.get(key)), str)
    } or {"via": "unknown"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_operation_schema(store: ConfigStore) -> None:
    store._ensure_database()
    store._ensure_schema()
    with store._connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS control_operations (
                operation_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                phase TEXT NOT NULL,
                target_revision TEXT,
                previous_applied_revision TEXT,
                controller_boot_id TEXT NOT NULL,
                restart_scope TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                request_digest TEXT NOT NULL,
                program_fingerprint TEXT NOT NULL,
                actor_json TEXT NOT NULL,
                error_code TEXT,
                recovery_attempted INTEGER NOT NULL DEFAULT 0,
                controller_start_attempted INTEGER NOT NULL DEFAULT 0,
                generation_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS control_operations_one_active
                ON control_operations((1))
                WHERE phase NOT IN ('succeeded','rolled_back','failed');
            CREATE TABLE IF NOT EXISTS control_operation_events (
                operation_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                phase TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(operation_id,sequence)
            );
            """
        )
        conn.commit()


def program_fingerprint(project_root: Path) -> str:
    """Fingerprint code whose compatibility governs automatic config rollback."""
    digest = hashlib.sha256()
    selected = [
        project_root / "pyproject.toml",
        project_root / "config" / "settings.py",
    ]
    for package in ("corona", "nucleus", "stella_bootstrap", "stella_contracts"):
        root = project_root / package
        if root.exists():
            selected.extend(sorted(root.rglob("*.py")))
    for path in sorted({path.resolve() for path in selected if path.is_file()}):
        digest.update(str(path.relative_to(project_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
