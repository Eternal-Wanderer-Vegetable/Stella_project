# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""core/self_restart 的单元测试：无壳自重启的派生守卫与父进程等待。

接任等待机制跨平台（Windows 上 ``os.kill(pid, 0)`` 是 TerminateProcess，
必须走 OpenProcess 只读探测），所以用真实子进程验证存活判断，而不是 mock。
"""

from __future__ import annotations

import subprocess
import sys
import time

from core import self_restart


def test_wait_returns_false_without_env(monkeypatch):
    monkeypatch.delenv(self_restart.PARENT_PID_ENV, raising=False)
    assert self_restart.wait_for_parent_exit() is False


def test_wait_consumes_env_even_when_pid_invalid(monkeypatch):
    """非法 PID 也要把环境变量消费掉：不能传染给接任进程再派生的子进程。"""
    monkeypatch.setenv(self_restart.PARENT_PID_ENV, "not-a-pid")
    assert self_restart.wait_for_parent_exit() is False
    import os

    assert self_restart.PARENT_PID_ENV not in os.environ


def test_wait_detects_dead_parent(monkeypatch):
    """真实子进程被终止后，等待必须立刻放行（而不是傻等满超时）。"""
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert self_restart._pid_alive(sleeper.pid), "前置：子进程应存活"
        sleeper.terminate()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and self_restart._pid_alive(sleeper.pid):
            time.sleep(0.05)
        assert not self_restart._pid_alive(sleeper.pid), "前置：子进程应已退出"

        monkeypatch.setenv(self_restart.PARENT_PID_ENV, str(sleeper.pid))
        started = time.monotonic()
        assert self_restart.wait_for_parent_exit(timeout=5.0) is True
        assert time.monotonic() - started < 4.5, "父已死应立即放行，不该等满超时"
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait(timeout=5)


def test_wait_times_out_while_parent_alive(monkeypatch):
    """父还活着时限时应放行（返回 False）：启动宁可撞端口报错，不可无声卡死。"""
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        monkeypatch.setenv(self_restart.PARENT_PID_ENV, str(sleeper.pid))
        started = time.monotonic()
        assert self_restart.wait_for_parent_exit(timeout=1.0) is False
        assert 0.9 <= time.monotonic() - started < 5.0
    finally:
        sleeper.kill()
        sleeper.wait(timeout=5)


def test_spawn_successor_refuses_non_bot_entry():
    """pytest（及其他宿主）不是 bot.py 入口：必须拒绝派生并如实说明，
    绝不能在测试或第三方宿主里凭空拉起一个真 Bot。"""
    result = self_restart.spawn_successor()
    assert result["spawned"] is False
    assert "bot.py" in (result.get("error") or "")
    assert result.get("pid") is None
