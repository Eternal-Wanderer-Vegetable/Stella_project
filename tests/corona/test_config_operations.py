# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Serialized lifecycle operations, retries, recovery and event cursors."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from corona.bootstrap import prepare_corona_bootstrap
from corona.config_store import ConfigStore
from corona.operations import OperationError, OperationManager
from corona.supervisor import CoreSupervisor
from stella_bootstrap.config import build_config_revision

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "cn05-operations-test"

_FAKE_CORE = r"""
import json
import hashlib
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

if os.environ.get("MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE") == "7":
    raise SystemExit(41)

identity = {
    "instance_id": os.environ["STELLA_INSTANCE_ID"],
    "controller_boot_id": os.environ["STELLA_CONTROLLER_BOOT_ID"],
    "generation_id": os.environ["STELLA_GENERATION_ID"],
    "revision_id": os.path.basename(os.path.dirname(os.environ["STELLA_CONFIG_REVISION_FILE"])),
    "pid": os.getpid(),
    "control_protocol_version": 1,
    "ready": True,
}
token = os.environ["STELLA_LAUNCH_TOKEN"]
route_catalog = {
    "control_protocol_version": 1,
    "route_catalog_version": 1,
    **{key: identity[key] for key in ("instance_id", "controller_boot_id", "generation_id", "revision_id")},
    "routes": [],
    "digest": hashlib.sha256(b"[]").hexdigest(),
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return
    def do_GET(self):
        if self.path not in {"/_nucleus/v1/health", "/_nucleus/v1/routes"} or self.headers.get("Authorization") != "Bearer " + token:
            self.send_response(401)
            self.end_headers()
            return
        data = json.dumps(route_catalog if self.path == "/_nucleus/v1/routes" else identity).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + token:
            self.send_response(401)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        request.update({"ok": True, "phase": "stopping" if self.path.endswith("/stop") else "draining"})
        data = json.dumps(request).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        if self.path.endswith("/stop"):
            threading.Thread(target=self.server.shutdown, daemon=True).start()

server = HTTPServer((os.environ["STELLA_INTERNAL_HOST"], int(os.environ["STELLA_INTERNAL_PORT"])), Handler)
server.serve_forever()
"""


def _new_store(tmp_path: Path):
    home = tmp_path / "stella-home"
    home.mkdir(parents=True)
    (home / ".env").write_text(
        "WEBUI_ENABLED=true\nHOST=127.0.0.1\nPORT=18765\n",
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "isolated.db")}
    revision = build_config_revision(
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
    store.initialize(revision)
    return store, revision, home


class _FakeSupervisor:
    def __init__(self, revision, *, failed_revisions=(), block_revision=None):
        self.bootstrap = SimpleNamespace(
            controller_boot_id="controller-cn05", revision=revision
        )
        self._selected = revision
        self.failed_revisions = set(failed_revisions)
        self.block_revision = block_revision
        self.start_entered = asyncio.Event()
        self.allow_start = asyncio.Event()
        if block_revision is None:
            self.allow_start.set()
        self.attempted_revisions = []
        self.snapshot = self._snapshot("ready", revision.revision_id, "initial")

    @staticmethod
    def _snapshot(phase, revision_id, generation, pid=321):
        updated = datetime.now(timezone.utc).isoformat()
        return SimpleNamespace(
            desired="running" if phase == "ready" else "stopped",
            phase=phase,
            instance_id=INSTANCE,
            controller_boot_id="controller-cn05",
            revision_id=revision_id,
            generation_id=generation,
            pid=pid if phase == "ready" else None,
            attempt=1,
            error_code=None if phase == "ready" else "fake_start_failed",
            updated_at=updated,
            public=lambda: {
                "phase": phase,
                "revision_id": revision_id,
                "updated_at": updated,
            },
        )

    def select_revision(self, revision, _path):
        self._selected = revision
        self.bootstrap.revision = revision

    async def drain_core(self, _operation_id):
        self.snapshot = self._snapshot(
            "draining", self._selected.revision_id, "draining"
        )
        return True

    async def stop(self, **_kwargs):
        self.snapshot = self._snapshot(
            "stopped", self._selected.revision_id, "stopped", pid=None
        )

    async def start_once(self):
        revision_id = self._selected.revision_id
        self.attempted_revisions.append(revision_id)
        self.start_entered.set()
        await self.allow_start.wait()
        if revision_id in self.failed_revisions:
            self.snapshot = self._snapshot("failed", revision_id, "failed", pid=None)
        else:
            self.snapshot = self._snapshot(
                "ready", revision_id, f"generation-{len(self.attempted_revisions)}"
            )
        return self.snapshot


@pytest.mark.asyncio
async def test_apply_is_idempotent_and_has_resumable_sequenced_events(
    tmp_path: Path,
) -> None:
    store, initial, _home = _new_store(tmp_path)
    saved = store.save(
        {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3},
        expected_revision=initial.revision_id,
        idempotency_key="config-apply",
    )
    supervisor = _FakeSupervisor(initial)
    manager = OperationManager(store, supervisor)

    operation = await manager.accept(
        "apply", idempotency_key="apply-once", actor={"username": "admin", "via": "jwt"}
    )
    repeated = await manager.accept(
        "apply", idempotency_key="apply-once", actor={"username": "admin", "via": "jwt"}
    )
    result = await manager.wait(operation["operation_id"], timeout=3)

    assert repeated["operation_id"] == operation["operation_id"]
    assert result["phase"] == "succeeded"
    assert result["target_revision"] == saved["revision_id"]
    assert result["applied_revision"] == saved["revision_id"]
    assert supervisor.attempted_revisions == [saved["revision_id"]]
    events = manager.events(operation["operation_id"], after_sequence=2)
    assert events[0]["id"] == 3
    assert [event["id"] for event in events] == sorted(event["id"] for event in events)
    assert events[-1]["phase"] == "succeeded"


@pytest.mark.asyncio
async def test_only_one_lifecycle_operation_can_be_active(tmp_path: Path) -> None:
    store, initial, _home = _new_store(tmp_path)
    saved = store.save(
        {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 4},
        expected_revision=initial.revision_id,
        idempotency_key="config-save",
    )
    supervisor = _FakeSupervisor(initial, block_revision=saved["revision_id"])
    manager = OperationManager(store, supervisor)
    accepted = await manager.accept("apply", target_revision=saved["revision_id"])
    await asyncio.wait_for(supervisor.start_entered.wait(), timeout=2)

    with pytest.raises(OperationError, match="operation_in_progress"):
        await manager.accept("restart")

    supervisor.allow_start.set()
    completed = await manager.wait(accepted["operation_id"], timeout=3)
    assert completed["phase"] == "succeeded"


@pytest.mark.asyncio
async def test_failed_target_restores_one_previous_config_and_marks_rolled_back(
    tmp_path: Path,
) -> None:
    store, initial, home = _new_store(tmp_path)
    original_env = (home / ".env").read_bytes()
    saved = store.save(
        {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 5},
        expected_revision=initial.revision_id,
        idempotency_key="config-save",
    )
    supervisor = _FakeSupervisor(initial, failed_revisions={saved["revision_id"]})
    manager = OperationManager(store, supervisor)

    accepted = await manager.accept("apply")
    completed = await manager.wait(accepted["operation_id"], timeout=3)

    assert completed["phase"] == "rolled_back"
    assert completed["recovery_attempted"] is True
    assert completed["error_code"] == "new_revision_not_ready"
    assert store.state().desired_revision == initial.revision_id
    assert store.state().applied_revision == initial.revision_id
    assert (home / ".env").read_bytes() == original_env
    assert supervisor.attempted_revisions == [saved["revision_id"], initial.revision_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fail_target", "expected_phase"),
    [(False, "succeeded"), (True, "rolled_back")],
)
async def test_apply_controls_real_fake_core_and_fences_target_failure(
    tmp_path: Path, fail_target: bool, expected_phase: str
) -> None:
    store, initial, home = _new_store(tmp_path)
    initial_revision, initial_path = store.get_revision(initial.revision_id)
    bootstrap = prepare_corona_bootstrap(
        {
            "STELLA_CONFIG_REVISION_FILE": str(initial_path),
            "STELLA_INSTANCE_ID": INSTANCE,
        },
        project_root=ROOT,
    )
    supervisor = CoreSupervisor(
        bootstrap,
        readiness_timeout=3,
        poll_interval=0.03,
        max_attempts=1,
        command_factory=lambda _bootstrap: [sys.executable, "-c", _FAKE_CORE],
    )
    start_results = []
    original_start_once = supervisor.start_once

    async def tracked_start_once():
        snapshot = await original_start_once()
        start_results.append(
            (snapshot.phase, snapshot.revision_id, snapshot.error_code)
        )
        return snapshot

    supervisor.start_once = tracked_start_once
    try:
        first = await supervisor.start()
        assert first.phase == "ready"
        old_pid = first.pid
        saved = store.save(
            {"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 7 if fail_target else 6},
            expected_revision=initial.revision_id,
            idempotency_key="real-process-config",
        )
        manager = OperationManager(store, supervisor)
        accepted = await manager.accept("apply", target_revision=saved["revision_id"])
        result = await manager.wait(accepted["operation_id"], timeout=8)

        assert result["phase"] == expected_phase, (
            f"operation={result!r}; snapshot={vars(supervisor.snapshot)!r}; starts={start_results!r}"
        )
        assert supervisor.snapshot.phase == "ready"
        assert supervisor.snapshot.pid != old_pid
        if fail_target:
            assert result["target_revision"] == saved["revision_id"]
            assert result["applied_revision"] == initial_revision.revision_id
            assert store.state().desired_revision == initial_revision.revision_id
            assert supervisor.snapshot.revision_id == initial_revision.revision_id
            assert (
                "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE="
                not in (home / ".env").read_text()
            )
        else:
            assert result["applied_revision"] == saved["revision_id"]
            assert store.state().applied_revision == saved["revision_id"]
            assert supervisor.snapshot.revision_id == saved["revision_id"]
    finally:
        await supervisor.stop()
