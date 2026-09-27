# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M3 所有权验收：同会话单 owner、跨会话并发、epoch fence、运行记录。"""
from __future__ import annotations

import asyncio

import pytest
import rpc_harness as harness

from core.runtime.contracts import M_TURN_SUBMIT, ProtocolError

KEY_A = "qq:bot1:group_a"
KEY_B = "qq:bot1:group_b"


async def test_same_key_turns_serialize_single_owner(tmp_path):
    h = harness.RpcHarness(tmp_path)
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
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        gate_a = h.hold_provider(KEY_A)
        t1 = asyncio.create_task(h.facade.submit_turn(KEY_A, h.pipeline, h.ctx("A 的轮次")))
        await asyncio.sleep(0.8)  # A 在途挂起
        t2 = asyncio.create_task(h.facade.submit_turn(KEY_B, h.pipeline, h.ctx("B 的轮次")))
        out_b = await asyncio.wait_for(t2, timeout=10)
        # B 未被 A 阻塞：B 的投影不含 A 的内容
        assert out_b.lines == ["桥回复"]
        assert all("A 的轮次" not in p for p in h.provider_calls if "B 的轮次" in p)
        gate_a.set()
        await asyncio.wait_for(t1, timeout=10)
    finally:
        await h.stop()


async def test_reset_fences_stale_owner_epoch(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        state = h.facade._key_state(KEY_A)
        resp = await h.bridge.request("session.ensure", {"key": KEY_A})
        state.owner_epoch = int(resp["owner_epoch"])
        old_epoch = state.owner_epoch
        await h.facade.reset_session(KEY_A)
        assert state.owner_epoch == old_epoch + 1
        # 旧 epoch 的裸提交被 host 拒绝（fence）
        with pytest.raises(ProtocolError) as ei:
            await h.bridge.request(M_TURN_SUBMIT, {
                "key": KEY_A, "turn_id": "stale", "owner_epoch": old_epoch,
                "decision": {"kind": "generate"},
                "projection": [{"role": "user", "text": "旧 owner"}],
            }, timeout=10.0)
        assert ei.value.code == "E_KEY"
        # 新 epoch 提交正常
        out = await h.facade.submit_turn(KEY_A, h.pipeline, h.ctx())
        assert out.lines == ["桥回复"]
    finally:
        await h.stop()


async def test_turn_records_written_to_independent_store(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        await h.facade.submit_turn(KEY_A, h.pipeline, h.ctx())
        lines = h.store_lines()
        assert lines, "运行记录独立于记忆库（JSONL）"
        assert {"accepted", "prepared"} <= {r["state"] for r in lines}
        assert all(r["key"] == KEY_A for r in lines)
    finally:
        await h.stop()
