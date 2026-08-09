# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""NapCat 消息流看门狗（napcat_manager.watchdog）。

监控 QQ 群消息是否仍在正常流入：每收到任意一条群消息就刷新心跳时间；
周期性任务检查心跳距今是否超过 NAPCAT_WATCHDOG_TIMEOUT（默认 300 秒），
若超出则判定 NapCat 链路中断，改为在机器人进程之外外部重启 NapCat
（经 launcher-user.bat 拉起，取代原先走 WebUI API 的不可用重启路径），
并把心跳时间拨后 NAPCAT_WATCHDOG_RESTART_COOLDOWN 秒避免恢复期间反复触发。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import logger, on_message
from nonebot_plugin_apscheduler import scheduler

from config import (
    NAPCAT_WATCHDOG_CHECK_INTERVAL,
    NAPCAT_WATCHDOG_RESTART_COOLDOWN,
    NAPCAT_WATCHDOG_TIMEOUT,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _Heartbeat:
    """看门狗心跳时间容器（对象属性代替模块级全局变量）。"""

    last_event_time: float = time.time()


class _RestartState:
    """外部重启实现入口容器；由 __init__ 注册为 manager.restart_napcat。"""

    impl: Callable[[], None] | None = None


heartbeat = _Heartbeat()
restart_state = _RestartState()


def set_restart_impl(impl: Callable[[], None] | None) -> None:
    """注入外部重启实现；测试/使用者可通过这里替换重启行为。"""
    restart_state.impl = impl


# 监听所有消息（不挂起其他处理器）：只要有消息进入就刷新心跳时间
msg_monitor = on_message(priority=1, block=False)


@msg_monitor.handle()
async def _refresh_heartbeat() -> None:
    """记录心跳时间到 heartbeat（看门狗心跳）。"""
    heartbeat.last_event_time = time.time()


async def _external_restart() -> None:
    """在事件循环之外执行外部重启，避免阻塞机器人主线程。"""
    impl = restart_state.impl
    if impl is None:
        logger.warning("[Watchdog] 未注册外部重启实现，跳过重启")
        return
    try:
        await asyncio.to_thread(impl)
    except Exception:  # noqa: BLE001  # 重启失败不拖垮看门狗循环
        logger.exception("[Watchdog] 外部重启 NapCat 失败")


# 周期性检查：超时无消息进入则外部重启 NapCat
@scheduler.scheduled_job("interval", seconds=NAPCAT_WATCHDOG_CHECK_INTERVAL)
async def watchdog_task() -> None:
    """检查消息流心跳：超时未更新则触发外部重启，并进入冷却缓冲。"""
    if time.time() - heartbeat.last_event_time <= NAPCAT_WATCHDOG_TIMEOUT:
        return
    logger.warning("[Watchdog] 检测到 NapCat 消息流中断，准备外部重启 ...")
    await _external_restart()
    # 拨后缓冲：给重启到恢复留出时间，避免修复过程中反复触发重启
    heartbeat.last_event_time = time.time() + NAPCAT_WATCHDOG_RESTART_COOLDOWN
