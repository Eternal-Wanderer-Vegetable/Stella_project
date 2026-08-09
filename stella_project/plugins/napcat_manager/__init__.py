# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""napcat_manager 插件包入口（NoneBot 插件）。

用外部 OS 进程的方式完整接管 NapCat.Shell 前端的生命周期：
- manager：通过 launcher-user.bat 启停/重启 NapCatWinBootMain.exe，
  QQ 账号/密码注入环境变量实现外部重启后的自动登录；
- watchdog：监控群消息流心跳，链路中断时触发外部重启（不再走 WebUI API）；
- 机器人启动时自动拉起 NapCat（若未在运行）。
"""

from __future__ import annotations

import asyncio

from nonebot import get_driver, get_plugin_config, logger
from nonebot.plugin import PluginMetadata

from config import NAPCAT_AUTO_START

from . import manager as napcat_manager
from . import watchdog as napcat_watchdog
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="napcat_manager",
    description="NapCat.Shell 前端管理器：自动启停、掉线外部重启、QQ 账号密码自动登录",
    usage="无手动操作：插件负责在机器人启动时拉起 NapCat，并在链路中断时自动重启",
    config=Config,
)

# 读取插件级配置（实际字段由 config/settings.py 提供）
config = get_plugin_config(Config)

# 看门狗的外部重启实现 = 在独立进程中重启 NapCat（取代已失效的 WebUI API 重启）
napcat_watchdog.set_restart_impl(napcat_manager.restart_napcat)


@get_driver().on_startup
async def _ensure_napcat_started() -> None:
    """机器人启动时自动拉起 NapCat（未配置自动启动或已在运行则跳过）。"""
    if not NAPCAT_AUTO_START:
        logger.info("[NapCat] NAPCAT_AUTO_START=false，跳过自动启动")
        return
    if not napcat_manager.is_installed():
        logger.warning(
            "[NapCat] NapCat.Shell 未安装（缺少启动组件），请检查 NAPCAT_SHELL_PATH"
        )
        return
    if napcat_manager.is_running():
        logger.info("[NapCat] NapCat 已在运行，跳过自动启动")
        return
    try:
        await asyncio.to_thread(napcat_manager.start_napcat)
    except Exception:  # noqa: BLE001  # 启动失败仅告警，不中断机器人
        logger.exception("[NapCat] 启动阶段自动拉起 NapCat 失败")
        return
    logger.success(
        "[NapCat] 已通过 launcher-user.bat 自动拉起 NapCat.Shell"
    )
