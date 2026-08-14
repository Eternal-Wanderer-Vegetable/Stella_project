# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""NapCat 链路看门狗（extensions.napcat_manager.watchdog）。

监控 NapCat 的 OneBot 链路是否仍健康：收到**任何**事件（含 NapCat 周期性发送的
meta_event.heartbeat，默认 15s）就刷新心跳时间——链路是否通，看的是「有没有事件」，
不是「有没有人说话」，安静的群不该被误判为链路中断。

周期性任务检查心跳距今是否超过 NAPCAT_WATCHDOG_TIMEOUT（默认 300 秒）；超时后再
主动调用一次 OneBot API 二次确认，只有探活也失败才判定链路中断，在机器人进程之外
触发外部重启（经 launcher-user.bat 拉起），并把心跳时间拨后
NAPCAT_WATCHDOG_RESTART_COOLDOWN 秒避免恢复期间反复触发。连续重启次数达到
NAPCAT_WATCHDOG_MAX_RESTARTS 后停止自动重启（重启换不回连接时，高频登录可能
触发 QQ 风控，交给人工处理）。bot 重新连接时清零连续计数。

与特定前端解耦：外部重启实现由 setup() 通过 set_restart_impl 注入，
替换为其它前端（GoCQ / LLP 等）的重启器即可复用本看门狗逻辑。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nonebot import get_driver, logger
from nonebot.message import event_preprocessor
from nonebot_plugin_apscheduler import scheduler

from config import (
    NAPCAT_WATCHDOG_CHECK_INTERVAL,
    NAPCAT_WATCHDOG_MAX_RESTARTS,
    NAPCAT_WATCHDOG_RESTART_COOLDOWN,
    NAPCAT_WATCHDOG_TIMEOUT,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class _Heartbeat:
    """看门狗心跳时间容器（对象属性代替模块级全局变量）。"""

    last_event_time: float = time.time()


class _RestartState:
    """外部重启实现入口容器；由 setup() 注册为 manager.restart_napcat。

    consecutive 记录连续重启次数（on_bot_connect 时清零）。防止「重启换不回连接」
    时无限循环：那种情况下重启只会持续把 bot 踢下线，且高频登录可能触发 QQ 风控。
    """

    impl: Callable[[], None] | None = None
    consecutive: int = 0


heartbeat = _Heartbeat()
restart_state = _RestartState()


def set_restart_impl(impl: Callable[[], None] | None) -> None:
    """注入外部重启实现；测试/使用者可通过这里替换重启行为。"""
    restart_state.impl = impl


@event_preprocessor
async def _refresh_on_any_event() -> None:
    """任何 OneBot 事件都刷新心跳，而不只是消息。

    NapCat 会周期性发送 meta_event.heartbeat（默认 15s），有它就说明
    WebSocket 通着。原先只挂 on_message，安静的群会被误判为链路中断——
    2026-08-14 的重启循环即由此产生。
    """
    heartbeat.last_event_time = time.time()


driver = get_driver()


@driver.on_bot_connect
async def _on_bot_connect(bot) -> None:
    """连接建立即视为健康，并清零连续重启计数。"""
    heartbeat.last_event_time = time.time()
    restart_state.consecutive = 0
    logger.info(f"[Watchdog] Bot {bot.self_id} 已连接，心跳重置")


@driver.on_bot_disconnect
async def _on_bot_disconnect(bot) -> None:
    logger.warning(f"[Watchdog] Bot {bot.self_id} 连接断开")


async def _external_restart() -> None:
    """在事件循环之外执行外部重启，避免阻塞机器人主线程。"""
    impl = restart_state.impl
    if impl is None:
        logger.warning("[Watchdog] 未注册外部重启实现，跳过重启")
        return
    try:
        await asyncio.to_thread(impl)
    except Exception:  # 重启失败不拖垮看门狗循环
        logger.exception("[Watchdog] 外部重启 NapCat 失败")


# 周期性检查：心跳超时且主动探活失败则外部重启 NapCat
@scheduler.scheduled_job("interval", seconds=NAPCAT_WATCHDOG_CHECK_INTERVAL)
async def watchdog_task() -> None:
    """检查链路心跳：超时且主动探活失败才触发外部重启。"""
    if time.time() - heartbeat.last_event_time <= NAPCAT_WATCHDOG_TIMEOUT:
        return

    # 二次确认：心跳超时不等于链路断开。主动调一次 OneBot API，
    # 能返回即说明连接健康，只是群里安静——看门狗该问的是「连接通不通」，
    # 不是「有没有人说话」。
    try:
        from nonebot import get_bot

        await get_bot().get_status()
        heartbeat.last_event_time = time.time()
        logger.debug("[Watchdog] 心跳超时但主动探活成功，链路正常")
        return
    except Exception as e:
        logger.warning(f"[Watchdog] 心跳超时且主动探活失败（{e}），准备外部重启 ...")

    if restart_state.consecutive >= NAPCAT_WATCHDOG_MAX_RESTARTS:
        logger.error(
            f"[Watchdog] 连续 {restart_state.consecutive} 次重启仍未恢复，停止自动重启。"
            "请人工检查 QQ 登录状态（可能已退化为扫码或触发风控）"
        )
        heartbeat.last_event_time = time.time()
        return

    restart_state.consecutive += 1
    logger.warning(
        f"[Watchdog] 第 {restart_state.consecutive}/{NAPCAT_WATCHDOG_MAX_RESTARTS} 次外部重启"
    )
    await _external_restart()
    heartbeat.last_event_time = time.time() + NAPCAT_WATCHDOG_RESTART_COOLDOWN
