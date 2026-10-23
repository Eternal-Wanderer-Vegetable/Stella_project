# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Real-process coverage for Corona ownership, health, failure, and fencing."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from corona.bootstrap import prepare_corona_bootstrap
from corona.ownership import CoronaOwnershipError, CoronaOwnershipLock
from corona.supervisor import CoreSupervisor
from stella_bootstrap.config import build_config_revision, write_revision
from stella_bootstrap.identity import runtime_dir

ROOT = Path(__file__).resolve().parents[2]


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _bootstrap(
    tmp_path: Path,
    *,
    instance_id: str = "cn03-test-instance",
    external_environment: dict[str, str] | None = None,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        f"HOST=127.0.0.1\nPORT={_port()}\nWEBUI_ENABLED=true\n"
        "WEBUI_SERVE_DIST=false\nWEBUI_TOKEN_TTL_HOURS=168\n"
        "WEBUI_LOGIN_RATELIMIT_PER_MIN=5\n",
        encoding="utf-8",
    )
    revision = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment={
            "DB_PATH": str(tmp_path / "db" / "agent_memory.db"),
            **(external_environment or {}),
        },
    )
    revision_path = write_revision(home, instance_id, revision)
    return prepare_corona_bootstrap(
        {
            "STELLA_HOME": str(home),
            "STELLA_CONFIG_REVISION_FILE": str(revision_path),
            "STELLA_INSTANCE_ID": instance_id,
        },
        project_root=ROOT,
    )


_FAKE_CORE = r"""
import json
import hashlib
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

mode = sys.argv[1]
if mode == "import_error":
    raise RuntimeError("synthetic import error")
if mode == "crash":
    raise SystemExit(41)
if mode == "hang":
    time.sleep(120)
    raise SystemExit(0)

identity = {
    "instance_id": os.environ["STELLA_INSTANCE_ID"],
    "controller_boot_id": os.environ["STELLA_CONTROLLER_BOOT_ID"],
    "generation_id": os.environ["STELLA_GENERATION_ID"],
    "revision_id": os.path.basename(os.path.dirname(os.environ["STELLA_CONFIG_REVISION_FILE"])),
    "pid": os.getpid(),
    "control_protocol_version": 1,
    "ready": True,
}
if mode == "foreign":
    identity["pid"] += 10

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
        request.update(
            {
                "ok": True,
                "phase": "stopping" if self.path.endswith("/stop") else "draining",
            }
        )
        data = json.dumps(request).encode()
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        if self.path.endswith("/stop"):
            threading.Thread(target=self.server.shutdown, daemon=True).start()

server = HTTPServer((os.environ["STELLA_INTERNAL_HOST"], int(os.environ["STELLA_INTERNAL_PORT"])), Handler)
if mode == "crash_after_ready":
    threading.Timer(0.1, lambda: os._exit(41)).start()
server.serve_forever()
"""


@pytest.mark.asyncio
async def test_real_fake_core_reaches_ready_and_drains(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path)
    supervisor = CoreSupervisor(
        bootstrap,
        readiness_timeout=3,
        poll_interval=0.05,
        max_attempts=1,
        command_factory=lambda _boot: [sys.executable, "-c", _FAKE_CORE, "ready"],
    )
    ready = await supervisor.start()
    assert ready.phase == "ready"
    assert ready.pid is not None
    assert ready.revision_id == bootstrap.revision.revision_id
    log_path = (
        runtime_dir(bootstrap.stella_home, bootstrap.instance_id)
        / "generations"
        / ready.generation_id
        / "nucleus.log"
    )
    assert log_path.is_file()
    assert log_path.stat().st_mode & 0o777 == 0o600
    await supervisor.stop()
    assert supervisor.snapshot.phase == "stopped"


@pytest.mark.asyncio
async def test_crash_after_ready_uses_bounded_restart_budget(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path, instance_id="cn03-crash-after-ready")
    supervisor = CoreSupervisor(
        bootstrap,
        readiness_timeout=2,
        poll_interval=0.02,
        backoff_base=0.01,
        max_attempts=2,
        command_factory=lambda _boot: [
            sys.executable,
            "-c",
            _FAKE_CORE,
            "crash_after_ready",
        ],
    )
    assert (await supervisor.start()).phase == "ready"
    deadline = time.monotonic() + 5
    while supervisor.snapshot.phase != "failed" and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert supervisor.snapshot.phase == "failed"
    assert supervisor.snapshot.attempt == 2
    assert supervisor.snapshot.error_code == "core_crashed"
    assert supervisor._tree is None
    await supervisor.stop()


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("import_error", "process_exited_before_ready"),
        ("crash", "process_exited_before_ready"),
        ("hang", "readiness_timeout"),
        ("foreign", "foreign_core_identity"),
    ],
)
@pytest.mark.asyncio
async def test_fake_core_failures_are_bounded_and_owned(
    tmp_path: Path, mode: str, expected_error: str
) -> None:
    bootstrap = _bootstrap(tmp_path, instance_id=f"cn03-{mode}")
    supervisor = CoreSupervisor(
        bootstrap,
        readiness_timeout=0.6,
        poll_interval=0.03,
        max_attempts=1,
        command_factory=lambda _boot: [sys.executable, "-c", _FAKE_CORE, mode],
    )
    failed = await supervisor.start()
    assert failed.phase == "failed"
    assert failed.error_code == expected_error
    assert supervisor._tree is None
    await supervisor.stop()


def test_corona_ownership_lock_is_held_by_open_handle(tmp_path: Path) -> None:
    lock = CoronaOwnershipLock.acquire(tmp_path, "cn03-lock-test")
    with pytest.raises(CoronaOwnershipError):
        CoronaOwnershipLock.acquire(tmp_path, "cn03-lock-test")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from corona.ownership import CoronaOwnershipError, CoronaOwnershipLock; import sys; "
            "\ntry: CoronaOwnershipLock.acquire(Path(sys.argv[1]), sys.argv[2])\n"
            "except CoronaOwnershipError: raise SystemExit(73)\n"
            "raise SystemExit(0)",
            str(tmp_path),
            "cn03-lock-test",
        ],
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert probe.returncode == 73, probe.stderr
    lock.close()
    reopened = CoronaOwnershipLock.acquire(tmp_path, "cn03-lock-test")
    reopened.close()


def test_child_environment_never_inherits_desktop_session_capability(
    tmp_path: Path,
) -> None:
    secret = "desktop-session-secret-value-that-must-not-cross"
    bootstrap = _bootstrap(
        tmp_path,
        instance_id="cn03-secret-boundary",
        external_environment={"STELLA_DESKTOP_SESSION_SECRET": secret},
    )
    supervisor = CoreSupervisor(bootstrap)
    child_environment = supervisor._child_environment(
        {
            "controller_boot_id": bootstrap.controller_boot_id,
            "generation_id": "cn03-secret-generation-0001",
        },
        "x" * 64,
    )
    assert "STELLA_DESKTOP_SESSION_SECRET" not in child_environment
    assert secret not in child_environment.values()


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX process groups are unavailable on Windows"
)
def test_process_tree_kills_descendant_after_root_exit(tmp_path: Path) -> None:
    from corona.process_tree import ManagedProcessTree

    child_pid_file = tmp_path / "worker.pid"
    command = [
        sys.executable,
        "-c",
        "import pathlib,subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid))",
        str(child_pid_file),
    ]
    tree = ManagedProcessTree.spawn(
        command,
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        log_path=tmp_path / "core.log",
    )
    deadline = time.monotonic() + 5
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text())
    assert tree.wait(timeout=5) == 0
    tree.wait_for_tree(grace_seconds=0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX owner pipe is unavailable on Windows"
)
def test_owner_loss_drains_core_and_fences_descendant_tree(tmp_path: Path) -> None:
    from corona.process_tree import ManagedProcessTree

    child_pid_file = tmp_path / "owner-loss-worker.pid"
    child_code = r"""
import asyncio
import os
import subprocess
import sys
import time
from types import SimpleNamespace

from nucleus.lifecycle import NucleusLifecycle

worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(sys.argv[1], "w", encoding="ascii").write(str(worker.pid))
lifecycle = NucleusLifecycle(
    instance_id="owner-loss-test-instance",
    controller_boot_id="owner-loss-controller-boot",
    generation_id="owner-loss-generation",
    revision_id="owner-loss-revision",
    launch_token="x" * 64,
    internal_host="127.0.0.1",
    internal_port=18080,
    controller_watch_fd=int(os.environ["STELLA_CONTROLLER_WATCH_FD"]),
)
server = SimpleNamespace(should_exit=False)
lifecycle.attach_server(server)
lifecycle.mark_ready()
deadline = time.monotonic() + 5
while not server.should_exit and time.monotonic() < deadline:
    time.sleep(0.01)
assert server.should_exit, "owner loss did not request a graceful server shutdown"
asyncio.run(lifecycle.finish_process_group_shutdown())
lifecycle.cancel_watchdog()
"""
    tree = ManagedProcessTree.spawn(
        [sys.executable, "-c", child_code, str(child_pid_file)],
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        log_path=tmp_path / "owner-loss.log",
    )
    deadline = time.monotonic() + 5
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text())
    tree.close_owner_watch()  # Simulate the Corona process closing on crash.
    assert tree.wait(timeout=8) == 0
    tree.wait_for_tree(grace_seconds=0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
