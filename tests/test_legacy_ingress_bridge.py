# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Focused checks for the shared QQ/WebChat compatibility boundaries."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.context import ChatContext
from core.transport.legacy_ingress import LegacyIngressBridge


class _Policy:
    def __init__(self, label):
        self.label = label
        self.calls = []

    def decide(self, event, **kwargs):
        self.calls.append((event, kwargs))
        return SimpleNamespace(allowed=True, reason_code=self.label)


def test_admission_switch_selects_shared_or_legacy_policy(monkeypatch):
    from config import settings

    shared, legacy = _Policy("shared"), _Policy("legacy")
    bridge = LegacyIngressBridge(shared)
    event = object()

    monkeypatch.setattr(settings, "STELLA_SHARED_INGRESS_ENABLED", True)
    assert bridge.decide(event, legacy_policy=legacy, purpose="plugin").reason_code == "shared"
    assert len(shared.calls) == 1 and legacy.calls == []

    monkeypatch.setattr(settings, "STELLA_SHARED_INGRESS_ENABLED", False)
    assert bridge.decide(event, legacy_policy=legacy, purpose="plugin").reason_code == "legacy"
    assert len(shared.calls) == 1 and len(legacy.calls) == 1


def test_capture_snapshot_and_writer_run_once_on_the_selected_path(monkeypatch):
    from config import settings

    class Gate:
        def __init__(self, allowed):
            self.allowed = allowed
            self.calls = 0

        def ingress_decision(self):
            self.calls += 1
            return SimpleNamespace(allowed=self.allowed, reason_code="fixture")

    async def exercise(enabled):
        monkeypatch.setattr(settings, "STELLA_SHARED_INGRESS_ENABLED", enabled)
        gate = Gate(True)
        bridge = LegacyIngressBridge(_Policy("unused"))
        ctx = ChatContext(user_id=1, group_id=2, msg_id=3, message="hello")
        writes = []

        async def writer(context, *, capture):
            writes.append((context, capture))
            return context

        decision = bridge.capture_decision(gate)
        assert bridge.capture_allowed(decision)
        saved = await bridge.record_message(writer, ctx, capture=decision)
        assert saved is ctx
        assert gate.calls == 1
        assert writes == [(ctx, decision)]

    asyncio.run(exercise(True))
    asyncio.run(exercise(False))


def test_shared_turn_uses_facade_once_and_rollback_uses_direct_callback(monkeypatch):
    from config import settings

    class Facade:
        def __init__(self):
            self.calls = []

        async def submit_turn(self, key, pipeline, context, **kwargs):
            self.calls.append((key, pipeline, context, kwargs))
            return context

    async def exercise(enabled):
        monkeypatch.setattr(settings, "STELLA_SHARED_INGRESS_ENABLED", enabled)
        bridge = LegacyIngressBridge(_Policy("unused"))
        facade = Facade()
        ctx, pipeline = ChatContext(user_id=3, group_id=4, msg_id=5, message="hello"), object()
        direct_calls = []

        async def direct():
            direct_calls.append("legacy")
            return ctx

        result = await bridge.submit_turn(
            "qq:3:private:4",
            pipeline,
            ctx,
            facade=facade,
            turn_deadline="deadline",
            legacy_submit=direct,
        )
        assert result is ctx
        if enabled:
            assert len(facade.calls) == 1
            assert facade.calls[0][3] == {"turn_deadline": "deadline"}
            assert direct_calls == []
        else:
            assert facade.calls == []
            assert direct_calls == ["legacy"]

    asyncio.run(exercise(True))
    asyncio.run(exercise(False))
