# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Corona startup decisions for an interrupted controller restart."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from corona.config_store import ConfigStore
from corona.operations import OperationManager
from corona.recovery import RecoveryManager
from stella_bootstrap.config import build_config_revision

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "cn05-recovery-test"


def _store(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "HOST=127.0.0.1\nPORT=18765\nWEBUI_ENABLED=true\n",
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "isolated.db")}
    initial = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment=external,
    )
    store = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
    )
    store.initialize(initial)
    original_env = (home / ".env").read_bytes()
    saved = store.save(
        {"HOST": "127.0.0.2"},
        expected_revision=initial.revision_id,
        idempotency_key="control-restart-config",
    )
    return store, initial, saved["revision_id"], home, original_env


class _Supervisor:
    def __init__(self, revision_id: str, controller_boot_id: str):
        self.bootstrap = SimpleNamespace(controller_boot_id=controller_boot_id)
        self.snapshot = SimpleNamespace(
            phase="ready",
            revision_id=revision_id,
            generation_id="generation-recovery",
            pid=700,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )


async def _interrupt_restart(
    store: ConfigStore,
    initial_revision: str,
    target: str,
    phase: str,
    *,
    start_attempted: bool,
):
    supervisor = _Supervisor(initial_revision, "old-controller")
    manager = OperationManager(store, supervisor)
    operation = await manager.accept("restart", idempotency_key="restart-operation")
    task = manager._tasks[operation["operation_id"]]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    with store._connect() as conn:
        conn.execute(
            "UPDATE control_operations SET phase=?,controller_start_attempted=? WHERE operation_id=?",
            (phase, int(start_attempted), operation["operation_id"]),
        )
        conn.commit()
    return operation["operation_id"]


@pytest.mark.asyncio
async def test_controller_restart_startup_runs_target_once_and_finalizes(
    tmp_path: Path,
) -> None:
    store, initial, target, _home, _original_env = _store(tmp_path)
    operation_id = await _interrupt_restart(
        store,
        initial.revision_id,
        target,
        "awaiting_controller_restart",
        start_attempted=False,
    )

    decision = RecoveryManager(store).prepare_startup("new-controller")
    assert decision.action == "controller_target"
    assert decision.revision_id == target
    assert decision.start_core is True

    next_supervisor = _Supervisor(target, "new-controller")
    manager = OperationManager(store, next_supervisor)
    await manager.finalize_startup_recovery(decision, next_supervisor.snapshot)
    operation = manager.get(operation_id)
    assert operation["phase"] == "succeeded"
    assert store.state().applied_revision == target


@pytest.mark.asyncio
async def test_controller_crash_during_target_start_restores_previous_once(
    tmp_path: Path,
) -> None:
    store, initial, target, home, original_env = _store(tmp_path)
    operation_id = await _interrupt_restart(
        store, initial.revision_id, target, "starting", start_attempted=True
    )

    decision = RecoveryManager(store).prepare_startup("retry-controller")
    assert decision.action == "core_previous"
    assert decision.revision_id == initial.revision_id
    assert decision.start_core is True
    assert decision.error_code == "controller_target_start_interrupted"
    assert (home / ".env").read_bytes() == original_env

    previous_supervisor = _Supervisor(initial.revision_id, "retry-controller")
    manager = OperationManager(store, previous_supervisor)
    await manager.finalize_startup_recovery(decision, previous_supervisor.snapshot)
    operation = manager.get(operation_id)
    assert operation["phase"] == "rolled_back"
    assert operation["recovery_attempted"] is True
    assert store.state().desired_revision == initial.revision_id
    assert store.state().applied_revision == initial.revision_id
