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


# ============================================================
# 机器级激活记录（S11 Phase 2）：版本化程序树的选择开关
# ============================================================

ACTIVE_RECORD_SCHEMA_VERSION = 1
_ACTIVATION_RECORD_FILENAME = "active-install.json"
ACTIVATION_APPS_DIRNAME = "app"


def machine_active_record_path() -> Path:
    """激活记录的机器级位置（INSTDIR 之外，旧卸载器/重装都碰不到）。

    与 config.home 指针（home.txt）同目录族：Windows 用
    ``%LOCALAPPDATA%\\Stella``，其余平台用 XDG ``~/.config/stella``。
    """
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stella" / _ACTIVATION_RECORD_FILENAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "stella" / _ACTIVATION_RECORD_FILENAME


def write_activation_record(
    *,
    version: str,
    tree_path: Path,
    tree_sha256: str | None = None,
    previous: dict | None = None,
) -> Path:
    """原子写入激活记录；previous 携带上代树（回滚开关的依据）。"""
    payload: dict = {
        "schema_version": ACTIVE_RECORD_SCHEMA_VERSION,
        "version": version,
        "path": str(Path(tree_path).resolve()),
        "previous": previous,
    }
    if tree_sha256:
        payload["tree_sha256"] = tree_sha256
    _atomic_json(machine_active_record_path(), payload)
    return machine_active_record_path()


def read_activation_record() -> dict | None:
    """读激活记录；缺失/损坏返回 None（调用方回退到旧解析路径）。"""
    path = machine_active_record_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_activation_record(record: dict, install_root: Path) -> Path:
    """校验激活记录并返回树路径；任何不合法抛 UpgradeError（调用方回退）。

    containment 铁律：树必须位于 ``<install_root>\\app`` 之下、单段版本名、
    且 ``bot.py`` 存在。记录内容是机器级持久状态，等同不可信输入。
    """
    if record.get("schema_version") != ACTIVE_RECORD_SCHEMA_VERSION:
        raise UpgradeError(
            "invalid_activation_record", "激活记录 schema 版本不受支持"
        )
    version = str(record.get("version") or "").strip()
    raw_path = str(record.get("path") or "").strip()
    if not version or "/" in version or "\\" in version:
        raise UpgradeError("invalid_activation_record", "激活记录版本非法")
    if not raw_path:
        raise UpgradeError("invalid_activation_record", "激活记录缺少树路径")
    install_root = Path(install_root).expanduser().resolve()
    apps_root = install_root / ACTIVATION_APPS_DIRNAME
    try:
        resolved = Path(raw_path).expanduser().resolve()
        resolved.relative_to(apps_root)
    except (OSError, ValueError) as exc:
        raise UpgradeError(
            "invalid_activation_record",
            f"激活树路径越界：{raw_path}（必须位于 {apps_root} 之下）",
            path=apps_root,
        ) from exc
    if not (resolved / "bot.py").is_file():
        raise UpgradeError(
            "invalid_activation_record", f"激活树缺少 bot.py：{resolved}",
            path=resolved,
        )
    return resolved


def rollback_activation() -> dict:
    """把激活记录翻转到 previous（滚回旧树）；当前树降为可滚回的 previous。

    双向：回滚后再执行一次即滚回新树。没有 previous 时明确拒绝。
    """
    record = read_activation_record()
    if not record:
        raise UpgradeError("rollback_unavailable", "没有激活记录可回滚")
    previous = record.get("previous")
    if not isinstance(previous, dict) or not previous.get("path"):
        raise UpgradeError(
            "rollback_unavailable", "激活记录没有可回滚的旧版本"
        )
    new_payload: dict = {
        "schema_version": ACTIVE_RECORD_SCHEMA_VERSION,
        "version": previous.get("version"),
        "path": previous.get("path"),
        "previous": {
            "version": record.get("version"),
            "path": record.get("path"),
        },
    }
    for key in ("tree_sha256",):
        if isinstance(previous, dict) and previous.get(key):
            new_payload[key] = previous[key]
    _atomic_json(machine_active_record_path(), new_payload)
    return new_payload


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
            from .install_state import process_identity

            payload = {
                "pid": os.getpid(),
                # 创建身份：恢复陈旧锁时区分「还是那个进程」与「PID 被复用」
                "identity": process_identity(os.getpid()),
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
        """Remove a lock only when its recorded owner is definitely gone.

        Windows 的 ``os.kill(pid, 0)`` 会 TerminateProcess——那是击杀，不是
        探测（F19）。探活改走 install_state 的三态原语：只有「确认死亡」
        或「进程活着但创建身份与记录不一致（PID 被复用）」才删锁；权限
        不足等 unknown 一律保留锁，绝不据此动手。
        """
        if not self.path.is_file():
            return False
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(owner, dict):
            return False
        if os.name != "nt":
            # POSIX：os.kill(pid, 0) 只做存在性检查，无副作用，保留轻量路径
            try:
                pid = int(owner["pid"])
            except (KeyError, TypeError, ValueError):
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
            except OSError:
                return False
            return False
        from .install_state import classify_owner

        if classify_owner(owner) != "stale":
            return False
        self.path.unlink(missing_ok=True)
        return True

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
    "ACTIVATION_APPS_DIRNAME",
    "ACTIVE_RECORD_SCHEMA_VERSION",
    "UpgradeError",
    "UpgradeLock",
    "UpgradeResult",
    "active_pointer",
    "machine_active_record_path",
    "read_activation_record",
    "read_active",
    "rollback_activation",
    "transactional_upgrade",
    "validate_activation_record",
    "write_activation_record",
]
