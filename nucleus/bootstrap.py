# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Prepare a managed Nucleus from one immutable configuration revision."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from stella_bootstrap.config import PROCESS_ENV_KEYS, RESERVED_ENV_KEYS, load_revision
from stella_bootstrap.identity import (
    INSTANCE_ID_PATTERN,
    resolve_instance_id,
    runtime_dir,
)
from stella_contracts.config import ConfigRevision

_CONTROL_ENV_KEYS = frozenset(
    {
        "STELLA_MANAGED_CORE",
        "STELLA_CONFIG_REVISION_FILE",
        "STELLA_HOME",
        "STELLA_INSTANCE_ID",
        "STELLA_LAUNCH_TOKEN",
        "STELLA_STOP_SENTINEL",
        "STELLA_GENERATION_ID",
        "STELLA_CONTROLLER_BOOT_ID",
        "STELLA_INTERNAL_HOST",
        "STELLA_INTERNAL_PORT",
    }
)
_PYTHON_PROCESS_ENV_KEYS = frozenset(
    {
        "PYTHONIOENCODING",
        "PYTHONNOUSERSITE",
        "PYTHONUNBUFFERED",
        "PYTHONUTF8",
    }
)
_OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_LAUNCH_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class ManagedBootstrapError(RuntimeError):
    """The managed Nucleus launch envelope is invalid or unsafe."""


@dataclass(frozen=True)
class ManagedBootstrap:
    revision: ConfigRevision
    revision_file: Path
    project_root: Path
    stella_home: Path
    instance_id: str
    controller_boot_id: str
    generation_id: str
    launch_token: str
    internal_host: str
    internal_port: int
    stop_sentinel: Path
    database_path: Path


def prepare_managed_environment(
    environ: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> ManagedBootstrap:
    """Validate launch identity, install only revision values, then resolve DB_PATH.

    This function imports ``config.settings`` only after replacing the inherited
    process environment with the immutable revision plus a narrow OS runtime set.
    It does not import plugins, NoneBot, or any business runtime.
    """
    raw = dict(os.environ if environ is None else environ)
    revision_raw = raw.get("STELLA_CONFIG_REVISION_FILE", "").strip()
    if not revision_raw:
        raise ManagedBootstrapError("STELLA_CONFIG_REVISION_FILE is required")
    revision_file = Path(revision_raw).expanduser()
    if not revision_file.is_absolute():
        raise ManagedBootstrapError("configuration revision path must be absolute")
    try:
        revision = load_revision(revision_file)
    except Exception as exc:
        raise ManagedBootstrapError("configuration revision could not be loaded") from exc

    project = (project_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    revision_project = Path(revision.project_root).expanduser().resolve()
    if revision_project != project:
        raise ManagedBootstrapError("configuration revision belongs to another project root")
    if Path.cwd().resolve() != project:
        raise ManagedBootstrapError("managed Nucleus must start with PROJECT_ROOT as cwd")

    instance_id = raw.get("STELLA_INSTANCE_ID", "").strip()
    if not instance_id:
        instance_id = resolve_instance_id(project, environ={})
    if not INSTANCE_ID_PATTERN.fullmatch(instance_id):
        raise ManagedBootstrapError("managed instance id is invalid")
    if revision_file.parents[2].name != instance_id:
        raise ManagedBootstrapError("configuration revision belongs to another instance")

    controller_boot_id = _required_opaque_id(raw, "STELLA_CONTROLLER_BOOT_ID")
    generation_id = _required_opaque_id(raw, "STELLA_GENERATION_ID")
    launch_token = raw.get("STELLA_LAUNCH_TOKEN", "").strip()
    if not _LAUNCH_TOKEN_PATTERN.fullmatch(launch_token):
        raise ManagedBootstrapError("managed launch capability is missing or invalid")

    internal_host = raw.get("STELLA_INTERNAL_HOST", "127.0.0.1").strip()
    try:
        host_address = ipaddress.ip_address(internal_host)
    except ValueError as exc:
        raise ManagedBootstrapError("Nucleus internal host must be a loopback IP") from exc
    if not host_address.is_loopback:
        raise ManagedBootstrapError("Nucleus internal host must be a loopback IP")
    internal_host = host_address.compressed
    raw_port = raw.get("STELLA_INTERNAL_PORT", "18080").strip()
    try:
        internal_port = int(raw_port)
    except ValueError as exc:
        raise ManagedBootstrapError("Nucleus internal port is invalid") from exc
    if not 1 <= internal_port <= 65535:
        raise ManagedBootstrapError("Nucleus internal port is invalid")

    home = Path(revision.stella_home).expanduser().resolve()
    process_values = {
        key: value
        for key, value in raw.items()
        if key.upper() in PROCESS_ENV_KEYS | _PYTHON_PROCESS_ENV_KEYS
    }
    runtime_values = {
        key: value
        for key, value in revision.values.items()
        if key.upper() not in RESERVED_ENV_KEYS
        and key.upper() not in PROCESS_ENV_KEYS
        and key.upper() not in _PYTHON_PROCESS_ENV_KEYS
        and key.upper() not in _CONTROL_ENV_KEYS
    }
    stop_sentinel = (
        runtime_dir(home, instance_id)
        / "generations"
        / generation_id
        / "stop-request.json"
    )
    controls = {
        "STELLA_MANAGED_CORE": "1",
        "STELLA_CONFIG_REVISION_FILE": str(revision_file.resolve()),
        "STELLA_HOME": str(home),
        "STELLA_INSTANCE_ID": instance_id,
        "STELLA_STOP_SENTINEL": str(stop_sentinel),
        "STELLA_GENERATION_ID": generation_id,
        "STELLA_CONTROLLER_BOOT_ID": controller_boot_id,
        "STELLA_INTERNAL_HOST": internal_host,
        "STELLA_INTERNAL_PORT": str(internal_port),
        # NoneBot's settings are deliberately overridden by the controller's
        # loopback address. Other business values still come from the revision.
        "HOST": internal_host,
        "PORT": str(internal_port),
    }
    sanitized = {**process_values, **runtime_values, **controls}
    os.environ.clear()
    os.environ.update(sanitized)

    try:
        from config.settings import DB_PATH
    except Exception as exc:
        raise ManagedBootstrapError("business database path could not be resolved") from exc
    database_path = Path(DB_PATH).expanduser()
    if not database_path.is_absolute():
        database_path = project / database_path
    database_path = database_path.resolve(strict=False)

    return ManagedBootstrap(
        revision=revision,
        revision_file=revision_file.resolve(),
        project_root=project,
        stella_home=home,
        instance_id=instance_id,
        controller_boot_id=controller_boot_id,
        generation_id=generation_id,
        launch_token=launch_token,
        internal_host=internal_host,
        internal_port=internal_port,
        stop_sentinel=stop_sentinel,
        database_path=database_path,
    )


def _required_opaque_id(raw: Mapping[str, str], key: str) -> str:
    value = raw.get(key, "").strip()
    if not _OPAQUE_ID_PATTERN.fullmatch(value):
        raise ManagedBootstrapError(f"{key} is missing or invalid")
    return value
