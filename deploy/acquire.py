# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Verified acquisition of remote component and model artifacts.

Network access is deliberately kept outside the transactional installers:
download into a temporary file, verify provenance, then hand the local file to
the existing atomic activation boundary.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import napcat, packages


class AcquireError(ValueError):
    """A user-actionable remote acquisition failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _https_url(value: Any, label: str) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AcquireError("invalid_source", f"{label} 必须是 HTTPS URL")
    if "latest" in url.lower():
        raise AcquireError("unpinned_source", f"{label} 不得使用 latest")
    return url


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AcquireError("read_failed", f"无法读取下载文件：{path}") from exc
    return digest.hexdigest()


def download_verified(
    source: str,
    destination: Path,
    *,
    checksum: str,
    size: int | None = None,
    timeout: float = 120,
) -> Path:
    """Download one immutable artifact and publish it only after verification."""
    url = _https_url(source, "source")
    expected = str(checksum or "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise AcquireError("invalid_checksum", "下载 artifact 必须提供 64 位 SHA-256")
    if size is not None and int(size) <= 0:
        raise AcquireError("invalid_size", "下载 artifact size 必须为正数")

    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as output:
            try:
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    total = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        total += len(chunk)
            except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
                raise AcquireError("download_failed", f"下载失败：{url}") from exc
            output.flush()
            os.fsync(output.fileno())
        if size is not None and temp_path.stat().st_size != int(size):
            raise AcquireError(
                "size_mismatch",
                f"下载大小不匹配：期望 {size}，实际 {temp_path.stat().st_size}",
            )
        actual = _digest(temp_path)
        if actual != expected:
            raise AcquireError(
                "checksum_mismatch",
                f"下载 checksum 不匹配：期望 {expected}，实际 {actual}",
            )
        temp_path.replace(destination)
        return destination
    except (OSError, AcquireError):
        temp_path.unlink(missing_ok=True)
        raise


def install_napcat(
    manifest: dict[str, Any],
    data_root: Path,
    *,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Acquire a pinned NapCat archive and pass it to install_archive."""
    metadata = napcat.validate_manifest(manifest)
    cache = Path(cache_dir or (Path(data_root) / ".stella" / "downloads"))
    archive = cache / f"napcat-{metadata['version']}.zip"
    download_verified(
        metadata["source"],
        archive,
        checksum=metadata["digest"],
    )
    return napcat.install_archive(archive, metadata, Path(data_root))


def install_default_embedding(
    model: dict[str, Any],
    data_root: Path,
    *,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Acquire and register one declared embedding artifact."""
    required = ("id", "version", "filename", "source", "sha256", "size", "role")
    missing = [key for key in required if key not in model]
    if missing or model.get("role") != "embedding":
        raise AcquireError("invalid_model", "默认 embedding 元数据不完整")
    cache = Path(cache_dir or (Path(data_root) / ".stella" / "downloads"))
    source = _https_url(model["source"], "model source")
    archive = cache / str(model["filename"])
    download_verified(
        source,
        archive,
        checksum=str(model["sha256"]),
        size=int(model["size"]),
    )
    return packages.import_model(
        archive,
        model_id=str(model["id"]),
        version=str(model["version"]),
        checksum=str(model["sha256"]),
        data_root=Path(data_root),
        backend="cpu",
        model_role="embedding",
        model_metadata=model,
    )


__all__ = ["AcquireError", "download_verified", "install_default_embedding", "install_napcat"]
