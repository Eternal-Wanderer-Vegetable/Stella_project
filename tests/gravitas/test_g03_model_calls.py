# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio

import pytest

import core.llm.registry as registry
import core.llm.scheduler as scheduler
from gravitas.clock import ManualControlClock
from gravitas.config import ResourceGroupConfig
from gravitas.contracts import Deadline, WorkClass
from gravitas.model_calls import (
    ModelCallContext,
    ModelCallDeferred,
    configure_resource_groups,
    execute_model_call,
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
