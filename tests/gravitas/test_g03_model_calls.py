# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio

import pytest

import core.llm.registry as registry
import core.llm.scheduler as scheduler
from core.llm.base import AdaptiveAttemptRequiredError
from gravitas.clock import ManualControlClock
from gravitas.config import ResourceGroupConfig
from gravitas.contracts import Deadline, WorkClass
from gravitas.model_calls import (
    ModelAttemptBudgetExceededError,
    ModelCallContext,
    ModelCallDeferred,
    attempt_coverage_snapshot,
    configure_resource_groups,
    execute_model_call,
    execute_model_operation,
    execute_model_stream,
    model_call_scope,
    observe_model_backend,
    resource_group_for,
)


@pytest.fixture(autouse=True)
def _clean_scheduler():
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(lambda _resource: 1)
    yield
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(registry.concurrency_of)


class _FakeBackend:
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.peak = 0

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.calls += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return f"{system_prompt}:{prompt}"

    async def generate_detailed(self, prompt: str, system_prompt: str = ""):
        return await self.generate(prompt, system_prompt), "stop"


def test_executor_uses_declared_shared_resource_and_one_attempt():
    backend = _FakeBackend()
    context = ModelCallContext("LOCAL", WorkClass.INTERACTIVE, tag="turn")

    async def main():
        return await asyncio.gather(
            *(
                execute_model_call(backend, str(index), context=context)
                for index in range(4)
            )
        )

    assert asyncio.run(main()) == [":0", ":1", ":2", ":3"]
    assert backend.calls == 4
    assert backend.peak == 1


def test_executor_supports_detailed_backend_contract():
    backend = _FakeBackend()
    result = asyncio.run(
        execute_model_call(
            backend,
            "prompt",
            "system",
            context=ModelCallContext("LOCAL", WorkClass.BACKGROUND),
            detailed=True,
        )
    )
    assert result == ("system:prompt", "stop")
    assert backend.calls == 1


def test_executor_defers_when_bounded_queue_is_full(monkeypatch):
    backend = _FakeBackend()
    monkeypatch.setattr(scheduler, "RESOURCE_QUEUE_CAP", 0)
    context = ModelCallContext("LOCAL", WorkClass.INTERACTIVE, tag="turn")

    with pytest.raises(ModelCallDeferred) as raised:
        asyncio.run(execute_model_call(backend, "prompt", context=context))

    assert raised.value.reason_code == "scheduler_queue_full"
    assert backend.calls == 0
    assert scheduler.snapshot()["LOCAL"]["waiting"] == 0


def test_configured_slots_share_the_bounded_resource_group(monkeypatch):
    monkeypatch.setattr(
        registry,
        "concurrency_of",
        lambda slot: {"CHAT": 3, "MEMORY": 2}.get(slot, 1),
    )
    configure_resource_groups(
        (ResourceGroupConfig("shared_gpu", ("CHAT", "MEMORY"), 4),)
    )
    try:
        assert resource_group_for("CHAT") == "shared_gpu"
        assert resource_group_for("MEMORY") == "shared_gpu"
        assert resource_group_for("VISION") == "VISION"

        async def main():
            async def worker(tag: str):
                async with scheduler.acquire("shared_gpu", tag=tag):
                    await asyncio.sleep(0.01)

            await asyncio.gather(worker("first"), worker("second"))

        asyncio.run(main())
        assert scheduler.snapshot()["shared_gpu"]["peak_holding"] == 2
    finally:
        configure_resource_groups(())


def test_executor_rejects_expired_and_foreign_clock_deadlines():
    backend = _FakeBackend()
    clock = ManualControlClock(5.0, clock_id="test-clock")
    expired = ModelCallContext(
        "LOCAL",
        WorkClass.INTERACTIVE,
        deadline=Deadline(5.0, "test-clock"),
        clock=clock,
    )
    with pytest.raises(TimeoutError, match="before queueing"):
        asyncio.run(execute_model_call(backend, "x", context=expired))

    foreign = ModelCallContext(
        "LOCAL",
        WorkClass.INTERACTIVE,
        deadline=Deadline(10.0, "different-clock"),
        clock=clock,
    )
    with pytest.raises(ValueError, match="different control clock"):
        asyncio.run(execute_model_call(backend, "x", context=foreign))
    assert backend.calls == 0


class _SingleAttemptBackend(_FakeBackend):
    def __init__(self, *, slot: str = "", fail: int = 0):
        super().__init__()
        self.slot = slot
        self.fail = fail

    async def generate_single_attempt(self, prompt: str, system_prompt: str = ""):
        self.calls += 1
        if self.fail:
            self.fail -= 1
            raise RuntimeError("temporary endpoint failure")
        return f"{system_prompt}:{prompt}", "stop"


def test_executor_bounds_real_attempts_to_three_and_marks_unmanaged_coverage():
    backend = _SingleAttemptBackend(fail=9)
    context = ModelCallContext("declared_resource", WorkClass.INTERACTIVE)
    with pytest.raises(RuntimeError, match="temporary endpoint failure"):
        asyncio.run(execute_model_call(backend, "prompt", context=context))
    assert backend.calls == 3

    unmanaged = _FakeBackend()
    asyncio.run(
        execute_model_call(
            unmanaged,
            "prompt",
            context=ModelCallContext("unmanaged_resource", WorkClass.BACKGROUND),
        )
    )
    assert "unmanaged_resource" in attempt_coverage_snapshot()["unknown_resources"]


def test_adaptive_compatibility_retry_consumes_a_fresh_attempt_ticket():
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AdaptiveAttemptRequiredError("drop_temperature", ValueError("HTTP 400"))
        return "ok"

    result = asyncio.run(
        execute_model_operation(
            operation,
            context=ModelCallContext("adaptive", WorkClass.INTERACTIVE),
        )
    )
    assert result == "ok"
    assert calls == 2
    assert scheduler.snapshot()["adaptive"]["acquired"] == 2


def test_business_call_scope_caps_several_domain_model_requests():
    backend = _FakeBackend()
    context = ModelCallContext("scope", WorkClass.BACKGROUND)

    async def main():
        async with model_call_scope(2):
            await execute_model_call(backend, "one", context=context)
            await execute_model_call(backend, "two", context=context)
            with pytest.raises(ModelAttemptBudgetExceededError):
                await execute_model_call(backend, "three", context=context)

    asyncio.run(main())
    assert backend.calls == 2


def test_role_fallback_releases_primary_ticket_before_queueing_fallback():
    observations = []

    class SlottedBackend(_SingleAttemptBackend):
        def __init__(self, slot: str, *, fail: int = 0, observe: bool = False):
            super().__init__(slot=slot, fail=fail)
            self.observe = observe

        async def generate_single_attempt(self, prompt: str, system_prompt: str = ""):
            if self.observe:
                snap = scheduler.snapshot()
                observations.append(
                    (snap.get("PRIMARY", {}).get("holding"), snap.get("FALLBACK", {}).get("holding"))
                )
            return await super().generate_single_attempt(prompt, system_prompt)

    primary = SlottedBackend("PRIMARY", fail=2)
    fallback = SlottedBackend("FALLBACK", observe=True)
    role = registry.RoleBackend("chat", primary, fallback, cooldown=0)
    async def main():
        async with scheduler.acquire("FALLBACK", tag="other-request"):
            task = asyncio.create_task(
                execute_model_call(
                    role,
                    "prompt",
                    context=ModelCallContext("PRIMARY", WorkClass.INTERACTIVE),
                )
            )
            for _ in range(100):
                await asyncio.sleep(0)
                primary_state = scheduler.snapshot().get("PRIMARY", {})
                fallback_state = scheduler.snapshot().get("FALLBACK", {})
                if fallback_state.get("waiting") == 1:
                    assert primary_state.get("holding") == 0
                    assert fallback_state.get("holding") == 1
                    break
            else:
                raise AssertionError("fallback attempt did not queue on its actual endpoint")
        return await task

    result = asyncio.run(main())
    assert result == ":prompt"
    assert observations == [(0, 1)]
    assert scheduler.snapshot()["PRIMARY"]["peak_holding"] == 1
    assert scheduler.snapshot()["FALLBACK"]["peak_holding"] == 1


def test_observed_role_backend_preserves_fallback_routing_and_records_reply():
    primary = _SingleAttemptBackend(slot="OBS_PRIMARY", fail=2)
    fallback = _SingleAttemptBackend(slot="OBS_FALLBACK")
    role = registry.RoleBackend("chat", primary, fallback, cooldown=0)
    observed = []
    backend = observe_model_backend(
        role, lambda prompt, reply, finish: observed.append((prompt, reply, finish))
    )

    result = asyncio.run(
        execute_model_call(
            backend,
            "prompt",
            context=ModelCallContext("OBS_PRIMARY", WorkClass.INTERACTIVE),
        )
    )

    assert result == ":prompt"
    assert primary.calls == 2
    assert fallback.calls == 1
    assert observed == [("prompt", ":prompt", "stop")]
    assert scheduler.snapshot()["OBS_PRIMARY"]["holding"] == 0
    assert scheduler.snapshot()["OBS_FALLBACK"]["holding"] == 0


def test_stream_holds_its_actual_resource_ticket_until_consumption_finishes():
    async def stream():
        assert scheduler.snapshot()["STREAM"]["holding"] == 1
        yield "first"
        assert scheduler.snapshot()["STREAM"]["holding"] == 1
        yield "last"

    async def collect():
        return [
            item
            async for item in execute_model_stream(
                stream,
                context=ModelCallContext("STREAM", WorkClass.INTERACTIVE),
            )
        ]

    assert asyncio.run(collect()) == ["first", "last"]
    assert scheduler.snapshot()["STREAM"]["holding"] == 0


def test_stream_fallback_only_replays_before_any_chunk_is_exposed():
    observations = []

    async def primary():
        raise RuntimeError("primary unavailable before first chunk")
        yield "unreachable"

    async def fallback():
        snapshot = scheduler.snapshot()
        observations.append(
            (snapshot.get("STREAM_PRIMARY", {}).get("holding"),
             snapshot.get("STREAM_FALLBACK", {}).get("holding"))
        )
        yield "fallback chunk"

    async def collect():
        return [
            item
            async for item in execute_model_stream(
                primary,
                context=ModelCallContext("STREAM_PRIMARY", WorkClass.INTERACTIVE),
                fallback_operation=fallback,
                fallback_context=ModelCallContext(
                    "STREAM_FALLBACK", WorkClass.INTERACTIVE
                ),
            )
        ]

    assert asyncio.run(collect()) == ["fallback chunk"]
    assert observations == [(0, 1)]

    fallback_calls = 0
    seen = []

    async def partial_primary():
        yield "partial"
        raise RuntimeError("stream failed after output")

    async def unused_fallback():
        nonlocal fallback_calls
        fallback_calls += 1
        yield "duplicate"

    async def collect_partial():
        async for item in execute_model_stream(
            partial_primary,
            context=ModelCallContext("STREAM_PRIMARY", WorkClass.INTERACTIVE),
            fallback_operation=unused_fallback,
            fallback_context=ModelCallContext(
                "STREAM_FALLBACK", WorkClass.INTERACTIVE
            ),
        ):
            seen.append(item)

    with pytest.raises(RuntimeError, match="after output"):
        asyncio.run(collect_partial())
    assert seen == ["partial"]
    assert fallback_calls == 0
