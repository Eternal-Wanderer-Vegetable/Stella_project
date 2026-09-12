# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Pinned NapCat package handling and deliberately manual login status.

This module never logs in to QQ and never interprets, captures, or forwards a
QR code. It manages only package provenance, isolated directories, and the
small status vocabulary consumed by Runtime/CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

STATES = (
    "not_installed",
    "not_logged_in",
    "qr_waiting",
    "connected",
    "expired",
)
NAPCAT_ID = "napcat"
_HEX = set("0123456789abcdef")


class NapCatError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text or "/" in text or "\\" in text or text in {".", ".."}:
        raise NapCatError("invalid_manifest", f"{label} 无效")
    return text


def validate_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NapCatError("invalid_manifest", "NapCat manifest 必须是对象")
    if payload.get("id") != NAPCAT_ID:
        raise NapCatError("invalid_manifest", "NapCat manifest id 必须是 napcat")
    version = _safe_name(payload.get("version"), "version")
    digest = str(payload.get("digest", "")).lower().strip()
    if len(digest) != 64 or any(char not in _HEX for char in digest):
        raise NapCatError("invalid_manifest", "NapCat digest 必须是 SHA-256")
    for key in ("source", "license", "sbom", "platform"):
        if not str(payload.get(key, "")).strip():
            raise NapCatError("provenance_missing", f"NapCat manifest 缺少 {key}")
    if "latest" in str(payload.get("source", "")).lower():
        raise NapCatError("unpinned_source", "NapCat source 不得使用 latest")
    return {
        "id": NAPCAT_ID,
        "version": version,
        "digest": digest,
        "source": str(payload["source"]).strip(),
        "license": str(payload["license"]).strip(),
        "sbom": str(payload["sbom"]).strip(),
        "platform": str(payload["platform"]).strip(),
        "onebot_protocol": str(payload.get("onebot_protocol", "11")).strip(),
    }


def _paths(data_root: Path) -> dict[str, Path]:
    root = Path(data_root).expanduser().resolve()
    return {
        "root": root,
        "packages": root / ".stella" / "packages" / "onebot" / NAPCAT_ID,
        "staging": root / ".stella" / "napcat-staging",
        "metadata": root / ".stella" / "napcat.json",
        "qq": root / "napcat" / "QQ",
        "config": root / "napcat" / "config",
    }


def _safe_member(name: str) -> Path:
    normalized = name.replace("\\", "/")
    path = Path(normalized)
    if (
        path.is_absolute()
        or ".." in path.parts
        or normalized.startswith("/")
        or (len(normalized) >= 2 and normalized[1] == ":")
    ):
        raise NapCatError("unsafe_archive", f"NapCat archive 路径穿越：{name}")
    return path


def _extract_archive(archive: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                relative = _safe_member(info.filename)
                if not relative.parts:
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise NapCatError("unsafe_archive", "NapCat archive 不得包含符号链接")
                target = destination / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise NapCatError("invalid_archive", f"NapCat archive 不是有效 ZIP：{archive}") from exc


def install_archive(
    archive: Path,
    manifest: dict[str, Any],
    data_root: Path,
) -> dict[str, Any]:
    """Verify and atomically install NapCat without touching QQ data."""
    metadata = validate_manifest(manifest)
    archive = Path(archive).expanduser().resolve()
    if not archive.is_file():
        raise NapCatError("source_missing", f"NapCat archive 不存在：{archive}")
    if sha256(archive) != metadata["digest"]:
        raise NapCatError("checksum_mismatch", "NapCat archive digest 不匹配")
    paths = _paths(data_root)
    target = paths["packages"] / metadata["version"]
    if target.exists():
        raise NapCatError("already_installed", f"NapCat 版本已安装：{metadata['version']}")
    paths["staging"].mkdir(parents=True, exist_ok=True)
    stage = paths["staging"] / uuid.uuid4().hex
    previous_metadata = (
        paths["metadata"].read_bytes() if paths["metadata"].is_file() else None
    )
    activated = False
    try:
        _extract_archive(archive, stage)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            **metadata,
            "install_path": str(target),
            "qq_data_path": str(paths["qq"]),
            "config_path": str(paths["config"]),
            "login": {"unattended": False, "status": "not_logged_in"},
        }
        fd, temporary = tempfile.mkstemp(
            prefix=".napcat-", suffix=".json", dir=paths["metadata"].parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            stage.replace(target)
            activated = True
            Path(temporary).replace(paths["metadata"])
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
    except NapCatError:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    except OSError as exc:
        if activated:
            shutil.rmtree(target, ignore_errors=True)
            if previous_metadata is None:
                paths["metadata"].unlink(missing_ok=True)
            else:
                paths["metadata"].write_bytes(previous_metadata)
        shutil.rmtree(stage, ignore_errors=True)
        raise NapCatError("install_failed", str(exc)) from exc
    return payload


def status(data_root: Path, observed: str | None = None) -> dict[str, Any]:
    paths = _paths(data_root)
    if not paths["metadata"].is_file():
        return {"state": "not_installed", "unattended": False}
    try:
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        validate_manifest(metadata)
    except (OSError, ValueError, TypeError, NapCatError):
        return {"state": "not_installed", "unattended": False}
    state = observed if observed in STATES[1:] else metadata.get("login", {}).get("status")
    if state not in STATES[1:]:
        state = "not_logged_in"
    return {
        "state": state,
        "version": metadata["version"],
        "platform": metadata["platform"],
        "unattended": False,
        "qq_data_path": str(paths["qq"]),
        "config_path": str(paths["config"]),
    }


def uninstall(data_root: Path, version: str | None = None) -> dict[str, Any]:
    paths = _paths(data_root)
    if not paths["metadata"].is_file():
        return {"removed": False, "state": "not_installed", "qq_data_removed": False}
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    selected = version or metadata.get("version")
    target = paths["packages"] / _safe_name(selected, "version")
    shutil.rmtree(target, ignore_errors=False)
    paths["metadata"].unlink(missing_ok=True)
    return {
        "removed": True,
        "version": selected,
        "state": "not_installed",
        "qq_data_removed": False,
    }


__all__ = [
    "NAPCAT_ID",
    "STATES",
    "NapCatError",
    "install_archive",
    "sha256",
    "status",
    "uninstall",
    "validate_manifest",
]
