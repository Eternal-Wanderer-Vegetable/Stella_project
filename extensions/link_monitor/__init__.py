# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""OneBot 链路监测扩展（extensions.link_monitor）。

职责：监测 OneBot 链路是否存活，断开时给可操作的排查提示。**只监测、不重启**
（不重启的理由：登录风控使自动重启无效，见 design_docs/deprecated_napcat_manager.md）。

与连接方向无关：基于「最近一次收到任何 OneBot 事件」判活，反向 WS / 正向 WS 都适用。

关键设计：必须区分「没人说话」与「链路断了」。NapCat 周期性发
meta_event.heartbeat（默认 15s），有它就说明 WS 通着；因此超时后要主动探活
（bot.get_status()），探活成功说明只是安静（正常），失败才是真断开。
2026-08-14 的重启循环就是因为只挂 on_message、把安静的群误判为中断。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nonebot import get_driver, logger
from nonebot.message import event_preprocessor
from nonebot_plugin_apscheduler import scheduler

from config import (
    LINK_MONITOR_ALERT_INTERVAL,
    LINK_MONITOR_CHECK_INTERVAL,
    LINK_MONITOR_ENABLED,
    LINK_MONITOR_TIMEOUT,
)
from memory.timeutil import humanize_duration

if TYPE_CHECKING:
    from core.pipeline import Pipeline


class _State:
    """链路状态容器（对象属性代替模块级全局变量）。

    时间统一用 time.time()：与原 watchdog 一致，且 link_status() 对外暴露
    「距今多少秒」这类相对值，不依赖单调性。
    """

    last_event_time: float | None = None  # 最近一次收到任何 OneBot 事件
    connected: bool = False
    bot_self_id: str = ""
    connected_since: float | None = None
    last_probe_ok: bool | None = None
    last_probe_time: float | None = None
    last_alert_time: float | None = None


state = _State()


@event_preprocessor
async def _refresh_on_any_event() -> None:
    """任何 OneBot 事件都刷新 last_event_time。

    包括 NapCat 周期性发送的 meta_event.heartbeat（默认 15s）——有它就说明
    WebSocket 通着。原先只挂 on_message，安静的群会被误判为链路中断。
    """
    state.last_event_time = time.time()


driver = get_driver()


@driver.on_bot_connect
async def _on_bot_connect(bot) -> None:
    """连接建立即视为健康，并清零告警节流，恢复后允许再次告警。"""
    state.connected = True
    state.bot_self_id = bot.self_id
    state.connected_since = time.time()
    state.last_event_time = time.time()
    state.last_alert_time = None
    logger.info(f"[LinkMonitor] Bot {bot.self_id} 已连接")


@driver.on_bot_disconnect
async def _on_bot_disconnect(bot) -> None:
    """连接断开：置未连接，保留 last_event_time 供链路异常排查参考。"""
    state.connected = False
    state.connected_since = None
    logger.warning(f"[LinkMonitor] Bot {bot.self_id} 连接断开")


def _alert(reason: str, elapsed: float | None = None) -> None:
    """节流告警：断线期间不重复刷同样的 error，否则日志会被填满。

    文案给出可操作的排查步骤——本项目现在不再自动重启 NapCat，
    用户需要知道该去哪里看、以及**不需要重启本程序**（Bot 会自动等待重连）。
    """
    now = time.time()
    if (
        state.last_alert_time is not None
        and now - state.last_alert_time < LINK_MONITOR_ALERT_INTERVAL
    ):
        return
    state.last_alert_time = now

    elapsed_line = ""
    if elapsed is not None:
        elapsed_line = f"   （距上次收到事件 {humanize_duration(elapsed)}）\n"
    logger.error(
        f"⚠️ [LinkMonitor] OneBot 链路异常：{reason}\n"
        f"{elapsed_line}"
        f"   请依次检查：\n"
        f"   1. NapCat 是否仍在运行、账号是否掉线 —— 用 NapCatQQ Desktop 查看日志\n"
        f"   2. NapCat 的 WebSocket 客户端是否指向 ws://<Bot地址>:<PORT>/onebot/v11/ws\n"
        f"      （反向 WS；若用正向 WS 则检查 ONEBOT_WS_URLS 是否可达）\n"
        f"   3. 若两侧配了 access token，是否一致\n"
        f"   4. 端口是否被防火墙拦截或被其他程序占用\n"
        f"   Bot 会持续等待重连，无需重启本程序。"
    )


# 周期性检查：事件超时 → 主动探活 → 探活失败才告警（不重启）
@scheduler.scheduled_job("interval", seconds=LINK_MONITOR_CHECK_INTERVAL)
async def link_monitor_task() -> None:
    """检查链路：超时后主动探活，探活失败才告警。"""
    if not LINK_MONITOR_ENABLED:
        return

    if not state.connected:
        _alert("协议端未连接")
        return

    if state.last_event_time is None:
        if (
            state.connected_since is not None
            and time.time() - state.connected_since > LINK_MONITOR_TIMEOUT
        ):
            _alert("已连接但从未收到任何事件")
        return

    if time.time() - state.last_event_time <= LINK_MONITOR_TIMEOUT:
        logger.debug("[LinkMonitor] 链路健康（事件新鲜）")
        return

    # 二次确认：心跳超时不等于链路断开。主动调一次 OneBot API，
    # 能返回即说明连接健康，只是群里安静——该问的是「连接通不通」，
    # 不是「有没有人说话」。
    try:
        from nonebot import get_bot

        bot = get_bot()
    except Exception as e:
        state.last_probe_ok = False
        state.last_probe_time = time.time()
        _alert(f"无可用 Bot 连接（{e}）")
        return

    try:
        await bot.get_status()
    except Exception as e:
        state.last_probe_ok = False
        state.last_probe_time = time.time()
        _alert(
            f"已连接但 API 无响应（{e}）",
            time.time() - state.last_event_time,
        )
        return

    # 探活成功：刷新 last_event_time，避免每个检查周期都重复探活
    state.last_probe_ok = True
    state.last_probe_time = time.time()
    state.last_event_time = time.time()
    logger.debug("[LinkMonitor] 超时但探活成功，链路正常，只是没人说话")


def link_status() -> dict:
    """导出链路状态，供 deploy doctor 与将来的前端查询。

    healthy 是给调用方的单一布尔（已连接 且（事件新鲜 或 最近探活成功）），
    避免每个消费方各自拼判断逻辑。
    """
    now = time.time()
    last_event_seconds_ago = (
        None if state.last_event_time is None else now - state.last_event_time
    )
    connected_seconds = (
        None if state.connected_since is None else now - state.connected_since
    )
    last_probe_seconds_ago = (
        None if state.last_probe_time is None else now - state.last_probe_time
    )
    healthy = (
        LINK_MONITOR_ENABLED
        and state.connected
        and (
            (last_event_seconds_ago is not None and last_event_seconds_ago <= LINK_MONITOR_TIMEOUT)
            or state.last_probe_ok is True
        )
    )
    return {
        "enabled": LINK_MONITOR_ENABLED,
        "connected": state.connected,
        "bot_self_id": state.bot_self_id,
        "connected_seconds": connected_seconds,
        "last_event_seconds_ago": last_event_seconds_ago,
        "last_probe_ok": state.last_probe_ok,
        "last_probe_seconds_ago": last_probe_seconds_ago,
        "timeout": LINK_MONITOR_TIMEOUT,
        "healthy": healthy,
    }


class _Hooked:
    """扩展幂等标记容器（对象属性代替模块级全局变量）。"""

    done: bool = False


_hooked = _Hooked()


def setup(_pipeline: Pipeline) -> None:
    """接入扩展机制。

    钩子与定时任务在模块 import 时已注册，这里只做一次开关状态的日志声明
    （保持与其他扩展一致的加载可见性）。
    """
    if _hooked.done:
        return
    _hooked.done = True
    logger.info(
        f"[扩展: link_monitor] 链路监测已就绪: "
        f"enabled={LINK_MONITOR_ENABLED}, timeout={LINK_MONITOR_TIMEOUT}s"
    )


def reset_state() -> None:
    """把 state 的所有字段还原为初始值，供测试用。"""
    state.last_event_time = None
    state.connected = False
    state.bot_self_id = ""
    state.connected_since = None
    state.last_probe_ok = None
    state.last_probe_time = None
    state.last_alert_time = None
