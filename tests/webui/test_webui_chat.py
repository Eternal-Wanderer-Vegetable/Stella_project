# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""WebChat 隔离测试（方案 §14）：虚拟群不入白名单、空间隔离、审计与落库。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webui import chat_ingress

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


def test_virtual_group_negative_and_outside_whitelist():
    assert chat_ingress.WEBCHAT_GROUP_ID < 0  # QQ 群号恒为正
    import config.settings as settings

    assert chat_ingress.WEBCHAT_GROUP_ID not in settings.ALLOWED_GROUPS


def test_ensure_webchat_space_creates_toml(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
):
    from config import spaces as spaces_mod
    from webui.services.spaces import spaces_dir

    chat_ingress._ensure_webchat_space()
    toml = Path(spaces_dir()) / "webchat.toml"
    assert toml.exists()
    assert "qq_groups = [-1]" in toml.read_text(encoding="utf-8")
    # resolve_space(-1) 命中专属空间
    assert spaces_mod.resolve_space(-1) == "webchat"


def test_run_turn_records_and_uses_pipeline(
    client: TestClient, auth_header: dict, isolated_home: Path, monkeypatch
):
    import config.settings as settings

    memory_db = isolated_home / "memory" / "agent_memory.db"
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DB_PATH", memory_db)
    from memory import pre_processors

    monkeypatch.setattr(pre_processors, "DB_PATH", memory_db)
    import asyncio

    captured = {}

    class FakePipeline:
        async def run(self, ctx):
            captured["group_id"] = ctx.group_id
            captured["space"] = ctx.group_shared_space
            captured["source_kind"] = ctx.source_kind
            captured["message"] = ctx.message
            ctx.lines = ["你好呀"]
            return ctx

    monkeypatch.setattr(chat_ingress, "_resolve_pipeline", lambda: FakePipeline())
    result = asyncio.run(chat_ingress.run_turn("你好", "admin"))
    assert result["lines"] == ["你好呀"]
    assert captured["group_id"] == chat_ingress.WEBCHAT_GROUP_ID
    assert captured["space"] == "webchat"
    assert captured["source_kind"] == "AT_MENTION"
    # 用户消息与 BOT_SELF 回复都落库
    import sqlite3

    import config.settings as settings

    conn = sqlite3.connect(settings.DB_PATH)
    rows = list(conn.execute(
        "SELECT source_kind, content FROM group_messages WHERE group_id = '-1'"
    ))
    conn.close()
    kinds = sorted(k for k, _ in rows)
    assert kinds == ["AT_MENTION", "BOT_SELF"]


def test_chat_endpoints_sse_and_history(
    client: TestClient, auth_header: dict, isolated_home: Path, monkeypatch
):
    import config.settings as settings

    memory_db = isolated_home / "memory" / "agent_memory.db"
    memory_db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DB_PATH", memory_db)
    from memory import pre_processors

    monkeypatch.setattr(pre_processors, "DB_PATH", memory_db)

    class FakePipeline:
        async def run(self, ctx):
            ctx.lines = ["面板回复"]
            return ctx

    monkeypatch.setattr(chat_ingress, "_resolve_pipeline", lambda: FakePipeline())
    resp = client.post("/api/v1/chat", json={"message": "在吗"}, headers=auth_header)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert '"type": "run_started"' in body or '"type":"run_started"' in body
    assert "面板回复" in body
    # 历史可读（含用户消息与 BOT_SELF 回复）
    resp = client.get("/api/v1/chat/messages", headers=auth_header)
    contents = [i["content"] for i in resp.json()["data"]["items"]]
    assert "在吗" in contents and "面板回复" in contents
    # 清空
    resp = client.post("/api/v1/chat/reset", headers=auth_header)
    assert resp.json()["data"]["cleared"] >= 2


def test_chat_standalone_degrades(client: TestClient, auth_header: dict, monkeypatch):
    """独立模式（无 bot 环境）→ SSE error 帧，不是 500。"""
    def boom():
        raise RuntimeError("WebChat 需要 Bot 运行环境")

    monkeypatch.setattr(chat_ingress, "_resolve_pipeline", boom)
    resp = client.post("/api/v1/chat", json={"message": "hi"}, headers=auth_header)
    assert resp.status_code == 200  # SSE 已建立
    assert "需要 Bot 运行环境" in resp.text
    assert '"type": "error"' in resp.text or '"type":"error"' in resp.text


def test_chat_requires_auth(client: TestClient):
    assert client.post("/api/v1/chat", json={"message": "x"}).status_code == 401
    assert client.get("/api/v1/chat/messages").status_code == 401
