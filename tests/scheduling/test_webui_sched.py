# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""WebUI scheduling routes bind task creation to an explicit connected Bot."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import nonebot
import pytest
from fastapi.testclient import TestClient

from webui.app import create_webui_app

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def scheduling_webui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "STELLA_HOME", tmp_path)
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    monkeypatch.setattr(settings, "SCHEDULING_ENABLED", True)
    monkeypatch.setattr(settings, "SCHEDULING_DB_PATH", tmp_path / "scheduling" / "tasks.db")
    with TestClient(create_webui_app()) as client:
        setup = client.post("/api/v1/auth/setup", json=USER)
        assert setup.status_code == 200
        auth = {"Authorization": f"Bearer {setup.json()['data']['token']}"}
        yield client, auth


@pytest.fixture
def connected_qq_bot(monkeypatch: pytest.MonkeyPatch):
    bot = SimpleNamespace(
        self_id="10000",
        adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
    )
    monkeypatch.setattr(nonebot, "get_bots", lambda: {bot.self_id: bot})
    return bot


def test_scheduling_crud_requires_and_persists_exact_bot(
    scheduling_webui, connected_qq_bot
):
    client, auth = scheduling_webui
    bots = client.get("/api/v1/scheduling/bots", headers=auth)
    assert bots.status_code == 200
    assert bots.json()["data"]["bots"] == [
        {"bot_id": connected_qq_bot.self_id, "adapter": "OneBot V11"}
    ]

    payload = {
        "bot_id": connected_qq_bot.self_id,
        "group_id": 123,
        "mode": "reminder",
        "objective": "喝水提醒",
        "cron_expr": "0 9 * * MON-FRI",
        "timezone": "Asia/Shanghai",
    }
    unconnected = client.post(
        "/api/v1/scheduling/tasks",
        json={**payload, "bot_id": "99999"},
        headers=auth,
    )
    assert unconnected.status_code == 409

    response = client.post("/api/v1/scheduling/tasks", json=payload, headers=auth)
    assert response.status_code == 200, response.text
    task = response.json()["data"]
    task_id = task["task_id"]
    assert task["bot_id"] == connected_qq_bot.self_id

    listed = client.get(
        "/api/v1/scheduling/tasks", params={"group_id": "123"}, headers=auth
    )
    assert len(listed.json()["data"]["tasks"]) == 1
    assert listed.json()["data"]["tasks"][0]["bot_id"] == connected_qq_bot.self_id

    def fresh_revision() -> int:
        detail = client.get(
            f"/api/v1/scheduling/tasks/{task_id[:8]}",
            params={"group_id": "123"},
            headers=auth,
        )
        return detail.json()["data"]["revision"]

    def mutate(method: str, action: str, body: dict[str, Any]):
        for _ in range(5):
            body = {**body, "expected_revision": fresh_revision()}
            response = client.request(
                method,
                f"/api/v1/scheduling/tasks/{task_id[:8]}/{action}",
                json=body,
                headers=auth,
            )
            if response.status_code == 200:
                return response
        raise AssertionError(f"{action} 连续冲突：{response.status_code} {response.text[:200]}")

    assert mutate("post", "pause", {"group_id": 123}).status_code == 200
    assert mutate(
        "patch", "", {"group_id": 123, "objective": "喝水提醒 v2"}
    ).status_code == 200
