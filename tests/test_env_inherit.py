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

from config import PROJECT_ROOT, settings
from config.settings import _env, _env_inherit
from deploy.env_schema import build_schema

# 全部继承型配置项及其父项，**从 schema 现算**而不是手抄一份：
# P1 一口气加了 16 对继承项，手抄的清单当场就过期了（而它的 docstring 还写着
# 「全部」）。这里直接问 deploy/env_schema.py——它读的就是 config/settings.py
# 里那些 _env*_inherit 调用，新增继承项自动进入本文件的参数化。
# 「这份关系对不对」由 tests/test_env_schema.py 的手写基线守，两处各管一头：
# 那边守「关系有没有被改错」，这边守「关系在运行时真的解析出了非空值」。
INHERIT_PAIRS = sorted(
    (field["key"], field["inherits"])
    for field in build_schema(PROJECT_ROOT / "config" / "settings.py")["fields"]
    if "inherits" in field
)


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


def test_inherit_pairs_were_actually_discovered():
    """派生参数化的自毁风险：schema 提取一坏，参数化变空，下面那条就静默不跑了。

    数量下限是个软基线（2026-08-28 是 24 对），只为把「一条都没找到」这种
    静默失效变成红灯，不是为了钉死具体条数。
    """
    assert len(INHERIT_PAIRS) >= 20, f"只发现 {len(INHERIT_PAIRS)} 对继承项，schema 提取大概坏了"


@pytest.mark.parametrize(("child", "parent"), INHERIT_PAIRS)
def test_resolved_settings_never_empty_when_parent_is_set(child, parent):
    """已解析的模块常量：父项有值时子项不许是空值。

    这是那个线上 bug 的直接断言——它当时的表现就是子项空串、父项正常。
    P1 起继承项还包括 int / float（角色的 temperature 与 max_tokens），
    判据统一成「真值」：父项本身是 0 / 空串时没有可验的继承，跳过。
    """
    parent_value = getattr(settings, parent)
    if not parent_value:
        pytest.skip(f"父项 {parent} 本身无值（默认为 0 或本机 .env 显式清空），无继承可验")
    assert getattr(settings, child), f"{child} 是空值，继承 {parent} 失败"
