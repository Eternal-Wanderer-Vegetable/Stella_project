# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebUI 重启服务的三形态语义（方案 §4 D7 的无壳补全）。

- 桌面壳（注入秘钥）：写哨兵，壳负责拉起；
- 无壳（python bot.py 直启）：先派接任进程再写哨兵——顺序不能反，派生
  失败绝不能写哨兵（否则站点直接失联，2026-09-24 实测）；
- 派生失败：不停止、如实报错，Bot 保持可用。
"""

from __future__ import annotations

from core import stop_signal
from webui import security
from webui.services import system


def _sentinel_written() -> bool:
    return stop_signal.is_stop_requested()


def _clear_sentinel() -> None:
    stop_signal.clear_stop_request()


def test_restart_desktop_mode_writes_sentinel(monkeypatch):
    monkeypatch.setattr(security, "desktop_session_secret", lambda: "secret")
    _clear_sentinel()
    try:
        data = system.restart()
        assert data["ok"] is True
        assert data["restart_mode"] == "desktop"
        assert _sentinel_written(), "壳形态必须写哨兵（壳监听退出自动拉起）"
    finally:
        _clear_sentinel()


def test_restart_shellless_spawns_successor_then_sentinel(monkeypatch):
    """无壳形态：接任进程先就位、哨兵后写——顺序反了接任方就抢不到端口时机。"""
    from core import self_restart

    monkeypatch.setattr(security, "desktop_session_secret", lambda: None)
    calls: list[str] = []

    def fake_spawn():
        calls.append("spawn")
        return {"spawned": True, "pid": 424242}

    real_request_stop = stop_signal.request_stop

    def spy_request_stop(reason: str = "") -> None:
        calls.append("stop")
        real_request_stop(reason=reason)

    monkeypatch.setattr(self_restart, "spawn_successor", fake_spawn)
    monkeypatch.setattr(stop_signal, "request_stop", spy_request_stop)
    _clear_sentinel()
    try:
        data = system.restart()
        assert data["ok"] is True
        assert data["restart_mode"] == "self"
        assert data["successor_pid"] == 424242
        assert calls == ["spawn", "stop"], "必须先派接任进程再请求停止"
        assert _sentinel_written()
    finally:
        _clear_sentinel()


def test_restart_spawn_failure_keeps_bot_running(monkeypatch):
    """派生失败：不写哨兵（Bot 保持运行），ok=False 带原因交前端展示。"""
    from core import self_restart

    monkeypatch.setattr(security, "desktop_session_secret", lambda: None)

    def refuse_spawn():
        return {"spawned": False, "error": "当前入口不是 bot.py"}

    def forbidden_stop(reason: str = "") -> None:
        raise AssertionError("派生失败后绝不能请求停止——那会让站点失联")

    monkeypatch.setattr(self_restart, "spawn_successor", refuse_spawn)
    monkeypatch.setattr(stop_signal, "request_stop", forbidden_stop)
    _clear_sentinel()
    data = system.restart()
    assert data["ok"] is False
    assert "bot.py" in (data.get("error") or "")
    assert data["restart_mode"] == "manual"
    assert not _sentinel_written()
