# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""鉴权流测试：setup → 登录 → me → 账号维护 → desktop-session → 限流。

约定（方案 §9）：公开端点只有 setup-status/setup/login/desktop-session；
其余 401；过期与伪造 token 不区分响应码（对攻击者等价，不给探测信息）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import config.settings as settings
from webui import security

USER = {"username": "admin", "password": "correct horse battery"}


def _setup(client: TestClient) -> str:
    resp = client.post("/api/v1/auth/setup", json=USER)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    return resp.json()["data"]["token"]


def test_setup_flow_and_idempotency(client: TestClient):
    assert client.get("/api/v1/auth/setup-status").json()["data"] == {
        "setup_required": True
    }
    token = _setup(client)
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["data"]["username"] == "admin"
    # 初始化后 setup-status 翻转、重复 setup 403
    assert client.get("/api/v1/auth/setup-status").json()["data"] == {
        "setup_required": False
    }
    resp = client.post("/api/v1/auth/setup", json=USER)
    assert resp.status_code == 403
    assert resp.json()["status"] == "error"


def test_setup_rejects_weak_password(client: TestClient):
    resp = client.post(
        "/api/v1/auth/setup", json={"username": "admin", "password": "short"}
    )
    assert resp.status_code == 422  # pydantic 校验失败走 FastAPI 默认 422


def test_login_and_logout(client: TestClient):
    _setup(client)
    bad = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong password"},
    )
    assert bad.status_code == 401
    ok_resp = client.post("/api/v1/auth/login", json=USER)
    assert ok_resp.status_code == 200
    assert ok_resp.json()["data"]["token"]
    # Cookie 补充通道：不带 Bearer 也能过认证端点
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_me_requires_auth(client: TestClient):
    assert client.get("/api/v1/auth/me").status_code == 401
    garbage = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert garbage.status_code == 401


def test_expired_token_is_401(client: TestClient, isolated_home):
    _setup(client)
    record = security.load_record()
    token, _ = security.create_token(record, ttl_hours=-1)
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


def test_account_update_rotates_tokens(client: TestClient):
    old_token = _setup(client)
    # 旧密码错 → 401
    resp = client.patch(
        "/api/v1/auth/account",
        json={"old_password": "wrong password", "new_password": "new password 9"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert resp.status_code == 401
    # 正确修改 → 返回新 token，旧 token 因 jwt_secret 轮换立即失效
    resp = client.patch(
        "/api/v1/auth/account",
        json={"old_password": USER["password"], "new_password": "new password 9"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert resp.status_code == 200
    new_token = resp.json()["data"]["token"]
    assert new_token != old_token
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}).status_code
        == 401
    )
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code
        == 200
    )
    # 新密码可登录、旧密码不可
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "new password 9"},
        ).status_code
        == 200
    )
    assert client.post("/api/v1/auth/login", json=USER).status_code == 401


def test_desktop_session_exchange(client: TestClient, monkeypatch):
    secret = "x" * 40
    client.post("/api/v1/auth/setup", json=USER)
    # 未配置 secret → 401
    monkeypatch.delenv("STELLA_DESKTOP_SESSION_SECRET", raising=False)
    assert client.post(
        "/api/v1/auth/desktop-session",
        headers={"X-Stella-Desktop-Session": secret},
    ).status_code == 401
    # 配置 + 错误头 → 401；正确头 + 回环来源 → 200
    monkeypatch.setenv("STELLA_DESKTOP_SESSION_SECRET", secret)
    assert (
        client.post(
            "/api/v1/auth/desktop-session",
            headers={"X-Stella-Desktop-Session": "y" * 40},
        ).status_code
        == 401
    )
    loopback = TestClient(
        client.app, client=("127.0.0.1", 50000)
    )  # 显式回环来源
    resp = loopback.post(
        "/api/v1/auth/desktop-session",
        headers={"X-Stella-Desktop-Session": secret},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["token"]


def test_login_rate_limit(isolated_home, monkeypatch):
    monkeypatch.setattr(settings, "WEBUI_LOGIN_RATELIMIT_PER_MIN", 1)
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    client = TestClient(create_webui_app_from_settings())
    body = {"username": "admin", "password": "wrong password"}
    # 容量 1：第一次请求进验证（返回 401），第二次连验证都进不去（429）
    assert client.post("/api/v1/auth/login", json=body).status_code == 401
    assert client.post("/api/v1/auth/login", json=body).status_code == 429


def create_webui_app_from_settings():
    from webui.app import create_webui_app

    return create_webui_app()


def test_audit_log_written(client: TestClient, isolated_home):
    _setup(client)
    audit_path = isolated_home / "logs" / "webui_audit.jsonl"
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    assert '"action": "auth.setup"' in content
    # 审计绝不含明文密码
    assert USER["password"] not in content


def test_dist_disabled_when_serve_off(
    client: TestClient, isolated_home, monkeypatch, make_dist
):
    """WEBUI_SERVE_DIST=false 时即使 dist 存在也不托管（Vite 反代开发场景）。"""
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    make_dist()
    from webui.static import dist_dir

    assert dist_dir() is None
