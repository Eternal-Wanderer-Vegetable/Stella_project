# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""无壳形态的 Bot 自重启（WebUI「重启」按钮的兜底监管）。

背景：``webui/services/system.restart`` 写停止哨兵后，Bot 的 watcher 优雅
退出——但谁来拉起新进程取决于形态：桌面壳监听退出自动重启；无壳形态
（终端直启 ``python bot.py``、浏览器访问 WebUI）过去只能提示用户手动重启，
用户点完重启就是 ``ERR_CONNECTION_REFUSED``（2026-09-24 实测）。

本模块补上缺失的一环：**退出前派生接任进程**。

- 派生侧 [`spawn_successor`]：以同样的解释器 + bot.py 入口起一个分离进程，
  环境变量 ``STELLA_RESTART_PARENT_PID`` 指向当前进程。
- 接任侧 [`wait_for_parent_exit`]：bot.py 启动极早期调用——上一任还占着
  服务端口，必须等它真正退出（优雅关闭最长 grace+缓冲）再继续初始化，
  否则端口绑定直接失败。超时后照样继续：绑定失败会留下明确错误，好过
  永远干等。

只服务 ``python bot.py`` 直启形态：入口不是 bot.py（测试、uvicorn 托管、
未来其他宿主）时拒绝派生并如实返回原因，绝不猜。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PARENT_PID_ENV = "STELLA_RESTART_PARENT_PID"
# 上一任的优雅关闭预算：SHUTDOWN_GRACE_SECONDS(30) + 收尾缓冲 + uvicorn
# 在途连接 5s + 余量。超时后照样继续启动——端口冲突会给出明确报错。
_PARENT_EXIT_TIMEOUT = 90.0
_POLL_INTERVAL = 0.2


def bot_entry() -> Path:
    from config import PROJECT_ROOT

    return PROJECT_ROOT / "bot.py"


def _running_as_bot_entry() -> bool:
    """当前进程是否由 ``python bot.py`` 直接启动（判定依据：入口脚本路径）。"""
    try:
        return Path(sys.argv[0]).resolve() == bot_entry().resolve()
    except (OSError, ValueError):
        return False


def spawn_successor() -> dict:
    """派生接任 Bot 进程。返回 ``{spawned, pid?, error?, entry}`` 供接口如实回报。"""
    info: dict = {"spawned": False, "entry": "bot.py"}
    if not _running_as_bot_entry():
        info["error"] = (
            f"当前入口不是 bot.py（{sys.argv[0]}），无法自动派生接任进程，请手动重启"
        )
        return info
    try:
        child_env = os.environ.copy()
        child_env[PARENT_PID_ENV] = str(os.getpid())
        child_env.pop("STELLA_LAUNCH_TOKEN", None)
        flags = 0
        if os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP：与 deploy start --detach 同款，脱离
            # 当前控制台组；CREATE_NO_WINDOW 抑制黑框（GUI 场景无控制台可闪）。
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
            flags |= 0x0800_0000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            [sys.executable, str(bot_entry())],
            cwd=str(bot_entry().parent),
            env=child_env,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        info["spawned"] = True
        info["pid"] = proc.pid
    except OSError as e:
        info["error"] = f"派生接任进程失败：{e}"
    return info


def _pid_alive(pid: int) -> bool:
    """进程存活探测。Windows 上 ``os.kill(pid, 0)`` 会 TerminateProcess（见
    deploy/process.py 的注释），这里用只读的 OpenProcess + 退出码判断。

    POSIX 上 ``os.kill(pid, 0)`` 对**僵尸进程**（已退出、未被父进程 wait）
    依然成功——而 CI/终端里 terminate 子进程后它恰恰就是僵尸。必须读
    /proc 的状态位把僵尸判成已死，否则等待循环永远放不了行
    （2026-09-25 Linux CI 实测）。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        query_limited_info = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(query_limited_info, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    try:
        # /proc/{pid}/stat 格式为 `pid (comm) state ...`；comm 可能含空格与
        # 括号，从最后一个 ')' 之后取状态字符（与 deploy.process 同一口径）。
        stat_text = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        if stat_text.rpartition(")")[2].lstrip()[:1] == "Z":
            return False
    except (OSError, ValueError):
        pass
    return True


def wait_for_parent_exit(
    timeout: float = _PARENT_EXIT_TIMEOUT, interval: float = _POLL_INTERVAL
) -> bool:
    """若本进程是接任进程，等上一任退出（最多 timeout 秒）再返回。

    返回 True = 确认上一任已退出；False = 不是接任进程（环境变量不存在，
    读取后立即清除，避免再派生时传染）或等待超时。超时继续启动是刻意的：
    端口冲突会留下明确错误，而卡死在这里只会让站点无声失踪。
    """
    raw = os.environ.pop(PARENT_PID_ENV, "").strip()
    if not raw:
        return False
    try:
        parent = int(raw)
    except ValueError:
        return False
    if parent == os.getpid() or not _pid_alive(parent):
        return True
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(parent):
            return True
        time.sleep(interval)
    return False
