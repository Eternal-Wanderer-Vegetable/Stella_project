# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""NapCat.Shell 进程管理器（extensions.napcat_manager.manager）。

在机器人进程之外以独立 OS 进程方式管理 NapCat.Shell 前端的完整生命周期：
- 启动：通过官方 launcher-user.bat 拉起 NapCatWinBootMain.exe（注入 QQ NT）；
- 停止：定位 NapCatWinBootMain.exe 后用 taskkill /T 终止其整棵进程树
  （含由它派生的 QQ.exe 子进程），不影响本机其他独立的 QQ 登录；
- 重启：停止后重新走 launcher-user.bat 启动。

自动登录：把 QQ 账号/密码注入子进程环境变量 NAPCAT_QUICK_ACCOUNT 与
NAPCAT_QUICK_PASSWORD（或 NAPCAT_QUICK_PASSWORD_MD5），NapCat 启动时会
自动尝试快速登录，历史会话失效时用密码回退登录，从而在外部重启后自动上线。

注意：部分 NapCat.Shell 版本的启动链（NapCatWinBootMain.exe -> QQ -> node）
不会把外部进程注入的 NAPCAT_QUICK_* 环境变量透传到 WebUI/登录进程，导致
自动登录退化为二维码。为兼容此类版本，启动前会把登录变量同步写入
NapCat.Shell/config/.env（NapCat 启动时会把该文件直接读入自身 process.env），
作为环境变量注入的可靠兜底。

本模块仅提供同步函数；在异步上下文（看门狗等）请用 asyncio.to_thread 调用。
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
import time

from nonebot import logger

from config import (
    NAPCAT_QQ_ACCOUNT,
    NAPCAT_QQ_PASSWORD,
    NAPCAT_QQ_PASSWORD_MD5,
    NAPCAT_SHELL_PATH,
)

# launcher-user.bat 启动时需要用到的组件
LAUNCHER_NAME = "launcher-user.bat"
REQUIRED_FILES = (LAUNCHER_NAME, "NapCatWinBootMain.exe", "napcat.mjs")

NAPCAT_PROCESS_NAME = "NapCatWinBootMain.exe"


class NapCatNotInstalledError(RuntimeError):
    """NapCat.Shell 安装目录缺少必要启动组件时抛出。"""

    def __init__(self, shell_path: str) -> None:
        super().__init__(f"NapCat.Shell 未安装（缺少启动组件）: {shell_path}")


# 终止进程树后等待端口/会话释放的时间
_RESTART_WAIT_SECONDS = 2.0

# tasklist CSV 输出列索引（Image Name, PID, Session Name, Session#, Mem Usage）
_MIN_TASKLIST_FIELDS = 2
_TASKLIST_PID_INDEX = 1


def is_installed() -> bool:
    """NapCat.Shell 安装目录是否包含可用的启动组件。"""
    return all(_shell_file(name) for name in REQUIRED_FILES)


def _shell_file(name: str) -> bool:
    """判断 NapCat.Shell 目录下指定启动组件是否存在。"""
    return (NAPCAT_SHELL_PATH / name).is_file()


def is_running() -> bool:
    """是否存在存活的 NapCatWinBootMain 进程。"""
    return bool(_napcat_pids())


def start_napcat() -> None:
    """通过 launcher-user.bat 在机器人进程之外启动 NapCat。

    用 cmd /c 拉起批处理，隐藏控制台窗口；QQ 账号/密码经环境变量注入，
    使 NapCat 启动后自动登录。启动器返回前 NapCatWinBootMain 已独立运行。
    """
    if not is_installed():
        logger.warning(f"[NapCat] 缺少启动组件，目录: {NAPCAT_SHELL_PATH}")
        raise NapCatNotInstalledError(str(NAPCAT_SHELL_PATH))
    _write_login_env_file()
    launcher = NAPCAT_SHELL_PATH / LAUNCHER_NAME
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(
        ["cmd.exe", "/c", str(launcher)],
        cwd=str(NAPCAT_SHELL_PATH),
        env=_build_login_env(),
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info(f"[NapCat] 已通过 {LAUNCHER_NAME} 外部启动，等待 QQ 自动登录")


def stop_napcat() -> None:
    """外部终止 NapCat 进程树（NapCatWinBootMain 及其派生的 QQ 子进程）。"""
    pids = _napcat_pids()
    if not pids:
        logger.info("[NapCat] 未检测到 NapCat 进程，无需停止")
        return
    for pid in pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    logger.info(f"[NapCat] 已外部终止 NapCat 进程树: {pids}")


def restart_napcat() -> None:
    """外部重启 NapCat：先终止进程树，再重新走 launcher-user.bat 拉起。"""
    logger.warning("[NapCat] 触发外部重启 NapCat.Shell ...")
    stop_napcat()
    time.sleep(_RESTART_WAIT_SECONDS)
    start_napcat()


def _build_login_env() -> dict[str, str]:
    """构造子进程环境变量；只有配置了账号才注入登录项，密码二选一（MD5 优先）。"""
    env = dict(os.environ)
    account = NAPCAT_QQ_ACCOUNT.strip()
    password_md5 = NAPCAT_QQ_PASSWORD_MD5.strip()
    if account:
        env["NAPCAT_QUICK_ACCOUNT"] = account
    if password_md5:
        env["NAPCAT_QUICK_PASSWORD_MD5"] = password_md5
    elif account and NAPCAT_QQ_PASSWORD:
        env["NAPCAT_QUICK_PASSWORD"] = NAPCAT_QQ_PASSWORD
    return env


def _write_login_env_file() -> None:
    """把登录变量同步写入 NapCat.Shell/config/.env。

    兼容部分 NapCat.Shell 版本（其启动链不会透传外部进程环境变量到登录进程）：
    该类版本启动时会读取 NapCat.Shell/config/.env 并写入自身 process.env，
    因此启动前维护该文件，可保证 NAPCAT_QUICK_* 一定对自动登录可见。
    """
    account = NAPCAT_QQ_ACCOUNT.strip()
    password_md5 = NAPCAT_QQ_PASSWORD_MD5.strip()
    lines: list[str] = []
    if account:
        lines.append(f"NAPCAT_QUICK_ACCOUNT={account}")
    if password_md5:
        lines.append(f"NAPCAT_QUICK_PASSWORD_MD5={password_md5}")
    elif account and NAPCAT_QQ_PASSWORD:
        lines.append(f"NAPCAT_QUICK_PASSWORD={NAPCAT_QQ_PASSWORD}")
    if not lines:
        logger.warning("[NapCat] 未配置 QQ 账号/密码，跳过 config/.env 写入")
        return
    config_dir = NAPCAT_SHELL_PATH / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    target = config_dir / ".env"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"[NapCat] 已同步登录变量到 {target}")


def _napcat_pids() -> list[int]:
    """查询当前存活的所有 NapCatWinBootMain 进程 PID（tasklist CSV 解析）。"""
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {NAPCAT_PROCESS_NAME}", "/FO", "CSV", "/NH"],
        capture_output=True,
        timeout=10,
        check=False,
    )
    text = result.stdout.decode("utf-8", errors="replace")
    pids: list[int] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < _MIN_TASKLIST_FIELDS:
            continue
        try:
            pids.append(int(row[_TASKLIST_PID_INDEX]))
        except ValueError:
            continue
    return pids
