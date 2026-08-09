# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆与上下文的 Prompt 拼接工具。

把“短期对话摘要、用户画像、检索到的长期记忆”等结构化信息翻译成 LLM
更容易理解的自然语言段落，插到用户消息之前作为补充上下文。大段记忆会
被截断到固定上限，避免把过长的历史一起塞进一次推理。

v2（记忆系统升级）新增分区拼接：聊天素材（Conversation Memory）与行为约束
（Behavior Constraint）必须分开注入，两区绝不混合——这是 Prompt 组织影响
模型表现最明显的地方。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable

from config import (
    MEMORY_BEHAVIOR_MAX_TOKENS,
    MEMORY_CONVERSATION_MAX_TOKENS,
    MEMORY_CONVERSATION_TECH_MAX_TOKENS,
)
from memory.policy import MODE_CONFLICT_AVOID, MODE_TECH_HELP


def naturalize_memory(mem: dict) -> str:
    """把单条记忆 dict 转成一句自然语言描述。

    会附带“重要性 / 置信度”这类元信息（若存在），让模型在生成回复时能
    参考这条记忆的可靠程度与权重。
    """
    content = mem.get("content", "").strip()
    user_id = mem.get("user_id", "")
    type_ = mem.get("type", "FACT")
    if not content:
        return ""
    # 包含信心与重要度信息（如果有），以便 LLM 在生成时考虑权重
    importance = mem.get("importance")
    confidence = mem.get("confidence")
    meta = []
    if importance is not None:
        with contextlib.suppress(Exception):
            meta.append(f"重要性={float(importance):.2f}")
    if confidence is not None:
        with contextlib.suppress(Exception):
            meta.append(f"置信度={float(confidence):.2f}")
    meta_s = ("（" + ", ".join(meta) + "）") if meta else ""
    if type_ and type_ != "FACT":
        return f"记忆：用户{user_id} 的 {type_.lower()}：{content}{meta_s}。"
    return f"记忆：用户{user_id} 曾提到：{content}{meta_s}。"


def build_memory_context(memories: Iterable[dict]) -> str:
    """把一批记忆逐条自然化，拼成换行分隔的上下文文本。

    只保留含 content 的有效条目；没有内容时返回空串。
    """
    items = [naturalize_memory(mem) for mem in memories if mem.get("content")]
    if not items:
        return ""
    return "\n".join(items)


def build_prompt_context(
    short_term: str,
    user_profile: str,
    memories: Iterable[dict],
    current_user_id=None,
) -> str:
    """把三层上下文（短期摘要 / 用户画像 / 长期记忆）拼成最终的 prompt。

    参数:
        short_term: 最近的对话摘要或原始消息回退文本；
        user_profile: 关于当前用户的长期画像描述；
        memories: 检索到的长期记忆列表；
        current_user_id: 当前正在对话的用户 QQ 号（主动发言时为 0/None）。
    返回:
        组装好的上下文文本；各部分之间以空行分隔。
    """
    parts: list[str] = []
    # 明确当前说话人身份，避免模型把摘要/记忆中其他用户的发言归属到当前用户
    if current_user_id not in (None, 0):
        parts.append(
            f"当前与你对话的用户 QQ 号：{current_user_id}。"
            f"注意：上下文里标注了用户QQ号的内容属于对应的人，"
            f"只有明确写着当前用户 {current_user_id} 的才归 TA；不要把别人的发言当成 TA 说的。"
        )
    if short_term:
        parts.append(f"当前对话摘要：\n{short_term}")
    if user_profile:
        parts.append(f"关于当前用户：\n{user_profile}")
    # 仅取前 N 条记忆以避免 prompt 过长
    mem_list = list(memories) if memories is not None else []
    if mem_list:
        limit = 10
        mem_text = build_memory_context(mem_list[:limit])
        if mem_text:
            parts.append(f"相关记忆回想（最多{limit}条）：\n{mem_text}")
    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════
# v2：分区注入（Conversation Memory / Behavior Constraint 分离）
# ════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文字符按 1.5 token、其余按单词计（保守估算）。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_words = len([w for w in text.split() if w])
    return int(cjk * 1.5 + other_words * 1.3)


def build_conversation_section(
    memories: Iterable[dict],
    max_tokens: int = MEMORY_CONVERSATION_MAX_TOKENS,
) -> str:
    """把聊天素材记忆拼成分区文本（可参考的聊天背景），超预算时截断。

    内容不再附带“重要性/置信度”等元信息——这些是给系统看的数据，塞给模型
    会让回复听起来像在念数据库。
    """
    items: list[str] = []
    budget = max_tokens
    for mem in memories:
        content = (mem.get("content") or "").strip()
        if not content:
            continue
        text = f"- {content}"
        tokens = estimate_tokens(text)
        if items and budget - tokens < 0:
            break
        items.append(text)
        budget -= tokens
    if not items:
        return ""
    return "可参考的聊天背景：\n" + "\n".join(items)


def build_behavior_section(
    constraints: Iterable[dict],
    max_tokens: int = MEMORY_BEHAVIOR_MAX_TOKENS,
) -> str:
    """把行为约束（Behavior Guard）拼成分区文本（交流注意），超预算时截断。"""
    items: list[str] = []
    budget = max_tokens
    for mem in constraints:
        rule = (mem.get("behavior_rule") or "").strip()
        if not rule:
            content = (mem.get("content") or "").strip()
            if not content:
                continue
            rule = f"避免主动针对相关成员进行涉及「{content}」的互动。"
        text = f"- {rule}"
        tokens = estimate_tokens(text)
        if items and budget - tokens < 0:
            break
        items.append(text)
        budget -= tokens
    if not items:
        return ""
    return "交流注意：\n" + "\n".join(items)


def build_v2_prompt_context(
    short_term: str,
    user_profile: str,
    conversation_memories: Iterable[dict],
    behavior_constraints: Iterable[dict],
    current_user_id=None,
    mode: str = "CASUAL_REPLY",
) -> str:
    """v2 分区版 Prompt 组装：对话摘要 / 用户画像 / 聊天背景 / 行为约束 四区分离。

    :param short_term: 短期摘要或最近消息回退文本；
    :param user_profile: 关于当前用户的稳定画像（仅稳定事实）；
    :param conversation_memories: 已按 Policy 过滤并排序的聊天素材记忆；
    :param behavior_constraints: 行为约束记忆（RESTRICTED/BOUNDARY）；
    :param current_user_id: 当前用户 QQ 号（主动发言时为 0/None）；
    :param mode: Stella 行为模式（决定聊天素材 token 预算）。
    """
    parts: list[str] = []
    if current_user_id not in (None, 0):
        parts.append(
            f"当前与你对话的用户 QQ 号：{current_user_id}。"
            f"注意：上下文里标注了用户QQ号的内容属于对应的人，"
            f"只有明确写着当前用户 {current_user_id} 的才归 TA；不要把别人的发言当成 TA 说的。"
        )
    if short_term:
        parts.append(f"当前对话摘要：\n{short_term}")
    if user_profile:
        parts.append(f"关于当前用户：\n{user_profile}")

    # 技术/冲突场景放宽聊天素材预算
    if mode == MODE_TECH_HELP:
        conv_max = MEMORY_CONVERSATION_TECH_MAX_TOKENS
    elif mode == MODE_CONFLICT_AVOID:
        # 安全优先：冲突场景给行为约束更多空间
        conv_max = max(100, MEMORY_CONVERSATION_MAX_TOKENS // 2)
    else:
        conv_max = MEMORY_CONVERSATION_MAX_TOKENS

    conv = build_conversation_section(conversation_memories, max_tokens=conv_max)
    if conv:
        parts.append(conv)

    # 行为约束与聊天素材严格分离
    behavior = build_behavior_section(behavior_constraints)
    if behavior:
        parts.append(behavior)

    return "\n\n".join(parts)
