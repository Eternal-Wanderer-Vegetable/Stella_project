# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""First-run acquisition and activation for OneClick product profiles."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any

from . import acquire, napcat, packages
from .profiles import load_profile

PROGRESS_FILENAME = ".bootstrap-progress"
COMPONENT_ROOT = Path(".stella") / "components"
CATALOG_TIMEOUT = 30


class BootstrapError(ValueError):
    """A user-actionable first-run installation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _progress_path(data_root: Path) -> Path:
    return Path(data_root) / ".stella" / PROGRESS_FILENAME


def _write_progress(
    data_root: Path,
    *,
    profile_id: str,
    state: str,
    current: str | None = None,
    completed: list[str] | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "profile": profile_id,
        "state": state,
        "current": current or "",
        "completed": list(completed or []),
    }
    if error:
        payload["error"] = str(error)[:500]
    _atomic_json(_progress_path(data_root), payload)


def read_progress(data_root: Path) -> dict[str, Any] | None:
    path = _progress_path(data_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_catalog(profile: dict[str, Any], catalog_path: Path | None) -> dict[str, Any]:
    if catalog_path is not None:
        try:
            payload = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise BootstrapError(
                "catalog_read_failed", "无法读取产品 package catalog"
            ) from exc
    else:
        source = str(profile.get("catalog_url", "")).strip()
        if not source.startswith("https://") or "latest" in source.lower():
            raise BootstrapError(
                "invalid_catalog_source", "OneClick catalog 必须是固定 HTTPS URL"
            )
        try:
            with urllib.request.urlopen(source, timeout=CATALOG_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
            raise BootstrapError(
                "catalog_download_failed", "无法下载 OneClick package catalog"
            ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != packages.SCHEMA_VERSION:
        raise BootstrapError("invalid_catalog", "package catalog schema 不受支持")
    if payload.get("profile") not in {None, profile["id"]}:
        raise BootstrapError("catalog_profile_mismatch", "package catalog 与产品 profile 不匹配")
    records = payload.get("packages")
    if not isinstance(records, list):
        raise BootstrapError("invalid_catalog", "package catalog 缺少 packages")
    normalized = []
    for item in records:
        try:
            normalized.append(packages._validate_record(item))
        except packages.PackageError as exc:
            raise BootstrapError("invalid_catalog", exc.message) from exc
    payload["packages"] = normalized
    return payload


def _record(
    catalog: dict[str, Any], package_id: str, kind: str | None = None
) -> dict[str, Any]:
    matches = [
        item
        for item in catalog["packages"]
        if item.get("id") == package_id
        and (kind is None or item.get("kind") == kind)
    ]
    if len(matches) != 1:
        raise BootstrapError(
            "catalog_component_missing",
            f"catalog 中缺少唯一的 {package_id} package",
        )
    return matches[0]


def _download_record(record: dict[str, Any], data_root: Path) -> Path:
    source = str(record.get("source") or "").strip()
    if not source:
        raise BootstrapError("provenance_missing", f"{record['id']} 缺少 source")
    filename = str(record.get("artifact") or Path(record["path"]).name)
    cache = Path(data_root) / ".stella" / "downloads"
    try:
        return acquire.download_verified(
            source,
            cache / filename,
            checksum=str(record["checksum"]),
            size=int(record["size"]) if record.get("size") is not None else None,
        )
    except acquire.AcquireError as exc:
        raise BootstrapError(exc.code, f"{record['id']} 下载失败：{exc.message}") from exc


def _safe_member(name: str) -> Path:
    normalized = name.replace("\\", "/")
    relative = Path(normalized)
    if (
        not normalized
        or relative.is_absolute()
        or ".." in relative.parts
        or normalized.startswith("/")
        or (len(normalized) > 1 and normalized[1] == ":")
    ):
        raise BootstrapError("unsafe_archive", f"组件归档包含不安全路径：{name}")
    return relative


def _install_component(
    record: dict[str, Any], archive: Path, data_root: Path
) -> dict[str, Any]:
    version_root = Path(data_root) / COMPONENT_ROOT / record["id"] / record["version"]
    if version_root.exists():
        return {
            "kind": "component",
            "id": record["id"],
            "version": record["version"],
            "path": version_root.relative_to(data_root).as_posix(),
            "checksum": record["checksum"],
        }
    stage_parent = version_root.parent / ".staging"
    stage_parent.mkdir(parents=True, exist_ok=True)
    stage = stage_parent / uuid.uuid4().hex
    activated = False
    try:
        stage.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                relative = _safe_member(info.filename)
                if not relative.parts:
                    continue
                target = stage / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        version_root.parent.mkdir(parents=True, exist_ok=True)
        stage.replace(version_root)
        activated = True
    except zipfile.BadZipFile as exc:
        raise BootstrapError("invalid_archive", f"{record['id']} 不是有效 ZIP") from exc
    except OSError as exc:
        raise BootstrapError("component_install_failed", f"{record['id']} 安装失败：{exc}") from exc
    finally:
        if not activated:
            shutil.rmtree(stage, ignore_errors=True)
    installed = {
        "kind": "component",
        "id": record["id"],
        "version": record["version"],
        "path": version_root.relative_to(data_root).as_posix(),
        "checksum": record["checksum"],
    }
    for key in (
        "platform",
        "backend",
        "runtime_api",
        "driver_min",
        "abi",
        "license",
        "sbom",
        "source",
        "artifact",
        "status",
    ):
        if record.get(key) is not None:
            installed[key] = record[key]
    return installed


def _register_component(record: dict[str, Any], data_root: Path) -> None:
    registry = packages.read_registry(data_root)
    identity = (record["kind"], record["id"], record["version"])
    registry["packages"] = [
        item
        for item in registry["packages"]
        if (item["kind"], item["id"], item["version"]) != identity
    ]
    registry["packages"].append(record)
    registry["updated_at"] = packages._now()
    packages.write_registry(registry, data_root)


def install_profile(
    profile_id: str,
    data_root: Path,
    *,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Install the remote defaults declared by a OneClick profile."""
    profile = load_profile(profile_id)
    root = Path(data_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if profile["distribution"] != "oneclick":
        _write_progress(root, profile_id=profile_id, state="skipped")
        return {"ok": True, "profile": profile_id, "state": "skipped", "installed": []}

    catalog = _load_catalog(profile, catalog_path)
    component_ids = [
        item for item in profile["included_components"] if item != "python-runtime"
    ]
    items = [(item, _record(catalog, item)) for item in component_ids]
    items.extend(
        (model["id"], _record(catalog, model["id"], "model"))
        for model in profile["default_models"]
    )
    completed: list[str] = []
    installed: list[dict[str, Any]] = []
    _write_progress(root, profile_id=profile_id, state="running", completed=completed)
    try:
        for item_id, record in items:
            _write_progress(
                root,
                profile_id=profile_id,
                state="running",
                current=item_id,
                completed=completed,
            )
            archive = _download_record(record, root)
            if record["kind"] == "onebot" or item_id == "napcat":
                manifest = {
                    "id": "napcat",
                    "version": record["version"],
                    "digest": record["checksum"],
                    "source": record["source"],
                    "license": record["license"],
                    "sbom": record["sbom"],
                    "platform": record["platform"],
                }
                installed.append(
                    acquire.install_napcat(manifest, root, cache_dir=archive.parent)
                )
            elif record["kind"] == "model":
                installed.append(
                    acquire.install_default_embedding(
                        {
                            **record,
                            "filename": archive.name,
                            "sha256": record["checksum"],
                            "role": record.get("model_role", "embedding"),
                        },
                        root,
                        cache_dir=archive.parent,
                    )
                )
            else:
                component = _install_component(record, archive, root)
                _register_component(component, root)
                installed.append(component)
            completed.append(item_id)
        _write_progress(root, profile_id=profile_id, state="complete", completed=completed)
        return {
            "ok": True,
            "profile": profile_id,
            "state": "complete",
            "installed": installed,
        }
    except BootstrapError as exc:
        _write_progress(
            root,
            profile_id=profile_id,
            state="failed",
            completed=completed,
            error=exc.message,
        )
        raise


__all__ = ["BootstrapError", "install_profile", "read_progress"]
