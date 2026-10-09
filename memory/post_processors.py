# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""LLM 原始输出的后处理工具。

解析模型返回的 ``<thought>``/``<action>``/``<reply>`` 三段标记文本，
做行数收敛、坏语料过滤；当模型没给出可用回复时，兜底到底层
FALLBACK_REPLY，并把每次思考过程写入 thought 日志供调试。
"""

from __future__ import annotations

import re
from datetime import datetime

from nonebot import logger

from config import (
    BAD_PHRASES,
    FALLBACK_REPLY,
    MAX_REPLY_LINES,
    THOUGHT_LOG_PATH,
)
from core.context import ChatContext


def parse_raw_output(raw: str) -> tuple[str, str, str]:
    thought = "（无思考过程）"
    action = "NONE"
    reply = ""

    thought_match = re.search(r"<thought>(.*?)(?:</thought>|<action>|<reply>|$)", raw, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_match = re.search(r"<action>(.*?)(?:</action>|<reply>|$)", raw, re.DOTALL)
    if action_match:
        action = action_match.group(1).strip()

    reply_match = re.search(r"<reply>(.*?)(?:</reply>|$)", raw, re.DOTALL)
    if reply_match:
        reply = reply_match.group(1).strip()

    if not reply:
        clean = re.sub(r"<[^>]+>.*?(?:</[^>]+>|$)", "", raw, flags=re.DOTALL).strip()
        if clean:
            reply = clean

    return thought, action, reply


async def parse_output(ctx: ChatContext) -> ChatContext:
    raw = ctx.raw_output
    if not raw:
        return ctx
    from core.dialogue_attribution import parse_reply_envelope

    envelope, error = parse_reply_envelope(raw)
    if envelope is None:
        # 解析失败不把块外 raw 当台词；只允许一个受限服务器澄清退路。
        ctx.typed_reply = {}
        ctx.typed_reply_error = error or "invalid_reply_envelope"
        ctx.thought = ""
        ctx.action = "NONE"
        ctx.reply = "我没看明白这条结构化回复，能换个说法再问一次吗？"
        ctx.reply_segments = [ctx.reply]
        ctx.reply_disposition = "fallback"
        ctx.delivery_source_kind = "trusted-server-fallback"
        return ctx
    ctx.typed_reply = envelope.to_projection()
    ctx.typed_reply_error = ""
    ctx.thought = envelope.thought or "（无思考过程）"
    ctx.action = envelope.action
    ctx.reply = envelope.current
    ctx.reply_segments = []
    if envelope.kind == "skip":
        ctx.reply_disposition = "suppressed"
        ctx.reply = ""
    return ctx


async def bad_phrase_filter(ctx: ChatContext) -> ChatContext:
    if any(p in ctx.reply for p in BAD_PHRASES):
        ctx.reply = FALLBACK_REPLY
        ctx.thought = "破防兜底"
        ctx.reply_segments = [FALLBACK_REPLY]
        ctx.reply_disposition = "fallback"
        ctx.delivery_source_kind = "trusted-server-fallback"
        ctx.guard_decision = {
            "decision": "fallback",
            "reason": "bad_phrase_filter",
            "semantic_status": "deterministic_fallback",
            "verified": False,
        }
    return ctx


async def split_lines(ctx: ChatContext) -> ChatContext:
    # 拒绝/静默不能被默认占位符复活。
    if getattr(ctx, "reply_disposition", "") in {"suppressed", "silent", "skip"}:
        ctx.lines = []
        ctx.reply_segments = []
        return ctx
    segments = list(getattr(ctx, "reply_segments", ()) or ())
    if segments:
        lines = [str(segment).replace("\\n", "\n").strip() for segment in segments]
        lines = [line for line in lines if line]
    else:
        reply = str(getattr(ctx, "reply", "") or "").replace("\\n", "\n").strip()
        lines = [line.strip() for line in reply.split("\n") if line.strip()]
    if len(lines) > MAX_REPLY_LINES:
        ctx.reply = ""
        ctx.lines = []
        ctx.reply_segments = []
        ctx.reply_disposition = "suppressed"
        ctx.guard_decision = {
            **(getattr(ctx, "guard_decision", None) or {}),
            "decision": "reject",
            "reason": "too_many_atomic_segments",
            "semantic_status": "format_rejected",
            "verified": False,
        }
        return ctx
    if not lines and getattr(ctx, "delivery_source_kind", "") == "trusted-server-fallback":
        lines = [FALLBACK_REPLY]
        ctx.reply = FALLBACK_REPLY
        ctx.reply_disposition = "fallback"
        ctx.reply_segments = [FALLBACK_REPLY]
    elif not lines:
        # 未知来源的空输出不能变成可发送占位文案。
        ctx.lines = []
        ctx.reply_disposition = "suppressed"
        return ctx
    ctx.lines = lines
    return ctx


def _route_log_line(ctx: ChatContext) -> str:
    """渲染 Router 判定与 Comes 结果。

    没有路由信息时返回空串——旧路径（能力层未启用/未跑到）的日志格式保持原样。

    这一行是排查「为什么这次没调工具」的唯一手段：判定级别、命中的能力与分数、
    降级原因，线上只能靠它复盘。缺了就只能靠猜。
    """
    route = getattr(ctx, "route", None)
    if route is None:
        return ""
    try:
        snap = route.to_dict()
    except Exception:
        return ""

    labels = "+".join(
        name for name in ("chat", "memory", "tool") if snap.get(name)
    )
    caps = ", ".join(snap.get("capabilities") or []) or "无"
    lines = [
        f"- **🧭 路由判定**: `{labels}` via `{snap.get('level')}`"
        f"（能力: {caps}，最高分 {snap.get('top_score')}，"
        f"{float(snap.get('elapsed') or 0.0) * 1000:.0f}ms）—— {snap.get('reason') or ''}",
    ]

    results = getattr(ctx, "task_results", None) or []
    if results:
        for r in results:
            meta = getattr(r, "metadata", None) or {}
            status = getattr(getattr(r, "status", None), "value", "?")
            summary = (getattr(r, "summary", "") or "").replace("\n", " ")
            detail = (
                f"{meta.get('capability', '?')} → `{status}`"
                f"（{meta.get('steps', 0)} 次工具调用"
                f"{'，直调' if meta.get('direct_call') else ''}"
                f"，{meta.get('elapsed', 0)}s）"
            )
            reason = meta.get("reason")
            if reason:
                detail += f" 原因: {reason}"
            lines.append(f"- **🔧 工具执行**: {detail}")
            if summary:
                lines.append(f"  > {summary}")
    return "\n".join(lines) + "\n"


async def log_thought(ctx: ChatContext) -> ChatContext:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reply_str = " <br> ".join(ctx.lines)
    thought_formatted = ctx.thought.replace("\n", "\n  > ")
    raw_output_formatted = ctx.raw_output.replace("\n", "\n  > ") if ctx.raw_output else ""
    trigger_str = {
        "reply": "@回复触发",
        "proactive": "主动发言",
    }.get(ctx.trigger, ctx.trigger)
    # intent 是纯诊断字段：主动 @ 时 trigger 仍为 reply（走用户级检索），
    # 但日志必须与「用户 @ 我」区分开，否则排查时混为一谈
    if ctx.intent == "proactive_at":
        trigger_str = "主动@触发"
    llm_info = f"{ctx.llm_backend or '未知'} / {ctx.llm_model or '未指定'}"
    log_entry = f"""### 🕒 [{now_str}] {trigger_str} | 群: `{ctx.group_id}` | 用户: `{ctx.user_id}`
- **🖥 模型**: `{llm_info}`（耗时 {ctx.llm_elapsed:.2f}s，系统提示词 {ctx.system_prompt_len} 字符）
- **📥 用户输入**: {ctx.message}
{_route_log_line(ctx)}- **📤 完整 Prompt（发给 LLM）**:
  > {ctx.prompt_log.replace(chr(10), chr(10) + "  > ") if ctx.prompt_log else "(空)"}
- **📥 原始 LLM 输出（完整）**:
  > {raw_output_formatted or "(空)"}
- **🧠 内部思考**:
  > {thought_formatted}
- **⚙️ 判定动作**: `{ctx.action}`
- **💬 最终台词**: {reply_str}

---
"""
    try:
        # LOG_DIR 可能还不存在（默认 logs/ 被 .gitignore，新克隆里没有这个目录），
        # 而日志写入失败不该影响回复，所以由写入方自己建目录而不是依赖启动期
        THOUGHT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not THOUGHT_LOG_PATH.exists():
            THOUGHT_LOG_PATH.write_text("# 🤖 思考过程与决策日志\n\n", encoding="utf-8")
        with THOUGHT_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logger.error(f"日志写入失败: {e}")
    return ctx



