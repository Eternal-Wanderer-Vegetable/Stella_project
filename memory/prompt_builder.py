# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆与上下文的 Prompt 拼接工具。

把“短期对话摘要、用户画像、检索到的长期记忆”等结构化信息翻译成 LLM
更容易理解的自然语言段落，插到用户消息之前作为补充上下文。大段记忆会
被截断到固定上限，避免把过长的历史一起塞进一次推理。
"""

from __future__ import annotations

from typing import Iterable


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
        try:
            meta.append(f"重要性={float(importance):.2f}")
        except Exception:
            pass
    if confidence is not None:
        try:
            meta.append(f"置信度={float(confidence):.2f}")
        except Exception:
            pass
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
) -> str:
    """把三层上下文（短期摘要 / 用户画像 / 长期记忆）拼成最终的 prompt。

    参数:
        short_term: 最近的对话摘要或原始消息回退文本；
        user_profile: 关于当前用户的长期画像描述；
        memories: 检索到的长期记忆列表。
    返回:
        组装好的上下文文本；各部分之间以空行分隔。
    """
    parts: list[str] = []
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
