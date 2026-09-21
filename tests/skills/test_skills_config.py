# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skills/Sandbox 配置校验测试（plan §6.4：负数、非法路径、网络无白名单拒绝）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import settings


def _errors(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> list[str]:
    """在打补丁后的配置上跑校验器，返回错误清单。"""
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)
    return settings.validate_skills_config()


class TestDefaultsAreValid:
    def test_default_config_passes(self):
        assert settings.validate_skills_config() == []


class TestNumericValidation:
    def test_negative_and_zero_rejected(self, monkeypatch: pytest.MonkeyPatch):
        for key in (
            "SANDBOX_CPU_LIMIT",
            "SANDBOX_MEMORY_LIMIT",
            "SANDBOX_PIDS_LIMIT",
            "SANDBOX_TIMEOUT",
            "SANDBOX_OUTPUT_MAX_CHARS",
            "SANDBOX_ARTIFACT_MAX_BYTES",
            "SKILLS_BODY_MAX_CHARS",
            "SKILLS_MANIFEST_MAX_BYTES",
            "SKILLS_ASSET_MAX_BYTES",
            "SKILLS_ASSET_TOTAL_MAX_BYTES",
            "SKILLS_TOTAL_TIMEOUT",
            "SKILLS_OUTPUT_MAX_CHARS",
        ):
            assert _errors(monkeypatch, **{key: 0}), f"{key}=0 应被拒绝"
        assert _errors(monkeypatch, SKILLS_MAX_CANDIDATES=-1)

    def test_asset_single_le_total(self, monkeypatch: pytest.MonkeyPatch):
        errors = _errors(
            monkeypatch, SKILLS_ASSET_MAX_BYTES=100, SKILLS_ASSET_TOTAL_MAX_BYTES=50
        )
        assert any("SKILLS_ASSET_MAX_BYTES" in e for e in errors)


class TestNetworkValidation:
    def test_network_without_allowlist_rejected(self, monkeypatch: pytest.MonkeyPatch):
        errors = _errors(
            monkeypatch, SANDBOX_NETWORK_ENABLED=True, SANDBOX_NETWORK_ALLOWLIST=[]
        )
        assert any("SANDBOX_NETWORK_ALLOWLIST" in e for e in errors)

    def test_network_with_allowlist_passes(self, monkeypatch: pytest.MonkeyPatch):
        errors = _errors(
            monkeypatch,
            SANDBOX_NETWORK_ENABLED=True,
            SANDBOX_NETWORK_ALLOWLIST=["api.example.com:443"],
        )
        assert errors == []


class TestWorkspaceRootValidation:
    def test_filesystem_root_rejected(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        errors = _errors(monkeypatch, SANDBOX_WORKSPACE_ROOT=Path(tmp_path.anchor))
        assert any("SANDBOX_WORKSPACE_ROOT" in e for e in errors)

    def test_project_and_home_root_rejected(self, monkeypatch: pytest.MonkeyPatch):
        assert _errors(monkeypatch, SANDBOX_WORKSPACE_ROOT=settings.PROJECT_ROOT)
        assert _errors(monkeypatch, SANDBOX_WORKSPACE_ROOT=settings.STELLA_HOME)

    def test_plugins_dir_rejected(self, monkeypatch: pytest.MonkeyPatch):
        assert _errors(monkeypatch, SANDBOX_WORKSPACE_ROOT=settings.ASTRBOT_PLUGINS_DIR)

    def test_normal_dir_passes(self, monkeypatch: pytest.MonkeyPatch, tmp_path):
        errors = _errors(monkeypatch, SANDBOX_WORKSPACE_ROOT=tmp_path / "workspaces")
        assert errors == []
