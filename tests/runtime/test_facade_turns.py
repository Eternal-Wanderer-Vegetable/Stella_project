# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""facade 轮次验收（计划修订 v2：进程内执行器）。

完整链路（prepare→provider→finalize）、provider 异常与超时的 legacy 兜底
（BC-5）、取消的有界失败、DIRECT/SILENT 零 provider。
"""
from __future__ import annotations

import asyncio

import pytest
import runtime_harness as harness

from core.runtime.facade import E_CANCELLED, RuntimeTurnError

KEY = "qq:bot1:group_protocol"


async def test_full_chain_single_turn(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        ctx = h.ctx("投影输入")
        out = await h.facade.submit_turn(KEY, h.pipeline, ctx)
        # provider 收到的最终 prompt 与预算估算同源（BC-6）
        assert h.provider_calls == [ctx.prompt_log]
        assert "<reply>桥回复</reply>" in out.raw_output
        assert out.lines == ["桥回复"]
        states = [r["state"] for r in h.store_lines() if r["turn_id"]]
        assert states[-1] == "completed"
    finally:
        await h.stop()


async def test_default_provider_uses_shared_chat_gate_across_conversations(
    tmp_path, monkeypatch
):
    """默认真实后端必须经过进程共享的 CHAT 资源门。"""
    import core.llm.scheduler as scheduler
    from core.llm.registry import ROLE_CHAT, gate_of

    scheduler.reset_state()
    monkeypatch.setattr(scheduler, "_concurrency_resolver", lambda _resource: 1)
    h = harness.RuntimeHarness(tmp_path)
    h.facade._provider = None  # 走生产默认 provider，而不是脚本注入 provider

    active = 0
    peak = 0
    release = asyncio.Event()

    async def generate(prompt: str, system_prompt: str = "") -> str:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await release.wait()
            return "<thought>ok</thought><action>NONE</action><reply>ok</reply>"
        finally:
            active -= 1

    h.backend.generate = generate
    resource = gate_of(ROLE_CHAT)
    submitted: list[asyncio.Task] = []
    try:
        await h.start()
        submitted.append(asyncio.create_task(
            h.facade.submit_turn("qq:bot:group:a", h.pipeline, h.ctx("A"))
        ))
        for _ in range(200):
            if active:
                break
            await asyncio.sleep(0.005)
        assert active == 1

        submitted.append(asyncio.create_task(
            h.facade.submit_turn("qq:bot:group:b", h.pipeline, h.ctx("B"))
        ))
        queued_or_overlapped = False
        for _ in range(200):
            state = scheduler.snapshot().get(resource, {})
            if peak > 1 or state.get("waiting", 0) > 0:
                queued_or_overlapped = True
                break
            await asyncio.sleep(0.005)

        assert queued_or_overlapped, "第二个会话既未进入后端，也未在共享资源门排队"
        assert peak == 1, "默认 provider 并发绕过共享 CHAT 资源上限"
        assert scheduler.snapshot()[resource]["limit"] == 1
    finally:
        release.set()
        if submitted:
            await asyncio.gather(*submitted, return_exceptions=True)
        await h.stop()
        scheduler.reset_state()


async def test_provider_error_falls_back_like_legacy(tmp_path):
    """provider 异常：与 legacy pipeline 内部 catch 一致（BC-5）——兜底而非上抛。"""

    async def boom(key: str, prompt: str) -> str:
        raise RuntimeError("后端爆炸")

    h = harness.RuntimeHarness(tmp_path)
    h.facade._provider = boom
    try:
        await h.start()
        out = await h.facade.submit_turn(KEY, h.pipeline, h.ctx())
        assert out.lines == ["......？"]
        assert [r for r in h.store_lines() if r["state"] == "provider_fallback"]
    finally:
        await h.stop()


async def test_scheduler_deferral_is_recorded_as_deferred_not_provider_failure(tmp_path):
    from gravitas.model_calls import ModelCallDeferred

    async def deferred(key: str, prompt: str) -> str:
        raise ModelCallDeferred("scheduler_queue_full")

    h = harness.RuntimeHarness(tmp_path)
    h.facade._provider = deferred
    try:
        await h.start()
        out = await h.facade.submit_turn(KEY, h.pipeline, h.ctx())
        assert out.lines == ["队列繁忙，我稍后再试。"]
        assert [r for r in h.store_lines() if r["state"] == "deferred_fallback"]
        assert not [r for r in h.store_lines() if r["state"] == "provider_fallback"]
    finally:
        await h.stop()


async def test_cancel_rejects_inflight_provider(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        h.hold_provider(KEY)
        submit_task = asyncio.create_task(
            h.facade.submit_turn(KEY, h.pipeline, h.ctx("慢慢想"))
        )
        await asyncio.sleep(0.3)  # provider 调用在途
        await h.facade.cancel_turn(KEY)
        with pytest.raises(RuntimeTurnError) as ei:
            await submit_task
        assert ei.value.code == E_CANCELLED
        assert h.provider_calls, "provider 已收到最终 prompt"
    finally:
        await h.stop()


async def test_deadline_produces_fallback_not_hang(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        h.hold_provider(KEY)
        out = await h.facade.submit_turn(KEY, h.pipeline, h.ctx(), deadline=0.3)
        # 有界失败：不悬挂；deadline 按 legacy 超时语义兜底（BC-5）
        assert out.lines == ["......？"]
    finally:
        await h.stop()


async def test_direct_and_silent_zero_provider(tmp_path):
    h = harness.RuntimeHarness(tmp_path)

    async def direct_hook(ctx):
        # 仅对天气查询直答；否则直回钩子会把 SILENT 场景也短路掉
        if ctx.message == "查天气":
            ctx.reply = "工具直答"
            ctx.lines = ["工具直答"]
        return ctx

    h.pipeline.register_pre_hook(direct_hook, priority=50)
    try:
        await h.start()
        out = await h.facade.submit_turn(KEY, h.pipeline, h.ctx("查天气"))
        assert out.reply == "工具直答"
        assert h.provider_calls == []

        class WaitPlanner:
            async def maybe_plan(self, ctx):
                ctx.planner_wait = True
                return ctx

        h.pipeline.set_planner(WaitPlanner())
        out2 = await h.facade.submit_turn(KEY, h.pipeline, h.ctx("高讨论度"))
        assert out2.lines == []
        assert h.provider_calls == []
    finally:
        await h.stop()


async def test_proactive_at_instruction_first_through_facade(tmp_path):
    """M6：主动 @ 的指令前置语义经 facade 保持（与冻结 oracle 同源）。"""
    from core.context import ChatContext

    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        ctx = ChatContext(
            user_id=2, group_id=1, msg_id=0,
            message="说出那句确认的话",
            trigger="reply", intent="proactive_at",
        )
        await h.facade.submit_turn("qq:1", h.pipeline, ctx)
        assert h.provider_calls[0].startswith("说出那句确认的话")
    finally:
        await h.stop()
