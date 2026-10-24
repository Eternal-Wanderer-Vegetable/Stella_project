# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Pure deploy-side discovery and lifecycle client for the Corona owner.

This module deliberately avoids importing :mod:`config`, Bot code, or Corona's
ASGI application. Start/status/stop can therefore find the current owner before
consulting a changed business port or importing business settings.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from stella_bootstrap.config import build_config_revision, write_revision
from stella_bootstrap.home import resolve as resolve_home
from stella_bootstrap.identity import resolve_instance_id, runtime_dir
from stella_contracts.local_control import (
    LocalControlClient,
    LocalControlError,
    local_control_record_path,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_OPERATIONS = ("start", "stop", "restart", "status", "logs", "doctor")
RUNTIME_COMPONENTS = ("stella", "llama", "onebot")
_VALID_STATES = frozenset(
    {"disabled", "stopped", "starting", "running", "healthy", "degraded", "failed"}
)
_LOCAL_TIMEOUT = 1.0
_START_TIMEOUT = 60.0
_STOP_TIMEOUT = 45.0
_CLEARED_ENVIRONMENT = frozenset(
    {
        "STELLA_MANAGED_CORE",
        "STELLA_LAUNCH_TOKEN",
        "STELLA_GENERATION_ID",
        "STELLA_CONTROLLER_BOOT_ID",
        "STELLA_INTERNAL_HOST",
        "STELLA_INTERNAL_PORT",
        "STELLA_STOP_SENTINEL",
    }
)


def local_record_path(*, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    home = resolve_home(PROJECT_ROOT, create=False, environ=env).path.expanduser().resolve()
    instance_id = resolve_instance_id(PROJECT_ROOT, environ=env)
    return local_control_record_path(home, instance_id)


def status(*, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return live Corona status without trusting current business settings."""
    env = os.environ if environ is None else environ
    try:
        home, instance_id, path = _target(env, create=False)
    except Exception:
        return _failed_status("instance_unavailable", "无法定位当前 Stella 实例。")
    if not path.exists() and not path.is_symlink():
        if _owner_lock_held(home, instance_id) is not False:
            return _failed_status(
                "controller_unreachable",
                "Corona ownership lock is held but its authenticated endpoint is unavailable.",
                instance_id=instance_id,
            )
        return _stopped_status(instance_id)
    try:
        client = LocalControlClient.from_record_file(path, timeout=_LOCAL_TIMEOUT)
        payload = client.status()
        return _status_from_control(payload, home, instance_id)
    except LocalControlError as exc:
        code = _error_code(exc)
        if code == "controller_unavailable":
            if _owner_lock_held(home, instance_id) is False:
                return _stopped_status(instance_id)
            code = "controller_unreachable"
        return _failed_status(code, _public_error_message(code), instance_id=instance_id)


def start(
    *,
    detach: bool = True,
    force: bool = False,
    timeout: float = _START_TIMEOUT,
    environ: Mapping[str, str] | None = None,
    on_ready: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Start Corona if absent; a live or unresponsive owner is never duplicated."""
    del force  # Force never bypasses ownership, identity, or protocol checks.
    env = os.environ if environ is None else environ
    try:
        home, instance_id, path = _target(env, create=True)
    except Exception:
        return _operation_failure("start", "instance_unavailable", "无法定位当前 Stella 实例。")

    if path.exists() or path.is_symlink():
        try:
            existing = LocalControlClient.from_record_file(path, timeout=_LOCAL_TIMEOUT)
            payload = existing.status()
        except LocalControlError as exc:
            code = _error_code(exc)
            # A stale, valid record may belong to a dead process. The OS-level
            # Corona ownership lock decides whether a replacement can proceed.
            if code != "controller_unavailable":
                return _operation_failure("start", code, _public_error_message(code))
            if _owner_lock_held(home, instance_id) is not False:
                return _operation_failure(
                    "start",
                    "controller_unreachable",
                    "Corona ownership lock is held but its authenticated endpoint is unavailable.",
                )
        else:
            result = _operation_success("start", _status_from_control(payload, home, instance_id))
            result["phase"] = "already_running"
            if on_ready is not None:
                on_ready(result["data"])
            return result
    elif _owner_lock_held(home, instance_id) is not False:
        return _operation_failure(
            "start",
            "controller_unreachable",
            "Corona ownership lock is held but its authenticated endpoint is unavailable.",
        )

    try:
        revision = build_config_revision(
            project_root=PROJECT_ROOT,
            stella_home=home,
            external_environment=env,
        )
        revision_file = write_revision(home, instance_id, revision)
        child_env = _corona_environment(env, home, instance_id, revision_file)
        log_path = _corona_log_path(home)
        process = _spawn_corona(child_env, log_path=log_path, detach=detach)
    except Exception as exc:
        return _operation_failure(
            "start",
            "corona_start_failed",
            f"Corona 启动准备失败：{type(exc).__name__}。",
        )

    deadline = time.monotonic() + max(0.1, float(timeout))
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            code = "controller_already_owned" if exit_code == 73 else "corona_exited"
            return _operation_failure(
                "start",
                code,
                "已有 Corona 控制器仍持有实例。" if exit_code == 73 else f"Corona 提前退出（code {exit_code}）。",
            )
        try:
            client = LocalControlClient.from_record_file(path, timeout=_LOCAL_TIMEOUT)
            payload = client.status()
        except LocalControlError as exc:
            if _error_code(exc) != "controller_unavailable":
                return _operation_failure("start", _error_code(exc), _public_error_message(_error_code(exc)))
            time.sleep(0.1)
            continue
        data = _status_from_control(payload, home, instance_id)
        result = _operation_success("start", data)
        result["phase"] = "started"
        if on_ready is not None:
            on_ready(data)
        if not detach:
            exit_code = process.wait()
            result["exit_code"] = int(exit_code or 0)
            result["phase"] = "stopped"
            result["ok"] = result["exit_code"] == 0
        return result

    return _operation_failure(
        "start", "controller_start_timeout", "等待 Corona 本机控制接口超时；未回退启动 legacy Bot。"
    )


def stop(
    *,
    timeout: float = _STOP_TIMEOUT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Stop the owned Nucleus tree and Corona through its authenticated API."""
    env = os.environ if environ is None else environ
    try:
        _home, instance_id, path = _target(env, create=False)
    except Exception:
        return _operation_failure("stop", "instance_unavailable", "无法定位当前 Stella 实例。")
    if not path.exists() and not path.is_symlink():
        if _owner_lock_held(_home, instance_id) is False:
            return _operation_success("stop", _stopped_status(instance_id), phase="already_stopped")
        return _operation_failure(
            "stop",
            "controller_unreachable",
            "Corona ownership lock is held but its authenticated endpoint is unavailable.",
        )
    try:
        client = LocalControlClient.from_record_file(path, timeout=_LOCAL_TIMEOUT)
        client.stop(uuid.uuid4().hex)
    except LocalControlError as exc:
        code = _error_code(exc)
        if code == "controller_unavailable":
            if _owner_lock_held(_home, instance_id) is False:
                return _operation_success("stop", _stopped_status(instance_id), phase="already_stopped")
            return _operation_failure(
                "stop",
                "controller_unreachable",
                "Corona ownership lock is held but its authenticated endpoint is unavailable.",
            )
        return _operation_failure("stop", code, _public_error_message(code))

    deadline = time.monotonic() + max(0.1, float(timeout))
    while time.monotonic() < deadline:
        try:
            client.status()
        except LocalControlError as exc:
            if (
                _error_code(exc) == "controller_unavailable"
                and _owner_lock_held(_home, instance_id) is False
            ):
                return _operation_success("stop", _stopped_status(instance_id), phase="stopped")
        time.sleep(0.1)
    return _operation_failure(
        "stop", "controller_stop_timeout", "Corona 已收到停止请求，但控制器退出未获确认。"
    )


def restart(
    *,
    timeout: float = _START_TIMEOUT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    stopped = stop(environ=environ)
    if not stopped.get("ok"):
        return {**stopped, "operation": "restart"}
    started = start(detach=True, timeout=timeout, environ=environ)
    return {**started, "operation": "restart"}


def runtime_operation(
    operation: str,
    component: str = "stella",
    parameters: dict[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the schema-v1 Runtime envelope for Corona-owned Stella operations."""
    if component != "stella" or operation not in {"start", "stop", "restart", "status"}:
        return _operation_failure(
            operation,
            "unsupported_component_operation",
            f"Corona control client does not own {component}/{operation}.",
            component=component,
        )
    options = parameters or {}
    if operation == "start":
        result = start(detach=True, force=bool(options.get("force", False)), environ=environ)
    elif operation == "stop":
        result = stop(environ=environ)
    elif operation == "restart":
        result = restart(environ=environ)
    else:
        result = status(environ=environ)
        result = {
            "ok": bool(result.get("ok")),
            "operation": "status",
            "component": "stella",
            "exit_code": 0 if result.get("ok") else 1,
            "data": result,
        }
        if not result["ok"]:
            result["error"] = result["data"].get("error")
    result.setdefault("operation", operation)
    result.setdefault("component", component)
    result.setdefault("exit_code", 0 if result.get("ok") else 1)
    return result


def _target(env: Mapping[str, str], *, create: bool) -> tuple[Path, str, Path]:
    home = resolve_home(PROJECT_ROOT, create=create, environ=env).path.expanduser().resolve()
    instance_id = resolve_instance_id(PROJECT_ROOT, environ=env)
    return home, instance_id, local_control_record_path(home, instance_id)


def _status_from_control(
    payload: dict[str, object], home: Path, instance_id: str
) -> dict[str, Any]:
    core = payload.get("core")
    if not isinstance(core, dict):
        raise LocalControlError("local control response is invalid")
    phase = str(core.get("phase") or "unknown")
    desired = "running" if str(core.get("desired") or "running") == "running" else "stopped"
    state = _runtime_state(phase, desired)
    core_pid = _positive_int(core.get("pid"))
    controller_pid = _positive_int(payload.get("controller_pid"))
    public_url = _public_url(payload.get("public_host"), payload.get("public_port"))
    now = str(core.get("updated_at") or "")
    diagnostics: dict[str, Any] = {
        "controller_reachable": True,
        "controller_pid": controller_pid,
        "controller_boot_id": str(payload.get("controller_boot_id") or ""),
        "core_phase": phase,
        "core_pid": core_pid,
        "revision_id": str(core.get("revision_id") or ""),
        "generation_id": str(core.get("generation_id") or ""),
        "attempt": _nonnegative_int(core.get("attempt")),
        "public_host": payload.get("public_host"),
        "public_port": _positive_int(payload.get("public_port")),
        "webui_enabled": payload.get("webui_enabled") is True,
    }
    error_code = str(core.get("error") or "")
    stella_component: dict[str, Any] = {
        "state": state,
        "endpoint": public_url,
        "diagnostics": diagnostics,
    }
    if controller_pid is not None:
        stella_component["pid"] = controller_pid
    if error_code:
        stella_component["error"] = {
            "code": "component_failed",
            "message": error_code[:200],
            "details": {"core_phase": phase},
        }
    optional = _read_optional_runtime_state(home, instance_id)
    components = {"stella": stella_component, **optional}
    runtime = {
        "schema_version": 1,
        "instance_id": instance_id,
        "desired": desired,
        "updated_at": now,
        "components": components,
    }
    return {
        "ok": True,
        "managed": True,
        "alive": True,
        "pid": controller_pid,
        "api_reachable": phase == "ready",
        "controller_reachable": True,
        "nucleus_ready": phase == "ready",
        "core": core,
        "runtime": runtime,
        "public_base_url": public_url,
        "webui_enabled": payload.get("webui_enabled") is True,
        "instance_id": instance_id,
        "recent_log": None,
    }


def _read_optional_runtime_state(home: Path, instance_id: str) -> dict[str, Any]:
    path = runtime_dir(home, instance_id) / "runtime-state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        payload = None
    components = payload.get("components") if isinstance(payload, dict) else None
    output: dict[str, Any] = {}
    if not isinstance(components, dict):
        return {"llama": {"state": "disabled"}, "onebot": {"state": "disabled"}}
    for name in ("llama", "onebot"):
        item = components.get(name)
        if not isinstance(item, dict):
            output[name] = {"state": "disabled"}
            continue
        state = item.get("state")
        if state not in _VALID_STATES:
            state = "degraded"
        clean: dict[str, Any] = {"state": state}
        pid = _positive_int(item.get("pid"))
        if pid is not None:
            clean["pid"] = pid
        endpoint = item.get("endpoint")
        if isinstance(endpoint, str) and endpoint and len(endpoint) < 2048:
            clean["endpoint"] = endpoint
        output[name] = clean
    return output


def _stopped_status(instance_id: str) -> dict[str, Any]:
    components = {
        "stella": {"state": "stopped", "diagnostics": {"controller_reachable": False}},
        "llama": {"state": "disabled"},
        "onebot": {"state": "disabled"},
    }
    return {
        "ok": True,
        "managed": True,
        "alive": False,
        "pid": None,
        "api_reachable": False,
        "controller_reachable": False,
        "nucleus_ready": False,
        "core": {"desired": "stopped", "phase": "stopped", "instance_id": instance_id},
        "runtime": {
            "schema_version": 1,
            "instance_id": instance_id,
            "desired": "stopped",
            "updated_at": None,
            "components": components,
        },
        "public_base_url": None,
        "webui_enabled": False,
        "instance_id": instance_id,
        "recent_log": None,
    }


def _failed_status(code: str, message: str, *, instance_id: str | None = None) -> dict[str, Any]:
    value = _stopped_status(instance_id or "unknown")
    value.update(
        {
            "ok": False,
            "managed": True,
            "controller_failed": True,
            "error": {"code": code, "message": message},
        }
    )
    value["runtime"]["components"]["stella"] = {
        "state": "failed",
        "error": {"code": code, "message": message},
        "diagnostics": {"controller_reachable": False},
    }
    return value


def _runtime_state(phase: str, desired: str) -> str:
    if desired == "stopped" or phase == "stopped":
        return "stopped"
    if phase == "ready":
        return "healthy"
    if phase in {"starting", "validating", "loading"}:
        return "starting"
    # Corona phases such as draining/backoff stay in diagnostics. Runtime v1
    # retains its stable enum and represents them as degraded.
    return "degraded"


def _public_url(host: object, port: object) -> str | None:
    if not isinstance(host, str) or not host or isinstance(port, bool):
        return None
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    host = host.strip()
    if host in {"0.0.0.0", "::", ""}:
        host = "127.0.0.1"
    if any(char in host for char in "/?#@") or not host.isascii():
        return None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _corona_environment(
    environ: Mapping[str, str], home: Path, instance_id: str, revision_file: Path
) -> dict[str, str]:
    child = {str(key): str(value) for key, value in environ.items()}
    for key in _CLEARED_ENVIRONMENT:
        child.pop(key, None)
    child["STELLA_HOME"] = str(home)
    child["STELLA_INSTANCE_ID"] = instance_id
    child["STELLA_CONFIG_REVISION_FILE"] = str(revision_file)
    return child


def _corona_log_path(home: Path) -> Path:
    directory = home / "logs"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        directory.chmod(0o700)
    return directory / "corona-console.log"


def _spawn_corona(
    environ: dict[str, str], *, log_path: Path, detach: bool
) -> subprocess.Popen:
    options: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "env": environ,
        "stdin": subprocess.DEVNULL if detach else None,
        "start_new_session": bool(detach and os.name != "nt"),
    }
    log_stream = None
    if detach:
        flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(log_path, flags, 0o600)
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        log_stream = os.fdopen(descriptor, "ab", buffering=0)
        options["stdout"] = log_stream
        options["stderr"] = subprocess.STDOUT
    if os.name == "nt":
        options.pop("start_new_session", None)
        if detach:
            options["creationflags"] = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
    try:
        return subprocess.Popen([sys.executable, "-m", "corona"], **options)
    finally:
        if log_stream is not None:
            log_stream.close()


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _owner_lock_held(home: Path, instance_id: str) -> bool | None:
    """Probe Corona's process-held lock without signalling or changing the owner."""
    path = runtime_dir(home, instance_id) / "corona" / "ownership.lock"
    if not path.exists():
        return False
    if path.is_symlink():
        return None
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            locked = True
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            locked = True
        return False
    except OSError:
        return None
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(descriptor)


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _error_code(exc: LocalControlError) -> str:
    message = str(exc)
    if message == "Corona local control is unavailable":
        return "controller_unavailable"
    if "protocol" in message:
        return "protocol_mismatch"
    if "identity" in message:
        return "identity_mismatch"
    if "record" in message or "endpoint" in message or "capability" in message:
        return "control_record_invalid"
    return "control_request_failed"


def _public_error_message(code: str) -> str:
    return {
        "controller_unavailable": "Corona 本机控制接口不可达。",
        "protocol_mismatch": "Corona 本机控制协议版本不兼容。",
        "identity_mismatch": "Corona 本机控制实例身份不匹配。",
        "control_record_invalid": "Corona 本机控制记录无效或权限不安全。",
        "control_request_failed": "Corona 本机控制请求失败。",
    }.get(code, "Corona 控制状态无效。")


def _operation_success(
    operation: str, data: dict[str, Any], *, phase: str | None = None
) -> dict[str, Any]:
    result = {
        "ok": True,
        "operation": operation,
        "component": "stella",
        "exit_code": 0,
        "data": data,
    }
    if phase:
        result["phase"] = phase
    return result


def _operation_failure(
    operation: str,
    code: str,
    message: str,
    *,
    component: str = "stella",
) -> dict[str, Any]:
    return {
        "ok": False,
        "operation": operation,
        "component": component,
        "exit_code": 1,
        "error": {"code": code, "message": message[:500]},
    }


__all__ = [
    "PROJECT_ROOT",
    "RUNTIME_COMPONENTS",
    "RUNTIME_OPERATIONS",
    "local_record_path",
    "restart",
    "runtime_operation",
    "start",
    "status",
    "stop",
]
