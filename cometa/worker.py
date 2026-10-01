# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""cometa 独立 worker 进程（``python -m cometa.worker``，方案 §3.1/§6.8）。

进程纪律：

- **不导入 NoneBot gateway**：认领、执行、事件落库全部自持；
- 数据库租约保证单 owner：第二个 worker 在 :meth:`CometaStore.register_worker`
  处被拒（tests/cometa/test_store.py 的双 worker 用例）；
- 受控关闭（§6.8）：先停止接单/认领 → 通知在途任务中断保存 → 有界等待 →
  释放 worker 租约。到点未停的 attempt 靠租约过期 + 下次启动恢复矩阵收束，
  **不做无条件 running→queued**；
- ``worker_id``/``process_identity`` 由 supervisor 注入并写入 worker_leases，
  健康检查与身份核验都靠它，不按进程名扫描杀进程（§3.1）。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
import uuid
from datetime import timedelta

from .artifacts import ArtifactCollector
from .backends.registry import default_registry
from .config import CometaConfig
from .executor import AttemptExecutor
from .models import utc_now
from .store import CometaStore
from .workspace import WorkspaceManager

_LOGGER = logging.getLogger("cometa.worker")

TICK_INTERVAL_SECONDS = 1.0
DEFAULT_STOP_GRACE_SECONDS = 20.0


class CometaWorker:
    """单实例 worker：认领 → executor 驱动 → 租约续期 → 受控关闭。"""

    def __init__(
        self,
        *,
        instance_id: str,
        config: CometaConfig,
        worker_id: str | None = None,
        process_identity: str = "",
        store: CometaStore | None = None,
        registry=None,
    ):
        self.instance_id = instance_id
        self.config = config
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.process_identity = process_identity or f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.store = store or CometaStore(config.db_path)
        self.registry = registry if registry is not None else default_registry()
        self.executor = AttemptExecutor(
            store=self.store,
            registry=self.registry,
            workspaces=WorkspaceManager(config),
            artifacts=ArtifactCollector(config.artifacts_dir),
            config=config,
            worker_id=self.worker_id,
        )
        self._active: dict[str, asyncio.Task] = {}  # attempt_id -> run task
        self._stop = asyncio.Event()
        self._worker_epoch = 0
        backend_ids = {b.backend_id for b in config.enabled_backends()}
        backend_ids.add("fake")  # 无配置后端时 FakeBackend 仍是可执行基线
        self._backend_ids = backend_ids

    # ── 主循环 ───────────────────────────────────────────
    async def _register_with_retry(self) -> int:
        """带界重试的注册。重启 bot 时旧 worker 的租约往往还没过期（bot 被强杀
        时不释放租约），首拍注册会被拒——这正是「双 worker 不重复执行」的
        数据库保证在工作，此时**等待租约到期后接管**而不是崩溃退出
        （2026-09-30 人工清单 T8 前哨实测：worker 静默死亡导致任务滞留 queued）。"""
        deadline = time.monotonic() + max(self.config.lease_seconds * 2 + 10.0, 15.0)
        attempt = 0
        while True:
            try:
                return self.store.register_worker(
                    self.instance_id,
                    self.worker_id,
                    self.process_identity,
                    lease_seconds=self.config.lease_seconds,
                )
            except Exception as e:
                attempt += 1
                if time.monotonic() >= deadline:
                    raise
                if attempt == 1:
                    _LOGGER.warning(
                        "worker 注册被拒（%s）；旧 worker 租约未过期，"
                        "每 2s 重试直至可接管（上限 %.0fs）",
                        e,
                        deadline - time.monotonic(),
                    )
                await asyncio.sleep(min(2.0, max(0.2, deadline - time.monotonic())))

    async def run_forever(self, *, stop_grace_seconds: float = DEFAULT_STOP_GRACE_SECONDS):
        """进程入口主循环。正常退出只经由 :meth:`request_stop`。"""
        self._worker_epoch = await self._register_with_retry()
        _LOGGER.info(
            "cometa worker 启动 instance=%s worker=%s epoch=%s db=%s",
            self.instance_id,
            self.worker_id,
            self._worker_epoch,
            self.store.db_path,
        )
        self._recover_orphans()
        try:
            while not self._stop.is_set():
                await self._tick()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=TICK_INTERVAL_SECONDS)
        finally:
            await self._graceful_stop(stop_grace_seconds)

    def request_stop(self) -> None:
        self._stop.set()

    # ── 每 tick ──────────────────────────────────────────
    async def _tick(self) -> None:
        # 1) 续约（worker 租约 + 在途 attempt 租约）
        try:
            self._worker_epoch = self.store.register_worker(
                self.instance_id,
                self.worker_id,
                self.process_identity,
                lease_seconds=self.config.lease_seconds,
            )
        except Exception as e:
            _LOGGER.warning("worker 租约续期失败（下个 tick 重试）: %s", e)
            return
        for attempt_id in list(self._active):
            self.store.renew_lease(
                attempt_id, self.worker_id, lease_seconds=self.config.lease_seconds
            )
        # 2) 期限与过期输入（§6.2/§6.10）
        self.store.enforce_deadlines()
        self.store.expire_stale_inputs()
        # 3) 恢复扫描：租约过期且未终态的孤儿任务
        self._recover_orphans()
        # 4) 认领新任务（受 max_concurrent 限制）
        while len(self._active) < self.config.max_concurrent:
            claimed = self.store.claim_next_task(
                instance_id=self.instance_id,
                worker_id=self.worker_id,
                backend_ids=self._backend_ids,
                lease_seconds=self.config.lease_seconds,
            )
            if claimed is None:
                break
            task, attempt = claimed
            run_task = asyncio.create_task(
                self.executor.run_attempt(task, attempt),
                name=f"cometa-attempt-{attempt.attempt_id[:8]}",
            )
            self._active[attempt.attempt_id] = run_task
            run_task.add_done_callback(
                lambda _t, aid=attempt.attempt_id: self._active.pop(aid, None)
            )
            _LOGGER.info("claimed task=%s attempt=%s", task.task_id[:8], attempt.attempt_id[:8])
        # 5) 消费控制命令（记账：pending → delivered；executor 轮询任务状态执行）
        for attempt_id, run_task in list(self._active.items()):
            if run_task.done():
                continue
            attempt = self.store.get_attempt(attempt_id)
            if attempt is None or attempt.lease_owner != self.worker_id:
                continue
            self.store.pending_controls_for_task(
                attempt.task_id,
                owner=self.worker_id,
                epoch=attempt.lease_epoch,
                attempt_id=attempt_id,
            )

    def _recover_orphans(self) -> None:
        for task in self.store.tasks_needing_recovery(self.instance_id, now=utc_now()):
            if task.current_attempt in self._active:
                continue
            attempt = self.store.get_attempt(task.current_attempt)
            if attempt is None:
                continue
            result = self.executor.recover_task(task, attempt)
            _LOGGER.warning(
                "recovered task=%s attempt=%s -> %s",
                task.task_id[:8],
                attempt.attempt_id[:8],
                result,
            )

    # ── 受控关闭（§6.8） ─────────────────────────────────
    async def _graceful_stop(self, stop_grace_seconds: float) -> None:
        """先停止认领（主循环已停），再中断在途并保存，最后有界等待。"""
        deadline = utc_now() + timedelta(seconds=stop_grace_seconds)
        if self._active:
            _LOGGER.info("worker 关闭：请求中断 %d 个在途任务", len(self._active))
            for attempt_id, _run_task in list(self._active.items()):
                attempt = self.store.get_attempt(attempt_id)
                if attempt is None:
                    continue
                self.store.request_cancel(
                    attempt.task_id, actor=f"worker:{self.worker_id}:shutdown"
                )
            while self._active and utc_now() < deadline:
                await asyncio.sleep(0.2)
            remaining = [
                aid
                for aid, task in self._active.items()
                if not task.done() or task.cancelled()
            ]
            for aid in remaining:
                task = self._active.get(aid)
                if task is not None and not task.done():
                    task.cancel()
            if remaining:
                _LOGGER.warning(
                    "worker 关闭：%d 个任务未在期限内收束，交由租约过期与恢复矩阵处理",
                    len(remaining),
                )
        # 等待被取消的任务真正退出（有界）
        pending = [t for t in self._active.values() if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=5.0)
        try:
            self.store.release_worker(self.instance_id, self.worker_id)
        except Exception:
            _LOGGER.warning("worker 租约释放失败，等待过期", exc_info=True)
        _LOGGER.info("cometa worker 已停止 worker=%s", self.worker_id)


# ============================================================
# CLI 入口
# ============================================================


def _resolve_instance_id() -> str:
    """worker 与 Bot 同机部署：默认沿用 Bot 的 instance_id；
    supervisor 总是显式传参，这里是裸启动的兜底。"""
    try:
        from config import INSTANCE_ID

        return str(INSTANCE_ID)
    except Exception:
        return "default"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cometa.worker")
    parser.add_argument("--instance-id", default=None)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--stop-grace", type=float, default=DEFAULT_STOP_GRACE_SECONDS)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = CometaConfig.load()
    if args.db_path:
        config.db_path = __import__("pathlib").Path(args.db_path)
    instance_id = args.instance_id or _resolve_instance_id()
    worker = CometaWorker(
        instance_id=instance_id,
        config=config,
        worker_id=args.worker_id,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _handle_signal(*_a) -> None:
        worker.request_stop()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except (NotImplementedError, RuntimeError):
                # Windows 的 add_signal_handler 不可用：SIGINT 由 KeyboardInterrupt 兜底
                signal.signal(sig, _handle_signal)
    try:
        loop.run_until_complete(worker.run_forever(stop_grace_seconds=args.stop_grace))
    except KeyboardInterrupt:
        worker.request_stop()
        loop.run_until_complete(worker.run_forever(stop_grace_seconds=args.stop_grace))
    finally:
        loop.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["CometaWorker", "main"]
