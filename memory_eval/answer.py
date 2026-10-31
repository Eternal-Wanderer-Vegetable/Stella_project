# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""生产检索 + 记忆包组装 + 短答生成（评测侧，无生产代码改动）。"""

from __future__ import annotations

import time
from typing import Any

# 检索通道（与 memory/benchmark.py RETRIEVAL_MODES 语义一致）：
#   rule     : RAG off + 无语义分
#   embedding: RAG off + 真实 embedding 语义分（服务不可用回退 rule）
#   fts      : RAG on  + 无语义分
#   hybrid   : RAG on  + 真实 embedding 语义分（生产默认形态）
CHANNELS: dict[str, tuple[bool, bool]] = {
    "rule": (False, False),
    "embedding": (False, True),
    "fts": (True, False),
    "hybrid": (True, True),
}

ANSWER_PROMPT_VERSION = "memory-eval-answer-v1"

_ANSWER_INSTRUCTIONS = (
    "根据上面分节给出的记忆信息回答最后的问题。只使用记忆里能找到的信息；"
    "如果记忆中没有足够信息，就明确说明你没有相关信息，不要编造。"
    "用与问题相同的语言，用一两句话简短回答。"
)


def compose_answer_prompt(result: Any, question: str, asker: str) -> tuple[str, int]:
    """组装评测问答 prompt；返回 (prompt, 记忆包字符数)。"""
    from memory.prompt_builder import build_v2_named_sections

    sections = build_v2_named_sections(
        "",
        "",
        result.conversation_memories,
        result.behavior_constraints,
        current_user_id=None,
        mode="CASUAL_REPLY",
    )
    parts = [f"【{name}】\n{text}" for name, text in sections if (text or "").strip()]
    pack_chars = sum(len(text) for _, text in sections)
    has_memories = any(name == "memories" and (text or "").strip() for name, text in sections)
    memory_block = "\n\n".join(parts) if parts else "（只有当前时间信息）"
    if not has_memories:
        memory_block += "\n\n（本题未召回任何长期记忆。）"
    prompt = (
        f"{memory_block}\n\n---\n{_ANSWER_INSTRUCTIONS}\n\n"
        f"问题（来自用户 {asker}）：{question}"
    )
    return prompt, pack_chars


async def answer_question(
    env: Any,
    scenario: dict[str, Any],
    qa: dict[str, Any],
    *,
    channel: str,
    llm: Any,
    service: Any = None,
    pack_mode: str | None = None,
) -> dict[str, Any]:
    """对单个 QA 走生产检索 → 记忆包 → 短答；返回带检索与成本明细的记录。

    ``pack_mode=None`` 走生产 ``detect_mode`` 自动分类；显式传入用法模式
    （如 ``CONFLICT_AVOID``，limit=10）即为「检索友好配置」对照实验。
    """
    import memory.retrieval_v2 as retrieval_v2
    from config.spaces import resolve_space

    if channel not in CHANNELS:
        raise ValueError(f"未知检索通道：{channel!r}（可选 {sorted(CHANNELS)}）")
    rag_enabled, use_embedding = CHANNELS[channel]
    space = resolve_space(int(scenario["group_id"]))
    asker = str((scenario.get("speakers") or {}).get("a") or "user A")

    old = (retrieval_v2.RAG_ENABLED, retrieval_v2.MEMORY_V2_ENABLED)
    started = time.monotonic()
    try:
        retrieval_v2.RAG_ENABLED = rag_enabled
        retrieval_v2.MEMORY_V2_ENABLED = True
        retrieval_v2._CACHE.clear()
        if use_embedding:
            result = await retrieval_v2.retrieve_memories_emb(
                space, None, qa["question"], trigger="reply", service=service,
                mode=pack_mode,
            )
        else:
            result = retrieval_v2.retrieve_memories(
                space, None, qa["question"], trigger="reply", mode=pack_mode
            )
    finally:
        retrieval_v2.RAG_ENABLED, retrieval_v2.MEMORY_V2_ENABLED = old
        retrieval_v2._CACHE.clear()

    prompt, pack_chars = compose_answer_prompt(result, qa["question"], asker)
    # reasoning 模型（gemma-4-e / qwen3.8 系）会先输出隐藏思考，预算必须给足
    completion = llm.chat(prompt, max_tokens=2048, temperature=0.0)
    retrieval_latency = time.monotonic() - started

    return {
        "qid": qa["qid"],
        "category": qa.get("category"),
        "category_name": qa.get("category_name"),
        "question": qa["question"],
        "gold_answer": qa.get("gold_answer"),
        "adversarial_answer": qa.get("adversarial_answer"),
        "evidence_dia_ids": qa.get("evidence_dia_ids") or [],
        "answer": completion["text"].strip(),
        "retrieved_ids": [m.get("id") for m in result.conversation_memories],
        "retrieved_contents": [m.get("content") or "" for m in result.conversation_memories],
        "behavior_ids": [m.get("id") for m in result.behavior_constraints],
        "retrieval_result_mode": result.mode,
        "pack_chars": pack_chars,
        "pack_memory_count": len(result.conversation_memories),
        "retrieval_latency_seconds": round(retrieval_latency, 3),
        "answer_latency_seconds": round(completion["latency_seconds"], 3),
        "answer_prompt_tokens": completion["prompt_tokens"],
        "answer_completion_tokens": completion["completion_tokens"],
    }
