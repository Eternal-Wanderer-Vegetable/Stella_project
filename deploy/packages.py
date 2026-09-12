# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# This file is licensed under AGPL-3.0; see the repository LICENSE.
"""Component package catalog and model import helpers.

Release catalogs live in the replaceable program directory. Installed package
records and model bytes live below ``STELLA_HOME`` so an application upgrade
cannot overwrite them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT, STELLA_HOME, state

CATALOG_FILENAME = ".stella-package-catalog.json"
REGISTRY_FILENAME = "packages.json"
PACKAGE_ROOT = Path(".stella") / "packages"
SCHEMA_VERSION = 1
PACKAGE_KINDS = ("runtime", "component", "model", "onebot")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
_CHECKSUM = re.compile(r"^[0-9a-fA-F]{64}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:/")


class PackageError(ValueError):
    """A user-actionable package or model import error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PackageError("read_failed", f"无法读取包文件：{path}") from exc
    return digest.hexdigest()


def _package_store(data_root: Path | None = None) -> Path:
    return (data_root or STELLA_HOME) / PACKAGE_ROOT


def registry_path(data_root: Path | None = None) -> Path:
    return _package_store(data_root) / REGISTRY_FILENAME


def default_registry() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now(),
        "packages": [],
        "active": {},
        "history": [],
    }


def _validate_id(value: str, label: str) -> str:
    value = str(value).strip()
    if not _SAFE_ID.fullmatch(value):
        raise PackageError("invalid_identifier", f"{label} 不是安全的包标识：{value!r}")
    return value


def _validate_checksum(value: str) -> str:
    value = str(value).strip().lower()
    if not _CHECKSUM.fullmatch(value):
        raise PackageError("invalid_checksum", "checksum 必须是 64 位十六进制 SHA-256")
    return value


def _validate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PackageError("invalid_registry", "包记录必须是对象")
    kind = str(record.get("kind", "")).strip()
    if kind not in PACKAGE_KINDS:
        raise PackageError("invalid_registry", f"不支持的包类型：{kind}")
    package_id = _validate_id(record.get("id", ""), "包 id")
    version = _validate_id(record.get("version", ""), "包 version")
    path = str(record.get("path", "")).strip().replace("\\", "/")
    if (
        not path
        or Path(path).is_absolute()
        or _WINDOWS_ABSOLUTE.match(path)
        or ".." in Path(path).parts
    ):
        raise PackageError("invalid_registry", "包路径必须是数据目录内的相对路径")
    checksum = _validate_checksum(record.get("checksum", ""))
    normalized: dict[str, Any] = {
        "kind": kind,
        "id": package_id,
        "version": version,
        "path": path,
        "checksum": checksum,
        **(
            {"platform": str(record["platform"]).strip()}
            if record.get("platform")
            else {}
        ),
        **(
            {"installed_at": str(record["installed_at"])}
            if record.get("installed_at")
            else {}
        ),
    }
    for key in (
        "backend",
        "model_role",
        "profile",
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
            value = record[key]
            if not isinstance(value, str) or not value.strip():
                raise PackageError("invalid_registry", f"包字段 {key} 必须是非空字符串")
            if key == "backend" and value.strip().lower() not in {
                "cpu", "cuda", "hip", "metal", "vulkan"
            }:
                raise PackageError("invalid_registry", f"不支持的 backend：{value}")
            normalized[key] = value.strip()
    if record.get("size") is not None:
        try:
            size = int(record["size"])
        except (TypeError, ValueError) as exc:
            raise PackageError("invalid_registry", "包 size 必须是正整数") from exc
        if size <= 0:
            raise PackageError("invalid_registry", "包 size 必须是正整数")
        normalized["size"] = size
    if record.get("dimension") is not None:
        try:
            dimension = int(record["dimension"])
        except (TypeError, ValueError) as exc:
            raise PackageError("invalid_registry", "包 dimension 必须是正整数") from exc
        if dimension <= 0:
            raise PackageError("invalid_registry", "包 dimension 必须是正整数")
        normalized["dimension"] = dimension
    if record.get("remote") is not None:
        if not isinstance(record["remote"], bool):
            raise PackageError("invalid_registry", "包 remote 必须是布尔值")
        normalized["remote"] = record["remote"]
    if record.get("dependencies") is not None:
        dependencies = record["dependencies"]
        if not isinstance(dependencies, list) or not all(
            isinstance(item, str) and item.strip() for item in dependencies
        ):
            raise PackageError("invalid_registry", "包 dependencies 必须是字符串数组")
        normalized["dependencies"] = list(dependencies)
    return normalized


def validate_registry(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise PackageError("invalid_registry", "不支持的包 registry schema")
    packages = payload.get("packages")
    if not isinstance(packages, list):
        raise PackageError("invalid_registry", "包 registry 缺少 packages 数组")
    identities: set[tuple[str, str, str]] = set()
    for item in packages:
        record = _validate_record(item)
        identity = (record["kind"], record["id"], record["version"])
        if identity in identities:
            raise PackageError("invalid_registry", f"包记录重复：{identity}")
        identities.add(identity)
    active = payload.get("active", {})
    if not isinstance(active, dict):
        raise PackageError("invalid_registry", "包 registry 的 active 必须是对象")
    for kind, identity in active.items():
        if kind not in PACKAGE_KINDS or not isinstance(identity, str):
            raise PackageError("invalid_registry", "包 registry 的 active 无效")
        if not any(
            item["kind"] == kind and f"{item['id']}@{item['version']}" == identity
            for item in packages
        ):
            raise PackageError(
                "invalid_registry", f"active 包不存在：{kind}={identity}"
            )
    history = payload.get("history", [])
    if not isinstance(history, list):
        raise PackageError("invalid_registry", "包 registry 的 history 必须是数组")


def _read_registry(data_root: Path | None = None) -> dict[str, Any]:
    path = registry_path(data_root)
    if not path.is_file():
        return default_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_registry(payload)
    except PackageError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PackageError("invalid_registry", f"无法读取包 registry：{path}") from exc
    return payload


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
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temp_path = Path(name)
        if temp_path.exists():
            temp_path.unlink()


def write_registry(payload: dict[str, Any], data_root: Path | None = None) -> Path:
    validate_registry(payload)
    path = registry_path(data_root)
    _atomic_write(path, payload)
    return path


def read_registry(data_root: Path | None = None) -> dict[str, Any]:
    return _read_registry(data_root)


def _copy_verified(source: Path, target: Path, expected: str) -> str:
    if not source.is_file():
        raise PackageError("source_missing", f"模型文件不存在：{source}")
    actual = file_sha256(source)
    if actual != expected:
        raise PackageError(
            "checksum_mismatch",
            f"模型校验失败：期望 {expected}，实际 {actual}；active model 未改变",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not target.is_file() or file_sha256(target) != actual:
            raise PackageError(
                "package_conflict", f"目标包已存在但 checksum 不一致：{target}"
            )
        return actual

    fd, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_stream:
            for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        staged = Path(name)
        if file_sha256(staged) != actual:
            raise PackageError(
                "checksum_mismatch", "临时模型文件校验失败；active model 未改变"
            )
        staged.replace(target)
    except OSError as exc:
        raise PackageError("write_failed", f"模型导入失败：{target}") from exc
    finally:
        temp_path = Path(name)
        if temp_path.exists():
            temp_path.unlink()
    return actual


def _update_runtime_manifest(record: dict[str, Any], data_root: Path) -> None:
    # Import lazily so package listing remains usable when the runtime contract
    # is unavailable during a first-run bootstrap.
    from . import runtime

    payload = runtime.read_manifest()
    llama = payload.setdefault("components", {}).setdefault("llama", {})
    config = llama.setdefault("config", {})
    config["model"] = {
        "path": str((data_root / record["path"]).resolve()),
        "package": f"{record['id']}@{record['version']}",
        "id": record["id"],
        "checksum": record["checksum"],
    }
    runtime.write_manifest(payload)


def import_model(
    source: Path,
    *,
    model_id: str,
    version: str,
    checksum: str,
    data_root: Path | None = None,
    activate: bool = True,
    backend: str | None = None,
) -> dict[str, Any]:
    """Import a model without exposing an incomplete or unverified file."""
    source = Path(source).expanduser().resolve()
    package_id = _validate_id(model_id, "模型 id")
    package_version = _validate_id(version, "模型 version")
    expected = _validate_checksum(checksum)
    if backend is not None and backend not in {"cpu", "cuda", "hip", "metal", "vulkan"}:
        raise PackageError("unsupported_backend", f"不支持的 model backend：{backend}")
    root = data_root or STELLA_HOME
    target = _package_store(root) / "model" / package_id / package_version
    suffix = source.suffix.lower() if source.suffix else ".bin"
    destination = target / f"{package_id}{suffix}"
    actual = _copy_verified(source, destination, expected)
    relative = destination.relative_to(root).as_posix()
    record = {
        "kind": "model",
        "id": package_id,
        "version": package_version,
        "path": relative,
        "checksum": actual,
        "installed_at": _now(),
    }
    if backend:
        record["backend"] = backend

    registry = _read_registry(root)
    identity = (record["kind"], record["id"], record["version"])
    registry["packages"] = [
        item
        for item in registry["packages"]
        if (item["kind"], item["id"], item["version"]) != identity
    ]
    registry["packages"].append(record)
    if activate:
        previous = registry.get("active", {}).get("model")
        current = f"{package_id}@{package_version}"
        registry.setdefault("active", {})["model"] = current
        if previous != current:
            registry.setdefault("history", []).append(
                {
                    "kind": "model",
                    "previous": previous,
                    "current": current,
                    "at": _now(),
                }
            )
    registry["updated_at"] = _now()
    write_registry(registry, root)
    if activate:
        _update_runtime_manifest(record, root)
    return record


def rollback_model(data_root: Path | None = None) -> dict[str, Any]:
    """Restore the previous active model recorded in the package history."""
    root = data_root or STELLA_HOME
    registry = _read_registry(root)
    current = registry.get("active", {}).get("model")
    previous = None
    for event in reversed(registry.get("history", [])):
        if (
            isinstance(event, dict)
            and event.get("kind") == "model"
            and event.get("current") == current
            and event.get("previous")
        ):
            previous = str(event["previous"])
            break
    if not previous:
        raise PackageError("rollback_unavailable", "没有可回滚的 active model")
    record = next(
        (
            item
            for item in registry["packages"]
            if item["kind"] == "model" and f"{item['id']}@{item['version']}" == previous
        ),
        None,
    )
    if record is None:
        raise PackageError("rollback_unavailable", f"回滚目标未安装：{previous}")
    registry.setdefault("active", {})["model"] = previous
    registry.setdefault("history", []).append(
        {
            "kind": "model",
            "previous": current,
            "current": previous,
            "at": _now(),
            "reason": "rollback",
        }
    )
    registry["updated_at"] = _now()
    write_registry(registry, root)
    _update_runtime_manifest(record, root)
    return record


def _catalog_records(
    root: Path, platform: str | None, profile_id: str | None = None
) -> list[dict[str, Any]]:
    version = state.program_version(root) or "unknown"
    candidates = (
        ("runtime", "python-bootstrap", version, "start.bat"),
        ("component", "stella-core", version, "bot.py"),
        (
            "component",
            "runtime-contract",
            str(SCHEMA_VERSION),
            "runtime-manager/schemas/runtime-manifest.schema.json",
        ),
        ("onebot", "onebot-adapter", version, "extensions/link_monitor/__init__.py"),
    )
    records = []
    for kind, package_id, package_version, relative in candidates:
        path = root / relative
        if not path.is_file():
            continue
        record = {
            "kind": kind,
            "id": package_id,
            "version": package_version,
            "path": relative,
            "checksum": file_sha256(path),
        }
        if platform:
            record["platform"] = platform
        records.append(record)
    generated = root / ".stella-llama-catalog.json"
    if generated.is_file():
        try:
            payload = json.loads(generated.read_text(encoding="utf-8"))
            extra = payload.get("packages", [])
        except (OSError, ValueError, TypeError) as exc:
            raise PackageError("invalid_catalog", f"{generated} 不是有效 JSON") from exc
        if not isinstance(extra, list):
            raise PackageError("invalid_catalog", "llama catalog packages 必须是数组")
        for item in extra:
            record = _validate_record(item)
            if record["kind"] != "component" or not record.get("backend"):
                raise PackageError("invalid_catalog", "llama artifact 必须是带 backend 的 component")
            if platform and record.get("platform") not in {None, platform}:
                continue
            records.append(record)
    if profile_id:
        from .profiles import load_profile

        profile = load_profile(profile_id)
        for model in profile["default_models"]:
            records.append(
                {
                    "kind": "model",
                    "id": model["id"],
                    "version": model["version"],
                    "path": f"models/embedding/{model['filename']}",
                    "checksum": model["sha256"],
                    "platform": profile["platform"],
                    "runtime_api": "llama.cpp-embedding",
                    "license": model["license"],
                    "source": model["source"],
                    "artifact": model["filename"],
                    "status": "available",
                    "model_role": model["role"],
                    "size": model["size"],
                    "dimension": model["dimension"],
                    "remote": True,
                }
            )
    return records


def build_catalog(
    root: Path = PROJECT_ROOT,
    *,
    platform: str | None = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "platform": platform or "any",
        "packages": _catalog_records(root, platform, profile_id),
    }
    if profile_id:
        payload["profile"] = profile_id
    return payload


def catalog_path(root: Path = PROJECT_ROOT) -> Path:
    return Path(root) / CATALOG_FILENAME


def write_catalog(
    root: Path = PROJECT_ROOT,
    *,
    platform: str | None = None,
    profile_id: str | None = None,
) -> Path:
    root = Path(root).resolve()
    path = catalog_path(root)
    _atomic_write(path, build_catalog(root, platform=platform, profile_id=profile_id))
    return path


def verify_catalog(root: Path = PROJECT_ROOT) -> list[str]:
    root = Path(root).resolve()
    path = catalog_path(root)
    if not path.is_file():
        return [f"缺少 {CATALOG_FILENAME}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        packages = payload["packages"]
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{CATALOG_FILENAME} 不是有效 JSON"]
    problems = []
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(
        packages, list
    ):
        return [f"{CATALOG_FILENAME} schema 不受支持"]
    for item in packages:
        try:
            record = _validate_record(item)
            file_path = root / record["path"]
            if record.get("remote"):
                if not record.get("source"):
                    problems.append(f"{record['id']} 缺少远程 source")
            elif not file_path.is_file():
                problems.append(f"{record['path']} 不存在")
            elif file_sha256(file_path) != record["checksum"]:
                problems.append(f"{record['path']} checksum 不匹配")
        except PackageError as exc:
            problems.append(exc.message)
    return problems


__all__ = [
    "CATALOG_FILENAME",
    "PACKAGE_KINDS",
    "PackageError",
    "build_catalog",
    "catalog_path",
    "default_registry",
    "file_sha256",
    "import_model",
    "read_registry",
    "registry_path",
    "rollback_model",
    "validate_registry",
    "verify_catalog",
    "write_catalog",
    "write_registry",
]
