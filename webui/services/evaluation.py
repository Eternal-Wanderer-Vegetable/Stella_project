# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""隔离验证执行器的 Dashboard 适配（计划 §6.7.2 / M6 实验入口）。

合同：

- 本服务只 **以固定参数 schema 启动 CLI 子进程**
  （``scripts/run_flow_evaluation.py``），不接任意 Python 模块、pickle 或
  shell 命令（计划 §6.7.2「Dashboard 实验 API 只调用固定 CLI/参数 schema」）；
- 实验工作目录放在系统临时区（``<tmp>/stella-evaluation/<run_id>``），
  全部实验状态由 runner 强制留在该目录内；
- **实验上限 1 并发**（计划 §6.7.4：实验上限 1 并发）；
- 记录 PID 与报告路径；取消即杀进程树（含 runner 的 worker 子进程），
  worker 落下的 partial 报告保留在报告路径。
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["cancel_run", "get_run", "list_runs", "start_run"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "run_flow_evaluation.py"
_EVAL_MODES = ("trace_playback", "decision_recompute", "isolated_pipeline", "model_validation")
_MAX_CONCURRENT = 1
_MAX_HISTORY = 50

_LOCK = threading.Lock()
_RUNS: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_CURRENT_RUNNING: str | None = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finalize(handle: dict[str, Any], exit_code: int | None) -> None:
    """等待线程收尾：读 CLI 退出码与 report.json，不覆盖 cancelled 状态。"""
    handle["exit_code"] = exit_code
    handle["finished_utc"] = _utcnow()
    report_path = Path(handle["report_path"])
    if handle["status"] == "cancelled":
        return
    if exit_code == 0 and report_path.is_file():
        handle["status"] = "completed"
    elif exit_code == 3 and report_path.is_file():
        handle["status"] = "partial"
    else:
        handle["status"] = "failed"
        handle["error"] = handle.get("error") or f"CLI 退出码 {exit_code}，未见完整报告"


def _waiter(run_id: str, proc: subprocess.Popen) -> None:
    exit_code = proc.wait()
    global _CURRENT_RUNNING
    with _LOCK:
        handle = _RUNS.get(run_id)
        if handle is None:
            return
        _finalize(handle, exit_code)
        if run_id == _CURRENT_RUNNING:
            _CURRENT_RUNNING = None


def start_run(
    mode: str,
    dataset: str,
    *,
    snapshot: str | None = None,
    seed: int | None = None,
    budget_max_calls: int | None = None,
    budget_timeout: float | None = None,
) -> dict[str, Any]:
    """以固定参数启动一次实验 CLI；返回任务句柄（含 PID 与报告路径）。

    参数非法/路径不存在/已有实验在跑都抛 ``ValueError``（router 转 400）。
    """
    if mode not in _EVAL_MODES:
        msg = f"未知实验模式: {mode}（可选 {'/'.join(_EVAL_MODES)}）"
        raise ValueError(msg)
    dataset_path = Path(dataset).resolve()
    if not dataset_path.is_dir():
        msg = f"数据集目录不存在: {dataset_path}"
        raise ValueError(msg)
    snapshot_path = Path(snapshot).resolve() if snapshot else None
    if snapshot and (snapshot_path is None or not snapshot_path.is_dir()):
        msg = f"快照目录不存在: {snapshot}"
        raise ValueError(msg)
    if not _CLI_PATH.is_file():
        msg = f"评测 CLI 不存在: {_CLI_PATH}"
        raise RuntimeError(msg)

    global _CURRENT_RUNNING
    with _LOCK:
        if _CURRENT_RUNNING is not None:
            msg = f"已有实验在运行（并发上限 {_MAX_CONCURRENT}）: {_CURRENT_RUNNING}"
            raise ValueError(msg)
        run_id = uuid.uuid4().hex[:12]
        workdir = Path(tempfile.gettempdir()) / "stella-evaluation" / run_id
        workdir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, "-X", "utf8", str(_CLI_PATH),
            "--mode", mode,
            "--dataset", str(dataset_path),
            "--workdir", str(workdir),
        ]
        if snapshot_path is not None:
            cmd += ["--snapshot", str(snapshot_path)]
        if seed is not None:
            cmd += ["--seed", str(seed)]
        if budget_max_calls is not None:
            cmd += ["--budget-max-calls", str(budget_max_calls)]
        if budget_timeout is not None:
            cmd += ["--budget-timeout", str(budget_timeout)]
        report_path = workdir / "artifacts" / "report.json"
        handle: dict[str, Any] = {
            "run_id": run_id,
            "mode": mode,
            "dataset": str(dataset_path),
            "snapshot": str(snapshot_path) if snapshot_path else None,
            "workdir": str(workdir),
            "status": "running",
            "pid": None,
            "report_path": str(report_path),
            "created_utc": _utcnow(),
            "started_utc": None,
            "finished_utc": None,
            "exit_code": None,
            "error": None,
        }
        _RUNS[run_id] = handle
        _RUNS.move_to_end(run_id)
        while len(_RUNS) > _MAX_HISTORY:
            _RUNS.popitem(last=False)

    log_dir = workdir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if sys.platform == "win32" else 0
    with (log_dir / "cli_stdout.log").open("wb") as log_fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_REPO_ROOT),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=creationflags,
            start_new_session=(sys.platform != "win32"),
        )
    with _LOCK:
        handle["pid"] = proc.pid
        handle["started_utc"] = _utcnow()
        _CURRENT_RUNNING = run_id
    threading.Thread(target=_waiter, args=(run_id, proc), daemon=True).start()
    return dict(handle)


def cancel_run(run_id: str) -> dict[str, Any]:
    """杀实验进程树（含 worker）；worker 的 partial 报告保留在报告路径。"""
    with _LOCK:
        handle = _RUNS.get(run_id)
        if handle is None:
            msg = f"实验不存在: {run_id}"
            raise ValueError(msg)
        if handle["status"] != "running":
            return dict(handle)
        pid = handle.get("pid")
        handle["status"] = "cancelled"
        handle["error"] = "被管理员取消"
    if pid:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, check=False,
            )
        else:
            import signal

            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGTERM)
    # 等待线程稍后补 exit_code/finished_utc；给一个短的同步窗口
    for _ in range(30):
        time.sleep(0.1)
        with _LOCK:
            if _RUNS.get(run_id, {}).get("finished_utc"):
                break
    with _LOCK:
        return dict(_RUNS.get(run_id, handle))


def get_run(run_id: str, *, include_report: bool = True) -> dict[str, Any] | None:
    """单条实验状态；``include_report`` 时附带完整报告（如已落盘）。"""
    with _LOCK:
        handle = _RUNS.get(run_id)
        if handle is None:
            return None
        detail = dict(handle)
    if include_report:
        report_path = Path(detail["report_path"])
        if report_path.is_file():
            try:
                detail["report"] = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                detail["report"] = None
    return detail


def list_runs(*, limit: int = 50) -> list[dict[str, Any]]:
    """实验列表（最新在前；只含句柄不含报告正文）。"""
    with _LOCK:
        items = [dict(h) for h in reversed(_RUNS.values())]
    return items[: max(0, limit)]
