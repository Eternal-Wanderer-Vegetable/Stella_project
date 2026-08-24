# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Level 0 规则路由的单测。

重点钉三件事：
1. **能力关键词只认显式声明**。从 examples 猜词一定会切出「不会」这类
   命中一切的坏词，代价是凭空调一次工具；
2. **规则只在能确定「需要什么」时才短路**。命中「帮我查一下」不等于知道查什么，
   必须返回 None 把能力选择交给 Level 1；
3. **NO_MEMORY 判定必须整句匹配**。判为不需要记忆的代价不对称
   （「Stella 突然不记得你了」是静默退化），宁可多查一次。
"""

from capability.registry import Capability, CapabilityProvider, CapabilityRegistry
from capability.router.rules import (
    MIN_KEYWORD_LEN,
    apply_rules,
    has_memory_intent,
    has_tool_intent,
    match_capabilities,
)
from capability.router.types import LEVEL_RULE


def _registry(*caps: Capability) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for cap in caps:
        reg.register(cap)
    return reg


def _cap(cap_id: str, keywords: list[str], examples: list[str] | None = None) -> Capability:
    return Capability(
        id=cap_id,
        description=f"{cap_id} 描述",
        examples=examples if examples is not None else ["示例句子"],
        keywords=keywords,
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}#tool",
                capability_id=cap_id,
                tool_name=f"{cap_id}_tool",
            ),
        ],
    )


def _weather() -> Capability:
    return _cap(
        "weather.query",
        keywords=["天气", "气温", "下雨"],
        examples=["明天天气怎么样", "会不会下雨"],
    )


def _anime() -> Capability:
    return _cap("anime.search", keywords=["番剧", "动画"], examples=["这部番剧什么时候更新"])


# ---------- 信号识别 ----------


def test_tool_and_memory_intent_markers():
    assert has_tool_intent("帮我查一下这个")
    assert not has_tool_intent("今天心情不好")
    assert has_memory_intent("你还记得我说的话吗")
    assert not has_memory_intent("今天天气不错")


# ---------- 关键词匹配 ----------


def test_match_capabilities_hits_declared_keyword():
    reg = _registry(_weather())
    hits = match_capabilities("东京天气如何", reg)
    assert [h.capability_id for h in hits] == ["weather.query"]
    # 字面出现是确定信号，给满分（不与语义相似度同尺度比较）
    assert hits[0].score == 1.0


def test_match_capabilities_ignores_words_only_in_examples():
    """回归：examples 里的词不参与字面匹配。

    「会不会下雨」若被切词，「不会」会成为 weather.query 的特征词，
    于是「我不会用这个软件」被路由去查天气。
    """
    reg = _registry(_cap("weather.query", keywords=[], examples=["会不会下雨"]))
    assert match_capabilities("我不会用这个软件", reg) == []
    assert match_capabilities("会不会下雨", reg) == []


def test_match_capabilities_rejects_single_char_keyword():
    """1 字关键词命中一切，声明了也不采纳。"""
    assert MIN_KEYWORD_LEN == 2
    reg = _registry(_cap("x.y", keywords=["查"]))
    assert match_capabilities("我查了一下资料", reg) == []


def test_match_capabilities_ignores_capability_without_provider():
    """没 provider 的能力路由到了也执行不了，routable() 已排除。"""
    reg = _registry(Capability(id="weather.query", keywords=["天气"], examples=["天气"]))
    assert match_capabilities("今天天气", reg) == []


def test_match_capabilities_can_hit_multiple_sorted():
    reg = _registry(_weather(), _anime())
    hits = match_capabilities("天气好的话就在家看番剧", reg)
    assert [h.capability_id for h in hits] == ["anime.search", "weather.query"]


def test_match_capabilities_empty_message():
    assert match_capabilities("   ", _registry(_weather())) == []


# ---------- 规则判定 ----------


def test_keyword_hit_short_circuits_with_tool():
    """情形 1：能力已被关键词确定，规则可以完整拍板。"""
    route = apply_rules("帮我看看东京天气", _registry(_weather()))
    assert route is not None
    assert route.tool is True
    assert route.capability_ids == ["weather.query"]
    assert route.level == LEVEL_RULE


def test_tool_marker_without_capability_defers_to_level1():
    """情形 2：想查东西但不知道查什么——必须交给 Level 1 选能力。"""
    assert apply_rules("帮我查一下", _registry(_weather())) is None
    assert apply_rules("搜一下这个", _registry(_weather())) is None


def test_pure_greeting_disables_memory():
    route = apply_rules("在吗？", _registry(_weather()))
    assert route is not None
    assert route.memory is False
    assert route.tool is False
    assert route.level == LEVEL_RULE


def test_greeting_with_real_content_keeps_memory():
    """回归：整句匹配。「你好」开头但带实质内容的句子不能被判成寒暄。"""
    route = apply_rules("你好，还记得我的旅行计划吗", _registry(_weather()))
    assert route is not None
    assert route.memory is True


def test_greeting_with_tool_marker_is_not_greeting():
    """「在吗」+ 工具意图：不能按纯寒暄短路掉工具判定。"""
    assert apply_rules("在吗，帮我查一下", _registry(_weather())) is None


def test_memory_marker_short_circuits_without_tool():
    """命中记忆信号且无工具意图：能确定不需要工具，省掉一次 embedding 编码。"""
    route = apply_rules("你还记得我之前说的旅行计划吗", _registry(_weather()))
    assert route is not None
    assert route.memory is True
    assert route.tool is False
    assert route.level == LEVEL_RULE


def test_memory_marker_with_tool_marker_defers():
    """既要回忆又要查东西：能力未定，仍需 Level 1。"""
    assert apply_rules("还记得我的计划吗，帮我查一下", _registry(_weather())) is None


def test_keyword_hit_with_memory_marker_keeps_both():
    route = apply_rules("还记得我说的天气吗", _registry(_weather()))
    assert route is not None
    assert route.tool is True
    assert route.memory is True


def test_plain_chat_defers_to_level1():
    """普通闲聊规则给不出结论，交给 Level 1。"""
    assert apply_rules("今天心情不太好", _registry(_weather())) is None


def test_empty_message_needs_nothing():
    route = apply_rules("", _registry(_weather()))
    assert route is not None
    assert route.memory is False
    assert route.tool is False


def test_auto_derived_capability_has_no_level0_matching():
    """自动派生的 tool.* 没有 keywords，只能靠 Level 1 —— 这是刻意的。"""
    reg = _registry(_cap("tool.get_weather", keywords=[], examples=["get weather"]))
    assert match_capabilities("天气怎么样", reg) == []
    assert apply_rules("天气怎么样", reg) is None
