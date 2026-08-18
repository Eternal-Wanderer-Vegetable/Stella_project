# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""deploy 进程管理的单元测试。

只测不依赖真实启停信号的部分：PID 文件读写、进程存活判断（用短命子进程）、
stop/status 的边界。真实启停信号依赖平台（Windows 的 CTRL_BREAK 行为），
留给手工验证。
"""

from __future__ import annotations

import subprocess
import sys
import time

from deploy import process


def _short_lived(seconds: float = 5.0):
    """起一个短暂运行的子进程（Windows 下独立进程组，与 start_detached 一致）。"""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    return proc, proc.pid


def test_pid_roundtrip(monkeypatch, tmp_path):
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    assert process.read_pid() is None
    process.write_pid(12345)
    assert process.read_pid() == 12345
    process.clear_pid()
    assert process.read_pid() is None


def test_read_pid_invalid_content(monkeypatch, tmp_path):
    pid_file = tmp_path / "stella.pid"
    pid_file.write_text("not-a-number", encoding="utf-8")
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    assert process.read_pid() is None


def test_is_alive_true_for_running(monkeypatch, tmp_path):
    monkeypatch.setattr(process, "PID_FILE", tmp_path / "stella.pid")
    proc, pid = _short_lived(5.0)
    try:
        assert process.is_alive(pid) is True
    finally:
        proc.terminate()
        proc.wait()


def test_is_alive_false_for_dead(monkeypatch, tmp_path):
    monkeypatch.setattr(process, "PID_FILE", tmp_path / "stella.pid")
    proc, pid = _short_lived(0.2)
    proc.wait()
    time.sleep(0.1)
    assert process.is_alive(pid) is False


def test_is_alive_bogus_pid():
    assert process.is_alive(0) is False
    assert process.is_alive(-1) is False
    assert process.is_alive(999999999) is False


def test_stop_no_running_process(monkeypatch, tmp_path, capsys):
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    assert process.stop(grace_seconds=0.1) is True
    assert "未发现运行中的 Stella" in capsys.readouterr().out
    assert process.read_pid() is None


def test_stop_kills_live_process(monkeypatch, tmp_path):
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    proc, pid = _short_lived(30.0)
    process.write_pid(pid)
    try:
        assert process.stop(grace_seconds=0.1) is True
        proc.wait(timeout=5)
        assert process.read_pid() is None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_status_dict_shape(monkeypatch, tmp_path):
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    monkeypatch.setattr(process, "LOG_FILE", tmp_path / "stella.jsonl")
    data = process.status()
    assert set(data) == {"pid", "alive", "log_file", "recent_log", "note"}
    assert data["pid"] is None
    assert data["alive"] is False
    assert data["recent_log"] is None
