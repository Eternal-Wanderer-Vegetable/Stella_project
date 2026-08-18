# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 采集层的少量单元测试。

探针是「不抛异常、失败写 None」的纯 IO 函数，这里覆盖最容易回归的几处：
.env 解析、WS URL 提取、端口探测、collect 兜底。网络/数据库相关探针在
单元测试里不依赖真实环境（LM Studio 探针被 monkeypatch 掉）。
"""

from __future__ import annotations

from deploy import probe
from deploy.models import Snapshot


def test_extract_ws_url_json_array():
    values = {"ONEBOT_WS_URLS": '["ws://127.0.0.1:3001"]'}
    assert probe._extract_ws_url(values) == "ws://127.0.0.1:3001"


def test_extract_ws_url_legacy_v11_alias():
    values = {"ONEBOT_V11_WS_URLS": '["ws://127.0.0.1:3001"]'}
    assert probe._extract_ws_url(values) == "ws://127.0.0.1:3001"


def test_extract_ws_url_bare_url():
    values = {"ONEBOT_WS_URLS": "ws://127.0.0.1:3001"}
    assert probe._extract_ws_url(values) == "ws://127.0.0.1:3001"


def test_extract_ws_url_missing():
    assert probe._extract_ws_url({}) is None


def test_probe_env_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "PROJECT_ROOT", tmp_path)
    exists, keys = probe._probe_env_file()
    assert exists is False
    assert keys == []


def test_probe_env_file_deprecated_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "ALLOWED_GROUPS=123\n"
        "NAPCAT_QQ_PASSWORD=x\n"
        "NAPCAT_WATCHDOG_INTERVAL=10\n",
        encoding="utf-8",
    )
    exists, keys = probe._probe_env_file()
    assert exists is True
    assert keys == ["NAPCAT_QQ_PASSWORD", "NAPCAT_WATCHDOG_INTERVAL"]


def test_probe_env_file_ignores_comments(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "# NAPCAT_QQ_PASSWORD=x\nALLOWED_GROUPS=1\n", encoding="utf-8"
    )
    exists, keys = probe._probe_env_file()
    assert exists is True
    assert keys == []


def test_port_in_use_free_port():
    # 端口 0 = 由系统分配空闲端口，bind 必然成功 → 返回 False
    assert probe._port_in_use("127.0.0.1", 0) is False


def test_tcp_reachable_invalid_url():
    assert probe._tcp_reachable("ws://") is None


def test_collect_never_raises(monkeypatch):
    monkeypatch.setattr(
        probe,
        "_probe_lm_studio",
        lambda: {"lm_reachable": False, "lm_error": "skipped", "lm_models": []},
    )
    snap = probe.collect()
    assert isinstance(snap, Snapshot)
    assert snap.lm_reachable is False
