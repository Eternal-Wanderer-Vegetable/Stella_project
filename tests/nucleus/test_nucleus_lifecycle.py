# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Unit and subprocess contracts for the managed Nucleus lifecycle boundary."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from nucleus.lifecycle import (
    DRAIN_PATH,
    HEALTH_PATH,
    STOP_PATH,
    BusinessRootLock,
    ManagedNucleusASGI,
    NucleusLifecycle,
)
from stella_bootstrap.config import build_config_revision, write_revision
from stella_contracts.control import CONTROL_PROTOCOL_VERSION, ControlIdentity
from stella_contracts.route_catalog import AdapterRoute, create_route_catalog

ROOT = Path(__file__).resolve().parents[2]


def _lifecycle(*, force_exit=lambda _code: None) -> NucleusLifecycle:
    return NucleusLifecycle(
        instance_id="test-instance",
        controller_boot_id="controller-boot-0001",
        generation_id="generation-test-0001",
        revision_id="revision-test-0001",
        launch_token=secrets.token_hex(32),
        internal_host="127.0.0.1",
        internal_port=18080,
        shutdown_budget_seconds=2.0,
        force_exit=force_exit,
    )


def test_business_root_lock_is_process_held_and_keyed_by_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "shared" / "memory.db"
    lock = BusinessRootLock.acquire(database)
    try:
        assert lock.database_path == database.resolve()
        assert lock.lock_path == database.with_name(".memory.db.nucleus.lock")
        child_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(ROOT),
            "PYTHONNOUSERSITE": "1",
            "STELLA_HOME": str(tmp_path / "isolated-home"),
        }
        if os.name == "nt" and os.environ.get("SYSTEMROOT"):
            child_env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; from nucleus.lifecycle import BusinessRootLock, BusinessRootLockError; "
                "import sys; "
                "\ntry: BusinessRootLock.acquire(Path(sys.argv[1]))\n"
                "except BusinessRootLockError: print('locked')\n"
                "else: raise SystemExit(4)",
                str(database),
            ],
            cwd=ROOT,
            env=child_env,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert probe.stdout.strip() == "locked"
    finally:
        lock.close()


@pytest.mark.asyncio
async def test_private_control_and_drain_fence() -> None:
    lifecycle = _lifecycle()
    server = type("FakeServer", (), {"should_exit": False})()
    lifecycle.attach_server(server)
    application_calls: list[str] = []

    async def inner(scope, receive, send):
        application_calls.append(scope["path"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    identity_contract = ControlIdentity(
        instance_id=lifecycle.instance_id,
        controller_boot_id=lifecycle.controller_boot_id,
        generation_id=lifecycle.generation_id,
        revision_id=lifecycle.revision_id,
    )
    catalog = create_route_catalog(
        identity_contract,
        [
            AdapterRoute(
                "OneBot V11", "/onebot/v11/ws", "websocket", (), "OneBot V11 WS"
            )
        ],
    )
    app = ManagedNucleusASGI(inner, lifecycle, catalog)
    identity = {
        "instance_id": lifecycle.instance_id,
        "controller_boot_id": lifecycle.controller_boot_id,
        "generation_id": lifecycle.generation_id,
        "revision_id": lifecycle.revision_id,
    }

    async def request(path, *, method="GET", body=b"", authorization=None):
        messages = [{"type": "http.request", "body": body, "more_body": False}]
        sent = []

        async def receive():
            return messages.pop(0) if messages else {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        headers = []
        if authorization:
            headers.append((b"authorization", authorization.encode("ascii")))
        await app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": method,
                "path": path,
                "headers": headers,
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 18080),
            },
            receive,
            send,
        )
        status = next(
            item["status"] for item in sent if item["type"] == "http.response.start"
        )
        payload = next(
            item["body"] for item in sent if item["type"] == "http.response.body"
        )
        return status, json.loads(payload)

    status, starting = await request("/api/v1/chat", method="POST", body=b"{}")
    assert status == 503
    assert starting["error"]["code"] == "core_starting"
    assert application_calls == []
    lifecycle.mark_ready()

    status, rejected = await request(HEALTH_PATH)
    assert status == 401
    assert lifecycle.launch_token not in json.dumps(rejected)

    status, rejected = await request(HEALTH_PATH, authorization=f"Bearer {'0' * 64}")
    assert status == 401

    bearer = f"Bearer {lifecycle.launch_token}"
    status, health = await request(HEALTH_PATH, authorization=bearer)
    assert status == 200
    assert health["ready"] is True
    assert health["generation_id"] == lifecycle.generation_id
    assert lifecycle.launch_token not in json.dumps(health)

    status, private_routes = await request("/_nucleus/v1/routes")
    assert status == 401
    assert "OneBot V11" not in json.dumps(private_routes)
    status, routes = await request("/_nucleus/v1/routes", authorization=bearer)
    assert status == 200
    assert routes["generation_id"] == lifecycle.generation_id
    assert routes["routes"][0]["path"] == "/onebot/v11/ws"

    wrong_identity = dict(
        identity,
        control_protocol_version=CONTROL_PROTOCOL_VERSION,
        operation_id="drain-wrong-generation",
        generation_id="generation-other-0001",
    )
    status, rejected = await request(
        DRAIN_PATH,
        method="POST",
        body=json.dumps(wrong_identity).encode(),
        authorization=bearer,
    )
    assert status == 409
    assert rejected["error"]["code"] == "identity_mismatch"
    assert lifecycle.phase == "ready"

    wrong_protocol = dict(
        identity,
        control_protocol_version=CONTROL_PROTOCOL_VERSION + 1,
        operation_id="drain-wrong-protocol",
    )
    status, rejected = await request(
        DRAIN_PATH,
        method="POST",
        body=json.dumps(wrong_protocol).encode(),
        authorization=bearer,
    )
    assert status == 409
    assert rejected["error"]["code"] == "protocol_mismatch"
    assert lifecycle.phase == "ready"

    status, drained = await request(
        DRAIN_PATH,
        method="POST",
        body=json.dumps(
            dict(
                identity,
                control_protocol_version=CONTROL_PROTOCOL_VERSION,
                operation_id="drain-test-0001",
                timeout_seconds=1.0,
            )
        ).encode(),
        authorization=bearer,
    )
    assert status == 202
    assert drained["phase"] == "draining"
    assert drained["operation_id"] == "drain-test-0001"
    status, fenced = await request("/api/v1/chat", method="POST", body=b"{}")
    assert status == 503
    assert fenced["error"]["code"] == "core_draining"
    assert application_calls == []

    status, stopped = await request(
        STOP_PATH,
        method="POST",
        body=json.dumps(
            dict(
                identity,
                control_protocol_version=CONTROL_PROTOCOL_VERSION,
                operation_id="stop-test-0001",
            )
        ).encode(),
        authorization=bearer,
    )
    assert status == 202
    assert stopped["phase"] == "stopping"
    assert stopped["operation_id"] == "stop-test-0001"
    assert server.should_exit is True
    lifecycle.cancel_watchdog()


def test_repeated_drain_cannot_extend_the_deadline() -> None:
    lifecycle = _lifecycle()
    try:
        initial = lifecycle.begin_drain(0.4)
        later = lifecycle.begin_drain(1.5)
        assert later <= initial
        assert lifecycle.phase == "draining"
    finally:
        lifecycle.cancel_watchdog()


@pytest.mark.asyncio
async def test_shutdown_callbacks_share_one_remaining_budget() -> None:
    lifecycle = NucleusLifecycle(
        instance_id="test-instance",
        controller_boot_id="controller-boot-0001",
        generation_id="generation-test-0001",
        revision_id="revision-test-0001",
        launch_token=secrets.token_hex(32),
        internal_host="127.0.0.1",
        internal_port=18080,
        shutdown_budget_seconds=0.05,
        force_exit=lambda _code: None,
    )
    calls: list[str] = []

    async def slow_hook() -> None:
        calls.append("slow")
        await asyncio.Event().wait()

    async def later_hook() -> None:
        calls.append("later")

    try:
        await lifecycle.run_shutdown_callback(slow_hook)
        await lifecycle.run_shutdown_callback(later_hook)
        assert calls == ["slow"]
        assert lifecycle.remaining_shutdown_seconds() == 0
    finally:
        lifecycle.cancel_watchdog()


def test_managed_framework_uses_locked_driver_and_ignores_dotenv(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "synthetic-cwd"
    cwd.mkdir()
    (cwd / ".env").write_text(
        "ENVIRONMENT=prod\nPORT=19002\nSTELLA_SNAPSHOT_MARKER=from-file\n",
        encoding="utf-8",
    )
    probe = r"""
import json
from nucleus.lifecycle import NucleusLifecycle, set_active_lifecycle
life = NucleusLifecycle(instance_id="test-instance", controller_boot_id="controller-boot-0001",
    generation_id="generation-test-0001", revision_id="revision-test-0001",
    launch_token="a" * 64, internal_host="127.0.0.1", internal_port=19001)
set_active_lifecycle(life)
from nucleus.framework import install_managed_driver
import nonebot
driver = install_managed_driver()
assert nonebot.get_driver() is driver
assert driver.type == "fastapi"
assert driver.env == "dev"
assert driver.config.port == 19001
assert getattr(driver.config, "stella_snapshot_marker", None) is None
print(json.dumps({"driver": driver.type, "environment": driver.env,
                  "port": driver.config.port,
                  "marker": getattr(driver.config, "stella_snapshot_marker", None)}))
"""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if os.environ.get(key)
    }
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "ENVIRONMENT": "dev",
            "HOST": "127.0.0.1",
            "PORT": "19001",
            "STELLA_HOME": str(tmp_path / "isolated-home"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert json.loads(result.stdout.strip()) == {
        "driver": "fastapi",
        "environment": "dev",
        "port": 19001,
        "marker": None,
    }


def test_managed_framework_rejects_unverified_nonebot_version(monkeypatch) -> None:
    import nucleus.framework as framework

    lifecycle = _lifecycle()
    monkeypatch.setattr(framework, "version", lambda _package: "2.5.1")
    from nucleus.lifecycle import set_active_lifecycle

    set_active_lifecycle(lifecycle)
    try:
        with pytest.raises(
            framework.ManagedFrameworkError, match=r"requires NoneBot 2\.5\.0"
        ):
            framework.install_managed_driver()
    finally:
        set_active_lifecycle(None)


def test_managed_bootstrap_discards_inherited_config_and_freezes_sources(
    tmp_path: Path,
) -> None:
    home = tmp_path / "revision-home"
    home.mkdir()
    (home / ".env").write_text("LLM_TIMEOUT=11\n", encoding="utf-8")
    instance_id = "cn02-snapshot-instance"
    revision = build_config_revision(project_root=ROOT, stella_home=home)
    revision_path = write_revision(home, instance_id, revision)
    probe = r"""
import json, os
from pathlib import Path
from nucleus.bootstrap import prepare_managed_environment
bootstrap = prepare_managed_environment()
from config import settings
Path(bootstrap.stella_home, '.env').write_text('LLM_TIMEOUT=22\n', encoding='utf-8')
assert settings.LLM_TIMEOUT == 11.0
assert os.environ['LLM_TIMEOUT'] == '11'
assert 'STELLA_LAUNCH_TOKEN' not in os.environ
assert settings.STELLA_HOME == bootstrap.stella_home
print(json.dumps({'timeout': settings.LLM_TIMEOUT,
                  'home': str(settings.STELLA_HOME),
                  'database': str(bootstrap.database_path)}))
"""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if os.environ.get(key)
    }
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "STELLA_CONFIG_REVISION_FILE": str(revision_path),
            "STELLA_INSTANCE_ID": instance_id,
            "STELLA_CONTROLLER_BOOT_ID": "controller-boot-cn02-001",
            "STELLA_GENERATION_ID": "generation-cn02-001",
            "STELLA_LAUNCH_TOKEN": secrets.token_hex(32),
            "STELLA_INTERNAL_HOST": "127.0.0.1",
            "STELLA_INTERNAL_PORT": "18081",
            "STELLA_HOME": str(tmp_path / "wrong-home"),
            "LLM_TIMEOUT": "999",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    payload = json.loads(result.stdout.strip())
    assert payload["timeout"] == 11.0
    assert payload["home"] == str(home.resolve())
    assert payload["database"] == str((home / "memory" / "agent_memory.db").resolve())
