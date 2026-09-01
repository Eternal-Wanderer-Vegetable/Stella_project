# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""三层声明（用户 > 出厂 > 插件自带）的载入单测。

这一层出错的表现全是**静默**的：声明写了但不生效、出厂标定被整体遮蔽、
未加载插件的声明抢走工具归属——都不报错，只表现为「路由变差」或「工具从来不被调用」。
所以每条优先级规则都要有一个用例钉住。
"""

from __future__ import annotations

import types

import pytest

from astrbot_compat.registry import StarMetadata, star_registry
from capability.loader import (
    PLUGIN_DECL_FILENAME,
    load_declaration_tiers,
    load_plugin_capabilities,
)
from capability.registry import SOURCE_CONFIG, SOURCE_PLUGIN, CapabilityRegistry

WEATHER_TOML = """
[[capability]]
id = "{cap_id}"
description = "{desc}"
examples = ["{example}"]
providers = ["get_weather"]
"""


def _decl(cap_id: str = "weather.query", desc: str = "查询天气", example: str = "明天天气怎么样"):
    return WEATHER_TOML.format(cap_id=cap_id, desc=desc, example=example)


@pytest.fixture
def tiers(tmp_path, monkeypatch):
    """把用户层与出厂层指到两个临时目录，返回 ``(用户目录, 出厂目录)``。

    monkeypatch 打在 ``config`` 包属性上：``_config_declaration_dirs`` 是在函数体内
    ``from config import PROJECT_ROOT, STELLA_HOME``，取的是调用时的模块属性。
    """
    home = tmp_path / "home"
    root = tmp_path / "root"
    user_dir = home / "config" / "capabilities"
    factory_dir = root / "config" / "capabilities"
    user_dir.mkdir(parents=True)
    factory_dir.mkdir(parents=True)
    monkeypatch.setattr("config.STELLA_HOME", home, raising=False)
    monkeypatch.setattr("config.PROJECT_ROOT", root, raising=False)
    return user_dir, factory_dir


def _make_plugin(
    tmp_path,
    dir_name: str,
    declaration: str | None = None,
    *,
    filename: str = PLUGIN_DECL_FILENAME,
    activated: bool = True,
    loaded: bool = True,
):
    """在 ``star_registry`` 里登记一个插件，可选地给它放一份声明文件。

    ``loaded=False`` 模拟 import 失败的插件（``star_cls is None``）——加载器必须跳过它。
    """
    plugin_dir = tmp_path / "plugins" / dir_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    main_py = plugin_dir / "main.py"
    main_py.write_text("", encoding="utf-8")
    if declaration is not None:
        (plugin_dir / filename).write_text(declaration, encoding="utf-8")

    module_path = f"data.plugins.{dir_name}.main"
    module = types.ModuleType(module_path)
    module.__file__ = str(main_py)
    star_registry.append(
        StarMetadata(
            name=dir_name,
            author="tester",
            root_dir_name=dir_name,
            module_path=module_path,
            module=module,
            star_cls=object() if loaded else None,
            activated=activated,
        ),
    )
    return plugin_dir


# ---------- 插件自带声明 ----------


def test_plugin_declaration_is_loaded_and_tagged(tmp_path):
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "astrbot_plugin_weather", _decl())

    assert load_plugin_capabilities(reg) == 1
    cap = reg.get("weather.query")
    assert cap is not None
    assert cap.source == SOURCE_PLUGIN
    assert [p.source for p in cap.providers] == [SOURCE_PLUGIN]
    assert reg.claimed_by("get_weather") == "weather.query"
    # 声明的能力照常参与路由——这正是本规范要解决的那件事
    assert [c.id for c in reg.routable()] == ["weather.query"]


def test_declaration_filename_must_be_exact(tmp_path):
    """``capability.toml.draft`` 一律不载入：文件名不匹配是 reviewed 之外的第一道闸门。"""
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "p", _decl(), filename="capability.toml.draft")
    assert load_plugin_capabilities(reg) == 0
    assert not reg


def test_reviewed_false_blocks_the_whole_file(tmp_path):
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "p", "reviewed = false\n" + _decl())
    assert load_plugin_capabilities(reg) == 0
    assert not reg


def test_reviewed_true_is_loaded(tmp_path):
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "p", "reviewed = true\n" + _decl())
    assert load_plugin_capabilities(reg) == 1


def test_missing_reviewed_key_is_treated_as_reviewed(tmp_path):
    """键缺省视为已审：手写声明的作者是在直接编写，不是在审阅草稿。

    要求他多写一行 ``reviewed = true`` 只会造出一类新的静默失效
    （写了声明却不生效，且不知道为什么）。
    """
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "p", _decl())
    assert load_plugin_capabilities(reg) == 1


def test_failed_plugin_declaration_is_not_loaded(tmp_path):
    """import 失败的插件没登记任何工具，载入它的声明会造出指向不存在工具的 provider。

    ``routable()`` 只查 enabled/backoff、不查工具是否存在，那条能力会照常参与路由竞争、
    抢走 ``ROUTER_CAPABILITY_MARGIN`` 的间距，最后必然在 Comes 里 failed。
    """
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "broken", _decl(), loaded=False)
    assert load_plugin_capabilities(reg) == 0
    assert not reg


def test_deactivated_plugin_declaration_is_not_loaded(tmp_path):
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "off", _decl(), activated=False)
    assert load_plugin_capabilities(reg) == 0


def test_broken_plugin_toml_does_not_stop_the_tier(tmp_path):
    """沿用 config/spaces.py 的容错契约：坏文件只跳过它自己。"""
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "a_broken", "this is not = = toml [[[")
    _make_plugin(tmp_path, "b_good", _decl())
    assert load_plugin_capabilities(reg) == 1
    assert reg.ids() == ["weather.query"]


def test_switch_off_skips_the_whole_plugin_tier(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.ASTRBOT_PLUGIN_CAPABILITIES_ENABLED", False)
    reg = CapabilityRegistry()
    _make_plugin(tmp_path, "p", _decl())
    assert load_plugin_capabilities(reg) == 0
    assert not reg


# ---------- 层间优先级 ----------


def test_user_tier_wins_over_factory_and_plugin(tmp_path, tiers):
    """同一个工具三层都声明时，只有用户那条生效。"""
    user_dir, factory_dir = tiers
    (user_dir / "information.toml").write_text(
        _decl(desc="用户版", example="用户写的问句"),
        encoding="utf-8",
    )
    (factory_dir / "information.toml").write_text(
        _decl(desc="出厂版", example="出厂写的问句"),
        encoding="utf-8",
    )
    _make_plugin(tmp_path, "p", _decl(desc="插件版", example="插件写的问句"))

    reg = CapabilityRegistry()
    counts = load_declaration_tiers(reg)

    assert counts == {"config": 1, "plugin": 0, "declared": 1}
    cap = reg.get("weather.query")
    assert cap is not None
    assert cap.description == "用户版"
    assert cap.examples == ["用户写的问句"]
    assert cap.source == SOURCE_CONFIG


def test_plugin_wins_when_no_config_tier_declares_the_tool(tmp_path, tiers):
    """出厂层声明的是别的工具时，插件那条照常生效——覆盖是逐条的，不是整层的。"""
    _user_dir, factory_dir = tiers
    (factory_dir / "entertainment.toml").write_text(
        '[[capability]]\nid = "dice.roll"\nexamples = ["丢个骰子"]\nproviders = ["roll_dice"]\n',
        encoding="utf-8",
    )
    _make_plugin(tmp_path, "p", _decl())

    reg = CapabilityRegistry()
    counts = load_declaration_tiers(reg)

    assert counts == {"config": 1, "plugin": 1, "declared": 2}
    assert reg.ids() == ["dice.roll", "weather.query"]


def test_user_override_under_a_different_id_still_shadows_the_plugin(tmp_path, tiers):
    """用户往往不知道插件把能力叫什么 id，只知道工具名——换 id 覆盖必须也能生效。

    判据是「provider 的工具已被别人认领」，不只是「同 id 已注册」；否则同一个工具会被
    两条能力同时声明，L1 里自己和自己抢。
    """
    user_dir, _factory_dir = tiers
    (user_dir / "information.toml").write_text(
        _decl(cap_id="my.weather", desc="我自己写的", example="我的问句"),
        encoding="utf-8",
    )
    _make_plugin(tmp_path, "p", _decl(cap_id="weather.query", desc="插件版"))

    reg = CapabilityRegistry()
    load_declaration_tiers(reg)

    assert reg.ids() == ["my.weather"]
    assert reg.claimed_by("get_weather") == "my.weather"


def test_factory_tier_is_not_shadowed_by_a_user_file(tiers):
    """回归：两层曾是**二选一**，用户目录里出现任意一个文件就丢掉全部出厂声明。

    出厂那批含随发布包出厂、带实测标定的 ``entertainment.toml``——而这不报错，
    只表现为路由质量下降。
    """
    user_dir, factory_dir = tiers
    (user_dir / "mine.toml").write_text(
        '[[capability]]\nid = "mine.cap"\nexamples = ["我的"]\nproviders = ["mine_tool"]\n',
        encoding="utf-8",
    )
    (factory_dir / "entertainment.toml").write_text(
        '[[capability]]\nid = "anime.search"\nexamples = ["有什么新番"]\nproviders = ["search"]\n',
        encoding="utf-8",
    )

    reg = CapabilityRegistry()
    counts = load_declaration_tiers(reg)

    assert counts["config"] == 2
    assert reg.ids() == ["anime.search", "mine.cap"]


def test_identical_config_dirs_are_read_once(tmp_path, monkeypatch):
    """自包含布局（STELLA_HOME == PROJECT_ROOT）下别把同一批读两遍。"""
    from capability.loader import _config_declaration_dirs

    root = tmp_path / "root"
    (root / "config" / "capabilities").mkdir(parents=True)
    monkeypatch.setattr("config.STELLA_HOME", root, raising=False)
    monkeypatch.setattr("config.PROJECT_ROOT", root, raising=False)

    assert len(_config_declaration_dirs()) == 1


def test_config_dirs_are_user_first(tiers):
    """层序不可交换：用户层必须先注册才能抢下工具归属（``_claim`` 先到先得）。"""
    from capability.loader import _config_declaration_dirs

    user_dir, factory_dir = tiers
    assert _config_declaration_dirs() == [user_dir, factory_dir]
