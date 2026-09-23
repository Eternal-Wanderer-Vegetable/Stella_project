# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""doctor 端点契约：退出码非零（有未通过检查项）≠ 传输失败——报告必须结构化返回。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

USER = {"username": "admin", "password": "correct horse battery"}

REPORT = {
    "version": 1,
    "summary": {"ok": 33, "warn": 2, "error": 3, "blocking": True, "total": 38},
    "items": [
        {"id": "env_file", "level": "error", "title": "缺少 .env 配置文件",
         "detail": "项目根目录下没有 .env。", "fix_hint": "python -m deploy init"}
    ],
}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


def test_doctor_parses_report_despite_nonzero_exit(
    client: TestClient, auth_header: dict, isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """deploy doctor 在存在失败项时退出码为 1 但照常打印 JSON——
    服务不得把它当成传输失败丢掉报告（用户实测：设置页只看到退出码报错）。"""
    async def fake_exec(*args, **kwargs):
        class P:
            returncode = 1
            async def communicate(self):
                return (json.dumps(REPORT).encode("utf-8"), b"")
        return P()

    monkeypatch.setattr("webui.services.system.asyncio.create_subprocess_exec", fake_exec)
    resp = client.get("/api/v1/system/doctor", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is False  # 有 error 项 + blocking
    assert data["summary"]["error"] == 3
    assert data["report"]["items"][0]["fix_hint"] == "python -m deploy init"


def test_doctor_all_pass_is_ok(client: TestClient, auth_header: dict, monkeypatch):
    async def fake_exec(*args, **kwargs):
        class P:
            returncode = 0
            async def communicate(self):
                report = {**REPORT,
                          "summary": {"ok": 38, "warn": 0, "error": 0,
                                      "blocking": False, "total": 38},
                          "items": []}
                return (json.dumps(report).encode("utf-8"), b"")
        return P()

    monkeypatch.setattr("webui.services.system.asyncio.create_subprocess_exec", fake_exec)
    resp = client.get("/api/v1/system/doctor", headers=auth_header)
    data = resp.json()["data"]
    assert data["ok"] is True
    assert data["summary"]["blocking"] is False


def test_doctor_non_json_output_degrades(client: TestClient, auth_header: dict, monkeypatch):
    async def fake_exec(*args, **kwargs):
        class P:
            returncode = 1
            async def communicate(self):
                return (b"Traceback ...", b"")
        return P()

    monkeypatch.setattr("webui.services.system.asyncio.create_subprocess_exec", fake_exec)
    resp = client.get("/api/v1/system/doctor", headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["ok"] is False
    assert "Traceback" in data["output"]


def test_port_item_reframed_when_bot_live(
    client: TestClient, auth_header: dict, isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Bot 进程内（宿主已注入状态源且 NapCat 已连接）：onebot_port 的
    「端口被占」error 必须改写为正常——检查面向启动前，运行中它是误报
    （python bot.py 直启没有 PID 文件，deploy 无法自行确认占用者）。"""

    from webui import status_source

    report = {
        "version": 1,
        "summary": {"ok": 33, "warn": 2, "error": 3, "blocking": True, "total": 38},
        "items": [
            {"id": "onebot_port", "level": "error", "title": "反向 WS 端口被其他程序占用",
             "detail": "端口 8080 无法 bind", "fix_hint": "netstat -ano"},
            {"id": "env_file", "level": "warn", "title": "其它提示"},
        ],
    }

    async def fake_exec(*args, **kwargs):
        class P:
            returncode = 1
            async def communicate(self):
                return (json.dumps(report).encode("utf-8"), b"")
        return P()

    monkeypatch.setattr("webui.services.system.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(status_source, "_source", lambda: {
        "pid": 4321, "link": {"connected": True},
    })

    resp = client.get("/api/v1/system/doctor", headers=auth_header)
    data = resp.json()["data"]
    port_item = data["report"]["items"][0]
    assert port_item["level"] == "ok"
    assert "当前 Bot 占用" in port_item["title"]
    # summary 重算：error 清零、blocking 解除
    assert data["summary"]["error"] == 0
    assert data["summary"]["warn"] == 1
    assert data["summary"]["blocking"] is False
    assert data["ok"] is True


def test_port_item_kept_in_standalone(
    client: TestClient, auth_header: dict, monkeypatch: pytest.MonkeyPatch,
):
    """独立模式（无宿主状态源）：onebot_port 检查原样保留（降一档为 warn）。"""
    from webui import status_source

    report = {
        "version": 1,
        "summary": {"ok": 30, "warn": 0, "error": 1, "blocking": True, "total": 31},
        "items": [
            {"id": "onebot_port", "level": "error", "title": "反向 WS 端口被其他程序占用"},
        ],
    }

    async def fake_exec(*args, **kwargs):
        class P:
            returncode = 1
            async def communicate(self):
                return (json.dumps(report).encode("utf-8"), b"")
        return P()

    monkeypatch.setattr("webui.services.system.asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(status_source, "_source", None)  # 独立模式

    resp = client.get("/api/v1/system/doctor", headers=auth_header)
    data = resp.json()["data"]
    item = data["report"]["items"][0]
    assert item["level"] == "warn"  # 非阻塞化，但不冒充正常
    assert data["summary"]["blocking"] is False


def test_doctor_requires_auth(client: TestClient):
    assert client.get("/api/v1/system/doctor").status_code == 401
