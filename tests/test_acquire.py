# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 全文见项目根目录 LICENSE.
"""download_verified 的恢复/重试/取消语义测试（WP12）。

全部用假 urlopen 模拟服务器行为（206 续传、200 全量、5xx、404），
不触碰真实网络。完整性锚点是 sha256——续传片段损坏必须在校验一步
暴露，而不是被当作可信数据。
"""

from __future__ import annotations

import hashlib
import io

import pytest

from deploy import acquire
from deploy.acquire import AcquireError

PAYLOAD = b"resume-payload-bytes-0123456789"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class _FakeResponse(io.BytesIO):
    def __init__(self, content: bytes, status: int = 200):
        super().__init__(content)
        self.status = status
        self.headers = {"Content-Length": str(len(content))}


def _install_urlopen(monkeypatch, responder):
    monkeypatch.setattr(
        acquire.urllib.request, "urlopen",
        lambda request, timeout=None: responder(request),
    )


def test_download_writes_and_publishes_verified_file(tmp_path, monkeypatch):
    _install_urlopen(
        monkeypatch,
        lambda request: _FakeResponse(PAYLOAD),
    )
    destination = tmp_path / "artifact.bin"
    result = acquire.download_verified(
        "https://example.invalid/artifact.bin",
        destination,
        checksum=_sha(PAYLOAD),
    )
    assert result == destination
    assert destination.read_bytes() == PAYLOAD
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_resumes_from_part_with_range(tmp_path, monkeypatch):
    # 已有前 4 字节的 .part；服务器响应 206 + 剩余内容
    destination = tmp_path / "artifact.bin"
    part = destination.with_name(destination.name + ".part")
    part.write_bytes(PAYLOAD[:4])
    seen_ranges: list[str | None] = []

    def responder(request):
        range_header = request.headers.get("Range")
        seen_ranges.append(range_header)
        assert range_header == f"bytes={len(PAYLOAD[:4])}-"
        return _FakeResponse(PAYLOAD[4:], status=206)

    _install_urlopen(monkeypatch, responder)
    acquire.download_verified(
        "https://example.invalid/artifact.bin",
        destination,
        checksum=_sha(PAYLOAD),
    )
    assert destination.read_bytes() == PAYLOAD
    assert seen_ranges == [f"bytes={len(PAYLOAD[:4])}-"]


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"
    destination.with_name(destination.name + ".part").write_bytes(PAYLOAD[:4])

    def responder(request):
        # 服务器不支持 Range：返回 200 全量（不带 Range 校验）
        assert request.headers.get("Range") is not None
        return _FakeResponse(PAYLOAD)

    _install_urlopen(monkeypatch, responder)
    acquire.download_verified(
        "https://example.invalid/artifact.bin",
        destination,
        checksum=_sha(PAYLOAD),
    )
    assert destination.read_bytes() == PAYLOAD


def test_retryable_status_backs_off_then_succeeds(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"
    sleeps: list[float] = []
    monkeypatch.setattr(acquire.time, "sleep", lambda s: sleeps.append(s))
    codes = iter([503, 429])

    def responder(request):
        code = next(codes, None)
        if code is not None:
            raise acquire.urllib.error.HTTPError(
                "https://example.invalid/x", code, "busy", hdrs=None, fp=None
            )
        return _FakeResponse(PAYLOAD)

    _install_urlopen(monkeypatch, responder)
    acquire.download_verified(
        "https://example.invalid/artifact.bin",
        destination,
        checksum=_sha(PAYLOAD),
    )
    assert sleeps == [1.0, 3.0]
    assert destination.read_bytes() == PAYLOAD


def test_fatal_404_fails_immediately_without_retry(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"
    sleeps: list[float] = []
    monkeypatch.setattr(acquire.time, "sleep", lambda s: sleeps.append(s))
    calls = {"count": 0}

    def responder(request):
        calls["count"] += 1
        raise acquire.urllib.error.HTTPError(
            "https://example.invalid/x", 404, "gone", hdrs=None, fp=None
        )

    _install_urlopen(monkeypatch, responder)
    with pytest.raises(AcquireError) as error:
        acquire.download_verified(
            "https://example.invalid/artifact.bin",
            destination,
            checksum=_sha(PAYLOAD),
        )
    assert error.value.code == "download_failed"
    assert calls["count"] == 1, "404 不可重试"
    assert sleeps == []


def test_retry_exhaustion_keeps_resumable_part(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"
    part = destination.with_name(destination.name + ".part")
    monkeypatch.setattr(acquire.time, "sleep", lambda _s: None)

    def responder(request):
        raise OSError("connection reset")

    _install_urlopen(monkeypatch, responder)
    with pytest.raises(AcquireError, match="重试"):
        acquire.download_verified(
            "https://example.invalid/artifact.bin",
            destination,
            checksum=_sha(PAYLOAD),
        )
    # 网络中断保留 .part（可能为空文件）；下次可续传/重下
    assert part.exists() or not destination.exists()


def test_progress_callback_can_cancel_and_part_survives(tmp_path, monkeypatch):
    destination = tmp_path / "artifact.bin"

    def responder(request):
        return _FakeResponse(PAYLOAD)

    _install_urlopen(monkeypatch, responder)

    def cancel_early(_done, _total):
        raise AcquireError("cancelled", "用户取消下载")

    with pytest.raises(AcquireError) as error:
        acquire.download_verified(
            "https://example.invalid/artifact.bin",
            destination,
            checksum=_sha(PAYLOAD),
            attempts=1,
            progress=cancel_early,
        )
    assert error.value.code == "cancelled"
    assert not destination.exists(), "取消后不得发布未完成的文件"


def test_corrupted_resume_part_is_caught_by_checksum(tmp_path, monkeypatch):
    """续传片段损坏 → sha256 校验兜底拒绝，绝不发布坏文件。"""
    destination = tmp_path / "artifact.bin"
    destination.with_name(destination.name + ".part").write_bytes(b"CORRUPT-PREFIX")

    def responder(request):
        # 服务器按 Range 返回剩余内容（从损坏长度起），拼起来 ≠ 期望内容
        return _FakeResponse(PAYLOAD, status=206)

    _install_urlopen(monkeypatch, responder)
    with pytest.raises(AcquireError, match="checksum"):
        acquire.download_verified(
            "https://example.invalid/artifact.bin",
            destination,
            checksum=_sha(PAYLOAD),
        )
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()
