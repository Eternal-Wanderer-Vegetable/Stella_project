from __future__ import annotations

import json
import subprocess
import sys

import pytest

from deploy.upgrade import (
    UpgradeError,
    UpgradeLock,
    active_pointer,
    transactional_upgrade,
)


def _source(tmp_path, name: str, value: str):
    root = tmp_path / name
    root.mkdir()
    (root / "bot.py").write_text(value, encoding="utf-8")
    return root


def test_upgrade_stages_and_activates_without_touching_data(tmp_path):
    source = _source(tmp_path, "source", "new")
    data = tmp_path / "data"
    user_file = data / "memory" / "agent_memory.db"
    user_file.parent.mkdir(parents=True)
    user_file.write_bytes(b"user-data")

    result = transactional_upgrade(
        source,
        version="4.0.1",
        data_root=data,
        install_root=tmp_path / "install",
    )

    assert result.active_path.joinpath("bot.py").read_text(encoding="utf-8") == "new"
    assert user_file.read_bytes() == b"user-data"
    pointer = json.loads(active_pointer(data).read_text(encoding="utf-8"))
    assert pointer["version"] == "4.0.1"


def test_upgrade_postflight_failure_preserves_previous_active_pointer(tmp_path):
    first = _source(tmp_path, "first", "first")
    second = _source(tmp_path, "second", "second")
    data = tmp_path / "data"
    install = tmp_path / "install"
    transactional_upgrade(first, version="4.0.0", data_root=data, install_root=install)
    before = active_pointer(data).read_text(encoding="utf-8")

    with pytest.raises(UpgradeError, match="bad postflight"):
        transactional_upgrade(
            second,
            version="4.0.1",
            data_root=data,
            install_root=install,
            postflight=lambda _path: (_ for _ in ()).throw(RuntimeError("bad postflight")),
        )

    assert active_pointer(data).read_text(encoding="utf-8") == before
    assert not any((data / ".stella" / "upgrade-staging").iterdir())


def test_upgrade_lock_rejects_concurrent_operation(tmp_path):
    first = UpgradeLock(tmp_path)
    first.acquire()
    try:
        with pytest.raises(UpgradeError) as error:
            UpgradeLock(tmp_path).acquire()
        assert error.value.code == "upgrade_in_progress"
    finally:
        first.release()


def _spawn_sleeper():
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _write_lock_with_owner(tmp_path, pid: int, identity: str | None):
    from deploy.upgrade import UpgradeLock

    lock_path = UpgradeLock(tmp_path).path
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"pid": pid, "token": "stale-token"}
    if identity is not None:
        payload["identity"] = identity
    lock_path.write_text(json.dumps(payload), encoding="utf-8")
    return lock_path


def test_recover_stale_leaves_live_owner_process_alive_and_locked(tmp_path):
    """recover_stale 绝不允许终止存活的 owner 进程（F19：Windows os.kill 击杀）。"""
    proc = _spawn_sleeper()
    try:
        from deploy.install_state import process_identity

        lock_path = _write_lock_with_owner(
            tmp_path, proc.pid, process_identity(proc.pid)
        )
        assert UpgradeLock(tmp_path).recover_stale() is False
        assert lock_path.is_file(), "活 owner 的锁不得被删"
        assert proc.poll() is None, "recover_stale 不允许终止 owner 进程"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_recover_stale_removes_lock_only_after_owner_exits(tmp_path):
    proc = _spawn_sleeper()
    try:
        from deploy.install_state import process_identity

        lock_path = _write_lock_with_owner(
            tmp_path, proc.pid, process_identity(proc.pid)
        )
        proc.kill()
        proc.wait(timeout=10)
        assert UpgradeLock(tmp_path).recover_stale() is True
        assert not lock_path.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_recover_stale_treats_pid_reuse_as_stale(tmp_path):
    """进程活着但创建身份与记录不符 = PID 被复用 → 陈旧，可恢复。"""
    import os

    lock_path = _write_lock_with_owner(tmp_path, os.getpid(), "win-creation-42")
    assert UpgradeLock(tmp_path).recover_stale() is True
    assert not lock_path.exists()


def test_recover_stale_keeps_lock_when_owner_identity_unknown(tmp_path):
    """身份不明的活 owner（旧格式锁记录）→ 保守保留锁，不删。"""
    import os

    lock_path = _write_lock_with_owner(tmp_path, os.getpid(), None)
    assert UpgradeLock(tmp_path).recover_stale() is False
    assert lock_path.is_file()


def test_upgrade_checksum_failure_keeps_active_pointer(tmp_path):
    source = _source(tmp_path, "source", "new")
    data = tmp_path / "data"
    with pytest.raises(UpgradeError, match="checksum"):
        transactional_upgrade(
            source,
            version="4.0.1",
            data_root=data,
            install_root=tmp_path / "install",
            expected_checksum="0" * 64,
        )
    assert active_pointer(data).exists() is False
