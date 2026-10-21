"""Synthetic, isolated probes; no model, network, Bot or production database."""

import asyncio
import contextlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from loguru import logger

logger.remove()
from core.context import ChatContext
from core.llm import scheduler
from core.llm.base import LLMBackend
from core.runtime.facade import RuntimeFacade
from core.runtime.turn_service import TurnService


class Backend(LLMBackend):
    backend_name = "fixture"
    model = "fixture"

    def __init__(self):
        self.active = 0
        self.peak = 0
        self.release = asyncio.Event()

    async def generate(self, prompt, system_prompt=""):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await self.release.wait()
            return "<reply>fixture</reply>"
        finally:
            self.active -= 1


async def main():
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(lambda _: 1)
    backend = Backend()
    pipeline = TurnService(timeout=2)
    pipeline.set_llm_backend(backend)
    facade = RuntimeFacade(default_deadline=2)
    tasks = [
        asyncio.create_task(
            facade.submit_turn(
                "fixture:" + str(i),
                pipeline,
                ChatContext(
                    user_id="fixture",
                    group_id=i + 1,
                    msg_id=i + 1,
                    message="fixture",
                    group_shared_space="fixture",
                ),
            )
        )
        for i in range(2)
    ]
    for _ in range(40):
        await asyncio.sleep(0)
    observed = {
        "facade_default_provider": {
            "synthetic_turns": 2,
            "configured_scheduler_limit": 1,
            "backend_peak": backend.peak,
            "scheduler_snapshot": scheduler.snapshot(),
        }
    }
    assert backend.peak == 2 and scheduler.snapshot() == {}, (
        "baseline changed: re-evaluate plan"
    )
    backend.release.set()
    await asyncio.gather(*tasks)
    await facade.stop()
    scheduler.reset_state()
    async with scheduler.acquire("fixture", tag="holder"):

        async def queued():
            async with scheduler.acquire("fixture", tag="waiter"):
                pass

        waiter = asyncio.create_task(queued())
        await asyncio.sleep(0)
        before = scheduler.snapshot()["fixture"]["waiting"]
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
    after = scheduler.snapshot()["fixture"]
    observed["cancelled_waiter"] = {
        "waiting_before_cancel": before,
        "waiting_after_holder_release": after["waiting"],
        "holding": after["holding"],
    }
    assert before == 1 and after["waiting"] == 1 and after["holding"] == 0, (
        "baseline changed: re-evaluate plan"
    )
    scheduler.reset_state()
    print(json.dumps(observed, ensure_ascii=False, indent=2))


asyncio.run(main())
