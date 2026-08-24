# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Result.data → Result.summary 的压缩（方案第 5 节）。

```
完整天气数据（大量 JSON）  →  "东京明天27℃，晴，降雨概率10%。"
```

为什么必须压缩：方案第 3.1 节说「工具描述会污染聊天上下文」——结果数据同样会。
一次搜索能返回几千字，原样拼进 Stella 的 prompt 会把 8192 的工作窗口挤爆，
把记忆与对话上下文全挤出去。

**压缩不调模型。** 受限 agent 读完工具输出后写的那句话（``completion_text``）
天然就是摘要，直接用它即可；它为空时才退到工具原文截断。为摘要再调一次 27B
是在聊天主链路上多加一次串行等待，而用户正在等回复。
"""

from __future__ import annotations

from typing import Any

# 与 astrbot_compat.llm.agent 的常量同源：工具没有返回值时回喂给模型的占位文本。
# 它是给模型看的内部标记，对 Stella 毫无意义，必须从摘要里剔掉。
_NO_RETURN_MARKERS = (
    "The tool has no return value",
    "has sent the result directly to the user",
)

# 工具执行失败时 execute_tool 返回的前缀（见 astrbot_compat/llm/agent.py）
ERROR_PREFIX = "error:"


def is_error(content: str) -> bool:
    """这段工具输出是否表示失败。"""
    return (content or "").strip().lower().startswith(ERROR_PREFIX)


def is_no_return(content: str) -> bool:
    """这段工具输出是否是「无返回值 / 已直接回复用户」的内部占位。"""
    text = content or ""
    return any(marker in text for marker in _NO_RETURN_MARKERS)


def truncate(text: str, limit: int) -> str:
    """按字符数截断，超出时加省略号。limit <= 0 表示不限制。"""
    clean = (text or "").strip()
    if limit <= 0 or len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "…"


def from_tool_outputs(outputs: list[tuple[str, str]], limit: int) -> str:
    """从工具原始输出拼一段摘要（受限 agent 没给出结论时的兜底）。

    参数:
        outputs: ``[(工具名, 输出文本), ...]``；
        limit: 摘要总长度上限。

    失败与「无返回值」的条目都跳过——前者对 Stella 没有信息量（它不该向用户解释
    某个工具报了什么错），后者是内部占位。全部跳过后返回空串，由调用方决定
    要不要给 Stella 一个「查询未果」的提示。
    """
    usable = [
        (name, (content or "").strip())
        for name, content in outputs
        if content and not is_error(content) and not is_no_return(content)
    ]
    if not usable:
        return ""

    # 单个工具时不加工具名前缀：「东京27℃」比「get_weather: 东京27℃」自然得多，
    # 而 Stella 的 prompt 里工具名毫无意义（它根本不知道有哪些工具）。
    if len(usable) == 1:
        return truncate(usable[0][1], limit)

    # 多工具时按条列出。均分预算，避免第一个工具的长输出吃掉全部额度。
    per_item = max(limit // len(usable), 40) if limit > 0 else 0
    lines = [truncate(content, per_item) for _, content in usable]
    return truncate("\n".join(lines), limit)


def summarize(
    completion_text: str,
    outputs: list[tuple[str, str]],
    limit: int,
) -> str:
    """产出进 Stella prompt 的摘要。

    优先用受限 agent 的结论（它已经读过工具输出、用自然语言总结过），
    为空时退到工具原文。两者都为空则返回空串。
    """
    text = (completion_text or "").strip()
    # agent 有时会把内部占位原样复述出来，那等于没有结论
    if text and not is_no_return(text):
        return truncate(text, limit)
    return from_tool_outputs(outputs, limit)


def stringify(value: Any) -> str:
    """把任意工具返回值转成文本（供 data 的日志渲染，不进 prompt）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return repr(value)


__all__ = [
    "ERROR_PREFIX",
    "from_tool_outputs",
    "is_error",
    "is_no_return",
    "stringify",
    "summarize",
    "truncate",
]
