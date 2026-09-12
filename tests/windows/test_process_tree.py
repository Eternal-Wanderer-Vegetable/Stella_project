from __future__ import annotations

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
    with path.open(encoding="utf-8", newline=""):
        assert is_file_locked(path)
    assert wait_for_unlock(path, timeout=2)
