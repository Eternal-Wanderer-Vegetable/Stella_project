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
        "usage": None,
        # capability_view.collect() 读的就是这个键：不在的话它会退到磁盘声明分支，
        # 于是「测 live 渲染」的用例悄悄变成「测 offline 渲染」
        "capabilities": None,
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


def test_migrate_subcommand_is_registered(capsys):
    """升级路径的四个子命令必须在 CLI 里存在——GUI 与 start.bat 都靠它们。"""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.suppress(SystemExit):
        deploy_main.main(["--help"])
    helptext = buffer.getvalue()
    for command in ("migrate", "space-merge", "manifest", "paths", "capabilities"):
        assert command in helptext, command


def test_paths_env_file_prints_single_path(capsys):
    """start.bat 靠 `paths --env-file` 判断配置过没有：必须只输出一行路径。"""
    rc = deploy_main._cmd_paths(argparse.Namespace(json=False, env_file=True))
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert len(out) == 1
    assert out[0].endswith(".env")


def test_paths_json_exposes_both_roots(capsys):
    """GUI 靠这份 JSON 找用户数据目录，两个根目录都必须在。"""
    import json

    rc = deploy_main._cmd_paths(argparse.Namespace(json=True, env_file=False))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["project_root"] and data["stella_home"]
    assert data["stella_home_source"]
    assert data["db_path"].endswith("agent_memory.db")


def _fake_capabilities() -> dict:
    """状态接口 ``capabilities`` 块的最小形状：一条可路由 + 一条未声明的插件工具。

    手写而不是现算一份 ``snapshot()``：这几个用例测的是 CLI 的**取数与退出码**，
    真实快照的字段语义由 tests/test_capability_query.py 钉住，两处不必重叠。
    """
    def _provider(tool: str) -> dict:
        return {
            "tool": tool,
            "kind": "astrbot_tool",
            "enabled": True,
            "available": True,
            "failures": 0,
            "backoff_seconds": 0,
            "tool_state": "ok",
        }

    return {
        "version": 1,
        "registry_version": 7,
        "total": 2,
        "routable": 1,
        "declared": 1,
        "auto": 1,
        "auto_unrouted": 1,
        "tools_known": True,
        "items": [
            {
                "id": "weather.query",
                "domain": "information",
                "source": "config",
                "route_enabled": True,
                "routable": True,
                "auto": False,
                "examples": 4,
                "keywords": 0,
                "providers": [_provider("get_weather")],
            },
            {
                "id": "tool.orphan",
                "domain": "plugin",
                "source": "auto",
                "route_enabled": True,
                "routable": False,
                "auto": True,
                "examples": 0,
                "keywords": 0,
                "providers": [_provider("orphan")],
            },
        ],
        "commands": [],
        "missing_tools": [],
    }


def test_cmd_capabilities_renders_the_live_snapshot(monkeypatch, capsys):
    """接口给了 capabilities 就用它，可路由与不可路由分两张表。"""
    fake = _fake_status(capabilities=_fake_capabilities())
    monkeypatch.setattr(deploy_main.process, "status", lambda: fake)
    rc = deploy_main._cmd_capabilities(argparse.Namespace(json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "可被聊天自动触发（1）" in out
    assert "不参与路由（1）" in out
    assert "weather.query" in out
    assert "无能力声明（自动派生）" in out
    # 「只是文件内容」那段免责声明是离线分支专有的，live 分支出现它就是走错了分支
    assert "只是文件内容" not in out


def test_cmd_capabilities_json_branch(monkeypatch, capsys):
    """GUI 读的是这一份：source 明说数据来自哪边，capabilities 原样透传。"""
    import json

    caps = _fake_capabilities()
    monkeypatch.setattr(
        deploy_main.process, "status", lambda: _fake_status(capabilities=caps)
    )
    rc = deploy_main._cmd_capabilities(argparse.Namespace(json=True))
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["source"] == "live"
    assert data["api_reachable"] is True
    assert data["capabilities"] == caps
    assert data["declarations"] is None


def test_cmd_capabilities_offline_still_exits_zero(monkeypatch, capsys):
    """Bot 没运行是一种合法状态，不是失败。

    退出码非零会让 CI 与 GUI 把「新装的实例还没启动」当故障处理；这条查询命令的
    退出码恒为 0（见 _cmd_capabilities 的 docstring）。
    """
    monkeypatch.setattr(
        deploy_main.process,
        "status",
        lambda: _fake_status(alive=False, api_reachable=False, capabilities=None),
    )
    rc = deploy_main._cmd_capabilities(argparse.Namespace(json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Stella 未在运行" in out
    # 离线分支必须先说清它回答不了「到底可不可路由」
    assert "只是文件内容" in out
