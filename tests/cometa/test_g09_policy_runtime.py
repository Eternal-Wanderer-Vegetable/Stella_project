# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import time

import pytest

from cometa.config import CometaConfig
from cometa.policy_transport import (
    ClaimDecision,
    ClaimDirective,
    CometaPolicyPublisher,
    WorkerRestartBudget,
    policy_paths,
)
from cometa.runtime import build_runtime
from cometa.supervisor import WorkerSupervisor
from cometa.worker import CometaWorker
from tests.cometa_helpers import claim_task, make_origin, submit_task


class _DenyReader:
    def evaluate(self) -> ClaimDecision:
        return ClaimDecision(False, reason_code="claims_paused")


class _ChildSupervisor:
    """Use real OS children while keeping the Cometa task store isolated."""

    def __init__(self, *, worker_id: str = "worker-test", protected_lease: bool = False):
        self.worker_id = worker_id
        self.process_identity = "pid:test-child"
        self.protected_lease = protected_lease
        self._process: subprocess.Popen | None = None
        self.starts = 0
        self.stop_calls = 0

    def start(self) -> bool:
        self.starts += 1
        duration = 0.08 if self.starts == 1 else 5.0
        self._process = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({duration})"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.worker_id = f"worker-{self.starts}"
        self.process_identity = f"pid:test-child-{self.starts}"
        return True

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def health(self, _store) -> dict[str, object]:
        return {
            "database_reachable": True,
            "lease_present": self.protected_lease,
            "lease_expired": not self.protected_lease,
        }

    def _worker_log_path(self):
        return None

    def stop(self, *, grace_seconds: float = 1.0) -> None:
        self.stop_calls += 1
        process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=max(0.1, grace_seconds))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)


async def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


class TestWorkerPolicyGate:
    @pytest.mark.asyncio
    async def test_pause_blocks_claim_but_renews_and_consumes_controls(
        self, store, config, monkeypatch
    ):
        config.max_concurrent = 2
        active_id = submit_task(store, config, key="g09-active")
        task, attempt = claim_task(store, worker="w-policy")
        assert task.task_id == active_id
        queued_id = submit_task(store, config, key="g09-queued")
        store.request_cancel(active_id, actor="test")

        worker = CometaWorker(
            instance_id="inst-test",
            config=config,
            worker_id="w-policy",
            process_identity="pid:policy-worker",
            store=store,
            policy_reader=_DenyReader(),
        )
        active_task = asyncio.create_task(asyncio.Event().wait())
        worker._active[attempt.attempt_id] = active_task
        counts = {"deadlines": 0, "stale": 0, "recover": 0, "claims": 0, "controls": 0}
        original_deadlines = store.enforce_deadlines
        original_stale = store.expire_stale_inputs
        original_controls = store.pending_controls_for_task

        def deadlines(*args, **kwargs):
            counts["deadlines"] += 1
            return original_deadlines(*args, **kwargs)

        def stale(*args, **kwargs):
            counts["stale"] += 1
            return original_stale(*args, **kwargs)

        def controls(*args, **kwargs):
            counts["controls"] += 1
            return original_controls(*args, **kwargs)

        original_claim = store.claim_next_task

        def claim(*args, **kwargs):
            counts["claims"] += 1
            return original_claim(*args, **kwargs)

        monkeypatch.setattr(store, "enforce_deadlines", deadlines)
        monkeypatch.setattr(store, "expire_stale_inputs", stale)
        monkeypatch.setattr(store, "pending_controls_for_task", controls)
        monkeypatch.setattr(store, "claim_next_task", claim)
        original_recover = worker._recover_orphans

        def recover():
            counts["recover"] += 1
            return original_recover()

        monkeypatch.setattr(worker, "_recover_orphans", recover)
        try:
            await worker._tick()
            assert counts == {
                "deadlines": 1,
                "stale": 1,
                "recover": 1,
                "claims": 0,
                "controls": 1,
            }
            assert store.get_task(queued_id).state.value == "queued"
            conn = store._connect()
            try:
                state = conn.execute(
                    "SELECT state FROM controls WHERE task_id = ?", (active_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            assert state == "delivered"
        finally:
            active_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active_task


class TestSupervisorBinding:
    def test_worker_lease_health_distinguishes_absent_expired_and_active(
        self, config, store
    ):
        supervisor = WorkerSupervisor(
            config=config,
            instance_id="inst-test",
            worker_id="w-lease",
        )
        absent = supervisor.health(store)
        assert absent["database_reachable"] is True
        assert absent["lease_present"] is False

        store.register_worker("inst-test", "w-lease", "pid:lease", lease_seconds=30)
        active = supervisor.health(store)
        assert active["lease_present"] is True
        assert active["lease_expired"] is False

        conn = store._connect()
        try:
            conn.execute(
                "UPDATE worker_leases SET lease_until_utc = '2000-01-01T00:00:00+00:00'"
                " WHERE instance_id = 'inst-test'"
            )
            conn.commit()
        finally:
            conn.close()
        expired = supervisor.health(store)
        assert expired["lease_present"] is True
        assert expired["lease_expired"] is True

    def test_supervisor_injects_policy_bindings_and_rotates_identity(
        self, config, tmp_path, monkeypatch
    ):
        config.db_path = tmp_path / "cometa.db"
        calls = []

        class Process:
            def __init__(self):
                self.alive = True
                self.pid = 321

            def poll(self):
                return None if self.alive else 1

        def popen(args, **_kwargs):
            calls.append(list(args))
            return Process()

        monkeypatch.setattr(subprocess, "Popen", popen)
        supervisor = WorkerSupervisor(
            config=config,
            instance_id="inst-test",
            python_executable=sys.executable,
            stella_home=tmp_path,
            controller_boot_id="boot-test",
            policy_transport_enabled=True,
        )
        original_identity = supervisor.process_identity
        assert supervisor.start()
        first = calls[-1]
        for argument in (
            "--process-identity",
            original_identity,
            "--controller-boot-id",
            "boot-test",
            "--stella-home",
            str(tmp_path.resolve()),
            "--lease-seconds",
            str(config.lease_seconds),
            "--policy-transport",
        ):
            assert argument in first

        supervisor._process.alive = False
        assert supervisor.start()
        assert supervisor.process_identity != original_identity
        assert calls[-1][calls[-1].index("--process-identity") + 1] == supervisor.process_identity
        if supervisor._log_handle is not None:
            supervisor._log_handle.close()
            supervisor._log_handle = None


class TestOptionalRestart:
    def _runtime_with_supervisor(self, config, tmp_path, supervisor, *, enabled):
        runtime = build_runtime(
            config,
            instance_id="inst-test",
            spawn_worker=False,
        )
        runtime.supervisor = supervisor
        runtime.worker_watch_interval_seconds = 0.01
        runtime.auto_restart_enabled = enabled
        if enabled:
            runtime.policy_publisher = CometaPolicyPublisher(
                paths=policy_paths(tmp_path, "inst-test"),
                config=config,
                instance_id="inst-test",
                controller_boot_id="boot-test",
                worker_id=lambda: supervisor.worker_id,
                process_identity=lambda: supervisor.process_identity,
                directive=lambda: ClaimDirective(
                    False, 0, restart_allowed=True, reason_code="restart_allowed"
                ),
            )
            runtime.restart_budget = WorkerRestartBudget(
                max_restarts=1,
                window_seconds=10.0,
                base_delay_seconds=0.0,
                max_delay_seconds=0.0,
            )
        return runtime

    def test_transport_and_restart_are_disabled_by_default(self, config):
        runtime = build_runtime(
            config,
            instance_id="inst-test",
            auto_restart_enabled=True,
        )
        assert runtime.policy_publisher is None
        assert runtime.auto_restart_enabled is False

    @pytest.mark.asyncio
    async def test_auto_restart_is_off_by_default(self, config, tmp_path):
        supervisor = _ChildSupervisor()
        runtime = self._runtime_with_supervisor(
            config, tmp_path, supervisor, enabled=False
        )
        await runtime.start(spawn_worker=True)
        try:
            assert await _wait_for(lambda: runtime._watchdog_task.done())
            assert supervisor.starts == 1
        finally:
            supervisor.stop(grace_seconds=0.1)
            await runtime.stop(grace_seconds=0.1)


    @pytest.mark.asyncio
    async def test_opt_in_restart_starts_real_child_only_after_safe_check(
        self, config, tmp_path
    ):
        supervisor = _ChildSupervisor()
        runtime = self._runtime_with_supervisor(
            config, tmp_path, supervisor, enabled=True
        )
        await runtime.start(spawn_worker=True)
        try:
            assert await _wait_for(lambda: supervisor.starts == 2)
            assert supervisor._process is not None and supervisor.is_running()
            # A restarted child is only process recovery; this test has no task receipt.
            assert runtime.store.tasks_in_flight(
                "inst-test", worker_id=supervisor.worker_id
            ) == []
        finally:
            supervisor.stop(grace_seconds=0.1)
            await runtime.stop(grace_seconds=0.1)


    @pytest.mark.asyncio
    async def test_new_worker_recovers_before_first_claim_tick(
        self, store, config, monkeypatch
    ):
        worker = CometaWorker(
            instance_id="inst-test",
            config=config,
            worker_id="w-restarted",
            process_identity="pid:restarted",
            store=store,
        )
        sequence = []

        async def register():
            return 1

        def recover():
            sequence.append("recover")

        async def tick():
            sequence.append("tick")
            worker.request_stop()

        monkeypatch.setattr(worker, "_register_with_retry", register)
        monkeypatch.setattr(worker, "_recover_orphans", recover)
        monkeypatch.setattr(worker, "_tick", tick)
        await worker.run_forever(stop_grace_seconds=0.1)
        assert sequence == ["recover", "tick"]

    @pytest.mark.asyncio
    async def test_active_owner_lease_blocks_optional_restart(self, config, tmp_path):
        supervisor = _ChildSupervisor(protected_lease=True)
        runtime = self._runtime_with_supervisor(
            config, tmp_path, supervisor, enabled=True
        )
        await runtime.start(spawn_worker=True)
        try:
            await asyncio.sleep(0.2)
            assert supervisor.starts == 1
            assert runtime._watchdog_task is not None
            assert not runtime._watchdog_task.done()
        finally:
            supervisor.stop(grace_seconds=0.1)
            await runtime.stop(grace_seconds=0.1)

    @pytest.mark.asyncio
    async def test_live_attempt_blocks_optional_restart(self, config, tmp_path):
        supervisor = _ChildSupervisor()
        runtime = self._runtime_with_supervisor(
            config, tmp_path, supervisor, enabled=True
        )
        await runtime.start(spawn_worker=True)
        task_id = submit_task(runtime.store, config, key="g09-restart-active")
        claimed_task, _attempt = claim_task(
            runtime.store, worker=supervisor.worker_id
        )
        assert claimed_task.task_id == task_id
        try:
            await asyncio.sleep(0.2)
            assert supervisor.starts == 1
            assert runtime.store.tasks_in_flight(
                "inst-test", worker_id=supervisor.worker_id
            ) == [task_id]
        finally:
            supervisor.stop(grace_seconds=0.1)
            await runtime.stop(grace_seconds=0.1)


class TestRealWorkerPolicyTransport:
    @pytest.mark.asyncio
    async def test_subprocess_ack_pauses_claim_then_allows_fake_task_once(
        self, tmp_path, monkeypatch
    ):
        for key in tuple(os.environ):
            if key.startswith("COMETA_"):
                monkeypatch.delenv(key)
        monkeypatch.setenv("COMETA_ENABLED", "true")
        worker_home = tmp_path / "worker-home"
        monkeypatch.setenv("STELLA_HOME", str(worker_home))
        config_dir = worker_home / "config"
        config_dir.mkdir(parents=True)
        (config_dir / "cometa.toml").write_text(
            "schema_version = 1\n\n"
            "[backends.fake]\n"
            "type = 'fake'\n"
            "enabled = true\n"
            "fake_behavior = 'complete'\n\n"
            "[profiles.coding]\n"
            "backend = 'fake'\n",
            encoding="utf-8",
        )
        config = CometaConfig.load()
        config.lease_seconds = 4.0
        state = {"allowed": False}
        runtime = build_runtime(
            config,
            instance_id="inst-g09-real-worker",
            stella_home=worker_home,
            controller_boot_id="boot-g09-real-worker",
            policy_transport_enabled=True,
            directive_provider=lambda: ClaimDirective(
                claim_allowed=state["allowed"],
                claim_limit=config.max_concurrent if state["allowed"] else 0,
                reason_code=(
                    "gravitas_allowed" if state["allowed"] else "claims_paused"
                ),
            ),
        )
        task_id = submit_task(
            runtime.store,
            config,
            origin=make_origin(instance_id="inst-g09-real-worker"),
            key="g09-real-process-policy",
        )

        def ack_matches(allowed: bool) -> bool:
            status = runtime.policy_publisher.status_snapshot()
            return (
                status.get("applied") is True
                and status.get("claim_allowed") is allowed
            )

        try:
            await runtime.start(spawn_worker=True)
            assert await _wait_for(lambda: ack_matches(False), timeout=8.0)
            await asyncio.sleep(1.1)
            assert runtime.store.get_task(task_id).state.value == "queued"

            state["allowed"] = True
            assert await _wait_for(lambda: ack_matches(True), timeout=8.0)
            assert await _wait_for(
                lambda: runtime.store.get_task(task_id).state.value == "succeeded",
                timeout=8.0,
            )
            conn = runtime.store._connect()
            try:
                attempts = conn.execute(
                    "SELECT COUNT(*) FROM attempts WHERE task_id = ?", (task_id,)
                ).fetchone()[0]
            finally:
                conn.close()
            assert attempts == 1
        finally:
            await runtime.stop(grace_seconds=1.0)


class TestWorkerCLIConfigBinding:
    def test_explicit_home_argument_overrides_inherited_home(
        self, config, tmp_path, monkeypatch
    ):
        import cometa.worker as worker_module

        observed = {}

        def load_config(cls, env=None):
            observed["home"] = env["STELLA_HOME"]
            return config

        class Worker:
            def __init__(self, **kwargs):
                observed["worker_home"] = kwargs["stella_home"]

            async def run_forever(self, *, stop_grace_seconds):
                observed["stop_grace_seconds"] = stop_grace_seconds

            def request_stop(self):
                pass

        monkeypatch.setattr(
            worker_module.CometaConfig, "load", classmethod(load_config)
        )
        monkeypatch.setattr(worker_module, "CometaWorker", Worker)
        worker_home = tmp_path / "explicit-home"
        assert worker_module.main(
            ["--instance-id", "inst-test", "--stella-home", str(worker_home)]
        ) == 0
        assert observed["home"] == str(worker_home)
        assert observed["worker_home"] == str(worker_home)


class TestRealWorkerRestart:
    @pytest.mark.asyncio
    async def test_real_worker_process_restarts_after_owner_lease_expires(
        self, tmp_path, monkeypatch
    ):
        for key in tuple(os.environ):
            if key.startswith("COMETA_"):
                monkeypatch.delenv(key)
        monkeypatch.setenv("STELLA_HOME", str(tmp_path))
        monkeypatch.setenv("COMETA_ENABLED", "true")
        config = CometaConfig.load()
        config.lease_seconds = 1.25
        runtime = build_runtime(
            config,
            instance_id="inst-g09-restart-process",
            stella_home=tmp_path,
            controller_boot_id="boot-g09-restart-process",
            policy_transport_enabled=True,
            auto_restart_enabled=True,
            directive_provider=lambda: ClaimDirective(
                False,
                0,
                restart_allowed=True,
                reason_code="restart_allowed",
            ),
        )
        runtime.worker_watch_interval_seconds = 0.05
        runtime.restart_budget = WorkerRestartBudget(
            max_restarts=1,
            window_seconds=30.0,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
        )
        supervisor = runtime.supervisor
        assert supervisor is not None
        await runtime.start(spawn_worker=True)
        try:
            assert await _wait_for(
                lambda: supervisor.health(runtime.store).get("identity_matches") is True,
                timeout=8.0,
            )
            old_worker_id = supervisor.worker_id
            old_process = supervisor._process
            assert old_process is not None
            old_process.kill()
            assert await _wait_for(lambda: not supervisor.is_running(), timeout=3.0)

            assert await _wait_for(
                lambda: supervisor.worker_id != old_worker_id
                and supervisor.is_running()
                and supervisor.health(runtime.store).get("identity_matches") is True,
                timeout=8.0,
            )

            def restart_policy_acked() -> bool:
                status = runtime.policy_publisher.status_snapshot()
                return status.get("applied") is True and status.get("claim_allowed") is False

            assert await _wait_for(restart_policy_acked, timeout=8.0)
            # The worker process restarted only after the old lease expired; no
            # task receipt or successful outcome is inferred from process health.
            assert runtime.store.tasks_in_flight(
                runtime.instance_id, worker_id=supervisor.worker_id
            ) == []
        finally:
            supervisor.stop(grace_seconds=0.2)
            await runtime.stop(grace_seconds=0.2)

