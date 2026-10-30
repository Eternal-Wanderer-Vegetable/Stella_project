# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Authenticated Corona config/API compatibility and operation streaming."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from corona.app import create_corona_app
from corona.bootstrap import prepare_corona_bootstrap
from corona.config_store import ConfigStore, ConfigStoreError
from corona.operations import OperationManager
from stella_bootstrap.config import build_config_revision, write_revision

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = "cn05-api-test"
TRANSPORT_SETTINGS_KEY = "STELLA_TRANSPORT_SETTINGS_JSON"


def _transport_bundle() -> dict:
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


def _app(
    tmp_path: Path,
    *,
    extra_env: str = "",
    external_environment: dict[str, str] | None = None,
):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "HOST=127.0.0.1\nPORT=18765\nWEBUI_ENABLED=true\nWEBUI_SERVE_DIST=false\n"
        + extra_env,
        encoding="utf-8",
    )
    external = {"DB_PATH": str(tmp_path / "isolated.db")}
    external.update(external_environment or {})
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


def _doctor_port_report(port: int) -> dict:
    return {
        "version": 1,
        # The CLI summary includes all 38 checks, while its items list only
        # includes findings. Keep passing entries implicit as in production.
        "summary": {"ok": 36, "warn": 1, "error": 1, "blocking": True, "total": 38},
        "items": [
            {
                "id": "onebot_port",
                "level": "error",
                "title": "反向 WS 端口被其他程序占用",
                "detail": f"端口 {port} 无法 bind，且 Stella 的状态接口不可达。",
                "fix_hint": "检查端口占用者",
            }
        ],
    }


def _doctor_headers(client: TestClient) -> dict[str, str]:
    setup = client.post(
        "/api/v1/auth/setup",
        json={"username": "admin", "password": "cn05-doctor-test-password"},
    )
    assert setup.status_code == 200
    return {"Authorization": f"Bearer {setup.json()['data']['token']}"}


def test_managed_doctor_reframes_corona_owned_reverse_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _store, _supervisor = _app(tmp_path)

    async def fake_doctor(*, reframe_embedded_bot_port: bool = True) -> dict:
        assert reframe_embedded_bot_port is False
        report = _doctor_port_report(18765)
        return {"ok": False, "report": report, "summary": report["summary"], "exit_code": 1}

    monkeypatch.setattr("webui.services.system.run_doctor", fake_doctor)
    with TestClient(app) as client:
        headers = _doctor_headers(client)
        response = client.get("/api/v1/system/doctor", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    port_item = next(item for item in data["report"]["items"] if item["id"] == "onebot_port")
    assert port_item["level"] == "ok"
    assert "由 Stella 托管" in port_item["title"]
    assert "fix_hint" not in port_item
    assert data["summary"] == {
        "ok": 41,
        "warn": 1,
        "error": 0,
        "blocking": False,
        "total": 42,
    }
    assert data["ok"] is True


def test_managed_doctor_keeps_error_when_desired_port_differs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, store, _supervisor = _app(tmp_path)
    store.save(
        {"PORT": "18766"},
        expected_revision=store.state().desired_revision,
        idempotency_key="doctor-pending-port-change",
    )

    async def fake_doctor(*, reframe_embedded_bot_port: bool = True) -> dict:
        assert reframe_embedded_bot_port is False
        report = _doctor_port_report(18766)
        return {"ok": False, "report": report, "summary": report["summary"], "exit_code": 1}

    monkeypatch.setattr("webui.services.system.run_doctor", fake_doctor)
    with TestClient(app) as client:
        headers = _doctor_headers(client)
        response = client.get("/api/v1/system/doctor", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    port_item = next(item for item in data["report"]["items"] if item["id"] == "onebot_port")
    assert port_item["level"] == "error"
    assert data["summary"]["error"] == 1
    assert data["summary"]["blocking"] is True
    assert data["ok"] is False


def test_managed_doctor_keeps_error_when_core_health_probe_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _store, supervisor = _app(tmp_path)

    async def core_unreachable() -> bool:
        return False

    supervisor.core_reachable = core_unreachable

    async def fake_doctor(*, reframe_embedded_bot_port: bool = True) -> dict:
        assert reframe_embedded_bot_port is False
        report = _doctor_port_report(18765)
        return {"ok": False, "report": report, "summary": report["summary"], "exit_code": 1}

    monkeypatch.setattr("webui.services.system.run_doctor", fake_doctor)
    with TestClient(app) as client:
        headers = _doctor_headers(client)
        response = client.get("/api/v1/system/doctor", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    port_item = next(item for item in data["report"]["items"] if item["id"] == "onebot_port")
    core_item = next(item for item in data["report"]["items"] if item["id"] == "corona_core")
    assert port_item["level"] == "error"
    assert core_item["level"] == "error"
    assert data["summary"]["error"] == 2
    assert data["ok"] is False


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


def test_corona_conversation_settings_cas_idempotency_apply_and_core_down_save(
    tmp_path: Path,
) -> None:
    app, store, supervisor = _app(tmp_path)
    initial_revision = store.state().desired_revision
    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "cn05-api-test-password"},
        )
        assert setup.status_code == 200
        headers = {"Authorization": f"Bearer {setup.json()['data']['token']}"}
        route = "/api/v1/platform/conversation-settings"

        generic_config = client.get("/api/v1/config", headers=headers).json()["data"]
        assert TRANSPORT_SETTINGS_KEY not in {
            field["key"] for field in generic_config["fields"]
        }
        generic_update = client.put(
            "/api/v1/config",
            headers={
                **headers,
                "If-Match": f'"{initial_revision}"',
                "Idempotency-Key": "generic-transport-settings-rejected",
            },
            json={TRANSPORT_SETTINGS_KEY: json.dumps(_transport_bundle())},
        )
        assert generic_update.status_code == 400
        assert generic_update.json()["data"]["code"] == "dedicated_settings_route_required"

        current = client.get(route, headers=headers)
        assert current.status_code == 200
        assert current.json()["data"]["settings"] == {"version": 1}
        assert current.json()["data"]["applied_settings"] == {"version": 1}
        assert current.headers["ETag"] == f'"{initial_revision}"'

        body = json.dumps(_transport_bundle(), ensure_ascii=False).encode("utf-8")
        missing = client.put(route, content=body, headers=headers)
        assert missing.status_code == 428
        assert missing.json()["data"]["code"] == "if_match_required"

        malformed = client.put(
            route,
            content=b'{"version":1,"version":1}',
            headers={**headers, "If-Match": current.headers["ETag"]},
        )
        assert malformed.status_code == 400
        assert malformed.json()["data"]["code"] == "transport_settings_invalid"

        invalid = client.put(
            route,
            content=b'{"version":1,"bindings":[{"connection_id":"11111111-1111-4111-8111-111111111111","scene":{"kind":"group","scene_id":"g"},"policy_profile_id":"missing"}]}',
            headers={**headers, "If-Match": current.headers["ETag"]},
        )
        assert invalid.status_code == 400
        assert store.state().desired_revision == initial_revision
        assert supervisor.started == []

        wrong_revision = client.put(
            route,
            content=body,
            headers={**headers, "If-Match": '"stale-revision"'},
        )
        assert wrong_revision.status_code == 409
        assert wrong_revision.json()["data"]["code"] == "revision_conflict"

        supervisor.snapshot = _snapshot("stopped", initial_revision, "core-down", None)
        manager = app.state.operation_manager
        app.state.operation_manager = None
        saved = client.put(
            route,
            content=body,
            headers={
                **headers,
                "If-Match": current.headers["ETag"],
                "Idempotency-Key": "conversation-settings-1",
            },
        )
        app.state.operation_manager = manager
        assert saved.status_code == 200, saved.text
        saved_data = saved.json()["data"]
        assert saved_data["valid"] is True
        assert saved_data["applied_settings"] == {"version": 1}
        assert saved_data["settings"] == _transport_bundle()
        assert saved_data["source"] == "data_env"
        assert saved_data["applied_revision"] == initial_revision
        assert saved_data["desired_revision"] != initial_revision
        assert supervisor.started == []
        managed_env = store.env_path.read_text(encoding="utf-8")
        assert r"\\u0024{HOME}" in managed_env
        assert "${HOME}" not in managed_env

        retry = client.put(
            route,
            content=body,
            headers={
                **headers,
                "If-Match": current.headers["ETag"],
                "Idempotency-Key": "conversation-settings-1",
            },
        )
        assert retry.status_code == 200
        assert retry.json()["data"]["desired_revision"] == saved_data["desired_revision"]

        conflicting_retry = client.put(
            route,
            content=json.dumps(
                {**_transport_bundle(), "defaults": {"capture_enabled": False}},
                ensure_ascii=False,
            ).encode("utf-8"),
            headers={
                **headers,
                "If-Match": current.headers["ETag"],
                "Idempotency-Key": "conversation-settings-1",
            },
        )
        assert conflicting_retry.status_code == 409
        assert conflicting_retry.json()["data"]["code"] == "idempotency_conflict"

        applied = client.post(
            "/api/v1/system/apply",
            headers={**headers, "Idempotency-Key": "conversation-settings-apply-1"},
            json={"revision_id": saved_data["desired_revision"]},
        )
        assert applied.status_code == 202
        repeated_apply = client.post(
            "/api/v1/system/apply",
            headers={**headers, "Idempotency-Key": "conversation-settings-apply-1"},
            json={"revision_id": saved_data["desired_revision"]},
        )
        assert repeated_apply.status_code == 202
        operation_id = applied.json()["data"]["operation_id"]
        assert repeated_apply.json()["data"]["operation_id"] == operation_id
        operation = client.get(
            f"/api/v1/system/operations/{operation_id}", headers=headers
        )
        assert operation.status_code == 200
        assert operation.json()["data"]["phase"] == "succeeded"
        assert supervisor.started == [saved_data["desired_revision"]]


def test_config_store_candidate_revision_rejects_invalid_transport_bundle(
    tmp_path: Path,
) -> None:
    _app_instance, store, _supervisor = _app(tmp_path)
    initial = store.state()
    env_before = store.env_path.read_bytes()
    with pytest.raises(ConfigStoreError, match="config_validation_failed"):
        store.save(
            {TRANSPORT_SETTINGS_KEY: '{"version":2}'},
            expected_revision=initial.desired_revision,
            idempotency_key="invalid-transport-settings",
        )
    assert store.state().desired_revision == initial.desired_revision
    assert store.env_path.read_bytes() == env_before


def test_corona_conversation_settings_reports_external_override_source(
    tmp_path: Path,
) -> None:
    external_settings = json.dumps(
        {"version": 1, "defaults": {"capture_enabled": False}},
        separators=(",", ":"),
    )
    app, _store, _supervisor = _app(
        tmp_path,
        external_environment={TRANSPORT_SETTINGS_KEY: external_settings},
    )
    with TestClient(app) as client:
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "cn05-api-test-password"},
        )
        headers = {"Authorization": f"Bearer {setup.json()['data']['token']}"}
        current = client.get(
            "/api/v1/platform/conversation-settings", headers=headers
        )
    assert current.status_code == 200
    data = current.json()["data"]
    assert data["settings"] == {
        "version": 1,
        "defaults": {"capture_enabled": False},
    }
    assert data["source"] == "external_environment"
    assert data["applied_source"] == "external_environment"


def test_transport_settings_profile_and_external_sources_roundtrip_large_json(
    tmp_path: Path,
) -> None:
    from stella_bootstrap.transport_settings import (
        MAX_TRANSPORT_SETTINGS_BYTES,
        parse_transport_settings_json,
    )
    from webui.services.conversation_settings import stored_json

    bundle = _transport_bundle()
    bundle["bindings"] = [
        {
            "connection_id": "11111111-1111-4111-8111-111111111111",
            "scene": {"kind": "group", "scene_id": f"{index}-" + "x" * 490},
            "policy_profile_id": "default",
        }
        for index in range(256)
    ]
    raw = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    parsed = parse_transport_settings_json(raw)
    assert 100_000 < len(parsed.canonical_json.encode("utf-8")) < MAX_TRANSPORT_SETTINGS_BYTES
    stored = stored_json(parsed)

    profile_home = tmp_path / "profile"
    profile_home.mkdir()
    (profile_home / ".env").write_text("ENVIRONMENT=dev\n", encoding="utf-8")
    (profile_home / ".env.dev").write_text(
        f"{TRANSPORT_SETTINGS_KEY}={json.dumps(stored, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    profile_revision = build_config_revision(
        project_root=ROOT,
        stella_home=profile_home,
        external_environment={},
    )
    assert profile_revision.sources[TRANSPORT_SETTINGS_KEY] == "dev_overlay"
    assert parse_transport_settings_json(
        profile_revision.values[TRANSPORT_SETTINGS_KEY]
    ).canonical_json == parsed.canonical_json

    external_home = tmp_path / "external"
    external_home.mkdir()
    (external_home / ".env").write_text("", encoding="utf-8")
    external_revision = build_config_revision(
        project_root=ROOT,
        stella_home=external_home,
        external_environment={TRANSPORT_SETTINGS_KEY: stored},
    )
    assert external_revision.sources[TRANSPORT_SETTINGS_KEY] == "external_environment"
    assert parse_transport_settings_json(
        external_revision.values[TRANSPORT_SETTINGS_KEY]
    ).canonical_json == parsed.canonical_json
