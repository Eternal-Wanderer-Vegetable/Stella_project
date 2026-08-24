# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Level 0：规则快速判断（方案第 8 节）。

目标是**处理高置信度请求**：极低延迟、不调模型。中文里「还记得」「之前说过」
「帮我查一下」这类说法的意图几乎没有歧义，为它们跑一次 embedding 编码是纯浪费。

三类信号，各自独立：

1. ``MEMORY_MARKERS``：明确要求回忆的说法 → memory=True；
2. ``TOOL_MARKERS``：明确要求查询/检索的说法 → 有工具意图（但不知道是哪个能力）；
3. ``NO_MEMORY_PATTERNS``：纯寒暄整句 → memory=False。

外加 ``Capability.keywords`` 的字面匹配 → 能力已确定。

## 两个关键设计

**能力关键词只认显式声明，绝不从 examples 里猜。**
中文没有词边界，从「会不会下雨」切出来的候选里既有「下雨」也有「不会」——
后者会命中几乎任何句子，于是「我不会用这个」被路由去查天气。滑窗切词能切出
好词，但同时一定会切出坏词，而坏词的代价是凭空调一次工具。Level 0 的职责是
「处理高置信度请求」，猜出来的词达不到这个标准。没声明 keywords 的能力
（包括全部自动派生的 ``tool.*``）由 Level 1 语义层负责。

**命中 TOOL_MARKERS 不等于知道要调什么。**
「帮我查一下」后面可能跟天气、股价、番剧。所以只有 keywords 命中时规则才敢
直接拍板；仅有工具意图时返回 None，把能力选择交给 Level 1。

**NO_MEMORY 判定必须整句匹配且集合极窄。**
判为不需要记忆的代价不对称——「Stella 突然不记得你了」不抛异常、不影响回复，
是静默退化（与 2026-08-17 那次 AT_MENTION 全为 0 同一类型）。宁可多查一次。
"""

from __future__ import annotations

import re

from capability.registry import CapabilityRegistry
from capability.registry import registry as _default_registry
from capability.router.types import LEVEL_RULE, CapabilityHit, Route

# ---- 记忆信号：明确要求回忆过去 ----
MEMORY_MARKERS: tuple[str, ...] = (
    "还记得",
    "记不记得",
    "记得吗",
    "之前说过",
    "之前提过",
    "之前聊过",
    "我跟你说过",
    "我告诉过你",
    "上次说",
    "上次聊",
    "你忘了",
    "忘记了吗",
)

# ---- 工具信号：明确要求查询/检索/执行 ----
# 只表示「需要动用外部能力」，不表示是哪一个——能力选择交给 Level 1。
TOOL_MARKERS: tuple[str, ...] = (
    "搜索",
    "搜一下",
    "搜下",
    "查一下",
    "查下",
    "查查",
    "帮我查",
    "帮我找",
    "帮我搜",
    "百度",
    "谷歌",
)

# ---- 纯寒暄整句 ----
NO_MEMORY_PATTERNS: tuple[str, ...] = (
    r"^在吗[?？!！~。\s]*$",
    r"^你好[呀啊哇~!！。\s]*$",
    r"^早上?好[呀啊~!！。\s]*$",
    r"^晚上?好[呀啊~!！。\s]*$",
    r"^晚安[呀啊~!！。\s]*$",
    r"^哈哈+[~!！。\s]*$",
    r"^在干嘛[?？~。\s]*$",
)

_NO_MEMORY_RE = tuple(re.compile(p) for p in NO_MEMORY_PATTERNS)

# 关键词最短长度。1 字关键词（「查」「看」）会命中几乎任何句子，
# 声明了也不采纳——这类拦截放在加载期不如放在使用期，因为声明文件是人写的。
MIN_KEYWORD_LEN = 2


def _is_pure_greeting(message: str) -> bool:
    """整句是纯寒暄。必须整句匹配——「你好，还记得我的旅行计划吗」不算。"""
    text = message.strip()
    return any(pattern.match(text) for pattern in _NO_MEMORY_RE)


def match_capabilities(
    message: str,
    target: CapabilityRegistry | None = None,
) -> list[CapabilityHit]:
    """字面匹配：消息里出现了某能力显式声明的 ``keywords``。

    命中即给 score=1.0——字面出现是确定信号，不与语义相似度同尺度比较
    （见 CapabilityHit.score 的注释）。未声明 keywords 的能力不参与。
    """
    reg = target if target is not None else _default_registry
    text = message.strip()
    if not text:
        return []

    hits: list[CapabilityHit] = []
    for capability in reg.routable():
        usable = [
            kw for kw in capability.keywords if kw and len(kw.strip()) >= MIN_KEYWORD_LEN
        ]
        if any(kw.strip() in text for kw in usable):
            hits.append(CapabilityHit(capability_id=capability.id, score=1.0))
    # 排序保证结果确定（便于测试与日志比对）
    hits.sort(key=lambda h: h.capability_id)
    return hits


def has_tool_intent(message: str) -> bool:
    """是否命中工具信号（只说明想查东西，不说明查什么）。"""
    return any(marker in message for marker in TOOL_MARKERS)


def has_memory_intent(message: str) -> bool:
    """是否明确要求回忆过去。"""
    return any(marker in message for marker in MEMORY_MARKERS)


def apply_rules(
    message: str,
    target: CapabilityRegistry | None = None,
) -> Route | None:
    """跑 Level 0 规则。返回 None 表示「规则给不出高置信结论」，应交给 Level 1。

    返回 Route 的情形：
    1. keywords 命中某能力 → tool=True 且能力已确定，直接拍板；
    2. 整句纯寒暄且无工具/记忆意图 → memory=False，确定不需要工具；
    3. 只有记忆意图、无工具意图 → memory=True + tool=False，省掉一次 embedding。

    返回 None 的情形：有工具意图但能力未定，或普通闲聊（规则无从判断）。
    """
    text = (message or "").strip()
    if not text:
        return Route(chat=True, memory=False, tool=False, level=LEVEL_RULE, reason="空消息")

    wants_memory = has_memory_intent(text)
    wants_tool = has_tool_intent(text)
    hits = match_capabilities(text, target)

    # 情形 1：能力已被关键词确定，规则可以完整拍板
    if hits:
        return Route(
            chat=True,
            memory=wants_memory or not _is_pure_greeting(text),
            tool=True,
            capabilities=hits,
            top_score=1.0,
            level=LEVEL_RULE,
            reason=f"关键词命中能力 {[h.capability_id for h in hits]}",
        )

    # 情形 2：纯寒暄，确定既不需要记忆也不需要工具
    if _is_pure_greeting(text) and not wants_tool and not wants_memory:
        return Route(
            chat=True,
            memory=False,
            tool=False,
            level=LEVEL_RULE,
            reason="纯寒暄，无需记忆与工具",
        )

    # 有工具意图但不知道调什么 → 交给 Level 1 选能力
    if wants_tool:
        return None

    # 情形 3：只命中记忆信号。memory 本就默认 True，但能确定不需要工具，
    # 故直接短路省掉一次 embedding 编码。
    if wants_memory:
        return Route(
            chat=True,
            memory=True,
            tool=False,
            level=LEVEL_RULE,
            reason="命中记忆信号，无工具意图",
        )

    return None


__all__ = [
    "MEMORY_MARKERS",
    "MIN_KEYWORD_LEN",
    "NO_MEMORY_PATTERNS",
    "TOOL_MARKERS",
    "apply_rules",
    "has_memory_intent",
    "has_tool_intent",
    "match_capabilities",
]
