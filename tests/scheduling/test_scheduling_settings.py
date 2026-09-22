# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""SCHEDULING_* 配置项的存在性、默认值与 .env.example 披露的钉底。

钉两件事：
1. settings 里的键与默认值不漂移（改默认值必须 conscious 地改这里）；
2. .env.example 里登记的键与 settings 定义键一致——新增键忘写示例文件时红。
"""

from __future__ import annotations

from pathlib import Path

import config.settings as settings

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_DEFAULTS = {
    "SCHEDULING_ENABLED": False,
    "SCHEDULING_WORKER_LEASE_TTL": 300,
    "SCHEDULING_TICK_INTERVAL": 30,
    "SCHEDULING_DAILY_GROUP_RUN_CAP": 40,
    "SCHEDULING_MAX_TASKS_PER_GROUP": 8,
    "SCHEDULING_MAX_TASKS_PER_USER": 3,
    "SCHEDULING_RUN_TIMEOUT_SECONDS": 300,
    "SCHEDULING_MAX_MODEL_ROUNDS": 4,
    "SCHEDULING_MAX_TOOL_CALLS": 8,
    "SCHEDULING_OUTPUT_MAX_CHARS": 1200,
    "SCHEDULING_CONTEXT_MAX_CHARS": 1200,
    "SCHEDULING_SEND_TIMEOUT": 30.0,
    "SCHEDULING_GLOBAL_ADMINS": set(),
}


def test_scheduling_settings_defaults():
    assert settings.SCHEDULING_ENABLED is False  # 刻意默认关闭
    assert settings.SCHEDULING_DB_PATH == settings.STELLA_HOME / "scheduling" / "tasks.db"
    for key, expected in _EXPECTED_DEFAULTS.items():
        value = getattr(settings, key)
        assert value == expected, f"{key} 默认值漂移：{value!r} != {expected!r}"


def test_scheduling_settings_types():
    assert isinstance(settings.SCHEDULING_DB_PATH, Path)
    for key in (
        "SCHEDULING_WORKER_LEASE_TTL",
        "SCHEDULING_TICK_INTERVAL",
        "SCHEDULING_DAILY_GROUP_RUN_CAP",
        "SCHEDULING_MAX_TASKS_PER_GROUP",
        "SCHEDULING_MAX_TASKS_PER_USER",
        "SCHEDULING_RUN_TIMEOUT_SECONDS",
        "SCHEDULING_MAX_MODEL_ROUNDS",
        "SCHEDULING_MAX_TOOL_CALLS",
        "SCHEDULING_OUTPUT_MAX_CHARS",
    ):
        assert isinstance(getattr(settings, key), int), key
        assert getattr(settings, key) > 0, f"{key} 必须为正数"
    assert isinstance(settings.SCHEDULING_SEND_TIMEOUT, float)


def test_env_example_discloses_all_scheduling_keys():
    example = (_PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    missing = [
        key
        for key in _EXPECTED_DEFAULTS
        if key != "SCHEDULING_ENABLED" and f"# {key}=" not in example
    ]
    assert not missing, f".env.example 缺少这些键的披露: {missing}"
    assert "# SCHEDULING_ENABLED=false" in example
