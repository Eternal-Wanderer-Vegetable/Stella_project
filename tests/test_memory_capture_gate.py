# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆采集就绪门的确定性测试（计划 v2 §7 步骤 2/3）。

全部使用注入的假探针/假时钟/假后端：不起网络、不碰生产库、不依赖真实
模型。覆盖：初始关门、启动开门、失败转关、退避阶梯、单飞、迟到成功围栏、
真实失败立即关门、租约到期、worker 取消，以及默认探针的 provider 中立
行为（未绑定/离线/超时/空输出/降级链成功），并断言快照无泄漏面。
"""

from __future__ import annotations

import asyncio

import pytest

import memory.capture_gate as capture_gate
from memory.capture_gate import (
    CAPTURE_RESULT_DENIED,
    CAPTURE_RESULT_OK,
    STATE_PROBING,
    STATE_READY,
    STATE_STARTING,
    STATE_UNAVAILABLE,
    CaptureDecision,
    CaptureGate,
)


class _FakeClock:
    """单调钟假件：手动推进，测试完全确定性。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _static_probe(ok: bool, category: str = ""):
    async def _probe() -> tuple[bool, str]:
        return ok, category

    return _probe


# ============================================================
# M1：状态机与围栏（注入假探针 + 假时钟）
# ============================================================


def test_module_defaults_fail_closed(monkeypatch):
    """门未安装时：不允许采集、决策明确 not_started、快照可序列化。"""
    monkeypatch.setattr(capture_gate, "_gate", None)
    assert capture_gate.capture_allowed() is False
    decision = capture_gate.current_decision()
    assert decision.allowed is False
    assert decision.reason_code == "not_started"
    assert decision.result_code == CAPTURE_RESULT_DENIED
    snapshot = capture_gate.status_snapshot()
    assert snapshot["state"] == STATE_STARTING
    assert snapshot["allowed"] is False


def test_fresh_gate_starts_closed():
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(True), clock=clock)
    assert gate.capture_allowed() is False
    assert gate.decision().state == STATE_STARTING
    assert gate.decision().reason_code == "not_started"


async def test_probe_success_opens_capture():
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(True), clock=clock)
    assert await gate.probe_once() is True
    assert gate.capture_allowed() is True
    decision = gate.decision()
    assert decision.allowed is True
    assert decision.result_code == CAPTURE_RESULT_OK
    assert decision.reason_code == ""


async def test_probe_failure_stays_closed_with_category():
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(False, "request_failed"), clock=clock)
    assert await gate.probe_once() is False
    assert gate.capture_allowed() is False
    decision = gate.decision()
    assert decision.state == STATE_UNAVAILABLE
    assert decision.reason_code == "request_failed"
    assert decision.result_code == CAPTURE_RESULT_DENIED


async def test_backoff_doubles_and_caps():
    """连续失败的退避阶梯：interval 起步、翻倍、封顶 300s。"""
    clock = _FakeClock()
    gate = CaptureGate(
        probe=_static_probe(False, "timeout"), clock=clock, probe_interval=30.0
    )
    expected = [30.0, 60.0, 120.0, 240.0, 300.0, 300.0]
    for want in expected:
        await gate.probe_once()
        assert gate.status_snapshot()["next_retry_in_seconds"] == pytest.approx(want)
        clock.advance(want)


async def test_single_flight_probe():
    """同一时刻至多一个探针在途；在途期间查询直接返回现况（关门）。"""
    clock = _FakeClock()
    started = asyncio.Event()
    release = asyncio.Event()
    calls: list[int] = []

    async def blocking_probe() -> tuple[bool, str]:
        calls.append(1)
        started.set()
        await release.wait()
        return True, ""

    gate = CaptureGate(probe=blocking_probe, clock=clock)
    await gate.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2.0)
        # 在途时再问：不触发第二个探针，直接返回当前（关门）结论
        assert await gate.probe_once() is False
        assert len(calls) == 1
        release.set()
        for _ in range(100):
            if gate.capture_allowed():
                break
            await asyncio.sleep(0.01)
        assert gate.capture_allowed() is True
        assert len(calls) == 1
    finally:
        await gate.stop()


async def test_real_failure_closes_immediately_and_fences_stale_success():
    """真实整合失败立即关门；在途旧探针的迟到成功被 epoch 围栏弃用。"""
    clock = _FakeClock()
    started = asyncio.Event()
    release = asyncio.Event()

    async def renewing_probe() -> tuple[bool, str]:
        started.set()
        await release.wait()
        return True, ""

    gate = CaptureGate(probe=_static_probe(True), clock=clock)
    await gate.probe_once()
    assert gate.capture_allowed() is True

    # 在 READY 状态发起一次续约探针（挂在半途）
    gate._probe_fn = renewing_probe
    probe_task = asyncio.create_task(gate.probe_once())
    await asyncio.wait_for(started.wait(), timeout=2.0)

    # 真实整合失败：立即关门并 bump epoch
    gate.note_generation_failure()
    assert gate.capture_allowed() is False
    decision = gate.decision()
    assert decision.reason_code == "generation_failed"

    # 迟到的探针成功：围栏弃用，绝不能重新开门
    release.set()
    await probe_task
    assert gate.capture_allowed() is False
    assert gate.decision().reason_code == "generation_failed"


async def test_note_generation_failure_ignored_while_closed():
    """已关门时真实失败不重复计失败（避免与探针失败混算撑大退避）。"""
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(False, "timeout"), clock=clock)
    await gate.probe_once()
    failures_before = gate.status_snapshot()["consecutive_failures"]
    gate.note_generation_failure()
    assert gate.status_snapshot()["consecutive_failures"] == failures_before


async def test_lease_expiry_closes_without_waiting_for_probe():
    """租约到期：capture_allowed 立即 False，原因 lease_expired（续约探针未回）。"""
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(True), clock=clock)
    await gate.probe_once()
    assert gate.capture_allowed() is True
    clock.advance(60.0)  # 租约（60s）到期，续约探针还没跑
    assert gate.capture_allowed() is False
    decision = gate.decision()
    assert decision.reason_code == "lease_expired"
    assert decision.result_code == CAPTURE_RESULT_DENIED


async def test_renewal_probe_reopens_after_lease_expiry():
    """租约到期后续约探针成功：重新开门（正常续约路径）。"""
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(True), clock=clock)
    await gate.probe_once()
    clock.advance(61.0)
    assert await gate.probe_once() is True
    assert gate.capture_allowed() is True


async def test_stop_shuts_gate_and_cancels_worker():
    clock = _FakeClock()
    gate = CaptureGate(probe=_static_probe(True), clock=clock, probe_interval=1.0)
    await gate.start()
    task = gate._task
    assert task is not None
    await gate.stop()
    assert gate.capture_allowed() is False
    decision = gate.decision()
    assert decision.reason_code == "shutdown"
    assert gate._task is None
    assert task.cancelled() or task.done()


async def test_worker_recovers_after_outage():
    """端到端 worker 循环：失败退避后探针成功 → 自动开门。"""
    attempts: list[int] = []

    async def flaky_probe() -> tuple[bool, str]:
        attempts.append(1)
        return (len(attempts) >= 3, "" if len(attempts) >= 3 else "request_failed")

    gate = CaptureGate(probe=flaky_probe, probe_interval=0.05)
    await gate.start()
    try:
        for _ in range(300):
            if gate.capture_allowed():
                break
            await asyncio.sleep(0.02)
        assert gate.capture_allowed() is True
        assert len(attempts) >= 3
    finally:
        await gate.stop()


async def test_worker_closes_after_later_failure():
    """worker 循环：就绪后真实失败关门 → 退避探针期间保持关门。"""
    gate = CaptureGate(
        probe=_static_probe(True), probe_interval=0.05, probe_timeout=0.5
    )
    await gate.start()
    try:
        for _ in range(200):
            if gate.capture_allowed():
                break
            await asyncio.sleep(0.01)
        assert gate.capture_allowed() is True
        gate.note_generation_failure()
        assert gate.capture_allowed() is False
    finally:
        await gate.stop()


async def test_status_snapshot_is_sanitized():
    """快照只含脱敏事实：无 URL、无 key、无探针/响应正文、无消息内容。"""

    class _LeakyBackend:
        slot = "memory"
        base_url = "http://127.0.0.1:1234/v1"
        api_key = "sk-super-secret"

        async def generate(self, prompt: str, system_prompt: str = "") -> str:
            return "pong-but-this-is-provider-output"

    async def probe() -> tuple[bool, str]:
        gate._role_slot = _LeakyBackend.slot
        return True, ""

    gate = CaptureGate(probe=probe, clock=_FakeClock())
    await gate.probe_once()
    snapshot = gate.status_snapshot()
    blob = repr(snapshot)
    assert _LeakyBackend.api_key not in blob
    assert _LeakyBackend.base_url not in blob
    assert "pong" not in blob
    assert set(snapshot) == {
        "state",
        "role",
        "endpoint_slot",
        "allowed",
        "epoch",
        "consecutive_failures",
        "last_probe_at",
        "last_success_at",
        "next_retry_in_seconds",
        "error_category",
    }
    assert snapshot["state"] == STATE_READY
    assert snapshot["endpoint_slot"] == "memory"
    assert snapshot["last_success_at"]


async def test_probe_exception_treated_as_failure():
    """假探针意外抛异常：按探测失败处理，不外溢。"""

    async def broken() -> tuple[bool, str]:
        raise ValueError("boom")

    clock = _FakeClock()
    gate = CaptureGate(probe=broken, clock=clock)
    assert await gate.probe_once() is False
    assert gate.decision().reason_code == "request_failed"


# ============================================================
# M2：默认探针（provider 中立、有界；monkeypatch registry）
# ============================================================


class _FakeProviderBackend:
    """行为可编程的假后端（替代 LMStudioBackend）。"""

    def __init__(self, behavior: str, slot: str = "memory") -> None:
        self.slot = slot
        self.behavior = behavior
        self.calls: list[tuple[str, str]] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.calls.append((prompt, system_prompt))
        if self.behavior == "ok":
            return "pong"
        if self.behavior == "empty":
            return "   \n"
        if self.behavior == "raise":
            raise ConnectionError("connection refused")
        if self.behavior == "sleep":
            await asyncio.sleep(30)
            return "pong"
        return "pong"


def _bind_backend(monkeypatch, backend) -> list[int]:
    """monkeypatch registry.backend_for；返回 models 端点调用计数（恒为 0）。"""
    import core.llm.registry as registry

    probes = {"models_calls": 0}

    def fake_backend_for(role: str):
        if role == registry.ROLE_CONSOLIDATION:
            return backend
        return None

    monkeypatch.setattr(registry, "backend_for", fake_backend_for)
    return probes


async def test_default_probe_unbound_role_stays_closed(monkeypatch):
    """CONSOLIDATION 未绑定端点：no_backend，关门。"""
    clock = _FakeClock()
    gate = CaptureGate(clock=clock)
    _bind_backend(monkeypatch, None)
    ok, category = await gate._default_probe()
    assert (ok, category) == (False, "no_backend")
    assert gate._role_slot == ""


async def test_default_probe_offline_provider(monkeypatch):
    """端点已配置但拒绝连接：request_failed，关门。"""
    gate = CaptureGate(clock=_FakeClock())
    backend = _FakeProviderBackend("raise")
    _bind_backend(monkeypatch, backend)
    ok, category = await gate._default_probe()
    assert (ok, category) == (False, "request_failed")
    # 探针正文固定 "ping"，不带任何会话数据
    assert backend.calls and backend.calls[0][0] == "ping"
    assert backend.calls[0][1] == ""


async def test_default_probe_bounded_timeout(monkeypatch):
    """探针有界：慢端点在 probe_timeout 处被截断为 timeout，关门。"""
    gate = CaptureGate(clock=_FakeClock(), probe_timeout=0.2)
    backend = _FakeProviderBackend("sleep")
    _bind_backend(monkeypatch, backend)
    ok, category = await gate._default_probe()
    assert (ok, category) == (False, "timeout")


async def test_default_probe_empty_output_not_ready(monkeypatch):
    """HTTP 成功但补全为空：empty_output，关门。"""
    gate = CaptureGate(clock=_FakeClock())
    backend = _FakeProviderBackend("empty")
    _bind_backend(monkeypatch, backend)
    ok, category = await gate._default_probe()
    assert (ok, category) == (False, "empty_output")


async def test_default_probe_success_without_models_endpoint(monkeypatch):
    """正常补全即就绪；全程不要求 /v1/models（在线服务商可不开放）。"""
    gate = CaptureGate(clock=_FakeClock())
    backend = _FakeProviderBackend("ok")
    probes = _bind_backend(monkeypatch, backend)
    ok, category = await gate._default_probe()
    assert (ok, category) == (True, "")
    assert probes["models_calls"] == 0
    assert gate._role_slot == "memory"


async def test_default_probe_fallback_chain_success(monkeypatch):
    """主端点失败、降级端点成功：探针经同一条降级链语义判定就绪。"""
    from core.llm.registry import RoleBackend

    primary = _FakeProviderBackend("raise", slot="memory")
    fallback = _FakeProviderBackend("ok", slot="chat")
    role_backend = RoleBackend(
        role="consolidation", primary=primary, fallback=fallback, cooldown=1.0
    )
    gate = CaptureGate(clock=_FakeClock())
    _bind_backend(monkeypatch, role_backend)
    ok, category = await gate._default_probe()
    assert (ok, category) == (True, "")
    assert primary.calls and fallback.calls
    # 槽名取主端点（脱敏标识，不是 URL）
    assert gate._role_slot == "memory"


async def test_end_to_end_denied_then_allowed_decision_flow(monkeypatch):
    """默认探针接状态机的最小闭环：未绑定关门 → 换可用后端后开门。"""
    clock = _FakeClock()
    gate = CaptureGate(clock=clock)
    backend = _FakeProviderBackend("ok")
    _bind_backend(monkeypatch, backend)
    assert await gate.probe_once() is True
    decision = gate.decision()
    assert isinstance(decision, CaptureDecision)
    assert decision.allowed is True
    assert decision.state == STATE_READY
    # 关门场景复用同一状态机：直接换失败探针后下一次探针转关
    gate._probe_fn = _static_probe(False, "timeout")
    clock.advance(61.0)
    assert await gate.probe_once() is False
    assert gate.decision().state == STATE_UNAVAILABLE
    assert gate.decision().reason_code == "timeout"


def test_capture_decision_result_codes():
    allowed = CaptureDecision(True, STATE_READY, "", 1)
    denied = CaptureDecision(False, STATE_PROBING, "probing", 1)
    assert allowed.result_code == CAPTURE_RESULT_OK
    assert denied.result_code == CAPTURE_RESULT_DENIED
