# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""FakeBackend：协议契约测试与故障注入的基线后端（方案 §7 M1、§8.1）。

定位：

- tests/cometa/test_backend_contract.py 用它跑通整套任务/事件/取消/输入/错误
  语义，不需要任何真实 Agent 与账号；
- 故障注入覆盖 M1 场景——「启动后崩溃」「终态提交前断电」「流中断」「审批
  挂起」「取消不确认」——恢复矩阵的每一行都由它驱动（§8.1 test_recovery）。

行为由 :class:`FakeBehavior` 描述：事件脚本 + 故障开关。所有调用都记账
（``sessions_opened`` / ``turns_started`` / ``cancel_requested``），供
「没有停止证据不得启动第二份执行」这类断言直接查证。
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from cometa.config import BackendConfig
from cometa.models import (
    BackendControlResult,
    BackendDescriptor,
    BackendEvent,
    BackendHealth,
    BackendSnapshot,
    HealthState,
    LifecycleCapabilities,
    SessionHandle,
    TurnHandle,
    new_id,
    utc_now,
)

from .base import (
    BACKEND_EVENT_KINDS,
    PolicyContext,
    TurnRequest,
    WorkspaceContext,
    backend_event,
)


@dataclass(slots=True)
class FakeBehavior:
    """FakeBackend 的行为脚本。"""

    # start_turn 后按序发出的事件（kind 必须是 BACKEND_EVENT_KINDS 之一）
    events: list[BackendEvent] = field(default_factory=list)
    # 每个事件之间的延迟（秒）；0 = 立即
    event_delay_seconds: float = 0.0
    # 发出 N 个事件后流中断（模拟崩溃/断流；不产生终态事件）
    abort_after: int | None = None
    # start_turn 直接抛错（启动失败）
    fail_on_start: Exception | None = None
    # open_session 直接抛错（后端不可用）
    fail_on_session: Exception | None = None
    # cancel 的返回（默认确认停止）
    cancel_result: BackendControlResult = field(
        default_factory=lambda: BackendControlResult(ok=True, confirmed=True)
    )
    # cancel 永不确认（超时 → recovery_required 路径）
    cancel_never_confirms: bool = False
    # respond 的返回
    respond_result: BackendControlResult = field(
        default_factory=lambda: BackendControlResult(ok=True, confirmed=True)
    )
    # inspect 报告的状态（恢复矩阵核对用）
    inspect_snapshot: BackendSnapshot = field(default_factory=BackendSnapshot)
    # probe 报告的健康状态
    health: BackendHealth | None = None
    # 收到 respond 后续发的事件（审批/输入通过后恢复执行）
    events_after_respond: list[BackendEvent] = field(default_factory=list)


class FakeBackend:
    """全协议可编程后端。describe/probe/open_session/start_turn/stream/
    inspect/respond/cancel/close 全部实现并记账。"""

    def __init__(self, config: BackendConfig | None = None):
        config = config or BackendConfig(backend_id="fake", type="fake")
        self.backend_id = config.backend_id
        self._config = config
        self.behavior = FakeBehavior()
        self._session_seq = itertools.count(1)
        self._turn_seq = itertools.count(1)
        # 记账：测试断言「第二份执行从未启动」直接读这些字段
        self.sessions_opened: list[str] = []
        self.turns_started: list[tuple[str, str]] = []  # (session_id, objective)
        self.cancel_requested: list[str] = []
        self.responded: list[tuple[str, str]] = []
        self.closed_sessions: list[str] = []
        self._pending_events: dict[str, list[BackendEvent]] = {}
        self._cancelled_turns: set[str] = set()
        self._apply_preset(getattr(config, "fake_behavior", ""))

    def _apply_preset(self, name: str) -> None:
        """TOML ``fake_behavior`` 预设（人工验收脚本；见 BackendConfig 字段说明）。"""
        if name == "complete":
            self.behavior.events = fake_completed(
                "演示任务已完成：FakeBackend 按 fake_behavior=complete 脚本产出最终答复。"
            )
        elif name == "fail":
            self.behavior.events = fake_failed("演示失败（fake_behavior=fail）")
        elif name == "input":
            self.behavior.events = [
                backend_event(
                    "input_request",
                    {
                        "backend_request_id": "demo-br-1",
                        "question": "演示：请补充任意一句话让任务继续。",
                        "options": [],
                    },
                    backend_event_id="demo-input-1",
                )
            ]
            self.behavior.events_after_respond = fake_completed(
                "已收到补充信息，演示任务完成。"
            )
        # "" / "hang"：空脚本 → 流挂起直到被取消（等待态/取消/超时场景用）

    # ── 描述与健康 ───────────────────────────────────────
    async def describe(self) -> BackendDescriptor:
        return BackendDescriptor(
            backend_id=self.backend_id,
            backend_type="fake",
            capabilities=["research.web", "code.read", "code.edit", "code.test"],
            lifecycle=LifecycleCapabilities(
                supports_inspect=True,
                supports_resume=False,  # 刻意不支持：契约测试要证明它不被伪装
                supports_event_replay=False,
                supports_cancel=True,
                supports_approval=True,
                supports_steer=True,
                supports_usage=True,
            ),
            version="fake-1.0.0",
            model=self._config.model,
        )

    async def probe(self) -> BackendHealth:
        if self.behavior.health is not None:
            return self.behavior.health
        return BackendHealth(
            backend_id=self.backend_id,
            state=HealthState.READY,
            version="fake-1.0.0",
            available_capabilities=["research.web", "code.read", "code.edit", "code.test"],
            missing_capabilities=[],
            reason="",
            checked_at=utc_now(),
        )

    # ── 会话与轮次 ───────────────────────────────────────
    async def open_session(
        self,
        request: TurnRequest,
        workspace: WorkspaceContext | None,
        policy: PolicyContext,
    ) -> SessionHandle:
        if self.behavior.fail_on_session is not None:
            raise self.behavior.fail_on_session
        session_id = f"fake-session-{next(self._session_seq)}"
        self.sessions_opened.append(session_id)
        return SessionHandle(session_id=session_id, backend_id=self.backend_id)

    async def start_turn(
        self, session: SessionHandle, request: TurnRequest, launch_token: str
    ) -> TurnHandle:
        if self.behavior.fail_on_start is not None:
            raise self.behavior.fail_on_start
        turn_id = f"fake-turn-{next(self._turn_seq)}"
        self.turns_started.append((session.session_id, request.objective))
        self._pending_events[turn_id] = list(self.behavior.events)
        return TurnHandle(turn_id=turn_id, session_id=session.session_id)

    async def stream(self, handle: TurnHandle) -> AsyncIterator[BackendEvent]:
        """持续流出事件直到终态/取消/注入中断——与真实后端一致：
        respond 追加的事件会随后到达，流不会在脚本耗尽时提前结束。"""
        emitted = 0
        queue = self._pending_events.setdefault(handle.turn_id, [])
        while True:
            if (
                self.behavior.abort_after is not None
                and emitted >= self.behavior.abort_after
            ):
                # 流中断：没有终态事件，executor 必须转 recovering
                return
            if queue:
                event = queue.pop(0)
                emitted += 1
                if self.behavior.event_delay_seconds:
                    await asyncio.sleep(self.behavior.event_delay_seconds)
                yield event
                if event.kind in ("completed", "failed", "interrupted"):
                    return
                continue
            if handle.turn_id in self._cancelled_turns:
                return
            await asyncio.sleep(0.01)  # 无事件：短轮询等待 respond 追加的事件

    async def inspect(self, handle: TurnHandle) -> BackendSnapshot:
        return self.behavior.inspect_snapshot

    async def respond(
        self, handle: TurnHandle, backend_request_id: str, answer: str
    ) -> BackendControlResult:
        self.responded.append((backend_request_id, answer))
        self._pending_events.setdefault(handle.turn_id, []).extend(
            self.behavior.events_after_respond
        )
        return self.behavior.respond_result

    async def cancel(self, handle: TurnHandle) -> BackendControlResult:
        self.cancel_requested.append(handle.turn_id)
        if self.behavior.cancel_never_confirms:
            return BackendControlResult(ok=False, confirmed=False, detail="unconfirmed")
        self._cancelled_turns.add(handle.turn_id)
        self._pending_events[handle.turn_id] = []  # 停止后续事件
        return self.behavior.cancel_result

    async def close(self, session: SessionHandle) -> None:
        self.closed_sessions.append(session.session_id)


def fake_completed(text: str = "任务完成", *, artifact: str | None = None) -> list[BackendEvent]:
    """常用脚本：一条命令记录 + 最终答复 + completed。"""
    events = [
        backend_event("phase", {"phase": "working", "detail": "分析目标"}),
        backend_event("command_record", {"command": "pytest -q", "summary": "3 passed"}),
        backend_event("message_final", {"text": text}),
        backend_event(
            "completed",
            {"outcome": "completed", "text": text, "artifact": artifact} if artifact else {"outcome": "completed", "text": text},
        ),
    ]
    for e in events:
        if e.backend_event_id is None:
            e.backend_event_id = new_id()
    return events


def fake_failed(error: str = "boom") -> list[BackendEvent]:
    return [
        backend_event("phase", {"phase": "working"}),
        backend_event("failed", {"error": error}, backend_event_id=new_id()),
    ]


__all__ = ["BACKEND_EVENT_KINDS", "FakeBackend", "FakeBehavior", "fake_completed", "fake_failed"]
