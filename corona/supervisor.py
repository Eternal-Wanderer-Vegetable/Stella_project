# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Single-generation Nucleus supervisor with bounded startup and crash backoff."""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from corona.bootstrap import CoronaBootstrap
from corona.nucleus_client import NucleusClient, NucleusProtocolError
from corona.process_tree import ManagedProcessTree
from stella_bootstrap.config import PROCESS_ENV_KEYS, RESERVED_ENV_KEYS
from stella_bootstrap.identity import runtime_dir
from stella_contracts.control import DRAIN_PATH, STOP_PATH, ControlIdentity


class CoreLaunchError(RuntimeError):
    """A Nucleus generation did not prove its own readiness and identity."""


@dataclass(frozen=True)
class CoreSnapshot:
    desired: str
    phase: str
    instance_id: str
    controller_boot_id: str
    revision_id: str
    generation_id: str | None = None
    pid: int | None = None
    attempt: int = 0
    error_code: str | None = None
    updated_at: str = ""

    def public(self) -> dict:
        return {
            "desired": self.desired,
            "phase": self.phase,
            "instance_id": self.instance_id,
            "controller_boot_id": self.controller_boot_id,
            "revision_id": self.revision_id,
            "generation_id": self.generation_id,
            "pid": self.pid,
            "attempt": self.attempt,
            "error": self.error_code,
            "updated_at": self.updated_at,
        }


class CoreSupervisor:
    """Own a single Nucleus tree and expose a redacted state snapshot."""

    def __init__(
        self,
        bootstrap: CoronaBootstrap,
        *,
        readiness_timeout: float = 40.0,
        poll_interval: float = 0.2,
        backoff_base: float = 1.0,
        max_attempts: int = 3,
        command_factory: Callable[[CoronaBootstrap], Sequence[str]] | None = None,
        process_tree_factory: Callable[..., ManagedProcessTree] = ManagedProcessTree.spawn,
    ) -> None:
        self.bootstrap = bootstrap
        self.readiness_timeout = max(0.1, float(readiness_timeout))
        self.poll_interval = max(0.01, float(poll_interval))
        self.backoff_base = max(0.01, float(backoff_base))
        self.max_attempts = max(1, int(max_attempts))
        self.command_factory = command_factory or (
            lambda _bootstrap: [sys.executable, "-m", "nucleus"]
        )
        self.process_tree_factory = process_tree_factory
        self._snapshot = CoreSnapshot(
            desired="running",
            phase="stopped",
            instance_id=bootstrap.instance_id,
            controller_boot_id=bootstrap.controller_boot_id,
            revision_id=bootstrap.revision.revision_id,
            updated_at=_now(),
        )
        self._tree: ManagedProcessTree | None = None
        self._identity: dict[str, str] | None = None
        self._token: str | None = None
        self._task: asyncio.Task | None = None
        self._first_state: asyncio.Event | None = None
        self._desired = True
        self._snapshot_lock = asyncio.Lock()

    @property
    def snapshot(self) -> CoreSnapshot:
        return self._snapshot

    async def start(self) -> CoreSnapshot:
        if self._task is not None and not self._task.done():
            if self._first_state is not None:
                await self._first_state.wait()
            return self._snapshot
        self._desired = True
        self._first_state = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="corona-core-supervisor")
        await self._first_state.wait()
        return self._snapshot

    def select_revision(self, revision, revision_file) -> None:
        """Select a previously validated immutable revision for the next generation."""
        if (
            revision.project_root != str(self.bootstrap.project_root)
            or revision.stella_home != str(self.bootstrap.stella_home)
        ):
            raise CoreLaunchError("revision_identity_mismatch")
        self.bootstrap = replace(
            self.bootstrap,
            revision=revision,
            revision_file=revision_file,
        )

    async def start_once(self) -> CoreSnapshot:
        """Start one generation without consuming the autonomous crash retry budget."""
        previous_attempts = self.max_attempts
        self.max_attempts = 1
        try:
            return await self.start()
        finally:
            self.max_attempts = previous_attempts

    async def drain_core(self, operation_id: str) -> bool:
        tree = self._tree
        if (
            tree is None
            or tree.poll() is not None
            or self._snapshot.phase != "ready"
            or not self._identity
            or not self._token
        ):
            return False
        client = self._nucleus_client(dict(self._identity), self._token)
        await asyncio.to_thread(
            client.lifecycle,
            DRAIN_PATH,
            operation_id=f"{operation_id}-drain",
            timeout_seconds=35,
        )
        await self._set_snapshot(phase="draining")
        return True

    async def core_reachable(self) -> bool:
        """Confirm that the owned generation still answers its identity-bound health probe."""
        tree = self._tree
        if (
            tree is None
            or tree.poll() is not None
            or self._snapshot.phase != "ready"
            or not self._identity
            or not self._token
        ):
            return False
        client = self._nucleus_client(dict(self._identity), self._token)
        try:
            status, payload = await asyncio.to_thread(client.health)
        except (NucleusProtocolError, OSError, TimeoutError):
            return False
        return status == 200 and payload.get("ready") is True

    def business_client(self) -> NucleusClient | None:
        """Return an identity-bound client only while this exact core is ready."""
        tree = self._tree
        if (
            tree is None
            or tree.poll() is not None
            or self._snapshot.phase != "ready"
            or not self._identity
            or not self._token
            or self._snapshot.generation_id != self._identity.get("generation_id")
            or self._snapshot.revision_id != self._identity.get("revision_id")
        ):
            return None
        return self._nucleus_client(dict(self._identity), self._token)

    async def stop(self, operation_id: str | None = None, *, already_drained: bool = False) -> None:
        self._desired = False
        tree = self._tree
        if (
            tree is not None
            and tree.poll() is None
            and self._snapshot.phase in {"ready", "draining"}
            and self._identity
            and self._token
        ):
            identity = dict(self._identity)
            client = self._nucleus_client(identity, self._token)
            try:
                if not already_drained and self._snapshot.phase == "ready":
                    await asyncio.to_thread(
                        client.lifecycle,
                        DRAIN_PATH,
                        operation_id=f"{operation_id or uuid.uuid4().hex}-drain",
                        timeout_seconds=35,
                    )
                await asyncio.to_thread(
                    client.lifecycle,
                    STOP_PATH,
                    operation_id=f"{operation_id or uuid.uuid4().hex}-stop",
                )
            except (NucleusProtocolError, OSError, TimeoutError):
                pass
        task = self._task
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=55.0)
            except TimeoutError:
                tree = self._tree
                if tree is not None:
                    await asyncio.to_thread(tree.terminate, grace_seconds=1.0)
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5.0)
                except TimeoutError:
                    task.cancel()
        await self._set_snapshot(phase="stopped", desired="stopped")

    async def _run(self) -> None:
        assert self._first_state is not None
        consecutive_failures = 0
        for attempt in range(1, self.max_attempts + 1):
            if not self._desired:
                break
            generation_id = uuid.uuid4().hex
            token = secrets.token_hex(32)
            identity = {
                "instance_id": self.bootstrap.instance_id,
                "controller_boot_id": self.bootstrap.controller_boot_id,
                "generation_id": generation_id,
                "revision_id": self.bootstrap.revision.revision_id,
            }
            await self._set_snapshot(
                phase="starting",
                desired="running",
                revision_id=self.bootstrap.revision.revision_id,
                generation_id=generation_id,
                pid=None,
                attempt=attempt,
                error_code=None,
            )
            self._identity = identity
            self._token = token
            try:
                tree = await self._spawn(identity, token)
                self._tree = tree
                await self._await_ready(tree, identity, token)
                await self._set_snapshot(phase="ready", pid=tree.pid, error_code=None)
                self._first_state.set()
                # Any exit while desired=running is unexpected, including exit 0.
                exit_code = await asyncio.to_thread(tree.wait)
                await asyncio.to_thread(tree.wait_for_tree)
                self._tree = None
                if not self._desired:
                    break
                consecutive_failures += 1
                code = "core_exited" if exit_code == 0 else "core_crashed"
            except CoreLaunchError as exc:
                tree = self._tree
                if tree is not None:
                    await asyncio.to_thread(tree.terminate, grace_seconds=0.5)
                    self._tree = None
                consecutive_failures += 1
                code = str(exc)
                self._first_state.set()
            except Exception:
                tree = self._tree
                if tree is not None:
                    await asyncio.to_thread(tree.terminate, grace_seconds=0.5)
                    self._tree = None
                consecutive_failures += 1
                code = "spawn_failed"
                self._first_state.set()

            if not self._desired:
                break
            if attempt >= self.max_attempts or consecutive_failures >= self.max_attempts:
                await self._set_snapshot(
                    phase="failed", desired="running", error_code=code, pid=None
                )
                self._first_state.set()
                return
            await self._set_snapshot(
                phase="backoff", desired="running", error_code=code, pid=None
            )
            await asyncio.sleep(min(self.backoff_base * (2 ** (attempt - 1)), 30.0))

        await self._set_snapshot(phase="stopped", desired="stopped", pid=None)
        self._first_state.set()

    async def _spawn(self, identity: dict[str, str], token: str) -> ManagedProcessTree:
        generation_dir = (
            runtime_dir(self.bootstrap.stella_home, self.bootstrap.instance_id)
            / "generations"
            / identity["generation_id"]
        )
        log_path = generation_dir / "nucleus.log"
        env = self._child_environment(identity, token)
        try:
            return await asyncio.to_thread(
                self.process_tree_factory,
                self.command_factory(self.bootstrap),
                cwd=self.bootstrap.project_root,
                env=env,
                log_path=log_path,
            )
        except Exception as exc:
            raise CoreLaunchError("spawn_failed") from exc

    def _child_environment(self, identity: dict[str, str], token: str) -> dict[str, str]:
        parent = os.environ
        runtime = {
            key: value
            for key, value in self.bootstrap.revision.values.items()
            if key.upper() not in RESERVED_ENV_KEYS
            and key.upper() not in PROCESS_ENV_KEYS
            and key.upper() != "STELLA_DESKTOP_SESSION_SECRET"
            and key.upper() not in {"PYTHONIOENCODING", "PYTHONNOUSERSITE", "PYTHONUNBUFFERED", "PYTHONUTF8"}
        }
        process = {
            key: value
            for key, value in parent.items()
            if key.upper() in PROCESS_ENV_KEYS
            or key.upper() in {"PYTHONIOENCODING", "PYTHONNOUSERSITE", "PYTHONUNBUFFERED", "PYTHONUTF8"}
        }
        env = {**process, **runtime}
        env.update(
            {
                "STELLA_MANAGED_CORE": "1",
                "STELLA_MANAGED_PROCESS_GROUP": "1",
                "STELLA_CONFIG_REVISION_FILE": str(self.bootstrap.revision_file),
                "STELLA_HOME": str(self.bootstrap.stella_home),
                "STELLA_INSTANCE_ID": self.bootstrap.instance_id,
                "STELLA_CONTROLLER_BOOT_ID": identity["controller_boot_id"],
                "STELLA_GENERATION_ID": identity["generation_id"],
                "STELLA_LAUNCH_TOKEN": token,
                "STELLA_INTERNAL_HOST": self.bootstrap.internal_host,
                "STELLA_INTERNAL_PORT": str(self.bootstrap.internal_port),
                "HOST": self.bootstrap.internal_host,
                "PORT": str(self.bootstrap.internal_port),
            }
        )
        return env

    async def _await_ready(
        self, tree: ManagedProcessTree, identity: dict[str, str], token: str
    ) -> None:
        deadline = time.monotonic() + self.readiness_timeout
        client = self._nucleus_client(identity, token)
        while time.monotonic() < deadline:
            if tree.poll() is not None:
                raise CoreLaunchError("process_exited_before_ready")
            try:
                status, payload = await asyncio.to_thread(
                    client.health
                )
            except NucleusProtocolError as exc:
                if exc.code == "core_unavailable":
                    await asyncio.sleep(self.poll_interval)
                    continue
                raise CoreLaunchError(exc.code) from exc
            except (OSError, TimeoutError):
                await asyncio.sleep(self.poll_interval)
                continue
            if status == 401:
                await asyncio.sleep(self.poll_interval)
                continue
            if status == 200 and payload.get("ready") is True:
                expected = dict(identity, pid=tree.pid)
                if any(payload.get(key) != value for key, value in expected.items()):
                    raise CoreLaunchError("foreign_core_identity")
                return
            await asyncio.sleep(self.poll_interval)
        raise CoreLaunchError("readiness_timeout")

    def _nucleus_client(self, identity: dict[str, str], token: str) -> NucleusClient:
        try:
            control_identity = ControlIdentity.from_payload(identity)
        except (TypeError, ValueError) as exc:
            raise CoreLaunchError("invalid_core_identity") from exc
        return NucleusClient(
            self.bootstrap.internal_host,
            self.bootstrap.internal_port,
            identity=control_identity,
            capability=token,
            timeout=0.75,
        )

    async def _set_snapshot(self, **changes) -> None:
        async with self._snapshot_lock:
            self._snapshot = replace(self._snapshot, updated_at=_now(), **changes)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
