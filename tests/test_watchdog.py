# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""NapCat 链路看门狗的单元测试。

extensions.napcat_manager.watchdog 在 import 时就会向 nonebot 注册钩子
（event_preprocessor / driver.on_bot_connect / scheduler.scheduled_job），
而纯测试环境没有 NoneBot 运行时。因此这里先注入桩模块/桩对象再 import：

- nonebot_plugin_apscheduler 整体替换为带 scheduled_job 的桩模块（真实模块
  import 即要求 get_driver，会抛「NoneBot has not been initialized」）；
- nonebot.get_driver / nonebot.get_bot 替换为桩对象，避免「未初始化」异常；
- nonebot.message.event_preprocessor 换成只登记 handler 的桩装饰器。

这样 watchdog 的模块级注册全部落到桩上，测试即可直接调用 watchdog_task /
on_bot_connect 处理器来验证判定逻辑（是否重启、连续次数、心跳刷新）。

注意：extensions/ 不在 coverage 范围（pyproject.toml omit），但看门狗判定逻辑
值得独立测试——它已经让 bot 掉线一整夜（2026-08-14 重启循环）。
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import (
    NAPCAT_WATCHDOG_MAX_RESTARTS,
    NAPCAT_WATCHDOG_RESTART_COOLDOWN,
    NAPCAT_WATCHDOG_TIMEOUT,
)


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
def watchdog(monkeypatch):
    """注入桩后重新 import watchdog 模块，返回模块与注册钩子的上下文。"""
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

    # 4) 清掉可能残留的旧 import，重新加载 watchdog（触发模块级注册）
    monkeypatch.delitem(
        sys.modules, "extensions.napcat_manager.watchdog", raising=False
    )
    mod = importlib.import_module("extensions.napcat_manager.watchdog")

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


def _make_impl():
    """构造记录被调用的外部重启实现，返回 (impl, calls)。"""
    calls: list = []

    def impl() -> None:
        calls.append(time.time())

    return impl, calls


def test_heartbeat_fresh_no_restart(watchdog):
    """心跳未超时：不探查、不重启、连续次数不变化。"""
    mod = watchdog["mod"]
    mod.heartbeat.last_event_time = time.time() + 10
    impl, calls = _make_impl()
    mod.set_restart_impl(impl)

    _run(mod.watchdog_task())

    assert calls == []
    assert mod.restart_state.consecutive == 0


def test_timeout_but_probe_ok_no_restart_and_refresh(watchdog):
    """心跳超时但主动探活成功：判定链路正常，不重启且刷新心跳。"""
    mod = watchdog["mod"]
    mod.heartbeat.last_event_time = time.time() - NAPCAT_WATCHDOG_TIMEOUT - 10
    impl, calls = _make_impl()
    mod.set_restart_impl(impl)

    before = time.time()
    _run(mod.watchdog_task())
    after = time.time()

    assert calls == []
    assert mod.restart_state.consecutive == 0
    # 探活成功后把心跳拨回到当前时刻
    assert before <= mod.heartbeat.last_event_time <= after


def test_timeout_probe_fail_restarts_and_increments(watchdog):
    """心跳超时且探活失败：外部重启一次，consecutive 递增并进入冷却。"""
    bot = watchdog["bot"]
    mod = watchdog["mod"]
    bot.get_status.side_effect = RuntimeError("网络不可达")
    mod.heartbeat.last_event_time = time.time() - NAPCAT_WATCHDOG_TIMEOUT - 10
    impl, calls = _make_impl()
    mod.set_restart_impl(impl)

    before = time.time()
    _run(mod.watchdog_task())
    after = time.time()

    assert len(calls) == 1
    assert mod.restart_state.consecutive == 1
    # 重启后心跳拨后冷却秒数，避免恢复期间反复触发
    assert before + NAPCAT_WATCHDOG_RESTART_COOLDOWN <= mod.heartbeat.last_event_time
    assert mod.heartbeat.last_event_time <= after + NAPCAT_WATCHDOG_RESTART_COOLDOWN


def test_max_restarts_reached_stops(watchdog):
    """连续重启达上限：不再重启，仅保留错误日志所需的字段状态。"""
    bot = watchdog["bot"]
    mod = watchdog["mod"]
    bot.get_status.side_effect = RuntimeError("网络不可达")
    mod.heartbeat.last_event_time = time.time() - NAPCAT_WATCHDOG_TIMEOUT - 10
    mod.restart_state.consecutive = NAPCAT_WATCHDOG_MAX_RESTARTS
    impl, calls = _make_impl()
    mod.set_restart_impl(impl)

    _run(mod.watchdog_task())

    assert calls == []
    assert mod.restart_state.consecutive == NAPCAT_WATCHDOG_MAX_RESTARTS


def test_on_bot_connect_resets_heartbeat_and_counter(watchdog):
    """bot 连接建立：心跳视为健康、连续重启计数清零。"""
    mod = watchdog["mod"]
    mod.heartbeat.last_event_time = time.time() - NAPCAT_WATCHDOG_TIMEOUT - 10
    mod.restart_state.consecutive = 5

    handler = watchdog["driver"].on_connect[0]
    _run(handler(watchdog["bot"]))

    assert mod.restart_state.consecutive == 0
    assert mod.heartbeat.last_event_time >= time.time() - 1


def test_any_event_refreshes_heartbeat(watchdog):
    """event_preprocessor 注册的处理器：任何事件都刷新心跳（不只是消息）。"""
    mod = watchdog["mod"]
    mod.heartbeat.last_event_time = time.time() - 100

    handlers = watchdog["preprocess_handlers"]
    assert handlers, "event_preprocessor 应已注册 _refresh_on_any_event"
    for handler in handlers:
        _run(handler())

    assert mod.heartbeat.last_event_time >= time.time() - 1
