# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""deploy CLI（deploy/__main__.py）的格式化与输出分支测试。

锁住的缺陷：link_status() 里 connected_seconds / last_event_seconds_ago 在未连接时
是显式的 None（键存在、值为 None），dict.get(key, 0) 的默认值不会生效，直接进
:.0f 会 TypeError。2026-08-19 实测：未连 NapCat 时 `deploy status` 必崩。
"""

from __future__ import annotations

import argparse

from deploy import __main__ as deploy_main


def test_fmt_secs_none():
    assert deploy_main._fmt_secs(None) == "—"


def test_fmt_secs_units():
    assert deploy_main._fmt_secs(30) == "30 秒"
    assert deploy_main._fmt_secs(300) == "5 分钟"
    assert deploy_main._fmt_secs(7200) == "2.0 小时"


def _fake_status(link: dict | None = None, **overrides) -> dict:
    data = {
        "pid": 18432,
        "alive": True,
        "pid_file_present": True,
        "api_reachable": True,
        "log_file": "logs/stella.jsonl",
        "recent_log": None,
        "link": link,
        "scheduler": {},
        "uptime_seconds": 4127.5,
        "note": "test",
    }
    data.update(overrides)
    return data


def _run_status(monkeypatch, capsys, fake: dict):
    monkeypatch.setattr(deploy_main.process, "status", lambda: fake)
    rc = deploy_main._cmd_status(argparse.Namespace(json=False))
    out = capsys.readouterr().out
    return rc, out


def test_cmd_status_link_disconnected_no_crash(monkeypatch, capsys):
    """未连接时所有可空字段为 None，打印不崩且给出可操作提示。"""
    fake = _fake_status(
        link={
            "enabled": True,
            "connected": False,
            "bot_self_id": None,
            "connected_seconds": None,
            "last_event_seconds_ago": None,
            "last_probe_ok": None,
            "last_probe_seconds_ago": None,
            "timeout": 300,
            "healthy": False,
        }
    )
    rc, out = _run_status(monkeypatch, capsys, fake)
    assert rc == 0
    assert "协议端未连接" in out
    assert "检查 NapCat 是否运行并已登录" in out
    assert "链路：健康" not in out


def test_cmd_status_link_connected(monkeypatch, capsys):
    fake = _fake_status(
        link={
            "enabled": True,
            "connected": True,
            "bot_self_id": "3213194821",
            "connected_seconds": 4127.5,
            "last_event_seconds_ago": 12.3,
            "last_probe_ok": None,
            "last_probe_seconds_ago": None,
            "timeout": 300,
            "healthy": True,
        }
    )
    rc, out = _run_status(monkeypatch, capsys, fake)
    assert rc == 0
    assert "链路：健康" in out
    assert "QQ 3213194821" in out
    assert "已连接 1.1 小时" in out
    assert "12 秒前" in out


def test_cmd_status_link_disabled(monkeypatch, capsys):
    fake = _fake_status(
        link={
            "enabled": False,
            "connected": False,
            "bot_self_id": None,
            "connected_seconds": None,
            "last_event_seconds_ago": None,
            "last_probe_ok": None,
            "last_probe_seconds_ago": None,
            "timeout": 300,
            "healthy": False,
        }
    )
    rc, out = _run_status(monkeypatch, capsys, fake)
    assert rc == 0
    assert "链路监测已关闭" in out


def test_cmd_status_json_branch(monkeypatch, capsys):
    fake = _fake_status(link=None)
    monkeypatch.setattr(deploy_main.process, "status", lambda: fake)
    rc = deploy_main._cmd_status(argparse.Namespace(json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert '"alive": true' in out
    assert '"link": null' in out
