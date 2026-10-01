# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""worker 子进程的启动/健康检查/受控停止（方案 §3.1/§6.8）。

纪律：WorkerSupervisor **只管理自己启动且身份核验一致的进程**——
不按进程名扫描、不结束其他 Codex（§3.1）。身份核验三件套：

1. 启动时注入 ``--worker-id`` 与随机 process_identity；
2. 健康检查读 worker_leases 行：worker_id 与 process_identity 都对上才算自己的；
3. 停止只 terminate 自己的 Popen 句柄；到点不退才 kill。

Windows 用 CREATE_NO_WINDOW：Bot 由 GUI 以无控制台方式启动，子进程
继承无控制台环境，弹窗会阻塞启动（repo 既有事实）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import uuid

from .config import CometaConfig
from .models import parse_iso_utc, utc_now
from .store import CometaStore

_LOGGER = logging.getLogger("cometa.supervisor")

CREATE_NO_WINDOW = 0x08000000  # 与 GUI 启动 Bot 的标志一致


class WorkerSupervisor:
    """一个实例最多一个 worker 子进程（worker_leases 单 owner 的进程侧镜像）。"""

    def __init__(
        self,
        *,
        config: CometaConfig,
        instance_id: str,
        python_executable: str | None = None,
        worker_id: str | None = None,
    ):
        self.config = config
        self.instance_id = instance_id
        self.worker_id = worker_id or f"cometa-worker-{uuid.uuid4().hex[:8]}"
        self.process_identity = f"{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self._python = python_executable or sys.executable
        self._process: subprocess.Popen | None = None
        self._log_handle = None

    # ── 生命周期 ─────────────────────────────────────────
    def start(self) -> bool:
        """启动 worker 子进程（幂等：已在运行则跳过）。

        worker 的 stdout/stderr 落到 ``cometa/worker.log``（每次启动重写）：
        子进程的崩溃（如注册被拒）不能只靠继承控制台——GUI/服务方式启动 bot
        时那里没人看（2026-09-30 人工清单实测：worker 静默死亡无痕迹）。"""
        if self._process is not None and self._process.poll() is None:
            return True
        args = [
            self._python,
            "-m",
            "cometa.worker",
            "--instance-id",
            self.instance_id,
            "--worker-id",
            self.worker_id,
        ]
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NO_WINDOW
        log_path = self._worker_log_path()
        try:
            if log_path is not None:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                kwargs["stdout"] = log_path.open("w", encoding="utf-8")
                kwargs["stderr"] = subprocess.STDOUT
            self._process = subprocess.Popen(args, **kwargs)
        except OSError as e:
            _LOGGER.error("worker 子进程启动失败: %s", e)
            self._process = None
            return False
        self._log_handle = kwargs.get("stdout")
        _LOGGER.info(
            "worker 子进程已启动 pid=%s worker=%s log=%s",
            self._process.pid,
            self.worker_id,
            log_path,
        )
        return True

    def _worker_log_path(self):
        base = getattr(self.config, "db_path", None)
        if base is None:
            return None
        return base.parent / "worker.log"

    def read_worker_log_tail(self, limit: int = 2000) -> str:
        """worker 崩溃诊断用：读取 worker.log 末尾。"""
        log_path = self._worker_log_path()
        if log_path is None or not log_path.is_file():
            return ""
        try:
            return log_path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return ""

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def health(self, store: CometaStore) -> dict:
        """进程存活 + 数据库身份核验（§3.1：身份一致才算健康）。"""
        info: dict = {
            "process_alive": self.is_running(),
            "worker_id": self.worker_id,
        }
        try:
            conn = store._connect()
            try:
                row = conn.execute(
                    "SELECT worker_id, process_identity, lease_until_utc"
                    " FROM worker_leases WHERE instance_id = ?",
                    (self.instance_id,),
                ).fetchone()
            finally:
                conn.close()
        except Exception as e:
            info["db_ok"] = False
            info["reason"] = str(e)[:120]
            return info
        info["db_ok"] = row is not None
        if row is not None:
            info["identity_matches"] = (
                str(row["worker_id"]) == self.worker_id
                and str(row["process_identity"]) == self.process_identity
            )
            until = parse_iso_utc(row["lease_until_utc"])
            info["lease_expired"] = bool(until is not None and until <= utc_now())
        return info

    def stop(self, *, grace_seconds: float = 10.0) -> None:
        """受控停止：terminate → 有界等待 → kill。只处理自己的进程句柄。"""
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            self._terminate(process)
            try:
                process.wait(timeout=max(grace_seconds, 1.0))
            except subprocess.TimeoutExpired:
                _LOGGER.warning(
                    "worker 未在 %.0fs 内退出，强制 kill（attempt 状态交恢复矩阵）",
                    grace_seconds,
                )
                self._kill(process)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=5.0)
        self._process = None
        if self._log_handle is not None:
            with contextlib.suppress(OSError):
                self._log_handle.close()
            self._log_handle = None
        _LOGGER.info("worker 子进程已停止 worker=%s", self.worker_id)

    # ── 内部 ─────────────────────────────────────────────
    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        # 进程刚好退出的竞态：忽略
        with contextlib.suppress(OSError):
            process.terminate()

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        with contextlib.suppress(OSError):
            process.kill()


__all__ = ["WorkerSupervisor"]
