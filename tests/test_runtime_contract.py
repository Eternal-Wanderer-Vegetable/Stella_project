# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deploy import checks, probe, process, runtime


def test_default_manifest_has_optional_components():
    manifest = runtime.default_manifest()
    assert manifest["schema_version"] == 1
    assert set(manifest["components"]) == {"stella", "llama", "onebot"}
    assert manifest["components"]["llama"]["enabled"] is False
    assert manifest["components"]["llama"]["config"] == {
        "host": "127.0.0.1",
        "port": 8081,
        "model": {"path": "", "package": "", "id": "", "checksum": ""},
        "ctx_size": 4096,
        "backend": "cpu",
    }


def test_enabled_llama_manifest_exposes_a_local_endpoint(monkeypatch, tmp_path):
    payload = runtime.default_manifest()
    payload["components"]["llama"]["enabled"] = True
    payload["components"]["llama"]["config"]["model"]["id"] = "demo.gguf"
    payload["components"]["llama"]["config"]["model"]["path"] = str(tmp_path / "demo.gguf")
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path)
    runtime.write_manifest(payload)
    endpoint = runtime.llama_endpoint_config()
    assert endpoint["base_url"] == "http://127.0.0.1:8081"
    assert endpoint["model"] == "demo.gguf"
    assert endpoint["backend"] == "cpu"


def test_unknown_operation_and_component_are_rejected():
    with pytest.raises(ValueError):
        runtime.validate_operation("shell")
    with pytest.raises(ValueError):
        runtime.validate_operation("status", "napcat")


def test_operation_request_rejects_shell_and_redacts_secrets():
    with pytest.raises(ValueError):
        runtime.validate_operation_request(
            {"operation": "start", "component": "stella", "shell": "bot.py"}
        )
    value = runtime.redact_value(
        {"api_key": "secret", "nested": [{"access_token": "token"}], "ok": 1}
    )
    assert value == {
        "api_key": "[REDACTED]",
        "nested": [{"access_token": "[REDACTED]"}],
        "ok": 1,
    }


def test_state_update_is_atomic_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")
    runtime.update_component(
        "stella",
        "failed",
        pid=123,
        error="x" * 1000,
    )
    payload = json.loads((tmp_path / runtime.STATE_FILENAME).read_text(encoding="utf-8"))
    assert payload["components"]["stella"]["state"] == "failed"
    assert payload["components"]["stella"]["pid"] == 123
    error = payload["components"]["stella"]["error"]
    assert error["code"] == "component_failed"
    assert len(error["message"]) == 500


def test_runtime_status_has_stable_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")
    snapshot = runtime.snapshot()
    assert snapshot["schema_version"] == 1
    assert snapshot["instance_id"] == "test"
    assert set(snapshot["components"]) == {"stella", "llama", "onebot"}


def test_schema_fixtures_match_python_defaults():
    root = Path(__file__).parents[1] / "runtime-manager" / "schemas" / "fixtures"
    manifest = json.loads((root / "runtime-manifest.json").read_text(encoding="utf-8"))
    state = json.loads((root / "runtime-state.json").read_text(encoding="utf-8"))
    assert manifest["components"] == runtime.default_manifest()["components"]
    assert state["components"] == runtime.default_state()["components"]


def test_onebot_link_maps_to_degraded_without_restarting_stella(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "test")
    runtime.sync_onebot_status(
        {
            "enabled": True,
            "healthy": False,
            "mode": "forward",
            "endpoint_configured": True,
            "forward_reachable": False,
            "token_configured": True,
            "token_in_url": True,
            "token_consistent": False,
            "connected": False,
            "waiting_for_reconnect": True,
            "last_probe_ok": False,
        }
    )
    state = runtime.read_state()
    assert state["components"]["onebot"]["state"] == "degraded"
    assert state["desired"] == "running"
    diagnostics = state["components"]["onebot"]["diagnostics"]
    assert diagnostics["token_consistent"] is False
    assert diagnostics["waiting_for_reconnect"] is True
    assert "secret" not in json.dumps(diagnostics).lower()


def test_onebot_diagnostics_reject_non_object():
    with pytest.raises(ValueError):
        runtime.validate_state_payload(
            {
                "schema_version": 1,
                "instance_id": "test",
                "desired": "running",
                "updated_at": "now",
                "components": {
                    "onebot": {"state": "degraded", "diagnostics": "secret"}
                },
            }
        )


def test_execute_status_uses_shared_operation_envelope(monkeypatch):
    monkeypatch.setattr(process, "status", lambda: {"alive": False})
    result = runtime.execute_operation("status")
    assert result == {
        "ok": True,
        "operation": "status",
        "component": "stella",
        "data": {"alive": False},
    }


def test_execute_rejects_unsupported_component_owner():
    result = runtime.execute_operation("start", "llama")
    assert result["ok"] is False
    assert result["error"]["code"] == "unsupported_component_operation"


def test_execute_start_captures_legacy_output(monkeypatch):
    monkeypatch.setattr(probe, "collect", lambda: object())
    monkeypatch.setattr(checks, "run_all", lambda facts: [])
    monkeypatch.setattr(process, "start_detached", lambda: (print("started"), 0)[1])
    monkeypatch.setattr(runtime, "snapshot", lambda: {"components": {"stella": {"state": "starting"}}})
    result = runtime.execute_operation("start")
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["message"] == "started"
