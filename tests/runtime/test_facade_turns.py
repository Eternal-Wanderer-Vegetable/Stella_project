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
