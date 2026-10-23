# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Load the narrow control-plane settings from one immutable revision."""

from __future__ import annotations

import ipaddress
import os
import socket
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from stella_bootstrap.config import load_revision
from stella_bootstrap.identity import INSTANCE_ID_PATTERN, resolve_instance_id
from stella_contracts.config import ConfigRevision


class CoronaBootstrapError(RuntimeError):
    """The control plane cannot safely select its instance or listener."""


@dataclass(frozen=True)
class CoronaBootstrap:
    revision: ConfigRevision
    revision_file: Path
    project_root: Path
    stella_home: Path
    instance_id: str
    controller_boot_id: str
    log_dir: Path
    webui_enabled: bool
    serve_dist: bool
    public_host: str
    public_port: int
    internal_host: str
    internal_port: int
    token_ttl_hours: int
    login_ratelimit_per_min: int
    recovery_mode: bool


def prepare_corona_bootstrap(
    environ: Mapping[str, str] | None = None,
    *,
    project_root: Path | None = None,
) -> CoronaBootstrap:
    """Resolve Corona's control subset without importing ``config`` or plugins."""
    raw = dict(os.environ if environ is None else environ)
    raw_revision = raw.get("STELLA_CONFIG_REVISION_FILE", "").strip()
    if not raw_revision:
        raise CoronaBootstrapError("STELLA_CONFIG_REVISION_FILE is required")
    revision_file = Path(raw_revision).expanduser()
    if not revision_file.is_absolute():
        raise CoronaBootstrapError("configuration revision path must be absolute")
    try:
        revision = load_revision(revision_file)
    except Exception as exc:
        raise CoronaBootstrapError("configuration revision could not be loaded") from exc

    project = (project_root or Path(__file__).resolve().parents[1]).expanduser().resolve()
    revision_project = Path(revision.project_root).expanduser().resolve()
    if revision_project != project:
        raise CoronaBootstrapError("configuration revision belongs to another project")
    if Path.cwd().resolve() != project:
        raise CoronaBootstrapError("Corona must start with PROJECT_ROOT as cwd")

    instance_id = raw.get("STELLA_INSTANCE_ID", "").strip()
    if not instance_id:
        instance_id = resolve_instance_id(project, environ={})
    if not INSTANCE_ID_PATTERN.fullmatch(instance_id):
        raise CoronaBootstrapError("managed instance id is invalid")
    if revision_file.parents[2].name != instance_id:
        raise CoronaBootstrapError("configuration revision belongs to another instance")

    values = revision.values
    recovery_mode = raw.get("STELLA_CORONA_RECOVERY", "").strip() == "1"
    try:
        webui_enabled = _boolean(values.get("WEBUI_ENABLED", "true"), "WEBUI_ENABLED")
        serve_dist = _boolean(values.get("WEBUI_SERVE_DIST", "true"), "WEBUI_SERVE_DIST")
        public_host = _loopback_or_bind_address(values.get("HOST", "127.0.0.1"))
        public_port = _port(values.get("PORT", "8080"), "PORT")
    except CoronaBootstrapError:
        if not recovery_mode:
            raise
        webui_enabled = True
        serve_dist = True
        public_host = "127.0.0.1"
        public_port = _port(raw.get("STELLA_CORONA_RECOVERY_PORT", "18765"), "recovery port")

    if not webui_enabled:
        # The browser management surface stays disabled, but local control
        # remains available until the capability API lands in CN04.
        public_host = "127.0.0.1"

    home = Path(revision.stella_home).expanduser().resolve()
    raw_log_dir = values.get("LOG_DIR", str(home / "logs"))
    log_dir = Path(raw_log_dir).expanduser()
    if not log_dir.is_absolute():
        log_dir = home / log_dir
    token_ttl_hours = _positive_integer(values.get("WEBUI_TOKEN_TTL_HOURS", "168"), "token TTL")
    login_limit = _positive_integer(
        values.get("WEBUI_LOGIN_RATELIMIT_PER_MIN", "5"), "login rate limit"
    )

    return CoronaBootstrap(
        revision=revision,
        revision_file=revision_file.resolve(),
        project_root=project,
        stella_home=home,
        instance_id=instance_id,
        controller_boot_id=uuid.uuid4().hex,
        log_dir=log_dir.resolve(),
        webui_enabled=webui_enabled,
        serve_dist=serve_dist,
        public_host=public_host,
        public_port=public_port,
        internal_host="127.0.0.1",
        internal_port=_free_loopback_port(),
        token_ttl_hours=token_ttl_hours,
        login_ratelimit_per_min=login_limit,
        recovery_mode=recovery_mode,
    )


def _boolean(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        raise CoronaBootstrapError(f"{key} must be a boolean")
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise CoronaBootstrapError(f"{key} must be a boolean")


def _loopback_or_bind_address(value: object) -> str:
    if not isinstance(value, str):
        raise CoronaBootstrapError("HOST must be an IP address")
    try:
        return ipaddress.ip_address(value.strip()).compressed
    except ValueError as exc:
        raise CoronaBootstrapError("HOST must be an IP address") from exc


def _port(value: object, key: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise CoronaBootstrapError(f"{key} must be a port number") from exc
    if isinstance(value, bool) or not 1 <= port <= 65535:
        raise CoronaBootstrapError(f"{key} must be a port number")
    return port


def _positive_integer(value: object, key: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CoronaBootstrapError(f"{key} must be a positive integer") from exc
    if isinstance(value, bool) or result < 1:
        raise CoronaBootstrapError(f"{key} must be a positive integer")
    return result


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
