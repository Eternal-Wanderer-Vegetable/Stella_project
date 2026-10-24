# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Authenticated Corona config/API compatibility and operation streaming."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from corona.app import create_corona_app
from corona.bootstrap import prepare_corona_bootstrap
from corona.config_store import ConfigStore
from corona.operations import OperationManager
from stella_bootstrap.config import build_config_revision, write_revision

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "cn05-api-test"


def _snapshot(phase: str, revision_id: str, generation_id: str, pid: int | None = 4200):
    updated = datetime.now(timezone.utc).isoformat()
    return SimpleNamespace(
        desired="running" if phase == "ready" else "stopped",
        phase=phase,
        instance_id=INSTANCE,
        controller_boot_id="controller-api-test",
        revision_id=revision_id,
        generation_id=generation_id,
        pid=pid if phase == "ready" else None,
        attempt=1,
        error_code=None,
        updated_at=updated,
        public=lambda: {
            "phase": phase,
            "revision_id": revision_id,
            "updated_at": updated,
        },
    )


class _Supervisor:
    def __init__(self, bootstrap):
        self.bootstrap = bootstrap
        self.snapshot = _snapshot("ready", bootstrap.revision.revision_id, "initial")
        self.selected = bootstrap.revision
        self.started = []

    async def start(self):
        return self.snapshot

    async def start_once(self):
        self.started.append(self.selected.revision_id)
        self.snapshot = _snapshot(
            "ready", self.selected.revision_id, f"gen-{len(self.started)}"
        )
        return self.snapshot

    def select_revision(self, revision, path):
        self.selected = revision
        self.bootstrap = SimpleNamespace(
            **{
                **vars(self.bootstrap),
                "revision": revision,
                "revision_file": path,
            }
        )

    async def drain_core(self, _operation_id):
        self.snapshot = _snapshot(
            "draining", self.selected.revision_id, "draining", None
        )
        return True

    async def stop(self, **_kwargs):
        self.snapshot = _snapshot("stopped", self.selected.revision_id, "stopped", None)


def _app(tmp_path: Path, *, extra_env: str = ""):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "HOST=127.0.0.1\nPORT=18765\nWEBUI_ENABLED=true\nWEBUI_SERVE_DIST=false\n"
        + extra_env,
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "isolated.db")}
    initial = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment=external,
    )
    revision_path = write_revision(home, INSTANCE, initial)
    bootstrap = prepare_corona_bootstrap(
        {
            "STELLA_CONFIG_REVISION_FILE": str(revision_path),
            "STELLA_INSTANCE_ID": INSTANCE,
        },
        project_root=ROOT,
    )
    store = ConfigStore(
        stella_home=home,
        instance_id=INSTANCE,
        project_root=ROOT,
        external_environment=external,
    )
    store.initialize(initial)
    supervisor = _Supervisor(bootstrap)
    manager = OperationManager(store, supervisor)
    return (
        create_corona_app(
            bootstrap,
            supervisor,
            config_store=store,
            operation_manager=manager,
        ),
        store,
        supervisor,
    )


def test_corona_config_api_auth_revision_redaction_and_sse(tmp_path: Path) -> None:
    app, _store, supervisor = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/v1/config").status_code == 401
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "cn05-api-test-password"},
        )
        assert setup.status_code == 200
        headers = {"Authorization": f"Bearer {setup.json()['data']['token']}"}

        current = client.get("/api/v1/config", headers=headers)
        assert current.status_code == 200
        current_data = current.json()["data"]
        revision = current_data["desired_revision"]
        secret_field = next(
            field
            for field in current_data["fields"]
            if field["key"] == "LLM_ENDPOINT_CHAT_API_KEY"
        )
        assert secret_field["current_value"] is None
        roles = client.get("/api/v1/providers/roles", headers=headers).json()["data"][
            "roles"
        ]
        assert len(roles) == 7
        assert (
            next(role for role in roles if role["role"] == "chat")["endpoint"] == "CHAT"
        )
        endpoints = client.get("/api/v1/providers/endpoints", headers=headers).json()[
            "data"
        ]["endpoints"]
        assert endpoints[0]["base_url"] == "http://127.0.0.1:1234"

        saved = client.put(
            "/api/v1/config",
            headers={
                **headers,
                "If-Match": f'"{revision}"',
                "Idempotency-Key": "api-config-1",
            },
            json={
                "MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 3,
                "LLM_ENDPOINT_CHAT_API_KEY": "api-test-secret",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["data"]["restart_scope"] == "nucleus"
        changed_revision = saved.json()["data"]["revision_id"]

        conflict = client.put(
            "/api/v1/config",
            headers={**headers, "If-Match": revision},
            json={"MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE": 4},
        )
        assert conflict.status_code == 409
        assert conflict.json()["data"]["code"] == "revision_conflict"

        accepted = client.post(
            "/api/v1/system/apply",
            headers={**headers, "Idempotency-Key": "api-apply-1"},
            json={"revision_id": changed_revision},
        )
        assert accepted.status_code == 202
        operation_id = accepted.json()["data"]["operation_id"]
        repeated = client.post(
            "/api/v1/system/apply",
            headers={**headers, "Idempotency-Key": "api-apply-1"},
            json={"revision_id": changed_revision},
        )
        assert repeated.status_code == 202
        assert repeated.json()["data"]["operation_id"] == operation_id

        operation = client.get(
            f"/api/v1/system/operations/{operation_id}", headers=headers
        )
        assert operation.status_code == 200
        assert operation.json()["data"]["phase"] == "succeeded"
        event_stream = client.get(
            f"/api/v1/system/operations/{operation_id}/events", headers=headers
        )
        assert event_stream.status_code == 200
        assert "id: 1" in event_stream.text
        assert "event: succeeded" in event_stream.text
        status = client.get("/api/v1/status", headers=headers)
        assert status.status_code == 200
        assert status.json()["data"]["applied_revision"] == changed_revision
        assert status.json()["data"]["core"]["stale"] is False

        onebot = client.put(
            "/api/v1/platform/onebot",
            headers={**headers, "Idempotency-Key": "api-onebot-1"},
            json={
                "ws_urls": ["ws://127.0.0.1:3001"],
                "access_token": "platform-secret",
            },
        )
        assert onebot.status_code == 200
        config_after = client.get("/api/v1/config", headers=headers).json()["data"]
        assert "platform-secret" not in str(config_after)
        token = next(
            field
            for field in config_after["fields"]
            if field["key"] == "ONEBOT_ACCESS_TOKEN"
        )
        assert token["has_value"] is True
        assert token["current_value"] is None

    assert supervisor.started == [changed_revision]


def test_corona_platform_adapters_catalog_save_and_secret_redaction(
    tmp_path: Path,
) -> None:
    app, store, _supervisor = _app(
        tmp_path,
        extra_env=(
            "STELLA_ADAPTER_MODULES=nonebot.adapters.onebot.v11\n"
            "DRIVER=~fastapi+~httpx+~websockets\n"
            "ONEBOT_ACCESS_TOKEN='onebot-old-secret'\n"
            'QQ_BOTS=\'[ {"id":"10001","secret":"qq-old-secret"} ]\'\n'
            'STELLA_ADAPTER_ENV_KEYS=\'["CUSTOM_ADAPTER_TOKEN","CUSTOM_ADAPTER_LABEL","CUSTOM_OLD"]\'\n'
            'STELLA_ADAPTER_ENV_MODULES=\'{"CUSTOM_ADAPTER_TOKEN":"nonebot.adapters.onebot.v11","CUSTOM_ADAPTER_LABEL":"nonebot.adapters.onebot.v11","CUSTOM_OLD":"nonebot.adapters.onebot.v11"}\'\n'
            "CUSTOM_ADAPTER_TOKEN='adapter-old-secret'\n"
            "CUSTOM_ADAPTER_LABEL='old label'\n"
            "CUSTOM_OLD='remove me'\n"
        ),
    )
    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "cn05-api-test-password"},
        )
        assert setup.status_code == 200
        headers = {"Authorization": f"Bearer {setup.json()['data']['token']}"}

        current = client.get("/api/v1/platform/adapters", headers=headers)
        assert current.status_code == 200
        current_data = current.json()["data"]
        assert current_data["modules"] == ["nonebot.adapters.onebot.v11"]
        assert current_data["driver"] == "~fastapi+~httpx+~websockets"
        assert current_data["installed_packages"]
        assert any(
            item["module"] == "nonebot.adapters.onebot.v11"
            for item in current_data["catalog"]
        )
        assert set(current_data["connections"]) == {
            "onebot", "qq", "telegram", "discord"
        }
        token_field = next(
            item
            for item in current_data["adapter_env"]
            if item["key"] == "CUSTOM_ADAPTER_TOKEN"
        )
        assert token_field["sensitive"] is True
        assert token_field["has_value"] is True
        assert token_field["value"] == ""
        assert "adapter-old-secret" not in str(current_data)
        assert "onebot-old-secret" not in str(current_data)
        assert "qq-old-secret" not in str(current_data)

        saved = client.put(
            "/api/v1/platform/adapters",
            headers={
                **headers,
                "If-Match": current_data["desired_revision"],
                "Idempotency-Key": "platform-adapters-save-1",
            },
            json={
                "modules": ["nonebot.adapters.onebot.v11"],
                "driver": "~fastapi+~httpx+~websockets",
                "connections": {
                    "onebot": {
                        "host": "127.0.0.1",
                        "port": "18766",
                        "ws_urls": ["wss://example.invalid/onebot"],
                        "access_token": "",
                    }
                },
                "adapter_env": [
                    {
                        "key": "CUSTOM_ADAPTER_TOKEN",
                        "value": "",
                        "module": "nonebot.adapters.onebot.v11",
                    },
                    {
                        "key": "CUSTOM_ADAPTER_LABEL",
                        "value": "space # and \\ slash",
                        "module": "nonebot.adapters.onebot.v11",
                    },
                ],
            },
        )
        assert saved.status_code == 200, saved.text
        saved_data = saved.json()["data"]
        assert saved_data["desired_revision"] == saved_data["revision_id"]
        revision, _path = store.current_revision("desired")
        assert revision.values["DRIVER"] == "~fastapi+~httpx+~websockets"
        assert revision.values["CUSTOM_ADAPTER_TOKEN"] == "adapter-old-secret"
        assert revision.values["CUSTOM_ADAPTER_LABEL"] == "space # and \\ slash"
        assert "CUSTOM_OLD" not in revision.values
        assert revision.values["ONEBOT_ACCESS_TOKEN"] == "onebot-old-secret"
        assert revision.values["ONEBOT_WS_URLS"] == '["wss://example.invalid/onebot"]'
        assert revision.values["QQ_BOTS"] == '[ {"id":"10001","secret":"qq-old-secret"} ]'

        updated = client.get("/api/v1/platform/adapters", headers=headers).json()["data"]
        assert updated["desired_revision"] == saved_data["desired_revision"]
        assert updated["connections"]["onebot"]["port"] == "18766"
        assert "adapter-old-secret" not in str(updated)
        assert "qq-old-secret" not in str(updated)

        blocked = client.put(
            "/api/v1/platform/adapters",
            headers={
                **headers,
                "If-Match": updated["desired_revision"],
                "Idempotency-Key": "platform-adapters-blocked-1",
            },
            json={"modules": ["nonebot.adapters.mail"]},
        )
        assert blocked.status_code == 400
        assert blocked.json()["data"]["code"] == "adapter_modules_unavailable"
        assert store.state().desired_revision == updated["desired_revision"]
