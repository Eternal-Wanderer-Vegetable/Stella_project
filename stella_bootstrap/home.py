# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Pure path policy for resolving the user-data directory.

Resolution order remains explicit ``STELLA_HOME``, portable ``StellaData``, the
legacy in-project layout, the machine pointer, then a sibling ``StellaData``.
The resolver does not read dotenv and does not import ``config``; a management
process can identify its data root before importing legacy application settings.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DIR_NAME = "StellaData"
POINTER_NAME = "home.txt"
ENV_VAR = "STELLA_HOME"
LEGACY_MARKERS = (".env", "memory/agent_memory.db", "deploy.answers.toml")
__all__ = [
    "DEFAULT_DIR_NAME",
    "ENV_VAR",
    "LEGACY_MARKERS",
    "POINTER_NAME",
    "HomeResolution",
    "looks_used",
    "pointer_path",
    "read_pointer",
    "resolve",
    "write_pointer",
]


@dataclass(frozen=True)
class HomeResolution:
    path: Path
    source: str


def _environment(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def pointer_path(environ: Mapping[str, str] | None = None) -> Path:
    env = _environment(environ)
    local = env.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Stella" / POINTER_NAME
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "stella" / POINTER_NAME


def read_pointer(environ: Mapping[str, str] | None = None) -> Path | None:
    path = pointer_path(environ)
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    candidate = Path(text)
    return candidate if candidate.is_dir() else None


def write_pointer(home: Path, environ: Mapping[str, str] | None = None) -> str | None:
    path = pointer_path(environ)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(home.resolve()) + "\n", encoding="utf-8")
    except OSError as exc:
        return f"指针文件 {path} 写入失败: {exc}"
    return None


def looks_used(directory: Path) -> bool:
    return any((directory / marker).exists() for marker in LEGACY_MARKERS)


def resolve(
    install_root: Path,
    *,
    create: bool = False,
    environ: Mapping[str, str] | None = None,
) -> HomeResolution:
    try:
        return _resolve(install_root, create=create, environ=environ)
    except Exception:
        return HomeResolution(path=install_root, source="定位失败，回退到安装目录")


def _resolve(
    install_root: Path,
    *,
    create: bool,
    environ: Mapping[str, str] | None = None,
) -> HomeResolution:
    env = _environment(environ)
    from_env = env.get(ENV_VAR, "").strip()
    if from_env:
        home = Path(from_env).expanduser()
        if create:
            _ensure(home)
        return HomeResolution(path=home, source=f"环境变量 {ENV_VAR}")

    inside = install_root / DEFAULT_DIR_NAME
    if inside.is_dir():
        return HomeResolution(path=inside.resolve(), source="便携模式：安装目录内的 StellaData")

    if looks_used(install_root):
        return HomeResolution(path=install_root, source="旧布局：数据在安装目录内")

    pointed = read_pointer(env)
    if pointed is not None:
        return HomeResolution(path=pointed, source=f"指针文件 {pointer_path(env)}")

    home = (install_root.parent / DEFAULT_DIR_NAME).resolve()
    if create:
        _ensure(home)
        write_pointer(home, env)
    return HomeResolution(path=home, source=f"新建数据目录 {home}")


def _ensure(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
