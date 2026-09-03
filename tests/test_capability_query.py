# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""能力查询三个 surface 的共用数据层（``capability.inventory``）与 CLI 渲染层
（``deploy.capability_view``）。

这一层出错的表现全是**误导**而不是崩溃，所以每条断言钉的都是一句具体的谎：

- ``routable`` 与 ``registry.routable()`` 不一致 → 清单说「可路由」而它从来不被调用，
  而这恰好是这份清单要回答的那个问题；
- ``tools_known`` 丢掉 ``None``/``{}`` 的区分 → 读不到工具注册表时谎报「工具不存在」，
  排查的人跑去插件目录核一个根本没问题的名字；
- 快照长出 ``description``/``examples`` 原文 → 经状态接口出到回环端口，而诊断包会被
  用户贴到 issue 里（同 ``tests/test_status_api.py`` 那条守卫）；
- 普通群友看到来源层与未声明工具名单 → 那是排查信息，方案 §3.1 只给管理员；
- 离线分支不说清「只是文件内容」→ 用户拿它去解释「为什么没被调用」，而它不含那个答案。

刻意不 import ``ai_gateway``：那会拉起 NoneBot 的事件监听与整条 Pipeline
（``test_status_api.py`` 与 ``test_proactive_rules.py`` 出于同样理由都绕开了它）。
需要它那两张开关词表时用 ``ast`` 从源码里取，见 ``_toggle_keywords``。
"""

from __future__ import annotations

import json
import time
import types
from pathlib import Path

import pytest

from capability import inventory
from capability.registry import (
    KIND_ASTRBOT_TOOL,
    SOURCE_AUTO,
    SOURCE_CONFIG,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from deploy import capability_view
from deploy.capability_view import CapabilityView

_PROJ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_commands(monkeypatch):
    """指令名默认置空。

    ``_command_names()`` 读的是 ``star_handlers_registry`` 这个**模块级单例**，别的
    测试文件往里注册过的 handler 会跨用例留下来。本模块的断言全是「清单里有什么」，
    被污染后会以最难查的方式变绿。需要指令的用例自己覆盖它。
    """
    monkeypatch.setattr(inventory, "_command_names", lambda limit=60: [])


@pytest.fixture
def reg() -> CapabilityRegistry:
    """独立注册表。刻意不用模块级单例 ``registry``——理由同上。"""
    return CapabilityRegistry()


def _cap(
    cap_id: str,
    *,
    domain: str = "information",
    description: str = "",
    examples: tuple[str, ...] = (),
    keywords: tuple[str, ...] = (),
    tools: tuple[str, ...] = (),
    route_enabled: bool = True,
    source: str = SOURCE_CONFIG,
) -> Capability:
    return Capability(
        id=cap_id,
        domain=domain,
        description=description,
        examples=list(examples),
        keywords=list(keywords),
        route_enabled=route_enabled,
        source=source,
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}#{tool}",
                capability_id=cap_id,
                kind=KIND_ASTRBOT_TOOL,
                tool_name=tool,
                source=source,
            )
            for tool in tools
        ],
    )


def _manager(**tools: bool):
    """假的工具注册表：``工具名=是否 active``。只需要 ``.tools`` 上的 name/active。"""
    return types.SimpleNamespace(
        tools=[types.SimpleNamespace(name=name, active=active) for name, active in tools.items()],
    )


def _live(snap: dict) -> str:
    return capability_view.to_terminal(
        CapabilityView(live=snap, offline=None, api_reachable=True),
    )


# ---------- 触发判定：is_query_text ----------


def _toggle_keywords() -> tuple[str, ...]:
    """从 ``ai_gateway.py`` **源码**里取那两张运行时开关词表。

    不 import（见模块 docstring），也不在这里抄一份副本——这几条断言的全部意义就是
    「有人往开关词表里加词、而那个词恰好也像一次能力查询时会红」，副本会让它永远绿。
    """
    import ast

    source = (
        _PROJ / "stella_project" / "plugins" / "bot_main" / "ai_gateway.py"
    ).read_text(encoding="utf-8")
    wanted = {"_MUTE_KEYWORDS", "_UNMUTE_KEYWORDS"}
    found: dict[str, tuple[str, ...]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", "")
            if name in wanted:
                found[name] = tuple(ast.literal_eval(node.value))
    missing = wanted - set(found)
    assert not missing, f"ai_gateway 里找不到 {missing}——改名了就要同步这个用例"
    return found["_MUTE_KEYWORDS"] + found["_UNMUTE_KEYWORDS"]


def test_is_query_text_accepts_every_declared_phrasing():
    for phrase in inventory.QUERY_KEYWORDS:
        assert inventory.is_query_text(f"@Stella {phrase}？") is True, phrase


def test_is_query_text_rejects_real_requests():
    """只收**问功能**的句式。真实请求要交给正常对话链路，被这里 block 掉就等于失灵。"""
    for text in ("帮我查一下东京天气", "有什么新番推荐吗", "你好", "", "   "):
        assert inventory.is_query_text(text) is False, text


def test_toggle_commands_are_never_read_as_capability_query():
    """穷举「开关词 + 查询词」的拼接：一律不算能力查询。

    ``capability_handler`` 与 ``toggle_handler`` 同优先级且都 ``block=True``，而
    NoneBot 会把同优先级的 matcher 一起跑。一句「恢复一下，你能做什么」若同时命中
    两者，其中一个**会改群设置**——而用户只是问了句功能。
    """
    toggle = _toggle_keywords()
    for word in toggle:
        for phrase in inventory.QUERY_KEYWORDS:
            sentence = f"{word}，{phrase}"
            assert inventory.is_query_text(sentence, toggle_keywords=toggle) is False, sentence


def test_exclusion_not_coincidence_is_what_makes_toggles_false():
    """确认上一条测的是**互斥判定**，而不是「那句话恰好不像一次查询」。

    不传词表时同一句话必须判为 True；否则上一条会在 is_query_text 彻底失灵时照样通过。
    """
    sentence = f"{_toggle_keywords()[0]}，{inventory.QUERY_KEYWORDS[0]}"
    assert inventory.is_query_text(sentence) is True
    assert inventory.is_query_text(sentence, toggle_keywords=_toggle_keywords()) is False


# ---------- 触发判定：与热重载命令的互斥 ----------
#
# reload_handler 与上面两个 handler 同优先级、同为 block=True，所以第三条规则加进来
# 之后互斥变成三方的。实现方式是「另外两条规则一旦发现这是重载命令就返回 False」，
# 于是整条链的正确性归结为两件可穷举的事：parse_reload_command 判得准（下面两条），
# 以及那两条规则真的调了它（再下面那条从源码里确认）。


def test_plugin_name_that_looks_like_a_toggle_still_parses_as_reload():
    """插件名是**任意字符串**：叫「恢复」也得仍被解析成重载命令。

    判错的后果是「重载插件 恢复」在重载的同时把主动发言打开——而发这句的人只想重载。
    """
    from astrbot_compat.loader import RELOAD_KEYWORDS, parse_reload_command

    names = _toggle_keywords() + inventory.QUERY_KEYWORDS
    for phrase in RELOAD_KEYWORDS:
        for name in names:
            text = f"{phrase} {name}"
            assert parse_reload_command(text) == name, text


def test_plain_toggle_or_query_is_never_read_as_reload():
    """反向：一句纯粹的开关命令或能力查询绝不能被当成重载命令。

    判错的后果更糟——「安静」会被 reload_handler 吃掉（block=True），开关彻底失灵。
    """
    from astrbot_compat.loader import parse_reload_command

    for text in _toggle_keywords() + inventory.QUERY_KEYWORDS:
        assert parse_reload_command(text) is None, text


def test_both_sibling_rules_actually_consult_the_reload_parser():
    """上面两条只证明判据本身对；这条确认那两条规则真的调了它。

    少调一处不会让任何断言变红，只会让一句「重载插件 恢复」同时改群设置——
    正是这类互斥最容易退化的方式（加规则的人不会去改另外两条）。
    """
    import ast

    source = (
        _PROJ / "stella_project" / "plugins" / "bot_main" / "ai_gateway.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"is_toggle_command", "is_capability_query"}
    seen: dict[str, bool] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted:
            body = ast.get_source_segment(source, node) or ""
            seen[node.name] = "parse_reload_command" in body
    assert set(seen) == wanted, f"ai_gateway 里找不到 {wanted - set(seen)}——改名了就要同步这个用例"
    assert all(seen.values()), f"这些规则没查重载命令: {[k for k, v in seen.items() if not v]}"


# ---------- 结构化快照：snapshot() ----------


def test_snapshot_carries_no_free_text(reg):
    """约束：快照只出结构化字段。

    与 ``tests/test_status_api.py`` 同一条守卫，但钉的是**源头**：那边过的是
    ``build_payload`` 的出口，这边过的是 ``snapshot()`` 自己，免得将来某条新的取数
    路径绕开状态接口把原文送出去。
    """
    reg.register(
        _cap(
            "weather.query",
            description="查询天气，内部接口 https://api.example.com?api_key=sk-abc",
            examples=("明天会下雨吗", "北京冷不冷"),
            keywords=("天气",),
            tools=("get_forecast",),
        ),
    )
    text = json.dumps(
        inventory.snapshot(target=reg, tool_manager=_manager(get_forecast=True)),
        ensure_ascii=False,
    )
    for banned in ("api_key", "sk-", "http://", "https://", "明天会下雨吗", "查询天气"):
        assert banned not in text, banned
    # 反过来确认样本确实进了注册表——不然上面这几条什么都没验到
    assert '"weather.query"' in text
    assert '"examples": 2' in text


def test_snapshot_routable_matches_registry_exactly(reg):
    """逐条 ``routable`` 必须与 ``registry.routable()`` 一致。

    这是快照唯一可能说谎的字段，而它说的谎恰好是这份清单要回答的那个问题。四条覆盖
    ``routable()`` 的三项判据：route_enabled / 有可用 provider / 有原型语料。
    """
    reg.register(_cap("a.ok", examples=("问一句",), tools=("t_a",)))
    reg.register(_cap("b.off", examples=("问一句",), tools=("t_b",), route_enabled=False))
    reg.register(_cap("c.no_provider", examples=("问一句",)))
    reg.register(_cap("d.no_corpus", tools=("t_d",)))
    snap = inventory.snapshot(
        target=reg,
        tool_manager=_manager(t_a=True, t_b=True, t_d=True),
    )
    assert {c.id for c in reg.routable()} == {"a.ok"}
    assert {i["id"] for i in snap["items"] if i["routable"]} == {"a.ok"}
    assert snap["total"] == 4
    assert snap["routable"] == 1


def test_snapshot_counts_declared_auto_and_unrouted(reg):
    reg.register(_cap("weather.query", examples=("明天下雨吗",), tools=("get_forecast",)))
    reg.register(
        _cap(
            "tool.orphan",
            domain="plugin",
            description="没写声明的插件工具",
            tools=("orphan",),
            route_enabled=False,
            source=SOURCE_AUTO,
        ),
    )
    snap = inventory.snapshot(
        target=reg,
        tool_manager=_manager(get_forecast=True, orphan=True),
    )
    assert snap["declared"] == 1
    assert snap["auto"] == 1
    # 「装了插件却从来不被调用」的那批就是这个数
    assert snap["auto_unrouted"] == 1
    assert snap["version"] == inventory.SNAPSHOT_VERSION
    assert snap["registry_version"] == reg.version


def test_missing_tools_ignores_the_auto_derived_tier(reg):
    """``missing_tools`` 只看声明层。

    自动派生那层是从 ``llm_tools`` 反推出来的，按定义指向存在的工具；把它算进来，
    在「工具注册表读得不全」时会凭空多出一堆假的「工具不存在」，把真正拼错的那个淹掉。
    """
    reg.register(_cap("weather.query", examples=("明天下雨吗",), tools=("get_weahter",)))
    reg.register(
        _cap(
            "tool.ghost",
            domain="plugin",
            description="x",
            tools=("ghost",),
            source=SOURCE_AUTO,
        ),
    )
    snap = inventory.snapshot(target=reg, tool_manager=_manager(get_forecast=True))
    assert snap["missing_tools"] == ["get_weahter"]


def test_tools_known_separates_unreadable_registry_from_an_empty_one(reg):
    """``None``（读不到）与 ``{}``（真的没装工具）必须分开。

    混为一谈时，``astrbot_compat`` 根本没起来的场合会把每个 provider 都标成
    「工具不存在」——那是**谎报**，排查的人会跑去插件目录核一个没问题的名字。
    """
    reg.register(_cap("weather.query", examples=("明天下雨吗",), tools=("get_forecast",)))

    empty = inventory.snapshot(target=reg, tool_manager=_manager())
    assert empty["tools_known"] is True
    assert empty["items"][0]["providers"][0]["tool_state"] == inventory.TOOL_MISSING
    assert empty["missing_tools"] == ["get_forecast"]

    unknown = inventory.snapshot(target=reg, tool_manager=types.SimpleNamespace(tools=None))
    assert unknown["tools_known"] is False
    assert unknown["items"][0]["providers"][0]["tool_state"] == inventory.TOOL_UNKNOWN
    assert unknown["missing_tools"] == []


def test_snapshot_reports_inactive_tool_and_backoff_window(reg):
    """``active=false`` 与失败退避各自的表现。两者都会让能力静默地不被调用。"""
    reg.register(_cap("weather.query", examples=("明天下雨吗",), tools=("get_forecast",)))
    now = time.time()
    provider = reg.get("weather.query").providers[0]
    provider.failures = 3
    # 用真实时钟加偏移而不是造一个假的 now：``registry.routable()`` 内部走的是
    # ``provider.available()``（无参，真实时钟），假时钟会让快照与 routable 打架。
    provider.disabled_until = now + 120

    snap = inventory.snapshot(
        target=reg,
        tool_manager=_manager(get_forecast=False),
        now=now,
    )
    item = snap["items"][0]
    assert item["providers"][0]["tool_state"] == inventory.TOOL_INACTIVE
    assert item["providers"][0]["available"] is False
    assert item["providers"][0]["backoff_seconds"] == 120
    assert item["providers"][0]["failures"] == 3
    assert item["routable"] is False
    assert snap["routable"] == 0


# ---------- 群内文本：chat_overview() ----------


def _two_tier_registry(reg: CapabilityRegistry) -> CapabilityRegistry:
    """一条正常声明 + 一个没写声明的插件工具（方案 §3.1 要区分的两种东西）。"""
    reg.register(
        _cap(
            "weather.query",
            description="查询指定城市的天气",
            examples=("明天会下雨吗",),
            tools=("get_forecast",),
        ),
    )
    reg.register(
        _cap(
            "tool.orphan",
            domain="plugin",
            description="没写声明的插件工具",
            tools=("orphan",),
            route_enabled=False,
            source=SOURCE_AUTO,
        ),
    )
    return reg


def test_chat_overview_member_sees_capabilities_but_no_diagnostics(reg):
    """普通群友：能力清单 + 未声明工具的**条数**。

    来源层、能力 id、未声明工具的具体名单属排查信息，方案 §3.1 只给管理员——
    「让用户知道 Stella 会什么」不需要这些，而它们会把一次提问变成一屏排查输出。
    """
    text = inventory.chat_overview(
        target=_two_tier_registry(reg),
        tool_manager=_manager(get_forecast=True, orphan=True),
    )
    assert "我现在能在聊天里自动用上的能力有 1 项" in text
    assert "【资讯查询】" in text
    assert "查询指定城市的天气" in text
    assert "另有 1 个插件工具没有能力声明" in text
    assert "（管理员）" not in text
    assert "weather.query" not in text
    assert "orphan" not in text


def test_chat_overview_admin_adds_ids_source_tier_and_tool_names(reg):
    text = inventory.chat_overview(
        target=_two_tier_registry(reg),
        tool_manager=_manager(get_forecast=True, orphan=True),
        admin=True,
    )
    assert "weather.query（配置声明）" in text
    assert "未声明的工具：orphan" in text
    assert "docs/plugin-spec.md" in text
    assert "注册表共 2 项" in text
    assert "配置声明 1 项" in text
    assert "自动派生 1 项" in text


def test_chat_overview_admin_names_the_misspelled_tool(reg):
    """声明指向不存在的工具时必须点名——工具名拼错是静默失效的头号原因。"""
    reg.register(
        _cap(
            "weather.query",
            description="查天气",
            examples=("明天会下雨吗",),
            tools=("get_weahter",),
        ),
    )
    text = inventory.chat_overview(
        target=reg,
        tool_manager=_manager(get_forecast=True),
        admin=True,
    )
    assert "get_weahter" in text
    assert "要么那个插件没装，要么工具名拼错了" in text


def test_chat_overview_admin_reports_backoff_and_manual_switch_off(reg):
    reg.register(
        _cap(
            "video.hot",
            domain="entertainment",
            description="热门视频",
            examples=("有什么热门视频",),
            tools=("hot", "hot_backup"),
        ),
    )
    now = time.time()
    cap = reg.get("video.hot")
    cap.providers[0].failures = 3
    cap.providers[0].disabled_until = now + 90
    cap.providers[1].enabled = False
    # 传 data 而不是 tool_manager：退避余量要用同一个 now 算，否则 backoff_seconds
    # 会随两次取时钟的间隔抖动
    text = inventory.chat_overview(
        target=reg,
        admin=True,
        data=inventory.snapshot(
            target=reg,
            tool_manager=_manager(hot=True, hot_backup=True),
            now=now,
        ),
    )
    assert "正在退避：video.hot#hot（连续失败 3 次" in text
    assert "已人工关闭的实现：video.hot#hot_backup" in text
    # 两个实现都不可用 → 这条能力已经不在可路由清单里，管理员要能看出来
    assert "我现在没有可以在聊天里自动触发的能力。" in text


def test_chat_overview_empty_registry_reads_as_a_sentence(reg):
    """空注册表那句话必须读得通——它出现的场合恰好是「装配根本没跑」。

    以前这里会打成「注册表共 0 项：；版本 v0」，而那时读日志的人最需要一句完整的话。
    """
    text = inventory.chat_overview(target=reg, tool_manager=_manager(), admin=True)
    assert "我现在没有可以在聊天里自动触发的能力。" in text
    assert "共 0 项：；" not in text
    assert "注册表共 0 项；" in text


def test_factory_declarations_stay_dark_until_their_plugin_is_installed(reg):
    """回归 bug_report_2026_9_2#1：一个插件都没装的部署答「我能做这 5 项能力」。

    读的是**仓库里真会随发布包出厂的那份** ``config/capabilities/``，而不是现编一条：
    那 5 条娱乐能力就是从那里来的。断言写成「工具一个都不在 → 0 项可路由」而不是钉住
    某个数字，这样以后再加出厂声明，这条守卫照样成立。
    """
    from capability.loader import load_capabilities

    declared = load_capabilities(_PROJ / "config" / "capabilities", reg)
    assert declared > 0, "出厂声明目录空了？这条守卫需要至少一条声明才有意义"

    # 装探针 = Bot 进程；一个工具都查不到 = 一个插件都没装
    reg.set_tool_probe(lambda name: False)
    snap = inventory.snapshot(target=reg, tool_manager=_manager())

    assert snap["declared"] == declared  # 声明照常留在注册表里——装上插件就点亮
    assert snap["routable"] == 0
    assert all(not i["routable"] for i in snap["items"])

    text = inventory.chat_overview(target=reg, data=snap)
    assert "我现在没有可以在聊天里自动触发的能力。" in text
    assert "【娱乐】" not in text

    # 管理员那一份要说清为什么：普通群友看到的是上面那句，排查的人需要工具名
    admin = inventory.chat_overview(target=reg, data=snap, admin=True)
    assert "声明里指向的这些工具不存在" in admin


def test_chat_overview_lists_commands_with_the_configured_wake_prefix(reg, monkeypatch):
    """指令要一起答。只答能力对装了一堆 ``@command`` 的群就是**误导**。

    前缀取 ``wake_prefix()`` 而不是硬编码 ``/``：改过 ``ASTRBOT_WAKE_PREFIXES`` 的
    实例照抄一个 ``/`` 出去，用户发出来的指令不会被识别。
    """
    monkeypatch.setattr(inventory, "_command_names", lambda limit=60: ["天气", "帮助"])
    prefix = inventory.wake_prefix()
    text = inventory.chat_overview(target=reg, tool_manager=_manager())
    assert f"也可以直接发指令：{prefix}天气 {prefix}帮助" in text


def test_chat_overview_admin_warns_when_tool_registry_unreadable(reg):
    reg.register(_cap("weather.query", description="查天气", examples=("下雨吗",), tools=("t",)))
    text = inventory.chat_overview(
        target=reg,
        tool_manager=types.SimpleNamespace(tools=None),
        admin=True,
    )
    assert "读不到工具注册表" in text
    assert "本次不可信" in text


# ---------- CLI 取数：capability_view.collect() ----------


def test_collect_prefers_the_live_snapshot(monkeypatch, reg):
    from deploy import process

    snap = inventory.snapshot(target=reg, tool_manager=_manager())
    monkeypatch.setattr(process, "status", lambda: {"api_reachable": True, "capabilities": snap})
    view = capability_view.collect()
    assert view.live is snap
    assert view.offline is None
    assert view.api_reachable is True


def test_collect_falls_back_to_disk_without_claiming_bot_is_down(monkeypatch):
    """接口可达但没有 ``capabilities`` 块（Bot 是旧版本）**不该**冒充「Bot 没运行」。

    冒充的代价是用户跑去 ``deploy start``，而进程明明活着——``api_reachable`` 必须
    照实传下去，让渲染层说对是哪种情况。
    """
    from deploy import process

    monkeypatch.setattr(process, "status", lambda: {"api_reachable": True, "capabilities": None})
    monkeypatch.setattr(
        inventory,
        "offline_declarations",
        lambda: {"version": 1, "files": [], "drafts": []},
    )
    view = capability_view.collect()
    assert view.live is None
    assert view.api_reachable is True
    out = capability_view.to_terminal(view)
    assert "状态接口可达，但没有返回能力清单" in out
    assert "Stella 未在运行" not in out


# ---------- CLI 渲染：live 分支 ----------


def test_live_table_splits_routable_from_blocked_with_a_reason_each(reg):
    """不可路由的每一条都要说清缺哪一样——判据顺序照 ``registry.routable()``。

    说「不可路由」谁都会；这张表的用途是省掉用户去翻源码的那一步，所以五个成因各验一条。
    """
    reg.register(
        _cap("weather.query", description="查天气", examples=("下雨吗",), tools=("get_forecast",)),
    )
    reg.register(_cap("news.read", examples=("有什么新闻",), tools=("fetch_news",), route_enabled=False))
    reg.register(_cap("music.play", examples=("放首歌",)))
    reg.register(_cap("video.hot", examples=("有什么热门视频",), tools=("hot",)))
    reg.register(_cap("silent.one", tools=("silent",)))
    reg.register(
        _cap(
            "tool.orphan",
            domain="plugin",
            description="孤儿工具",
            tools=("orphan",),
            route_enabled=False,
            source=SOURCE_AUTO,
        ),
    )
    now = time.time()
    reg.get("video.hot").providers[0].failures = 3
    reg.get("video.hot").providers[0].disabled_until = now + 120

    out = _live(
        inventory.snapshot(
            target=reg,
            tool_manager=_manager(
                get_forecast=True, fetch_news=True, hot=True, silent=True, orphan=True,
            ),
            now=now,
        ),
    )
    assert "可被聊天自动触发（1）" in out
    assert "不参与路由（5）" in out
    assert "声明里 route_enabled = false" in out
    assert "声明没有任何 providers" in out
    assert "所有实现都不可用（已关闭或正在退避）" in out
    assert "既没有 examples 也没有 keywords（没有原型语料）" in out
    assert "无能力声明（自动派生）" in out
    assert "退避中 120s／连续失败 3 次" in out
    assert "原因未知" not in out


def test_live_notes_name_the_misspelled_tool_and_the_undeclared_ones(reg):
    """两条说明各对应一个可动手修的成因。

    顺带钉住一个**已知且刻意保留**的性质：只有一个实现、而那个工具名拼错的能力仍然
    算「可路由」——``registry.routable()`` 就是这么判的（它不查工具存不存在），清单跟
    着它说才不会自相矛盾。被抓住的地方是「实现」列里的标注与下面那条说明。
    """
    reg.register(
        _cap("weather.query", description="查天气", examples=("下雨吗",), tools=("get_weahter",)),
    )
    reg.register(
        _cap(
            "tool.orphan",
            domain="plugin",
            description="孤儿工具",
            tools=("orphan",),
            route_enabled=False,
            source=SOURCE_AUTO,
        ),
    )
    out = _live(
        inventory.snapshot(target=reg, tool_manager=_manager(get_forecast=True, orphan=True)),
    )
    assert "可被聊天自动触发（1）" in out
    assert "get_weahter（工具不存在）" in out
    assert "要么那个插件没装，要么工具名拼错了" in out
    assert "有 1 个插件工具没有能力声明" in out
    assert "docs/plugin-spec.md" in out


def test_live_marks_the_tool_registry_as_untrustworthy_when_unreadable(reg):
    reg.register(_cap("weather.query", description="查天气", examples=("下雨吗",), tools=("t",)))
    out = _live(inventory.snapshot(target=reg, tool_manager=types.SimpleNamespace(tools=None)))
    assert "读不到工具注册表" in out
    assert "「工具不存在」这一列本次不可信" in out


def test_live_lists_commands_with_the_configured_wake_prefix(reg, monkeypatch):
    monkeypatch.setattr(inventory, "_command_names", lambda limit=60: ["天气"])
    prefix = inventory.wake_prefix()
    out = _live(inventory.snapshot(target=reg, tool_manager=_manager()))
    assert f"{prefix}天气" in out
    assert "不参与语义路由" in out


def test_live_empty_registry_says_so_instead_of_printing_an_empty_table(reg):
    out = _live(inventory.snapshot(target=reg, tool_manager=_manager()))
    assert "没有任何能力可被聊天自动触发。" in out


def test_live_table_says_when_a_declaration_points_at_a_missing_tool(reg):
    """「插件没装 / 工具名拼错」是这张表最常要回答的一条，得与「被停用」分开报。

    两者在表里长得一样（都是「不可路由」），而它们要人去的地方不同：核插件目录里
    ``@llm_tool`` 的函数名，还是去把 ``active`` 打开。
    """
    reg.register(
        _cap("anime.search", description="检索番剧", examples=("有什么好看的番",), tools=("bgm_search",)),
    )
    reg.register(
        _cap("music.play", description="放歌", examples=("放首歌",), tools=("play_song",)),
    )
    # 真探针对「查不到」与「active=false」都回 False（判据见 comes/executor.resolve_tools）
    reg.set_tool_probe(lambda name: False)

    out = _live(inventory.snapshot(target=reg, tool_manager=_manager(play_song=False)))
    assert "不参与路由（2）" in out
    assert "声明指向的工具不存在（插件没装，或工具名拼错）" in out
    assert "声明指向的工具被停用了（active = false）" in out


def test_live_table_never_blames_a_missing_plugin_when_tools_are_unknown(reg):
    """读不到工具注册表时不许指着用户说「你的插件没装」——那会把人送去翻插件目录。

    这一列的成因在别处（兼容层没起来），而那时 Bot 进程里探针也压根装不上，
    所以这条能力照旧算可路由；表里出现「工具不存在」就说明判据串了。
    """
    reg.register(
        _cap("anime.search", description="检索番剧", examples=("有什么好看的番",), tools=("bgm_search",)),
    )
    out = _live(inventory.snapshot(target=reg, tool_manager=types.SimpleNamespace(tools=None)))
    assert "可被聊天自动触发（1）" in out  # 钉住它没被降级——否则下一行会空过
    assert "声明指向的工具不存在" not in out


# ---------- CLI 渲染：表格对齐 ----------


def test_width_counts_east_asian_characters_as_two_columns():
    assert capability_view._width("资讯查询") == 8
    assert capability_view._width("id") == 2
    assert capability_view._width("能力 id") == 7


def test_table_pads_by_display_width_not_character_count():
    """列宽按终端显示宽度算。

    ``str.ljust`` 按字符数补空格，而这张表把 ASCII 能力 id 和中文来源标签放在相邻列里
    ——按字符数对齐会错开一半，而表格错位比不做表更难读。
    """
    lines = capability_view._table(["域", "备注"], [["资讯查询", "x"], ["娱乐", "y"]])
    prefixes = [line[: line.index("x" if "x" in line else "y")] for line in lines[2:]]
    assert len({capability_view._width(p) for p in prefixes}) == 1
    # 字符数**不**相等，正是「用 ljust 会错位」的那个情形
    assert len({len(p) for p in prefixes}) == 2


# ---------- CLI 渲染：offline 分支（Bot 未运行）----------

_DECL_TOML = """
[[capability]]
id = "weather.query"
description = "查询指定城市的天气"
examples = ["明天会下雨吗", "北京冷不冷"]
keywords = ["天气"]
providers = ["get_forecast"]
"""


@pytest.fixture
def offline_dirs(tmp_path, monkeypatch):
    """把三层声明的取数位置全部钉在临时目录里。

    ``offline_declarations()`` 默认读真实的用户目录与程序目录（仓库里那份出厂声明就
    在后者），不隔离的话断言会随开发机上装了什么而变。
    """
    from capability import loader

    user = tmp_path / "home" / "config" / "capabilities"
    factory = tmp_path / "proj" / "config" / "capabilities"
    plugins = tmp_path / "plugins"
    for path in (user, factory, plugins):
        path.mkdir(parents=True)
    monkeypatch.setattr(loader, "_config_declaration_dirs", lambda: [user, factory])
    monkeypatch.setattr(inventory, "_plugins_dir", lambda: plugins)
    return types.SimpleNamespace(user=user, factory=factory, plugins=plugins)


def _offline(api_reachable: bool = False) -> str:
    return capability_view.to_terminal(
        CapabilityView(live=None, offline=inventory.offline_declarations(), api_reachable=api_reachable),
    )


def test_offline_states_up_front_what_it_cannot_answer(offline_dirs):
    """离线分支**必须**先说清它回答不了「到底可不可路由」。

    那要看工具存不存在、插件加载成不成功、自动派生那层有没有把工具先占走，全都只有
    Bot 进程里才知道。不说的话用户会拿这份清单去解释「为什么没被调用」，而它恰好不含
    那个答案——那是一次比不输出更糟的输出。
    """
    (offline_dirs.user / "information.toml").write_text(_DECL_TOML, encoding="utf-8")
    out = _offline()
    assert "Stella 未在运行" in out
    assert "只是文件内容" in out
    assert "启动后再查一次" in out
    # 原文只在本机 CLI 里露出（不经状态接口），所以这里**应当**能看到描述
    assert "查询指定城市的天气" in out
    assert "weather.query" in out
    assert "get_forecast" in out
    assert "2/1" in out


def test_offline_labels_user_and_factory_tiers_separately(offline_dirs):
    """两层各自标名。用户覆盖没生效时，第一眼要能看出自己改的是哪一份。"""
    (offline_dirs.user / "information.toml").write_text(_DECL_TOML, encoding="utf-8")
    (offline_dirs.factory / "entertainment.toml").write_text(_DECL_TOML, encoding="utf-8")
    out = _offline()
    assert "[用户层]" in out
    assert "[出厂层]" in out


def test_offline_calls_a_single_directory_neither_user_nor_factory(tmp_path, monkeypatch):
    """只有一层时（开发机 / 自包含布局）它同时是两层，别谎称是其中一层。"""
    from capability import loader

    only = tmp_path / "config" / "capabilities"
    only.mkdir(parents=True)
    (only / "information.toml").write_text(_DECL_TOML, encoding="utf-8")
    monkeypatch.setattr(loader, "_config_declaration_dirs", lambda: [only])
    monkeypatch.setattr(inventory, "_plugins_dir", lambda: None)
    out = _offline()
    assert "[配置层]" in out
    assert "[用户层]" not in out
    assert "[出厂层]" not in out


def test_offline_flags_unreviewed_plugin_declaration_and_drafts(offline_dirs):
    """``reviewed = false`` 与 ``*.draft`` 都不会被载入，清单必须说出那句话。

    这两个状态是 §2.2 那道闸门的全部外在表现。不说清的话，用户会以为声明已经生效，
    然后去查一个根本没进注册表的能力为什么不被调用。
    """
    plugin = offline_dirs.plugins / "astrbot_plugin_demo"
    plugin.mkdir()
    (plugin / "capability.toml").write_text(
        "reviewed = false\n" + _DECL_TOML,
        encoding="utf-8",
    )
    (plugin / "capability.toml.draft").write_text(_DECL_TOML, encoding="utf-8")
    out = _offline()
    assert "[插件自带]" in out
    assert "reviewed = false" in out
    assert "未经人审，不会被载入" in out
    assert "待人审的草稿（1 份" in out
    assert "capability.toml.draft" in out


def test_offline_reports_a_broken_toml_without_pretending_it_loaded(offline_dirs):
    (offline_dirs.user / "broken.toml").write_text("[[capability]\nid = ", encoding="utf-8")
    out = _offline()
    assert "解析失败" in out
    assert "该文件整体不会被载入" in out


def test_offline_says_so_when_a_file_has_no_capability_section(offline_dirs):
    (offline_dirs.user / "empty.toml").write_text("reviewed = true\n", encoding="utf-8")
    out = _offline()
    # 缺 [[capability]] 段走的是 parse_declaration 的 error 分支，同样要照实说
    assert "解析失败" in out
    assert "缺少 [[capability]] 段" in out


def test_offline_with_nothing_on_disk_says_nothing_was_found(offline_dirs):
    out = _offline()
    assert "没有找到任何 capability.toml。" in out


def test_offline_distinguishes_old_bot_from_stopped_bot(offline_dirs):
    """接口通了却没有 ``capabilities`` 块 → 说「Bot 可能是旧版本」，不说「未在运行」。"""
    out = _offline(api_reachable=True)
    assert "状态接口可达，但没有返回能力清单" in out
    assert "Stella 未在运行" not in out


# ---------- CLI 渲染：--json ----------


def test_to_json_marks_which_source_it_came_from(reg):
    """``source`` 存在是为了让 GUI 不必靠「哪个 key 是 null」去猜。"""
    snap = inventory.snapshot(target=reg, tool_manager=_manager())
    live = json.loads(
        capability_view.to_json(CapabilityView(live=snap, offline=None, api_reachable=True)),
    )
    assert live["version"] == 1
    assert live["source"] == "live"
    assert live["api_reachable"] is True
    # live 是状态接口那一块**原样**：CLI 与 GUI 读同一份字段，加工过就会两边不一致
    assert live["capabilities"] == snap
    assert live["declarations"] is None

    declarations = {"version": 1, "files": [], "drafts": []}
    offline = json.loads(
        capability_view.to_json(
            CapabilityView(live=None, offline=declarations, api_reachable=False),
        ),
    )
    assert offline["source"] == "offline"
    assert offline["capabilities"] is None
    assert offline["declarations"] == declarations
