# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Small gated exec wrapper for atomic process-tree ownership assignment."""

from __future__ import annotations

import ctypes
import os
import signal
import sys


def _arm_parent_death_signal() -> None:
    if not sys.platform.startswith("linux"):
        return
    expected_parent = int(os.environ.get("STELLA_CONTROLLER_PID", "0"))
    if expected_parent < 1:
        raise RuntimeError("controller pid is missing")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGTERM)


def main() -> int:
    command = sys.argv[1:]
    if not command:
        return 64
    _arm_parent_death_signal()
    # The controller assigns the blocked Windows process to a kill-on-close Job
    # Object before releasing this gate. On POSIX it gives it a fresh process
    # group before starting the managed command.
    if sys.stdin.buffer.read(1) != b"\x01":
        return 65
    expected_parent = int(os.environ.get("STELLA_CONTROLLER_PID", "0"))
    if expected_parent > 0 and os.getppid() != expected_parent:
        return 66
    executable = command[0]
    os.execvpe(executable, command, os.environ)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
