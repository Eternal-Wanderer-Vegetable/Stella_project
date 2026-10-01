# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Codex 后端适配器——官方 SDK `openai-codex` 驱动本地 App Server（方案 §6.7）。

**M0 状态（2026-10-01）**：已通过。版本矩阵 = openai-codex 0.159.2 + 自带
cli-bin 0.159.2（0.147.0 被账号后端拒绝——「模型需要更新版客户端」），
事件契约以实录像
tests/cometa/fixtures/codex_events.jsonl 为准。会话/轮次/流事件/中断/steer
均经真实 App Server 验证；``resume``/``event_replay`` 虽有 thread_resume API
但未经验证——**显式声明不支持**（§6.6：不能用一次新执行伪装 resume）。

映射（§6.7）：

- open_session  → ``thread_start``（sandbox/cwd/approval 按 profile 落实）；
- start_turn    → ``thread.turn(objective)``（用户原话语义目标）；
- stream        → ``turn.stream()`` 经 codex_events.notification_to_event 归一；
- cancel        → ``turn.interrupt()``（确认停止后 executor 才落终态）；
- respond       → ``turn.steer(answer)``（补充信息通道；审批由 SDK
  auto_review 裁决，cometa 级审批声明不支持）；
- close         → 结束 app-server 子进程（thread 持久化在 codexHome）。

认证（§6.7）：经 :mod:`cometa.backends.codex_auth` 管理托管 codex_home
（WebUI 配置，账号登录或自定义端点）。probe 检查托管认证状态，缺失 →
``auth_required``（不是 ready）；发现旧版 ``~/.codex`` 登录报 legacy 语义
（不可用，提示 WebUI 一键迁移）。沙盒映射：profile 的
allow_workspace_write/allow_network → read-only/workspace-write
（+network_access）——不能落实时拒绝而不是降级成无限权限。
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

from cometa.backends import codex_auth
from cometa.backends.base import PolicyContext, TurnRequest, WorkspaceContext
from cometa.backends.codex_events import notification_to_event
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

# 可选 SDK 的导入名。0.147.0 的包名是 openai_codex（openai-codex on PyPI）。
# 权威实现在 codex_auth._import_sdk；此处保留同名引用，测试 seam 指向本模块。
_import_sdk = codex_auth._import_sdk

# M0 冻结的版本组合（§6.7：版本矩阵；升级须先重跑 M0 探针）。
M0_SDK_VERSION = "0.159.2"


class CodexUnavailableError(RuntimeError):
    """Codex 会话协议不可用（SDK 缺失/版本未验证/认证缺失）。"""


def _sdk_version(sdk) -> str:
    # 0.159.2 起顶层不再暴露 SDK_VERSION：从包元数据读，拿不到就空（无害）
    try:
        from importlib.metadata import version

        return str(version("openai-codex"))
    except Exception:
        return ""


class CodexBackend:
    """通过本地 App Server（stdio）驱动 Codex 的适配器（M0 已验证）。

    SDK 对象（AsyncCodex/Thread/TurnHandle）挂在 backend 实例的注册表里，
    以 cometa 的 session_id/turn_id 为键；SessionHandle/TurnHandle 只携带
    ID 字符串（executor 可序列化地持有）。
    """

    def __init__(self, config: BackendConfig):
        self.backend_id = config.backend_id
        self._config = config
        self._sessions: dict[str, object] = {}   # session_id -> AsyncCodex
        self._threads: dict[str, object] = {}    # session_id -> AsyncThread
        self._turns: dict[str, object] = {}      # turn_id -> AsyncTurnHandle

    # ── 描述与探测 ───────────────────────────────────────
    async def describe(self) -> BackendDescriptor:
        sdk = _import_sdk()
        return BackendDescriptor(
            backend_id=self.backend_id,
            backend_type="codex",
            capabilities=list(self._config.capabilities),
            lifecycle=LifecycleCapabilities(
                supports_inspect=True,       # thread_read 可查会话
                supports_resume=False,       # thread_resume 存在但未验证：显式关闭
                supports_event_replay=False,
                supports_cancel=True,        # turn_interrupt
                supports_approval=False,     # SDK auto_review 裁决，无 cometa 级审批
                supports_steer=True,         # turn_steer
                supports_usage=True,         # turn 完成 payload 携带 token usage
            ),
            version=_sdk_version(sdk) if sdk else "",
            model=self._config.model,  # 空 = 后端账号配置默认模型
        )

    async def probe(self) -> BackendHealth:
        health = BackendHealth(
            backend_id=self.backend_id,
            state=HealthState.READY,
            available_capabilities=list(self._config.capabilities),
            checked_at=utc_now(),
        )
        executable = self._config.executable or ""
        if executable and shutil.which(executable) is None and not Path(executable).is_file():
            health.state = HealthState.INCOMPATIBLE
            health.reason = f"未找到 Codex 可执行文件 {executable!r}"
            return health
        sdk = _import_sdk()
        if sdk is None:
            health.state = HealthState.DEGRADED
            health.reason = (
                "openai-codex SDK 未安装（App Server 会话协议不可用）；"
                f"安装固定版本 openai-codex=={M0_SDK_VERSION}（须 -i https://pypi.org/simple）"
            )
            return health
        state = codex_auth.auth_state(self._config)
        if not state.ready:
            # legacy = 旧版 ~/.codex 有登录但托管后端用不到（CODEX_HOME 已指向
            # 托管 home）——如实 auth_required，附 WebUI 迁移指引，不装可用。
            health.state = HealthState.AUTH_REQUIRED
            health.reason = state.reason
            return health
        return health

    # ── 会话与轮次 ───────────────────────────────────────
    def _build_codex(self):
        sdk = _import_sdk()
        if sdk is None:
            raise CodexUnavailableError(
                "openai-codex SDK 未安装；先安装固定版本并完成 M0 验证"
            )
        codex_bin = self._config.executable or None
        if codex_bin and not Path(codex_bin).is_file() and shutil.which(codex_bin) is None:
            raise CodexUnavailableError(
                f"未找到 Codex 可执行文件 {codex_bin!r}（§6.9 fail-closed，不降级）"
            )
        # env 透传（toml [backends.<id>.env]）+ 托管 codex_home + 自定义端点
        # API key 都由 codex_auth 统一装配——worker 子进程只会继承 bot 的环境，
        # 缺了就到不了 app-server；probe 与这里必须同源（auth 状态一致性）。
        return sdk.AsyncCodex(sdk.CodexConfig(
            codex_bin=codex_bin or None,
            env=codex_auth.backend_spawn_env(self._config),
        ))

    def _sandbox_and_overrides(self, policy: PolicyContext):
        from openai_codex import (
            Sandbox,  # 延迟导入：SDK 缺失时 open_session 报错路径不变
        )

        sandbox = (
            Sandbox.workspace_write if policy.allow_workspace_write else Sandbox.read_only
        )
        overrides = None
        if policy.allow_network:
            # workspace-write 沙盒默认禁网；allow_network 需显式打开
            overrides = {"sandbox_workspace_write": {"network_access": True}}
        return sandbox, overrides

    async def open_session(
        self,
        request: TurnRequest,
        workspace: WorkspaceContext | None,
        policy: PolicyContext,
    ) -> SessionHandle:
        sdk = _import_sdk()
        if sdk is None:
            raise CodexUnavailableError(
                "openai-codex SDK 未安装；先安装固定版本并完成 M0 验证"
            )
        codex = self._build_codex()
        try:
            await codex._ensure_initialized()
        except Exception as e:
            raise CodexUnavailableError(
                f"App Server 启动/握手失败（§6.9 fail-closed）: {type(e).__name__}"
            ) from e

        sandbox, overrides = self._sandbox_and_overrides(policy)
        from openai_codex import ApprovalMode

        thread = await codex.thread_start(
            sandbox=sandbox,
            approval_mode=ApprovalMode.deny_all,  # cometa v1：无人工审批通道（SDK 自动裁决）
            cwd=str(workspace.path) if workspace is not None else None,
            config=overrides,
        )
        session_id = thread.id
        self._sessions[session_id] = codex
        self._threads[session_id] = thread
        return SessionHandle(session_id=session_id, backend_id=self.backend_id)

    async def start_turn(
        self, session: SessionHandle, request: TurnRequest, launch_token: str
    ) -> TurnHandle:
        thread = self._threads.get(session.session_id)
        if thread is None:
            raise CodexUnavailableError("会话不存在或已关闭")
        prompt = request.objective
        if request.acceptance_criteria:
            prompt += "\n\n验收标准：\n" + "\n".join(
                f"- {c}" for c in request.acceptance_criteria
            )
        handle = await thread.turn(prompt)
        self._turns[handle.id] = handle
        return TurnHandle(turn_id=handle.id, session_id=session.session_id)

    async def stream(self, handle: TurnHandle) -> AsyncIterator[BackendEvent]:
        turn = self._turns.get(handle.turn_id)
        if turn is None:
            raise CodexUnavailableError("轮次不存在或已关闭")
        async for notification in turn.stream():
            yield notification_to_event(notification)

    async def respond(
        self, handle: TurnHandle, backend_request_id: str, answer: str
    ) -> BackendControlResult:
        turn = self._turns.get(handle.turn_id)
        if turn is None:
            return BackendControlResult(ok=False, confirmed=False, detail="turn gone")
        try:
            await turn.steer(answer)
            return BackendControlResult(ok=True, confirmed=True)
        except Exception as e:  # 后端拒收由 executor 决定重开请求
            return BackendControlResult(ok=False, confirmed=False, detail=f"{type(e).__name__}")

    async def cancel(self, handle: TurnHandle) -> BackendControlResult:
        turn = self._turns.get(handle.turn_id)
        if turn is None:
            return BackendControlResult(ok=True, confirmed=True, detail="turn gone")
        try:
            await turn.interrupt()
            return BackendControlResult(ok=True, confirmed=True)
        except Exception as e:
            return BackendControlResult(ok=False, confirmed=False,
                                        detail=f"{type(e).__name__}")

    async def inspect(self, handle: TurnHandle) -> BackendSnapshot:
        """thread_read 核对轮次状态（M0：API 存在；恢复矩阵的核对证据）。"""
        thread = self._threads.get(handle.session_id)
        if thread is None:
            return BackendSnapshot(detail="session gone")
        try:
            read = await thread.read(include_turns=False)
        except Exception as e:
            return BackendSnapshot(detail=f"read failed: {type(e).__name__}")
        turns = getattr(read, "turns", None) or []
        target = next(
            (t for t in turns if getattr(t, "id", "") == handle.turn_id), None
        )
        if target is None:
            return BackendSnapshot(session_found=True, detail="turn not found")
        status = str(getattr(getattr(target, "status", ""), "value", target.status or ""))
        return BackendSnapshot(
            session_found=True,
            turn_running=status == "inProgress",
            turn_completed=status == "completed",
            turn_failed=status == "failed",
            detail=status,
        )

    async def close(self, session: SessionHandle) -> None:
        codex = self._sessions.pop(session.session_id, None)
        self._threads.pop(session.session_id, None)
        if codex is None:
            return
        # 子进程已死属正常（executor 侧任务结束）
        with contextlib.suppress(Exception):
            await codex.close()


__all__ = ["M0_SDK_VERSION", "CodexBackend", "CodexUnavailableError", "_import_sdk"]
