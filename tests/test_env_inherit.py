# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""继承型配置项（``_env_inherit``）的语义基线。

2026-08-28 之前这些键走 ``_env``，而 ``_env`` 的「未设置」与「设为空」是两回事：
GUI 高级配置页把 schema 里每个键都写成 ``KEY=`` 一行落进 ``.env``，于是
``MEMORY_EXTRACT_LM_STUDIO_BASE_URL`` 被读成空串，阶段2 候选提取拼出
``/v1/chat/completions`` 这种无协议 URL，每次调用都失败并静默回退阶段1 候选。

本文件守两条：``_env_inherit`` 空值必须回落到父项；而 ``_env`` **不许**跟着改成
空值回落——``LM_STUDIO_API_KEY=`` 的空值是有意义的（表示「这个端点不带 key」）。
"""
import pytest

from config import settings
from config.settings import _env, _env_inherit

# 全部继承型配置项及其父项（与 config/settings.py 的调用一致，
# deploy/env_schema.py 会把同一份关系输出成 schema 的 inherits 字段）
INHERIT_PAIRS = [
    ("CONSOLIDATION_LM_STUDIO_BASE_URL", "LM_STUDIO_BASE_URL"),
    ("CONSOLIDATION_LM_STUDIO_API_KEY", "LM_STUDIO_API_KEY"),
    ("MEMORY_EXTRACT_LM_STUDIO_BASE_URL", "LM_STUDIO_BASE_URL"),
    ("MEMORY_EXTRACT_LM_STUDIO_API_KEY", "LM_STUDIO_API_KEY"),
    ("MEMORY_EXTRACT_LM_STUDIO_MODEL", "LM_STUDIO_MODEL"),
    ("ASTRBOT_LLM_BASE_URL", "LM_STUDIO_BASE_URL"),
    ("ASTRBOT_LLM_MODEL", "LM_STUDIO_MODEL"),
    ("ASTRBOT_LLM_API_KEY", "LM_STUDIO_API_KEY"),
]


def test_unset_falls_back_to_parent(monkeypatch):
    monkeypatch.delenv("SOME_CHILD_KEY", raising=False)
    assert _env_inherit("SOME_CHILD_KEY", "http://127.0.0.1:1234") == "http://127.0.0.1:1234"


def test_empty_value_falls_back_to_parent(monkeypatch):
    """核心回归：``KEY=`` 必须等同未设置，否则继承链被 GUI 静默切断。"""
    monkeypatch.setenv("SOME_CHILD_KEY", "")
    assert _env_inherit("SOME_CHILD_KEY", "http://127.0.0.1:1234") == "http://127.0.0.1:1234"


def test_whitespace_only_falls_back_to_parent(monkeypatch):
    monkeypatch.setenv("SOME_CHILD_KEY", "   ")
    assert _env_inherit("SOME_CHILD_KEY", "http://127.0.0.1:1234") == "http://127.0.0.1:1234"


def test_explicit_value_wins_and_is_stripped(monkeypatch):
    monkeypatch.setenv("SOME_CHILD_KEY", "  http://example.invalid:9999  ")
    assert _env_inherit("SOME_CHILD_KEY", "http://127.0.0.1:1234") == "http://example.invalid:9999"


def test_env_still_distinguishes_unset_from_empty(monkeypatch):
    """``_env`` 不许跟着改：空 api_key 表示「故意不带 key」，一刀切会让用户无法表达。"""
    monkeypatch.delenv("SOME_KEY", raising=False)
    assert _env("SOME_KEY", "fallback") == "fallback"
    monkeypatch.setenv("SOME_KEY", "")
    assert _env("SOME_KEY", "fallback") == ""


@pytest.mark.parametrize(("child", "parent"), INHERIT_PAIRS)
def test_resolved_settings_never_empty_when_parent_is_set(child, parent):
    """已解析的模块常量：父项非空时子项不许是空串。

    这是那个线上 bug 的直接断言——它当时的表现就是子项空串、父项正常。
    """
    parent_value = getattr(settings, parent)
    if not parent_value:
        pytest.skip(f"父项 {parent} 本身为空（本机 .env 显式清空），无继承可验")
    assert getattr(settings, child), f"{child} 为空串，继承 {parent} 失败"
