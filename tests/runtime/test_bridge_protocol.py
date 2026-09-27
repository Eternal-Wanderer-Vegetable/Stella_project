# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M3 协议验收：真实 Node host 子进程上的协议行为。

握手、完整链路一轮（prepare→fork→provider 回程→finalize）、超限帧有界失败、
provider 异常、取消与超时兜底。计划 §7 M3「验证」清单的协议子集。
"""
from __future__ import annotations

import asyncio

import pytest
import rpc_harness as harness

from core.runtime.contracts import (
    E_PROVIDER,
    ProtocolError,
    parse_frame,
    request,
)

KEY = "qq:bot1:group_protocol"


async def test_hello_handshake(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        info = await h.start()
        assert info["protocol_version"] == 1
        assert info["host_version"] == 1
        assert info["node"].startswith("v2")
    finally:
        await h.stop()


async def test_full_chain_single_turn(tmp_path):
    """完整新链路：prepare→Core fork→provider.respond 回程→finalize。"""
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        ctx = h.ctx("投影输入")
        out = await h.facade.submit_turn(KEY, h.pipeline, ctx)
        # provider 收到的最终 prompt 与预算估算同源（BC-6）
        assert h.provider_calls == [ctx.prompt_log]
        # Core fork 返回正文 → raw_output → finalize 解析分行
        assert "<reply>桥回复</reply>" in out.raw_output
        assert out.lines == ["桥回复"]
        states = [r["state"] for r in h.store_lines() if r["turn_id"]]
        assert states[-1] in ("prepared", "local")
    finally:
        await h.stop()


async def test_oversized_frame_fails_bounded_locally(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        big = request("runtime.drain", {"blob": "x" * (5 * 1024 * 1024)})
        with pytest.raises(ProtocolError) as ei:
            await h.bridge._write_frame(big)
        assert ei.value.code == "E_FRAME_TOO_LARGE"
        # 桥仍然可用
        await h.bridge.request("runtime.drain", {}, timeout=10.0)
    finally:
        await h.stop()


async def test_provider_error_fails_turn(tmp_path):
    async def boom(_params):
        raise RuntimeError("后端爆炸")

    h = harness.RpcHarness(tmp_path)
    h.bridge._provider_handler = boom
    try:
        await h.start()
        with pytest.raises(ProtocolError) as ei:
            await h.facade.submit_turn(KEY, h.pipeline, h.ctx())
        assert ei.value.code == E_PROVIDER
    finally:
        await h.stop()


async def test_cancel_rejects_inflight_provider(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        gate = h.hold_provider(KEY)
        submit_task = asyncio.create_task(
            h.facade.submit_turn(KEY, h.pipeline, h.ctx("慢慢想"))
        )
        await asyncio.sleep(0.8)  # 等 provider 回程挂起
        await h.facade.cancel_turn(KEY)
        with pytest.raises(ProtocolError) as ei:
            await submit_task
        assert ei.value.code == "E_CANCELLED"
        assert h.provider_calls, "provider 已把最终 prompt 送回 Python"
        assert h.provider_calls, "provider 已把最终 prompt 送回 Python"
        gate.set()
    finally:
        await h.stop()


async def test_deadline_produces_fallback_not_hang(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        h.hold_provider(KEY, result="<reply>迟到的回复</reply>")
        out = await h.facade.submit_turn(KEY, h.pipeline, h.ctx(), deadline=0.3)
        # 有界失败：不悬挂；deadline 按 legacy 超时语义兜底（BC-5）
        assert out.lines == ["......？"]
        h.release_provider(KEY)
    finally:
        await h.stop()


async def test_direct_and_silent_roundtrip_zero_provider(tmp_path):
    h = harness.RpcHarness(tmp_path)

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


async def test_parse_frame_rejects_garbage():
    for bad in ("not json", '{"v":999,"id":"x","kind":"request","method":"m"}', '{"id":"x","kind":"wat"}'):
        with pytest.raises(ProtocolError):
            parse_frame(bad)
