# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBot 插件工具 → Capability 自动派生的单测。

最重要的一条：**bootstrap 的顺序不可交换**。声明必须先注册才能抢下工具归属；
反过来自动派生会先把每个工具占成 ``tool.<name>``，精心写的中文 examples
就永远不会被用到——而这不报错，只表现为「路由准确率没提升」。
见 test_bootstrap_lets_declaration_claim_the_tool。
"""

from capability.adapters.astrbot import (
    auto_capability_id,
    bootstrap,
    install_tool_probe,
    sync_astrbot_tools,
)
from capability.registry import Capability, CapabilityProvider, CapabilityRegistry


def _register_tool(name: str, desc: str = "", active: bool = True, required=None):
    from astrbot_compat.llm.tool import FunctionTool, llm_tools

    params = {"type": "object", "properties": {}}
    for p in required or []:
        params["properties"][p] = {"type": "string"}
    if required:
        params["required"] = list(required)
    tool = FunctionTool(
        name=name,
        description=desc,
        parameters=params,
        handler=lambda event, **kw: "ok",
        active=active,
    )
    llm_tools.add_tool(tool)
    return tool


def test_auto_capability_id_prefix():
    assert auto_capability_id("get_weather") == "tool.get_weather"


def test_derives_capability_per_tool():
    _register_tool("get_weather", "get weather forecast")
    reg = CapabilityRegistry()
    stats = sync_astrbot_tools(reg)

    assert stats["derived"] == 1
    cap = reg.get("tool.get_weather")
    assert cap is not None
    assert cap.is_auto
    assert cap.domain == "plugin"
    assert cap.description == "get weather forecast"
    assert [p.tool_name for p in cap.providers] == ["get_weather"]
    assert cap.providers[0].source == "auto"


def test_description_falls_back_to_tool_name():
    _register_tool("ping", "")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)
    cap = reg.get("tool.ping")
    assert cap is not None
    assert cap.description == "ping"
    # 有描述就能进 routable（prototype_texts 非空）
    assert cap.prototype_texts() == ["ping"]


def test_derived_capability_has_no_examples_or_keywords():
    """描述已由 prototype_texts() 带上；复制进 examples 只会在原型均值里被计两次。

    没有 keywords 是刻意的：自动派生的能力拿不到 Level 0 的零延迟通路，
    只能靠 Level 1 语义匹配（见 adapters/astrbot.py 的模块 docstring）。
    """
    _register_tool("get_weather", "get weather")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)
    cap = reg.get("tool.get_weather")
    assert cap is not None
    assert cap.examples == []
    assert cap.keywords == []
    assert cap.prototype_texts() == ["get weather"]


def test_input_schema_copied_from_tool():
    _register_tool("get_weather", "d", required=["city"])
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)
    cap = reg.get("tool.get_weather")
    assert cap is not None
    assert cap.input_schema["required"] == ["city"]


def test_inactive_tools_are_skipped():
    _register_tool("off", "d", active=False)
    reg = CapabilityRegistry()
    stats = sync_astrbot_tools(reg)
    assert stats == {"derived": 0, "claimed": 0, "skipped": 1}
    assert not reg


def test_declared_tool_is_not_derived():
    """显式声明拥有工具归属，自动派生必须跳过它。"""
    _register_tool("get_weather", "get weather")
    reg = CapabilityRegistry()
    reg.register(
        Capability(
            id="weather.query",
            description="查询天气信息",
            examples=["明天天气怎么样"],
            keywords=["天气"],
            providers=[
                CapabilityProvider(
                    provider_id="weather.query#get_weather",
                    capability_id="weather.query",
                    tool_name="get_weather",
                ),
            ],
        ),
    )
    stats = sync_astrbot_tools(reg)
    assert stats["claimed"] == 1
    assert stats["derived"] == 0
    assert reg.get("tool.get_weather") is None
    assert reg.ids() == ["weather.query"]


def test_unclaimed_tools_still_derived_alongside_declarations():
    """声明只认领了一部分工具，其余仍应零配置可用。"""
    _register_tool("get_weather", "get weather")
    _register_tool("roll_dice", "roll a dice")
    reg = CapabilityRegistry()
    reg.register(
        Capability(
            id="weather.query",
            description="查询天气信息",
            providers=[
                CapabilityProvider(
                    provider_id="weather.query#get_weather",
                    capability_id="weather.query",
                    tool_name="get_weather",
                ),
            ],
        ),
    )
    stats = sync_astrbot_tools(reg)
    assert stats["claimed"] == 1
    assert stats["derived"] == 1
    assert reg.ids() == ["tool.roll_dice", "weather.query"]


def test_sync_is_idempotent():
    """插件热加载后可以重复调用，不该重复注册。"""
    _register_tool("get_weather", "get weather")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)
    stats = sync_astrbot_tools(reg)
    assert stats["derived"] == 0
    assert len(reg) == 1
    assert len(reg.find_providers("tool.get_weather")) == 1


def test_sync_picks_up_newly_added_tools():
    _register_tool("a", "d")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)
    _register_tool("b", "d")
    stats = sync_astrbot_tools(reg)
    assert stats["derived"] == 1
    assert reg.ids() == ["tool.a", "tool.b"]


def test_bootstrap_lets_declaration_claim_the_tool(tmp_path, monkeypatch):
    """**顺序不可交换**：声明先注册 → 抢下归属 → 中文 examples 生效。

    反过来的话自动派生先把工具占成 tool.get_weather，声明再想认领就抢不到
    （_claim 先到先得），于是精心写的 examples 永远不会被用到，且不报错。
    """
    import capability.loader as loader_mod

    (tmp_path / "information.toml").write_text(
        """
[[capability]]
id = "weather.query"
description = "查询天气信息"
examples = ["明天天气怎么样", "会不会下雨"]
keywords = ["天气"]
providers = ["get_weather"]
""",
        encoding="utf-8",
    )
    real_load = loader_mod.load_capabilities
    monkeypatch.setattr(
        loader_mod,
        "load_capabilities",
        lambda directory=None, target=None: real_load(tmp_path, target),
    )

    _register_tool("get_weather", "get weather forecast")
    _register_tool("roll_dice", "roll a dice")
    reg = CapabilityRegistry()

    stats = bootstrap(reg)
    assert stats["declared"] == 1
    assert stats["claimed"] == 1
    assert stats["derived"] == 1

    # 声明的中文 examples 保住了，没被英文描述顶掉
    cap = reg.get("weather.query")
    assert cap is not None
    assert cap.examples == ["明天天气怎么样", "会不会下雨"]
    assert cap.keywords == ["天气"]
    assert reg.claimed_by("get_weather") == "weather.query"
    # 未声明的工具仍自动派生
    assert reg.get("tool.roll_dice") is not None


def test_bootstrap_with_no_declarations_is_all_auto(tmp_path, monkeypatch):
    import capability.loader as loader_mod

    real_load = loader_mod.load_capabilities
    monkeypatch.setattr(
        loader_mod,
        "load_capabilities",
        lambda directory=None, target=None: real_load(tmp_path, target),
    )
    _register_tool("a", "d")
    reg = CapabilityRegistry()
    stats = bootstrap(reg)
    assert stats["declared"] == 0
    assert stats["derived"] == 1


def test_derived_capability_is_registered_but_not_routable():
    """声明优先：自动派生的能力照常注册、可被显式执行，但默认不参与路由竞争。

    依据是 2026-08-24 首轮实测——工具描述是写给决策器的指令句，拿它当语义原型时
    同域工具之间几乎没有区分度，代价是「工具假阳」（高）。见 registry.Capability.route_enabled。
    """
    _register_tool("get_weather", "get weather forecast")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)

    cap = reg.get("tool.get_weather")
    assert cap is not None            # 注册了：Comes 仍能按 id 执行它
    assert cap.route_enabled is False
    assert reg.routable() == []       # 但不进任何路由级别的候选集


def test_auto_capabilities_route_when_opted_in():
    """``ROUTER_ROUTE_AUTO_CAPABILITIES=true`` 恢复「装上插件就能路由」的旧行为。"""
    _register_tool("get_weather", "get weather forecast")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg, route_enabled=True)
    assert [c.id for c in reg.routable()] == ["tool.get_weather"]


def test_auto_route_policy_reads_settings(monkeypatch):
    """缺省不传 route_enabled 时要读配置，而不是硬编码 False。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_ROUTE_AUTO_CAPABILITIES", True, raising=False)
    _register_tool("get_weather", "get weather forecast")
    reg = CapabilityRegistry()
    sync_astrbot_tools(reg)
    assert [c.id for c in reg.routable()] == ["tool.get_weather"]


def test_bootstrap_reports_routable_count(tmp_path, monkeypatch):
    """``routable`` 才是决定 Router 行为的数；declared/derived 只说明注册表里有什么。

    声明的能力进 routable，未声明的工具不进——两者都注册了，数上要能区分开。
    """
    import capability.loader as loader_mod

    (tmp_path / "information.toml").write_text(
        """
[[capability]]
id = "weather.query"
description = "查询天气信息"
examples = ["明天天气怎么样"]
providers = ["get_weather"]
""",
        encoding="utf-8",
    )
    real_load = loader_mod.load_capabilities
    monkeypatch.setattr(
        loader_mod,
        "load_capabilities",
        lambda directory=None, target=None: real_load(tmp_path, target),
    )

    _register_tool("get_weather", "get weather forecast")
    _register_tool("roll_dice", "roll a dice")
    reg = CapabilityRegistry()

    stats = bootstrap(reg)
    assert stats["declared"] == 1
    assert stats["derived"] == 1          # roll_dice 被派生了
    assert stats["routable"] == 1         # 但只有声明的 weather.query 参与路由
    assert [c.id for c in reg.routable()] == ["weather.query"]


# ---------- 工具存活探针（回归 bug_report_2026_9_2#1）----------


def _declare(reg: CapabilityRegistry, cap_id: str, tool: str) -> None:
    """手写一条指向 ``tool`` 的声明（等价于 config/capabilities/*.toml 里的一条）。"""
    reg.register(
        Capability(
            id=cap_id,
            domain="entertainment",
            description="检索 ACG 作品信息",
            examples=["有什么好看的番"],
            providers=[
                CapabilityProvider(
                    provider_id=f"{cap_id}#{tool}",
                    capability_id=cap_id,
                    tool_name=tool,
                ),
            ],
        ),
    )


def test_install_tool_probe_makes_a_declaration_wait_for_its_plugin():
    """回归：一个插件都没装的部署把出厂声明答成了自己的 5 项能力。

    ``llm_tools`` 在这个用例里是空的（conftest 每个用例都清），正好等于那台部署。
    装上插件后**不重跑 bootstrap** 也该点亮——探针是查询时才问的，不留装配快照，
    热重载后不用重装就靠这一点。
    """
    reg = CapabilityRegistry()
    _declare(reg, "anime.search", "bgm_search_subjects_advanced")

    assert install_tool_probe(reg) is True
    assert reg.routable() == []

    _register_tool("bgm_search_subjects_advanced", "search bangumi subjects")
    assert [c.id for c in reg.routable()] == ["anime.search"]


def test_probe_treats_an_inactive_tool_as_absent():
    """判据与 ``comes/executor.resolve_tools`` 对齐：``active=False`` 视同缺失。"""
    reg = CapabilityRegistry()
    _declare(reg, "anime.search", "bgm_search")
    _register_tool("bgm_search", "search", active=False)

    install_tool_probe(reg)
    assert reg.routable() == []


def test_bootstrap_routable_stat_is_truthful_when_the_probe_is_installed(
    tmp_path, monkeypatch,
):
    """``bootstrap`` 回的 ``routable`` 是排查这件事时第一个看的数，必须是真话。

    所以 ``bot.py`` 里探针**必须**装在 ``bootstrap()`` 之前——反过来那行启动日志会
    报装探针前的旧答案，而那正是「怎么一个插件都没装还说有 5 项能力」的现场。
    """
    import capability.loader as loader_mod

    (tmp_path / "entertainment.toml").write_text(
        """
[[capability]]
id = "anime.search"
description = "检索 ACG 作品信息"
examples = ["有什么好看的番"]
providers = ["bgm_search_subjects_advanced"]
""",
        encoding="utf-8",
    )
    real_load = loader_mod.load_capabilities
    monkeypatch.setattr(
        loader_mod,
        "load_capabilities",
        lambda directory=None, target=None: real_load(tmp_path, target),
    )

    reg = CapabilityRegistry()
    install_tool_probe(reg)
    stats = bootstrap(reg)

    assert stats["declared"] == 1      # 声明读到了
    assert stats["routable"] == 0      # 但它指向的插件没装
    assert reg.routable() == []
