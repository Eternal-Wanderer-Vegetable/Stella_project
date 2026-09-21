# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skills 运行时装配点：进程级单例的安装与读取。

装配发生在 ``bot._bootstrap_capabilities``（plan §6.5：插件能力准备之后、
Router 预热之前）；``capability/hooks.py`` 只通过本模块的访问器拿实例——
拿不到（未装配/测试环境）就当 Skills 层不存在，立即返回。这样主链路
不依赖 Skills 的 import，Skills 的失败也不污染能力层。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from skills.orchestrator import SkillOrchestrator


@dataclass(frozen=True)
class SkillRuntime:
    """一次装配的全部部件。``orchestrator.executor`` 为 None 表示无沙盒。"""

    catalog: Any  # skills.catalog.SkillCatalog
    selector: Any  # skills.selector.SkillSelector
    orchestrator: Any  # skills.orchestrator.SkillOrchestrator | None
    audit: Any = None  # skills.audit.AuditLog（step 5 接线）

    def status(self) -> dict:
        """状态 API 的 skills 段（plan §6.5：只返回计数与后端状态）。"""
        payload: dict[str, Any] = {
            "installed": True,
            "orchestrator": self.orchestrator is not None,
        }
        catalog_status = getattr(self.catalog, "status", None)
        if callable(catalog_status):
            payload["catalog"] = catalog_status()
        return payload


_RUNTIME: SkillRuntime | None = None


def install(runtime: SkillRuntime) -> None:
    """装上（或整体替换）进程级运行时。装配失败不应走到这里。"""
    global _RUNTIME
    _RUNTIME = runtime


def reset() -> None:
    """卸载运行时（测试与进程收尾用）。"""
    global _RUNTIME
    _RUNTIME = None


def current() -> SkillRuntime | None:
    """当前运行时；未装配返回 None（主链路据此立即跳过 Skills 分支）。"""
    return _RUNTIME


def build_runtime() -> SkillRuntime | None:
    """按 settings 装配完整运行时；装配失败返回 None 并由调用方告警。

    沙盒执行器按 ``SANDBOX_BACKEND`` 选择（skills.sandbox.create_executor）：
    禁用/不可用后端一律 fail-closed（ DisabledSandboxExecutor 或 executor
    为 None），绝不回落宿主执行；目录发现、候选与正文浏览不受影响。
    """
    from skills.catalog import SkillCatalog
    from skills.sandbox import create_executor
    from skills.selector import SkillSelector

    catalog = SkillCatalog.from_settings()
    if not catalog.refresh():
        # 首次刷新失败：不是致命状态（目录可能还没有），但要知道
        from nonebot import logger

        logger.warning(f"⚠️ [Skills] 首次目录刷新失败: {catalog.status()['last_error']}")
    selector = SkillSelector.from_settings(catalog)
    orchestrator = _build_orchestrator(executor=create_executor())
    return SkillRuntime(catalog=catalog, selector=selector, orchestrator=orchestrator)


def _build_orchestrator(executor: Any) -> "SkillOrchestrator | None":
    from config import settings
    from skills.model import SandboxLimits
    from skills.orchestrator import SkillOrchestrator

    planner = _build_planner()
    limits = SandboxLimits(
        cpu=float(settings.SANDBOX_CPU_LIMIT),
        memory_mb=int(settings.SANDBOX_MEMORY_LIMIT),
        pids=int(settings.SANDBOX_PIDS_LIMIT),
        timeout_seconds=float(settings.SANDBOX_TIMEOUT),
        output_max_chars=int(settings.SANDBOX_OUTPUT_MAX_CHARS),
        artifact_max_bytes=int(settings.SANDBOX_ARTIFACT_MAX_BYTES),
    )
    return SkillOrchestrator(
        planner=planner,
        executor=executor,
        workspace_root=Path(settings.SANDBOX_WORKSPACE_ROOT),
        limits=limits,
        backend=str(settings.SANDBOX_BACKEND),
        image=str(settings.SANDBOX_IMAGE),
        body_max_chars=int(settings.SKILLS_BODY_MAX_CHARS),
        total_timeout=float(settings.SKILLS_TOTAL_TIMEOUT),
        output_max_chars=int(settings.SKILLS_OUTPUT_MAX_CHARS),
        asset_max_bytes=int(settings.SKILLS_ASSET_MAX_BYTES),
        network_enabled=bool(settings.SANDBOX_NETWORK_ENABLED),
        network_allowlist=tuple(settings.SANDBOX_NETWORK_ALLOWLIST),
    )


def _build_planner() -> Any:
    """规划模型：复用插件角色模型（``astrbot_compat.llm`` 的 provider 通道），
    不带 Stella 人格与聊天上下文。

    装配失败（无 astrbot 兼容层/无模型）返回 None → orchestrator 对
    执行一律 fail-closed，但候选浏览照常可用。
    """
    try:
        from astrbot_compat.llm.manager import get_provider_manager
    except Exception:
        return None

    async def _plan(prompt: str) -> str:
        provider = get_provider_manager().provider
        if provider is None:
            raise RuntimeError("生成模型不可用")
        resp = await provider.text_chat(prompt=prompt, session_id="skills-planner")
        return str(getattr(resp, "completion_text", "") or "")

    return _plan
