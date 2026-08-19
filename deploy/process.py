# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""deploy 的进程管理：``start --detach`` / ``status`` / ``stop``。

跨平台说明（Windows 没有 SIGTERM）：
- ``start --detach`` 用 ``CREATE_NEW_PROCESS_GROUP`` 启动，写成独立进程组，
  这样 ``stop`` 才能把 ``CTRL_BREAK_EVENT`` 只发给它而不波及启动器；
- ``stop`` 用 ``os.kill(pid, CTRL_BREAK_EVENT)``。uvicorn 0.52+ 在 Windows 上
  注册了 SIGBREAK 处理器（``HANDLED_SIGNALS`` 含 ``SIGBREAK``），收到后走
  优雅关闭并触发 NoneBot 的 ``on_shutdown`` 钩子——因此这个信号方案能拿到
  优雅停止。POSIX 下用 ``SIGTERM``，同样走优雅关闭。

注意：``os.kill(pid, 0)`` 在 Windows 上会调用 TerminateProcess 把进程杀掉，
不能用来探活。这里用 ``OpenProcess + GetExitCodeProcess`` 判断存活。
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

from config import PROJECT_ROOT, SHUTDOWN_GRACE_SECONDS

PID_FILE = PROJECT_ROOT / "logs" / "stella.pid"
BOT_ENTRY = PROJECT_ROOT / "bot.py"
LOG_FILE = PROJECT_ROOT / "logs" / "stella.jsonl"


def read_pid() -> int | None:
    """读取 PID 文件；不存在或内容非法返回 None。"""
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid(pid: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    with contextlib.suppress(OSError):
        PID_FILE.unlink()


def is_alive(pid: int) -> bool:
    """进程存活判断。

    POSIX 用 ``os.kill(pid, 0)``；Windows 上该调用会 TerminateProcess，改用
    ``OpenProcess + GetExitCodeProcess``（返回码 259 = STILL_ACTIVE）。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # 僵尸进程（已退出但父进程未 wait）在进程表里仍存在，os.kill(pid, 0) 会成功。
    # 生产中 Bot 不是 deploy stop 的子进程、由 init 回收，因此不会出现；
    # 但父子关系下（如 GUI 直接 spawn Bot）需要区分，否则会把已死进程当成活的。
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """读 /proc/{pid}/stat 判断是否为僵尸态（Z）。非 Linux 或读取失败按「非僵尸」处理。"""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return _stat_is_zombie(stat)
    except (OSError, ValueError, IndexError):
        return False


def _stat_is_zombie(stat: str) -> bool:
    """从 /proc/{pid}/stat 原始文本判断状态是否为 Z（僵尸）。

    格式：pid (comm) state ...；comm 可能含空格与括号，因此从最后一个 ')'
    之后取状态字符，而不是按空格 split。
    """
    return stat[stat.rindex(")") + 2] == "Z"


def _windows_is_alive(pid: int) -> bool:
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


def start_detached() -> int:
    """后台启动 bot.py 并写 PID 文件，立即返回。"""
    if not BOT_ENTRY.exists():
        print(f"缺少入口 {BOT_ENTRY}，无法启动。")
        return 1
    flags = 0
    if os.name == "nt":
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [sys.executable, str(BOT_ENTRY)],
        cwd=str(PROJECT_ROOT),
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    write_pid(proc.pid)
    print(f"后台启动 Stella（PID {proc.pid}），PID 已写入 {PID_FILE}")
    return 0


def stop(grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> bool:
    """优雅停止：发信号 → 等 ``grace+5s`` → 仍存活则强杀。

    返回 True 表示进程已退出（或本来就没在跑）。
    """
    pid = read_pid()
    if pid is None or not is_alive(pid):
        print("未发现运行中的 Stella 进程。")
        clear_pid()
        return True
    print(f"发送停止信号给 PID {pid}...")
    try:
        if os.name == "nt":
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError) as e:
        print(f"发送信号失败: {e}，等待后强杀。")
    deadline = time.monotonic() + grace_seconds + 5.0
    while time.monotonic() < deadline:
        if not is_alive(pid):
            print("Stella 已优雅退出。")
            clear_pid()
            return True
        time.sleep(0.5)
    print("等待超时，强制终止...")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    time.sleep(1.0)
    if is_alive(pid):
        print("强杀后进程仍存活，请手动检查。")
        return False
    print("Stella 已被强制终止。")
    clear_pid()
    return True


def _fetch_live_status(timeout: float = 1.0) -> dict | None:
    """查询 Bot 进程内的状态接口；不可达返回 None。

    HOST/PORT 从 .env 读（dotenv_values 而非 os.getenv——避免受当前进程
    环境变量干扰，与 probe 的做法一致）。HOST 为 0.0.0.0 / :: 时改连
    127.0.0.1：那是「监听所有地址」的写法，不是可连接的目标地址。

    超时取 1 秒：status 是交互命令（GUI 每 1.5 秒轮询一次），
    宁可少一块信息也不能卡住。
    """
    env = dotenv_values(PROJECT_ROOT / ".env")
    host = (env.get("HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = (env.get("PORT") or "8080").strip() or "8080"
    path = (env.get("STELLA_STATUS_API_PATH") or "/stella/status").strip()
    if not path:
        path = "/stella/status"
    if host in ("0.0.0.0", "::", "::0"):
        host = "127.0.0.1"
    url = f"http://{host}:{port}{path}"
    try:
        resp = httpx.get(url, timeout=timeout, trust_env=False)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def status() -> dict:
    """返回状态字典（供 ``status [--json]``）。

    存活判据有两个来源，优先级明确：
    1. **状态接口可达** —— 最强证据，说明进程活着且 HTTP 服务已就绪；
    2. PID 文件 + 进程存活 —— 仅在接口不可达时兜底（进程刚启动、HTTP 还没起来，
       或用户关掉了 STELLA_STATUS_API_ENABLED）。

    为什么不能只看 PID 文件：它只由 ``deploy start --detach`` 写入。用
    ``python bot.py`` 或 ``deploy start``（前台）启动时没有 PID 文件，
    但进程明明在跑——2026-08-19 实测出现「api_reachable=true 却报未在运行」。
    """
    pid = read_pid()
    pid_alive = pid is not None and is_alive(pid)
    live = _fetch_live_status()

    # 接口可达即视为运行中；它同时能补上 PID（进程自己报的，比文件可靠）
    alive = live is not None or pid_alive
    if live is not None and live.get("pid"):
        pid = live["pid"]

    recent: dict | None = None
    try:
        if LOG_FILE.exists():
            lines = [
                ln
                for ln in LOG_FILE.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            if lines:
                recent = json.loads(lines[-1])
    except Exception:
        recent = None
    return {
        "pid": pid,
        "alive": alive,
        "pid_file_present": pid_alive,   # GUI 据此判断进程是否由 deploy stop 管得了
        "api_reachable": live is not None,
        "log_file": str(LOG_FILE),
        "recent_log": recent,
        # 以下来自进程内状态接口；接口不可达时为 None
        "link": (live or {}).get("link"),
        "scheduler": (live or {}).get("scheduler"),
        "uptime_seconds": (live or {}).get("uptime_seconds"),
        "note": "link/scheduler 来自 Bot 进程内的状态接口，接口不可达时为 null",
    }
