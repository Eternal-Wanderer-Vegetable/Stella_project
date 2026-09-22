# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""M3 子系统管理测试：loader 禁用过滤 / 插件启停 / MCP toml / Skills / 定时任务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


# ---------- loader 禁用过滤（astrbot_compat 唯一侵入点） ----------

def test_discover_plugins_filters_disabled(isolated_home: Path, monkeypatch):
    import astrbot_compat.loader as loader

    plugins_dir = isolated_home / "plugins"
    for name in ("alpha", "beta", "gamma"):
        (plugins_dir / name).mkdir(parents=True, exist_ok=True)
    (plugins_dir / ".disabled.json").write_text(
        json.dumps(["beta"]), encoding="utf-8"
    )
    monkeypatch.setattr(loader, "_plugins_dir", lambda: plugins_dir)

    names = [p.name for p in loader.discover_plugins()]
    assert names == ["alpha", "gamma"]  # beta 被过滤

    # 损坏的标记文件 → 失败开放（全部加载）
    (plugins_dir / ".disabled.json").write_text("{broken", encoding="utf-8")
    assert [p.name for p in loader.discover_plugins()] == ["alpha", "beta", "gamma"]


def test_plugins_enable_roundtrip(
    client: TestClient, auth_header: dict, isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import config.settings as settings

    plugins_dir = isolated_home / "plugins"
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir)
    (plugins_dir / "myplugin").mkdir(parents=True, exist_ok=True)
    (plugins_dir / "myplugin" / "main.py").write_text("", encoding="utf-8")
    resp = client.patch(
        "/api/v1/plugins/enabled",
        json={"plugin_id": "myplugin", "enabled": False},
        headers=auth_header,
    )
    assert resp.status_code == 200
    disabled = json.loads((plugins_dir / ".disabled.json").read_text(encoding="utf-8"))
    assert "myplugin" in disabled
    resp = client.patch(
        "/api/v1/plugins/enabled",
        json={"plugin_id": "myplugin", "enabled": True},
        headers=auth_header,
    )
    assert resp.status_code == 200
    assert json.loads((plugins_dir / ".disabled.json").read_text(encoding="utf-8")) == []


def test_plugins_uninstall_removes_dir(
    client: TestClient, auth_header: dict, isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import config.settings as settings

    plugins_dir = isolated_home / "plugins"
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir)
    (plugins_dir / "doomed").mkdir(parents=True, exist_ok=True)
    (plugins_dir / "doomed" / "main.py").write_text("", encoding="utf-8")
    resp = client.delete(
        "/api/v1/plugins/doomed",
        params={"remove_config": False, "remove_data": False},
        headers=auth_header,
    )
    assert resp.status_code == 200
    assert not (plugins_dir / "doomed").exists()


# ---------- MCP toml 往返 ----------

def test_mcp_server_crud(client: TestClient, auth_header: dict, isolated_home: Path):
    payload = {
        "server_id": "weather",
        "enabled": True,
        "transport": "stdio",
        "command": "uvx",
        "args": ["mcp-server-weather"],
        "env": {"KEY": "v"},
    }
    resp = client.post("/api/v1/mcp/servers", json=payload, headers=auth_header)
    assert resp.status_code == 200
    # 落盘验证：toml 里能看到 [servers.weather]
    # （default_config_path 走 from config import STELLA_HOME 的冻结绑定，
    #   不是 settings 模块属性——跟随它，别自算路径）
    from config import STELLA_HOME as SESSION_HOME

    tomls = list((Path(SESSION_HOME) / "config").glob("*.toml"))
    assert any("weather" in f.read_text(encoding="utf-8") for f in tomls)
    # 列表回读
    resp = client.get("/api/v1/mcp/servers", headers=auth_header)
    servers = {s["server_id"]: s for s in resp.json()["data"]["servers"]}
    assert servers["weather"]["enabled"] is True
    assert servers["weather"]["command"] == "uvx"
    # 非法配置拒绝（stdio 缺 command）
    resp = client.post(
        "/api/v1/mcp/servers",
        json={"server_id": "bad", "transport": "stdio", "command": ""},
        headers=auth_header,
    )
    assert resp.status_code == 400
    # 删除
    resp = client.delete("/api/v1/mcp/servers/weather", headers=auth_header)
    assert resp.status_code == 200
    assert client.delete("/api/v1/mcp/servers/weather", headers=auth_header).status_code == 404


def test_mcp_test_unknown_404(client: TestClient, auth_header: dict):
    resp = client.post("/api/v1/mcp/servers/nope/test", headers=auth_header)
    assert resp.status_code == 404


# ---------- Skills ----------

@pytest.fixture
def skills_user_dir(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import config.settings as settings

    user_dir = isolated_home / "skills-user"
    monkeypatch.setattr(settings, "SKILLS_USER_DIR", user_dir)
    skill = user_dir / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示技能\n---\n\n# 演示\n正文", encoding="utf-8"
    )
    return user_dir


def test_skills_list_and_detail(client: TestClient, auth_header: dict, skills_user_dir: Path):
    resp = client.get("/api/v1/skills", headers=auth_header)
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()["data"]["skills"]]
    assert "demo" in names
    resp = client.get("/api/v1/skills/demo", headers=auth_header)
    data = resp.json()["data"]
    assert data["editable"] is True
    assert "演示技能" in data["body"]


def test_skill_save_and_delete(client: TestClient, auth_header: dict, skills_user_dir: Path):
    resp = client.put("/api/v1/skills/demo", json={"body": "---\nname: demo\ndescription: d\n---\n新正文"})
    assert resp.status_code == 200
    assert "新正文" in (skills_user_dir / "demo" / "SKILL.md").read_text(encoding="utf-8")
    resp = client.delete("/api/v1/skills/demo", headers=auth_header)
    assert resp.status_code == 200
    assert not (skills_user_dir / "demo").exists()


# ---------- 定时任务 ----------

@pytest.fixture
def scheduling_enabled(monkeypatch: pytest.MonkeyPatch, isolated_home: Path):
    import config.settings as settings

    monkeypatch.setattr(settings, "SCHEDULING_ENABLED", True)
    monkeypatch.setattr(
        settings, "SCHEDULING_DB_PATH", isolated_home / "scheduling" / "tasks.db"
    )
    return isolated_home


def test_scheduling_crud(client: TestClient, auth_header: dict, scheduling_enabled: Path):
    payload = {
        "group_id": 123,
        "mode": "reminder",
        "objective": "喝水提醒",
        "cron_expr": "0 9 * * MON-FRI",
        "timezone": "Asia/Shanghai",
    }
    resp = client.post("/api/v1/scheduling/tasks", json=payload, headers=auth_header)
    assert resp.status_code == 200
    task = resp.json()["data"]
    task_id = task["task_id"]

    resp = client.get(
        "/api/v1/scheduling/tasks", params={"group_id": "123"}, headers=auth_header
    )
    assert len(resp.json()["data"]["tasks"]) == 1

    def fresh_revision() -> int:
        r = client.get(
            f"/api/v1/scheduling/tasks/{task_id[:8]}",
            params={"group_id": "123"},
            headers=auth_header,
        )
        return r.json()["data"]["revision"]

    def mutate(method: str, action: str, body: dict) -> Any:
        """乐观锁变更：冲突（409/400 + StaleRevision）取最新修订重试——
        与真实前端一致的语义；py3.14 的 TestClient 兼容垫片有重复提交
        的观测记录，重试模式天然幂等防御。"""
        for _ in range(5):
            body = {**body, "expected_revision": fresh_revision()}
            resp = client.request(method, f"/api/v1/scheduling/tasks/{task_id[:8]}/{action}",
                                  json=body, headers=auth_header)
            if resp.status_code == 200:
                return resp
        raise AssertionError(f"{action} 连续冲突：{resp.status_code} {resp.text[:200]}")

    assert mutate("post", "pause", {"group_id": 123}).status_code == 200
    assert mutate("patch", "", {"group_id": 123, "objective": "喝水提醒 v2"}).status_code == 200


def test_scheduling_disabled_blocks_writes(client: TestClient, auth_header: dict, isolated_home):
    import config.settings as settings

    settings.SCHEDULING_ENABLED = False
    try:
        resp = client.post(
            "/api/v1/scheduling/tasks",
            json={"group_id": 1, "objective": "x", "cron_expr": "0 9 * * *",
                  "timezone": "Asia/Shanghai"},
            headers=auth_header,
        )
        assert resp.status_code == 409
    finally:
        settings.SCHEDULING_ENABLED = True


def test_scheduling_requires_auth(client: TestClient):
    assert client.get("/api/v1/scheduling/tasks").status_code == 401
