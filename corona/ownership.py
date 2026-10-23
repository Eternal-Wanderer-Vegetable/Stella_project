# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Process-held lock ensuring one Corona controller per instance."""

from __future__ import annotations

import os
from pathlib import Path

from typing_extensions import Self

from stella_bootstrap.identity import runtime_dir


class CoronaOwnershipError(RuntimeError):
    """Another controller owns this instance or the lock cannot be secured."""


class CoronaOwnershipLock:
    def __init__(self, path: Path, descriptor: int) -> None:
        self.path = path
        self._descriptor = descriptor

    @classmethod
    def acquire(cls, stella_home: Path, instance_id: str) -> CoronaOwnershipLock:
        lock_dir = runtime_dir(stella_home, instance_id) / "corona"
        try:
            lock_dir.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                lock_dir.chmod(0o700)
            path = lock_dir / "ownership.lock"
            flags = os.O_CREAT | os.O_RDWR
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(path, flags, 0o600)
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
        except OSError as exc:
            raise CoronaOwnershipError("could not establish Corona ownership lock") from exc

        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return cls(path, descriptor)
        except OSError as exc:
            os.close(descriptor)
            raise CoronaOwnershipError("another Corona controller owns this instance") from exc

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor < 0:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(descriptor)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
