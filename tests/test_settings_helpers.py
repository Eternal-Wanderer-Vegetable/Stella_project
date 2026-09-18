# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""config/settings.py 环境变量助手的单元测试。

覆盖每个 _env* 助手的 合法 / 空 / 非法 三态与回退口径。非法值一律「告警 +
回退、绝不抛异常」——本模块在 import 期执行，一个坏值就让 Bot 起不来的
历史（裸 int() 推导时代）不能再重演。
"""

from config import settings
from deploy.env_keys import _bool as env_keys_bool


def test_env_bool_accepts_known_truthy_and_falsy(monkeypatch):
    for raw, expected in [
        ("true", True), ("1", True), ("Yes", True), (" TRUE ", True), ('"true"', True),
        ("false", False), ("0", False), ("No", False), (" false ", False),
    ]:
        monkeypatch.setenv("STELLA_TEST_BOOL", raw)
        assert settings._env_bool("STELLA_TEST_BOOL", "true") is expected, f"raw={raw!r}"


def test_env_bool_invalid_or_empty_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("STELLA_TEST_BOOL", "maybe")
    assert settings._env_bool("STELLA_TEST_BOOL", "false") is False
    monkeypatch.setenv("STELLA_TEST_BOOL", "")
    assert settings._env_bool("STELLA_TEST_BOOL", "false") is False
    monkeypatch.delenv("STELLA_TEST_BOOL", raising=False)
    assert settings._env_bool("STELLA_TEST_BOOL", "true") is True


def test_env_int_set_skips_invalid_fragments(monkeypatch):
    """非法片段告警并跳过，其余保留——替代旧版裸 int() 的 import 崩溃。"""
    monkeypatch.setenv("STELLA_TEST_SET", "123, abc, 456, , 0")
    assert settings._env_int_set("STELLA_TEST_SET") == {123, 456, 0}


def test_env_int_set_empty_env_uses_default(monkeypatch):
    monkeypatch.setenv("STELLA_TEST_SET", "  ")
    assert settings._env_int_set("STELLA_TEST_SET", "7,8") == {7, 8}
    monkeypatch.delenv("STELLA_TEST_SET", raising=False)
    assert settings._env_int_set("STELLA_TEST_SET") == set()


def test_env_str_list_preserves_order_and_strips(monkeypatch):
    monkeypatch.setenv("STELLA_TEST_LIST", " b, a ,,c ")
    assert settings._env_str_list("STELLA_TEST_LIST") == ["b", "a", "c"]


def test_env_str_list_upper(monkeypatch):
    monkeypatch.setenv("STELLA_TEST_LIST", "event, plan")
    assert settings._env_str_list("STELLA_TEST_LIST", upper=True) == ["EVENT", "PLAN"]


def test_env_choice_valid_and_empty(monkeypatch):
    monkeypatch.setenv("STELLA_TEST_CHOICE", "  ENFORCE ")
    assert settings._env_choice(
        "STELLA_TEST_CHOICE", "observe", ("observe", "enforce")
    ) == "enforce"
    monkeypatch.setenv("STELLA_TEST_CHOICE", "")
    assert settings._env_choice(
        "STELLA_TEST_CHOICE", "enforce", ("observe", "enforce")
    ) == "enforce"


def test_env_choice_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("STELLA_TEST_CHOICE", "bogus")
    # 兜底方向与默认值不同的键（PROACTIVE_NATURALNESS_MODE 语义）：on_invalid 指定
    assert settings._env_choice(
        "STELLA_TEST_CHOICE", "enforce", ("observe", "enforce"), on_invalid="observe"
    ) == "observe"
    # 未指定时回默认值
    assert settings._env_choice(
        "STELLA_TEST_CHOICE", "enforce", ("observe", "enforce")
    ) == "enforce"


def test_env_bool_agrees_with_env_keys_bool(monkeypatch):
    """同一真值口径的两份实现不许漂移。

    deploy/env_keys.py 供 deploy 工具链独立使用、刻意不 import config，布尔
    口径因此存在两份实现；这个对照测试就是防漂移的约定落点。改真值集时
    两处必须同步，本用例会同时失败提醒。
    """
    for raw in ["true", "TRUE", "1", "yes", "Yes", "false", "FALSE", "0", "no", " true "]:
        monkeypatch.setenv("STELLA_TEST_BOOL", raw)
        assert env_keys_bool(raw) is settings._env_bool("STELLA_TEST_BOOL", "true"), (
            f"口径漂移: raw={raw!r}"
        )
