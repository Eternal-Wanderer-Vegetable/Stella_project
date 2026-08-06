from __future__ import annotations

from typing import Iterable


def naturalize_memory(mem: dict) -> str:
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
    items = [naturalize_memory(mem) for mem in memories if mem.get("content")]
    if not items:
        return ""
    return "\n".join(items)


def build_prompt_context(short_term: str, user_profile: str, memories: Iterable[dict]) -> str:
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
