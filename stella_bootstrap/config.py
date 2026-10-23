# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Build, persist, and load isolated immutable configuration revisions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

from stella_contracts.config import ConfigRevision, ConfigRevisionError

from .env import capture_external_environment, parse_dotenv
from .env_schema import build_schema
from .identity import INSTANCE_ID_PATTERN, runtime_dir

CONFIG_REVISION_FILE_ENV = "STELLA_CONFIG_REVISION_FILE"
RESERVED_ENV_KEYS = frozenset(
    {
        "STELLA_HOME",
        "STELLA_INSTANCE_ID",
        "STELLA_LAUNCH_TOKEN",
        "STELLA_STOP_SENTINEL",
        "STELLA_CONFIG_REVISION_FILE",
        "STELLA_GENERATION_ID",
        "STELLA_CONTROLLER_BOOT_ID",
        "STELLA_INTERNAL_HOST",
        "STELLA_INTERNAL_PORT",
    }
)
PROCESS_ENV_KEYS = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "CONDA_PREFIX",
        "DYLD_LIBRARY_PATH",
        "HOME",
        "HOSTNAME",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "LOCALAPPDATA",
        "OS",
        "PATH",
        "PATHEXT",
        "PYTHONHOME",
        "PYTHONPATH",
        "SHELL",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USER",
        "USERNAME",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
        "XDG_CONFIG_HOME",
    }
)


class ConfigBuildError(ConfigRevisionError):
    """A source file or known configuration value cannot form a safe revision."""


def build_config_revision(
    *,
    project_root: Path,
    stella_home: Path,
    external_environment: Mapping[str, str] | None = None,
    settings_path: Path | None = None,
    created_at: str | None = None,
    revision_id: str | None = None,
) -> ConfigRevision:
    """Resolve legacy-compatible source precedence into one immutable value set.

    Order is defaults (still supplied by ``config.settings``) < data ``.env`` <
    the pre-import external environment < the selected profile overlay. Per-run
    identity and control values are excluded from user configuration values.
    """
    project = project_root.expanduser().resolve()
    home = stella_home.expanduser().resolve()
    captured = capture_external_environment(external_environment)
    external = {
        _canonical_key(key): value
        for key, value in captured.items()
        if _is_env_key(key)
        and key.upper() not in RESERVED_ENV_KEYS
        and key.upper() not in PROCESS_ENV_KEYS
    }

    base_path = home / ".env"
    base_text, base_digest = _read_source(base_path)
    parsed_base = parse_dotenv(base_text, environment=captured, override=False)
    base_values = {_canonical_key(key): value for key, value in parsed_base.items()}
    values = {
        key: value
        for key, value in base_values.items()
        if key.upper() not in RESERVED_ENV_KEYS
    }
    sources = dict.fromkeys(values, "data_env")

    for key, value in external.items():
        values[key] = value
        sources[key] = "external_environment"

    environment = values.get("ENVIRONMENT", "").strip().lower()
    overlay_name = _profile_name(environment)
    digests: dict[str, str] = {}
    if base_digest is not None:
        digests[".env"] = base_digest
    if overlay_name:
        overlay_path = home / overlay_name
        overlay_text, overlay_digest = _read_source(overlay_path)
        if overlay_digest is not None:
            digests[overlay_name] = overlay_digest
        overlay_values = parse_dotenv(overlay_text, environment=values, override=True)
        source_kind = "dev_overlay" if overlay_name == ".env.dev" else "prod_overlay"
        for key, value in overlay_values.items():
            if key.upper() in RESERVED_ENV_KEYS:
                continue
            key = _canonical_key(key)
            values[key] = value
            sources[key] = source_kind

    external_overrides = tuple(
        sorted(
            key
            for key in external
            if key in base_values and sources.get(key) == "external_environment"
        )
    )

    schema_source = settings_path or project / "config" / "settings.py"
    try:
        schema = build_schema(schema_source)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise ConfigBuildError("could not read the active configuration schema") from exc
    _validate_known_values(values, schema)

    return ConfigRevision(
        revision_id=revision_id or secrets.token_urlsafe(24),
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        project_root=str(project),
        stella_home=str(home),
        environment=environment,
        values=values,
        sources=sources,
        source_digests=digests,
        external_override_keys=external_overrides,
    )


def _is_env_key(key: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key))


def _canonical_key(key: str) -> str:
    return key.upper() if os.name == "nt" else key


def _profile_name(environment: str) -> str | None:
    if environment in {"dev", "development"}:
        return ".env.dev"
    if environment in {"prod", "production"}:
        return ".env.prod"
    return None


def _read_source(path: Path) -> tuple[str, str | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "", None
    except OSError as exc:
        raise ConfigBuildError(f"could not read configuration source {path.name}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigBuildError(f"configuration source {path.name} is not UTF-8") from exc
    return text, hashlib.sha256(raw).hexdigest()


def _validate_known_values(values: Mapping[str, str], schema: dict) -> None:
    for field in schema.get("fields", ()):
        key = field["key"]
        if key not in values:
            continue
        raw = values[key]
        value = raw.strip()
        if field.get("inherits") and not value:
            continue
        kind = field["type"]
        try:
            if kind == "int" and value:
                int(value)
            elif kind == "float" and value:
                parsed = float(value)
                if not math.isfinite(parsed):
                    raise ValueError("not finite")
            elif kind == "bool" and value:
                normalized = value.strip("\"'").lower()
                if normalized not in {"true", "false", "yes", "no", "1", "0"}:
                    raise ValueError("expected a boolean")
            elif kind == "int_set" and value:
                for fragment in value.replace("，", ",").split(","):
                    fragment = fragment.strip()
                    if fragment:
                        int(fragment)
            elif kind == "choice" and value:
                choices = field.get("choices", ())
                if choices and value.lower() not in {choice.lower() for choice in choices}:
                    raise ValueError("value is outside the declared choices")
            elif kind == "path" and value:
                Path(value).expanduser().resolve()
        except (TypeError, ValueError, OSError) as exc:
            raise ConfigBuildError(f"invalid value for configuration key {key}") from exc


def revision_path(stella_home: Path, instance_id: str, revision_id: str) -> Path:
    if not INSTANCE_ID_PATTERN.fullmatch(instance_id):
        raise ConfigRevisionError("invalid instance id")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", revision_id):
        raise ConfigRevisionError("invalid configuration revision id")
    return runtime_dir(stella_home, instance_id) / "revisions" / revision_id / "config.json"


def write_revision(
    stella_home: Path, instance_id: str, revision: ConfigRevision
) -> Path:
    """Create one private, write-once revision file and return its absolute path."""
    home = stella_home.expanduser().resolve()
    if Path(revision.stella_home) != home:
        raise ConfigRevisionError("revision data root does not match destination")
    path = revision_path(home, instance_id, revision.revision_id)
    directory = path.parent
    if directory.exists():
        raise FileExistsError("configuration revision id already exists")
    _create_private_tree(home, directory)
    payload = json.dumps(
        revision.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=directory)
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if temp_path.exists():
            _check_private_file(temp_path)
        temp_path.replace(path)
        if os.name != "nt":
            path.chmod(0o600)
            directory_fd = os.open(
                directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        _check_private_file(path)
        return path
    except Exception:
        with suppress(OSError):
            temp_path.unlink(missing_ok=True)
        raise


def load_revision(path: Path) -> ConfigRevision:
    """Load and validate a private revision without reading dotenv or process values."""
    file_path = path.expanduser()
    if not file_path.is_absolute():
        raise ConfigRevisionError("configuration revision path must be absolute")
    if file_path.name != "config.json":
        raise ConfigRevisionError("configuration revision filename is invalid")
    _check_private_file(file_path)
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigRevisionError("configuration revision file is unreadable") from exc
    revision = ConfigRevision.from_dict(payload)
    if revision.revision_id != file_path.parent.name:
        raise ConfigRevisionError("configuration revision id does not match its path")
    if Path(revision.stella_home) != file_path.parents[5].resolve():
        raise ConfigRevisionError("configuration revision data root does not match its path")
    return revision


def get_managed_revision(
    environ: Mapping[str, str] | None = None,
) -> ConfigRevision | None:
    """Load the explicit managed revision; an invalid marker fails closed."""
    env = os.environ if environ is None else environ
    configured_path = env.get(CONFIG_REVISION_FILE_ENV, "").strip()
    if not configured_path:
        return None
    return load_revision(Path(configured_path))


def _create_private_tree(home: Path, revision_directory: Path) -> None:
    protected = [
        home / ".stella",
        home / ".stella" / "instances",
        home / ".stella" / "instances" / revision_directory.parents[1].name,
        home / ".stella" / "instances" / revision_directory.parents[1].name / "revisions",
        revision_directory,
    ]
    for directory in protected:
        if directory.is_symlink():
            raise ConfigRevisionError("configuration revision path contains a symlink")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "nt":
            _set_windows_private_acl(directory, is_directory=True)
        else:
            directory.chmod(0o700)
            if stat.S_IMODE(directory.stat().st_mode) & 0o077:
                raise ConfigRevisionError("configuration revision directory is not private")


def _check_private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ConfigRevisionError("configuration revision file is missing or unsafe")
    parents = path.parents
    if (
        len(parents) < 6
        or parents[1].name != "revisions"
        or parents[3].name != "instances"
        or parents[4].name != ".stella"
    ):
        raise ConfigRevisionError("configuration revision is outside the private revision store")
    if os.name == "nt":
        _check_windows_private_acl(path)
        for directory in parents[:5]:
            _check_windows_private_acl(directory)
        return
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ConfigRevisionError("configuration revision file permissions are too broad")
    for directory in parents[:5]:
        if directory.is_symlink() or not directory.is_dir():
            raise ConfigRevisionError("configuration revision directory is missing or unsafe")
        if stat.S_IMODE(directory.stat().st_mode) & 0o077:
            raise ConfigRevisionError("configuration revision directory permissions are too broad")


def _current_windows_sid() -> str:
    whoami = shutil.which("whoami.exe") or shutil.which("whoami")
    if not whoami:
        raise ConfigRevisionError("cannot identify the current Windows account")
    try:
        result = subprocess.run(
            [whoami, "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigRevisionError("cannot identify the current Windows account") from exc
    match = re.search(r"S-1-(?:\d+-)+\d+", result.stdout)
    if not match:
        raise ConfigRevisionError("cannot identify the current Windows account")
    return match.group(0)


def _set_windows_private_acl(path: Path, *, is_directory: bool) -> None:
    icacls = shutil.which("icacls.exe") or shutil.which("icacls")
    if not icacls:
        raise ConfigRevisionError("icacls is required to protect configuration revisions")
    sid = _current_windows_sid()
    grant = f"*{sid}:(OI)(CI)F" if is_directory else f"*{sid}:F"
    try:
        subprocess.run(
            [icacls, str(path), "/inheritance:r", "/grant:r", grant, "/Q"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigRevisionError("could not restrict configuration revision ACL") from exc


def _check_windows_private_acl(path: Path) -> None:
    icacls = shutil.which("icacls.exe") or shutil.which("icacls")
    if not icacls:
        raise ConfigRevisionError("icacls is required to validate configuration ACLs")
    sid = _current_windows_sid()
    try:
        result = subprocess.run(
            [icacls, str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigRevisionError("could not validate configuration revision ACL") from exc
    entries = [line.strip() for line in result.stdout.splitlines() if re.search(r":\(", line)]
    if not entries or any(sid not in entry for entry in entries):
        raise ConfigRevisionError("configuration revision ACL includes another account")
    if not any(sid in entry and "(F)" in entry for entry in entries):
        raise ConfigRevisionError("configuration revision ACL lacks current-user access")
