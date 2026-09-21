# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skills 生命周期接线测试：bootstrap 装配、插件重载局部刷新。

``bot.py`` 本体 import 即初始化 NoneBot（coverage 配置也刻意排除它），
无法直接单测——bootstrap 里那段装配与 ``build_runtime`` 是同一份调用，
这里测 ``build_runtime`` 与 loader 侧的 ``_refresh_plugin_skills``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from astrbot_compat import loader
from skills.model import SandboxLimits

# ---------- Skills 运行时装配（bot bootstrap 的核心调用） ----------


@pytest.fixture
def _settings_for_runtime(monkeypatch, tmp_path):
    from config import settings

    overrides = {
        "SKILLS_BUILTIN_DIR": tmp_path / "builtin",
        "SKILLS_USER_DIR": tmp_path / "user",
        "ASTRBOT_PLUGINS_DIR": tmp_path / "plugins",
        "SKILLS_MANIFEST_MAX_BYTES": 262144,
        "SKILLS_MAX_CANDIDATES": 3,
        "SKILLS_EMBEDDING_ENABLED": False,
        "SKILLS_BODY_MAX_CHARS": 24000,
        "SKILLS_TOTAL_TIMEOUT": 120.0,
        "SKILLS_OUTPUT_MAX_CHARS": 2000,
        "SKILLS_ASSET_MAX_BYTES": 524288,
        "SANDBOX_BACKEND": "disabled",
        "SANDBOX_IMAGE": "python:3.12-slim",
        "SANDBOX_WORKSPACE_ROOT": tmp_path / "workspaces",
        "SANDBOX_CPU_LIMIT": 1.0,
        "SANDBOX_MEMORY_LIMIT": 256,
        "SANDBOX_PIDS_LIMIT": 64,
        "SANDBOX_TIMEOUT": 60.0,
        "SANDBOX_OUTPUT_MAX_CHARS": 65536,
        "SANDBOX_ARTIFACT_MAX_BYTES": 10485760,
        "SANDBOX_NETWORK_ENABLED": False,
        "SANDBOX_NETWORK_ALLOWLIST": [],
    }
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)
    yield tmp_path


def test_build_runtime_assembles_all_parts(_settings_for_runtime):
    import skills.runtime as skills_runtime

    try:
        rt = skills_runtime.build_runtime()
        assert rt is not None
        assert rt.catalog.snapshot is not None
        assert rt.orchestrator is not None
        # 默认禁用后端：executor 存在但后端是 disabled（fail-closed 而非缺席）
        executor = rt.orchestrator._executor
        assert executor is not None
        assert executor.backend == "disabled"
        assert rt.status()["installed"] is True
    finally:
        skills_runtime.reset()


def test_build_runtime_budgets_flow_into_orchestrator(_settings_for_runtime):
    import skills.runtime as skills_runtime
    from config import settings

    monkeypatch_overrides = {
        "SKILLS_TOTAL_TIMEOUT": 42.0,
        "SKILLS_OUTPUT_MAX_CHARS": 777,
        "SANDBOX_CPU_LIMIT": 2.0,
    }
    for key, value in monkeypatch_overrides.items():
        setattr(settings, key, value)
    try:
        rt = skills_runtime.build_runtime()
        orchestrator = rt.orchestrator
        assert orchestrator._total_timeout == 42.0
        assert orchestrator._output_max_chars == 777
        limits: SandboxLimits = orchestrator._limits
        assert limits.cpu == 2.0
    finally:
        skills_runtime.reset()


# ---------- 插件重载后的 Skills 局部刷新（loader 接线） ----------


def test_refresh_plugin_skills_noop_without_runtime(monkeypatch, tmp_path):
    import skills.runtime as skills_runtime

    monkeypatch.setattr(skills_runtime, "current", lambda: None)
    loader._refresh_plugin_skills(tmp_path)  # 不抛异常即为通过


def test_refresh_plugin_skills_refreshes_that_origin(monkeypatch, tmp_path):
    import skills.runtime as skills_runtime

    calls: list[Path] = []

    class _Catalog:
        def refresh_plugin(self, plugin_dir):
            calls.append(plugin_dir)
            return True

    monkeypatch.setattr(skills_runtime, "current", lambda: type("_RT", (), {"catalog": _Catalog()})())
    loader._refresh_plugin_skills(tmp_path / "my_plugin")
    assert calls == [tmp_path / "my_plugin"]


def test_refresh_plugin_skills_swallows_errors(monkeypatch, tmp_path):
    import skills.runtime as skills_runtime

    class _Catalog:
        def refresh_plugin(self, plugin_dir):
            raise RuntimeError("目录飞了")

    monkeypatch.setattr(skills_runtime, "current", lambda: type("_RT", (), {"catalog": _Catalog()})())
    loader._refresh_plugin_skills(tmp_path)  # 刷新失败不影响重载链路


def test_refresh_plugin_skills_none_dir_is_noop(monkeypatch):
    import skills.runtime as skills_runtime

    monkeypatch.setattr(skills_runtime, "current", lambda: None)
    loader._refresh_plugin_skills(None)  # 不抛异常
