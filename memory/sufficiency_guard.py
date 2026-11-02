# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""生产证据充分性守护（MBENCH-004 P3 生产化，灰度旗标默认关闭）。

对整组记忆包判定回答一个用户问题的证据充分性（三态）：
- SUPPORTED：记忆中存在与问题直接对应的陈述，足以推出答案 → 正常作答；
- INSUFFICIENT：缺少必要证据 → 弃答（固定文案，enforce 模式短路投递）；
- AMBIGUOUS：部分相关/冲突/不确定 → 保守作答（记忆分节追加保守指令）。

可靠性契约（全部 fail-open，与 embedding 回退同一哲学）：
- ROLE_EXTRACT 无后端 / 每日预算拦截 / 调用配额预留不足 / 任何异常 →
  返回 None（不拦截，正常作答）并记日志——守护失效绝不能阻塞回复；
- 判定解析兼容 schema 漂移（verdict 枚举 + sufficient 布尔 + 词面兜底），
  无法解析保守判 AMBIGUOUS（本守护语境下 AMBIGUOUS 只是追加保守指令）。

验证依据：P3 隔离实验（INSUFFICIENT 格对对抗题 26/26 正确弃答、可回答题
误杀率 3.8%）与 P4 未见数据（1,682 题 overall 24.0%→50.6%）。
灰度：``MEMORY_SUFFICIENCY_GUARD_MODE`` off/shadow/enforce（config/settings.py）。
"""

from __future__ import annotations

import json
from typing import Any

SUFFICIENCY_PROMPT_VERSION = "sufficiency-verifier-v1"

_VERIFIER_INSTRUCTIONS = (
    "你是记忆问答的证据充分性审核员。给你一个问题和一组候选记忆，"
    "判断这组记忆**合起来**是否足以直接支持回答该问题所需的事实。"
    "判定标准：\n"
    "SUPPORTED — 记忆中存在与问题直接对应的陈述，其内容足以推出答案；\n"
    "INSUFFICIENT — 记忆中没有与问题直接对应的内容（只有主题相近的无关信息也算不足）；\n"
    "AMBIGUOUS — 有部分相关或相互冲突的信息，不足以确定地回答。\n"
    "注意：多条证据必须合并核对是否完整；不要因为某条记忆与问题主题相近就判 SUPPORTED。\n"
    "只输出一个 JSON 对象，格式严格为：{\"verdict\": \"SUPPORTED\"} 或 "
    "{\"verdict\": \"INSUFFICIENT\"} 或 {\"verdict\": \"AMBIGUOUS\"}。"
    "不要使用 sufficient 布尔字段，不要输出 reason 或其他字段。"
)

VERIFIER_MAX_TOKENS = 2048


def build_pack_text(conversation_memories: list[dict[str, Any]]) -> str:
    """把检索结果的记忆列表拼成验证器输入文本（与评测 answer 阶段同源）。"""
    return "\n".join(
        str(m.get("content") or "").strip()
        for m in conversation_memories or []
        if (m.get("content") or "").strip()
    )


def build_verifier_prompt(question: str, pack_text: str) -> str:
    return (
        f"{pack_text}\n\n---\n问题：{question}\n\n"
        "请按系统规则输出这组记忆对该问题的充分性判定 JSON。"
    )


def _json_segments(text: str) -> list[str]:
    """粗提取所有 {...} 平衡片段（容忍 ``` 围栏与前后杂文本）。"""
    segments: list[str] = []
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                segments.append(text[start : i + 1])
                start = -1
    return segments


def parse_verdict_output(raw: str) -> str:
    """解析验证器输出为三态之一；无法解析保守判 AMBIGUOUS。

    兼容两种实测输出形态：{"verdict": "..."} 与 {"sufficient": true/false}
    （reasoning 模型的 schema 漂移），再退回词面匹配。
    """
    text = (raw or "").strip()
    for segment in _json_segments(text):
        try:
            obj = json.loads(segment)
        except ValueError:
            continue
        if isinstance(obj, dict):
            verdict = str(obj.get("verdict") or "").upper()
            if verdict in ("SUPPORTED", "INSUFFICIENT", "AMBIGUOUS"):
                return verdict
            sufficient = obj.get("sufficient")
            if isinstance(sufficient, bool):
                return "SUPPORTED" if sufficient else "INSUFFICIENT"
    upper = text.upper()
    if "INSUFFICIENT" in upper:
        return "INSUFFICIENT"
    if "AMBIGUOUS" in upper:
        return "AMBIGUOUS"
    if "SUPPORTED" in upper:
        return "SUPPORTED"
    return "AMBIGUOUS"


async def judge_sufficiency(
    question: str,
    conversation_memories: list[dict[str, Any]],
    *,
    conversation_key: str = "",
    turn_deadline: Any = None,
) -> str | None:
    """判定记忆包对问题的充分性；返回三态或 None（fail-open，不拦截）。

    任何一条前置不满足都返回 None：ROLE_EXTRACT 无后端、每日预算拦截、
    包为空、调用异常/超时。调用方（turn_service）据旗标决定 shadow 记录
    或 enforce 拦截。
    """
    pack_text = build_pack_text(conversation_memories)
    if not pack_text:
        return None
    from core.llm.registry import ROLE_EXTRACT, backend_for
    from core.llm.usage_store import budget_blocked

    if budget_blocked(ROLE_EXTRACT):
        return None
    backend = backend_for(ROLE_EXTRACT)
    if backend is None:
        return None

    prompt = build_verifier_prompt(question, pack_text)
    from gravitas.contracts import WorkClass
    from gravitas.model_calls import execute_model_call, role_call_context

    try:
        reply, _finish = await execute_model_call(
            backend,
            prompt,
            _VERIFIER_INSTRUCTIONS,
            context=role_call_context(
                ROLE_EXTRACT,
                work_class=WorkClass.INTERACTIVE,
                tag="sufficiency-guard",
                conversation_key=conversation_key,
                deadline=turn_deadline,
            ),
            detailed=True,
        )
    except Exception as exc:  # fail-open：守护失效绝不阻塞回复
        from nonebot import logger

        logger.warning(f"⚠️ [SufficiencyGuard] 验证器调用失败，fail-open 放行：{exc}")
        return None
    return parse_verdict_output(reply)
