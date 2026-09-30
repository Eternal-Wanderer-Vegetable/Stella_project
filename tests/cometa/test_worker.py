# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""worker 基线（方案 §8.1 test_worker）：端到端认领执行、双 worker 互斥、
受控关闭不丢任务事实。"""

from __future__ import annotations

import asyncio

import pytest
from conftest import make_origin, submit_task

from cometa.backends.fake import FakeBackend, fake_completed
from cometa.backends.registry import BackendRegistry
from cometa.store import StoreBusyError
from cometa.worker import CometaWorker


def _worker(store, config, backend: FakeBackend, **kwargs) -> CometaWorker:
    registry = BackendRegistry()
    registry.register_type("fake", lambda cfg: backend)
    return CometaWorker(
        instance_id="inst-test",
        config=config,
        store=store,
        registry=registry,
        **kwargs,
    )


class TestWorkerE2E:
    @pytest.mark.asyncio
    async def test_worker_processes_submitted_task(self, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_completed("worker 跑完了")
        worker = _worker(store, config, backend, worker_id="w1")
        task_id = submit_task(store, config)
        run = asyncio.create_task(worker.run_forever(stop_grace_seconds=5.0))
        try:
            state = None
            for _ in range(200):
                record = store.get_task(task_id)
                state = record.state
                if state.value in ("succeeded", "failed", "cancelled"):
                    break
                await asyncio.sleep(0.05)
            assert state.value == "succeeded"
            assert len(backend.turns_started) == 1
        finally:
            worker.request_stop()
            await asyncio.wait_for(run, timeout=15)
        # worker 租约已释放
        epoch = store.register_worker("inst-test", "w-next", "pid:x", lease_seconds=30)
        assert epoch >= 1

    @pytest.mark.asyncio
    async def test_worker_respects_max_concurrent(self, store, config):
        config.max_concurrent = 1
        backend = FakeBackend()
        backend.behavior.events = fake_completed("done")
        backend.behavior.event_delay_seconds = 0.05
        worker = _worker(store, config, backend, worker_id="w1")
        t1 = submit_task(store, config, key="k1")
        t2 = submit_task(
            store,
            config,
            key="k2",
            origin=make_origin(requester_id="888", source_request_id="r2"),
        )
        run = asyncio.create_task(worker.run_forever(stop_grace_seconds=5.0))
        try:
            done = 0
            for _ in range(400):
                done = sum(
                    1
                    for tid in (t1, t2)
                    if store.get_task(tid).state.value
                    in ("succeeded", "failed", "cancelled")
                )
                if done == 2:
                    break
                await asyncio.sleep(0.05)
            assert done == 2
        finally:
            worker.request_stop()
            await asyncio.wait_for(run, timeout=15)


class TestSingleOwner:
    @pytest.mark.asyncio
    async def test_second_worker_rejected(self, store, config):
        backend = FakeBackend()
        w1 = _worker(store, config, backend, worker_id="w1")
        run = asyncio.create_task(w1.run_forever(stop_grace_seconds=5.0))
        await asyncio.sleep(0.2)
        w2 = _worker(store, config, FakeBackend(), worker_id="w2")
        with pytest.raises(StoreBusyError):
            await w2.run_forever(stop_grace_seconds=1.0)
        w1.request_stop()
        await asyncio.wait_for(run, timeout=15)

    @pytest.mark.asyncio
    async def test_shutdown_cancels_inflight_and_frees_quota(self, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_completed("done")
        backend.behavior.event_delay_seconds = 30.0  # 拖住任务
        worker = _worker(store, config, backend, worker_id="w1")
        task_id = submit_task(store, config)
        run = asyncio.create_task(worker.run_forever(stop_grace_seconds=6.0))
        # 等任务开始
        for _ in range(100):
            if store.get_task(task_id).state.value in ("starting", "running"):
                break
            await asyncio.sleep(0.05)
        worker.request_stop()
        await asyncio.wait_for(run, timeout=30)
        # 受控关闭：任务被中断保存（cancelled）或仍在途交恢复矩阵——
        # 两种都是明确事实，不允许卡死在 running 且租约永远有效
        state = store.get_task(task_id).state
        assert state.value in ("cancelled", "cancelling", "running")
        # 关闭后 worker 租约已释放，新 worker 可立即接管
        epoch = store.register_worker("inst-test", "w2", "pid:2", lease_seconds=30)
        assert epoch >= 1
