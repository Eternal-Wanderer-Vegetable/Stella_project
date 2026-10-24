from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from deploy.windows_reliability import is_file_locked, process_tree, wait_for_unlock

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native matrix")


def test_process_tree_contains_real_child(tmp_path):
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        nodes = process_tree(child.pid)
        assert any(node.pid == child.pid for node in nodes)
    finally:
        child.kill()
        child.wait()


def test_corona_process_tree_module_imports_on_windows():
    from corona import process_tree

    assert process_tree.ManagedProcessTree.__name__ == "ManagedProcessTree"


def test_corona_managed_process_tree_starts_the_child_in_its_job(tmp_path):
    from corona.process_tree import ManagedProcessTree

    log_path = tmp_path / "managed-child.log"
    tree = ManagedProcessTree.spawn(
        [sys.executable, "-c", "import os, time; print(os.getpid(), flush=True); time.sleep(30)"],
        cwd=Path(__file__).resolve().parents[2],
        env=os.environ.copy(),
        log_path=log_path,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if log_path.exists() and log_path.read_text(encoding="utf-8").strip():
                child_pid = int(log_path.read_text(encoding="utf-8").strip())
                assert tree.owns_pid(child_pid)
                return
            if tree.poll() is not None:
                break
            time.sleep(0.02)
        pytest.fail("managed child did not start inside its Windows Job Object")
    finally:
        tree.terminate()


def test_corona_managed_process_tree_suppresses_console_window(tmp_path):
    from corona.process_tree import ManagedProcessTree

    log_path = tmp_path / "console-window.log"
    tree = ManagedProcessTree.spawn(
        [
            sys.executable,
            "-c",
            "import ctypes; print(ctypes.windll.kernel32.GetConsoleWindow(), flush=True)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=os.environ.copy(),
        log_path=log_path,
    )
    try:
        assert tree.wait(timeout=10) == 0
        tree.wait_for_tree()
        assert log_path.read_text(encoding="utf-8").strip() == "0"
    finally:
        if tree.poll() is None:
            tree.terminate()


def test_file_lock_is_observable_and_clears(tmp_path):
    path = tmp_path / "locked.txt"
    path.write_text("locked", encoding="utf-8")
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(
        str(path),
        0x80000000,  # GENERIC_READ
        0,  # no sharing: an actual Windows exclusive handle
        None,
        3,  # OPEN_EXISTING
        0x80,
        None,
    )
    assert handle != ctypes.c_void_p(-1).value
    try:
        assert is_file_locked(path)
    finally:
        kernel32.CloseHandle(handle)
    assert wait_for_unlock(path, timeout=2)
