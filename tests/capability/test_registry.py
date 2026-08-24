# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Capability Registry 的单测。

重点钉两件事：
1. **合并而不是覆盖**——两条注册通路（TOML 声明 / 自动派生）会先后碰到同一个 id，
   覆盖会让后跑的那条把 examples 抹掉，路由质量无声下降；
2. **工具归属先到先得**——加载顺序里声明一定早于自动派生，所以「先到」等于「显式优先」。
"""

from capability.registry import (
    AUTO_CAPABILITY_PREFIX,
    KIND_ASTRBOT_TOOL,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as singleton


def _provider(tool: str, capability_id: str = "weather.query", priority: int = 0):
    return CapabilityProvider(
        provider_id=f"{capability_id}#{tool}",
        capability_id=capability_id,
        kind=KIND_ASTRBOT_TOOL,
        tool_name=tool,
        priority=priority,
    )


def _capability(**kwargs) -> Capability:
    base = {
        "id": "weather.query",
        "domain": "information",
        "description": "查询天气信息",
        "examples": ["明天天气怎么样"],
    }
    base.update(kwargs)
    return Capability(**base)


# ---------- Capability ----------


def test_prototype_texts_includes_examples_and_description():
    """只写了 description 的能力（自动派生的都是这样）也必须能被语义路由命中。"""
    cap = _capability(examples=["明天下雨吗"])
    assert cap.prototype_texts() == ["明天下雨吗", "查询天气信息"]

    bare = Capability(id="tool.ping", description="ping a host")
    assert bare.prototype_texts() == ["ping a host"]

    assert Capability(id="tool.x").prototype_texts() == []


def test_prototype_texts_drops_blank_entries():
    cap = _capability(examples=["  ", "", "会不会下雨"], description="  ")
    assert cap.prototype_texts() == ["会不会下雨"]


def test_enabled_providers_sorted_by_priority_desc():
    cap = _capability(
        providers=[_provider("a", priority=1), _provider("b", priority=9)],
    )
    assert [p.tool_name for p in cap.enabled_providers()] == ["b", "a"]


def test_enabled_providers_is_stable_within_same_priority():
    """同 priority 保持登记顺序，否则每次启动选到不同 provider，行为不可复现。"""
    cap = _capability(providers=[_provider("a"), _provider("b"), _provider("c")])
    assert [p.tool_name for p in cap.enabled_providers()] == ["a", "b", "c"]


def test_disabled_providers_are_excluded():
    disabled = _provider("broken")
    disabled.enabled = False
    cap = _capability(providers=[disabled, _provider("good")])
    assert [p.tool_name for p in cap.enabled_providers()] == ["good"]


def test_is_auto_detects_derived_capabilities():
    assert Capability(id=f"{AUTO_CAPABILITY_PREFIX}get_weather").is_auto
    assert not _capability().is_auto


# ---------- CapabilityRegistry ----------


def test_register_merges_instead_of_overwriting():
    """声明先注册（带中文 examples），自动派生后到——examples 绝不能被抹掉。"""
    reg = CapabilityRegistry()
    reg.register(_capability(examples=["明天天气怎么样", "会不会下雨"]))
    reg.register(
        Capability(id="weather.query", description="get weather", examples=["weather"]),
    )

    cap = reg.get("weather.query")
    assert cap is not None
    # 已有描述优先，不被英文描述顶掉
    assert cap.description == "查询天气信息"
    # 新 example 追加而非替换
    assert cap.examples == ["明天天气怎么样", "会不会下雨", "weather"]
    assert len(reg) == 1


def test_register_fills_empty_fields_from_later_registration():
    reg = CapabilityRegistry()
    reg.register(Capability(id="weather.query"))
    reg.register(_capability())
    cap = reg.get("weather.query")
    assert cap is not None
    assert cap.description == "查询天气信息"
    assert cap.domain == "information"


def test_register_does_not_duplicate_examples():
    reg = CapabilityRegistry()
    reg.register(_capability(examples=["明天天气怎么样"]))
    reg.register(_capability(examples=["明天天气怎么样"]))
    cap = reg.get("weather.query")
    assert cap is not None
    assert cap.examples == ["明天天气怎么样"]


def test_add_provider_rejects_duplicate_provider_id():
    reg = CapabilityRegistry()
    reg.register(_capability())
    assert reg.add_provider("weather.query", _provider("get_weather")) is True
    assert reg.add_provider("weather.query", _provider("get_weather")) is False
    assert len(reg.find_providers("weather.query")) == 1


def test_add_provider_to_unknown_capability_returns_false():
    reg = CapabilityRegistry()
    assert reg.add_provider("nope", _provider("x")) is False


def test_add_provider_rebinds_capability_id():
    """provider 可能是从别处复制来的，capability_id 必须以挂载目标为准。"""
    reg = CapabilityRegistry()
    reg.register(_capability())
    stray = _provider("get_weather", capability_id="wrong.id")
    reg.add_provider("weather.query", stray)
    assert stray.capability_id == "weather.query"


def test_tool_claim_is_first_come_first_served():
    """声明（先）拥有归属，自动派生（后）不许改——这就是「显式优先」的实现方式。"""
    reg = CapabilityRegistry()
    reg.register(_capability(providers=[_provider("get_weather")]))
    reg.register(
        Capability(
            id="tool.get_weather",
            providers=[_provider("get_weather", capability_id="tool.get_weather")],
        ),
    )
    assert reg.claimed_by("get_weather") == "weather.query"


def test_claimed_by_returns_none_for_unknown_tool():
    reg = CapabilityRegistry()
    assert reg.claimed_by("nothing") is None


def test_routable_requires_provider_and_prototype():
    """没 provider 路由到了也执行不了；没原型语料根本匹配不上。都提前排除。"""
    reg = CapabilityRegistry()
    reg.register(_capability(id="ok", providers=[_provider("t", "ok")]))
    reg.register(_capability(id="no_provider", providers=[]))
    reg.register(
        Capability(id="no_text", providers=[_provider("t2", "no_text")]),
    )
    assert [c.id for c in reg.routable()] == ["ok"]


def test_version_bumps_on_every_mutation():
    """Router 的原型向量缓存靠它失效——不自增会让新装插件永远路由不到。"""
    reg = CapabilityRegistry()
    v0 = reg.version
    reg.register(_capability())
    v1 = reg.version
    assert v1 > v0
    reg.add_provider("weather.query", _provider("get_weather"))
    v2 = reg.version
    assert v2 > v1
    reg.clear()
    assert reg.version > v2


def test_all_and_ids_are_sorted():
    reg = CapabilityRegistry()
    for cid in ("c", "a", "b"):
        reg.register(Capability(id=cid))
    assert reg.ids() == ["a", "b", "c"]
    assert [c.id for c in reg.all()] == ["a", "b", "c"]


def test_clear_resets_claims_too():
    """只清能力不清归属，会让重载后的工具永远认领不上。"""
    reg = CapabilityRegistry()
    reg.register(_capability(providers=[_provider("get_weather")]))
    reg.clear()
    assert not reg
    assert reg.claimed_by("get_weather") is None


def test_module_singleton_is_shared_across_import_paths():
    """注册表分裂的表现是「插件明明装了但路由不到」，必须钉死单例。"""
    import importlib

    import capability.registry as reg_mod

    assert reg_mod.registry is singleton
    assert importlib.import_module("capability.registry").registry is singleton


def test_package_does_not_shadow_registry_submodule():
    """回归：包入口若再导出 ``registry``，``capability.registry`` 就从子模块变成实例。

    ``import a.b as c`` 会退化成 ``getattr(a, "b")``，于是拿到的是单例对象而不是模块，
    且只在 ``__init__`` 已执行时才这样——行为随 import 顺序变化，最难查。
    """
    import types

    import capability

    assert isinstance(capability.registry, types.ModuleType)
    assert "registry" not in capability.__all__
