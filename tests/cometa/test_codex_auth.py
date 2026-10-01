# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""codex_auth 单测：托管 home 解析、五态判定、自定义端点写入、spawn env。

文件面函数不依赖可选 SDK（CI 无 openai-codex 也全绿）；登录包装的 SDK
分支只在 SDK 存在的环境验证（importorskip 门）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # Py3.10 回退
    import tomli as tomllib

from cometa.backends import codex_auth
from cometa.backends.codex_auth import (
    AUTH_FILENAME,
    CODEX_API_KEY_ENV,
    CREDENTIAL_FILENAME,
    CodexAuthUnavailable,
    auth_state,
    backend_spawn_env,
    codex_home_for,
    default_stella_home,
    legacy_auth_home,
    migrate_legacy_auth,
    read_custom_credential,
    write_custom_endpoint,
)
from cometa.config import BackendConfig


def _backend(**env: str) -> BackendConfig:
    return BackendConfig(backend_id="codex_local", type="codex", env=dict(env))


@pytest.fixture(autouse=True)
def _isolated_legacy_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """把旧版认证位置指到空目录：开发机 ~/.codex 的真实登录不得影响判定。"""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "legacy-empty"))


class TestHomeResolution:
    def test_explicit_env_wins(self, tmp_path: Path) -> None:
        explicit = tmp_path / "declared-home"
        backend = _backend(CODEX_HOME=str(explicit))
        assert codex_home_for(backend, tmp_path) == explicit

    def test_default_under_stella_home_scoped_by_backend_id(self, tmp_path: Path) -> None:
        backend = _backend()
        home = codex_home_for(backend, tmp_path)
        assert home == tmp_path / "cometa" / "codex_home" / "codex_local"

    def test_backends_are_isolated(self, tmp_path: Path) -> None:
        a = codex_home_for(_backend(), tmp_path / "a")
        b = codex_home_for(
            BackendConfig(backend_id="codex_second", type="codex"), tmp_path / "a"
        )
        assert a != b

    def test_default_stella_home_honors_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("STELLA_HOME", str(tmp_path))
        assert default_stella_home() == tmp_path.resolve()


class TestAuthState:
    def test_none_when_nothing_configured(self, tmp_path: Path) -> None:
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "none"
        assert not state.ready
        assert "WebUI" in state.reason

    def test_ready_custom_after_write(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        write_custom_endpoint(
            home, base_url="https://relay.example.com/v1", api_key="sk-t", model="gpt-x"
        )
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "ready_custom"
        assert state.ready
        assert state.has_api_key

    def test_custom_config_without_credential_is_incomplete(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        write_custom_endpoint(
            home, base_url="https://relay.example.com/v1", api_key="", model="gpt-x"
        )
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "none"
        assert "凭据文件" in state.reason

    def test_ready_chatgpt_shape(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        home.mkdir(parents=True)
        (home / AUTH_FILENAME).write_text(
            json.dumps({"OPENAI_API_KEY": None, "auth_mode": "chatgpt",
                        "tokens": {"id_token": "x", "access_token": "y"}}),
            encoding="utf-8",
        )
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "ready_chatgpt"

    def test_ready_api_key_shape(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        home.mkdir(parents=True)
        # T-0 实证形状：{OPENAI_API_KEY, auth_mode}
        (home / AUTH_FILENAME).write_text(
            json.dumps({"OPENAI_API_KEY": "sk-x", "auth_mode": "api"}),
            encoding="utf-8",
        )
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "ready_api_key"

    def test_broken_auth_file_reports_none_with_reason(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        home.mkdir(parents=True)
        (home / AUTH_FILENAME).write_text("{not json", encoding="utf-8")
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "none"
        assert "损坏" in state.reason

    def test_legacy_detected_from_old_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        legacy = tmp_path / "old-home"
        legacy.mkdir()
        (legacy / AUTH_FILENAME).write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CODEX_HOME", str(legacy))
        assert legacy_auth_home() == legacy
        state = auth_state(_backend(), tmp_path)
        assert state.mode == "legacy"
        assert not state.ready

    def test_custom_wins_over_stale_auth_json(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        home.mkdir(parents=True)
        (home / AUTH_FILENAME).write_text(
            json.dumps({"OPENAI_API_KEY": "sk-old", "auth_mode": "api"}),
            encoding="utf-8",
        )
        write_custom_endpoint(
            home, base_url="https://relay.example.com/v1", api_key="sk-new", model="gpt-x"
        )
        assert auth_state(_backend(), tmp_path).mode == "ready_custom"


class TestCustomEndpointWrite:
    def test_writes_parseable_native_config(self, tmp_path: Path) -> None:
        home = tmp_path / "h"
        write_custom_endpoint(
            home, base_url="https://relay.example.com/v1", api_key="sk-t", model="gpt-x"
        )
        data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        assert data["model_provider"] == "stella_custom"
        assert data["model"] == "gpt-x"
        provider = data["model_providers"]["stella_custom"]
        assert provider["base_url"] == "https://relay.example.com/v1"
        assert provider["env_key"] == CODEX_API_KEY_ENV
        assert provider["wire_api"] == "responses"

    def test_escapes_toml_basic_strings(self, tmp_path: Path) -> None:
        home = tmp_path / "h"
        write_custom_endpoint(
            home, base_url=r"https://a.example.com/\v1", api_key="k", model='m"odel\\x'
        )
        data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        assert data["model"] == 'm"odel\\x'
        assert data["model_providers"]["stella_custom"]["base_url"] == r"https://a.example.com/\v1"

    def test_credential_roundtrip(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        write_custom_endpoint(
            home, base_url="https://r.example.com", api_key="sk-secret", model="m"
        )
        cred = read_custom_credential(_backend(), tmp_path)
        assert cred is not None
        assert cred["api_key"] == "sk-secret"
        assert cred["base_url"] == "https://r.example.com"

    def test_empty_api_key_writes_config_without_credential(self, tmp_path: Path) -> None:
        home = tmp_path / "h"
        write_custom_endpoint(
            home, base_url="https://r.example.com", api_key="", model="m"
        )
        assert (home / "config.toml").is_file()
        assert not (home / CREDENTIAL_FILENAME).exists()

    def test_validations(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            write_custom_endpoint(tmp_path, base_url="  ", api_key="k", model="m")
        with pytest.raises(ValueError):
            write_custom_endpoint(tmp_path, base_url="https://x", api_key="k", model="")


class TestSpawnEnv:
    def test_toml_env_preserved_and_home_injected(self, tmp_path: Path) -> None:
        backend = _backend(HTTP_PROXY="http://127.0.0.1:7890")
        env = backend_spawn_env(backend, tmp_path)
        assert env["HTTP_PROXY"] == "http://127.0.0.1:7890"
        assert env["CODEX_HOME"] == str(tmp_path / "cometa" / "codex_home" / "codex_local")
        assert CODEX_API_KEY_ENV not in env

    def test_custom_key_injected_when_configured(self, tmp_path: Path) -> None:
        home = codex_home_for(_backend(), tmp_path)
        write_custom_endpoint(
            home, base_url="https://r.example.com", api_key="sk-live", model="m"
        )
        env = backend_spawn_env(_backend(), tmp_path)
        assert env[CODEX_API_KEY_ENV] == "sk-live"

    def test_explicit_codex_home_respected(self, tmp_path: Path) -> None:
        explicit = tmp_path / "declared"
        backend = _backend(CODEX_HOME=str(explicit))
        env = backend_spawn_env(backend, tmp_path)
        assert env["CODEX_HOME"] == str(explicit)


class TestMigrateLegacy:
    def test_migrate_copies_auth_and_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        legacy = tmp_path / "old"
        legacy.mkdir()
        (legacy / AUTH_FILENAME).write_text('{"OPENAI_API_KEY": "sk-old"}', encoding="utf-8")
        (legacy / "config.toml").write_text('model = "gpt-x"\n', encoding="utf-8")
        monkeypatch.setenv("CODEX_HOME", str(legacy))
        backend = _backend()
        target = migrate_legacy_auth(backend, tmp_path)
        migrated = json.loads(target.read_text(encoding="utf-8"))
        assert migrated["OPENAI_API_KEY"] == "sk-old"
        assert (target.parent / "config.toml").is_file()
        assert auth_state(backend, tmp_path).mode == "ready_api_key"

    def test_migrate_refuses_when_managed_auth_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        legacy = tmp_path / "old"
        legacy.mkdir()
        (legacy / AUTH_FILENAME).write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CODEX_HOME", str(legacy))
        backend = _backend()
        home = codex_home_for(backend, tmp_path)
        home.mkdir(parents=True)
        (home / AUTH_FILENAME).write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError):
            migrate_legacy_auth(backend, tmp_path)

    def test_migrate_without_legacy_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            migrate_legacy_auth(_backend(), tmp_path)


class TestSdkWrappers:
    """登录包装只测 SDK 缺失分支（CI 无 SDK 也绿）；真流需实机（T-0 已证）。"""

    @pytest.mark.asyncio
    async def test_login_without_sdk_raises_unavailable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(codex_auth, "_import_sdk", lambda: None)
        with pytest.raises(CodexAuthUnavailable):
            await codex_auth.login_with_api_key(_backend(), "sk-x", tmp_path)
        with pytest.raises(CodexAuthUnavailable):
            await codex_auth.start_device_login(_backend(), tmp_path)
        with pytest.raises(CodexAuthUnavailable):
            await codex_auth.account_status(_backend(), tmp_path)

    @pytest.mark.asyncio
    async def test_login_rejects_empty_key(self, tmp_path: Path) -> None:
        # SDK 存在与否都先校验参数：本地开发机装了 SDK，也能测参数分支
        if codex_auth._import_sdk() is None:
            pytest.skip("SDK 缺失，参数校验分支由 SDK 分支覆盖")
        with pytest.raises(ValueError):
            await codex_auth.login_with_api_key(_backend(), "  ", tmp_path)
