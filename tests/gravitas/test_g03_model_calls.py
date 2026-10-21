# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
from __future__ import annotations

import asyncio

import pytest

import core.llm.registry as registry
import core.llm.scheduler as scheduler
from gravitas.clock import ManualControlClock
from gravitas.contracts import Deadline, WorkClass
from gravitas.model_calls import ModelCallContext, execute_model_call


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
