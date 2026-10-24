# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Coordinate the legacy mixed group binding API across Corona and Nucleus."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from corona.config_store import ConfigStore, ConfigStoreError
from corona.nucleus_client import NucleusClient, NucleusProtocolError
from corona.operations import TERMINAL_PHASES, OperationError, OperationManager
from stella_contracts.control import TrustedActor
from webui.auth import AuthContext, require_auth
from webui.responses import ApiError, ok


class GroupBindingsCoordinator:
    """Persist the request and every cross-process step before proceeding."""

    def __init__(
        self,
        store: ConfigStore,
        operations: OperationManager,
        supervisor: Any,
    ) -> None:
        self.store = store
        self.operations = operations
        self.supervisor = supervisor
        self._lock = asyncio.Lock()
        self._ensure_schema()
        self._recover_interrupted()

    async def execute(
        self, payload: Any, *, actor: Mapping[str, str] | None
    ) -> dict[str, Any]:
        actor_record = dict(actor or {})
        actor_id = actor_record.get("actor_id", "")
        if not actor_id:
            raise ApiError("unauthorized", status_code=401)
        trusted_actor = TrustedActor(
            actor_id=actor_id, kind="admin", authentication="jwt"
        )
        async with self._lock:
            client = self.supervisor.business_client()
            if client is None:
                raise ApiError(
                    "core_unavailable",
                    status_code=503,
                    data={"code": "core_unavailable"},
                )
            try:
                validation = await asyncio.to_thread(
                    client.group_bindings,
                    "validate",
                    {"bindings": payload},
                    actor=trusted_actor,
                )
            except NucleusProtocolError as exc:
                self._raise_nucleus_error(exc)
            bindings = validation.get("bindings")
            snapshot = validation.get("snapshot")
            if (
                not isinstance(bindings, list)
                or not isinstance(snapshot, dict)
                or not isinstance(snapshot.get("digest"), str)
            ):
                raise ApiError("invalid_nucleus_response", status_code=502)

            saga_id = secrets.token_urlsafe(24)
            current = self.store.state()
            request_record = {
                "bindings": bindings,
                "expected_revision": current.desired_revision,
            }
            self._begin(
                saga_id,
                request_record,
                current.desired_revision,
                snapshot["digest"],
            )
            self._step(saga_id, "validated", {"groups": len(bindings)})

            group_ids = sorted({int(item["group_id"]) for item in bindings})
            try:
                saved = self.store.save(
                    {"ALLOWED_GROUPS": ",".join(map(str, group_ids))},
                    expected_revision=current.desired_revision,
                    idempotency_key=f"group-bindings-{saga_id}",
                    actor={"via": "webui", "username": actor_id},
                )
            except ConfigStoreError as exc:
                self._step(saga_id, "config_save_failed", {"code": exc.code})
                self._finish(saga_id, "failed", error_code=exc.code)
                raise ApiError(
                    exc.code,
                    status_code=409 if "conflict" in exc.code else 400,
                    data={"code": exc.code, "current_revision": exc.current_revision},
                ) from exc

            target_revision = str(saved["revision_id"])
            transaction_id = (
                self.store.transaction_for_revision(target_revision)
                if saved.get("changed_keys")
                else None
            )
            self._set_revisions(saga_id, target_revision, transaction_id)
            self._step(
                saga_id,
                "config_saved",
                {
                    "revision_id": target_revision,
                    "changed": bool(saved.get("changed_keys")),
                },
            )

            try:
                applied = await asyncio.to_thread(
                    client.group_bindings,
                    "apply",
                    {
                        "operation_id": saga_id,
                        "bindings": bindings,
                        "expected_digest": snapshot["digest"],
                    },
                    actor=trusted_actor,
                )
                if applied.get("applied") is not True:
                    raise NucleusProtocolError("group_bindings_apply_unconfirmed")
            except NucleusProtocolError as exc:
                self._step(saga_id, "nucleus_apply_failed", {"code": exc.code})
                await self._compensate(
                    saga_id, client, trusted_actor, target_revision, exc.code
                )
                raise ApiError(
                    "group_binding_partial"
                    if self._phase(saga_id) == "needs_reconcile"
                    else exc.code,
                    status_code=409
                    if self._phase(saga_id) == "needs_reconcile"
                    else 503,
                    data={
                        "code": "needs_reconcile"
                        if self._phase(saga_id) == "needs_reconcile"
                        else exc.code,
                        "operation_id": saga_id,
                    },
                ) from exc

            self._step(saga_id, "bindings_applied", {"digest": applied.get("digest")})
            if saved.get("changed_keys"):
                self._set_phase(saga_id, "awaiting_apply")
                try:
                    operation = await self.operations.accept(
                        "apply",
                        target_revision=target_revision,
                        idempotency_key=f"group-bindings-apply-{saga_id}",
                        actor={"via": "webui", "username": actor_id},
                        group_binding_operation_id=saga_id,
                    )
                    self._step(
                        saga_id,
                        "apply_accepted",
                        {"operation_id": operation["operation_id"]},
                    )
                    operation = await self.operations.wait(
                        operation["operation_id"], timeout=120.0
                    )
                except (OperationError, ConfigStoreError) as exc:
                    code = getattr(exc, "code", "apply_failed")
                    await self._compensate(
                        saga_id,
                        self.supervisor.business_client(),
                        trusted_actor,
                        target_revision,
                        code,
                    )
                    raise ApiError(
                        "group_binding_partial"
                        if self._phase(saga_id) == "needs_reconcile"
                        else code,
                        status_code=409,
                        data={
                            "code": "needs_reconcile"
                            if self._phase(saga_id) == "needs_reconcile"
                            else code,
                            "operation_id": saga_id,
                        },
                    ) from exc
                if operation is None or operation.get("phase") not in TERMINAL_PHASES:
                    self._step(saga_id, "apply_pending", {})
                    self._set_phase(saga_id, "awaiting_apply")
                    raise ApiError(
                        "group_binding_apply_pending",
                        status_code=202,
                        data={"code": "apply_pending", "operation_id": saga_id},
                    )
                if operation.get("phase") != "succeeded":
                    code = str(operation.get("error_code") or "apply_failed")
                    replacement = self.supervisor.business_client()
                    await self._compensate(
                        saga_id, replacement, trusted_actor, target_revision, code
                    )
                    raise ApiError(
                        "group_binding_partial"
                        if self._phase(saga_id) == "needs_reconcile"
                        else code,
                        status_code=409,
                        data={
                            "code": "needs_reconcile"
                            if self._phase(saga_id) == "needs_reconcile"
                            else code,
                            "operation_id": saga_id,
                        },
                    )
                self._step(
                    saga_id,
                    "apply_succeeded",
                    {"operation_id": operation["operation_id"]},
                )

            self._finish(saga_id, "succeeded")
            return {
                "groups": group_ids,
                "restart_required": bool(saved.get("changed_keys")),
                "revision_id": target_revision,
                "operation_id": saga_id,
            }

    async def _compensate(
        self,
        saga_id: str,
        client: NucleusClient | None,
        actor: TrustedActor,
        target_revision: str,
        cause: str,
    ) -> None:
        self._set_phase(saga_id, "compensating", error_code=cause)
        problems: list[str] = []
        if client is None:
            client = self.supervisor.business_client()
        if client is None:
            problems.append("core_unavailable")
        else:
            try:
                result = await asyncio.to_thread(
                    client.group_bindings,
                    "rollback",
                    {"operation_id": saga_id},
                    actor=actor,
                )
                if result.get("restored") is not True:
                    problems.append(
                        str(result.get("reason") or "spaces_rollback_failed")
                    )
            except NucleusProtocolError as exc:
                problems.append(exc.code)
        previous_revision = self._previous_revision(saga_id)
        if self.store.state().desired_revision != previous_revision:
            transaction_id = self._config_transaction(saga_id)
            if transaction_id is None:
                problems.append("config_rollback_unavailable")
            else:
                try:
                    result = self.store.restore_transaction_if_unchanged(transaction_id)
                    if not result.get("restored"):
                        problems.append(
                            str(result.get("reason") or "config_rollback_conflict")
                        )
                except ConfigStoreError as exc:
                    problems.append(exc.code)
        if problems:
            self._finish(
                saga_id,
                "needs_reconcile",
                error_code=";".join(sorted(set(problems))),
            )
        else:
            self._finish(saga_id, "rolled_back", error_code=cause)

    def _begin(
        self,
        operation_id: str,
        request: dict[str, Any],
        previous_revision: str,
        spaces_digest: str,
    ) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT operation_id FROM control_operations WHERE phase NOT IN ('succeeded','rolled_back','failed') ORDER BY created_at LIMIT 1"
            ).fetchone()
            if active is not None:
                conn.rollback()
                raise ApiError("operation_in_progress", status_code=409)
            pending = conn.execute(
                "SELECT operation_id,phase FROM group_binding_sagas WHERE phase NOT IN ('succeeded','rolled_back','failed') ORDER BY created_at LIMIT 1"
            ).fetchone()
            if pending is not None:
                conn.rollback()
                raise ApiError(
                    "needs_reconcile"
                    if pending[1] == "needs_reconcile"
                    else "group_bindings_in_progress",
                    status_code=409,
                    data={"operation_id": pending[0]},
                )
            conn.execute(
                """INSERT INTO group_binding_sagas
                (operation_id,phase,request_json,previous_revision,spaces_digest,steps_json,created_at,updated_at)
                VALUES(?,'accepted',?,?,?,?,?,?)""",
                (
                    operation_id,
                    json.dumps(request, sort_keys=True),
                    previous_revision,
                    spaces_digest,
                    "[]",
                    _now(),
                    _now(),
                ),
            )
            conn.commit()

    def _ensure_schema(self) -> None:
        with self.store._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS group_binding_sagas (
                    operation_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    previous_revision TEXT NOT NULL,
                    target_revision TEXT,
                    config_transaction_id TEXT,
                    spaces_digest TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def _recover_interrupted(self) -> None:
        with self.store._connect() as conn:
            conn.execute(
                """UPDATE group_binding_sagas
                   SET phase='needs_reconcile',error_code=COALESCE(error_code,'interrupted_saga'),updated_at=?
                   WHERE phase NOT IN ('succeeded','rolled_back','failed','needs_reconcile')""",
                (_now(),),
            )
            conn.commit()

    def _step(self, operation_id: str, name: str, data: dict[str, Any]) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT steps_json FROM group_binding_sagas WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise ApiError("group_binding_operation_not_found", status_code=500)
            steps = json.loads(row[0])
            steps.append({"name": name, "data": data, "at": _now()})
            conn.execute(
                "UPDATE group_binding_sagas SET steps_json=?,updated_at=? WHERE operation_id=?",
                (json.dumps(steps, sort_keys=True), _now(), operation_id),
            )
            conn.commit()

    def _set_revisions(
        self,
        operation_id: str,
        target_revision: str,
        transaction_id: str | None,
    ) -> None:
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE group_binding_sagas SET target_revision=?,config_transaction_id=?,phase='config_saved',updated_at=? WHERE operation_id=?",
                (target_revision, transaction_id, _now(), operation_id),
            )
            conn.commit()

    def _set_phase(
        self, operation_id: str, phase: str, *, error_code: str | None = None
    ) -> None:
        with self.store._connect() as conn:
            conn.execute(
                "UPDATE group_binding_sagas SET phase=?,error_code=?,updated_at=? WHERE operation_id=?",
                (phase, error_code, _now(), operation_id),
            )
            conn.commit()

    def _finish(
        self, operation_id: str, phase: str, *, error_code: str | None = None
    ) -> None:
        self._set_phase(operation_id, phase, error_code=error_code)

    def _phase(self, operation_id: str) -> str:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT phase FROM group_binding_sagas WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        return str(row[0]) if row else "missing"

    def _previous_revision(self, operation_id: str) -> str:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT previous_revision FROM group_binding_sagas WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        return str(row[0]) if row else ""

    def _config_transaction(self, operation_id: str) -> str | None:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT config_transaction_id FROM group_binding_sagas WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
        return str(row[0]) if row and row[0] else None

    @staticmethod
    def _raise_nucleus_error(exc: NucleusProtocolError) -> None:
        status = 503 if exc.code == "core_unavailable" else 409
        raise ApiError(
            "core_unavailable" if status == 503 else exc.code,
            status_code=status,
            data={"code": exc.code},
        ) from exc


def install_group_bindings(app: Any, coordinator: GroupBindingsCoordinator) -> None:
    router = APIRouter()

    @router.put("/api/v1/groups/bindings")
    async def groups_bindings(
        payload: list[dict[str, Any]],
        auth: Annotated[AuthContext, Depends(require_auth)],
    ):
        result = await coordinator.execute(
            payload,
            actor={"actor_id": auth.username, "via": auth.via},
        )
        return ok(result)

    app.include_router(router)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
