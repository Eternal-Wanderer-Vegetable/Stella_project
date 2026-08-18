# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""OneBot 链路监测（link_monitor）的单元测试。

extensions.link_monitor 在 import 时就会向 nonebot 注册钩子
（event_preprocessor / driver.on_bot_connect / scheduler.scheduled_job），
而纯测试环境没有 NoneBot 运行时。因此这里先注入桩模块/桩对象再 import：

- nonebot_plugin_apscheduler 整体替换为带 scheduled_job 的桩模块（真实模块
  import 即要求 get_driver，会抛「NoneBot has not been initialized」）；
- nonebot.get_driver / nonebot.get_bot 替换为桩对象，避免「未初始化」异常；
- nonebot.message.event_preprocessor 换成只登记 handler 的桩装饰器。

这样 link_monitor 的模块级注册全部落到桩上，测试即可直接调用
link_monitor_task / on_bot_connect 处理器来验证判定逻辑（是否探活、是否告警、
事件刷新、探活成功后的心跳回拨）。

注意：extensions/ 不在 coverage 范围（pyproject.toml omit），但链路判定逻辑
值得独立测试——它曾经让 bot 掉线一整夜（2026-08-14 重启循环），本次重构后
只告警不重启，更要防止它把「安静的群」误判成链路故障。
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import LINK_MONITOR_TIMEOUT


class _StubScheduler:
    """带 scheduled_job 装饰器的桩调度器，登记注册的周期性任务。"""

    def __init__(self) -> None:
        self.jobs: list = []

    def scheduled_job(self, *args, **kwargs):
        def _deco(func):
            self.jobs.append(func)
            return func

        return _deco


class _StubDriver:
    """桩 driver：on_bot_connect / on_bot_disconnect 只作登记，不触发事件流。"""

    def __init__(self) -> None:
        self.on_connect: list = []
        self.on_disconnect: list = []

    def on_bot_connect(self, func):
        self.on_connect.append(func)
        return func

    def on_bot_disconnect(self, func):
        self.on_disconnect.append(func)
        return func


@pytest.fixture
def link_monitor(monkeypatch):
    """注入桩后重新 import link_monitor 模块，返回模块与注册钩子的上下文。"""
    import nonebot
    import nonebot.message

    # 1) 替换 apscheduler 模块：真实模块 import 需要 NoneBot 驱动已初始化
    scheduler = _StubScheduler()
    stub_module = types.ModuleType("nonebot_plugin_apscheduler")
    stub_module.scheduler = scheduler  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler", stub_module)

    # 2) event_preprocessor：桩装饰器，只把 handler 登记下来
    preprocess_handlers: list = []

    def _event_preprocessor(func):
        preprocess_handlers.append(func)
        return func

    monkeypatch.setattr(nonebot.message, "event_preprocessor", _event_preprocessor)

    # 3) get_driver / get_bot 换成桩，避免抛「NoneBot has not been initialized」
    driver = _StubDriver()

    bot = MagicMock()
    bot.get_status = AsyncMock()

    monkeypatch.setattr(nonebot, "get_driver", lambda: driver)
    monkeypatch.setattr(nonebot, "get_bot", lambda: bot)

    # 4) 清掉可能残留的旧 import，重新加载 link_monitor（触发模块级注册）
    monkeypatch.delitem(sys.modules, "extensions.link_monitor", raising=False)
    mod = importlib.import_module("extensions.link_monitor")

    return {
        "mod": mod,
        "scheduler": scheduler,
        "driver": driver,
        "bot": bot,
        "preprocess_handlers": preprocess_handlers,
    }


def _run(coro) -> None:
    """在临时事件循环里跑完异步协程（不依赖 pytest-asyncio）。"""
    asyncio.run(coro)


def test_any_event_refreshes_last_event_time(link_monitor):
    """event_preprocessor 注册的处理器：任何事件都刷新 last_event_time。"""
    mod = link_monitor["mod"]
    mod.state.last_event_time = time.time() - 100

    handlers = link_monitor["preprocess_handlers"]
    assert handlers, "event_preprocessor 应已注册 _refresh_on_any_event"
    for handler in handlers:
        _run(handler())

    assert mod.state.last_event_time >= time.time() - 1


def test_fresh_event_no_probe(link_monitor):
    """事件新鲜（距上次收到事件未超时）：不探活。"""
    bot = link_monitor["bot"]
    mod = link_monitor["mod"]
    mod.state.connected = True
    mod.state.last_event_time = time.time()

    _run(mod.link_monitor_task())

    bot.get_status.assert_not_called()


def test_timeout_probe_ok_refreshes_and_no_alert(link_monitor):
    """事件超时但主动探活成功：判定链路正常，刷新 last_event_time 且不告警。"""
    bot = link_monitor["bot"]
    mod = link_monitor["mod"]
    mod.state.connected = True
    mod.state.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 10
    bot.get_status.return_value = {}

    before = time.time()
    _run(mod.link_monitor_task())
    after = time.time()

    assert mod.state.last_probe_ok is True
    assert mod.state.last_probe_time is not None
    # 探活成功后把 last_event_time 拨回当前时刻，避免每个周期都重复探活
    assert before <= mod.state.last_event_time <= after
    assert mod.state.last_alert_time is None
    bot.get_status.assert_awaited_once()


def test_timeout_probe_fail_alerts(link_monitor):
    """事件超时且探活失败：记录探活失败并告警。"""
    bot = link_monitor["bot"]
    mod = link_monitor["mod"]
    mod.state.connected = True
    mod.state.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 10
    bot.get_status.side_effect = RuntimeError("网络不可达")

    _run(mod.link_monitor_task())

    assert mod.state.last_probe_ok is False
    assert mod.state.last_probe_time is not None
    assert mod.state.last_alert_time is not None


def test_alert_throttled(link_monitor):
    """告警节流：断线期间连续跑任务只告警一次，不刷屏。"""
    bot = link_monitor["bot"]
    mod = link_monitor["mod"]
    bot.get_status.side_effect = RuntimeError("网络不可达")
    mod.state.connected = True
    mod.state.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 10

    _run(mod.link_monitor_task())
    first_alert = mod.state.last_alert_time
    assert first_alert is not None

    _run(mod.link_monitor_task())
    assert mod.state.last_alert_time == first_alert


def test_not_connected_alerts_without_probe(link_monitor):
    """协议端未连接：直接告警，不探活。"""
    bot = link_monitor["bot"]
    mod = link_monitor["mod"]
    mod.state.connected = False
    mod.state.last_event_time = time.time() - 1000

    _run(mod.link_monitor_task())

    assert mod.state.last_alert_time is not None
    bot.get_status.assert_not_called()


def test_disabled_does_nothing(link_monitor, monkeypatch):
    """监测开关关闭：不探活、不告警。"""
    bot = link_monitor["bot"]
    mod = link_monitor["mod"]
    monkeypatch.setattr(mod, "LINK_MONITOR_ENABLED", False)
    mod.state.connected = True
    mod.state.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 10

    _run(mod.link_monitor_task())

    bot.get_status.assert_not_called()
    assert mod.state.last_alert_time is None


def test_link_status_fields_and_healthy(link_monitor):
    """link_status() 字段完整，且 healthy 在三种状态下的取值正确。"""
    mod = link_monitor["mod"]
    mod.reset_state()
    expected_keys = {
        "enabled",
        "connected",
        "bot_self_id",
        "connected_seconds",
        "last_event_seconds_ago",
        "last_probe_ok",
        "last_probe_seconds_ago",
        "timeout",
        "healthy",
    }

    # ① 连接 + 事件新鲜 → healthy True
    mod.state.connected = True
    mod.state.bot_self_id = "123456"
    mod.state.connected_since = time.time()
    mod.state.last_event_time = time.time()
    status = mod.link_status()
    assert set(status) == expected_keys
    assert status["enabled"] is True
    assert status["connected"] is True
    assert status["healthy"] is True
    assert status["connected_seconds"] is not None
    assert status["last_event_seconds_ago"] is not None
    assert status["timeout"] == LINK_MONITOR_TIMEOUT

    # ② 连接 + 事件超时 + 最近探活成功 → healthy True
    mod.state.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 10
    mod.state.last_probe_ok = True
    mod.state.last_probe_time = time.time()
    assert mod.link_status()["healthy"] is True

    # ③ 未连接 → healthy False
    mod.state.connected = False
    assert mod.link_status()["healthy"] is False
