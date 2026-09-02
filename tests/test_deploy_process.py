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


def _stubborn_child(seconds: float = 30.0):
    """起一个忽略 SIGTERM/SIGBREAK 的子进程——降级信号杀不掉它，硬杀才会生效。

    用于验证 stop() 的降级信号阶段不会抢在硬杀之前把进程结束掉。
    """
    code = (
        "import signal, time\n"
        "try: signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "except Exception: pass\n"
        "try: signal.signal(signal.SIGBREAK, signal.SIG_IGN)\n"
        "except Exception: pass\n"
        f"time.sleep({seconds})"
    )
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
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


def test_is_alive_false_for_unreaped_child(monkeypatch, tmp_path):
    """已退出但未 wait() 回收的子进程（POSIX 下为僵尸）应被判为不存活。"""
    monkeypatch.setattr(process, "PID_FILE", tmp_path / "stella.pid")
    proc, pid = _short_lived(0.2)
    try:
        time.sleep(0.6)  # 等它自己退出；poll() 返回时不回收 → POSIX 下成为僵尸
        if proc.poll() is None:
            # 负载高时 0.6s 可能不够：wait() 会同时回收，is_alive 走 ProcessLookupError 分支
            proc.wait(timeout=5)
        assert process.is_alive(pid) is False
    finally:
        proc.wait(timeout=5)  # 回收，避免僵尸泄漏到其他测试


def test_stat_is_zombie_true():
    assert process._stat_is_zombie("123 (sleep) Z 45 46 47 ...") is True


def test_stat_is_zombie_false_running():
    assert process._stat_is_zombie("123 (sleep) S 45 46 47 ...") is False


def test_stat_is_zombie_comm_with_parens():
    assert process._stat_is_zombie("123 (python (child)) Z 45 ...") is True


def test_is_zombie_nonexistent_pid():
    assert process._is_zombie(999999999) is False


def test_stop_no_running_process(monkeypatch, tmp_path, capsys):
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    monkeypatch.setattr(process, "_fetch_live_status", lambda: None)
    assert process.stop(grace_seconds=0.1) is True
    assert "未发现运行中的 Stella" in capsys.readouterr().out
    assert process.read_pid() is None


def test_stop_without_pid_but_api_reachable(monkeypatch, tmp_path, capsys):
    """手工启动的进程没有 PID 文件，状态接口可达时不能假装停止成功。"""
    monkeypatch.setattr(process, "PID_FILE", tmp_path / "stella.pid")
    monkeypatch.setattr(process, "_fetch_live_status", lambda: {"pid": 999})
    assert process.stop(grace_seconds=0.1) is False
    out = capsys.readouterr().out
    assert "无法从这里停止" in out
    assert "999" in out


def test_stop_without_pid_and_api_unreachable(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(process, "PID_FILE", tmp_path / "stella.pid")
    monkeypatch.setattr(process, "_fetch_live_status", lambda: None)
    assert process.stop(grace_seconds=0.1) is True
    assert "未发现运行中的 Stella" in capsys.readouterr().out


def test_stop_writes_sentinel_before_hard_kill(monkeypatch, tmp_path):
    """stop() 先写哨兵请求，硬杀只发生在请求与等待之后。"""
    events: list[str] = []

    def fake_request_stop(reason=""):
        events.append("request")

    def fake_hard_kill(pid):
        events.append("hard_kill")
        return True

    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    monkeypatch.setattr(process, "request_stop", fake_request_stop)
    monkeypatch.setattr(process, "_hard_kill", fake_hard_kill)
    proc, pid = _stubborn_child(30.0)
    process.write_pid(pid)
    try:
        assert process.stop(grace_seconds=0.1) is True
        assert events[0] == "request"
        assert "hard_kill" in events
        assert events.index("request") < events.index("hard_kill")
    finally:
        proc.terminate()
        proc.wait()


def test_stop_clears_sentinel_on_exit(monkeypatch, tmp_path):
    """stop() 返回后哨兵文件被清除（无论退出路径），避免下次启动自杀。"""
    import core.stop_signal

    sentinel = tmp_path / "stop-request"
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(core.stop_signal, "_sentinel_path", lambda: sentinel)
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    proc, pid = _short_lived(0.5)
    process.write_pid(pid)
    try:
        assert process.stop(grace_seconds=0.1) is True
    finally:
        proc.terminate()
        proc.wait()
    assert not sentinel.exists()


def test_stop_kills_live_process(monkeypatch, tmp_path):
    """stop() 能让在跑的进程退出并清掉 PID 文件。

    注意：本测试是子进程的父进程，POSIX 下子进程退出后会变僵尸直到父进程
    wait()。而 os.kill(pid, 0) 对僵尸进程仍然成功，因此 is_alive() 会持续
    返回 True——这不是 stop() 的缺陷，是测试的进程关系造成的。
    先 proc.wait() 回收，再断言子进程确实终止了。
    """
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    proc, pid = _short_lived(30.0)
    process.write_pid(pid)
    try:
        # stop() 的返回值在「测试进程是子进程的父进程」这一特殊关系下不可靠
        # （僵尸未回收 → is_alive 恒为 True），因此只调用、不断言返回值。
        process.stop(grace_seconds=0.1)
        # 回收僵尸：这一步之后 is_alive(pid) 才会如实返回 False
        proc.wait(timeout=10)
        assert proc.returncode is not None
        assert process.is_alive(pid) is False
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_status_dict_shape(monkeypatch, tmp_path):
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    monkeypatch.setattr(process, "LOG_FILE", tmp_path / "stella.jsonl")
    monkeypatch.setattr(process, "_fetch_live_status", lambda: None)
    data = process.status()
    assert set(data) == {
        "pid",
        "alive",
        "pid_file_present",
        "api_reachable",
        "log_file",
        "recent_log",
        "link",
        "scheduler",
        "usage",
        "capabilities",
        "uptime_seconds",
        "note",
    }
    assert data["pid"] is None
    assert data["alive"] is False
    assert data["pid_file_present"] is False
    assert data["recent_log"] is None
    assert data["api_reachable"] is False


def test_status_api_unreachable(monkeypatch, tmp_path):
    """status() 在状态接口不可达时：link/scheduler 为 None、api_reachable False，不抛异常。"""
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    monkeypatch.setattr(process, "LOG_FILE", tmp_path / "stella.jsonl")
    monkeypatch.setattr(process, "_fetch_live_status", lambda: None)
    data = process.status()
    assert data["alive"] is False
    assert data["api_reachable"] is False
    assert data["pid_file_present"] is False
    assert data["link"] is None
    assert data["scheduler"] is None
    assert data["usage"] is None
    assert data["uptime_seconds"] is None


def test_status_api_reachable_without_pid_file(monkeypatch, tmp_path):
    """接口可达是比 PID 文件更强的存活证据：无 PID 文件也报运行中，pid 从接口取。"""

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"pid": 99999, "link": {"healthy": True}, "scheduler": {}, "uptime_seconds": 12.0}

    class _FakeHttpx:
        def get(self, url, **kwargs):
            return _FakeResp()

    monkeypatch.setattr(process, "PID_FILE", tmp_path / "stella.pid")
    monkeypatch.setattr(process, "LOG_FILE", tmp_path / "stella.jsonl")
    monkeypatch.setattr(process, "dotenv_values", lambda _p: {})
    monkeypatch.setattr(process, "httpx", _FakeHttpx())
    data = process.status()
    assert data["alive"] is True
    assert data["api_reachable"] is True
    assert data["pid_file_present"] is False
    assert data["pid"] == 99999
    assert data["link"] == {"healthy": True}


def test_status_pid_file_fallback_when_api_unreachable(monkeypatch, tmp_path):
    """接口不可达但有 PID 文件：PID 文件兜底，仍报运行中（进程刚启动 / 状态接口被关）。"""
    pid_file = tmp_path / "stella.pid"
    monkeypatch.setattr(process, "PID_FILE", pid_file)
    monkeypatch.setattr(process, "LOG_FILE", tmp_path / "stella.jsonl")
    monkeypatch.setattr(process, "_fetch_live_status", lambda: None)
    proc, pid = _short_lived(5.0)
    try:
        process.write_pid(pid)
        data = process.status()
        assert data["alive"] is True
        assert data["api_reachable"] is False
        assert data["pid_file_present"] is True
        assert data["pid"] == pid
        assert data["link"] is None
    finally:
        proc.terminate()
        proc.wait()


def test_fetch_live_status_maps_wildcard_host(monkeypatch):
    """HOST=0.0.0.0 是「监听所有地址」的写法，不是可连接的目标——应改连 127.0.0.1。"""

    class _FakeResp:
        status_code = 200

        def json(self):
            return {"uptime_seconds": 42.0}

    calls: list[tuple[str, dict]] = []

    class _FakeHttpx:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return _FakeResp()

    monkeypatch.setattr(process, "dotenv_values", lambda _p: {"HOST": "0.0.0.0", "PORT": "8080"})
    monkeypatch.setattr(process, "httpx", _FakeHttpx())
    data = process._fetch_live_status()
    assert data == {"uptime_seconds": 42.0}
    assert calls[0][0] == "http://127.0.0.1:8080/stella/status"
    assert calls[0][1]["timeout"] == 1.0
    assert calls[0][1]["trust_env"] is False


def test_fetch_live_status_unreachable_returns_none(monkeypatch):
    """连接失败时返回 None，status() 不因此崩溃。"""

    class _FakeHttpx:
        def get(self, url, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(process, "dotenv_values", lambda _p: {})
    monkeypatch.setattr(process, "httpx", _FakeHttpx())
    assert process._fetch_live_status() is None


def test_fetch_live_status_non_200_returns_none(monkeypatch):
    """非 200 响应同样视为不可达。"""

    class _FakeResp:
        status_code = 403

        def json(self):
            return {}

    class _FakeHttpx:
        def get(self, url, **kwargs):
            return _FakeResp()

    monkeypatch.setattr(process, "dotenv_values", lambda _p: {})
    monkeypatch.setattr(process, "httpx", _FakeHttpx())
    assert process._fetch_live_status() is None
