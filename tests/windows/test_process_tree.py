from __future__ import annotations

import ctypes
import os
import subprocess
import sys

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
