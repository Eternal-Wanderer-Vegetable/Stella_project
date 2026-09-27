# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M4 验收（native 模式）：WebChat ingress 经 facade 完整链路 + reset fence。

QQ 侧 handle_chat 走同一 facade 路径（ai_gateway 内分支，与 run_turn 共用
submit_turn）；完整 gateway 回放按计划归 M9 的确定性差异回放。
"""
from __future__ import annotations

import asyncio

import pytest
import runtime_harness as harness

import config
import webui.chat_ingress as ingress
from core.runtime import facade as facade_mod
from core.runtime.facade import E_CANCELLED, RuntimeTurnError


async def test_run_turn_native_mode_full_chain(tmp_path, monkeypatch):
    h = harness.RuntimeHarness(tmp_path)
    await h.start()
    monkeypatch.setattr(config, "RUNTIME_MODE", "native")
    monkeypatch.setattr(ingress, "_resolve_pipeline", lambda: h.pipeline)

    async def _started():
        return h.facade

    monkeypatch.setattr(facade_mod, "ensure_shared_facade_started", _started)
    try:
        result = await ingress.run_turn("面板里的提问", "admin")
        assert result["lines"] == ["桥回复"]
        assert result["thought"] == "RPC"
        # provider 收到的是 Python prepare 的最终投影 prompt
        assert len(h.provider_calls) == 1
    finally:
        await h.stop()


async def test_reset_fences_inflight_and_bumps_epoch(tmp_path, monkeypatch):
    h = harness.RuntimeHarness(tmp_path)
    await h.start()
    monkeypatch.setattr(config, "RUNTIME_MODE", "native")
    monkeypatch.setattr(ingress, "_resolve_pipeline", lambda: h.pipeline)

    async def _started():
        return h.facade

    monkeypatch.setattr(facade_mod, "ensure_shared_facade_started", _started)
    try:
        h.hold_provider(ingress.WEBCHAT_CONV_KEY)
        turn_task = asyncio.create_task(ingress.run_turn("会被 reset 的轮次", "admin"))
        await asyncio.sleep(0.3)
        await ingress.reset_webchat_runtime()
        with pytest.raises(RuntimeTurnError) as ei:  # E_CANCELLED：有界失败，不悬挂
            await asyncio.wait_for(turn_task, timeout=15)
        assert ei.value.code == E_CANCELLED
        h.release_provider(ingress.WEBCHAT_CONV_KEY)  # 放行旧 provider 的挂起
        # reset 后新轮次正常；hold 期间预设的结果对新轮次仍然生效
        result = await ingress.run_turn("reset 之后的新轮次", "admin")
        assert result["lines"] == ["慢回复"]
    finally:
        await h.stop()


async def test_legacy_mode_skips_runtime(monkeypatch):
    """默认 legacy：不触碰 facade（分支选择冒烟）。"""
    monkeypatch.setattr(config, "RUNTIME_MODE", "legacy")
    assert ingress._runtime_mode() == "legacy"
