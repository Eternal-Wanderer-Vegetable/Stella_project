# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""脱敏红线测试（方案 §9.5，手法沿用 tests/test_status_api.py 的反泄漏断言）。

/auth.json 里的 jwt_secret、ONEBOT_ACCESS_TOKEN 这类凭据，任何已认证响应
都不得出现。payload 由 status_api.collect_status() 聚合——它的脱敏在 v1
侧已有测试钉死，这里钉的是 webui 附加层与透传路径。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import config.settings as settings

SECRET_TOKEN = "super-secret-onebot-token"


def _fake_collect() -> dict:
    """一帧有代表性的 v1 payload（形状照 build_payload，值脱敏无关紧要）。"""
    return {
        "version": "4.4.0",
        "instance_id": "test",
        "launch_token_digest": "ab" * 32,
        "pid": 1234,
        "uptime_seconds": 1.0,
        "allowed_group_count": 2,
        "link": None,
        "scheduler": {},
        "usage": {"tokens_today": 100},
        "capabilities": None,
        "skills": None,
        "runtime": None,
    }


def _client_with_stubbed_status(isolated_home, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    monkeypatch.setenv("ONEBOT_ACCESS_TOKEN", SECRET_TOKEN)
    monkeypatch.setattr(
        "webui.routers.status.status_api",
        type("Stub", (), {"collect_status": staticmethod(_fake_collect)}),
    )
    from webui.app import create_webui_app

    app = create_webui_app()
    client = TestClient(app)
    resp = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "correct horse battery"},
    )
    assert resp.status_code == 200
    return client


def test_status_response_leaks_no_credentials(isolated_home, monkeypatch):
    client = _client_with_stubbed_status(isolated_home, monkeypatch)
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "correct horse battery"},
    )
    assert resp.status_code == 200
    token = resp.json()["data"]["token"]
    # 凭据文件里的 jwt_secret 是最敏感的长期值，任何响应都不得出现
    auth_record = json.loads(
        (isolated_home / "webui" / "auth.json").read_text(encoding="utf-8")
    )
    resp = client.get("/api/v1/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    # webui 段存在且只含身份（via 是传输语义，恒为 jwt；签发途径只进审计）
    assert data["webui"] == {"username": "admin", "via": "jwt"}
    # 凭据零泄漏
    text = json.dumps(resp.json(), ensure_ascii=False)
    assert SECRET_TOKEN not in text
    assert auth_record["jwt_secret"] not in text
    assert "Bearer " not in text
    # 响应透传了 v1 payload 的既有形状
    assert data["pid"] == 1234
    assert data["allowed_group_count"] == 2


def test_unauthenticated_status_is_401(client: TestClient):
    assert client.get("/api/v1/status").status_code == 401
