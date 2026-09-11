# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deploy import runtime


def test_default_manifest_has_optional_components():
    manifest = runtime.default_manifest()
    assert manifest["schema_version"] == 1
    assert set(manifest["components"]) == {"stella", "llama", "onebot"}
    assert manifest["components"]["llama"]["enabled"] is False


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
