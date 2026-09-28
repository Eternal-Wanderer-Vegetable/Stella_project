# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Verified acquisition of remote component and model artifacts.

Network access is deliberately kept outside the transactional installers:
download into a temporary file, verify provenance, then hand the local file to
the existing atomic activation boundary.
"""

from __future__ import annotations

import hashlib
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import napcat, packages

# 可重试与致命的下载错误分类（WP12）：429/5xx/网络抖动 → 有限退避重试；
# 404/403/校验失败 → 立即具名失败，绝不无限换源或绕过校验。
RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
DOWNLOAD_MAX_ATTEMPTS = 4
DOWNLOAD_BACKOFF_SECONDS = (1.0, 3.0, 9.0)

ProgressCallback = Callable[[int, int | None], None]


class AcquireError(ValueError):
    """A user-actionable remote acquisition failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _RetryableDownloadError(Exception):
    pass


class _FatalDownloadError(Exception):
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


def _download_once(
    url: str,
    part_path: Path,
    *,
    timeout: float,
    progress: ProgressCallback | None,
) -> None:
    """单次下载（支持对 .part 的 Range 续传）；中途网络错误保留 .part。"""
    resume_from = part_path.stat().st_size if part_path.is_file() else 0
    request = urllib.request.Request(url)
    if resume_from:
        request.add_header("Range", f"bytes={resume_from}-")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in RETRYABLE_HTTP_STATUS:
            raise _RetryableDownloadError(f"HTTP {exc.code}") from exc
        raise _FatalDownloadError(
            "download_failed", f"HTTP {exc.code}（不可重试）"
        ) from exc
    except OSError as exc:
        raise _RetryableDownloadError(str(exc)) from exc
    with response:
        status = getattr(response, "status", None) or 200
        appending = bool(resume_from) and status == 206
        if resume_from and not appending:
            # 服务器不支持 Range：放弃续传，全量重下
            resume_from = 0
        mode = "ab" if appending else "wb"
        with part_path.open(mode) as output:
            downloaded = resume_from
            total = None
            length = response.headers.get("Content-Length") if hasattr(
                response, "headers"
            ) else None
            if length is not None:
                total = int(length) + (resume_from if appending else 0)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
    # 进度回调可抛 AcquireError("cancelled") 取消本次下载；此处不捕获，
    # .part 保留为可验证的续传片段。


def download_verified(
    source: str,
    destination: Path,
    *,
    checksum: str,
    size: int | None = None,
    timeout: float = 120,
    attempts: int = DOWNLOAD_MAX_ATTEMPTS,
    backoff: tuple[float, ...] = DOWNLOAD_BACKOFF_SECONDS,
    progress: ProgressCallback | None = None,
) -> Path:
    """Download one immutable artifact and publish it only after verification.

    WP12 语义：
    * 断点续传：失败保留 ``<destination>.part``，重试时带 Range 续传；
      服务器不支持 Range 则全量重下。最终完整性始终由 sha256 保证——
      续传片段若被破坏会在校验一步暴露，不依赖传输层可信。
    * 有限重试：429/5xx/网络抖动按固定退避重试（默认 4 次）；404/403
      等致命错误立即失败；校验不匹配不重试。
    * 取消：``progress`` 回调可抛 ``AcquireError("cancelled")`` 终止本次
      下载，已下载部分保留为可续传片段。
    """
    url = _https_url(source, "source")
    expected = str(checksum or "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise AcquireError("invalid_checksum", "下载 artifact 必须提供 64 位 SHA-256")
    if size is not None and int(size) <= 0:
        raise AcquireError("invalid_size", "下载 artifact size 必须为正数")

    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_name(destination.name + ".part")
    try:
        last_message = ""
        for attempt in range(max(1, attempts)):
            try:
                _download_once(url, part_path, timeout=timeout, progress=progress)
                break
            except _RetryableDownloadError as exc:
                last_message = str(exc)
                if attempt < max(1, attempts) - 1:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
            except _FatalDownloadError as exc:
                raise AcquireError(exc.code, exc.message) from exc
        else:
            raise AcquireError(
                "download_failed",
                f"下载失败（重试 {attempts} 次后放弃）：{url}；最后错误：{last_message}",
            )

        actual_size = part_path.stat().st_size
        if size is not None and actual_size != int(size):
            part_path.unlink(missing_ok=True)
            raise AcquireError(
                "size_mismatch",
                f"下载大小不匹配：期望 {size}，实际 {actual_size}",
            )
        actual = _digest(part_path)
        if actual != expected:
            part_path.unlink(missing_ok=True)
            raise AcquireError(
                "checksum_mismatch",
                f"下载 checksum 不匹配：期望 {expected}，实际 {actual}",
            )
        part_path.replace(destination)
        return destination
    except AcquireError:
        raise
    except OSError as exc:
        raise AcquireError("download_failed", f"下载写入失败：{exc}") from exc


def verify_local_artifact(
    path: Path,
    *,
    checksum: str,
    size: int | None = None,
) -> Path:
    """Verify one already-local artifact and return it.

    Offline installers ship release-time copies of the remote artifacts; those
    copies must clear exactly the same provenance bar as a fresh download
    (checksum, and size when the catalog declares one) before the transactional
    installers may touch them. Verification failure is an error, never a
    silent pass-through — a corrupted bundle must not install half a component.
    """
    expected = str(checksum or "").strip().lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise AcquireError("invalid_checksum", "本地 artifact 必须提供 64 位 SHA-256")
    path = Path(path)
    if not path.is_file():
        raise AcquireError("read_failed", f"本地 artifact 不存在：{path}")
    if size is not None:
        if int(size) <= 0:
            raise AcquireError("invalid_size", "artifact size 必须为正数")
        actual_size = path.stat().st_size
        if actual_size != int(size):
            raise AcquireError(
                "size_mismatch",
                f"本地大小不匹配：期望 {size}，实际 {actual_size}",
            )
    actual = _digest(path)
    if actual != expected:
        raise AcquireError(
            "checksum_mismatch",
            f"本地 checksum 不匹配：期望 {expected}，实际 {actual}",
        )
    return path


def install_napcat(
    manifest: dict[str, Any],
    data_root: Path,
    *,
    archive: Path | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Acquire a pinned NapCat archive and pass it to install_archive."""
    metadata = napcat.validate_manifest(manifest)
    cache = Path(cache_dir or (Path(data_root) / ".stella" / "downloads"))
    local_archive = (
        Path(archive)
        if archive is not None
        else cache / f"napcat-{metadata['version']}.zip"
    )
    if archive is None:
        download_verified(
            metadata["source"],
            local_archive,
            checksum=metadata["digest"],
        )
    if local_archive.suffix.lower() == ".msi":
        return napcat.install_msi(local_archive, metadata, Path(data_root))
    return napcat.install_archive(local_archive, metadata, Path(data_root))


def install_default_embedding(
    model: dict[str, Any],
    data_root: Path,
    *,
    archive: Path | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Acquire and register one declared embedding artifact."""
    required = ("id", "version", "filename", "source", "sha256", "size", "role")
    missing = [key for key in required if key not in model]
    if missing or model.get("role") != "embedding":
        raise AcquireError("invalid_model", "默认 embedding 元数据不完整")
    cache = Path(cache_dir or (Path(data_root) / ".stella" / "downloads"))
    local_archive = (
        Path(archive)
        if archive is not None
        else cache / str(model["filename"])
    )
    if archive is None:
        source = _https_url(model["source"], "model source")
        download_verified(
            source,
            local_archive,
            checksum=str(model["sha256"]),
            size=int(model["size"]),
        )
    return packages.import_model(
        local_archive,
        model_id=str(model["id"]),
        version=str(model["version"]),
        checksum=str(model["sha256"]),
        data_root=Path(data_root),
        backend="cpu",
        model_role="embedding",
        model_metadata=model,
    )


__all__ = [
    "AcquireError",
    "download_verified",
    "install_default_embedding",
    "install_napcat",
    "verify_local_artifact",
]
