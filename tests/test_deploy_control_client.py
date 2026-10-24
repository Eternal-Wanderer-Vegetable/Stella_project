# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from corona.ownership import CoronaOwnershipLock
from deploy import control_client
from stella_bootstrap.config import build_config_revision
from stella_contracts.local_control import LocalControlRecord, local_control_record_path

ROOT = Path(__file__).resolve().parents[1]


def _environment(home: Path) -> dict[str, str]:
    return {"STELLA_HOME": str(home), "STELLA_INSTANCE_ID": "cn09-test"}


def test_deploy_entry_import_does_not_load_business_settings(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["STELLA_HOME"] = str(tmp_path / "home")
    env["STELLA_INSTANCE_ID"] = "cn09-import"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import deploy.__main__; "
            "assert 'config' not in sys.modules; "
            "assert 'config.settings' not in sys.modules",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_status_requires_owner_lock_resolution_when_control_record_is_missing(
    tmp_path: Path,
) -> None:
    env = _environment(tmp_path / "home")
    home = Path(env["STELLA_HOME"])
    lock = CoronaOwnershipLock.acquire(home, env["STELLA_INSTANCE_ID"])
    try:
        status = control_client.status(environ=env)
        assert status["ok"] is False
        assert status["error"]["code"] == "controller_unreachable"
    finally:
        lock.close()

    assert control_client.status(environ=env)["alive"] is False


def test_start_and_stop_do_not_duplicate_or_claim_a_locked_owner_is_stopped(
    tmp_path: Path, monkeypatch
) -> None:
    env = _environment(tmp_path / "home")
    home = Path(env["STELLA_HOME"])
    lock = CoronaOwnershipLock.acquire(home, env["STELLA_INSTANCE_ID"])
    spawned = False

    def forbidden_spawn(*_args, **_kwargs):
        nonlocal spawned
        spawned = True
        raise AssertionError("must not spawn a second Corona owner")

    monkeypatch.setattr(control_client, "_spawn_corona", forbidden_spawn)
    try:
        started = control_client.start(environ=env)
        stopped = control_client.stop(environ=env)
        assert started["ok"] is False
        assert started["error"]["code"] == "controller_unreachable"
        assert stopped["ok"] is False
        assert stopped["error"]["code"] == "controller_unreachable"
        assert spawned is False
    finally:
        lock.close()

    stopped = control_client.stop(environ=env)
    assert stopped["ok"] is True
    assert stopped["phase"] == "already_stopped"


def test_stale_control_record_is_resolved_against_os_owner_lock(tmp_path: Path) -> None:
    env = _environment(tmp_path / "home")
    home = Path(env["STELLA_HOME"])
    home.mkdir(parents=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        unused_port = listener.getsockname()[1]
    record_path = local_control_record_path(home, env["STELLA_INSTANCE_ID"])
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        json.dumps(
            LocalControlRecord(
                instance_id=env["STELLA_INSTANCE_ID"],
                controller_boot_id="dead-controller",
                host="127.0.0.1",
                port=unused_port,
                capability="private-capability",
            ).to_dict()
        ),
        encoding="utf-8",
    )
    if os.name != "nt":
        record_path.chmod(0o600)

    lock = CoronaOwnershipLock.acquire(home, env["STELLA_INSTANCE_ID"])
    try:
        assert control_client.status(environ=env)["error"]["code"] == "controller_unreachable"
        assert control_client.stop(environ=env)["error"]["code"] == "controller_unreachable"
    finally:
        lock.close()

    assert control_client.status(environ=env)["alive"] is False
    stopped = control_client.stop(environ=env)
    assert stopped["ok"] is True
    assert stopped["phase"] == "already_stopped"


def test_corona_status_maps_unstable_phases_to_runtime_v1_diagnostics(tmp_path: Path) -> None:
    from deploy import runtime

    home = tmp_path / "home"
    data = control_client._status_from_control(
        {
            "control_protocol_version": 1,
            "controller_boot_id": "boot-cn09",
            "controller_pid": None,
            "public_host": "127.0.0.1",
            "public_port": 19080,
            "webui_enabled": True,
            "core": {
                "desired": "running",
                "phase": "backoff",
                "updated_at": "2026-10-23T00:00:00+00:00",
                "pid": None,
                "generation_id": "generation-cn09",
                "revision_id": "revision-cn09",
            },
        },
        home,
        "cn09-test",
    )
    state = data["runtime"]
    runtime.validate_state_payload(state)
    stella = state["components"]["stella"]
    assert stella["state"] == "degraded"
    assert stella["diagnostics"]["core_phase"] == "backoff"
    assert "pid" not in stella
    assert data["controller_reachable"] is True
    assert data["nucleus_ready"] is False


def test_corona_child_environment_preserves_desktop_but_drops_legacy_control_secrets(
    tmp_path: Path,
) -> None:
    env = {
        "STELLA_DESKTOP_SESSION_SECRET": "desktop-session",
        "STELLA_MANAGED_CORE": "1",
        "STELLA_LAUNCH_TOKEN": "old-token",
        "STELLA_GENERATION_ID": "old-generation",
        "STELLA_INTERNAL_PORT": "18080",
        "MODEL_ID": "user-config-is-preserved",
    }
    child = control_client._corona_environment(
        env, tmp_path / "home", "cn09-test", tmp_path / "revision.json"
    )
    assert child["STELLA_DESKTOP_SESSION_SECRET"] == "desktop-session"
    assert "STELLA_MANAGED_CORE" not in child
    assert "STELLA_LAUNCH_TOKEN" not in child
    assert "STELLA_GENERATION_ID" not in child
    assert "STELLA_INTERNAL_PORT" not in child
    assert child["MODEL_ID"] == "user-config-is-preserved"
    assert child["STELLA_INSTANCE_ID"] == "cn09-test"


def test_desktop_session_secret_is_not_persisted_in_config_revision(tmp_path: Path) -> None:
    secret = "desktop-session-secret-that-must-only-reach-corona"
    revision = build_config_revision(
        project_root=ROOT,
        stella_home=tmp_path / "home",
        external_environment={"STELLA_DESKTOP_SESSION_SECRET": secret},
    )
    assert "STELLA_DESKTOP_SESSION_SECRET" not in revision.values
    assert secret not in json.dumps(revision.to_dict())


def test_runtime_cli_control_failure_does_not_load_legacy_modules(
    monkeypatch, capsys
) -> None:
    from deploy import __main__ as cli

    called: list[tuple[str, str, dict]] = []

    def fail_closed(operation, component, parameters):
        called.append((operation, component, parameters))
        return {
            "ok": False,
            "operation": operation,
            "component": component,
            "exit_code": 1,
            "error": {"code": "controller_unreachable", "message": "offline"},
        }

    def legacy_path_forbidden():
        raise AssertionError("Runtime protocol failure must not enter legacy modules")

    monkeypatch.setattr(control_client, "runtime_operation", fail_closed)
    monkeypatch.setattr(cli, "_load_legacy_modules", legacy_path_forbidden)
    assert cli.main(["runtime", "start", "--component", "stella"]) == 1
    assert called and called[0][0:2] == ("start", "stella")
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "controller_unreachable"
