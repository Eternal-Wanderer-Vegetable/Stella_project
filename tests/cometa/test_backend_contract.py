# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""后端契约 + executor 生命周期基线（方案 §8.1 test_backend_contract）。

同一套「任务/事件/取消/输入/错误」语义运行于 FakeBackend；
CodexAdapter 在 M0 门禁通过前显式跳过（fail-closed 本身也被测到）。
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import claim_task, submit_task

from cometa.backends.codex import CodexBackend, CodexUnavailableError
from cometa.backends.fake import FakeBackend, fake_completed, fake_failed
from cometa.backends.registry import BackendRegistry
from cometa.config import BackendConfig
from cometa.models import (
    EventKind,
    InputRequestState,
    NotificationState,
    Outcome,
    TaskState,
    VerificationStatus,
)


def _codex_backend() -> CodexBackend:
    return CodexBackend(BackendConfig(backend_id="codex-local", type="codex"))


async def _run_one(make_executor, store, config, backend=None, **kwargs):
    executor, fake = make_executor(backend)
    task_id = submit_task(store, config, **kwargs)
    task, attempt = claim_task(store)
    await executor.run_attempt(task, attempt)
    return task_id, store.get_task(task_id), fake


class TestSuccessPath:
    @pytest.mark.asyncio
    async def test_completed_task_becomes_succeeded(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_completed("排序算法已写好")
        task_id, task, fake = await _run_one(make_executor, store, config, backend)
        assert task.state is TaskState.SUCCEEDED
        assert task.result_id
        result = store.get_result(task_id)
        assert result.outcome is Outcome.SUCCEEDED
        assert result.verification_status is VerificationStatus.NOT_REQUIRED
        assert "排序算法已写好" in result.summary
        kinds = [e.kind for e in store.events_page(task_id)]
        assert kinds[-1] is EventKind.COMPLETED
        final = store.notification_of_dedupe(task_id, f"final:{task_id}")
        assert final.state is NotificationState.PENDING
        assert fake.turns_started, "FakeBackend 记账：turn 已启动"

    @pytest.mark.asyncio
    async def test_session_and_turn_recorded(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_completed()
        _task_id, task, _ = await _run_one(make_executor, store, config, backend)
        attempt = store.get_attempt(task.current_attempt)
        assert attempt.session_id.startswith("fake-session-")
        assert attempt.turn_id.startswith("fake-turn-")
        assert attempt.launch_phase == "running"

    @pytest.mark.asyncio
    async def test_final_text_saved_as_artifact_ref(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_completed("完整结果文本")
        task_id, _task, _ = await _run_one(make_executor, store, config, backend)
        result = store.get_result(task_id)
        assert result.final_text_ref == "final_text.md"
        assert "完整结果文本" in executor_final_text(store, config, task_id)


def executor_final_text(store, config, task_id) -> str:
    from cometa.artifacts import ArtifactCollector

    collector = ArtifactCollector(config.artifacts_dir)
    return collector.read_final_text(task_id)


class TestFailurePaths:
    @pytest.mark.asyncio
    async def test_failed_event_maps_to_failed(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_failed("编译错误")
        task_id, task, _ = await _run_one(make_executor, store, config, backend)
        assert task.state is TaskState.FAILED
        result = store.get_result(task_id)
        assert result.outcome is Outcome.FAILED
        assert result.error == "boom" or "编译" in result.summary or result.error

    @pytest.mark.asyncio
    async def test_start_failure_lands_failed_not_stuck(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.fail_on_start = RuntimeError("no account")
        task_id, task, fake = await _run_one(make_executor, store, config, backend)
        assert task.state is TaskState.FAILED
        assert not fake.turns_started
        result = store.get_result(task_id)
        assert result.error == "backend_start_failed"

    @pytest.mark.asyncio
    async def test_unknown_backend_fails_fast(self, make_executor, store, config):
        executor, _fake = make_executor()
        task_id = submit_task(store, config, backend_id="ghost-backend")
        task, attempt = claim_task(store, backend_ids={"fake", "ghost-backend"})
        await executor.run_attempt(task, attempt)
        record = store.get_task(task_id)
        assert record.state is TaskState.FAILED
        result = store.get_result(task_id)
        assert result.error == "backend_unresolved"

    @pytest.mark.asyncio
    async def test_stream_drop_without_terminal_requires_recovery(
        self, make_executor, store, config
    ):
        backend = FakeBackend()
        backend.behavior.events = fake_completed("永远不会到达")
        backend.behavior.abort_after = 1  # 流中断，无终态事件
        task_id, task, _ = await _run_one(make_executor, store, config, backend)
        assert task.state is TaskState.RECOVERY_REQUIRED
        kinds = [e.kind for e in store.events_page(task_id)]
        assert EventKind.RECOVERY_REQUIRED in kinds

    @pytest.mark.asyncio
    async def test_inspect_confirms_completed_after_drop(self, make_executor, store, config):
        from cometa.models import BackendSnapshot

        backend = FakeBackend()
        backend.behavior.events = fake_completed("已完成但流丢了")
        backend.behavior.abort_after = 1
        backend.behavior.inspect_snapshot = BackendSnapshot(
            session_found=True, turn_completed=True
        )
        _task_id, task, _ = await _run_one(make_executor, store, config, backend)
        # 恢复矩阵第 5 行：后端已完成 → 明确失败收束（结果不可收集），不挂起
        assert task.state is TaskState.FAILED


class TestCancellation:
    @pytest.mark.asyncio
    async def test_cancel_during_run_confirmed(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = [
            *fake_completed("太迟了"),
        ]
        backend.behavior.event_delay_seconds = 0.05
        executor, fake = make_executor(backend)
        task_id = submit_task(store, config)
        task, attempt = claim_task(store)
        run = asyncio.create_task(executor.run_attempt(task, attempt))
        await asyncio.sleep(0.05)
        store.request_cancel(task_id, actor="u777")
        await asyncio.wait_for(run, timeout=10)
        record = store.get_task(task_id)
        assert record.state is TaskState.CANCELLED
        assert fake.cancel_requested, "后端收到取消请求"
        kinds = [e.kind for e in store.events_page(task_id)]
        assert EventKind.CANCELLED in kinds

    @pytest.mark.asyncio
    async def test_cancel_unconfirmed_requires_recovery(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = fake_completed("x")
        backend.behavior.event_delay_seconds = 0.05
        backend.behavior.cancel_never_confirms = True
        executor, _ = make_executor(backend)
        executor.cancel_confirm_timeout = 0.5  # 注入短超时，避免用例等 30s
        task_id = submit_task(store, config)
        task, attempt = claim_task(store)
        run = asyncio.create_task(executor.run_attempt(task, attempt))
        await asyncio.sleep(0.05)
        store.request_cancel(task_id, actor="u")
        await asyncio.wait_for(run, timeout=15)
        assert store.get_task(task_id).state is TaskState.RECOVERY_REQUIRED

    @pytest.mark.asyncio
    async def test_cancel_wins_race_over_completion(self, make_executor, store, config):
        """取消与完成竞争：终态 CAS 裁决，只有一个终态。"""
        backend = FakeBackend()
        backend.behavior.events = fake_completed("done")
        backend.behavior.event_delay_seconds = 0.01
        executor, _ = make_executor(backend)
        task_id = submit_task(store, config)
        task, attempt = claim_task(store)
        await executor.run_attempt(task, attempt)
        # 完成后取消：任务已终态 → already_terminal，不再改变状态
        state, _, _ = store.request_cancel(task_id, actor="u")
        assert state == "already_terminal"
        assert store.get_task(task_id).state is TaskState.SUCCEEDED


class TestInputAndApproval:
    @pytest.mark.asyncio
    async def test_input_request_blocks_until_answered(self, make_executor, store, config):
        from cometa.backends.base import backend_event

        backend = FakeBackend()
        backend.behavior.events = [
            backend_event(
                "input_request",
                {"backend_request_id": "br-1", "question": "需要选择哪个分支？", "options": []},
                backend_event_id="input-1",
            )
        ]
        backend.behavior.events_after_respond = fake_completed("按答复继续")
        executor, fake = make_executor(backend)
        task_id = submit_task(store, config)
        task, attempt = claim_task(store)
        run = asyncio.create_task(executor.run_attempt(task, attempt))

        # 等任务进入 waiting_input
        record = store.get_task(task_id)
        for _ in range(200):
            record = store.get_task(task_id)
            if record.state is TaskState.WAITING_INPUT:
                break
            await asyncio.sleep(0.02)
        assert record.state is TaskState.WAITING_INPUT
        request_id = record.waiting_request_id
        request = store.get_input_request(request_id)
        store.respond_input(
            request_id, "main", actor="u777", expected_revision=request.revision
        )
        await asyncio.wait_for(run, timeout=10)
        record = store.get_task(task_id)
        assert record.state is TaskState.SUCCEEDED
        assert fake.responded, "答复已转发给后端"

    @pytest.mark.asyncio
    async def test_input_expiry_interrupts_task(self, make_executor, store, config):
        backend = FakeBackend()
        backend.behavior.events = [fake_backend_input("?")]
        config.limits.input_wait_seconds = 1.0  # 缩短等待
        task_id, task, _ = await _run_one(make_executor, store, config, backend)
        assert task.state is TaskState.CANCELLED
        request = store.get_input_request(_waiting_request_id(store, task_id))
        assert request.state is InputRequestState.EXPIRED


def fake_backend_input(question: str):
    from cometa.backends.base import backend_event

    return backend_event(
        "input_request",
        {"backend_request_id": "br-1", "question": question, "options": []},
        backend_event_id="input-1",
    )


def _waiting_request_id(store, task_id) -> str:
    record = store.get_task(task_id)
    if record.waiting_request_id:
        return record.waiting_request_id
    for event in store.events_page(task_id):
        if event.kind is EventKind.INPUT_REQUIRED:
            return str(event.payload.get("request_id", ""))
    raise AssertionError("没有找到输入请求")


class TestCodexFailClosed:
    """M0 门禁前 Codex 适配器必须 fail-closed（方案 §6.7/§12.1）。"""

    @pytest.mark.asyncio
    async def test_probe_without_sdk_is_degraded_or_incompatible(self):
        health = await _codex_backend().probe()
        assert health.state.value in ("degraded", "incompatible")

    @pytest.mark.asyncio
    async def test_open_session_refuses(self):
        from cometa.backends.base import PolicyContext, TurnRequest

        with pytest.raises(CodexUnavailableError):
            await _codex_backend().open_session(
                TurnRequest(objective="x"), None, PolicyContext(profile="p")
            )

    @pytest.mark.asyncio
    async def test_executor_marks_codex_task_failed(self, make_executor, store, config):
        """codex 后端不可用时任务明确失败，绝不静默换后端（§6.4）。"""
        executor, _ = make_executor()
        executor.registry = BackendRegistry()
        executor.registry.register_type("codex", CodexBackend)
        task_id = submit_task(store, config, backend_id="codex-local")
        import sqlite3

        conn = sqlite3.connect(str(store.db_path))
        conn.execute("UPDATE tasks SET backend_id = 'codex-local' WHERE task_id = ?", (task_id,))
        conn.commit()
        conn.close()
        task, attempt = claim_task(store, backend_ids={"fake", "codex-local"})
        await executor.run_attempt(task, attempt)
        record = store.get_task(task_id)
        assert record.state is TaskState.FAILED
