# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Codex 事件归一契约（M0 实录 fixture 重放 + 合成事件）。

fixture（tests/cometa/fixtures/codex_events.jsonl）是 2026-09-30 在
openai-codex 0.147.0 + codex-cli 0.147.0 上实录的**失败路径**（模型后端
不可达：request timed out 重连 5/5）——契约断言：事实被保留、重连进度
不被误报成功、最终落在 failed。completed 路径用 SDK 真实 payload 模型
合成（等待代理可用后以实录替换，测试即契约）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cometa.backends.base import backend_event
from cometa.backends.codex_events import normalize_jsonl, notification_to_event

FIXTURE = Path(__file__).parent / "fixtures" / "codex_events.jsonl"


class TestErrorPathFixture:
    """实录（0.159.2 + 代理）：账号模型需要更新版客户端 → 400 →
    turn/completed(status=failed) 终态。契约：错误事实保留、终态落 failed、
    **绝不伪装 completed**——SDK 把失败轮次也经 turn/completed 投递，
    归一器必须检查 status 而不是把 method 当成功。"""

    @pytest.fixture()
    def events(self):
        return normalize_jsonl(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_replays_to_failed_terminal(self, events):
        kinds = [e.kind for e in events]
        assert kinds[0] == "phase"  # turn/started
        assert "failed" in kinds, "失败轮次必须落 failed"
        assert "completed" not in kinds, "turn/completed + status=failed 不得映射成功"
        assert events[-1].kind == "failed", "终态在最后"

    def test_error_message_preserved(self, events):
        failed = next(e for e in events if e.kind == "failed")
        detail = str(failed.payload.get("error", ""))
        assert "requires a newer version" in detail

    def test_will_retry_error_maps_to_reconnect_phase(self):
        """will_retry=True 的 error → 重连进度（不是失败、不是成功）。"""
        from openai_codex.generated.v2_all import ErrorNotification
        from openai_codex.models import Notification

        notification = Notification(method="error", payload=ErrorNotification(
            thread_id="t1", turn_id="turn-1", will_retry=True,
            error={"message": "Reconnecting... 2/5",
                   "additional_details": "request timed out",
                   "codex_error_info": "other"},
        ))
        event = notification_to_event(notification)
        assert event.kind == "phase"
        assert event.payload.get("phase") == "backend_reconnecting"
        assert "Reconnecting" in str(event.payload.get("detail", ""))


class TestCompletedPathSynthetic:
    """completed 路径（用 SDK payload 模型合成；实录替换后测试自动增强）。"""

    def _make_notification(self, method, payload):
        from openai_codex.models import Notification

        return Notification(method=method, payload=payload)

    def test_completed_turn_yields_final_and_usage(self):
        from openai_codex.generated.v2_all import (
            AgentMessageThreadItem,
            Turn,
            TurnCompletedNotification,
            TurnStartedNotification,
            UserMessageThreadItem,
        )

        notifications = [
            self._make_notification("turn/started", TurnStartedNotification(
                thread_id="t1",
                turn=Turn(id="turn-1", status="inProgress", items=[]),
            )),
            self._make_notification("item/completed", __import__(
                "openai_codex.generated.v2_all", fromlist=["ItemCompletedNotification"]
            ).ItemCompletedNotification(
                thread_id="t1", turn_id="turn-1",
                item=UserMessageThreadItem(id="i0", type="userMessage", content=[]),
                completed_at_ms=1,
            )),
            self._make_notification("turn/usage", __import__(
                "openai_codex.generated.v2_all", fromlist=["ThreadTokenUsageUpdatedNotification"]
            ).ThreadTokenUsageUpdatedNotification(
                thread_id="t1", turn_id="turn-1",
                token_usage=__import__(
                    "openai_codex.generated.v2_all", fromlist=["ThreadTokenUsage"]
                ).ThreadTokenUsage(
                    last=__import__(
                        "openai_codex.generated.v2_all", fromlist=["TokenUsageBreakdown"]
                    ).TokenUsageBreakdown(
                        input_tokens=10, output_tokens=5, cached_input_tokens=0,
                        reasoning_output_tokens=0, total_tokens=15),
                    total=__import__(
                        "openai_codex.generated.v2_all", fromlist=["TokenUsageBreakdown"]
                    ).TokenUsageBreakdown(
                        input_tokens=10, output_tokens=5, cached_input_tokens=0,
                        reasoning_output_tokens=0, total_tokens=15),
                    model_context_window=None,
                ),
            )),
            self._make_notification("turn/completed", TurnCompletedNotification(
                thread_id="t1",
                turn=Turn(
                    id="turn-1", status="completed",
                    items=[AgentMessageThreadItem(id="i1", type="agentMessage",
                                                  text="1+1 等于 2。")],
                ),
            )),
        ]
        events = [notification_to_event(n) for n in notifications]
        kinds = [e.kind for e in events]
        assert "usage" in kinds, "token usage 事件被归一"
        assert kinds[-1] == "completed"
        usage = next(e.payload for e in events if e.kind == "usage")
        assert usage.get("tokens_in") == 10 and usage.get("tokens_out") == 5
        completed = events[-1]
        assert completed.payload.get("text") == "1+1 等于 2。"

    def test_agent_delta_is_message_delta(self):
        from openai_codex.generated.v2_all import AgentMessageDeltaNotification

        event = notification_to_event(self._make_delta(
            AgentMessageDeltaNotification(delta="1+1 等", item_id="i1",
                                          thread_id="t1", turn_id="turn-1")))
        assert event.kind == "message_delta"
        assert event.payload.get("delta") == "1+1 等"

    @staticmethod
    def _make_delta(payload):
        from openai_codex.models import Notification

        return Notification(method="item/agentMessage/delta", payload=payload)


class TestExecutorMapping:
    @pytest.mark.asyncio
    async def test_failed_notification_after_retries_lands_failed(
        self, make_executor, store, config
    ):
        """重连若干次后 will_retry=False 的 error → 任务明确失败。"""

        backend = FakeBackendForMapping()
        backend.behavior.events = [
            backend_event("phase", {"phase": "backend_reconnecting", "detail": "1/5"}),
            backend_event("failed", {"error": "request timed out"}),
        ]
        from tests.cometa_helpers import claim_task, submit_task

        executor, _ = make_executor(backend)
        task_id = submit_task(store, config)
        task, attempt = claim_task(store)
        await executor.run_attempt(task, attempt)
        record = store.get_task(task_id)
        assert record.state.value == "failed"
        result = store.get_result(task_id)
        assert result is not None and "timed out" in result.summary


class FakeBackendForMapping:
    """最小可编程后端（与 FakeBackend 相同的流语义，独立于 fake 模块避免循环）。"""

    def __init__(self):
        from cometa.backends.fake import FakeBehavior

        self.backend_id = "fake"
        self.behavior = FakeBehavior()

    async def describe(self):
        from cometa.models import BackendDescriptor, LifecycleCapabilities

        return BackendDescriptor(
            backend_id=self.backend_id, backend_type="fake",
            lifecycle=LifecycleCapabilities(supports_cancel=True),
        )

    async def probe(self):
        from cometa.models import BackendHealth, HealthState

        return BackendHealth(backend_id=self.backend_id, state=HealthState.READY)

    async def open_session(self, request, workspace, policy):
        from cometa.models import SessionHandle

        return SessionHandle(session_id="sess-map", backend_id=self.backend_id)

    async def start_turn(self, session, request, launch_token):
        from cometa.models import TurnHandle

        return TurnHandle(turn_id="turn-map", session_id=session.session_id)

    async def stream(self, handle):
        for event in list(self.behavior.events):
            yield event
            if event.kind in ("completed", "failed", "interrupted"):
                return

    async def inspect(self, handle):
        from cometa.models import BackendSnapshot

        return BackendSnapshot()

    async def respond(self, handle, backend_request_id, answer):
        from cometa.models import BackendControlResult

        return BackendControlResult(ok=True, confirmed=True)

    async def cancel(self, handle):
        from cometa.models import BackendControlResult

        return BackendControlResult(ok=True, confirmed=True)

    async def close(self, session):
        return None
