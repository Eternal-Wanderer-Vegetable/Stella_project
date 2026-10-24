# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Real-process coverage for Corona ownership, health, failure, and fencing."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

try:
    import resource
except ImportError:  # pragma: no cover - Windows CI does not expose resource
    resource = None

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
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

mode = sys.argv[1]
writer_lock = None
if mode.startswith("exclusive_"):
    import fcntl

    lock_path = Path(os.environ["STELLA_HOME"]) / "cn10-core-writer.lock"
    writer_lock = lock_path.open("a+")
    try:
        fcntl.flock(writer_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(92)
    with (lock_path.parent / "cn10-core-writer-pids.txt").open("a") as stream:
        stream.write(f"{os.getpid()}\n")
    mode = {
        "exclusive_ready": "ready",
        "exclusive_crash": "crash",
        "exclusive_crash_after_ready": "crash_after_ready_triggered",
    }[mode]
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
if mode == "crash_after_ready_triggered":
    crash_marker = (
        Path(os.environ["STELLA_HOME"])
        / f"cn10-crash-after-ready-{identity['generation_id']}"
    )

    def wait_for_crash_trigger():
        deadline = time.monotonic() + 30
        while not crash_marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.005)
        if crash_marker.is_file():
            os._exit(41)

    threading.Thread(target=wait_for_crash_trigger, daemon=True).start()
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
    try:
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
        if os.name == "nt":
            from stella_bootstrap.config import _check_windows_private_acl

            _check_windows_private_acl(log_path)
        else:
            assert log_path.stat().st_mode & 0o777 == 0o600
    finally:
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
            "crash_after_ready_triggered",
        ],
    )
    try:
        ready = await supervisor.start()
        assert ready.phase == "ready"
        crash_generations = {ready.generation_id}
        (bootstrap.stella_home / f"cn10-crash-after-ready-{ready.generation_id}").touch()
        deadline = time.monotonic() + 5
        while supervisor.snapshot.phase != "failed" and time.monotonic() < deadline:
            current = supervisor.snapshot
            if (
                current.phase == "ready"
                and current.generation_id not in crash_generations
            ):
                crash_generations.add(current.generation_id)
                (bootstrap.stella_home / f"cn10-crash-after-ready-{current.generation_id}").touch()
            await asyncio.sleep(0.02)
        assert supervisor.snapshot.phase == "failed"
        assert supervisor.snapshot.attempt == 2
        assert supervisor.snapshot.error_code == "core_crashed"
        assert supervisor._tree is None
    finally:
        await supervisor.stop()


@pytest.mark.skipif(
    sys.platform != "linux", reason="CN10 resource soak uses Linux /proc and flock"
)
@pytest.mark.asyncio
async def test_linux_real_core_100_cycles_do_not_leak_or_overlap(
    tmp_path: Path,
) -> None:
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cn10-soak")
    asyncio.get_running_loop().set_default_executor(executor)
    bootstrap = _bootstrap(tmp_path, instance_id="cn10-process-soak")
    selected_mode = ["exclusive_ready"]
    supervisor = CoreSupervisor(
        bootstrap,
        readiness_timeout=5,
        poll_interval=0.02,
        backoff_base=0.01,
        max_attempts=1,
        command_factory=lambda _boot: [
            sys.executable,
            "-c",
            _FAKE_CORE,
            selected_mode[0],
        ],
    )
    samples: list[dict[str, int]] = []
    ready_pids: list[int] = []
    cycle_modes = ("exclusive_ready", "exclusive_crash", "exclusive_crash_after_ready")

    def resources() -> dict[str, int]:
        return {
            "fd_count": sum(1 for _ in Path("/proc/self/fd").iterdir()),
            "thread_count": sum(1 for _ in Path("/proc/self/task").iterdir()),
            "pending_async_tasks": sum(
                not task.done() for task in asyncio.all_tasks()
            ),
            "controller_peak_rss_kib": int(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            ),
        }

    try:
        # asyncio.to_thread uses a lazy default executor. Start all workers before
        # sampling so runner-specific pool growth is not mistaken for a leak.
        worker_barrier = threading.Barrier(4)
        await asyncio.gather(
            *(asyncio.to_thread(worker_barrier.wait, timeout=5) for _ in range(4))
        )
        for cycle in range(100):
            selected_mode[0] = cycle_modes[cycle % len(cycle_modes)]
            snapshot = await supervisor.start()
            if selected_mode[0] == "exclusive_ready":
                assert snapshot.phase == "ready"
                assert snapshot.pid is not None
                ready_pids.append(snapshot.pid)
                await supervisor.stop()
            elif selected_mode[0] == "exclusive_crash":
                assert snapshot.phase == "failed"
                assert snapshot.error_code == "process_exited_before_ready"
                await supervisor.stop()
            else:
                assert snapshot.phase == "ready"
                assert snapshot.pid is not None
                assert snapshot.generation_id is not None
                ready_pids.append(snapshot.pid)
                crash_marker = (
                    Path(bootstrap.stella_home)
                    / f"cn10-crash-after-ready-{snapshot.generation_id}"
                )
                crash_marker.touch()
                deadline = time.monotonic() + 5
                while supervisor.snapshot.phase != "failed" and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)
                assert supervisor.snapshot.phase == "failed"
                assert supervisor._tree is None
                await supervisor.stop()
            assert supervisor.snapshot.phase == "stopped"
            assert supervisor._tree is None
            await asyncio.sleep(0.01)
            samples.append(resources())

        writer_pids = [
            int(line)
            for line in (Path(bootstrap.stella_home) / "cn10-core-writer-pids.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert len(writer_pids) == 100
        assert len(set(writer_pids)) == 100
        assert len(set(ready_pids)) == len(ready_pids)
        assert all(not Path(f"/proc/{pid}").exists() for pid in writer_pids)

        log_files = list(
            (runtime_dir(bootstrap.stella_home, bootstrap.instance_id) / "generations")
            .glob("*/nucleus.log")
        )
        assert len(log_files) == 100

        # Ignore startup and executor-pool warm-up. Compare fixed 20-cycle windows
        # and allow small allocator/pytest noise instead of claiming zero variation.
        warm_window = samples[40:60]
        final_window = samples[80:100]
        medians = {
            key: {
                "warm": statistics.median(item[key] for item in warm_window),
                "final": statistics.median(item[key] for item in final_window),
                "final_max": max(item[key] for item in final_window),
            }
            for key in ("fd_count", "thread_count", "pending_async_tasks")
        }
        assert medians["fd_count"]["final"] <= medians["fd_count"]["warm"] + 2
        assert medians["fd_count"]["final_max"] <= medians["fd_count"]["warm"] + 4
        assert medians["thread_count"]["final"] <= medians["thread_count"]["warm"] + 1
        assert medians["thread_count"]["final_max"] <= medians["thread_count"]["warm"] + 2
        assert medians["pending_async_tasks"]["final"] <= medians["pending_async_tasks"]["warm"] + 1
        assert medians["pending_async_tasks"]["final_max"] <= medians["pending_async_tasks"]["warm"] + 2

        evidence = {
            "scope": "CN10 A31 Linux real child process soak",
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cycles": 100,
            "cycle_pattern": list(cycle_modes),
            "warmup_cycles_excluded": 40,
            "comparison_windows": {"warm": "cycles 41-60", "final": "cycles 81-100"},
            "tolerance": {"fd_median_delta": 2, "fd_final_max_delta": 4,
                          "thread_median_delta": 1, "thread_final_max_delta": 2,
                          "pending_async_task_median_delta": 1,
                          "pending_async_task_final_max_delta": 2},
            "resource_windows": medians,
            "peak_controller_rss_kib": max(item["controller_peak_rss_kib"] for item in samples),
            "orphan_child_processes": 0,
            "per_generation_log_files": len(log_files),
            "log_queue": "not_applicable; supervisor redirects each child to a generation log file",
            "unique_child_pids": len(set(writer_pids)),
            "single_writer_flock": "100/100 child processes acquired exclusive lock serially",
        }
        output_dir = os.environ.get("STELLA_CN10_EVIDENCE_DIR")
        if output_dir:
            evidence_path = Path(output_dir) / "cn10-process-soak.json"
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print("CN10_METRIC " + json.dumps(evidence, sort_keys=True))
    finally:
        try:
            await supervisor.stop()
        finally:
            executor.shutdown(wait=True)


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
        readiness_timeout=3,
        poll_interval=0.03,
        max_attempts=1,
        command_factory=lambda _boot: [sys.executable, "-c", _FAKE_CORE, mode],
    )
    failed = await supervisor.start()
    try:
        assert failed.phase == "failed"
        assert failed.error_code == expected_error
        assert supervisor._tree is None
    finally:
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


def test_windows_process_tree_hides_console_for_exec_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    from types import SimpleNamespace

    import corona.process_tree as process_tree
    from stella_bootstrap import config as bootstrap_config

    create_new_process_group = 0x00000200
    create_no_window = 0x08000000
    monkeypatch.setattr(
        process_tree,
        "os",
        SimpleNamespace(
            name="nt",
            open=os.open,
            fdopen=os.fdopen,
            getpid=os.getpid,
            O_CREAT=os.O_CREAT,
            O_WRONLY=os.O_WRONLY,
            O_TRUNC=os.O_TRUNC,
        ),
    )
    monkeypatch.setattr(
        bootstrap_config, "_set_windows_private_acl", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        process_tree.subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        create_new_process_group,
        raising=False,
    )
    monkeypatch.setattr(
        process_tree.subprocess,
        "CREATE_NO_WINDOW",
        create_no_window,
        raising=False,
    )
    monkeypatch.setattr(process_tree, "_WindowsJob", lambda _process: None)

    captured: dict[str, object] = {}
    fake_process = SimpleNamespace(pid=12345, stdin=io.BytesIO())

    def fake_popen(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return fake_process

    monkeypatch.setattr(process_tree.subprocess, "Popen", fake_popen)

    tree = process_tree.ManagedProcessTree.spawn(
        ["python", "-m", "nucleus"],
        cwd=tmp_path,
        env={},
        log_path=tmp_path / "nucleus.log",
    )
    try:
        flags = captured["creationflags"]
        assert flags & create_new_process_group
        assert flags & create_no_window
    finally:
        tree._close_log()


def test_windows_exec_wrapper_hides_console_for_managed_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    from types import SimpleNamespace

    import corona._exec_tree as exec_tree

    create_no_window = 0x08000000
    monkeypatch.setattr(
        exec_tree,
        "os",
        SimpleNamespace(name="nt", environ={"STELLA_CONTROLLER_PID": "1"}),
    )
    monkeypatch.setattr(
        exec_tree,
        "sys",
        SimpleNamespace(
            argv=["corona._exec_tree", "python", "-m", "nucleus"],
            stdin=SimpleNamespace(buffer=io.BytesIO(b"\x01")),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        ),
    )
    monkeypatch.setattr(exec_tree, "_arm_parent_death_signal", lambda: None)
    monkeypatch.setattr(
        exec_tree.subprocess, "CREATE_NO_WINDOW", create_no_window, raising=False
    )

    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(wait=lambda: 0)

    monkeypatch.setattr(exec_tree.subprocess, "Popen", fake_popen)

    assert exec_tree.main() == 0
    assert captured["creationflags"] & create_no_window
    assert captured["stdin"] == subprocess.DEVNULL
    assert captured["stdout"] is exec_tree.sys.stdout
    assert captured["stderr"] is exec_tree.sys.stderr


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
    ready_file = tmp_path / "owner-loss-ready"
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
open(sys.argv[2], "w", encoding="ascii").write("ready")
deadline = time.monotonic() + 5
while not server.should_exit and time.monotonic() < deadline:
    time.sleep(0.01)
assert server.should_exit, "owner loss did not request a graceful server shutdown"
asyncio.run(lifecycle.finish_process_group_shutdown())
lifecycle.cancel_watchdog()
"""
    tree = ManagedProcessTree.spawn(
        [sys.executable, "-c", child_code, str(child_pid_file), str(ready_file)],
        cwd=ROOT,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT)},
        log_path=tmp_path / "owner-loss.log",
    )
    deadline = time.monotonic() + 5
    while not ready_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready_file.exists()
    assert child_pid_file.exists()
    child_pid = int(child_pid_file.read_text())
    tree.close_owner_watch()  # Simulate the Corona process closing on crash.
    assert tree.wait(timeout=8) == 0
    tree.wait_for_tree(grace_seconds=0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
