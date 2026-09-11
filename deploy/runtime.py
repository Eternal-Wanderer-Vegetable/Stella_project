# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Stella Runtime Contract 的 Python 兼容实现。

Runtime manager 在 Rust 侧负责长期进程监督；Python 侧只维护同一份
manifest/state JSON 契约，供旧 deploy、GUI 和诊断工具在迁移期使用。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import INSTANCE_ID, INSTANCE_RUNTIME_DIR, PROJECT_ROOT

SCHEMA_VERSION = 1
COMPONENTS = ("stella", "llama", "onebot")
OPERATIONS = ("start", "stop", "restart", "status", "logs", "doctor")
STATES = (
    "disabled",
    "stopped",
    "starting",
    "running",
    "healthy",
    "degraded",
    "failed",
)

MANIFEST_FILENAME = "runtime-manifest.json"
STATE_FILENAME = "runtime-state.json"
ERROR_CODES = (
    "invalid_operation",
    "invalid_component",
    "unsupported_component_operation",
    "invalid_manifest",
    "invalid_state",
    "runtime_unavailable",
    "component_failed",
    "operation_failed",
)
_SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|credential)", re.IGNORECASE
)
_FORBIDDEN_REQUEST_KEYS = frozenset({"command", "cmd", "shell", "shell_command", "executable"})


def manifest_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or INSTANCE_RUNTIME_DIR) / MANIFEST_FILENAME


def state_path(runtime_dir: Path | None = None) -> Path:
    return (runtime_dir or INSTANCE_RUNTIME_DIR) / STATE_FILENAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
        with contextlib.suppress(OSError), path.parent.open("rb") as directory:
            os.fsync(directory.fileno())
    finally:
        temp_path = Path(name)
        if temp_path.exists():
            temp_path.unlink()


def default_manifest() -> dict[str, Any]:
    """返回不含机器密钥和任意 shell 命令的默认 manifest。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": INSTANCE_ID,
        "project_root": str(PROJECT_ROOT.resolve()),
        "runtime_dir": str(INSTANCE_RUNTIME_DIR),
        "components": {
            "stella": {
                "kind": "stella",
                "enabled": True,
                "dependencies": [],
                "health": {"type": "http", "path": "/stella/status"},
                "logs": {"path": "logs/stella.log"},
            },
            "llama": {
                "kind": "llama",
                "enabled": False,
                "dependencies": [],
                "health": {"type": "http", "path": "/v1/models"},
                "logs": {"path": "logs/llama.log"},
            },
            "onebot": {
                "kind": "onebot",
                "enabled": False,
                "dependencies": ["stella"],
                "health": {"type": "link-status"},
                "logs": {"path": "logs/onebot.log"},
            },
        },
    }


def default_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": INSTANCE_ID,
        "desired": "stopped",
        "updated_at": _now(),
        "components": {
            "stella": {"state": "stopped"},
            "llama": {"state": "disabled"},
            "onebot": {"state": "disabled"},
        },
    }


def structured_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    """Build the stable error envelope shared by Python, Rust and the GUI."""
    if code not in ERROR_CODES:
        code = "invalid_operation"
    value: dict[str, Any] = {"code": code, "message": str(message)[:500]}
    if details:
        value["details"] = redact_value(details)
    return value


def redact_value(value: Any, *, key: str = "") -> Any:
    """Recursively redact credential-like fields before they cross a boundary."""
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value


def validate_manifest(payload: dict[str, Any]) -> None:
    """Validate the portable subset of the Runtime manifest."""
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("manifest schema_version 不受支持")
    components = payload.get("components")
    if not isinstance(components, dict) or not components:
        raise ValueError("manifest 必须包含 components")
    for name, spec in components.items():
        if name not in COMPONENTS or not isinstance(spec, dict):
            raise ValueError(f"manifest 包含未知组件：{name}")
        if spec.get("kind") != name:
            raise ValueError(f"组件 {name} 的 kind 不匹配")
        if not isinstance(spec.get("enabled"), bool):
            raise ValueError(f"组件 {name} 的 enabled 必须是布尔值")
        for dependency in spec.get("dependencies") or []:
            if dependency not in COMPONENTS:
                raise ValueError(f"组件 {name} 依赖未知组件：{dependency}")
        health = spec.get("health")
        if health is not None and not isinstance(health, dict):
            raise ValueError(f"组件 {name} 的 health 必须是对象")


def validate_state_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("state schema_version 不受支持")
    validate_state(str(payload.get("desired", "")))
    components = payload.get("components")
    if not isinstance(components, dict):
        raise ValueError("state 必须包含 components")
    for name, spec in components.items():
        if name not in COMPONENTS or not isinstance(spec, dict):
            raise ValueError(f"state 包含未知组件：{name}")
        validate_state(str(spec.get("state", "")))
        if "pid" in spec and (not isinstance(spec["pid"], int) or spec["pid"] <= 0):
            raise ValueError(f"组件 {name} 的 pid 无效")
        if "error" in spec and not isinstance(spec["error"], dict):
            raise ValueError(f"组件 {name} 的 error 无效")


def validate_operation_request(payload: dict[str, Any]) -> None:
    """Reject shell-shaped requests; only enum operations reach the supervisor."""
    if not isinstance(payload, dict):
        raise ValueError("Runtime 请求必须是对象")
    unexpected = _FORBIDDEN_REQUEST_KEYS.intersection(payload)
    if unexpected:
        raise ValueError(f"Runtime 请求禁止包含命令字段：{sorted(unexpected)}")
    validate_operation(
        str(payload.get("operation", "")),
        str(payload.get("component", "stella")),
    )
    extra = set(payload) - {"operation", "component", "parameters"}
    if extra:
        raise ValueError(f"Runtime 请求包含未知字段：{sorted(extra)}")
    if "parameters" in payload and not isinstance(payload["parameters"], dict):
        raise ValueError("Runtime parameters 必须是对象")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def read_manifest() -> dict[str, Any]:
    value = _read_json(manifest_path())
    if value is None:
        return default_manifest()
    try:
        validate_manifest(value)
    except ValueError:
        return default_manifest()
    return value


def read_state() -> dict[str, Any]:
    value = _read_json(state_path())
    if value is None:
        return default_state()
    try:
        validate_state_payload(value)
    except ValueError:
        return default_state()
    return redact_value(value)


def validate_operation(operation: str, component: str = "stella") -> None:
    if operation not in OPERATIONS:
        raise ValueError(f"不支持的 Runtime 操作：{operation}")
    if component not in COMPONENTS:
        raise ValueError(f"不支持的 Runtime 组件：{component}")


def validate_state(state: str) -> None:
    if state not in STATES:
        raise ValueError(f"不支持的 Runtime 状态：{state}")


def write_manifest(payload: dict[str, Any] | None = None) -> None:
    value = payload or default_manifest()
    validate_manifest(value)
    _atomic_write(manifest_path(), redact_value(value))


def update_component(
    component: str,
    state: str,
    *,
    pid: int | None = None,
    endpoint: str | None = None,
    error: str | None = None,
    desired: str | None = None,
) -> str | None:
    """更新一个组件状态；失败返回诊断文本而不阻断 Bot 生命周期。"""
    try:
        validate_state(state)
        if component not in COMPONENTS:
            raise ValueError(f"不支持的 Runtime 组件：{component}")
        payload = read_state()
        components = payload.setdefault("components", {})
        current = components.setdefault(component, {})
        current["state"] = state
        if pid is not None:
            current["pid"] = pid
        elif state in ("stopped", "disabled"):
            current.pop("pid", None)
        if endpoint is not None:
            current["endpoint"] = endpoint
        if error:
            current["error"] = structured_error(
                "component_failed", str(error), component=component
            )
        else:
            current.pop("error", None)
        if desired is not None:
            payload["desired"] = desired
        payload["schema_version"] = SCHEMA_VERSION
        payload["instance_id"] = INSTANCE_ID
        payload["updated_at"] = _now()
        _atomic_write(state_path(), payload)
    except (OSError, ValueError, TypeError) as exc:
        return str(exc)
    return None


def snapshot() -> dict[str, Any]:
    """返回供 status API/CLI 消费的统一状态，不泄露 secret。"""
    manifest = read_manifest()
    state = read_state()
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": INSTANCE_ID,
        "runtime_dir": str(INSTANCE_RUNTIME_DIR),
        "manifest_path": str(manifest_path()),
        "state_path": str(state_path()),
        "desired": state.get("desired", "stopped"),
        "updated_at": state.get("updated_at"),
        "components": state.get("components", {}),
        "manifest": {
            "components": {
                name: {
                    "enabled": bool(spec.get("enabled", False)),
                    "dependencies": list(spec.get("dependencies") or []),
                    "health": spec.get("health") or {},
                    "logs": spec.get("logs") or {},
                }
                for name, spec in (manifest.get("components") or {}).items()
                if name in COMPONENTS and isinstance(spec, dict)
            }
        },
    }


def sync_stella_status(
    *,
    alive: bool,
    api_reachable: bool,
    pid: int | None = None,
    error: str | None = None,
) -> None:
    """把旧进程观测映射到 Runtime 状态；不成为第二个进程 owner。"""
    if not alive:
        state = "stopped"
    elif api_reachable:
        state = "healthy"
    else:
        state = "starting"
    update_component(
        "stella",
        state,
        pid=pid,
        error=error,
        desired="running" if alive else "stopped",
    )


def sync_onebot_status(link: dict[str, Any] | None) -> None:
    """Map OneBot link facts to Runtime state without restarting Stella."""
    if not link or not link.get("enabled", False):
        update_component("onebot", "disabled", desired="stopped")
        return
    state = "healthy" if link.get("healthy") else "degraded"
    update_component("onebot", state, desired="running")


def runtime_status_json() -> str:
    return json.dumps(snapshot(), ensure_ascii=False, indent=2)


def _captured_call(callback: Any) -> tuple[Any, str]:
    """Run a legacy owner call without contaminating the JSON operation output."""
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(output):
        value = callback()
    return value, output.getvalue().strip()


def execute_operation(
    operation: str,
    component: str = "stella",
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one Runtime operation through the current compatibility owner.

    The dispatcher is deliberately small: it provides the stable control-plane
    envelope now, while the Rust supervisor can replace the owner behind this
    seam without changing CLI or GUI callers.
    """
    request = {
        "operation": operation,
        "component": component,
        "parameters": parameters or {},
    }
    validate_operation_request(request)
    force = request["parameters"].get("force", False)
    if not isinstance(force, bool):
        raise ValueError("Runtime parameters.force 必须是布尔值")
    if component != "stella" and operation in {"start", "stop", "restart", "logs"}:
        return {
            "ok": False,
            "operation": operation,
            "component": component,
            "error": structured_error(
                "unsupported_component_operation",
                f"组件 {component} 当前没有可用的 Python compatibility owner",
                component=component,
            ),
        }

    from . import checks, probe, process, report

    if operation == "status":
        return {
            "ok": True,
            "operation": operation,
            "component": component,
            "data": redact_value(process.status()),
        }

    if operation == "doctor":
        facts = probe.collect()
        results = checks.run_all(facts)
        data = json.loads(report.to_json(results, facts))
        return {
            "ok": not report.has_blocking(results),
            "operation": operation,
            "component": component,
            "data": redact_value(data),
            "exit_code": 0 if not report.has_blocking(results) else 1,
        }

    if operation == "start":
        facts = probe.collect()
        results = checks.run_all(facts)
        if report.has_blocking(results) and not force:
            data = json.loads(report.to_json(results, facts))
            return redact_value({
                "ok": False,
                "operation": operation,
                "component": component,
                "exit_code": 1,
                "data": data,
                "error": structured_error(
                    "component_failed",
                    "存在阻塞性问题；确认原因后可使用 force 参数继续启动",
                    component=component,
                ),
            })

    if operation == "logs":
        tail = parameters.get("tail", 100) if parameters else 100
        if not isinstance(tail, int) or isinstance(tail, bool) or not 1 <= tail <= 2000:
            raise ValueError("logs.tail 必须是 1 到 2000 的整数")
        path = process.LOG_FILE
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-tail:] if path.exists() else []
        except OSError as exc:
            return {
                "ok": False,
                "operation": operation,
                "component": component,
                "error": structured_error("operation_failed", str(exc), path=str(path)),
            }
        return {
            "ok": True,
            "operation": operation,
            "component": component,
            "data": {"path": str(path), "lines": lines},
        }

    if operation == "start":
        value, output = _captured_call(process.start_detached)
        ok = value == 0
    elif operation == "stop":
        value, output = _captured_call(process.stop)
        ok = value is True
    elif operation == "restart":
        stopped, stop_output = _captured_call(process.stop)
        if stopped is True:
            value, start_output = _captured_call(process.start_detached)
            output = "\n".join(part for part in (stop_output, start_output) if part)
            ok = value == 0
        else:
            output = stop_output
            ok = False
    else:
        raise ValueError(f"不支持的 Runtime 操作：{operation}")

    result: dict[str, Any] = {
        "ok": ok,
        "operation": operation,
        "component": component,
        "exit_code": 0 if ok else 1,
        "data": snapshot(),
    }
    if output:
        result["message"] = output[-2000:]
    if not ok:
        result["error"] = structured_error(
            "operation_failed",
            output or f"Runtime 操作失败：{operation}",
            operation=operation,
            component=component,
        )
    return redact_value(result)


__all__ = [
    "COMPONENTS",
    "ERROR_CODES",
    "MANIFEST_FILENAME",
    "OPERATIONS",
    "SCHEMA_VERSION",
    "STATES",
    "STATE_FILENAME",
    "default_manifest",
    "default_state",
    "execute_operation",
    "read_manifest",
    "read_state",
    "redact_value",
    "runtime_status_json",
    "snapshot",
    "structured_error",
    "sync_onebot_status",
    "sync_stella_status",
    "update_component",
    "validate_manifest",
    "validate_operation",
    "validate_operation_request",
    "validate_state",
    "validate_state_payload",
    "write_manifest",
]
