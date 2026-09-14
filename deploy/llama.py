# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Local llama.cpp embedding service supervision.

OneClick ships the CPU server and the qwen embedding model, but it must not
pretend that an embedding-only model can answer chat requests. This module
owns only the local embedding server and leaves chat endpoint selection to the
existing LLM registry.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from config import LM_STUDIO_BASE_URL, STELLA_HOME

from . import packages, runtime

STARTUP_TIMEOUT_SECONDS = 30.0
POLL_INTERVAL_SECONDS = 0.5


def _endpoint_ready(base_url: str) -> bool:
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/v1/models",
            timeout=1.0,
            trust_env=False,
        )
        response.raise_for_status()
        payload = response.json()
        return isinstance(payload, dict) and isinstance(payload.get("data"), list)
    except Exception:
        return False


def _server_path() -> Path | None:
    candidates: list[tuple[str, Path]] = []
    try:
        registry = packages.read_registry(STELLA_HOME)
    except packages.PackageError:
        return None
    for record in registry.get("packages", []):
        if (
            record.get("kind") != "component"
            or record.get("id") != "llama-cpu"
        ):
            continue
        root = STELLA_HOME / str(record.get("path") or "")
        executable = root / ("llama-server.exe" if os.name == "nt" else "llama-server")
        if executable.is_file():
            candidates.append((str(record.get("version") or ""), executable))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    from .process import is_alive

    return is_alive(value)


def _current_pid() -> int | None:
    state = runtime.read_state()
    value = (state.get("components") or {}).get("llama") or {}
    pid = value.get("pid")
    return int(pid) if isinstance(pid, int) and pid > 0 else None


def _stop_pid(pid: int) -> bool:
    if not _pid_alive(pid):
        return True
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        return False
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(POLL_INTERVAL_SECONDS)
    return not _pid_alive(pid)


def stop_local_embedding_service() -> dict[str, Any]:
    """Stop only the llama process owned by this Stella instance."""
    pid = _current_pid()
    if pid is None:
        return {"ok": True, "message": "本地 llama embedding 服务未运行。"}
    if not _stop_pid(pid):
        runtime.update_component(
            "llama",
            "failed",
            pid=pid,
            error=f"无法停止本地 llama embedding 服务（PID {pid}）",
            desired="stopped",
        )
        return {"ok": False, "message": f"无法停止本地 llama embedding 服务（PID {pid}）。"}
    runtime.update_component("llama", "stopped", desired="stopped")
    return {"ok": True, "message": "本地 llama embedding 服务已停止。"}


def _launch_local(endpoint: dict[str, Any]) -> dict[str, Any]:
    executable = _server_path()
    model_path = Path(endpoint["model_path"])
    if executable is None:
        return {"ok": False, "message": "未找到已安装的 llama-server。"}
    if not model_path.is_file():
        return {"ok": False, "message": f"未找到本地 embedding 模型：{model_path}"}

    log_path = runtime.INSTANCE_RUNTIME_DIR / "logs" / "llama.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "--model",
        str(model_path),
        "--host",
        str(endpoint["host"]),
        "--port",
        str(endpoint["port"]),
        "--embedding",
        "--pooling",
        "mean",
        "--ctx-size",
        str(endpoint["ctx_size"]),
    ]
    model_id = str(endpoint.get("model") or "").strip()
    if model_id:
        command.extend(["--alias", model_id])

    try:
        log = log_path.open("ab")
        flags = 0
        if os.name == "nt":
            flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        proc = subprocess.Popen(
            command,
            cwd=str(executable.parent),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            start_new_session=os.name != "nt",
        )
        log.close()
    except (OSError, ValueError) as exc:
        with contextlib.suppress(Exception):
            log.close()
        return {"ok": False, "message": f"启动本地 llama-server 失败：{exc}"}

    runtime.update_component(
        "llama",
        "starting",
        pid=proc.pid,
        endpoint=endpoint["base_url"],
        desired="running",
    )
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_alive(proc.pid):
            runtime.update_component(
                "llama",
                "failed",
                error=f"llama-server 在启动期间退出（PID {proc.pid}）",
                desired="running",
            )
            return {
                "ok": False,
                "message": f"llama-server 在启动期间退出（PID {proc.pid}），请检查 {log_path}",
            }
        if _endpoint_ready(str(endpoint["base_url"])):
            runtime.update_component(
                "llama",
                "healthy",
                pid=proc.pid,
                endpoint=endpoint["base_url"],
                desired="running",
            )
            return {
                "ok": True,
                "source": "local",
                "endpoint": endpoint["base_url"],
                "model": endpoint.get("model", ""),
                "message": f"已启动本地 llama embedding 服务（PID {proc.pid}）。",
            }
        time.sleep(POLL_INTERVAL_SECONDS)

    _stop_pid(proc.pid)
    runtime.update_component(
        "llama",
        "failed",
        error=f"llama-server 启动超时（PID {proc.pid}）",
        desired="running",
    )
    return {
        "ok": False,
        "message": f"本地 llama-server 启动超时，请检查 {log_path}",
    }


def ensure_local_embedding_service(
    *, preferred_url: str = LM_STUDIO_BASE_URL
) -> dict[str, Any]:
    """Prefer LM Studio, otherwise start and return the bundled local service."""
    endpoint = runtime.embedding_endpoint_config()
    if endpoint is None:
        return {"ok": False, "source": "unavailable", "message": "未配置本地 embedding runtime。"}

    if (
        preferred_url
        and preferred_url.rstrip("/") != endpoint["base_url"].rstrip("/")
        and _endpoint_ready(preferred_url)
    ):
        return {
            "ok": True,
            "source": "external",
            "endpoint": preferred_url.rstrip("/"),
            "model": endpoint.get("model", ""),
            "message": "LM Studio embedding 服务可用。",
        }

    if _endpoint_ready(endpoint["base_url"]):
        return {
            "ok": True,
            "source": "local",
            "endpoint": endpoint["base_url"],
            "model": endpoint.get("model", ""),
            "message": "本地 llama embedding 服务已可用。",
        }

    pid = _current_pid()
    if pid is not None and _pid_alive(pid):
        return {
            "ok": False,
            "source": "local",
            "message": f"本地 llama embedding 服务仍在启动（PID {pid}）。",
        }
    return _launch_local(endpoint)


def status() -> dict[str, Any]:
    endpoint = runtime.embedding_endpoint_config()
    pid = _current_pid()
    return {
        "enabled": endpoint is not None,
        "endpoint": endpoint["base_url"] if endpoint else "",
        "model": endpoint.get("model", "") if endpoint else "",
        "model_path": endpoint.get("model_path", "") if endpoint else "",
        "pid": pid,
        "alive": bool(pid and _pid_alive(pid)),
        "ready": bool(endpoint and _endpoint_ready(endpoint["base_url"])),
    }


__all__ = [
    "ensure_local_embedding_service",
    "status",
    "stop_local_embedding_service",
]
