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
import subprocess
import tempfile
import time
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
_IS_WINDOWS = os.name == "nt"
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


# msiexec 返回码语义（Microsoft MSI 文档；本项目固定策略的唯一事实来源）：
MSI_SUCCESS_CODES = {0, 3010, 1641}
MSI_REBOOT_CODES = {3010, 1641}
MSI_CANCELLED = 1602
MSI_BUSY = 1618
MSI_FAILURE = 1603
# 1618（Windows Installer 忙）的有界退避：重试次数与间隔固定，超限归入
# msi_busy 具名失败——绝不无限等待，也绝不并发启动第二个 msiexec。
MSI_BUSY_RETRIES = 3
MSI_BUSY_BACKOFF_SECONDS = 30.0
MSI_TIMEOUT_SECONDS = 900


def install_msi(
    archive: Path,
    manifest: dict[str, Any],
    data_root: Path,
    *,
    allow_interactive_retry: bool = False,
) -> dict[str, Any]:
    """Verify and invoke a pinned Windows NapCat MSI without logging in.

    返回码策略（WP09）：每个非零码都有具名语义并穿透到调用方——
    0 继续健康检查；3010/1641 记录 reboot_required 并向上传播（1641 表示
    已请求重启）；1602 用户取消（不写 metadata，不留假成功）；1618 有界
    退避后仍忙则 msi_busy；1603 与其它一律具名失败并保留 MSI 详细日志，
    **不自动弹出完整 UI**（silent 安装突然弹窗是 F10 的缺陷之一；
    需要交互重试时由 GUI/用户显式发起，传
    ``allow_interactive_retry=True``）。失败或取消都不写安装 metadata，
    避免「metadata 说装好了、系统里其实没有」的假成功。
    """
    metadata = validate_manifest(manifest)
    archive = Path(archive).expanduser().resolve()
    if archive.suffix.lower() != ".msi":
        raise NapCatError("invalid_source", "NapCat MSI 安装入口只接受 .msi")
    if not archive.is_file():
        raise NapCatError("source_missing", f"NapCat MSI 不存在：{archive}")
    if sha256(archive) != metadata["digest"]:
        raise NapCatError("checksum_mismatch", "NapCat MSI digest 不匹配")
    if not _IS_WINDOWS:
        raise NapCatError("unsupported_platform", "NapCat MSI 只能在 Windows 上安装")
    paths = _paths(data_root)
    log_dir = paths["root"] / ".stella" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "napcat-msi-install.log"
    command = [
        "msiexec.exe",
        "/i",
        str(archive),
        "/passive",
        "/norestart",
        "/L*v",
        str(log_path),
    ]
    result = _run_msiexec(command, timeout=MSI_TIMEOUT_SECONDS)

    if result.returncode == MSI_BUSY:
        for _attempt in range(MSI_BUSY_RETRIES):
            time.sleep(MSI_BUSY_BACKOFF_SECONDS)
            result = _run_msiexec(command, timeout=MSI_TIMEOUT_SECONDS)
            if result.returncode != MSI_BUSY:
                break
        else:
            raise NapCatError(
                "msi_busy",
                "Windows Installer 服务忙（1618）：已有其它安装在进行，"
                f"重试 {MSI_BUSY_RETRIES} 次仍失败。请稍后在系统空闲时重试"
                f"（日志：{log_path}）",
            )

    if result.returncode == MSI_CANCELLED:
        raise NapCatError(
            "msi_cancelled",
            f"NapCat MSI 安装被用户取消（1602）。未写入安装记录（日志：{log_path}）",
        )

    if result.returncode == MSI_FAILURE and allow_interactive_retry:
        # Some NapCat MSI builds require an interactive elevation/custom-action
        # path that cannot run under /passive. Only when the caller explicitly
        # allows a full-UI retry (user-facing repair flows), never silently.
        interactive_log = log_dir / "napcat-msi-install-interactive.log"
        interactive_command = [
            "msiexec.exe",
            "/i",
            str(archive),
            "/norestart",
            "/L*v",
            str(interactive_log),
        ]
        result = _run_msiexec(interactive_command, timeout=MSI_TIMEOUT_SECONDS)
        log_path = interactive_log

    if result.returncode not in MSI_SUCCESS_CODES:
        raise NapCatError(
            "msi_install_failed",
            f"NapCat MSI 安装失败：msiexec 退出码 {result.returncode}"
            f"（日志：{log_path}）",
        )
    reboot_required = result.returncode in MSI_REBOOT_CODES

    paths["metadata"].parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **metadata,
        "install_path": "msi-managed",
        "qq_data_path": str(paths["qq"]),
        "config_path": str(paths["config"]),
        "login": {"unattended": False, "status": "not_logged_in"},
        "reboot_required": reboot_required,
    }
    if result.returncode == 1641:
        # 1641：安装器已请求重启。不能谎称“完成且无需重启”，也不在脚本里
        # 主动重启机器——恢复交给用户/外层协议。
        payload["reboot_initiated"] = True
    fd, temporary = tempfile.mkstemp(
        prefix=".napcat-", suffix=".json", dir=paths["metadata"].parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(paths["metadata"])
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return payload


def _run_msiexec(command: list[str], *, timeout: float):
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        log_path = command[-1]
        raise NapCatError(
            "msi_timeout",
            f"NapCat MSI 安装超时（{int(timeout)} 秒）。Windows Installer 可能"
            f"仍在后台运行，请先在任务管理器确认 msiexec 已退出再重试"
            f"（日志：{log_path}）",
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise NapCatError("install_failed", f"NapCat MSI 安装失败：{exc}") from exc


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
    "install_msi",
    "sha256",
    "status",
    "uninstall",
    "validate_manifest",
]
