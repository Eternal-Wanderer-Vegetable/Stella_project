# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa 配置层测试：env 解析、TOML 加载、fail-closed 校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from cometa.config import (
    AccessConfig,
    CometaConfig,
    CometaConfigError,
    LimitsConfig,
)


def _env(**overrides) -> dict[str, str]:
    env = {"STELLA_HOME": str(Path(__file__).parent), "COMETA_ENABLED": "true"}
    env.update({k: v for k, v in overrides.items() if v is not None})
    return env


class TestEnvLoading:
    def test_disabled_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STELLA_HOME", str(tmp_path))
        monkeypatch.delenv("COMETA_ENABLED", raising=False)
        cfg = CometaConfig.load(env={})
        assert cfg.enabled is False

    def test_enabled_and_paths(self, tmp_path):
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.enabled is True
        assert cfg.db_path == tmp_path / "cometa" / "tasks.db"
        assert cfg.artifacts_dir == cfg.db_path.parent / "artifacts"

    def test_db_path_override_relative_to_home(self, tmp_path):
        cfg = CometaConfig.load(
            env=_env(COMETA_DB_PATH="custom/tasks.db", STELLA_HOME=str(tmp_path))
        )
        assert cfg.db_path == tmp_path / "custom" / "tasks.db"

    def test_numeric_and_mode_defaults(self):
        cfg = CometaConfig.load(env=_env())
        assert cfg.delegation_mode == "explicit"
        assert cfg.max_concurrent == 2
        assert cfg.task_timeout_seconds == 1800.0
        assert cfg.result_max_chars == 2000

    def test_invalid_delegation_mode_falls_back(self):
        cfg = CometaConfig.load(env=_env(COMETA_DELEGATION_MODE="yolo"))
        assert cfg.delegation_mode == "explicit"

    def test_max_concurrent_floor_is_one(self):
        cfg = CometaConfig.load(env=_env(COMETA_MAX_CONCURRENT="0"))
        assert cfg.max_concurrent == 1


class TestTomlLoading:
    def _write(self, tmp_path: Path, body: str) -> Path:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        path = config_dir / "cometa.toml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_full_toml(self, tmp_path):
        # 仓库路径用 tmp_path 构造：Windows 盘符路径（E:/...）在 POSIX 上是
        # 相对路径，resolve() 会拼上 cwd 导致断言失败（CI 实测）
        repo = (tmp_path / "repo").resolve()
        self._write(
            tmp_path,
            f"""
schema_version = 1

[limits]
per_user_active = 3
per_group_active = 5
retention_days = 14

[backends.codex_local]
type = "codex"
executable = "C:/bin/codex.exe"
capabilities = ["code.edit"]

[workspaces.stella]
repository = "{repo.as_posix()}"
base_ref = "HEAD"

[profiles.coding]
backend = "codex_local"
workspace = "stella"
allow_workspace_write = true

[access]
qq_user_ids = [111, 222]
qq_group_ids = [333]
operator_user_ids = [111]
""",
        )
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.config_hash
        assert "codex_local" in cfg.backends
        assert cfg.backends["codex_local"].capabilities == ["code.edit"]
        assert cfg.workspaces["stella"].repository == repo
        assert cfg.profiles["coding"].allow_workspace_write is True
        assert cfg.access.qq_user_ids == {111, 222}
        assert cfg.limits.per_user_active == 3

    def test_unknown_top_key_rejected(self, tmp_path):
        self._write(tmp_path, "schema_version = 1\nwhatever = 1\n")
        with pytest.raises(CometaConfigError, match="未知顶层键"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_unknown_limits_key_rejected(self, tmp_path):
        self._write(tmp_path, "[limits]\nnope = 1\n")
        with pytest.raises(CometaConfigError, match="未知键"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_profile_reference_validation(self, tmp_path):
        self._write(tmp_path, "[profiles.x]\nbackend = 'missing'\n")
        with pytest.raises(CometaConfigError, match="未定义的后端"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_workspace_mode_restricted(self, tmp_path):
        self._write(tmp_path, "[workspaces.w]\nrepository = 'C:/r'\nmode = 'sandbox'\n")
        with pytest.raises(CometaConfigError, match="mode"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_broken_toml_raises(self, tmp_path):
        self._write(tmp_path, "schema_version = = 1")
        with pytest.raises(CometaConfigError, match="解析失败"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_wrong_schema_version_rejected(self, tmp_path):
        self._write(tmp_path, "schema_version = 99")
        with pytest.raises(CometaConfigError, match="schema_version"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_access_empty_means_unauthorized(self, tmp_path):
        self._write(tmp_path, "[access]\nqq_user_ids = []\n")
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.access.qq_user_ids == set()

    def test_access_invalid_int_rejected(self, tmp_path):
        self._write(tmp_path, "[access]\nqq_user_ids = ['abc']\n")
        with pytest.raises(CometaConfigError, match="非法整数"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))


class TestDefaults:
    def test_limits_defaults_match_design(self):
        limits = LimitsConfig()
        assert limits.per_user_active == 1
        assert limits.per_group_active == 2
        assert limits.input_wait_seconds == 600.0
        assert limits.retention_days == 7.0

    def test_access_defaults_empty(self):
        access = AccessConfig()
        assert access.qq_user_ids == set()
        assert access.qq_group_ids == set()
        assert access.operator_user_ids == set()


class TestFakeBehavior:
    """fake_behavior：仅 type="fake" 可用的人工验收脚本键（本分支扩展）。"""

    def _write(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "cometa.toml").write_text(body, encoding="utf-8")

    def test_valid_values_accepted(self, tmp_path):
        self._write(
            tmp_path,
            '[backends.demo]\ntype = "fake"\nfake_behavior = "complete"\n',
        )
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.backends["demo"].fake_behavior == "complete"

    def test_rejected_on_non_fake_backend(self, tmp_path):
        self._write(
            tmp_path,
            '[backends.codex_local]\ntype = "codex"\nfake_behavior = "complete"\n',
        )
        with pytest.raises(CometaConfigError, match="fake"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))

    def test_rejects_unknown_value(self, tmp_path):
        self._write(
            tmp_path,
            '[backends.demo]\ntype = "fake"\nfake_behavior = "explode"\n',
        )
        with pytest.raises(CometaConfigError, match="fake_behavior"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))


class TestDefaultProfile:
    """default_profile：显式委派命令（QQ/WebUI 表单无 profile 槽位）的默认路由。"""

    def _write(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "cometa.toml").write_text(body, encoding="utf-8")

    def test_default_profile_parsed_and_validated(self, tmp_path):
        self._write(
            tmp_path,
            'default_profile = "coding"\n'
            '[backends.f]\ntype = "fake"\n'
            "[profiles.coding]\nbackend = \"f\"\n",
        )
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.default_profile == "coding"

    def test_default_profile_unknown_rejected(self, tmp_path):
        self._write(
            tmp_path,
            'default_profile = "ghost"\n'
            '[backends.f]\ntype = "fake"\n'
            "[profiles.coding]\nbackend = \"f\"\n",
        )
        with pytest.raises(CometaConfigError, match="default_profile"):
            CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))


class TestBackendEnv:
    """[backends.<id>.env]：后端子进程的环境透传（代理等部署级配置）。"""

    def _write(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "cometa.toml").write_text(body, encoding="utf-8")

    def test_env_parsed(self, tmp_path):
        self._write(
            tmp_path,
            '[backends.c]\ntype = "codex"\n\n[backends.c.env]\n'
            'HTTP_PROXY = "http://127.0.0.1:7890"\n',
        )
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.backends["c"].env == {"HTTP_PROXY": "http://127.0.0.1:7890"}

    def test_env_empty_by_default(self, tmp_path):
        self._write(tmp_path, '[backends.f]\ntype = "fake"\n')
        cfg = CometaConfig.load(env=_env(STELLA_HOME=str(tmp_path)))
        assert cfg.backends["f"].env == {}
