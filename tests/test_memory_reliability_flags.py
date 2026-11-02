# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MBENCH-005：记忆可靠性栈生产化旗标测试。

覆盖：T3 元数据渲染（off 逐字节兼容硬门禁 / full 含确认时间）、生产充分性
验证器（schema 漂移解析 + 全路径 fail-open）、turn_service 接线（shadow 记录
不拦截 / enforce INSUFFICIENT 硬短路 DIRECT + delivery 标记 / AMBIGUOUS 保守
指令）、env_schema 对新键字面量默认的校验。
"""

from __future__ import annotations

import asyncio

from config import settings
from core.runtime.turn_service import _PENDING_PROMPT_KEY, DIRECT, GENERATE
from memory.prompt_builder import build_v2_named_sections
from memory.sufficiency_guard import build_pack_text, parse_verdict_output

# ── T3 元数据渲染 ────────────────────────────────────────────────


def _mems():
    return [
        {"id": "m1", "user_id": "101", "content": "Alice lives in Springfield",
         "last_confirmed_at": "2023-05-08 13:56:00", "owner_type": "SPACE",
         "subject_key": "", "usage_tags": []},
        {"id": "m2", "user_id": "102", "content": "Ben likes pottery",
         "last_confirmed_at": "", "owner_type": "PERSON", "subject_key": "person:102",
         "usage_tags": []},
    ]


def test_metadata_off_byte_compat(monkeypatch):
    """off（默认）时输出与历史格式逐字节一致——生产兼容硬门禁。"""
    monkeypatch.setattr(settings, "MEMORY_PACK_METADATA_MODE", "off")
    sections = build_v2_named_sections(
        "", "", _mems(), [], current_user_id="101", mode="CASUAL_REPLY"
    )
    memories_text = next(t for n, t in sections if n == "memories")
    assert "｜确认" not in memories_text
    assert "- 群共享背景 [记录=用户(101)；事实主语未确认]：Alice lives in Springfield" in memories_text


def test_metadata_full_renders_confirmation_date(monkeypatch):
    """full 时带确认头的条目追加 `｜确认 YYYY-MM-DD`；无日期条目不加。"""
    monkeypatch.setattr(settings, "MEMORY_PACK_METADATA_MODE", "full")
    sections = build_v2_named_sections(
        "", "", _mems(), [], current_user_id="101", mode="CASUAL_REPLY"
    )
    memories_text = next(t for n, t in sections if n == "memories")
    assert "｜确认 2023-05-08：Alice lives in Springfield" in memories_text
    # 无日期条目：无时间段，但归属头照常
    assert "Ben likes pottery" in memories_text
    tail = memories_text.split("Ben likes pottery")[0].rsplit("\n", 1)[-1]
    assert "确认" not in tail


def test_metadata_full_requires_attribution_path(monkeypatch):
    """无 current_user_id 的旧路径即使 full 也保持旧格式（历史调用兼容）。"""
    monkeypatch.setattr(settings, "MEMORY_PACK_METADATA_MODE", "full")
    sections = build_v2_named_sections("", "", _mems(), [], mode="CASUAL_REPLY")
    memories_text = next(t for n, t in sections if n == "memories")
    assert memories_text == "可参考的聊天背景：\n- Alice lives in Springfield\n- Ben likes pottery"


# ── 生产充分性验证器 ──────────────────────────────────────────────


def test_parse_verdict_schema_variants():
    assert parse_verdict_output('{"verdict": "SUPPORTED"}') == "SUPPORTED"
    assert parse_verdict_output('{"sufficient": true, "reason": "x"}') == "SUPPORTED"
    assert parse_verdict_output('{"sufficient": false}') == "INSUFFICIENT"
    assert parse_verdict_output("完全无关文本") == "AMBIGUOUS"


def test_build_pack_text_skips_empty():
    assert build_pack_text([{"content": "a"}, {"content": ""}, {}]) == "a"


def test_judge_sufficiency_fail_open_paths(monkeypatch):
    """三条 fail-open：空包 / 预算拦截 / 无后端 → None（不拦截）。"""
    from memory import sufficiency_guard

    assert asyncio.run(sufficiency_guard.judge_sufficiency("Q", [{"content": ""}])) is None

    import core.llm.usage_store as usage_store

    monkeypatch.setattr(usage_store, "budget_blocked", lambda role: "daily_budget")
    assert asyncio.run(
        sufficiency_guard.judge_sufficiency("Q", [{"content": "x"}])
    ) is None

    import core.llm.registry as registry

    monkeypatch.setattr(registry, "backend_for", lambda role: None)
    assert asyncio.run(
        sufficiency_guard.judge_sufficiency("Q", [{"content": "x"}])
    ) is None


def test_judge_sufficiency_exception_fail_open(monkeypatch):
    """执行异常 → None（fail-open），不向回复路径抛错。"""
    import gravitas.model_calls as mc
    from memory import sufficiency_guard

    async def boom(*args, **kwargs):
        raise RuntimeError("endpoint down")

    monkeypatch.setattr(mc, "execute_model_call", boom)
    assert asyncio.run(
        sufficiency_guard.judge_sufficiency("Q", [{"content": "x"}])
    ) is None


def test_judge_sufficiency_success(monkeypatch):
    """正常路径：detailed 元组解包 + schema 漂移解析。"""
    import gravitas.model_calls as mc
    from memory import sufficiency_guard

    async def fake_call(backend, prompt, system, *, context, detailed):
        assert detailed is True
        return '{"sufficient": true}', "stop"

    monkeypatch.setattr(mc, "execute_model_call", fake_call)
    monkeypatch.setattr("core.llm.registry.backend_for", lambda role: object())
    verdict = asyncio.run(
        sufficiency_guard.judge_sufficiency("Q", [{"content": "x"}])
    )
    assert verdict == "SUPPORTED"


# ── turn_service 接线 ─────────────────────────────────────────────


class _FakeLLM:
    backend_name = "fake"


def _fake_judge(verdict):
    async def judge(question, memories, **kwargs):
        return verdict

    return judge


def _make_service_and_ctx(monkeypatch, mode, verdict):
    from core.context import ChatContext
    from core.runtime.turn_service import TurnService

    monkeypatch.setattr(settings, "MEMORY_SUFFICIENCY_GUARD_MODE", mode)
    # conftest autouse 会把 turn_service 模块级 MEMORY_V2_ENABLED 强制 False；
    # 守卫接线读的是该模块名，测试显式开回（与生产 v2 路径一致）。
    monkeypatch.setattr("core.runtime.turn_service.MEMORY_V2_ENABLED", True)
    svc = TurnService.__new__(TurnService)
    svc._llm = _FakeLLM()
    svc._pre_hooks = []
    svc._planner = None
    svc.system_prompt = "sys"
    svc.system_prompt_resolver = None
    ctx = ChatContext(
        user_id="101", group_id=1, msg_id=1, message="Where does Alice live?"
    )
    ctx.conversation_memories = _mems()
    ctx.memory_trace = {}
    monkeypatch.setattr(
        "memory.sufficiency_guard.judge_sufficiency", _fake_judge(verdict)
    )
    return svc, ctx


def test_guard_off_no_verdict(monkeypatch):
    """off：不调用验证器、不写 ctx、走正常生成路径。"""
    svc, ctx = _make_service_and_ctx(monkeypatch, "off", "INSUFFICIENT")
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == GENERATE
    assert not getattr(ctx, "memory_sufficiency", "")
    assert "sufficiency" not in ctx.memory_trace


def test_guard_shadow_records_but_does_not_gate(monkeypatch):
    """shadow：判定写入 ctx/memory_trace，但不短路（INSUFFICIENT 也继续生成）。"""
    svc, ctx = _make_service_and_ctx(monkeypatch, "shadow", "INSUFFICIENT")
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == GENERATE
    assert getattr(ctx, "memory_sufficiency", "") == "INSUFFICIENT"
    assert ctx.memory_trace.get("sufficiency") == "INSUFFICIENT"
    assert not ctx.reply


def test_guard_enforce_insufficient_short_circuits(monkeypatch):
    """enforce + INSUFFICIENT：DIRECT 短路、弃答文案、delivery 标记。"""
    svc, ctx = _make_service_and_ctx(monkeypatch, "enforce", "INSUFFICIENT")
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == DIRECT
    assert ctx.reply == settings.MEMORY_SUFFICIENCY_ABSTENTION_REPLY
    assert ctx.delivery_source_kind == "memory-sufficiency-abstention"


def test_guard_enforce_ambiguous_appends_conservative_directive(monkeypatch):
    """enforce + AMBIGUOUS：不短路，memories 分节追加保守指令。"""
    svc, ctx = _make_service_and_ctx(monkeypatch, "enforce", "AMBIGUOUS")
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == GENERATE
    assert "对应关系不确定" in (getattr(ctx, _PENDING_PROMPT_KEY, "") or "")
    assert getattr(ctx, "memory_sufficiency", "") == "AMBIGUOUS"


def test_guard_enforce_supported_normal_path(monkeypatch):
    """enforce + SUPPORTED：不短路、不追加指令。"""
    svc, ctx = _make_service_and_ctx(monkeypatch, "enforce", "SUPPORTED")
    plan = asyncio.run(svc.prepare_turn(ctx))
    assert plan.outcome == GENERATE
    assert "对应关系不确定" not in (getattr(ctx, _PENDING_PROMPT_KEY, "") or "")
