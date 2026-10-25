# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Legacy conversation-settings writes use authenticated content CAS."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _bundle() -> dict:
    return {
        "version": 1,
        "connections": [
            {
                "connection_id": "11111111-1111-4111-8111-111111111111",
                "adapter": "telegram",
                "platform_scope": "telegram",
                "self_id": "007:雪",
                "credential_ref": "env:TELEGRAM_BOT_TOKEN",
                "display_name": 'ops "blue" # ${HOME}',
            }
        ],
        "profiles": [{"policy_profile_id": "default", "policy": {}}],
        "bindings": [],
    }


def _auth(client: TestClient) -> dict[str, str]:
    setup = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "correct horse battery"},
    )
    assert setup.status_code == 200
    return {"Authorization": f"Bearer {setup.json()['data']['token']}"}


def test_legacy_conversation_settings_roundtrip_and_stale_write_rejected(
    client: TestClient, isolated_home: Path
):
    assert client.get("/api/v1/platform/conversation-settings").status_code == 401
    headers = _auth(client)
    generic_config = client.get("/api/v1/config", headers=headers).json()["data"]
    assert "STELLA_TRANSPORT_SETTINGS_JSON" not in {
        field["key"] for field in generic_config["fields"]
    }
    generic_write = client.put(
        "/api/v1/config",
        json={"STELLA_TRANSPORT_SETTINGS_JSON": json.dumps(_bundle())},
        headers=headers,
    )
    assert generic_write.status_code == 400

    current = client.get("/api/v1/platform/conversation-settings", headers=headers)
    assert current.status_code == 200
    assert current.json()["data"]["settings"] == {"version": 1}
    assert current.headers["ETag"].startswith('"sha256:')

    body = json.dumps(_bundle(), ensure_ascii=False).encode("utf-8")
    missing = client.put(
        "/api/v1/platform/conversation-settings",
        content=body,
        headers=headers,
    )
    assert missing.status_code == 428
    assert missing.json()["data"]["code"] == "if_match_required"

    saved = client.put(
        "/api/v1/platform/conversation-settings",
        content=body,
        headers={**headers, "If-Match": current.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["valid"] is True
    assert saved.json()["data"]["settings"] == _bundle()
    assert saved.json()["data"]["source"] == "data_env"
    assert saved.json()["data"]["restart_required"] is True
    assert saved.headers["ETag"] != current.headers["ETag"]

    env_text = (isolated_home / ".env").read_text(encoding="utf-8")
    assert env_text.count("STELLA_TRANSPORT_SETTINGS_JSON=") == 1
    assert r"\u0024{HOME}" in env_text

    stale = client.put(
        "/api/v1/platform/conversation-settings",
        content=body,
        headers={**headers, "If-Match": current.headers["ETag"]},
    )
    assert stale.status_code == 409
    assert stale.json()["data"]["code"] == "revision_conflict"


def test_legacy_conversation_settings_put_deduplicates_existing_key(
    client: TestClient, isolated_home: Path
):
    from webui.services.conversation_settings import SETTINGS_KEY

    (isolated_home / ".env").write_text(
        f'{SETTINGS_KEY}={{"version":1}}\n{SETTINGS_KEY}={{"version":1}}\n',
        encoding="utf-8",
    )
    headers = _auth(client)
    current = client.get("/api/v1/platform/conversation-settings", headers=headers)
    assert current.json()["data"]["valid"] is False

    saved = client.put(
        "/api/v1/platform/conversation-settings",
        content=json.dumps(_bundle(), ensure_ascii=False).encode("utf-8"),
        headers={**headers, "If-Match": current.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["valid"] is True
    assert (isolated_home / ".env").read_text(encoding="utf-8").count(
        f"{SETTINGS_KEY}="
    ) == 1


def test_legacy_conversation_settings_exposes_profile_and_external_overrides(
    client: TestClient, isolated_home: Path, monkeypatch
):
    import config.settings as settings
    from stella_bootstrap.transport_settings import parse_transport_settings_json
    from webui.services.conversation_settings import stored_json

    base = parse_transport_settings_json(json.dumps(_bundle(), ensure_ascii=False))
    profile = parse_transport_settings_json(
        '{"version":1,"defaults":{"capture_enabled":false}}'
    )
    (isolated_home / ".env").write_text(
        f"STELLA_TRANSPORT_SETTINGS_JSON={json.dumps(stored_json(base), ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    (isolated_home / ".env.dev").write_text(
        f"STELLA_TRANSPORT_SETTINGS_JSON={json.dumps(stored_json(profile), ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "_ENVIRONMENT", "dev")
    monkeypatch.setattr(settings, "_LEGACY_TRANSPORT_SETTINGS_EXTERNAL", None)
    headers = _auth(client)

    current = client.get("/api/v1/platform/conversation-settings", headers=headers)
    data = current.json()["data"]
    assert data["settings"] == _bundle()
    assert data["effective_settings"] == {
        "version": 1,
        "defaults": {"capture_enabled": False},
    }
    assert data["effective_source"] == "dev_overlay"

    external = parse_transport_settings_json(
        '{"version":1,"defaults":{"llm_enabled":false}}'
    )
    monkeypatch.setattr(
        settings, "_LEGACY_TRANSPORT_SETTINGS_EXTERNAL", stored_json(external)
    )
    monkeypatch.setattr(settings, "_ENVIRONMENT", "")
    current = client.get("/api/v1/platform/conversation-settings", headers=headers)
    data = current.json()["data"]
    assert data["effective_settings"] == {
        "version": 1,
        "defaults": {"llm_enabled": False},
    }
    assert data["effective_source"] == "external_environment"
