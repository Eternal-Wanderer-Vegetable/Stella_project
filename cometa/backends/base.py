# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""AgentBackend 协议与能力声明（方案 §6.6）。

这些是 cometa 内部方法，**不是** Codex SDK 的逐字 API。后端的边界：

- 不调用 QQ/WebUI，不写任务数据库，不决定最终用户权限；
- 只通过 :class:`AgentBackend` 协议被 executor 驱动；
- 生命周期能力（inspect/resume/cancel/approval...）显式声明，不支持的
  能力返回明确 unsupported——**不能用一次新执行伪装 resume**（§6.6）。

``launch_token`` 是 cometa 的跟踪字段；只有后端明确验证支持幂等启动时，
才允许把它作为后端幂等键使用（§6.6）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from cometa.models import (
    BackendControlResult,
    BackendDescriptor,
    BackendEvent,
    BackendHealth,
    BackendSnapshot,
    SessionHandle,
    TurnHandle,
    utc_now,
)


@dataclass(slots=True)
class WorkspaceContext:
    """open_session 时交给后端的工作区上下文（§6.9）。

    ``path`` 是后端实际工作目录（worktree 或目录模式下的仓库本身）；
    ``base_commit`` 记录初始状态（worktree 模式）。
    """

    workspace_id: str
    path: str
    mode: str  # worktree | directory
    base_commit: str = ""
    allow_write: bool = False


@dataclass(slots=True)
class PolicyContext:
    """后端启动时的权限边界（§6.9）。后端不能落实 profile 时**拒绝启动**，
    不降级成无限权限。"""

    profile: str
    allow_network: bool = False
    allow_workspace_write: bool = False
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class TurnRequest:
    """一轮执行的内容请求。objective 是语义层目标（用户原话），不是工具指令。"""

    objective: str
    context_excerpt: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    deadline_at: datetime | None = None
    launch_token: str = ""


@runtime_checkable
class AgentBackend(Protocol):
    """编程 Agent 的适配协议（§6.6 的方法集，Python Protocol 形式）。"""

    async def describe(self) -> BackendDescriptor: ...

    async def probe(self) -> BackendHealth: ...

    async def open_session(
        self,
        request: TurnRequest,
        workspace: WorkspaceContext | None,
        policy: PolicyContext,
    ) -> SessionHandle: ...

    async def start_turn(
        self, session: SessionHandle, request: TurnRequest, launch_token: str
    ) -> TurnHandle: ...

    def stream(self, handle: TurnHandle) -> AsyncIterator[BackendEvent]: ...

    async def inspect(self, handle: TurnHandle) -> BackendSnapshot: ...

    async def respond(
        self, handle: TurnHandle, backend_request_id: str, answer: str
    ) -> BackendControlResult: ...

    async def cancel(self, handle: TurnHandle) -> BackendControlResult: ...

    async def close(self, session: SessionHandle) -> None: ...


def backend_event(
    kind: str,
    payload: dict | None = None,
    *,
    backend_event_id: str | None = None,
    occurred_at: datetime | None = None,
    raw_kind: str = "",
) -> BackendEvent:
    """后端适配器构造归一事件的便捷函数（occurred_at 缺省为当前 UTC）。"""
    return BackendEvent(
        kind=kind,
        payload=payload or {},
        backend_event_id=backend_event_id,
        occurred_at=occurred_at or utc_now(),
        raw_kind=raw_kind,
    )


# 归一事件 kind 的约定值（executor 按这些分派；适配器负责把原始协议映射过来）：
#   phase            阶段/活动变化（payload: {"phase": str, "detail": str})
#   message_delta    消息增量（payload: {"delta": str}；有界合并，不当最终答复）
#   message_final    最终答复文本（payload: {"text": str}）
#   command_record   命令/文件/搜索记录（payload: {"command"/"file"/"query", "summary"})
#   input_request    请求补充信息（payload: {"backend_request_id", "question", "schema"})
#   approval_request 请求审批（payload: {"backend_request_id", "question", "options", "risk"})
#   usage            用量（payload: {"tokens_in","tokens_out","cost"...}；拿不到是 unknown）
#   completed        轮次成功完成（"待结果校验"，executor 校验后落业务终态）
#   failed           轮次失败（payload: {"error": str}）
#   interrupted      轮次被中断（取消/外部信号；不能只看进程 exit code，§6.7）
BACKEND_EVENT_KINDS = (
    "phase",
    "message_delta",
    "message_final",
    "command_record",
    "input_request",
    "approval_request",
    "usage",
    "completed",
    "failed",
    "interrupted",
)

__all__ = [
    "AGENT_BACKEND_PROTOCOL_NOTE",
    "BACKEND_EVENT_KINDS",
    "AgentBackend",
    "PolicyContext",
    "TurnRequest",
    "WorkspaceContext",
    "backend_event",
]

AGENT_BACKEND_PROTOCOL_NOTE = "cometa internal protocol; not a verbatim SDK API"
