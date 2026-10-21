# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Platform configuration supports multiple adapters without exposing secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

USER = {"username": "admin", "password": "correct horse battery"}


def _auth_header(client: TestClient) -> dict:
    response = client.post("/api/v1/auth/setup", json=USER)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['token']}"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    return _auth_header(client)


def test_adapter_module_routes_require_auth(client: TestClient):
    assert client.get("/api/v1/platform/adapters").status_code == 401
    assert client.put(
        "/api/v1/platform/adapters", json={"modules": []}
    ).status_code == 401


def test_adapter_module_config_roundtrips_without_secrets(
    client: TestClient, auth_header: dict, isolated_home: Path
):
    (isolated_home / ".env").write_text(
        "ONEBOT_ACCESS_TOKEN=must-not-return\n", encoding="utf-8"
    )

    response = client.get("/api/v1/platform/adapters", headers=auth_header)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["modules"] == ["nonebot.adapters.onebot.v11"]
    assert data["effective_modules"] == ["nonebot.adapters.onebot.v11"]
    assert "must-not-return" not in response.text
    assert "ONEBOT_ACCESS_TOKEN" not in response.text

    response = client.put(
        "/api/v1/platform/adapters",
        json={"modules": ["custom.adapter.alpha", "custom.adapter.beta"]},
        headers=auth_header,
    )

    assert response.status_code == 200
    assert response.json()["data"]["modules"] == [
        "custom.adapter.alpha",
        "custom.adapter.beta",
    ]
    assert response.json()["data"]["restart_required"] is True
    saved = (isolated_home / ".env").read_text(encoding="utf-8")
    assert "STELLA_ADAPTER_MODULES=custom.adapter.alpha,custom.adapter.beta" in saved
    assert "ONEBOT_ACCESS_TOKEN=must-not-return" in saved


def test_adapter_modules_can_be_disabled_and_invalid_values_are_rejected(
    client: TestClient, auth_header: dict, isolated_home: Path
):
    disabled = client.put(
        "/api/v1/platform/adapters", json={"modules": []}, headers=auth_header
    )
    assert disabled.status_code == 200
    assert "STELLA_ADAPTER_MODULES=none" in (
        isolated_home / ".env"
    ).read_text(encoding="utf-8")

    invalid = client.put(
        "/api/v1/platform/adapters",
        json={"modules": ["not-a-module"]},
        headers=auth_header,
    )
    assert invalid.status_code == 400
    assert "valid Python module paths" in invalid.json()["message"]


def test_onebot_config_supports_multiple_urls_and_redacts_token(
    client: TestClient, auth_header: dict, isolated_home: Path
):
    secret = "onebot-token-must-not-return"
    urls = ["ws://127.0.0.1:3001/onebot", "wss://bot.example.test/onebot"]

    saved = client.put(
        "/api/v1/platform/onebot",
        json={"ws_urls": urls, "access_token": secret, "host": "0.0.0.0", "port": 8080},
        headers=auth_header,
    )

    assert saved.status_code == 200
    assert saved.json()["data"]["restart_required"] is True
    env_text = (isolated_home / ".env").read_text(encoding="utf-8")
    assert "ONEBOT_WS_URLS=[\"ws://127.0.0.1:3001/onebot\", \"wss://bot.example.test/onebot\"]" in env_text
    assert f"ONEBOT_ACCESS_TOKEN={secret}" in env_text

    current = client.get("/api/v1/platform/onebot", headers=auth_header)

    assert current.status_code == 200
    assert current.json()["data"]["ws_urls"] == urls
    assert current.json()["data"]["has_token"] is True
    assert secret not in current.text
