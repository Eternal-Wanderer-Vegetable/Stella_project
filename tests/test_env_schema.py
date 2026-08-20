# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""settings.py → GUI 配置 schema 的回归测试。"""

from config import PROJECT_ROOT
from deploy.env_schema import build_schema


def test_schema_includes_multiline_env_calls():
    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    fields = {field["key"]: field for field in schema["fields"]}
    assert fields["PROACTIVE_SLEEP_MESSAGES"]["default"]
    assert fields["PROACTIVE_SLEEP_MESSAGES"]["section"] == "主动发言：睡眠时段"
    assert fields["MESSAGE_CLEANUP_HOUR"]["default"] == "4"


def test_schema_has_descriptions_for_documented_settings():
    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    fields = {field["key"]: field for field in schema["fields"]}
    assert "定时清理" in fields["MESSAGE_CLEANUP_ENABLED"]["description"]


def test_schema_uses_nearest_section_despite_blank_comment_lines():
    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    fields = {field["key"]: field for field in schema["fields"]}
    assert fields["MEMORY_SCORE_W_CONTEXT"]["section"] == "记忆系统 v2（Memory Policy / Retrieval v2）"
    assert fields["PROACTIVE_SLEEP_MESSAGES"]["section"] == "主动发言：睡眠时段"


def test_schema_excludes_deprecated_compatibility_settings():
    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    keys = {field["key"] for field in schema["fields"]}
    assert "RECENT_MESSAGE_LIMIT" not in keys
    assert "MEMORY_CANDIDATE_CONFIRM_MIN_CONFIDENCE" not in keys
    assert "PROACTIVE_HIGH_FREQ_INTERVAL" not in keys
