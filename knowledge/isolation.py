# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆隔离护栏（plan §6.7：外部文档与引用不得成为个人记忆候选）。

知识证据进入 prompt 的同时，必须**在结构上**与记忆系统保持分离。本模块
是这条红线的运行时检查面 + 契约文档：

1. 证据只住在 ``ChatContext.knowledge_evidence``，它不是
   ``memories_for_prompt`` / ``conversation_memories`` 的输入；
2. 记忆整合（consolidator）的输入是 ``group_messages`` 原始聊天记录——
   证据从未被写进该表，整合管线自然见不到它；
3. ``evidence_leaked_into_memory`` 在每轮证据注入后运行（capability.hooks
   调用），一旦发现证据文本出现在任何记忆字段里，立刻告警——隔离被破坏
   是 must-fix 级别的事故，宁可吵闹不可静默。

该检查是**纵深防御的最后一道**，不是唯一一道：写入侧（hooks 分流、
pipeline 渲染）从来不会把证据写进记忆字段，这里防的是未来改动不小心
打破契约。
"""

from __future__ import annotations

from typing import Any

# 记忆 bound 字段：证据文本不得出现在其中任何一个里。
_MEMORY_TEXT_FIELDS = ("short_term", "user_profile")

# 记忆条目 dict 里承载文本的键（memories_for_prompt / conversation_memories /
# behavior_constraints 的条目形态；缺键的条目跳过）。
_MEMORY_ITEM_KEYS = ("content", "text", "summary", "rule")


def _memory_texts(ctx: Any) -> list[str]:
    """收集 ctx 里全部记忆 bound 文本（渲染前字段的原始形态）。"""
    texts: list[str] = []
    for field_name in _MEMORY_TEXT_FIELDS:
        value = getattr(ctx, field_name, None)
        if isinstance(value, str) and value:
            texts.append(value)
    for list_name in (
        "memories_for_prompt",
        "conversation_memories",
        "behavior_constraints",
    ):
        items = getattr(ctx, list_name, None) or []
        for item in items:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                for key in _MEMORY_ITEM_KEYS:
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        texts.append(value)
    return texts


def evidence_leaked_into_memory(ctx: Any) -> list[str]:
    """返回泄漏进记忆字段的知识证据文本列表；空列表 = 隔离成立。

    判定用「证据文本（规范化后前 80 字）是否是某记忆文本的子串」——
    整段照抄会命中，压缩改写不命中；后者是记忆系统的正常工作
    （它整合的是聊天记录，不是证据），不是泄漏。
    """
    evidence = getattr(ctx, "knowledge_evidence", None) or []
    if not evidence:
        return []
    from memory.text_similarity import normalize_text

    memory_texts = _memory_texts(ctx)
    if not memory_texts:
        return []
    normalized_memories = [normalize_text(t) for t in memory_texts]
    leaked: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        text = normalize_text(str(item.get("text", "") or ""))[:80]
        if not text:
            continue
        if any(text in memory for memory in normalized_memories):
            leaked.append(str(item.get("text", ""))[:80])
    return leaked


__all__ = [
    "evidence_leaked_into_memory",
]
