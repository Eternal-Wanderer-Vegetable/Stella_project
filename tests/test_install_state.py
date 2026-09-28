# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""install_state 的行为测试：三态探活、进程身份、跨进程安装锁与账本。

只操作测试自己创建的子进程与临时目录，绝不触碰系统里的无关进程。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from deploy import install_state


def _spawn_sleeper() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ============================================================
# 三态探活与进程身份
# ============================================================


def test_probe_pid_three_states():
    assert install_state.probe_pid(0) == install_state.GONE
    assert install_state.probe_pid(-5) == install_state.GONE
    # 当前进程必然存活
    import os

    assert install_state.probe_pid(os.getpid()) == install_state.ALIVE
    # 自己创建、已退出的子进程 → gone（不是 unknown，更不是误杀）
    proc = _spawn_sleeper()
    proc.kill()
    proc.wait(timeout=10)
    assert install_state.probe_pid(proc.pid) == install_state.GONE


def test_probe_never_kills_a_live_child():
    """探活前后被测进程必须仍然活着（os.kill(pid,0) 语义的回归防线）。"""
    proc = _spawn_sleeper()
    try:
        assert install_state.probe_pid(proc.pid) == install_state.ALIVE
        assert proc.poll() is None, "probe 不允许终止目标进程"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_process_identity_is_stable_and_nonempty_for_self():
    import os

    identity = install_state.process_identity(os.getpid())
    assert identity
    assert identity == install_state.process_identity(os.getpid())


# ============================================================
# 跨进程安装锁
# ============================================================


def test_lock_acquire_release_and_mutex(tmp_path):
    lock = install_state.InstallLock(tmp_path)
    lock.acquire()
    try:
        assert install_state.lock_path(tmp_path).is_file()
        other = install_state.InstallLock(tmp_path)
        with pytest.raises(install_state.InstallLockError) as error:
            other.acquire(recover_stale=False)
        assert error.value.code == "install_in_progress"
    finally:
        lock.release()
    assert not install_state.lock_path(tmp_path).exists()
    # 释放后可重新获取
    other = install_state.InstallLock(tmp_path)
    other.acquire()
    other.release()


def test_lock_records_owner_identity(tmp_path):
    lock = install_state.InstallLock(tmp_path)
    lock.acquire()
    try:
        payload = json.loads(
            install_state.lock_path(tmp_path).read_text(encoding="utf-8")
        )
        assert payload["pid"] > 0
        assert payload["identity"], "锁必须记录进程创建身份以供 PID 复用判定"
    finally:
        lock.release()


def test_lock_recovers_only_when_owner_definitely_gone(tmp_path):
    """死 owner 的锁被恢复；活 owner（含身份不明）的锁绝不被动。"""
    proc = _spawn_sleeper()
    try:
        # 活 owner（真实身份）→ 互斥拒绝，锁保留
        lock_path = install_state.lock_path(tmp_path)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "identity": install_state.process_identity(proc.pid),
                }
            ),
            encoding="utf-8",
        )
        other = install_state.InstallLock(tmp_path)
        with pytest.raises(install_state.InstallLockError):
            other.acquire()
        assert lock_path.is_file()

        # owner 死亡 → 恢复陈旧锁并成功获取
        proc.kill()
        proc.wait(timeout=10)
        other.acquire()  # 不抛 = 恢复成功
        other.release()
        assert not lock_path.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_lock_pid_reuse_is_detected_as_stale(tmp_path):
    """进程活着但身份与记录不符 = PID 被复用，原 owner 已死 → 可恢复。"""
    import os

    lock_path = install_state.lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "identity": "win-creation-123"}),
        encoding="utf-8",
    )
    lock = install_state.InstallLock(tmp_path)
    lock.acquire()  # 身份不匹配 → stale → 恢复成功
    lock.release()


def test_lock_unknown_owner_is_never_recovered(tmp_path):
    """身份不明（无 identity 记录且进程存活）→ 保守拒绝，绝不删锁。"""
    import os

    lock_path = install_state.lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    lock = install_state.InstallLock(tmp_path)
    with pytest.raises(install_state.InstallLockError):
        lock.acquire()
    assert lock_path.is_file(), "unknown 归属的锁必须原样保留"


# ============================================================
# 安装账本
# ============================================================


def test_ledger_lifecycle_and_component_transitions(tmp_path):
    ledger = install_state.new_ledger(
        tmp_path,
        profile="oneclick-python",
        catalog_sha256="a" * 64,
        components=["llama-cpu", "napcat"],
    )
    assert ledger["state"] == install_state.LEDGER_RUNNING
    assert ledger["operation_id"]
    assert set(ledger["components"]) == {"llama-cpu", "napcat"}

    install_state.set_component(
        tmp_path, "llama-cpu",
        state=install_state.COMPONENT_VERIFIED, expected_digest="b" * 64,
    )
    install_state.set_component(
        tmp_path, "llama-cpu", state=install_state.COMPONENT_HEALTHY
    )
    record = install_state.read_ledger(tmp_path)["components"]["llama-cpu"]
    assert record["state"] == install_state.COMPONENT_HEALTHY
    assert record["expected_digest"] == "b" * 64
    assert record["attempts"] == 2

    install_state.set_component(
        tmp_path, "napcat",
        state=install_state.COMPONENT_FAILED,
        error_code="install_failed", error_message="MSI 爆炸",
    )
    failed = install_state.read_ledger(tmp_path)["components"]["napcat"]
    assert failed["state"] == install_state.COMPONENT_FAILED
    assert failed["error_code"] == "install_failed"

    install_state.update_ledger(tmp_path, state=install_state.LEDGER_READY)
    assert install_state.read_ledger(tmp_path)["state"] == install_state.LEDGER_READY


def test_classify_previous_ledger_transitions_dead_owner_running(tmp_path):
    """崩溃残留（running 且 owner 已死）必须转 interrupted；活 owner 保持 running。"""
    install_state.new_ledger(
        tmp_path, profile="oneclick-python", components=["napcat"]
    )
    # owner 是当前进程（活着）→ 保持 running
    assert (
        install_state.classify_previous_ledger(tmp_path, owner_present=True)
        == install_state.LEDGER_RUNNING
    )
    # owner 已死 → interrupted 并写回
    ledger = install_state.read_ledger(tmp_path)
    ledger["owner"] = {"pid": 999999, "identity": "whatever"}
    install_state.write_ledger(tmp_path, ledger)
    assert (
        install_state.classify_previous_ledger(tmp_path, owner_present=False)
        == install_state.LEDGER_INTERRUPTED
    )
    assert (
        install_state.read_ledger(tmp_path)["state"]
        == install_state.LEDGER_INTERRUPTED
    )


def test_ledger_write_is_atomic(tmp_path):
    """账本写入必须走临时文件 + replace（写入中途被杀不留半写 JSON）。"""
    real_replace = Path.replace
    calls: list[str] = []

    def spy_replace(self, target):
        calls.append(str(target))
        return real_replace(self, target)

    import unittest.mock

    with unittest.mock.patch.object(Path, "replace", spy_replace):
        install_state.new_ledger(tmp_path, profile="p", components=["x"])
    assert calls, "账本必须经临时文件 replace 落盘"
