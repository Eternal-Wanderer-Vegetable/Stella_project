# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M2 验收：三阶段服务可独立调用、决策有类型、投影契约成立。

行为保真由 tests/runtime/test_legacy_reference_traces.py 的冻结 oracle 负责；
本文件验证迁移计划 §6.2 的新边界：TurnPlan 决策语义、阶段拆分后的可组合性、
ChatContext JSON 投影（raw_event/bot 永不过桥）。
"""
from __future__ import annotations

import asyncio

import pytest

from core.context import ChatContext
from core.runtime.turn_service import (
    BUDGET_LIMITED,
    DIRECT,
    GENERATE,
    SILENT,
    TurnService,
)
from memory.post_processors import bad_phrase_filter, parse_output, split_lines


class ScriptedBackend:
    backend_name = "scripted"
    model = "scripted-model"

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _service(replies: list[str], **kwargs) -> tuple[TurnService, ScriptedBackend]:
    svc = TurnService(timeout=5.0, **kwargs)
    backend = ScriptedBackend(replies)
    svc.set_llm_backend(backend)
    # 标准后置钩子（与 ai_gateway 装配同序）：解析→过滤→分行
    svc.register_post_hook(parse_output, priority=100)
    svc.register_post_hook(bad_phrase_filter, priority=80)
    svc.register_post_hook(split_lines, priority=60)
    return svc, backend


def _ctx(message: str = "在吗", **kwargs) -> ChatContext:
    return ChatContext(user_id=1, group_id=1, msg_id=1, message=message, **kwargs)


def test_prepare_returns_typed_generate_and_stashes_prompt():
    svc, backend = _service(["<reply>好</reply>"])
    ctx = _ctx()
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == GENERATE
    # 最终 prompt 与预算估算同源（BC-6），暂存在 ctx 上供 generate 消费
    assert ctx._turn_pending_prompt == ctx.prompt_log
    out = asyncio.run(svc.generate_reply(ctx))
    assert out.raw_output == "<reply>好</reply>"
    assert backend.prompts == [ctx.prompt_log]


def test_prepare_direct_when_pre_hook_replies():
    svc, backend = _service([])

    async def hook(ctx):
        ctx.reply = "直接答复"
        return ctx

    svc.register_pre_hook(hook, priority=50)
    plan = asyncio.run(svc.prepare_turn(_ctx()))
    assert plan.outcome == DIRECT
    assert backend.prompts == []


def test_prepare_silent_on_planner_wait():
    svc, _ = _service([])

    class Planner:
        async def maybe_plan(self, ctx):
            ctx.planner_wait = True
            return ctx

    svc.set_planner(Planner())
    plan = asyncio.run(svc.prepare_turn(_ctx()))
    assert plan.outcome == SILENT


def test_budget_limited_skips_generation_but_finalizes_fallback():
    svc, backend = _service([])
    ctx = _ctx()
    ctx.llm_call_count = 2  # 达到 PLANNER_MAX_LLM_CALLS_PER_TURN
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == BUDGET_LIMITED
    out = asyncio.run(svc.run(ctx))
    # 与 legacy 一致：跳过生成仍产出兜底 lines（不与 silent 混淆）
    assert out.lines == ["......？"]
    assert out.llm_backend == "scripted"
    assert backend.prompts == []


def test_no_backend_runs_post_hooks_without_generation():
    svc = TurnService(timeout=5.0)  # 不装配 backend
    svc.register_post_hook(parse_output, priority=100)
    svc.register_post_hook(split_lines, priority=60)
    out = asyncio.run(svc.run(_ctx()))
    assert out.lines == ["......？"]


def test_stages_reject_out_of_order_generate_without_prepare():
    svc, _ = _service(["x"])
    with pytest.raises(AttributeError):
        asyncio.run(svc.generate_reply(_ctx()))


def test_projection_excludes_handles_and_roundtrips_json():
    import json

    ctx = _ctx()
    ctx.raw_event = object()
    ctx.bot = object()
    ctx.tool_summaries = ["东京 27℃"]
    ctx.trace_id = "trace-1"
    ctx.turn_id = "turn-1"
    proj = ctx.to_json_projection()
    # JSON 可序列化 + 白名单语义
    assert json.loads(json.dumps(proj, ensure_ascii=False)) == proj
    assert "raw_event" not in proj and "bot" not in proj
    assert "route" not in proj and "task_results" not in proj
    # v2：社交闭环身份（trace_id/turn_id）进投影（计划 §6.1）；
    # v3：会话身份字段（conversation_kind/key/bot_id/peer/storage）进投影；
    # v4：消息身份信封；v6：typed reply、DeliveryDraft/Plan 与 runtime fence。
    assert proj["projection_schema_version"] == 6
    assert "reply_to_msg_id" in proj and "logical_message_id" in proj
    assert "identity_capsule" in proj
    assert "delivery_draft" in proj and "delivery_plan" in proj
    assert "retained_evidence_ids" in proj and "generation_epoch" in proj
    assert proj["trace_id"] == "trace-1" and proj["turn_id"] == "turn-1"
    assert proj["message"] == "在吗"
    assert proj["tool_summaries"] == ["东京 27℃"]
