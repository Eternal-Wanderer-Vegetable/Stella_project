# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

"""Runtime/Desktop/Docker contract-level end-to-end scenarios.

These tests deliberately stop at the shared state boundary. They exercise the
same transitions that the Windows GUI, CLI and Docker status adapters consume,
without requiring a real llama model or a logged-in QQ account.
"""

from __future__ import annotations

import json
from pathlib import Path

from deploy import checks, runtime
from deploy.models import Snapshot


def _runtime_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "INSTANCE_RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime, "INSTANCE_ID", "e2e")
    runtime.write_manifest()
    runtime.update_component("stella", "healthy", pid=1234, desired="running")


def _component_states():
    return {
        name: component["state"]
        for name, component in runtime.snapshot()["components"].items()
    }


def test_ai_off_keeps_basic_bot_healthy(monkeypatch, tmp_path):
    _runtime_fixture(monkeypatch, tmp_path)

    states = _component_states()

    assert states == {"stella": "healthy", "llama": "disabled", "onebot": "disabled"}


def test_missing_llama_is_a_non_blocking_degradation(monkeypatch, tmp_path):
    _runtime_fixture(monkeypatch, tmp_path)
    manifest = runtime.default_manifest()
    manifest["components"]["llama"]["enabled"] = True
    manifest["components"]["llama"]["config"]["model"]["path"] = str(
        tmp_path / "missing.gguf"
    )
    runtime.write_manifest(manifest)
    runtime.update_component("llama", "failed", error="model is missing")

    readiness = {
        "ready": False,
        "model_path": str(tmp_path / "missing.gguf"),
        "model_exists": False,
        "port_in_use": False,
        "models_reachable": False,
        "runtime_state": "failed",
        "error": "connection refused",
    }
    result = checks.check_llama_readiness(
        Snapshot(llama_readiness=readiness)
    )

    assert result is not None and result.level == "warn"
    assert _component_states()["stella"] == "healthy"
    assert _component_states()["llama"] == "failed"


def test_napcat_not_logged_in_does_not_stop_stella(monkeypatch, tmp_path):
    _runtime_fixture(monkeypatch, tmp_path)
    runtime.sync_onebot_status(
        {
            "enabled": True,
            "healthy": False,
            "mode": "reverse",
            "endpoint_configured": True,
            "forward_reachable": None,
            "reverse_port_in_use": True,
            "token_configured": True,
            "token_in_url": False,
            "token_consistent": None,
            "connected": False,
            "waiting_for_reconnect": True,
            "last_probe_ok": False,
        }
    )

    states = _component_states()

    assert states["stella"] == "healthy"
    assert states["onebot"] == "degraded"
    assert runtime.snapshot()["components"]["onebot"]["diagnostics"][
        "waiting_for_reconnect"
    ]


def test_onebot_disconnect_waits_for_reconnect_without_restart(
    monkeypatch, tmp_path
):
    _runtime_fixture(monkeypatch, tmp_path)
    runtime.sync_onebot_status(
        {
            "enabled": True,
            "healthy": False,
            "mode": "reverse",
            "endpoint_configured": True,
            "forward_reachable": None,
            "reverse_port_in_use": True,
            "token_configured": False,
            "token_in_url": False,
            "token_consistent": None,
            "connected": True,
            "waiting_for_reconnect": True,
            "last_probe_ok": False,
        }
    )

    assert _component_states()["stella"] == "healthy"
    assert _component_states()["onebot"] == "degraded"
    assert runtime.read_state()["desired"] == "running"


def test_degraded_status_golden_has_no_credentials(monkeypatch, tmp_path):
    _runtime_fixture(monkeypatch, tmp_path)
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
    snapshot = runtime.snapshot()
    golden_path = Path(__file__).parent / "goldens" / "runtime-degraded.json"
    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    actual = {
        "schema_version": snapshot["schema_version"],
        "components": snapshot["components"],
    }

    assert actual == golden
    assert "secret" not in json.dumps(actual).lower()


def test_compose_declares_optional_components_and_llama_healthcheck():
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert 'profiles: ["llama"]' in compose
    assert "com.stella.runtime.component: stella" in compose
    assert "com.stella.runtime.component: llama" in compose
    assert "com.stella.runtime.component: onebot" in compose
    assert "http://127.0.0.1:8081/v1/models" in compose
    assert "container_name: napcat" in compose
