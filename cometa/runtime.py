# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Bot 进程内的 cometa 装配与受控关闭（方案 §3.2 runtime、§6.8 关闭）。

与 scheduling 的装配模式一致（ai_gateway._build_scheduling_stack 的镜像）：

- 失败（配置坏/迁移失败）**抛给调用方**，接线层捕获后停用 cometa 功能，
  进程本身照常运行；
- 关闭共享现有有界 shutdown 预算：先停泵与认领，再停 worker 子进程，
  不给每个子系统串行叠加完整超时时间（§6.8）。

cometa 内核（store/worker/executor）刻意不 import 本模块——runtime 只属于
Bot 进程。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass

from .artifacts import ArtifactCollector
from .config import CometaConfig
from .delivery import NotificationPump, NotificationSender
from .service import Actor, CometaService
from .store import CometaStore
from .supervisor import WorkerSupervisor
from .workspace import WorkspaceManager

_LOGGER = logging.getLogger("cometa.runtime")


@dataclass(slots=True)
class CometaRuntime:
    """Bot 进程持有的全部 cometa 组件。"""

    config: CometaConfig
    store: CometaStore
    service: CometaService
    pump: NotificationPump
    workspaces: WorkspaceManager
    artifacts: ArtifactCollector
    supervisor: WorkerSupervisor | None = None
    instance_id: str = ""

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    async def start(self, *, spawn_worker: bool = True) -> None:
        """启动投递泵与（可选的）worker 子进程。"""
        self._pump_stop = asyncio.Event()
        self._pump_task = asyncio.create_task(
            self.pump.run_forever(self._pump_stop), name="cometa-delivery-pump"
        )
        if spawn_worker and self.supervisor is not None:
            self.supervisor.start()
        _LOGGER.info(
            "cometa runtime 已启动（worker 子进程=%s）",
            "yes" if self.supervisor is not None else "no",
        )

    async def stop(self, *, grace_seconds: float = 10.0) -> None:
        """受控关闭：泵 → worker 子进程 → 存量状态留给租约/恢复矩阵。"""
        if getattr(self, "_pump_stop", None) is not None:
            self._pump_stop.set()
        pump_task = getattr(self, "_pump_task", None)
        if pump_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(pump_task), timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pump_task.cancel()
        if self.supervisor is not None:
            self.supervisor.stop(grace_seconds=grace_seconds)
        _LOGGER.info("cometa runtime 已停止")


def build_runtime(
    config: CometaConfig | None = None,
    *,
    sender: NotificationSender | None = None,
    instance_id: str = "",
    spawn_worker: bool = True,
) -> CometaRuntime:
    """装配 cometa runtime。配置/迁移失败直接抛错（调用方停用功能）。

    ``sender`` 由接线层注入（QQ 桥接/WebChat）；未注入且需要投递时泵会
    记录 delivery_unknown——宁可 unknown 也不静默丢弃。
    """
    config = config or CometaConfig.load()
    store = CometaStore(config.db_path)
    service = CometaService(store, config, instance_id=instance_id)
    workspaces = WorkspaceManager(config)
    artifacts = ArtifactCollector(config.artifacts_dir)
    pump = NotificationPump(store, sender, config=config)
    supervisor: WorkerSupervisor | None = None
    if spawn_worker:
        supervisor = WorkerSupervisor(
            config=config,
            instance_id=instance_id,
            python_executable=sys.executable,
        )
    return CometaRuntime(
        config=config,
        store=store,
        service=service,
        pump=pump,
        workspaces=workspaces,
        artifacts=artifacts,
        supervisor=supervisor,
        instance_id=instance_id,
    )


SYSTEM_ACTOR = Actor(kind="system", id="runtime")

# ── 进程内服务定位（方案 §3.2：runtime 负责「Bot 进程服务定位」）──
# capability.delegation / QQ 桥接 / WebUI 都通过 current() 取服务，
# 不反向 import ai_gateway（避免重型依赖环）。测试可 set_current(None) 复位。
_current_runtime: CometaRuntime | None = None


def set_current(runtime: CometaRuntime | None) -> None:
    """登记/清除本进程的 cometa runtime（装配成功后调用）。"""
    global _current_runtime
    _current_runtime = runtime


def current() -> CometaRuntime | None:
    """本进程的 cometa runtime；未装配或停用时返回 None。"""
    return _current_runtime


def current_service() -> CometaService | None:
    """便捷取服务。未启用返回 None——调用方必须按「功能未装配」处理。"""
    runtime = _current_runtime
    if runtime is None or not runtime.enabled:
        return None
    return runtime.service


__all__ = [
    "SYSTEM_ACTOR",
    "CometaRuntime",
    "build_runtime",
    "current",
    "current_service",
    "set_current",
]
