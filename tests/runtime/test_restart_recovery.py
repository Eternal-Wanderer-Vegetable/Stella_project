# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M3 崩溃恢复验收：host 死亡 → 在途轮次有界失败、不自动重试、可重启。

计划 §6.4：崩溃后只自动恢复确定无副作用的工作；本层（桥）不重放任何轮次。
"""
from __future__ import annotations

import asyncio

import pytest
import rpc_harness as harness

from core.runtime.bridge import BridgeBrokenError
from core.runtime.contracts import ProtocolError

KEY = "qq:bot1:group_crash"


async def test_host_death_fails_pending_turn_without_retry(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        h.hold_provider(KEY)
        submit_task = asyncio.create_task(h.facade.submit_turn(KEY, h.pipeline, h.ctx("会崩溃的轮次")))
        await asyncio.sleep(0.8)  # provider 回程在途
        prompts_before = len(h.backend.prompts)
        assert h.bridge._process is not None
        h.bridge._process.kill()
        with pytest.raises((BridgeBrokenError, ProtocolError)):
            await asyncio.wait_for(submit_task, timeout=15)
        # 无自动重试：后端调用次数不再增长
        await asyncio.sleep(0.3)
        assert len(h.backend.prompts) == prompts_before
        failed = [r for r in h.store_lines() if r["state"] == "failed"]
        assert failed, "运行记录标记 failed（待判定，不自动重放）"
    finally:
        await h.stop()


async def test_bridge_restart_after_crash(tmp_path):
    h = harness.RpcHarness(tmp_path)
    try:
        await h.start()
        assert h.bridge._process is not None
        h.bridge._process.kill()
        await asyncio.sleep(0.3)
        await h.bridge.stop()
        # 重启新桥，同 key 数据仍在（独立 dataDir），链路可用
        h.bridge = harness.NodeBridge(
            host_config=harness._FIXTURE_CONFIG,
            data_root=h.tmp_path / "runtime-data",
            provider_handler=h._provider_respond,
        )
        h.facade = harness.RuntimeFacade(h.bridge, store=harness.RuntimeStore(h.store_path))
        await h.start()
        out = await h.facade.submit_turn(KEY, h.pipeline, h.ctx("重启后的轮次"))
        print("RAW:", repr(out.raw_output), "| provider_calls:", len(h.provider_calls))
        assert out.lines == ["桥回复"]
    finally:
        await h.stop()
