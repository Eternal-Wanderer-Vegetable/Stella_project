# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Own a managed child process and its descendants as one OS process tree."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path


class ProcessTreeError(RuntimeError):
    """The OS could not establish or terminate the managed process tree."""


class ManagedProcessTree:
    def __init__(self, process: subprocess.Popen, log_stream, job=None) -> None:
        self.process = process
        self.pid = process.pid
        self.log_stream = log_stream
        self._job = job
        self._owner_watch_write_fd: int | None = None
        self._observed_exit_code: int | None = None

    @classmethod
    def spawn(
        cls,
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> ManagedProcessTree:
        if not command:
            raise ValueError("managed process command cannot be empty")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            try:
                from stella_bootstrap.config import _set_windows_private_acl

                _set_windows_private_acl(log_path.parent, is_directory=True)
            except Exception as exc:
                raise ProcessTreeError("could not protect managed process logs") from exc
        if os.name != "nt":
            log_path.parent.chmod(0o700)
        descriptor = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        log_stream = os.fdopen(descriptor, "wb", buffering=0)
        child_env = dict(env)
        child_env["STELLA_CONTROLLER_PID"] = str(os.getpid())
        owner_watch_read_fd: int | None = None
        owner_watch_write_fd: int | None = None
        wrapper = [sys.executable, "-m", "corona._exec_tree", *command]
        creationflags = 0
        popen_args: dict = {}
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            owner_watch_read_fd, owner_watch_write_fd = os.pipe()
            os.set_inheritable(owner_watch_read_fd, True)
            child_env["STELLA_CONTROLLER_WATCH_FD"] = str(owner_watch_read_fd)
            popen_args["start_new_session"] = True
            popen_args["pass_fds"] = (owner_watch_read_fd,)
        try:
            process = subprocess.Popen(
                wrapper,
                cwd=cwd,
                env=child_env,
                stdin=subprocess.PIPE,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=creationflags,
                **popen_args,
            )
        except Exception:
            if owner_watch_read_fd is not None:
                os.close(owner_watch_read_fd)
            if owner_watch_write_fd is not None:
                os.close(owner_watch_write_fd)
            log_stream.close()
            raise

        if owner_watch_read_fd is not None:
            os.close(owner_watch_read_fd)

        job = None
        try:
            if os.name == "nt":
                job = _WindowsJob(process)
            assert process.stdin is not None
            process.stdin.write(b"\x01")
            process.stdin.flush()
            process.stdin.close()
            tree = cls(process, log_stream, job)
            tree._owner_watch_write_fd = owner_watch_write_fd
            return tree
        except Exception as exc:
            if owner_watch_write_fd is not None:
                os.close(owner_watch_write_fd)
            if job is not None:
                job.terminate(1)
                job.close()
            else:
                _kill_process_group(process.pid)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log_stream.close()
            if isinstance(exc, ProcessTreeError):
                raise
            raise ProcessTreeError("could not establish managed process ownership") from exc

    def poll(self) -> int | None:
        if os.name != "nt" and hasattr(os, "waitid"):
            return self._peek_posix_exit()
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        if os.name != "nt" and hasattr(os, "waitid"):
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                exit_code = self._peek_posix_exit()
                if exit_code is not None:
                    return exit_code
                if deadline is not None and time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(self.process.args, timeout)
                time.sleep(0.01)
        return self.process.wait(timeout=timeout)

    def _peek_posix_exit(self) -> int | None:
        if self._observed_exit_code is not None:
            return self._observed_exit_code
        try:
            info = os.waitid(
                os.P_PID,
                self.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except (ChildProcessError, OSError):
            # A platform or an external caller may have reaped the Popen child.
            self._observed_exit_code = self.process.poll()
            return self._observed_exit_code
        if info is None or info.si_pid == 0:
            return None
        if info.si_code == os.CLD_EXITED:
            self._observed_exit_code = int(info.si_status)
        else:
            self._observed_exit_code = -int(info.si_status)
        return self._observed_exit_code

    def wait_for_tree(self, *, grace_seconds: float = 0.5) -> None:
        """After the root exits, reap any surviving descendants in its tree."""
        if self._job is not None:
            # Once the root has exited, any process left in its Job Object is an
            # orphan from the generation. Closing a kill-on-close job fences it.
            self._job.terminate(0)
            self._job.close()
            self._job = None
            self._close_log()
            return
        _terminate_process_group(
            self.pid, grace_seconds=grace_seconds, exclude_pid=self.pid
        )
        # Keep the exited group leader unreaped until its descendants are gone.
        self.process.wait()
        self._close_log()

    def terminate(self, *, grace_seconds: float = 2.0) -> None:
        if self._job is not None:
            self._job.terminate(1)
            with suppress(subprocess.TimeoutExpired):
                self.process.wait(timeout=max(0.1, grace_seconds))
            self._job.close()
            self._job = None
        else:
            _kill_process_group(self.pid, signal.SIGTERM)
            try:
                self.wait(timeout=max(0.1, grace_seconds))
            except subprocess.TimeoutExpired:
                _kill_process_group(self.pid, signal.SIGKILL)
                self.wait(timeout=5)
            _terminate_process_group(
                self.pid, grace_seconds=grace_seconds, exclude_pid=self.pid
            )
            self.process.wait()
        self._close_log()

    def _close_log(self) -> None:
        self.close_owner_watch()
        if not self.log_stream.closed:
            self.log_stream.flush()
            self.log_stream.close()

    def close_owner_watch(self) -> None:
        """Release the owner pipe after an orderly stop or cleanup."""
        descriptor, self._owner_watch_write_fd = self._owner_watch_write_fd, None
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)

    def owns_pid(self, pid: int) -> bool:
        """Return whether a process is inside this managed Windows Job Object."""
        if self._job is None:
            return pid == self.pid
        return self._job.contains_pid(pid)


def _kill_process_group(pgid: int, sig: int | None = None) -> None:
    if os.name == "nt":
        return
    if sig is None:
        sig = signal.SIGKILL
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return


def _process_group_alive(pgid: int) -> bool:
    if os.name == "nt":
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_process_group(
    pgid: int, *, grace_seconds: float, exclude_pid: int | None = None
) -> None:
    if os.name == "nt" or not _process_group_alive(pgid):
        return
    members = _process_group_members(pgid)
    if members is None:
        _kill_process_group(pgid, signal.SIGTERM)
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while time.monotonic() < deadline and _process_group_alive(pgid):
            time.sleep(0.025)
        if _process_group_alive(pgid):
            _kill_process_group(pgid, signal.SIGKILL)
        return
    members.discard(exclude_pid)
    if members:
        _kill_process_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while time.monotonic() < deadline and _process_group_members(pgid, exclude_pid):
        time.sleep(0.025)
    remaining = _process_group_members(pgid, exclude_pid)
    if remaining:
        _kill_process_group(pgid, signal.SIGKILL)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and _process_group_members(pgid, exclude_pid):
            time.sleep(0.025)


def _process_group_members(
    pgid: int, exclude_pid: int | None = None
) -> set[int] | None:
    members: set[int] = set()
    proc_root = Path("/proc")
    if proc_root.is_dir():
        for entry in proc_root.iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                stat_line = (entry / "stat").read_text(encoding="ascii")
                fields = stat_line[stat_line.rfind(")") + 2 :].split()
                if fields[0] != "Z" and int(fields[2]) == pgid:
                    pid = int(entry.name)
                    if pid != exclude_pid:
                        members.add(pid)
            except (OSError, ValueError, IndexError):
                continue
        return members
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat="],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and not fields[2].startswith("Z"):
            try:
                pid = int(fields[0])
                if int(fields[1]) == pgid and pid != exclude_pid:
                    members.add(pid)
            except ValueError:
                continue
    return members


class _WindowsJob:
    """Kill-on-close Job Object; assignment precedes release of the child gate."""

    def __init__(self, process: subprocess.Popen) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, wintypes.INT, wintypes.LPVOID, wintypes.DWORD
        ]
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.IsProcessInJob.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)
        ]
        self._kernel32.IsProcessInJob.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ProcessTreeError("CreateJobObjectW failed")
        info = ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
            self._handle, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            self.close()
            raise ProcessTreeError("SetInformationJobObject failed")
        if not self._kernel32.AssignProcessToJobObject(self._handle, process._handle):
            self.close()
            raise ProcessTreeError("AssignProcessToJobObject failed")

    def terminate(self, exit_code: int) -> None:
        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, exit_code)

    def contains_pid(self, pid: int) -> bool:
        if not self._handle or pid < 1:
            return False
        process = self._kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not process:
            return False
        try:
            in_job = self._wintypes.BOOL()
            succeeded = self._kernel32.IsProcessInJob(
                process, self._handle, self._ctypes.byref(in_job)
            )
            return bool(succeeded and in_job.value)
        finally:
            self._kernel32.CloseHandle(process)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
