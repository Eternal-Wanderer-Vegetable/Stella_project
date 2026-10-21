# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Fair, bounded ticket queue guarantees for the shared LLM scheduler."""

from __future__ import annotations

import asyncio
import time

import pytest

import core.llm.registry as registry
import core.llm.scheduler as scheduler
from gravitas.contracts import WorkClass


@pytest.fixture(autouse=True)
def _clean_scheduler():
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(lambda _resource: 1)
    yield
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(registry.concurrency_of)


def test_interactive_background_ticket_order_is_weighted_four_to_one():
    order: list[str] = []

    async def main():
        holder = scheduler.acquire("LOCAL", tag="holder")
        await holder.__aenter__()

        async def worker(name: str, kind: WorkClass):
            async with scheduler.acquire("LOCAL", tag=name, work_class=kind):
                order.append(name)

        workers = [
            asyncio.create_task(worker(f"i{number}", WorkClass.INTERACTIVE))
            for number in range(1, 6)
        ] + [
            asyncio.create_task(worker(f"b{number}", WorkClass.BACKGROUND))
            for number in range(1, 3)
        ]
        for _ in range(10):
            await asyncio.sleep(0)
        assert scheduler.snapshot()["LOCAL"]["waiting"] == 7
        await holder.__aexit__(None, None, None)
        await asyncio.gather(*workers)

    asyncio.run(main())
    assert order == ["i1", "i2", "i3", "i4", "b1", "i5", "b2"]


def test_aged_background_ticket_is_admitted_before_new_interactive(monkeypatch):
    monkeypatch.setattr(scheduler, "BACKGROUND_AGING_SECONDS", 0.0)
    order: list[str] = []

    async def main():
        holder = scheduler.acquire("LOCAL", tag="holder")
        await holder.__aenter__()

        async def worker(name: str, kind: WorkClass):
            async with scheduler.acquire("LOCAL", tag=name, work_class=kind):
                order.append(name)

        interactive = asyncio.create_task(worker("interactive", WorkClass.INTERACTIVE))
        background = asyncio.create_task(worker("background", WorkClass.BACKGROUND))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await holder.__aexit__(None, None, None)
        await asyncio.gather(interactive, background)

    asyncio.run(main())
    assert order == ["background", "interactive"]


def test_queue_and_per_conversation_caps_reject_without_growing_waiters(monkeypatch):
    monkeypatch.setattr(scheduler, "RESOURCE_QUEUE_CAP", 1)

    async def main():
        holder = scheduler.acquire("LOCAL", tag="holder")
        await holder.__aenter__()

        async def queued():
            async with scheduler.acquire(
                "LOCAL",
                tag="conversation-a",
                work_class=WorkClass.INTERACTIVE,
                conversation_key="opaque-conversation-a",
            ):
                pass

        first = asyncio.create_task(queued())
        await asyncio.sleep(0)
        async def rejected():
            with pytest.raises(scheduler.QueueCapacityError):
                async with scheduler.acquire(
                    "LOCAL",
                    tag="conversation-b",
                    work_class=WorkClass.BACKGROUND,
                ):
                    pass

        await asyncio.create_task(rejected())
        stats = scheduler.snapshot()["LOCAL"]
        assert stats["waiting"] == 1
        assert stats["rejected_queue_full"] == 1
        await holder.__aexit__(None, None, None)
        await first

    asyncio.run(main())


def test_second_pending_interactive_for_same_conversation_is_rejected():
    async def main():
        holder = scheduler.acquire("LOCAL", tag="holder")
        await holder.__aenter__()
        queued = asyncio.create_task(
            _hold_or_finish(
                "LOCAL",
                "first",
                conversation_key="opaque-conversation-a",
            )
        )
        await asyncio.sleep(0)
        async def rejected():
            with pytest.raises(scheduler.QueueCapacityError):
                async with scheduler.acquire(
                    "LOCAL",
                    tag="second",
                    work_class=WorkClass.INTERACTIVE,
                    conversation_key="opaque-conversation-a",
                ):
                    pass

        await asyncio.create_task(rejected())
        assert scheduler.snapshot()["LOCAL"]["waiting"] == 1
        await holder.__aexit__(None, None, None)
        await queued

    asyncio.run(main())


def test_scheduler_resource_registry_has_a_fixed_bound(monkeypatch):
    monkeypatch.setattr(scheduler, "MAX_TRACKED_RESOURCES", 1)

    async def main():
        async with scheduler.acquire("LOCAL", tag="first"):
            pass
        with pytest.raises(scheduler.QueueCapacityError):
            async with scheduler.acquire("MEMORY", tag="second"):
                pass

    asyncio.run(main())


@pytest.mark.parametrize("nested_resource", ["LOCAL", "MEMORY"])
def test_nested_same_or_cross_resource_acquisition_is_refused(nested_resource):
    async def main():
        async with scheduler.acquire("LOCAL", tag="outer"):
            with pytest.raises(scheduler.NestedResourceAcquireError):
                async with scheduler.acquire(nested_resource, tag="nested"):
                    pass
        snapshot = scheduler.snapshot()
        assert snapshot["LOCAL"]["holding"] == 0
        if nested_resource == "MEMORY":
            assert "MEMORY" not in snapshot

    asyncio.run(main())


async def _hold_or_finish(
    resource: str, tag: str, *, conversation_key: str | None = None
) -> None:
    async with scheduler.acquire(
        resource,
        tag=tag,
        work_class=WorkClass.INTERACTIVE,
        conversation_key=conversation_key,
    ):
        pass


def test_expired_ticket_is_removed_before_holder_releases():
    async def main():
        holder = scheduler.acquire("LOCAL", tag="holder")
        await holder.__aenter__()
        waiter = asyncio.create_task(
            _deadline_waiter(time.monotonic() + 0.01)
        )
        await asyncio.sleep(0)
        with pytest.raises(asyncio.TimeoutError):
            await waiter
        stats = scheduler.snapshot()["LOCAL"]
        assert stats["waiting"] == 0
        assert stats["holding"] == 1
        await holder.__aexit__(None, None, None)

    asyncio.run(main())


async def _deadline_waiter(deadline: float) -> None:
    async with scheduler.acquire("LOCAL", tag="deadline", deadline=deadline):
        pass
