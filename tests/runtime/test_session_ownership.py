# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""所有权验收：同会话单 owner 串行、跨会话并发、reset fence 与 epoch、运行记录。"""
from __future__ import annotations

import asyncio

import pytest
import runtime_harness as harness

from core.runtime.facade import E_CANCELLED, RuntimeTurnError

KEY_A = "qq:bot1:group_a"
KEY_B = "qq:bot1:group_b"


async def test_same_key_turns_serialize_single_owner(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        results = await asyncio.gather(*[
            h.facade.submit_turn(KEY_A, h.pipeline, h.ctx(f"并发{i}")) for i in range(3)
        ])
        assert all(r.lines == ["桥回复"] for r in results)
        # 串行：provider 按提交序逐次调用（无交错）
        assert len(h.provider_calls) == 3
    finally:
        await h.stop()


async def test_different_keys_run_concurrently(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        h.hold_provider(KEY_A)
        t1 = asyncio.create_task(h.facade.submit_turn(KEY_A, h.pipeline, h.ctx("A 的轮次")))
        await asyncio.sleep(0.2)  # A 在途挂起
        t2 = asyncio.create_task(h.facade.submit_turn(KEY_B, h.pipeline, h.ctx("B 的轮次")))
        out_b = await asyncio.wait_for(t2, timeout=10)
        # B 未被 A 阻塞：B 的投影不含 A 的内容
        assert out_b.lines == ["桥回复"]
        assert all("A 的轮次" not in p for p in h.provider_calls if "B 的轮次" in p)
        h.release_provider(KEY_A)
        await asyncio.wait_for(t1, timeout=10)
    finally:
        await h.stop()


async def test_reset_cancels_inflight_and_bumps_epoch(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        state = h.facade._key_state(KEY_A)
        state.owner_epoch = await h.facade._ensure_epoch(state)
        old_epoch = state.owner_epoch
        h.hold_provider(KEY_A)
        turn_task = asyncio.create_task(
            h.facade.submit_turn(KEY_A, h.pipeline, h.ctx("会被 reset 的轮次"))
        )
        await asyncio.sleep(0.2)
        await h.facade.reset_session(KEY_A)
        with pytest.raises(RuntimeTurnError) as ei:
            await asyncio.wait_for(turn_task, timeout=15)
        assert ei.value.code == E_CANCELLED
        assert state.owner_epoch == old_epoch + 1
        # reset 后新轮次正常（拿到 hold 期间预设的结果，证明回程完整）
        h.release_provider(KEY_A)
        out = await h.facade.submit_turn(KEY_A, h.pipeline, h.ctx("reset 之后"))
        assert out.lines == ["慢回复"]
        resets = [r for r in h.store_lines() if r["state"] == "reset"]
        assert resets and resets[-1]["owner_epoch"] == old_epoch + 1
    finally:
        await h.stop()


async def test_turn_records_written_to_independent_store(tmp_path):
    h = harness.RuntimeHarness(tmp_path)
    try:
        await h.start()
        await h.facade.submit_turn(KEY_A, h.pipeline, h.ctx())
        lines = h.store_lines()
        assert lines, "运行记录独立于记忆库（JSONL）"
        assert {"accepted", "prepared", "completed"} <= {r["state"] for r in lines}
        assert all(r["key"] == KEY_A for r in lines)
    finally:
        await h.stop()
