# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""deploy 的进程管理：``start --detach`` / ``status`` / ``stop``。

停止链路（哨兵优先，信号降级，硬杀兜底）：
- ``stop`` 第一阶写停止哨兵文件，Bot 进程内的 watcher 观察到后自行走完整
  优雅关闭（含 on_shutdown → _graceful_shutdown 的整合收尾）。这绕开了
  「GUI 用 CREATE_NO_WINDOW 启动、子进程没有控制台、控制台信号永远送不到」
  的问题——文件不依赖控制台，Windows 与 POSIX 行为一致。
- 超时后降级发 ``CTRL_BREAK_EVENT``（Windows）/ ``SIGTERM``（POSIX）：
  手动 ``--detach`` 启动（有控制台）时有效；GUI 场景大概无效，但保留。
- 仍不退出则硬杀（Windows ``taskkill /F /T``，POSIX ``SIGKILL``）。

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

from config import (
    INSTANCE_ID,
    INSTANCE_MANIFEST_PATH,
    INSTANCE_PID_FILE,
    PROJECT_ROOT,
    SHUTDOWN_GRACE_SECONDS,
    STELLA_HOME,
    STELLA_JSON_LOG_PATH,
    STELLA_STATUS_API_ENABLED,
)
from config.instance import (
    LAUNCH_TOKEN_ENV,
    launch_token_digest,
    manifest_for,
    new_launch_token,
    read_manifest,
    write_manifest,
)
from core.stop_signal import clear_stop_request, request_stop

from . import runtime

PID_FILE = INSTANCE_PID_FILE
MANIFEST_FILE = INSTANCE_MANIFEST_PATH
BOT_ENTRY = PROJECT_ROOT / "bot.py"
# 必须读配置而不是自己拼 logs/stella.jsonl：Bot 侧的 sink 由 STELLA_JSON_LOG_PATH
# 决定，两边各拼一份的话，用户一改配置 `deploy status` 就开始读一个空文件
# （而它只会显示「暂无日志」，不会报错）。
LOG_FILE = STELLA_JSON_LOG_PATH

# 停止等待缓冲：必须严格大于 Bot 侧 SHUTDOWN_GRACE_SECONDS 里真正在跑的时间。
# 与 grace 成比例而非固定值——grace 很小（测试/快速关闭）时不该白白多等，
# grace=30 时缓冲也够足。它和旧的「信号后 +5 死等」不是一回事：哨兵保证会被
# watcher 观察到，缓冲只花在真有在途任务收尾的场景。
STOP_WAIT_BUFFER_SECONDS = 5.0
# 降级信号发出后再等多久（秒）
_STAGE_SIGNAL_WAIT_SECONDS = 3.0
# 轮询间隔（秒）
_POLL_INTERVAL = 0.3
# 后台启动不能只以 Popen 成功为成功：uvicorn 可能随后因端口冲突或导入错误退出。
STARTUP_TIMEOUT_SECONDS = 15.0
STARTUP_POLL_INTERVAL = 0.3


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


def clear_manifest() -> None:
    with contextlib.suppress(OSError):
        MANIFEST_FILE.unlink()


def _owned_manifest(pid: int | None = None) -> dict | None:
    manifest = read_manifest(MANIFEST_FILE)
    if not manifest or manifest.get("instance_id") != INSTANCE_ID:
        return None
    if manifest.get("project_root") != str(PROJECT_ROOT.resolve()):
        return None
    if pid is not None and manifest.get("pid") != pid:
        return None
    if not isinstance(manifest.get("launch_token"), str) or not manifest["launch_token"]:
        return None
    return manifest


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


def _service_port_in_use() -> bool:
    """探测 .env 里 HOST:PORT 是否有进程在监听（TCP 连得上 = 有）。"""
    import socket

    env = dotenv_values(STELLA_HOME / ".env")
    host = (env.get("HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port = int((env.get("PORT") or "8080").strip() or 8080)
    if host in ("0.0.0.0", "::", "::0"):
        host = "127.0.0.1"
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def start_detached() -> int:
    """后台启动 bot.py，写 PID 文件并等待当前实例真正就绪。

    已有本安装实例在跑时执行**重启语义**：先优雅停掉旧实例再启动（2026-09-24
    用户要求）——否则新实例绑定端口失败、旧实例继续占位，两头不是。停止链
    只认身份（状态接口自报 / manifest+端口），PID 文件在就绪后由本函数为新
    进程重写，ownership 随之转移到新进程。
    """
    if not BOT_ENTRY.exists():
        print(f"缺少入口 {BOT_ENTRY}，无法启动。")
        return 1
    replace_running()  # 内部自带「发现实例」提示与停止链

    existing = read_pid()
    if existing is not None and is_alive(existing):
        # 走到这里说明 PID 文件还指着一个活进程但身份未获证明——典型是 PID
        # 复用撞号（2026-09-24 实测：QQ 的 crashpad_handler 撞号，deploy
        # start 从此永远拒启）。真正的 Stella 必然占着服务端口：端口没人听
        # 就是陈旧记录，清掉照常启动；端口被占则归属不明，宁拒不误杀。
        if _service_port_in_use():
            print(
                f"服务端口已被 PID {existing} 占用，但无法确认它是本安装的 Stella"
                "（状态接口无匹配）——为避免误伤其他程序，不会自动结束它。"
            )
            print("请用任务管理器处理该进程，或在 .env 改用其他 PORT。")
            return 1
        print(
            f"PID 文件指向 {existing}，但服务端口无人监听——该 PID 已被系统复用给"
            "其他进程，清除陈旧记录后继续启动。"
        )
        clear_pid()
        clear_manifest()
    flags = 0
    if os.name == "nt":
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    launch_token = new_launch_token()
    child_env = os.environ.copy()
    child_env[LAUNCH_TOKEN_ENV] = launch_token
    child_env["STELLA_INSTANCE_ID"] = INSTANCE_ID
    proc = subprocess.Popen(
        [sys.executable, str(BOT_ENTRY)],
        cwd=str(PROJECT_ROOT),
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=child_env,
    )
    try:
        write_pid(proc.pid)
        write_manifest(
            MANIFEST_FILE,
            manifest_for(
                instance_id=INSTANCE_ID,
                project_root=PROJECT_ROOT,
                pid=proc.pid,
                launch_token=launch_token,
            ),
        )
        runtime.update_component(
            "stella",
            "starting",
            pid=proc.pid,
            desired="running",
        )
    except OSError as e:
        with contextlib.suppress(Exception):
            proc.terminate()
        clear_pid()
        clear_manifest()
        runtime.update_component("stella", "failed", error=str(e), desired="running")
        print(f"无法记录 Stella 实例 ownership：{e}")
        return 1
    print(
        f"后台启动 Stella（PID {proc.pid}），实例 {INSTANCE_ID} 的 PID 已写入 {PID_FILE}"
    )
    ready, detail = wait_for_startup(proc.pid)
    if ready:
        print(f"Stella 已就绪（PID {proc.pid}）。")
        return 0

    _cleanup_failed_start(proc)
    clear_pid()
    clear_manifest()
    runtime.update_component(
        "stella",
        "failed",
        error=detail,
        desired="running",
    )
    print(detail)
    return 1


def _cleanup_failed_start(proc: subprocess.Popen) -> None:
    """回收启动探测失败后仍存活的 Bot，避免残留进程占用服务端口。"""
    if proc.poll() is not None and not is_alive(proc.pid):
        return

    with contextlib.suppress(OSError):
        proc.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        proc.wait(timeout=2.0)

    if is_alive(proc.pid):
        _hard_kill(proc.pid)


def wait_for_startup(
    pid: int,
    *,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
    poll_interval: float = STARTUP_POLL_INTERVAL,
) -> tuple[bool, str]:
    """等待指定实例的状态接口就绪，或报告可操作的启动失败原因。

    ``_fetch_live_status`` 同时校验 instance_id 与 launch token，因此响应来自
    另一份 Stella 安装时不会被误认为当前实例已经启动。状态接口被显式关闭时，
    存活的子进程仍可视为就绪，保持旧配置的兼容性。
    """
    if timeout < 0:
        raise ValueError("启动等待 timeout 不能为负数")
    if poll_interval <= 0:
        raise ValueError("启动等待 poll_interval 必须大于 0")

    if not STELLA_STATUS_API_ENABLED:
        return (True, "") if is_alive(pid) else (
            False,
            f"Stella 子进程在启动期间退出（PID {pid}）。",
        )

    deadline = time.monotonic() + timeout
    while True:
        if not is_alive(pid):
            return False, f"Stella 子进程在启动期间退出（PID {pid}）。"

        live = _fetch_live_status(timeout=min(1.0, poll_interval))
        if live is not None and live.get("pid") == pid:
            return True, ""

        if time.monotonic() >= deadline:
            return (
                False,
                f"Stella 启动超时（PID {pid}）：状态接口未在 "
                f"{timeout:.0f} 秒内就绪。请运行 deploy doctor 检查端口和依赖。",
            )
        time.sleep(poll_interval)


def _graceful_stop_pid(pid: int, grace_seconds: float, reason: str) -> bool:
    """对已确认属于本安装的 PID 执行完整停止链，成功则清 PID/manifest。

    停止链（哨兵优先，信号降级，硬杀兜底）：
    - 第 1 阶写停止哨兵文件，Bot 进程内的 watcher 观察到后自行走完整优雅
      关闭（含 on_shutdown → _graceful_shutdown 的整合收尾）。这绕开了
      「GUI 用 CREATE_NO_WINDOW 启动、子进程没有控制台、控制台信号永远
      送不到」的问题——文件不依赖控制台，Windows 与 POSIX 行为一致。
    - 第 2 阶轮询等待 ``grace + 缓冲``；第 3 阶降级发 CTRL_BREAK/SIGTERM
      （GUI 场景大概无效，但手动 --detach 启动时有效）；第 4 阶硬杀兜底。

    调用方负责先确认身份（manifest 或状态接口），本函数不做归属判断。
    """
    # 缓冲与 grace 成比例：grace 很小（测试）时不该白白多等，grace=30 时给足 5 秒
    buffer = min(STOP_WAIT_BUFFER_SECONDS, grace_seconds * 0.2)
    try:
        # 第 1 阶：写哨兵，请 Bot 自己走完整优雅关闭
        request_stop(reason=reason)
        print(f"已发出停止请求给 PID {pid}，等待在途任务收尾…")

        # 第 2 阶：轮询等待 Bot 收到哨兵后自行退出
        deadline = time.monotonic() + grace_seconds + buffer
        started = time.monotonic()
        last_report = started
        while time.monotonic() < deadline:
            if not is_alive(pid):
                print("Stella 已优雅退出。")
                clear_pid()
                clear_manifest()
                return True
            now = time.monotonic()
            if now - last_report >= 5.0:
                print(f"仍在等待（已等 {now - started:.0f}s）…")
                last_report = now
            time.sleep(_POLL_INTERVAL)

        # 第 3 阶：降级信号（GUI 场景大概无效，但手动 --detach 启动时有效）
        print("等待超时，发送降级信号…")
        try:
            if os.name == "nt":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError) as e:
            print(f"发送信号失败: {e}")
        signal_deadline = time.monotonic() + _STAGE_SIGNAL_WAIT_SECONDS
        while time.monotonic() < signal_deadline:
            if not is_alive(pid):
                print("Stella 已优雅退出。")
                clear_pid()
                clear_manifest()
                return True
            time.sleep(_POLL_INTERVAL)

        # 第 4 阶：硬杀。此刻在途整合大概率被中断——这是用户了解数据可能
        # 不一致的唯一渠道，必须明确告警。
        print("警告：进程未在限时内退出，正在强制终止——在途整合可能未完成。")
        if not _hard_kill(pid):
            print("强杀后进程仍存活，请手动检查。")
            return False
        print("Stella 已被强制终止。")
        clear_pid()
        clear_manifest()
        return True
    finally:
        # 无论哪条路径退出都不留哨兵，避免下次启动自杀
        clear_stop_request()


def stop(grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> bool:
    """优雅停止：写哨兵 → 轮询收尾 → 降级信号 → 硬杀。

    返回 True 表示进程已退出（或本来就没在跑）。

    停止链见 `_graceful_stop_pid`。没有 PID 文件时会查询状态接口：若接口
    可达，说明 Bot 确实在运行但不是 ``deploy start --detach`` 启动的，本
    函数无法定位并停止它，返回 False（自动接管场景请走 `replace_running`，
    它认状态接口的身份证明）。
    """
    pid = read_pid()
    if pid is None or not is_alive(pid):
        live = _fetch_live_status()
        if live is not None:
            print("检测到 Stella 正在运行，但没有 PID 文件——它不是用")
            print("  python -m deploy start --detach 启动的，因此无法从这里停止。")
            print(f"  进程 PID（由状态接口自报）：{live.get('pid', '?')}")
            print("  请在启动它的终端按 Ctrl+C，或用任务管理器结束该 PID。")
            return False
        print("未发现运行中的 Stella 进程。")
        clear_pid()
        clear_manifest()
        return True

    manifest = _owned_manifest(pid)
    if manifest is None:
        print(
            f"拒绝停止 PID {pid}：它不属于当前 Stella 实例（{INSTANCE_ID}）。"
        )
        print("未写入停止哨兵，也未发送信号；请使用启动该进程的实例执行停止。")
        return False

    return _graceful_stop_pid(pid, grace_seconds, reason="deploy stop")


def _identify_running() -> int | None:
    """找出本安装正在运行的实例 PID；没有返回 None。

    身份判据从严——只认「能证明自己是谁」的进程，绝凭一个裸 PID 号动手
    （Windows 会复用 PID 号，2026-09-24 实测撞上 QQ 的 crashpad）：

    1. 状态接口自报 instance_id 匹配（含 manifest launch_token 校验）——
       ``python bot.py`` 直启也满足，这是最强的身份证明；
    2. 状态接口被显式关闭时的兜底：PID 文件 + manifest 匹配 + 服务端口
       确实在听。端口在听排除 PID 复用撞号——撞上来的无关进程不会碰
       我们的服务端口。
    """
    live = _fetch_live_status()
    if live is not None and live.get("pid"):
        return int(live["pid"])
    if not STELLA_STATUS_API_ENABLED:
        pid = read_pid()
        if (
            pid is not None
            and is_alive(pid)
            and _owned_manifest(pid) is not None
            and _service_port_in_use()
        ):
            return pid
    return None


def replace_running(grace_seconds: float = SHUTDOWN_GRACE_SECONDS) -> tuple[bool, str]:
    """找到本安装正在运行的实例并优雅停掉，为启动新实例清场。

    返回 ``(stopped, message)``：没有运行中的实例时 ``(False, "")``；停了
    东西时 ``(True, 说明)``。身份确认见 `_identify_running`——只停拿得出
    身份证明的进程；端口被身份不明的占用者把着时不动手，由调用方拒启。
    """
    pid = _identify_running()
    if pid is None:
        return False, ""
    # 顺序要点：先打印发现提示再执行停止链，否则停止链的输出会跑在前面，
    # 用户看到的就是「已发出停止请求」凭空出现（2026-09-24 实测）。
    note = f"发现运行中的 Stella 实例（PID {pid}），先停止以便启动新实例…"
    print(note)
    stopped = _graceful_stop_pid(pid, grace_seconds, reason="deploy start 接管旧实例")
    return stopped, note


def register_self() -> bool:
    """Bot 进程自登记 ownership（PID + manifest）。

    「python bot.py」直启的实例由此获得与 ``deploy start`` 启动实例同等的
    可管理性：deploy stop/status、WebUI 重启都按同一套记录定位它。前提是
    环境里已有 launch token（bot.py 在 config import 前兜底生成；deploy
    start --detach 注入），否则状态接口的 token 摘要与 manifest 对不上，
    登记反而制造一个身份对不上的记录——此时放弃登记。

    任何失败都静默放弃（返回 False）：登记是增强，绝不能拦住启动。
    """
    from config import STELLA_LAUNCH_TOKEN

    if not STELLA_LAUNCH_TOKEN:
        return False
    try:
        write_pid(os.getpid())
        write_manifest(
            MANIFEST_FILE,
            manifest_for(
                instance_id=INSTANCE_ID,
                project_root=PROJECT_ROOT,
                pid=os.getpid(),
                launch_token=STELLA_LAUNCH_TOKEN,
            ),
        )
        return True
    except OSError:
        with contextlib.suppress(Exception):
            clear_pid()
            clear_manifest()
        return False


def preflight_for_foreground_start() -> bool:
    """前台启动（``deploy start`` 不带 --detach）前的清场。

    与 start_detached 同一接管语义；端口仍被身份不明的占用者把着时返回
    False——前台启动没有兜底清理，绑定失败就是用户终端里一行 10048。
    """
    replaced, note = replace_running()
    if note:
        print(note)
    if _service_port_in_use():
        print(
            "服务端口仍被身份不明的进程占用（状态接口无匹配），前台启动将无法绑定端口。"
        )
        print("请用任务管理器处理该进程，或在 .env 改用其他 PORT。")
        return False
    return True


def _hard_kill(pid: int) -> bool:
    """硬杀进程；返回进程是否已退出（成功或本来就不存在）。

    与 stop() 分开以便测试 monkeypatch。Windows 用 ``taskkill /F /T``（含子进程
    树），POSIX 用 ``SIGKILL``。
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    time.sleep(0.2)
    return not is_alive(pid)


def _fetch_live_status(timeout: float = 1.0) -> dict | None:
    """查询 Bot 进程内的状态接口；不可达返回 None。

    HOST/PORT 从 .env 读（dotenv_values 而非 os.getenv——避免受当前进程
    环境变量干扰，与 probe 的做法一致）。HOST 为 0.0.0.0 / :: 时改连
    127.0.0.1：那是「监听所有地址」的写法，不是可连接的目标地址。

    超时取 1 秒：status 是交互命令（GUI 每 1.5 秒轮询一次），
    宁可少一块信息也不能卡住。
    """
    env = dotenv_values(STELLA_HOME / ".env")
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
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("instance_id") != INSTANCE_ID:
        return None
    manifest = _owned_manifest()
    token = manifest.get("launch_token") if manifest else ""
    if token and data.get("launch_token_digest") != launch_token_digest(token):
        return None
    return data


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
    managed = pid_alive and _owned_manifest(pid) is not None

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
    data = {
        "pid": pid,
        "alive": alive,
        "pid_file_present": managed,   # GUI 据此判断进程是否由当前实例管得了
        "managed": managed,
        "instance_id": INSTANCE_ID,
        "api_reachable": live is not None,
        "log_file": str(LOG_FILE),
        "recent_log": recent,
        # 以下来自进程内状态接口；接口不可达时为 None
        "link": (live or {}).get("link"),
        "scheduler": (live or {}).get("scheduler"),
        "usage": (live or {}).get("usage"),
        # 能力清单：deploy capabilities 与 GUI 的能力面板都读它。注册表是 Bot
        # 进程内的模块级单例，别的进程拿不到，所以只能经状态接口取
        "capabilities": (live or {}).get("capabilities"),
        "uptime_seconds": (live or {}).get("uptime_seconds"),
        "note": (
            "link/scheduler/usage/capabilities 来自 Bot 进程内的状态接口，"
            "接口不可达时为 null"
        ),
    }
    runtime.sync_stella_status(
        alive=alive,
        api_reachable=live is not None,
        pid=pid,
    )
    data["runtime"] = runtime.snapshot()
    return data
