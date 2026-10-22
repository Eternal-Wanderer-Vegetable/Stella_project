# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Isolated checks for adapter-specific and per-Bot link health."""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from unittest.mock import AsyncMock

import pytest

from config import LINK_MONITOR_TIMEOUT


class _StubScheduler:
    def __init__(self) -> None:
        self.jobs: list = []

    def scheduled_job(self, *args, **kwargs):
        def _deco(func):
            self.jobs.append(func)
            return func

        return _deco


class _StubDriver:
    def __init__(self) -> None:
        self.on_connect: list = []
        self.on_disconnect: list = []
        self.config = types.SimpleNamespace(host="127.0.0.1", port=8080)

    def on_bot_connect(self, func):
        self.on_connect.append(func)
        return func

    def on_bot_disconnect(self, func):
        self.on_disconnect.append(func)
        return func


class _Adapter:
    def __init__(self, name: str) -> None:
        self.name = name

    def get_name(self) -> str:
        return self.name


class _Bot:
    def __init__(self, adapter: str, self_id: str) -> None:
        self.adapter = _Adapter(adapter)
        self.self_id = self_id
        self.get_status = AsyncMock(return_value={})


@pytest.fixture
def link_monitor(monkeypatch):
    import nonebot
    import nonebot.message

    scheduler = _StubScheduler()
    stub_module = types.ModuleType("nonebot_plugin_apscheduler")
    stub_module.scheduler = scheduler
    monkeypatch.setitem(sys.modules, "nonebot_plugin_apscheduler", stub_module)

    handlers: list = []
    monkeypatch.setattr(
        nonebot.message,
        "event_preprocessor",
        lambda func: handlers.append(func) or func,
    )

    driver = _StubDriver()
    adapters: dict = {}
    bots: dict = {}
    monkeypatch.setattr(nonebot, "get_driver", lambda: driver)
    monkeypatch.setattr(nonebot, "get_adapters", lambda: adapters)
    monkeypatch.setattr(nonebot, "get_bots", lambda: bots)
    monkeypatch.delitem(sys.modules, "extensions.link_monitor", raising=False)
    mod = importlib.import_module("extensions.link_monitor")

    return {
        "mod": mod,
        "scheduler": scheduler,
        "driver": driver,
        "adapters": adapters,
        "bots": bots,
        "handlers": handlers,
    }


def _run(coro) -> None:
    asyncio.run(coro)


def test_event_preprocessor_signature_is_supported_by_nonebot_di(link_monitor):
    from nonebot.dependencies import Dependent
    from nonebot.message import EVENT_PCS_PARAMS

    Dependent.parse(
        call=link_monitor["handlers"][0],
        allow_types=EVENT_PCS_PARAMS,
    )


def test_bot_lifecycle_signatures_are_supported_by_nonebot_di(link_monitor):
    from nonebot.dependencies import Dependent
    from nonebot.internal.driver.abstract import BOT_HOOK_PARAMS

    for handler in (*link_monitor["driver"].on_connect, *link_monitor["driver"].on_disconnect):
        Dependent.parse(call=handler, allow_types=BOT_HOOK_PARAMS)


def _bot(link_monitor, adapter: str = "OneBot V11", self_id: str = "1") -> _Bot:
    bot = _Bot(adapter, self_id)
    link_monitor["adapters"][adapter] = object()
    link_monitor["bots"][self_id] = bot
    return bot


def test_only_onebot_events_refresh_heartbeat(link_monitor):
    mod = link_monitor["mod"]
    handler = link_monitor["handlers"][0]
    onebot = _Bot("OneBot V11", "one")
    telegram = _Bot("Telegram", "tg")

    mod.state.bots[("OneBot V11", "one")] = mod._BotState(
        adapter="OneBot V11", self_id="one", last_event_time=time.time() - 100
    )
    mod.state.bots[("Telegram", "tg")] = mod._BotState(
        adapter="Telegram", self_id="tg", last_event_time=time.time() - 100
    )
    _run(handler(bot=onebot, event=object()))
    _run(handler(bot=telegram, event=object()))

    assert mod.state.bots[("OneBot V11", "one")].last_event_time > time.time() - 1
    assert mod.state.bots[("Telegram", "tg")].last_event_time < time.time() - 90


def test_fresh_event_no_probe(link_monitor):
    bot = _bot(link_monitor)
    mod = link_monitor["mod"]
    _run(link_monitor["handlers"][0](bot=bot, event=object()))

    _run(mod.link_monitor_task())

    bot.get_status.assert_not_awaited()


def test_stale_bots_are_probed_independently(link_monitor):
    fresh = _bot(link_monitor, self_id="fresh")
    stale = _bot(link_monitor, self_id="stale")
    mod = link_monitor["mod"]
    now = time.time()
    mod.state.bots[("OneBot V11", "fresh")] = mod._BotState(
        adapter="OneBot V11", self_id="fresh", connected=True,
        connected_since=now, last_event_time=now,
    )
    stale_state = mod._BotState(
        adapter="OneBot V11", self_id="stale", connected=True,
        connected_since=now - 200, last_event_time=now - LINK_MONITOR_TIMEOUT - 10,
    )
    mod.state.bots[("OneBot V11", "stale")] = stale_state
    stale.get_status.side_effect = RuntimeError("network unavailable")

    _run(mod.link_monitor_task())
    status = mod.link_status()

    fresh.get_status.assert_not_awaited()
    stale.get_status.assert_awaited_once()
    assert stale_state.last_probe_ok is False
    assert status["healthy"] is False
    assert len(status["bots"]) == 2
    assert {item["connected"] for item in status["bots"]} == {True}
    assert len({item["instance_ref"] for item in status["bots"]}) == 2
    assert all("self_id" not in item for item in status["bots"])


def test_disconnect_changes_only_that_bot(link_monitor):
    disconnected = _bot(link_monitor, self_id="a")
    connected = _bot(link_monitor, self_id="b")
    mod = link_monitor["mod"]
    _run(mod._on_bot_connect(disconnected))
    _run(mod._on_bot_connect(connected))
    link_monitor["bots"].pop("a")
    _run(mod._on_bot_disconnect(disconnected))

    status = mod.link_status()
    by_ref = {item["instance_ref"]: item for item in status["bots"]}
    first = mod.state.bots[("OneBot V11", "a")]
    second = mod.state.bots[("OneBot V11", "b")]
    assert by_ref[first.instance_ref]["connected"] is False
    assert by_ref[second.instance_ref]["connected"] is True
    assert status["connected"] is True
    assert status["healthy"] is False


def test_non_onebot_adapter_is_not_reported_as_disconnected(link_monitor):
    telegram = _bot(link_monitor, "Telegram", "tg-1")
    mod = link_monitor["mod"]

    _run(mod.link_monitor_task())
    status = mod.link_status()

    telegram.get_status.assert_not_awaited()
    assert status["enabled"] is False
    assert status["applicable"] is False
    assert status["connected"] is None
    assert status["healthy"] is None
    assert status["waiting_for_reconnect"] is False
    assert status["connections"] == [
        {
            "adapter": "Telegram",
            "instance_ref": status["connections"][0]["instance_ref"],
            "connected": True,
            "health": None,
        }
    ]
    assert "tg-1" not in repr(status["connections"])


def test_configured_onebot_without_connected_bot_alerts(link_monitor):
    link_monitor["adapters"]["OneBot V11"] = object()
    mod = link_monitor["mod"]

    _run(mod.link_monitor_task())
    status = mod.link_status()

    assert mod.state.no_bot_alert_time is not None
    assert status["applicable"] is True
    assert status["enabled"] is True
    assert status["connected"] is False
    assert status["healthy"] is False
    assert status["waiting_for_reconnect"] is True


def test_connect_without_any_event_alerts_after_timeout(link_monitor):
    bot = _bot(link_monitor)
    mod = link_monitor["mod"]
    _run(mod._on_bot_connect(bot))
    record = mod.state.bots[("OneBot V11", bot.self_id)]
    record.connected_since = time.time() - LINK_MONITOR_TIMEOUT - 2
    record.last_event_time = None

    _run(mod.link_monitor_task())

    assert record.last_alert_time is not None
    bot.get_status.assert_not_awaited()


def test_alerts_are_throttled_per_bot(link_monitor):
    bot = _bot(link_monitor)
    mod = link_monitor["mod"]
    record = mod._state_for(bot)
    record.connected = True
    record.connected_since = time.time() - LINK_MONITOR_TIMEOUT - 5
    record.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 5
    bot.get_status.side_effect = RuntimeError("network unavailable")

    _run(mod.link_monitor_task())
    first_alert = record.last_alert_time
    _run(mod.link_monitor_task())

    assert first_alert is not None
    assert record.last_alert_time == first_alert
    # A failed active probe is backoff fenced; the next scheduler tick does not
    # amplify a single dependency failure into another request.
    assert bot.get_status.await_count == 1


def test_disabled_monitor_does_not_probe_or_alert(link_monitor, monkeypatch):
    bot = _bot(link_monitor)
    mod = link_monitor["mod"]
    monkeypatch.setattr(mod, "LINK_MONITOR_ENABLED", False)
    record = mod._state_for(bot)
    record.connected = True
    record.last_event_time = time.time() - LINK_MONITOR_TIMEOUT - 10

    _run(mod.link_monitor_task())

    bot.get_status.assert_not_awaited()
    assert record.last_alert_time is None


def test_link_status_preserves_legacy_fields_and_adds_multi_adapter_detail(link_monitor):
    bot = _bot(link_monitor)
    mod = link_monitor["mod"]
    _run(mod._on_bot_connect(bot))
    status = mod.link_status()

    legacy_keys = {
        "enabled", "connected", "bot_self_id", "connected_seconds",
        "last_event_seconds_ago", "last_probe_ok", "last_probe_seconds_ago",
        "timeout", "healthy", "mode", "endpoint_configured",
        "forward_reachable", "reverse_port_in_use", "token_configured",
        "token_in_url", "token_consistent", "waiting_for_reconnect",
    }
    assert legacy_keys <= status.keys()
    assert status["enabled"] is True
    assert status["applicable"] is True
    assert status["connected"] is True
    assert status["healthy"] is True
    assert status["bot_self_id"] == "1"
    assert len(status["bots"]) == 1
    assert status["bots"][0]["healthy"] is True
    assert status["connections"][0]["health"] is True


def test_multi_bot_legacy_id_is_not_misleading(link_monitor):
    first = _bot(link_monitor, self_id="1")
    second = _bot(link_monitor, self_id="2")
    mod = link_monitor["mod"]
    _run(mod._on_bot_connect(first))
    _run(mod._on_bot_connect(second))

    status = mod.link_status()

    assert status["bot_self_id"] == ""
    assert status["connected"] is True
    assert status["healthy"] is True
    assert status["last_probe_ok"] is None
    assert len(status["bots"]) == 2
