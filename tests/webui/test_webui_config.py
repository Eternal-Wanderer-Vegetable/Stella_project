# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""M2 写入面测试：.env 写回、配置读写、providers/platform/spaces/groups/system。

要点：
- 隔离：STELLA_HOME / DB_PATH 指到临时目录（webui 各服务在调用时读）；
- 继承键留空=删除、敏感键空串=不修改、choice/数值/未知键在服务端拒绝；
- spaces 走真实 toml 落盘 + reload；
- restart 只断言哨兵语义（mock stop_signal，不真停）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


# ---------- .env 写回 ----------

def test_envfile_write_and_remove(client: TestClient, isolated_home: Path):
    from webui.services import envfile

    (isolated_home / ".env").write_text(
        "# 注释\nEXISTING_KEY=1\n#HIDDEN_KEY=2\n", encoding="utf-8"
    )
    report = envfile.write_values(
        {"EXISTING_KEY": "9", "HIDDEN_KEY": "3", "NEW_KEY": "abc"}, remove={"GONE"}
    )
    assert report["written"] == ["EXISTING_KEY", "HIDDEN_KEY", "NEW_KEY"]
    text = (isolated_home / ".env").read_text(encoding="utf-8")
    assert "EXISTING_KEY=9" in text
    assert "#HIDDEN_KEY=2" not in text and "HIDDEN_KEY=3" in text  # 取消注释并替换
    assert "NEW_KEY=abc" in text
    assert "GONE" not in text
    assert "# 注释" in text  # 既有内容保留

    report = envfile.write_values({}, remove={"HIDDEN_KEY"})
    assert report["removed"] == ["HIDDEN_KEY"]
    assert "HIDDEN_KEY" not in (isolated_home / ".env").read_text(encoding="utf-8")


def test_envfile_rejects_stale_and_bad_keys(client: TestClient, isolated_home: Path):
    from webui.responses import ApiError
    from webui.services import envfile

    with pytest.raises(ApiError):
        envfile.write_values({"lower_case": "1"})
    # 废弃键（env_keys 登记表）：任取一个真实登记的废弃键验证
    try:
        from deploy import env_keys

        stale = [k for k in ("LM_STUDIO_BASE_URL", "OLD_KEY") if env_keys.deprecation_reason(k) or env_keys.superseded_by(k)]
        if stale:
            with pytest.raises(ApiError):
                envfile.write_values({stale[0]: "x"})
    except ImportError:
        pass


# ---------- 配置读写 ----------

def test_config_read_masks_sensitive(client: TestClient, auth_header: dict, isolated_home: Path):
    (isolated_home / ".env").write_text(
        "LLM_ENDPOINT_LOCAL_API_KEY=sk-secret-123\nHOST=127.0.0.1\n", encoding="utf-8"
    )
    resp = client.get("/api/v1/config", headers=auth_header)
    assert resp.status_code == 200
    fields = {f["key"]: f for f in resp.json()["data"]["fields"]}
    assert fields["LLM_ENDPOINT_LOCAL_API_KEY"]["sensitive"] is True
    assert fields["LLM_ENDPOINT_LOCAL_API_KEY"]["current_value"] is None
    assert fields["LLM_ENDPOINT_LOCAL_API_KEY"]["has_value"] is True
    assert fields["HOST"]["current_value"] == "127.0.0.1"


def test_config_update_validates(client: TestClient, auth_header: dict, isolated_home: Path):
    # 未知键拒绝
    resp = client.put("/api/v1/config", json={"NOT_A_REAL_KEY": "1"}, headers=auth_header)
    assert resp.status_code == 400
    # 合法键写回 + restart_required
    resp = client.put("/api/v1/config", json={"HOST": "127.0.0.1"}, headers=auth_header)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["restart_required"] is True
    assert "HOST=127.0.0.1" in (isolated_home / ".env").read_text(encoding="utf-8")


# ---------- providers ----------

def test_providers_endpoints_roundtrip(client: TestClient, auth_header: dict, isolated_home: Path):
    resp = client.get("/api/v1/providers/endpoints", headers=auth_header)
    assert resp.status_code == 200
    endpoints = resp.json()["data"]["endpoints"]
    assert any(e["slot"] == "LOCAL" for e in endpoints)
    local = next(e for e in endpoints if e["slot"] == "LOCAL")
    local.update({"base_url": "http://127.0.0.1:1234", "model": "test-model", "api_key": "sk-x"})
    resp = client.put("/api/v1/providers/endpoints", json=[local], headers=auth_header)
    assert resp.status_code == 200
    assert resp.json()["data"]["restart_required"] is True
    text = (isolated_home / ".env").read_text(encoding="utf-8")
    assert "LLM_ENDPOINT_LOCAL_BASE_URL=http://127.0.0.1:1234" in text
    assert "LLM_ENDPOINT_LOCAL_MODEL=test-model" in text
    assert "LLM_ENDPOINT_LOCAL_API_KEY=sk-x" in text


def test_providers_roles_get_put(client: TestClient, auth_header: dict):
    resp = client.get("/api/v1/providers/roles", headers=auth_header)
    roles = resp.json()["data"]["roles"]
    assert {r["role"] for r in roles} >= {"chat", "consolidation"}
    payload = next(r for r in roles if r["role"] == "chat")
    payload["endpoint"] = "ONLINE_CHAT"
    resp = client.put("/api/v1/providers/roles", json=[payload], headers=auth_header)
    assert resp.status_code == 200
    # 非法端点槽拒绝
    payload["endpoint"] = "NOT_A_SLOT"
    resp = client.put("/api/v1/providers/roles", json=[payload], headers=auth_header)
    assert resp.status_code == 400


# ---------- spaces ----------

def test_spaces_crud(client: TestClient, auth_header: dict, isolated_home: Path):
    resp = client.post("/api/v1/spaces", json={"name": "gaming", "system_prompt": "你是游戏搭子"})
    assert resp.status_code == 200
    resp = client.get("/api/v1/spaces", headers=auth_header)
    names = [s["name"] for s in resp.json()["data"]["spaces"]]
    assert "gaming" in names
    # prompt 读写
    resp = client.put("/api/v1/spaces/gaming/prompt", json={"text": "新的 prompt"})
    assert resp.status_code == 200
    resp = client.get("/api/v1/spaces/gaming/prompt", headers=auth_header)
    assert resp.json()["data"]["text"] == "新的 prompt"
    # 有绑定群时拒绝删除
    client.put("/api/v1/spaces/gaming/bindings", json={"qq_groups": [123]})
    resp = client.delete("/api/v1/spaces/gaming", headers=auth_header)
    assert resp.status_code == 409
    client.put("/api/v1/spaces/gaming/bindings", json={"qq_groups": []})
    assert client.delete("/api/v1/spaces/gaming", headers=auth_header).status_code == 200
    # 非法名拒绝
    assert client.post("/api/v1/spaces", json={"name": "../evil"}).status_code == 400


def test_spaces_default_readonly(client: TestClient, auth_header: dict):
    resp = client.get("/api/v1/spaces/default", headers=auth_header)
    assert resp.status_code == 200
    assert "text" in resp.json()["data"]


# ---------- groups ----------

def test_groups_bindings_write_env(
    client: TestClient, auth_header: dict, isolated_home: Path, monkeypatch
):
    import config.settings as settings

    monkeypatch.setattr(settings, "ALLOWED_GROUPS", [123])
    resp = client.put(
        "/api/v1/groups/bindings",
        json=[{"group_id": 123, "space": "default_space"}, {"group_id": 456, "space": "second"}],
        headers=auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["restart_required"] is True
    env_text = (isolated_home / ".env").read_text(encoding="utf-8")
    assert "ALLOWED_GROUPS=" in env_text
    # 两个空间的 toml 落盘（跟随 spaces.SPACES_DIR 的隔离值）
    from config import spaces as spaces_mod

    spaces_dir = Path(spaces_mod.SPACES_DIR)
    assert (spaces_dir / "default_space.toml").exists()
    assert (spaces_dir / "second.toml").exists()


def test_groups_mute(client: TestClient, auth_header: dict, isolated_home: Path):
    resp = client.post("/api/v1/groups/123/mute", headers=auth_header)
    assert resp.status_code == 200
    assert resp.json()["data"]["proactive_muted"] is True
    resp = client.post("/api/v1/groups/123/unmute", headers=auth_header)
    assert resp.json()["data"]["proactive_muted"] is False


# ---------- system ----------

def test_system_restart_writes_sentinel(client: TestClient, auth_header: dict, monkeypatch):
    from core import stop_signal

    called = {}
    monkeypatch.setattr(stop_signal, "request_stop", lambda reason="": called.update(reason=reason))
    resp = client.post("/api/v1/system/restart", headers=auth_header)
    assert resp.status_code == 200
    assert resp.json()["data"]["restart_mode"] in ("desktop", "manual")
    assert called.get("reason")


def test_write_endpoints_require_auth(client: TestClient):
    for method, path in (
        ("put", "/api/v1/config"),
        ("put", "/api/v1/providers/endpoints"),
        ("post", "/api/v1/spaces"),
        ("put", "/api/v1/groups/bindings"),
        ("post", "/api/v1/system/restart"),
    ):
        resp = getattr(client, method)(path, json={})
        assert resp.status_code == 401, path
