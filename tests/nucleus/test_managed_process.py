# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Real subprocess coverage for managed startup, ownership, and stop control."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from stella_bootstrap.config import build_config_revision, write_revision

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _revision(home: Path, instance_id: str, database: Path):
    home.mkdir(parents=True, exist_ok=True)
    (home / ".env").write_text(
        "LLM_TIMEOUT=11\n"
        "STELLA_ADAPTER_MODULES=\n"
        "COMETA_ENABLED=false\n"
        "SCHEDULING_ENABLED=false\n"
        "ASTRBOT_COMPAT_ENABLED=false\n",
        encoding="utf-8",
    )
    revision = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment={"DB_PATH": str(database)},
    )
    return revision, write_revision(home, instance_id, revision)


def _launch(home: Path, revision_path: Path, instance_id: str, port: int, log_path: Path):
    controller_id = uuid.uuid4().hex
    generation_id = uuid.uuid4().hex
    token = secrets.token_hex(32)
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
            "PYTHONUNBUFFERED": "1",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "STELLA_CONFIG_REVISION_FILE": str(revision_path),
            "STELLA_INSTANCE_ID": instance_id,
            "STELLA_CONTROLLER_BOOT_ID": controller_id,
            "STELLA_GENERATION_ID": generation_id,
            "STELLA_LAUNCH_TOKEN": token,
            "STELLA_INTERNAL_HOST": "127.0.0.1",
            "STELLA_INTERNAL_PORT": str(port),
        }
    )
    stream = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "nucleus"],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stream,
        stderr=subprocess.STDOUT,
    )
    return process, stream, token, {
        "instance_id": instance_id,
        "controller_boot_id": controller_id,
        "generation_id": generation_id,
        "revision_id": revision_path.parent.name,
    }


def _log_text(process: subprocess.Popen, stream, path: Path) -> str:
    stream.flush()
    stream.close()
    return path.read_text(encoding="utf-8", errors="replace")


def _health(port: int, token: str | None = None):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/_nucleus/v1/health")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _post_control(port: int, path: str, token: str, payload: dict):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _wait_ready(process: subprocess.Popen, port: int, token: str, log_path: Path, stream):
    deadline = time.monotonic() + 90.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"Nucleus exited before ready ({process.returncode}):\n"
                f"{_log_text(process, stream, log_path)}"
            )
        try:
            status, payload = _health(port, token)
            if status == 200 and payload.get("ready"):
                return payload
        except (OSError, TimeoutError):
            pass
        time.sleep(0.2)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    raise AssertionError(f"Nucleus readiness timed out:\n{_log_text(process, stream, log_path)}")


def _stop(process: subprocess.Popen, port: int, token: str, identity: dict, stream, log_path: Path):
    status, response = _post_control(
        port,
        "/_nucleus/v1/lifecycle/drain",
        token,
        dict(identity, timeout_seconds=35),
    )
    assert status == 202, response
    status, response = _post_control(
        port,
        "/_nucleus/v1/lifecycle/stop",
        token,
        identity,
    )
    assert status == 202, response
    try:
        return_code = process.wait(timeout=55)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        pytest.fail(f"managed Nucleus did not exit within its budget:\n{_log_text(process, stream, log_path)}")
    log = _log_text(process, stream, log_path)
    assert return_code == 0, log
    return log


def test_real_managed_nucleus_ready_refuses_second_writer_and_drains(tmp_path: Path) -> None:
    database = tmp_path / "shared-data" / "memory" / "agent_memory.db"
    first_home = tmp_path / "home-one"
    first_revision, first_path = _revision(first_home, "cn02-instance-one", database)
    first_port = _free_port()
    first, first_stream, first_token, identity = _launch(
        first_home,
        first_path,
        "cn02-instance-one",
        first_port,
        tmp_path / "first-nucleus.log",
    )
    first_log = tmp_path / "first-nucleus.log"
    second = None
    second_stream = None
    try:
        ready = _wait_ready(first, first_port, first_token, first_log, first_stream)
        assert ready["instance_id"] == identity["instance_id"]
        assert ready["controller_boot_id"] == identity["controller_boot_id"]
        assert ready["generation_id"] == identity["generation_id"]
        assert ready["revision_id"] == first_revision.revision_id
        assert ready["pid"] == first.pid

        status, rejected = _health(first_port)
        assert status == 401
        assert first_token not in json.dumps(rejected)

        # Changing live sources cannot mutate the immutable values captured by
        # this generation; health continues to identify the same revision.
        (first_home / ".env").write_text(
            "LLM_TIMEOUT=22\nSTELLA_ADAPTER_MODULES=\nCOMETA_ENABLED=false\n",
            encoding="utf-8",
        )
        status, unchanged = _health(first_port, first_token)
        assert status == 200
        assert unchanged["revision_id"] == first_revision.revision_id
        assert first_token not in json.dumps(unchanged)

        second_home = tmp_path / "home-two"
        _second_revision, second_path = _revision(
            second_home, "cn02-instance-two", database
        )
        second, second_stream, second_token, _second_identity = _launch(
            second_home,
            second_path,
            "cn02-instance-two",
            _free_port(),
            tmp_path / "second-nucleus.log",
        )
        second_log = tmp_path / "second-nucleus.log"
        assert second.wait(timeout=15) == 73
        log = _log_text(second, second_stream, second_log)
        assert "business database ownership rejected" in log
        assert second_token not in log
        assert first.poll() is None
        assert _health(first_port, first_token)[0] == 200

        stopped_log = _stop(
            first, first_port, first_token, identity, first_stream, first_log
        )
        first_stream = None
        assert first_token not in stopped_log
        assert "force-exit grace elapsed" not in stopped_log
    finally:
        if second is not None and second.poll() is None:
            second.terminate()
            try:
                second.wait(timeout=5)
            except subprocess.TimeoutExpired:
                second.kill()
                second.wait(timeout=5)
        if second_stream is not None and not second_stream.closed:
            second_stream.close()
        if first.poll() is None:
            first.terminate()
            try:
                first.wait(timeout=10)
            except subprocess.TimeoutExpired:
                first.kill()
                first.wait(timeout=5)
        if first_stream is not None and not first_stream.closed:
            first_stream.close()
