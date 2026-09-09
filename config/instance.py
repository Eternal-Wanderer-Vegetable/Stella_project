# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Stella 实例身份与进程控制命名空间。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INSTANCE_ID_ENV = "STELLA_INSTANCE_ID"
LAUNCH_TOKEN_ENV = "STELLA_LAUNCH_TOKEN"
INSTANCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def normalize_project_root(project_root: Path) -> str:
    """返回跨 Windows 大小写与路径分隔符稳定的程序目录字符串。"""
    value = str(project_root.expanduser().resolve())
    return value.casefold() if os.name == "nt" else value


def resolve_instance_id(project_root: Path) -> str:
    """读取显式实例 ID，未设置时从程序目录生成稳定 ID。"""
    explicit = os.environ.get(INSTANCE_ID_ENV, "").strip()
    if explicit and INSTANCE_ID_PATTERN.fullmatch(explicit):
        return explicit
    digest = hashlib.sha256(normalize_project_root(project_root).encode("utf-8")).hexdigest()
    return f"root-{digest[:16]}"


def runtime_dir(stella_home: Path, instance_id: str) -> Path:
    """返回实例专属的运行时控制目录。"""
    return stella_home / ".stella" / "instances" / instance_id


def new_launch_token() -> str:
    return uuid.uuid4().hex


def launch_token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def manifest_path(stella_home: Path, instance_id: str) -> Path:
    return runtime_dir(stella_home, instance_id) / "ownership.json"


def pid_path(stella_home: Path, instance_id: str) -> Path:
    return runtime_dir(stella_home, instance_id) / "stella.pid"


def stop_sentinel_path(stella_home: Path, instance_id: str) -> Path:
    return runtime_dir(stella_home, instance_id) / "stop-request.json"


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 ownership manifest，避免 stop 读到半份 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def manifest_for(
    *,
    instance_id: str,
    project_root: Path,
    pid: int,
    launch_token: str,
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "project_root": str(project_root.resolve()),
        "pid": pid,
        "launch_token": launch_token,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
