# Copyright (c) 2026 Stella Project Contributors
# This file is licensed under AGPL-3.0; see the repository LICENSE.
"""Small Windows-native helpers used by upgrade and process diagnostics.

The helpers deliberately keep the platform boundary narrow.  Linux and macOS
callers receive a deterministic "unsupported" result instead of pretending
that a POSIX process tree or share mode is equivalent to Windows.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


@dataclass(frozen=True)
class ProcessNode:
    pid: int
    parent_pid: int | None
    name: str
    command_line: str | None = None


def process_tree(pid: int) -> list[ProcessNode]:
    """Return a best-effort Windows process tree rooted at ``pid``."""
    if os.name != "nt":
        return []
    script = (
        "$ErrorActionPreference='Stop'; "
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return []
    import json

    raw = json.loads(result.stdout or "[]")
    if isinstance(raw, dict):
        raw = [raw]
    nodes = {
        int(item["ProcessId"]): ProcessNode(
            pid=int(item["ProcessId"]),
            parent_pid=(
                int(item["ParentProcessId"])
                if item.get("ParentProcessId") is not None
                else None
            ),
            name=str(item.get("Name") or ""),
            command_line=item.get("CommandLine"),
        )
        for item in raw
        if item.get("ProcessId") is not None
    }
    selected: set[int] = {pid}
    changed = True
    while changed:
        changed = False
        for node in nodes.values():
            if node.parent_pid in selected and node.pid not in selected:
                selected.add(node.pid)
                changed = True
    return [nodes[item] for item in sorted(selected) if item in nodes]


def file_lock_error(path: Path) -> int | None:
    """Return the Win32 error code when ``path`` cannot be opened exclusively."""
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x80000000,  # GENERIC_READ
        0,
        None,
        3,  # OPEN_EXISTING
        0x80,  # FILE_ATTRIBUTE_NORMAL
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle == -1:
        return int(ctypes.get_last_error())
    close_handle(handle)
    return None


def is_file_locked(path: Path) -> bool:
    """Whether Windows reports a sharing or lock violation for ``path``."""
    error = file_lock_error(path)
    return error in {ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION}


def wait_for_unlock(path: Path, timeout: float = 10.0, interval: float = 0.1) -> bool:
    """Wait for a file to become exclusively openable."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_file_locked(path):
            return True
        time.sleep(interval)
    return not is_file_locked(path)


__all__ = ["ProcessNode", "file_lock_error", "is_file_locked", "process_tree", "wait_for_unlock"]
