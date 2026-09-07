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
    monkeypatch.setattr(probe, "STELLA_HOME", tmp_path)
    exists, keys, superseded = probe._probe_env_file()
    assert exists is False
    assert keys == []
    assert superseded == []


def test_probe_env_file_deprecated_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "STELLA_HOME", tmp_path)
    (tmp_path / ".env").write_text(
        "ALLOWED_GROUPS=123\n"
        "NAPCAT_QQ_PASSWORD=x\n"
        "NAPCAT_WATCHDOG_INTERVAL=10\n",
        encoding="utf-8",
    )
    exists, keys, superseded = probe._probe_env_file()
    assert exists is True
    assert keys == ["NAPCAT_QQ_PASSWORD", "NAPCAT_WATCHDOG_INTERVAL"]
    assert superseded == []


def test_probe_env_file_ignores_comments(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "STELLA_HOME", tmp_path)
    (tmp_path / ".env").write_text(
        "# NAPCAT_QQ_PASSWORD=x\nALLOWED_GROUPS=1\n", encoding="utf-8"
    )
    exists, keys, superseded = probe._probe_env_file()
    assert exists is True
    assert keys == []
    assert superseded == []


def test_probe_env_file_reports_superseded_keys(monkeypatch, tmp_path):
    """被新键取代的键要与废弃键分开报：前者代码还在读，提示的动作不一样。"""
    monkeypatch.setattr(probe, "STELLA_HOME", tmp_path)
    (tmp_path / ".env").write_text(
        "LLM_SCHEDULER_GATE_EMBEDDING=false\nNAPCAT_QQ_PASSWORD=x\n",
        encoding="utf-8",
    )
    exists, keys, superseded = probe._probe_env_file()
    assert exists is True
    assert keys == ["NAPCAT_QQ_PASSWORD"]
    assert superseded == ["LLM_SCHEDULER_GATE_EMBEDDING"]


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


def test_version_marks_does_not_write_state_file(tmp_path, monkeypatch):
    """doctor 只读版本标记。

    若 doctor 顺手写了 ``last_run_version``，紧接着的第一次真正启动就会把「刚升级」
    判成「版本未变」——升级提示、一次性迁移动作全部静默失效。
    """
    from config import state

    monkeypatch.setattr(probe, "STELLA_HOME", tmp_path)
    marks = probe._version_marks()

    assert not state.state_path(tmp_path).exists()
    # 空目录里没有上次运行记录，因此必然被判为首次运行
    assert marks["version_transition"] == state.FIRST_RUN
    assert marks["last_run_version"] == ""
    assert not marks["state_file_error"]


def test_probe_database_fresh_install_parent_missing(monkeypatch, tmp_path):
    """全新安装：memory/ 目录尚不存在时，可写性探测不应误报。

    历史缺陷：对缺失目录直接 os.access(W_OK) 必得 False，doctor 在任何全新
    部署上都会报「数据库不可写」的阻塞级误报。修复后探测会先建目录（与 Bot
    首次写库的行为一致），全新安装应得到 db_writable=True。
    """
    monkeypatch.setattr(probe, "DB_PATH", tmp_path / "memory" / "agent_memory.db")
    r = probe._probe_database()
    assert r["db_exists"] is False
    assert r["db_writable"] is True
    # 目录确实被建出来（Bot 首启前 doctor 就能给出真实结论）
    assert (tmp_path / "memory").is_dir()
