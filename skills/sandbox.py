# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""受控沙盒执行层：协议、策略校验与后端选择。

边界纪律（plan §6.4）：

* ``SandboxExecutor`` 是**唯一**的脚本/文件操作执行边界。orchestrator
  只请求抽象动作；任何后端都不得把动作翻译成宿主进程的
  ``subprocess``/``eval``/``exec``。
* 后端创建失败、Docker 不可用、平台不支持或策略拒绝 → 可诊断的
  ``sandbox_unavailable``，**绝不**回退到宿主任意执行（没有 local 后端，
  永远不会有）。
* ``DisabledSandboxExecutor`` 是默认后端：它对一切动作返回拒绝——
  「没有沙盒」不是错误状态，而是明确的关闭态。
* 平台差异由后端**能力探测**处理（Docker 在不在、daemon 通不通），
  不按 OS 名猜测隔离设施：Windows 不假设 bubblewrap，也不假设
  Docker Desktop 一定在（plan §9：Windows 隔离误判）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from skills.audit import audit
from skills.model import SandboxAction, SandboxActionOutcome, SandboxSpec

BACKEND_DISABLED = "disabled"
BACKEND_DOCKER = "docker"


@dataclass(frozen=True)
class SandboxAvailability:
    """后端能力探测结果（进状态 API 与审计，不进 prompt）。"""

    backend: str
    available: bool
    reason: str = ""


@runtime_checkable
class SandboxExecutor(Protocol):
    """沙盒执行协议。``execute`` 必须自身做策略校验并截断输出。"""

    backend: str

    async def execute(
        self, spec: SandboxSpec, action: SandboxAction
    ) -> SandboxActionOutcome: ...

    async def cleanup(self, spec: SandboxSpec) -> None: ...

    def availability(self) -> SandboxAvailability: ...


def is_within(child: Path, parent: Path) -> bool:
    """``child`` 是否位于 ``parent`` 之内（含相等）。路径都已 resolve 后使用。"""
    try:
        return child.resolve().is_relative_to(Path(parent).resolve())
    except OSError:
        return False


def validate_spec(spec: SandboxSpec, *, workspace_root: Path) -> list[str]:
    """策略校验：返回违规清单（空 = 通过）。runner 执行前最后一道闸。

    校验的是「这次执行想碰哪里」：workspace 必须在配置的 workspace 根下
    （每次调用一个独立子目录）。网络策略在配置层已拒绝「开网络无白名单」，
    这里复核 spec 与配置一致。
    """
    problems: list[str] = []
    workspace = Path(spec.workspace)
    root = Path(workspace_root)
    if workspace == root or not is_within(workspace, root):
        problems.append(f"workspace {workspace} 不在配置的 workspace 根 {root} 之下")
    if spec.network_enabled and not spec.network_allowlist:
        problems.append("network_enabled=true 但 allowlist 为空")
    if spec.limits.timeout_seconds <= 0 or spec.limits.memory_mb <= 0:
        problems.append("沙盒预算必须为正数")
    return problems


class DisabledSandboxExecutor:
    """默认后端：一切动作拒绝。「关闭」是明确状态，不是降级路径。"""

    backend = BACKEND_DISABLED

    def __init__(self, *, reason: str = "沙盒后端已禁用（SANDBOX_BACKEND=disabled）"):
        self._reason = reason

    def availability(self) -> SandboxAvailability:
        return SandboxAvailability(
            backend=self.backend, available=False, reason=self._reason
        )

    async def execute(
        self, spec: SandboxSpec, action: SandboxAction
    ) -> SandboxActionOutcome:
        audit().emit(
            "sandbox_refused",
            invocation_id=spec.invocation_id,
            session=spec.session_id,
            backend=self.backend,
            action=action.action,
            reason=self._reason,
        )
        return SandboxActionOutcome(
            action=action.action,
            ok=False,
            output="",
            error_code="sandbox_unavailable",
        )

    async def cleanup(self, spec: SandboxSpec) -> None:
        return None


def create_executor() -> SandboxExecutor:
    """按 ``SANDBOX_BACKEND`` 创建执行器。未知后端 fail-closed 到 Disabled。"""
    from config import settings

    backend = str(settings.SANDBOX_BACKEND)
    if backend == BACKEND_DOCKER:
        try:
            from skills.runners.docker import DockerSandboxExecutor

            return DockerSandboxExecutor(
                image=str(settings.SANDBOX_IMAGE),
                workspace_root=Path(settings.SANDBOX_WORKSPACE_ROOT),
                network_enabled=bool(settings.SANDBOX_NETWORK_ENABLED),
                network_allowlist=tuple(settings.SANDBOX_NETWORK_ALLOWLIST),
            )
        except Exception as exc:
            # runner 未装配/依赖缺失：fail-closed 到 Disabled，绝不回落宿主
            from nonebot import logger

            logger.warning(
                f"⚠️ [Sandbox] Docker runner 不可用，回退为禁用后端（fail-closed）: {exc}"
            )
            return DisabledSandboxExecutor(reason=f"Docker runner 不可用: {exc}")
    if backend != BACKEND_DISABLED:
        return DisabledSandboxExecutor(reason=f"未知沙盒后端 {backend!r}，已按禁用处理")
    return DisabledSandboxExecutor()


def executor_status(executor: SandboxExecutor | None) -> dict:
    """状态 API 的 sandbox 段（plan §6.5：后端状态，无敏感内容）。"""
    if executor is None:
        return {"backend": BACKEND_DISABLED, "available": False, "reason": "未装配"}
    info = executor.availability()
    return {
        "backend": info.backend,
        "available": info.available,
        "reason": info.reason,
    }
