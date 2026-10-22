# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Monitor OneBot V11 links without assigning fake health to other adapters.

NapCat periodically sends ``meta_event.heartbeat``. A quiet chat therefore does
not mean a dead link: after the event timeout, actively call ``get_status`` on
that exact Bot. This module monitors every OneBot V11 connection independently;
adapters without a comparable heartbeat remain connected with unknown health.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import nonebot
from nonebot import get_driver, logger
from nonebot.adapters import Bot, Event
from nonebot.message import event_preprocessor
from nonebot_plugin_apscheduler import scheduler

from config import (
    LINK_MONITOR_ALERT_INTERVAL,
    LINK_MONITOR_CHECK_INTERVAL,
    LINK_MONITOR_ENABLED,
    LINK_MONITOR_TIMEOUT,
)
from gravitas.dependency_recovery import (
    classify_dependency_failure,
    connection_scope,
    dependency_recovery,
)
from memory.timeutil import humanize_duration

if TYPE_CHECKING:
    from core.pipeline import Pipeline


def _adapter_name(bot: Any) -> str:
    adapter = getattr(bot, "adapter", None)
    try:
        name = adapter.get_name()
    except Exception:
        name = getattr(adapter, "name", None)
    return str(name or "unknown")


def _is_onebot_v11(adapter_name: str) -> bool:
    """Match the NoneBot adapter type, never a configured instance ID."""
    return adapter_name.casefold().replace(" ", "") == "onebotv11"


@dataclass(slots=True)
class _BotState:
    adapter: str
    self_id: str
    instance_ref: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    connected: bool = False
    connected_since: float | None = None
    last_event_time: float | None = None
    last_probe_ok: bool | None = None
    last_probe_time: float | None = None
    last_alert_time: float | None = None


@dataclass(slots=True)
class _State:
    bots: dict[tuple[str, str], _BotState] = field(default_factory=dict)
    no_bot_alert_time: float | None = None


state = _State()


def _bot_key(bot: Any) -> tuple[str, str]:
    return (_adapter_name(bot), str(getattr(bot, "self_id", "")))


def _state_for(bot: Any) -> _BotState:
    adapter, self_id = _bot_key(bot)
    key = (adapter, self_id)
    record = state.bots.get(key)
    if record is None:
        record = _BotState(adapter=adapter, self_id=self_id)
        state.bots[key] = record
    return record


def _current_adapters() -> dict[str, Any]:
    try:
        return dict(nonebot.get_adapters())
    except Exception:
        return {}


def _current_bots() -> list[Any]:
    try:
        return list(nonebot.get_bots().values())
    except Exception:
        return []


def _sync_active_bots() -> list[Any]:
    """Refresh lifecycle state from NoneBot's current Bot registry."""
    active = _current_bots()
    active_keys: set[tuple[str, str]] = set()
    now = time.time()
    for bot in active:
        record = _state_for(bot)
        active_keys.add(_bot_key(bot))
        if not record.connected:
            record.connected_since = now
        record.connected = True
    for key, record in state.bots.items():
        if key not in active_keys and record.connected:
            record.connected = False
            record.connected_since = None
    return active


@event_preprocessor
async def _refresh_on_any_event(bot: Bot, event: Event) -> None:
    """Refresh heartbeat only for OneBot V11 events."""
    del event
    if not _is_onebot_v11(_adapter_name(bot)):
        return
    record = _state_for(bot)
    now = time.time()
    if not record.connected:
        record.connected_since = now
    record.connected = True
    record.last_event_time = now
    fence = dependency_recovery.begin_attempt(connection_scope(record.instance_ref))
    dependency_recovery.record_attempt_result(fence, success=True)


driver = get_driver()


def _ws_hint() -> str:
    """Return the configured reverse WS endpoint for actionable alerts."""
    try:
        cfg = get_driver().config
        host = getattr(cfg, "host", None)
        port = getattr(cfg, "port", None)
        if not host or not port:
            return "ws://[Bot地址]:[端口]/onebot/v11/ws"
        return f"ws://{host}:{port}/onebot/v11/ws"
    except Exception:
        return "ws://[Bot地址]:[端口]/onebot/v11/ws"


@driver.on_bot_connect
async def _on_bot_connect(bot: Bot) -> None:
    """Mark only the connecting Bot healthy and reset its alert throttle."""
    record = _state_for(bot)
    now = time.time()
    record.connected = True
    record.connected_since = now
    record.last_event_time = now if _is_onebot_v11(record.adapter) else None
    record.last_alert_time = None
    logger.info(f"[LinkMonitor] {record.adapter} Bot {record.self_id} 已连接")


@driver.on_bot_disconnect
async def _on_bot_disconnect(bot: Bot) -> None:
    """Mark the disconnected Bot without changing any peer's state."""
    record = _state_for(bot)
    record.connected = False
    record.connected_since = None
    logger.warning(f"[LinkMonitor] {record.adapter} Bot {record.self_id} 连接断开")


def _alert(record: _BotState, reason: str, elapsed: float | None = None) -> None:
    """Throttle repeated alerts independently for each OneBot connection."""
    now = time.time()
    if (
        record.last_alert_time is not None
        and now - record.last_alert_time < LINK_MONITOR_ALERT_INTERVAL
    ):
        return
    record.last_alert_time = now

    elapsed_line = ""
    if elapsed is not None:
        elapsed_line = f"   （距上次收到事件 {humanize_duration(elapsed)}）\n"
    logger.error(
        f"⚠️ [LinkMonitor] OneBot 链路异常（实例 {record.instance_ref}）：{reason}\n"
        f"{elapsed_line}"
        f"   请依次检查：\n"
        f"   1. NapCat 是否仍在运行、账号是否掉线 —— 用 NapCatQQ Desktop 查看日志\n"
        f"   2. NapCat 的 WebSocket 客户端是否指向 {_ws_hint()}\n"
        f"      （反向 WS；若用正向 WS 则检查 ONEBOT_WS_URLS 是否可达）\n"
        f"   3. 若两侧配了 access token，是否一致\n"
        f"   4. 端口是否被防火墙拦截或被其他程序占用\n"
        f"   Bot 会持续等待重连，无需重启本程序。"
    )


def _alert_no_bot() -> None:
    now = time.time()
    if (
        state.no_bot_alert_time is not None
        and now - state.no_bot_alert_time < LINK_MONITOR_ALERT_INTERVAL
    ):
        return
    state.no_bot_alert_time = now
    logger.error("⚠️ [LinkMonitor] 已启用 OneBot V11，但当前没有已连接的 Bot。")


def _event_age(record: _BotState, now: float) -> float | None:
    return None if record.last_event_time is None else now - record.last_event_time


def _record_healthy(record: _BotState, now: float) -> bool:
    if not record.connected:
        return False
    age = _event_age(record, now)
    return (age is not None and age <= LINK_MONITOR_TIMEOUT) or record.last_probe_ok is True


@scheduler.scheduled_job("interval", seconds=LINK_MONITOR_CHECK_INTERVAL)
async def link_monitor_task() -> None:
    """Probe every stale OneBot V11 connection independently."""
    if not LINK_MONITOR_ENABLED:
        return

    adapters = _current_adapters()
    if not any(_is_onebot_v11(str(name)) for name in adapters):
        return

    active_bots = _sync_active_bots()
    onebot_bots = [
        bot for bot in active_bots if _is_onebot_v11(_adapter_name(bot))
    ]
    if not onebot_bots:
        records = [
            record
            for record in state.bots.values()
            if _is_onebot_v11(record.adapter)
        ]
        if records:
            now = time.time()
            for record in records:
                age = _event_age(record, now)
                _alert(record, "协议端未连接", age)
        else:
            _alert_no_bot()
        return

    now = time.time()
    for bot in onebot_bots:
        record = _state_for(bot)
        age = _event_age(record, now)
        if age is None:
            connected_for = (
                None
                if record.connected_since is None
                else now - record.connected_since
            )
            if connected_for is not None and connected_for > LINK_MONITOR_TIMEOUT:
                _alert(record, "已连接但从未收到任何事件")
            continue
        if age <= LINK_MONITOR_TIMEOUT:
            logger.debug(
                f"[LinkMonitor] OneBot 实例 {record.instance_ref} 链路健康（事件新鲜）"
            )
            continue

        probe_lease = dependency_recovery.claim_probe(
            connection_scope(record.instance_ref),
            min_interval_seconds=LINK_MONITOR_CHECK_INTERVAL,
        )
        if probe_lease is None:
            continue
        try:
            await bot.get_status()
        except Exception as exc:
            accepted = dependency_recovery.finish_probe(
                probe_lease,
                success=False,
                failure_kind=classify_dependency_failure(exc),
            )
            if not accepted:
                continue
            record.last_probe_ok = False
            record.last_probe_time = time.time()
            _alert(record, f"已连接但 API 无响应（{exc}）", time.time() - record.last_event_time)
            continue

        accepted = dependency_recovery.finish_probe(
            probe_lease,
            success=True,
            next_probe_delay=LINK_MONITOR_CHECK_INTERVAL,
        )
        if not accepted:
            continue
        record.last_probe_ok = True
        record.last_probe_time = time.time()
        record.last_event_time = record.last_probe_time
        logger.debug(
            f"[LinkMonitor] OneBot 实例 {record.instance_ref} 超时但探活成功"
        )


def _age(value: float | None, now: float) -> float | None:
    return None if value is None else now - value


def link_status() -> dict[str, Any]:
    """Export aggregate health plus opaque per-connection status records."""
    adapters = _current_adapters()
    applicable = any(_is_onebot_v11(str(name)) for name in adapters)
    active_bots = _sync_active_bots()
    now = time.time()

    onebot_records = [
        record
        for record in state.bots.values()
        if _is_onebot_v11(record.adapter)
    ]
    # A registry can be populated before the connect callbacks fire.
    for bot in active_bots:
        record = _state_for(bot)
        if record not in onebot_records and _is_onebot_v11(record.adapter):
            onebot_records.append(record)

    per_bot: list[dict[str, Any]] = []
    for record in onebot_records:
        age = _event_age(record, now)
        connected_seconds = _age(record.connected_since, now)
        per_bot.append(
            {
                "instance_ref": record.instance_ref,
                "connected": record.connected,
                "healthy": _record_healthy(record, now),
                "connected_seconds": connected_seconds,
                "last_event_seconds_ago": age,
                "last_probe_ok": record.last_probe_ok,
                "last_probe_seconds_ago": _age(record.last_probe_time, now),
            }
        )

    connections = []
    for record in sorted(state.bots.values(), key=lambda item: item.instance_ref):
        onebot = _is_onebot_v11(record.adapter)
        connections.append(
            {
                "adapter": record.adapter,
                "instance_ref": record.instance_ref,
                "connected": record.connected,
                "health": _record_healthy(record, now) if onebot else None,
            }
        )

    enabled = bool(LINK_MONITOR_ENABLED and applicable)
    connected = (
        any(record.connected for record in onebot_records) if applicable else None
    )
    if not applicable:
        healthy: bool | None = None
    elif not enabled:
        healthy = False
    else:
        healthy = bool(onebot_records) and all(
            _record_healthy(record, now) for record in onebot_records
        )

    # Preserve the legacy single-Bot fields. Multi-Bot callers use the explicit
    # ``bots`` entries so no one connection is misrepresented as the whole group.
    singleton = onebot_records[0] if len(onebot_records) == 1 else None
    last_event_ages = [
        age for record in onebot_records if (age := _event_age(record, now)) is not None
    ]
    connected_ages = [
        age
        for record in onebot_records
        if (age := _age(record.connected_since, now)) is not None
    ]
    probe_ages = [
        age
        for record in onebot_records
        if (age := _age(record.last_probe_time, now)) is not None
    ]
    if singleton:
        aggregate_probe_ok = singleton.last_probe_ok
    elif any(record.last_probe_ok is False for record in onebot_records):
        aggregate_probe_ok = False
    elif onebot_records and all(
        record.last_probe_ok is True for record in onebot_records
    ):
        aggregate_probe_ok = True
    else:
        aggregate_probe_ok = None

    config_status: dict[str, Any] = {}
    if applicable:
        try:
            from deploy.probe import _probe_onebot

            config_status = _probe_onebot()
        except Exception:
            pass

    return {
        "enabled": enabled,
        "applicable": applicable,
        "connected": connected,
        "bot_self_id": singleton.self_id if singleton else "",
        "connected_seconds": (
            _age(singleton.connected_since, now)
            if singleton
            else (max(connected_ages) if connected_ages else None)
        ),
        "last_event_seconds_ago": (
            _event_age(singleton, now)
            if singleton
            else (max(last_event_ages) if last_event_ages else None)
        ),
        "last_probe_ok": aggregate_probe_ok,
        "last_probe_seconds_ago": (
            _age(singleton.last_probe_time, now)
            if singleton
            else (max(probe_ages) if probe_ages else None)
        ),
        "timeout": LINK_MONITOR_TIMEOUT,
        "healthy": healthy,
        "mode": config_status.get("mode", "unknown"),
        "endpoint_configured": config_status.get("endpoint_configured"),
        "forward_reachable": config_status.get("forward_reachable"),
        "reverse_port_in_use": config_status.get("port_in_use"),
        "token_configured": config_status.get("token_configured", False),
        "token_in_url": config_status.get("token_in_url", False),
        "token_consistent": config_status.get("token_consistent"),
        "waiting_for_reconnect": enabled and not connected,
        "bots": per_bot,
        "connections": connections,
    }


class _Hooked:
    done: bool = False


_hooked = _Hooked()


def setup(_pipeline: Pipeline) -> None:
    """Expose extension readiness in startup logs."""
    if _hooked.done:
        return
    _hooked.done = True
    logger.info(
        f"[扩展: link_monitor] 链路监测已就绪: "
        f"enabled={LINK_MONITOR_ENABLED}, timeout={LINK_MONITOR_TIMEOUT}s"
    )


def reset_state() -> None:
    """Reset all in-memory connection state for tests."""
    state.bots.clear()
    state.no_bot_alert_time = None
