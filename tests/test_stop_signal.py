# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""停止请求哨兵（core.stop_signal）的单元测试。

用 tmp_path + monkeypatch 掉 ``_sentinel_path``，不碰真实进程与真实 .env。
"""

from __future__ import annotations

from core.stop_signal import (
    clear_stop_request,
    is_stop_requested,
    read_stop_request,
    request_stop,
)


def _point_at(tmp_path, monkeypatch):
    sentinel = tmp_path / "stop-request"
    monkeypatch.setattr("core.stop_signal._sentinel_path", lambda: sentinel)
    return sentinel


def test_request_and_detect(monkeypatch, tmp_path):
    sentinel = _point_at(tmp_path, monkeypatch)
    assert is_stop_requested() is False
    request_stop()
    assert is_stop_requested() is True
    assert sentinel.exists()


def test_clear_is_idempotent(monkeypatch, tmp_path):
    _point_at(tmp_path, monkeypatch)
    clear_stop_request()
    clear_stop_request()  # 未创建时 clear 也不报错
    assert is_stop_requested() is False


def test_read_returns_metadata(monkeypatch, tmp_path):
    _point_at(tmp_path, monkeypatch)
    request_stop(reason="deploy stop")
    info = read_stop_request()
    assert info is not None
    assert info["reason"] == "deploy stop"
    assert isinstance(info["pid"], int)
    assert "ts" in info


def test_read_tolerates_corrupt_file(monkeypatch, tmp_path):
    """存在即意义：文件损坏不影响停止判断，read 只返回 None。"""
    sentinel = _point_at(tmp_path, monkeypatch)
    sentinel.write_text("not json", encoding="utf-8")
    assert read_stop_request() is None
    assert is_stop_requested() is True
