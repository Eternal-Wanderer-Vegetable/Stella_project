# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest
from dotenv.main import DotEnv

from stella_bootstrap.config import (
    ConfigBuildError,
    build_config_revision,
    load_revision,
    write_revision,
)
from stella_bootstrap.env import parse_dotenv
from stella_contracts.config import ConfigRevisionError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _revision(home: Path, *, external: dict[str, str] | None = None):
    return build_config_revision(
        project_root=PROJECT_ROOT,
        stella_home=home,
        external_environment={} if external is None else external,
    )


def test_dotenv_parser_matches_installed_python_dotenv(monkeypatch):
    """Capture quoting, comments, duplicate keys, interpolation and CRLF semantics."""
    text = (
        "export CN01_DUP=first\r\n"
        "CN01_DUP=last\r\n"
        'CN01_DOUBLE="hello # world"\r\n'
        "CN01_INLINE=word # comment\r\n"
        "CN01_HASH=#literal\r\n"
        "CN01_EMPTY=\r\n"
        "CN01_FROM_DUP=${CN01_DUP}\r\n"
        "CN01_FROM_EXTERNAL=${CN01_EXTERNAL}\r\n"
        "CN01_DEFAULT=${CN01_MISSING:-fallback}\r\n"
        'CN01_JSON=["one", "two"]\r\n'
        "CN01_NO_VALUE\r\n"
        "not a valid assignment\r\n"
    )
    monkeypatch.setenv("CN01_DUP", "inherited")
    monkeypatch.setenv("CN01_EXTERNAL", "outside")
    environment = dict(os.environ)

    for override in (False, True):
        actual = parse_dotenv(text, environment=environment, override=override)
        expected = DotEnv(
            dotenv_path=None,
            stream=StringIO(text),
            override=override,
            interpolate=True,
        ).dict()
        assert actual == {key: value for key, value in expected.items() if value is not None}
        assert actual["CN01_JSON"] == '["one", "two"]'
        assert actual["CN01_DEFAULT"] == "fallback"


def test_config_revision_applies_source_order_and_keeps_unknown_keys(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    (home / ".env").write_text(
        "ENVIRONMENT=prod\n"
        "BASE_VALUE=from-file\n"
        "BASE_EXPANDED=${BASE_VALUE}\n"
        "EXTERNAL_OVERRIDE=from-file\n"
        "PORT=8080\n"
        "STELLA_HOME=/wrong/from/file\n"
        "PLUGIN_PRIVATE_SETTING=keep-me\n",
        encoding="utf-8",
    )
    (home / ".env.prod").write_text(
        "BASE_VALUE=from-prod\n"
        "PORT=19002\n"
        "PROFILE_EXPANDED=${BASE_VALUE}\n"
        "STELLA_LAUNCH_TOKEN=must-not-be-config\n",
        encoding="utf-8",
    )
    external = {
        "BASE_VALUE": "from-external",
        "EXTERNAL_OVERRIDE": "from-external",
        "EXTERNAL_ONLY": "from-parent",
        "PORT": "19001",
        "STELLA_HOME": "/wrong/from/parent",
        "STELLA_LAUNCH_TOKEN": "parent-token",
        "PATH": "/runtime/path",
    }

    revision = _revision(home, external=external)

    assert revision.environment == "prod"
    assert revision.values["BASE_VALUE"] == "from-prod"
    assert revision.values["BASE_EXPANDED"] == "from-external"
    assert revision.values["PROFILE_EXPANDED"] == "from-prod"
    assert revision.values["PORT"] == "19002"
    assert revision.values["EXTERNAL_OVERRIDE"] == "from-external"
    assert revision.sources["EXTERNAL_OVERRIDE"] == "external_environment"
    assert revision.external_override_keys == ("EXTERNAL_OVERRIDE",)
    assert revision.values["PLUGIN_PRIVATE_SETTING"] == "keep-me"
    assert "STELLA_HOME" not in revision.values
    assert "STELLA_LAUNCH_TOKEN" not in revision.values
    assert "PATH" not in revision.values
    assert revision.source_digests.keys() == {".env", ".env.prod"}


def test_config_revision_rejects_invalid_known_values_and_preserves_raw_file(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    raw = 'MESSAGE_CLEANUP_HOUR=not-an-integer\nPLUGIN_UNDOCUMENTED_KEY="kept as text"\n'
    (home / ".env").write_text(raw, encoding="utf-8")

    with pytest.raises(ConfigBuildError, match="MESSAGE_CLEANUP_HOUR"):
        _revision(home)

    assert (home / ".env").read_text(encoding="utf-8") == raw


def test_revision_is_private_write_once_and_public_metadata_redacts_values(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    (home / ".env").write_text("LLM_ENDPOINT_CHAT_API_KEY=top-secret-value\n", encoding="utf-8")
    revision = _revision(home)
    path = write_revision(home, "demo-instance", revision)

    assert load_revision(path) == revision
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    public = json.dumps(revision.public_metadata(), sort_keys=True)
    assert "top-secret-value" not in public
    assert revision.revision_id in public
    with pytest.raises(TypeError):
        load_revision(path).values["LLM_ENDPOINT_CHAT_API_KEY"] = "modified"
    with pytest.raises(FileExistsError):
        write_revision(home, "demo-instance", revision)


def test_revision_loader_rejects_broad_file_permissions(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX mode-bit behavior is not available on Windows")
    home = tmp_path / "data"
    home.mkdir()
    revision = _revision(home)
    path = write_revision(home, "demo-instance", revision)
    path.chmod(0o644)

    with pytest.raises(ConfigRevisionError, match="permissions"):
        load_revision(path)


def test_revision_loader_rejects_broad_private_parent_permissions(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX mode-bit behavior is not available on Windows")
    home = tmp_path / "data"
    home.mkdir()
    path = write_revision(home, "demo-instance", _revision(home))
    (home / ".stella").chmod(0o755)

    with pytest.raises(ConfigRevisionError, match="directory permissions"):
        load_revision(path)


def _managed_settings(revision_path: Path, cwd: Path) -> dict:
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / ".env").write_text("REVISION_MARKER=from-cwd-dotenv\nLLM_TIMEOUT=333\n", encoding="utf-8")
    env = {
        "PYTHONPATH": str(PROJECT_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "STELLA_CONFIG_REVISION_FILE": str(revision_path),
        "STELLA_HOME": str(cwd / "wrong-home"),
        "REVISION_MARKER": "inherited-poison",
        "LLM_TIMEOUT": "999",
    }
    if os.name == "nt":
        env["PATH"] = os.environ.get("PATH", "")
        if os.environ.get("SYSTEMROOT"):
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    script = (
        "import json, pathlib, config.settings as settings; "
        "print(json.dumps({'marker': settings._getenv('REVISION_MARKER', 'default'), "
        "'timeout': settings.LLM_TIMEOUT, 'home': str(settings.STELLA_HOME), "
        "'home_env': settings._getenv('STELLA_HOME', 'missing'), "
        "'cwd': str(pathlib.Path.cwd()), "
        "'empty': settings._env('CN01_EMPTY', 'fallback'), "
        "'inherited': settings._env_inherit('CN01_EMPTY', 'inherited-value'), "
        "'removed': settings._env('REMOVED_CONFIG', 'default'), "
        "'relative': str(settings._env_path('CN01_RELATIVE_PATH', pathlib.Path('fallback')))}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_managed_settings_read_two_revisions_without_cwd_or_parent_leakage(tmp_path):
    home = tmp_path / "data"
    home.mkdir()
    (home / ".env").write_text(
        "REVISION_MARKER=revision-one\n"
        "LLM_TIMEOUT=11.5\n"
        "CN01_EMPTY=\n"
        "CN01_RELATIVE_PATH=relative/logs\n"
        "REMOVED_CONFIG=present-in-first-revision\n",
        encoding="utf-8",
    )
    first = _revision(home)
    first_path = write_revision(home, "demo-instance", first)

    (home / ".env").write_text(
        "REVISION_MARKER=revision-two\nLLM_TIMEOUT=22.5\n", encoding="utf-8"
    )
    second = _revision(home)
    second_path = write_revision(home, "demo-instance", second)
    cwd = tmp_path / "synthetic-project-cwd"

    first_settings = _managed_settings(first_path, cwd)
    second_settings = _managed_settings(second_path, cwd)

    assert first_settings == {
        "marker": "revision-one",
        "timeout": 11.5,
        "home": str(home.resolve()),
        "home_env": str(home.resolve()),
        "cwd": str(cwd),
        "empty": "",
        "inherited": "inherited-value",
        "removed": "present-in-first-revision",
        "relative": str((cwd / "relative" / "logs").resolve()),
    }
    assert second_settings == {
        "marker": "revision-two",
        "timeout": 22.5,
        "home": str(home.resolve()),
        "home_env": str(home.resolve()),
        "cwd": str(cwd),
        "empty": "fallback",
        "inherited": "inherited-value",
        "removed": "default",
        "relative": "fallback",
    }


def test_bootstrap_imports_do_not_load_legacy_runtime_packages(tmp_path):
    script = (
        "import importlib, json, sys; "
        "[importlib.import_module(name) for name in ("
        "'stella_bootstrap.home', 'stella_bootstrap.identity', "
        "'stella_bootstrap.adapter_names', 'stella_bootstrap.env', "
        "'stella_bootstrap.env_schema', 'stella_bootstrap.config')]; "
        "forbidden=('config', 'core', 'memory', 'capability', 'cometa', "
        "'knowledge', 'gravitas', 'astrbot_compat', 'nonebot', 'bot_main'); "
        "print(json.dumps(sorted(name for name in sys.modules if any("
        "name == prefix or name.startswith(prefix + '.') for prefix in forbidden))))"
    )
    env = {
        "PYTHONPATH": str(PROJECT_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt" and os.environ.get("SYSTEMROOT"):
        env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(result.stdout) == []
