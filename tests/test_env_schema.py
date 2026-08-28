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


def test_schema_keeps_keys_whose_comments_merely_mention_deprecation():
    """回归：废弃与否只认 env_keys 登记表，不许再拿注释做子串匹配。

    旧实现按「说明里有没有『废弃』二字」猜，误剔两个**在用**的键——
    CONSOLIDATION_LM_STUDIO_BASE_URL（注释提到 FlexiWeb 流程已弃用）与
    MEMORY_COMPRESS_LOG_PATH（注释提到旧键登记在废弃表里，它本身是那个新键）。
    被剔除的键在 GUI 里完全不可见，用户根本改不到。
    """
    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    keys = {field["key"] for field in schema["fields"]}
    assert "CONSOLIDATION_LM_STUDIO_BASE_URL" in keys
    assert "MEMORY_COMPRESS_LOG_PATH" in keys


def test_schema_never_leaks_registered_deprecated_keys():
    """反向守卫：登记表里所有废弃键都不许出现在 schema 里。"""
    from deploy import env_keys

    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    leaked = [f["key"] for f in schema["fields"] if env_keys.deprecation_reason(f["key"])]
    assert leaked == []


def test_schema_marks_inherited_defaults():
    """继承型配置项必须带 inherits，GUI 才知道「留空即继承谁」而不写成 KEY=。

    这一步缺失时 GUI 会把继承项写成空串落进 .env，继承链被静默切断
    （见 tests/test_env_inherit.py 的同源回归）。
    """
    schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
    fields = {field["key"]: field for field in schema["fields"]}
    expected = {
        "CONSOLIDATION_LM_STUDIO_BASE_URL": "LM_STUDIO_BASE_URL",
        "CONSOLIDATION_LM_STUDIO_API_KEY": "LM_STUDIO_API_KEY",
        "MEMORY_EXTRACT_LM_STUDIO_BASE_URL": "LM_STUDIO_BASE_URL",
        "MEMORY_EXTRACT_LM_STUDIO_API_KEY": "LM_STUDIO_API_KEY",
        "MEMORY_EXTRACT_LM_STUDIO_MODEL": "LM_STUDIO_MODEL",
        "ASTRBOT_LLM_BASE_URL": "LM_STUDIO_BASE_URL",
        "ASTRBOT_LLM_MODEL": "LM_STUDIO_MODEL",
        "ASTRBOT_LLM_API_KEY": "LM_STUDIO_API_KEY",
    }
    for child, parent in expected.items():
        assert fields[child].get("inherits") == parent, f"{child} 缺 inherits 标记"
        # 继承型默认值无法静态求值，default 必须留空——写成别的值会误导 GUI
        assert fields[child]["default"] == ""
    # 非继承项不许莫名带上这个标记
    assert "inherits" not in fields["LM_STUDIO_BASE_URL"]
    inherited = {f["key"] for f in schema["fields"] if "inherits" in f}
    assert inherited == set(expected), "继承项集合与预期不一致（新增继承项请同步本用例）"
