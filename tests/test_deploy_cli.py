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
from deploy import control_client


def test_fmt_secs_none():
    assert deploy_main._fmt_secs(None) == "—"


def test_fmt_secs_units():
    assert deploy_main._fmt_secs(30) == "30 秒"
    assert deploy_main._fmt_secs(300) == "5 分钟"
    assert deploy_main._fmt_secs(7200) == "2.0 小时"


def _fake_status(**overrides) -> dict:
    data = {
        "ok": True,
        "controller_reachable": True,
        "controller_failed": False,
        "pid": 18432,
        "public_base_url": "http://127.0.0.1:8080",
        "webui_enabled": True,
        "core": {"phase": "ready", "error": None},
        "error": None,
    }
    data.update(overrides)
    return data


def _run_status(monkeypatch, capsys, fake: dict):
    monkeypatch.setattr(control_client, "status", lambda: fake)
    rc = deploy_main._cmd_status(argparse.Namespace(json=False))
    out = capsys.readouterr().out
    return rc, out


def test_cmd_status_reports_live_corona_and_nucleus(monkeypatch, capsys):
    """Status reports the authenticated Corona owner and its separate core phase."""
    fake = _fake_status()
    rc, out = _run_status(monkeypatch, capsys, fake)
    assert rc == 0
    assert "Corona 管理面在线（Corona PID 18432）" in out
    assert "Nucleus 阶段：ready" in out
    assert "http://127.0.0.1:8080" in out


def test_cmd_status_reports_unreachable_owner_failure(monkeypatch, capsys):
    fake = _fake_status(
        ok=False,
        controller_reachable=False,
        controller_failed=True,
        error={"message": "controller_unreachable"},
    )
    rc, out = _run_status(monkeypatch, capsys, fake)
    assert rc == 1
    assert "Corona 控制器状态不可用" in out
    assert "controller_unreachable" in out


def test_cmd_status_reports_stopped_owner_as_success(monkeypatch, capsys):
    fake = _fake_status(
        controller_reachable=False,
        controller_failed=False,
        pid=None,
        public_base_url=None,
        core=None,
    )
    rc, out = _run_status(monkeypatch, capsys, fake)
    assert rc == 0
    assert "Corona 与 Nucleus 均未运行" in out


def test_cmd_status_json_branch(monkeypatch, capsys):
    fake = _fake_status()
    monkeypatch.setattr(control_client, "status", lambda: fake)
    rc = deploy_main._cmd_status(argparse.Namespace(json=True))
    out = capsys.readouterr().out
    assert rc == 0
    assert '"controller_reachable": true' in out
    assert '"phase": "ready"' in out


def test_migrate_subcommand_is_registered(capsys):
    """升级路径的四个子命令必须在 CLI 里存在——GUI 与 start.bat 都靠它们。"""
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.suppress(SystemExit):
        deploy_main.main(["--help"])
    helptext = buffer.getvalue()
    for command in (
        "migrate",
        "space-merge",
        "manifest",
        "paths",
        "capabilities",
        "packages",
        "runtime",
    ):
        assert command in helptext, command


def test_paths_env_file_prints_single_path(capsys):
    """start.bat 靠 `paths --env-file` 判断配置过没有：必须只输出一行路径。"""
    rc = deploy_main.main(["paths", "--env-file"])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0
    assert len(out) == 1
    assert out[0].endswith(".env")


def test_paths_json_exposes_both_roots(capsys):
    """GUI 靠这份 JSON 找用户数据目录，两个根目录都必须在。"""
    import json

    rc = deploy_main.main(["paths", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["project_root"] and data["stella_home"]
    assert data["stella_home_source"]
    assert data["db_path"].endswith("agent_memory.db")
    assert data["instance_id"]
    assert data["instance_runtime_dir"]
    assert data["instance_pid_file"]


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
    from deploy import capability_view
    from deploy.capability_view import CapabilityView

    view = CapabilityView(live=_fake_capabilities(), offline=None, api_reachable=True)
    monkeypatch.setattr(capability_view, "collect", lambda: view)
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

    from deploy import capability_view
    from deploy.capability_view import CapabilityView

    caps = _fake_capabilities()
    view = CapabilityView(live=caps, offline=None, api_reachable=True)
    monkeypatch.setattr(capability_view, "collect", lambda: view)
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
    from deploy import capability_view
    from deploy.capability_view import CapabilityView

    view = CapabilityView(live=None, offline={"files": [], "drafts": []}, api_reachable=False)
    monkeypatch.setattr(capability_view, "collect", lambda: view)
    rc = deploy_main._cmd_capabilities(argparse.Namespace(json=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Stella 未在运行" in out
    # 离线分支必须先说清它回答不了「到底可不可路由」
    assert "只是文件内容" in out
