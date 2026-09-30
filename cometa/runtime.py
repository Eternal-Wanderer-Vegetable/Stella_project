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
from dataclasses import dataclass, field

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
    # 运行期句柄必须声明为字段：slots dataclass 不允许事后赋新属性
    # （2026-09-30 实测：装配时 'CometaRuntime' object has no attribute
    # '_pump_stop' → cometa 整体停用，测试的 SimpleNamespace 替身掩盖了它）。
    _pump_stop: asyncio.Event | None = field(
        default=None, repr=False, compare=False
    )
    _pump_task: asyncio.Task | None = field(default=None, repr=False, compare=False)
    _watchdog_task: asyncio.Task | None = field(default=None, repr=False, compare=False)

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
            self._watchdog_task = asyncio.create_task(
                self._watch_worker(), name="cometa-worker-watchdog"
            )
        _LOGGER.info(
            "cometa runtime 已启动（worker 子进程=%s）",
            "yes" if self.supervisor is not None else "no",
        )

    async def _watch_worker(self) -> None:
        """worker 子进程退出看门狗：崩溃必须留痕（worker.log 有详情）。
        v1 不自动拉起（避免与租约恢复矩阵互相踩），只报错。"""
        supervisor = self.supervisor
        if supervisor is None:
            return
        while not self._pump_stop.is_set():
            await asyncio.sleep(5.0)
            if not supervisor.is_running():
                _LOGGER.error(
                    "❌ [Cometa] worker 子进程已退出（exit=%s）；任务认领已停摆，"
                    "详情见 %s。重启 bot 可恢复。",
                    supervisor._process.poll() if supervisor._process else "?",
                    supervisor._worker_log_path(),
                )
                return

    def _cancel_inflight_for_shutdown(self) -> int:
        """关闭协议第一步（§6.8「通知在途任务中断和保存」）：bot 侧经任务库
        对本实例 worker 的在途任务注入取消。worker 里的执行器每 2s 轮询到
        cancelling 即确认后端停止并落终态——Windows 的 terminate() 是硬杀，
        worker 自己的优雅关闭代码没有机会执行（2026-09-30 人工清单 T14 实测：
        在途任务优雅关闭后仍是 running）。返回注入数。"""
        supervisor = self.supervisor
        if supervisor is None:
            return 0
        injected = 0
        try:
            for task_id in self.store.tasks_in_flight(
                self.instance_id, worker_id=supervisor.worker_id
            ):
                with contextlib.suppress(Exception):
                    self.store.request_cancel(
                        task_id,
                        actor=f"runtime:{supervisor.worker_id}:shutdown",
                    )
                    injected += 1
        except Exception:
            _LOGGER.warning(
                "shutdown：在途任务取消注入失败，交由租约过期与恢复矩阵处理",
                exc_info=True,
            )
        if injected:
            _LOGGER.info("cometa 关闭：已请求中断 %d 个在途任务", injected)
        return injected

    async def stop(self, *, grace_seconds: float = 10.0) -> None:
        """受控关闭：注入在途取消 → 泵 → worker 子进程（terminate 只兜底）。"""
        if getattr(self, "_pump_stop", None) is not None:
            self._pump_stop.set()
        watchdog = getattr(self, "_watchdog_task", None)
        if watchdog is not None:
            watchdog.cancel()
        if self.supervisor is not None and self.supervisor.is_running():
            # 注入要趁 worker 的执行器还活着：executor 轮询 2s + 确认停止 +
            # 落终态 ≈ 3-5s，宽限给足
            self._cancel_inflight_for_shutdown()
            await asyncio.sleep(min(6.0, max(grace_seconds - 4.0, 2.0)))
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
