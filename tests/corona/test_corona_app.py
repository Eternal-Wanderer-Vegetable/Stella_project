# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Corona control-app import fence, auth compatibility, and SPA hosting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from corona.app import create_corona_app
from corona.bootstrap import prepare_corona_bootstrap
from stella_bootstrap.config import build_config_revision, write_revision

ROOT = Path(__file__).resolve().parents[2]


def _bootstrap(tmp_path: Path, *, webui_enabled: bool = True, serve_dist: bool = False):
    home = tmp_path / "home"
    home.mkdir()
    public_port = "18765"
    (home / ".env").write_text(
        f"HOST=127.0.0.1\nPORT={public_port}\n"
        f"WEBUI_ENABLED={'true' if webui_enabled else 'false'}\n"
        f"WEBUI_SERVE_DIST={'true' if serve_dist else 'false'}\n"
        "WEBUI_TOKEN_TTL_HOURS=168\nWEBUI_LOGIN_RATELIMIT_PER_MIN=5\n",
        encoding="utf-8",
    )
    revision = build_config_revision(
        project_root=ROOT,
        stella_home=home,
        external_environment={"DB_PATH": str(tmp_path / "db" / "agent_memory.db")},
    )
    path = write_revision(home, "cn03-app-test", revision)
    return prepare_corona_bootstrap(
        {
            "STELLA_CONFIG_REVISION_FILE": str(path),
            "STELLA_INSTANCE_ID": "cn03-app-test",
        },
        project_root=ROOT,
    )


class _StubSupervisor:
    def __init__(self) -> None:
        self.snapshot = SimpleNamespace(
            phase="stopped",
            public=lambda: {"phase": self.snapshot.phase, "desired": "running"},
        )
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True
        self.snapshot.phase = "failed"

    async def stop(self):
        self.stopped = True


def test_corona_app_import_does_not_load_business_packages(tmp_path: Path) -> None:
    code = """
import sys
import corona.app
banned = ('config', 'core', 'memory', 'capability', 'cometa', 'knowledge', 'gravitas', 'astrbot_compat', 'nonebot', 'stella_project.plugins.bot_main')
loaded = sorted(name for name in sys.modules if any(name == item or name.startswith(item + '.') for item in banned))
assert not loaded, loaded
"""
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if os.environ.get(key)
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_corona_auth_uses_existing_credentials_and_separate_audit(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path)
    supervisor = _StubSupervisor()
    app = create_corona_app(bootstrap, supervisor)
    with TestClient(app) as client:
        status = client.get("/api/v1/auth/setup-status")
        assert status.status_code == 200
        assert status.json()["data"]["setup_required"] is True

        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "correct horse battery"},
        )
        assert setup.status_code == 200
        token = setup.json()["data"]["token"]
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/api/v1/system/core").status_code == 200
        assert supervisor.started

    auth_file = bootstrap.stella_home / "webui" / "auth.json"
    assert auth_file.is_file()
    audit_path = bootstrap.log_dir / "corona_auth_audit.jsonl"
    audit_text = audit_path.read_text(encoding="utf-8")
    assert "correct horse battery" not in audit_text
    assert token not in audit_text
    assert json.loads(audit_text.splitlines()[0])["action"] == "auth.setup"
    assert supervisor.stopped


def test_corona_static_fallback_uses_explicit_dist_only(tmp_path: Path) -> None:
    bootstrap = replace(_bootstrap(tmp_path), project_root=tmp_path, serve_dist=True)
    dist = tmp_path / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>corona-dist</html>", encoding="utf-8")
    supervisor = _StubSupervisor()
    app = create_corona_app(bootstrap, supervisor)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "corona-dist" in response.text
        health = client.get("/_corona/v1/health")
        assert health.status_code == 404
        assert health.headers["content-type"].startswith("application/json")
        assert health.json()["error"]["code"] == "not_found"
        assert "corona-dist" in client.get("/settings").text
        assert client.get("/api/v1/auth/setup-status").status_code == 200


def test_disabled_webui_keeps_supervisor_and_protects_local_health(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path, webui_enabled=False)
    supervisor = _StubSupervisor()
    app = create_corona_app(bootstrap, supervisor)
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/setup-status").status_code == 404
        health = client.get("/_corona/v1/health")
        assert health.status_code == 404
        assert health.json()["error"]["code"] == "not_found"
        assert supervisor.started
    assert supervisor.stopped
