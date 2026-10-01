# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""runtime 装配集成基线。

背景：CometaRuntime 是 slots dataclass，曾因 start() 给未声明字段赋值而在
真实装配路径上整体失败——单元测试的 SimpleNamespace 替身掩盖了它。本文件
用 build_runtime 的**真实产物**（真泵 + fake sender）验证 start/stop 全链路。
"""

from __future__ import annotations

import asyncio

import pytest

from cometa.runtime import build_runtime


class NullSender:
    def __init__(self):
        self.sent: list[tuple[dict, str]] = []

    async def send(self, target: dict, text: str, payload: dict | None = None) -> str | None:
        self.sent.append((dict(target), text))
        return "server_emitted"


class TestAssembly:
    @pytest.mark.asyncio
    async def test_start_and_stop_with_real_pump(self, cometa_config):
        """真实 build_runtime 产物可 start/stop；泵任务随 stop 结束。"""
        cometa_config.enabled = True
        runtime = build_runtime(
            cometa_config, sender=NullSender(), instance_id="inst-test",
            spawn_worker=False,
        )
        assert runtime.enabled
        await runtime.start(spawn_worker=False)
        try:
            # 泵任务在跑（run_forever 循环挂起在 stop.wait 上）
            assert runtime._pump_task is not None
            assert not runtime._pump_task.done()
        finally:
            await runtime.stop(grace_seconds=2.0)
        assert runtime._pump_task.done()

    @pytest.mark.asyncio
    async def test_pump_delivers_submitted_ack(self, cometa_config):
        """提交任务后，运行中的泵把 ack 投递出去（webchat → server_emitted）。"""
        from cometa.models import NotificationState
        from cometa.service import Actor
        from tests.cometa_helpers import make_origin, make_spec

        cometa_config.enabled = True
        sender = NullSender()
        runtime = build_runtime(
            cometa_config, sender=sender, instance_id="inst-test",
            spawn_worker=False,
        )
        _receipt = runtime.service.submit(
            make_spec(),
            actor=Actor(kind="webchat_admin", id="admin"),
            origin=make_origin(platform="webchat", conversation_id="webchat",
                               instance_id="inst-test"),
            idempotency_key="k-assembly",
        )
        await runtime.start(spawn_worker=False)
        try:
            for _ in range(50):
                ack = runtime.store.notification_of_dedupe(
                    _receipt.task_id, f"ack:{_receipt.task_id}"
                )
                if ack.state is not NotificationState.PENDING:
                    break
                await asyncio.sleep(0.05)
            # 泵 + sender 返回的 server_emitted 占位回执 → 记 SENT（SSE 路径
            # 才记 SERVER_EMITTED 状态；投递语义一致：服务端已可查询）
            assert ack.state is NotificationState.SENT
            assert ack.receipt == "server_emitted"
            assert sender.sent, "泵真实发送了 ack"
        finally:
            await runtime.stop(grace_seconds=2.0)


class TestShutdownInjection:
    @pytest.mark.asyncio
    async def test_stop_cancels_inflight_via_store(self, cometa_config):
        """§6.8 关闭协议：runtime.stop 经任务库注入在途取消（Windows terminate
        是硬杀，worker 的优雅代码没有机会跑——必须由 bot 侧注入）。"""
        from cometa.models import TaskState
        from cometa.service import Actor
        from tests.cometa_helpers import claim_task, make_origin, make_spec

        cometa_config.enabled = True
        runtime = build_runtime(
            cometa_config, sender=NullSender(), instance_id="inst-test",
            spawn_worker=False,
        )
        receipt = runtime.service.submit(
            make_spec(),
            actor=Actor(kind="webchat_admin", id="admin"),
            origin=make_origin(platform="webchat", instance_id="inst-test"),
            idempotency_key="k-shutdown",
        )
        task, attempt = claim_task(runtime.store)
        runtime.store.transition_task(
            task.task_id,
            attempt_id=attempt.attempt_id,
            owner="w-test",
            epoch=attempt.lease_epoch,
            from_states=(TaskState.STARTING,),
            to_state=TaskState.RUNNING,
        )
        # 伪 supervisor：worker_id 与在途 attempt 的租约归属一致
        runtime.supervisor = type("S", (), {"worker_id": "w-test", "_process": None,
                                            "is_running": lambda self: True,
                                            "stop": lambda self, grace_seconds=10: None})()
        await runtime.start(spawn_worker=False)
        await runtime.stop(grace_seconds=6.0)
        assert runtime.store.get_task(task.task_id).state is TaskState.CANCELLING
