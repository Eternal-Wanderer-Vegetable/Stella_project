# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Codex 后端适配器（方案 §6.7）。

状态声明（诚实优先）：**M0 门禁未通过前，会话能力一律关闭**。

- 官方 Python SDK ``openai-codex`` 提供异步 App Server 接口，是首选路径；
  版本必须固定并经协议 fixture 验证（方案 §12.1 假设 1）。
- ``codex exec --json`` 是可选的独立非交互模式，与本文件的会话协议**不混用**。
- probe 分别检查：可执行文件存在、SDK 可导入、认证可用。任何一项失败只禁用
  对应能力（health=degraded/incompatible/auth_required），**绝不带病启动**——
  「能启动 Codex」不等于「实时联网搜索已可用」（§6.7）。
- ``launch_token`` 在 SDK 明确验证幂等启动前只作跟踪字段使用（§6.6）。

SDK 缺失时 open_session 抛 :class:`CodexUnavailableError`，executor 据此把
任务落为 failed（明确错误码），不会降级成「假装执行」。
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator

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
    utc_now,
)

from .base import PolicyContext, TurnRequest, WorkspaceContext

# 可选 SDK 的导入名。M0 冻结版本时一并确认（package: openai-codex）。
_SDK_IMPORT_NAMES = ("openai_codex", "codex_sdk")


class CodexUnavailableError(RuntimeError):
    """Codex 会话协议不可用（SDK 缺失/版本未验证/认证缺失）。"""


def _import_sdk():
    """尝试导入官方 SDK。返回模块或 None（缺失不是错误——probe 负责报告）。"""
    for name in _SDK_IMPORT_NAMES:
        try:
            return __import__(name)
        except ImportError:
            continue
    return None


class CodexBackend:
    """通过本地 App Server（stdio）驱动 Codex 的适配器骨架。

    会话方法在 SDK 不可用时全部 fail-closed。事件归一在
    :mod:`.codex_events`（以录制 fixture 为契约）。
    """

    def __init__(self, config: BackendConfig):
        self.backend_id = config.backend_id
        self._config = config

    # ── 描述与探测 ───────────────────────────────────────
    async def describe(self) -> BackendDescriptor:
        return BackendDescriptor(
            backend_id=self.backend_id,
            backend_type="codex",
            capabilities=list(self._config.capabilities),
            lifecycle=LifecycleCapabilities(
                supports_inspect=False,  # M0 验证前不声明
                supports_resume=False,
                supports_event_replay=False,
                supports_cancel=True,  # 中断轮次是协议基础能力
                supports_approval=True,  # 审批映射到 input_request 通道
                supports_steer=False,
                supports_usage=True,
            ),
            version="",  # probe 时填充
            model=self._config.model,
        )

    async def probe(self) -> BackendHealth:
        health = BackendHealth(
            backend_id=self.backend_id,
            state=HealthState.READY,
            checked_at=utc_now(),
        )
        executable = self._config.executable or "codex"
        exe_path = shutil.which(executable)
        if exe_path is None:
            health.state = HealthState.INCOMPATIBLE
            health.reason = f"未找到 Codex 可执行文件 {executable!r}"
            return health
        sdk = _import_sdk()
        if sdk is None:
            # 可执行文件在但 SDK 缺失：会话协议不可用，能力显式关闭
            health.state = HealthState.DEGRADED
            health.reason = (
                "openai-codex SDK 未安装（App Server 会话协议不可用）；"
                "先安装并完成 M0 协议验证"
            )
            return health
        # 认证探测留给 M0 探针（不在这里消耗用户额度）
        return health

    # ── 会话与轮次（M0 验证前 fail-closed） ───────────────
    async def open_session(
        self,
        request: TurnRequest,
        workspace: WorkspaceContext | None,
        policy: PolicyContext,
    ) -> SessionHandle:
        raise CodexUnavailableError(
            "Codex App Server 会话协议尚未通过 M0 验证（SDK 固定版本 + fixture）；"
            "在此之前 codex 后端拒绝启动（方案 §6.9 fail-closed）"
        )

    async def start_turn(
        self, session: SessionHandle, request: TurnRequest, launch_token: str
    ) -> TurnHandle:
        raise CodexUnavailableError("Codex 会话协议未启用（见 open_session）")

    def stream(self, handle: TurnHandle) -> AsyncIterator[BackendEvent]:
        raise CodexUnavailableError("Codex 会话协议未启用（见 open_session）")
        yield  # pragma: no cover - 使本函数成为生成器

    async def inspect(self, handle: TurnHandle) -> BackendSnapshot:
        raise CodexUnavailableError("Codex 会话协议未启用（见 open_session）")

    async def respond(
        self, handle: TurnHandle, backend_request_id: str, answer: str
    ) -> BackendControlResult:
        raise CodexUnavailableError("Codex 会话协议未启用（见 open_session）")

    async def cancel(self, handle: TurnHandle) -> BackendControlResult:
        raise CodexUnavailableError("Codex 会话协议未启用（见 open_session）")

    async def close(self, session: SessionHandle) -> None:
        return None


__all__ = ["CodexBackend", "CodexUnavailableError", "_import_sdk"]
