# Copyright (c) 2026 Stella Project Contributors
# This file is licensed under AGPL-3.0; see the repository LICENSE.
"""Transactional program-directory upgrades.

User data is never copied into the staged tree.  A small active-pointer file
selects the program tree, which makes a failed postflight recoverable without
trying to delete or replace files that may still be open on Windows.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class UpgradeError(RuntimeError):
    def __init__(self, code: str, message: str, *, path: Path | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path


@dataclass(frozen=True)
class UpgradeResult:
    version: str
    active_path: Path
    previous_path: Path | None
    rolled_back: bool = False


class UpgradeLock:
    """Cross-platform create-new lock with a durable owner record."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / ".stella" / "upgrade.lock"
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise UpgradeError("upgrade_in_progress", "已有升级操作正在进行中", path=self.path) from exc
        try:
            payload = {
                "pid": os.getpid(),
                "token": uuid.uuid4().hex,
            }
            os.write(fd, (json.dumps(payload) + "\n").encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        self._held = False

    def recover_stale(self) -> bool:
        """Remove a lock only when its recorded owner is definitely gone."""
        if not self.path.is_file():
            return False
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
            pid = int(owner["pid"])
        except (OSError, ValueError, TypeError, KeyError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self.path.unlink(missing_ok=True)
            return True
        except PermissionError:
            return False
        return False

    def __enter__(self) -> "UpgradeLock":  # noqa: PYI034
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
    finally:
        temporary = Path(name)
        if temporary.exists():
            temporary.unlink()


def active_pointer(data_root: Path) -> Path:
    return Path(data_root) / ".stella" / "active-install.json"


def read_active(data_root: Path) -> dict[str, object] | None:
    path = active_pointer(data_root)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpgradeError(
            "invalid_active_pointer", f"无法读取 active pointer：{path}", path=path
        ) from exc
    return value if isinstance(value, dict) else None


def transactional_upgrade(
    source: Path,
    *,
    version: str,
    data_root: Path,
    install_root: Path,
    postflight: Callable[[Path], None] | None = None,
    expected_checksum: str | None = None,
) -> UpgradeResult:
    """Stage, verify, postflight and activate a program tree atomically."""
    source = Path(source).expanduser().resolve()
    data_root = Path(data_root).expanduser().resolve()
    install_root = Path(install_root).expanduser().resolve()
    if not source.is_dir():
        raise UpgradeError("source_missing", f"升级源目录不存在：{source}", path=source)
    if not version or "/" in version or "\\" in version:
        raise UpgradeError("invalid_version", "升级版本必须是非空单路径名称")

    with UpgradeLock(data_root):
        staging_root = data_root / ".stella" / "upgrade-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staged = staging_root / f"{version}-{uuid.uuid4().hex}"
        previous = read_active(data_root)
        previous_path = (
            Path(str(previous["path"]))
            if previous and previous.get("path")
            else None
        )
        try:
            shutil.copytree(source, staged)
            source_digest = _tree_digest(source)
            if expected_checksum and source_digest != expected_checksum.lower():
                raise UpgradeError(
                    "checksum_mismatch",
                    "升级源 checksum 不匹配；active pointer 未改变",
                )
            staged_digest = _tree_digest(staged)
            if source_digest != staged_digest:
                raise UpgradeError("staging_checksum_mismatch", "升级暂存目录校验失败")
            if postflight is not None:
                postflight(staged)
            # Keep the versioned tree below the replaceable install root as
            # well as the staging copy. The pointer is the only activation
            # switch, so an open Windows handle never has to be replaced.
            install_root.mkdir(parents=True, exist_ok=True)
            installed = install_root / f"{version}-{uuid.uuid4().hex}"
            shutil.copytree(staged, installed)
            installed_digest = _tree_digest(installed)
            if installed_digest != staged_digest:
                raise UpgradeError(
                    "install_checksum_mismatch", "安装目录校验失败；active pointer 未改变"
                )
            _atomic_json(
                active_pointer(data_root),
                {
                    "version": version,
                    "path": str(installed),
                    "tree_sha256": staged_digest,
                },
            )
            shutil.rmtree(staged, ignore_errors=True)
            return UpgradeResult(version, installed, previous_path)
        except UpgradeError:
            shutil.rmtree(staged, ignore_errors=True)
            raise
        except OSError as exc:
            shutil.rmtree(staged, ignore_errors=True)
            raise UpgradeError("file_locked" if getattr(exc, "winerror", None) in {5, 32, 33} else "upgrade_failed", str(exc)) from exc
        except Exception as exc:
            shutil.rmtree(staged, ignore_errors=True)
            raise UpgradeError("postflight_failed", str(exc)) from exc


__all__ = [
    "UpgradeError",
    "UpgradeLock",
    "UpgradeResult",
    "active_pointer",
    "read_active",
    "transactional_upgrade",
]
