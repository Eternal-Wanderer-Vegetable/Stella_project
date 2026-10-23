# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""The local deploy capability survives WEBUI_ENABLED=false and core failure."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi.testclient import TestClient

from corona.app import create_corona_app
from corona.bootstrap import prepare_corona_bootstrap
from corona.local_control import (
    LOCAL_STATUS_PATH,
    LOCAL_STOP_PATH,
    LocalControlClient,
    local_control_record_path,
)
from stella_bootstrap.config import build_config_revision, write_revision
from webui.security import reset_auth_runtime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_auth_runtime_after_test():
    yield
    reset_auth_runtime()


def _bootstrap(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "HOST=127.0.0.1\nPORT=18765\nWEBUI_ENABLED=false\n"
        "WEBUI_TOKEN_TTL_HOURS=168\nWEBUI_LOGIN_RATELIMIT_PER_MIN=5\n",
        encoding="utf-8",
    )
    revision = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment={"DB_PATH": str(tmp_path / "db" / "agent_memory.db")},
    )
    path = write_revision(home, "cn04-local-control", revision)
    return prepare_corona_bootstrap(
        {
            "STELLA_CONFIG_REVISION_FILE": str(path),
            "STELLA_INSTANCE_ID": "cn04-local-control",
        },
        project_root=ROOT,
    )


@dataclass
class _StubSupervisor:
    phase: str = "failed"
    started: bool = False
    stopped: bool = False

    def __post_init__(self):
        self.snapshot = SimpleNamespace(
            phase=self.phase,
            generation_id=None,
            public=lambda: {"phase": self.phase, "desired": "running"},
        )

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True
        self.snapshot.phase = "stopped"


def test_local_control_api_remains_online_when_browser_webui_is_disabled(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path)
    supervisor = _StubSupervisor()
    app = create_corona_app(bootstrap, supervisor)
    record = app.state.local_control_record
    record_path = local_control_record_path(bootstrap.stella_home, bootstrap.instance_id)
    assert record_path.is_file()
    if os.name != "nt":
        assert record_path.stat().st_mode & 0o777 == 0o600

    headers = {
        "Authorization": f"Bearer {record.capability}",
        "X-Stella-Control-Protocol-Version": "1",
        "X-Stella-Instance-ID": record.instance_id,
        "X-Stella-Controller-Boot-ID": record.controller_boot_id,
    }
    with TestClient(app, client=("127.0.0.1", 123)) as public_client:
        assert public_client.get("/api/v1/auth/setup-status").status_code == 404
        health = public_client.get("/_corona/v1/health")
        assert health.status_code == 200
        assert health.json()["data"]["control_protocol_version"] == 1

    with TestClient(app.state.local_control_app, client=("127.0.0.1", 123)) as local_client:
        assert local_client.get(LOCAL_STATUS_PATH).status_code == 401

        bad_capability = dict(headers, Authorization="Bearer forged")
        assert local_client.get(LOCAL_STATUS_PATH, headers=bad_capability).status_code == 401

        wrong_protocol = dict(headers, **{"X-Stella-Control-Protocol-Version": "99"})
        assert local_client.get(LOCAL_STATUS_PATH, headers=wrong_protocol).json()["error"]["code"] == "protocol_mismatch"

        wrong_instance = dict(headers, **{"X-Stella-Instance-ID": "another-instance"})
        assert local_client.get(LOCAL_STATUS_PATH, headers=wrong_instance).json()["error"]["code"] == "identity_mismatch"

        status = local_client.get(LOCAL_STATUS_PATH, headers=headers)
        assert status.status_code == 200
        assert status.json()["webui_enabled"] is False
        assert status.json()["core"]["phase"] == "failed"
        assert record.capability not in status.text

        with TestClient(app.state.local_control_app, client=("192.0.2.1", 123)) as remote:
            assert remote.get(LOCAL_STATUS_PATH, headers=headers).status_code == 404

        stopped = local_client.post(
            LOCAL_STOP_PATH,
            headers=headers,
            json={
                "control_protocol_version": 1,
                "instance_id": record.instance_id,
                "controller_boot_id": record.controller_boot_id,
                "operation_id": "deploy-stop-0001",
            },
        )
        assert stopped.status_code == 202
        assert stopped.json()["operation_id"] == "deploy-stop-0001"
        assert stopped.json()["phase"] == "stopping"
        deadline = time.monotonic() + 1
        while not supervisor.stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        assert supervisor.stopped


def test_published_local_control_record_drives_the_no_redirect_client(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path)
    supervisor = _StubSupervisor()
    app = create_corona_app(bootstrap, supervisor)
    record_path = local_control_record_path(bootstrap.stella_home, bootstrap.instance_id)
    server = uvicorn.Server(
        uvicorn.Config(
            app.state.local_control_app,
            host="127.0.0.1",
            port=bootstrap.local_control_port,
            lifespan="off",
            log_level="critical",
            access_log=False,
        )
    )
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert server.started
        client = LocalControlClient.from_record_file(record_path)
        assert client.status()["webui_enabled"] is False
        stopped = client.stop("deploy-client-stop-0001")
        assert stopped["operation_id"] == "deploy-client-stop-0001"
        deadline = time.monotonic() + 1
        while not supervisor.stopped and time.monotonic() < deadline:
            time.sleep(0.01)
        assert supervisor.stopped
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()
