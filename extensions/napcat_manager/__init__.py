# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""NapCat 前端管理扩展（官方扩展示例，extensions/napcat_manager）。

通过 extensions 机制（``setup(pipeline)`` 接入）在机器人进程之外以独立 OS
进程方式完整接管 NapCat.Shell 前端生命周期，作为"前端进程自动化"扩展的官方示例：

- manager：经官方 launcher-user.bat 外部启停 NapCatWinBootMain.exe
  （taskkill 整树终止、含派生的 QQ 子进程），并把 QQ 账号/密码注入
  NAPCAT_* 环境变量，实现外部重启后的自动登录；
- watchdog：群消息心跳 + 定时检查，链路中断（默认 300 秒无消息）时自动外部重启。

与其他前端不干扰的设计：看门狗只依赖一个"外部重启实现的注入点"
（watchdog.set_restart_impl），未来若接管其它前端（GoCQ / LLOneBot 等），
只需实现同名协议并重新注入，无需改动本扩展之外的代码。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from nonebot import get_driver, logger

from config import NAPCAT_AUTO_START, NAPCAT_SHELL_PATH

from . import manager, watchdog

if TYPE_CHECKING:
    from core.pipeline import Pipeline

class _Hooked:
    """扩展幂等标记容器（对象属性代替模块级全局变量）。"""

    done: bool = False


_hooked = _Hooked()


def setup(_pipeline: Pipeline) -> None:
    """接入扩展机制：登记看门狗外部重启实现，并注册启动时自动拉起 NapCat。"""
    if _hooked.done:
        return
    _hooked.done = True
    watchdog.set_restart_impl(manager.restart_napcat)
    _register_auto_start()
    logger.info(f"[扩展: napcat_manager] 外部管理已就绪: {NAPCAT_SHELL_PATH}")


def _register_auto_start() -> None:
    """注册 on_startup 钩子：机器人启动时按需自动拉起 NapCat。"""

    @get_driver().on_startup
    async def _ensure_napcat_started() -> None:
        """机器人启动时自动拉起 NapCat（未配置自动启动或已在运行则跳过）。"""
        if not NAPCAT_AUTO_START:
            logger.info("[NapCat] NAPCAT_AUTO_START=false, 跳过自动启动")
            return
        if not manager.is_installed():
            logger.warning(
                "[NapCat] NapCat.Shell 未安装（缺少启动组件）, 请检查 NAPCAT_SHELL_PATH"
            )
            return
        if manager.is_running():
            logger.info("[NapCat] NapCat 已在运行, 跳过自动启动")
            return
        try:
            await asyncio.to_thread(manager.start_napcat)
        except Exception:  # 启动失败仅告警，不阻断扩展加载
            logger.exception("[NapCat] 启动阶段自动拉起 NapCat 失败")
            return
        logger.success("[NapCat] 已通过 launcher-user.bat 自动拉起 NapCat.Shell")
