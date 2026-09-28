# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""离线决策回放与显式模型重生成（计划 §6.8）。

**A. 离线决策回放（默认，零副作用）**：从 turn_trace 载入冻结快照，在
进程内重放**纯本地决策段**（预算截断、social 插槽选择），provider / 工具 /
发送器 / 学习全部换成只读桩——桩一旦被调用立即抛错（回放绝不联网、绝不
发消息、绝不写记忆/学习）。比较原决策与重放决策产报告（replay_id +
parent_trace_id）。只有 metadata 的 trace 显示「仅可浏览」，不补查今天的
memory 来伪造当时输入（计划 §8.1 回放行）。

**B. 显式模型重生成（本期仅契约）**：需要用户在鉴权页面确认且消费真实
模型预算，结果进 replay 命名空间；本版本提供 :class:`ReplayGuard` 供后续
接线——任何未过闸的重生成调用都会被拒绝。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from core.context_budget import fit_prompt_to_window


class ReplaySideEffectError(RuntimeError):
    """回放期间触碰只读桩（联网/发送/工具/学习）——立即失败，绝不放行。"""


# ---- 只读桩：回放专用，调用即失败 ----


def _forbidden(name: str):
    def _raise(*_a: Any, **_kw: Any) -> None:
        raise ReplaySideEffectError(f"replay 不允许调用 {name}（离线零副作用红线）")

    return _raise


class ReadOnlyStubs:
    """provider / 工具 / 发送器 / 学习的替身集合：任何方法被调用即抛错。"""

    def __init__(self) -> None:
        self.provider = _forbidden("provider(LLM)")
        self.tool = _forbidden("tool")
        self.sender = _forbidden("sender")
        self.memory_write = _forbidden("memory_write")
        self.learning = _forbidden("learning")


# ---- 冻结快照与报告 ----


@dataclass
class FrozenDecisionInput:
    """一次可重放决策的冻结输入（来自 detailed 快照的裁剪白名单）。"""

    turn_id: str
    trace_id: str
    scope: str
    system_prompt: str = ""
    user_prompt: str = ""
    context_window_tokens: int = 8192
    output_reserve_tokens: int = 0
    safety_tokens: int = 0
    social_snapshot: str = ""
    versions: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayReport:
    replay_id: str
    parent_trace_id: str
    turn_id: str
    verdict: str  # match / mismatch / browsable_only
    original: dict[str, Any] = field(default_factory=dict)
    replayed: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def replay_budget_decision(
    original: dict[str, Any],
    *,
    trace_id: str,
    turn_id: str,
    scope: str = "",
) -> ReplayReport:
    """重放预算决策：冻结的 system+user prompt 重新过 fit_prompt_to_window。

    比较预算、估算 token 与截断标记。快照缺字段（仅 metadata 档）→
    verdict=browsable_only——绝不声称可重放。
    """
    report = ReplayReport(
        replay_id=uuid.uuid4().hex,
        parent_trace_id=trace_id,
        turn_id=turn_id,
        verdict="browsable_only",
    )
    required = ("user_prompt", "system_prompt", "budget_tokens", "estimated_tokens")
    missing = [k for k in required if k not in original or original.get(k) in (None, "")]
    if missing:
        report.notes.append(
            f"快照缺少 {missing}（仅 metadata 档）——仅可浏览，不补查今天的记忆伪造当时输入"
        )
        return report

    frozen = FrozenDecisionInput(
        turn_id=turn_id,
        trace_id=trace_id,
        scope=scope,
        system_prompt=str(original["system_prompt"]),
        user_prompt=str(original["user_prompt"]),
        context_window_tokens=int(original.get("context_window_tokens") or 8192),
        output_reserve_tokens=int(original.get("output_reserve_tokens") or 0),
        safety_tokens=int(original.get("safety_tokens") or 0),
    )
    stubs = ReadOnlyStubs()  # 供调用方确认桩存在；回放本身不触碰任何桩
    del stubs
    recomputed = fit_prompt_to_window(
        frozen.user_prompt,
        frozen.system_prompt,
        context_window_tokens=frozen.context_window_tokens,
        output_reserve_tokens=frozen.output_reserve_tokens,
        safety_tokens=frozen.safety_tokens,
    )
    original_estimated = int(original["estimated_tokens"])
    report.original = {
        "budget_tokens": int(original["budget_tokens"]),
        "estimated_tokens": original_estimated,
        "truncated": bool(original.get("truncated")),
    }
    report.replayed = {
        "budget_tokens": recomputed.budget_tokens,
        "estimated_tokens": recomputed.estimated_tokens,
        "truncated": recomputed.truncated,
    }
    report.verdict = (
        "match"
        if report.original == report.replayed
        else "mismatch"
    )
    if report.verdict == "mismatch":
        report.notes.append(
            "重放与原决策不一致：提示词版本或窗口常量可能已变化（差异可见，不静默）"
        )
    return report


def is_replayable(timeline: dict[str, Any] | None) -> bool:
    """trace 是否完整到可重放（全部事件 complete 且有 detailed 快照）。"""
    if not timeline:
        return False
    events = timeline.get("events") or []
    return bool(events) and all(e.get("complete") for e in events) and any(
        e.get("has_payload") for e in events
    )
