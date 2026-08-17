# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""config.spaces 共享空间解析的单元测试。

覆盖：显式空间、自动命名持久化、递增编号、TOML 冲突取先者、显式名与账本名
冲突告警。SPACES_DIR / _AUTO_FILE 由 conftest 的 autouse fixture 隔离到每个
用例独立的临时目录（不写仓库真实目录）。
"""

import json
from pathlib import Path

import nonebot

import config.spaces as spaces


def _make_toml(tmp_path: Path, name: str, groups) -> None:
    """在隔离的 SPACES_DIR 下写一个 qq_groups 配置文件。"""
    d = tmp_path / "spaces"
    d.mkdir(exist_ok=True)
    (d / f"{name}.toml").write_text(
        f"qq_groups = [{', '.join(map(str, groups))}]\n", encoding="utf-8"
    )


def test_explicit_space_resolved(tmp_path):
    """显式空间：TOML 收录的群解析为文件名，qq_groups_of 反查正确。"""
    _make_toml(tmp_path, "casual", [263402786, 111])
    spaces.reload()
    assert spaces.resolve_space(263402786) == "casual"
    assert spaces.resolve_space(111) == "casual"
    assert spaces.qq_groups_of("casual") == [263402786, 111]


def test_auto_space_persisted_across_calls(tmp_path):
    """自动命名：同一群两次 resolve 返回同一个 space_N（账本持久化，不现算）。"""
    a = spaces.resolve_space(1001)
    b = spaces.resolve_space(1001)
    assert a == b == "space_1"
    # 账本已落盘，且反查能找到该群
    assert spaces._AUTO_FILE.exists()
    assert spaces.qq_groups_of("space_1") == [1001]


def test_auto_space_increments_across_restart(tmp_path):
    """账本存在时新群拿到递增编号；reload 模拟重启后编号稳定。"""
    assert spaces.resolve_space(1001) == "space_1"
    assert spaces.resolve_space(2002) == "space_2"
    spaces.reload()  # 模拟重启：账本从磁盘重新加载
    assert spaces.resolve_space(1001) == "space_1"
    assert spaces.resolve_space(2002) == "space_2"
    assert spaces.resolve_space(3003) == "space_3"


def test_toml_conflict_takes_first_by_filename(tmp_path, monkeypatch):
    """同群出现在两个 toml：按文件名排序取先者，并打 error 告警。"""
    errors: list[str] = []
    monkeypatch.setattr(nonebot.logger, "error", lambda m: errors.append(str(m)))
    _make_toml(tmp_path, "a_casual", [263402786])
    _make_toml(tmp_path, "b_tech", [263402786])
    spaces.reload()
    assert spaces.resolve_space(263402786) == "a_casual"
    assert any("同时出现在空间" in e and "a_casual" in e for e in errors)


def test_explicit_vs_ledger_conflict_warns(tmp_path, monkeypatch):
    """显式名与账本名冲突：先自动分配，再配显式空间 → error 告警提示手工迁移。"""
    errors: list[str] = []
    monkeypatch.setattr(nonebot.logger, "error", lambda m: errors.append(str(m)))
    assert spaces.resolve_space(1001) == "space_1"
    _make_toml(tmp_path, "casual", [1001])
    spaces.reload()
    assert spaces.resolve_space(1001) == "casual"
    assert any("需手工迁移" in e and "space_1" in e and "casual" in e for e in errors)


def test_list_spaces_uses_auto_names(tmp_path, monkeypatch):
    """list_spaces：ALLOWED_GROUPS 里未被显式收录的群走自动命名，而非群号字符串。"""
    monkeypatch.setattr(spaces, "ALLOWED_GROUPS", {1001, 2002})
    _make_toml(tmp_path, "casual", [3003])
    spaces.reload()
    assert spaces.resolve_space(3003) == "casual"
    assert spaces.list_spaces() == sorted({"casual", "space_1", "space_2"})


def test_ledger_corrupt_falls_back_without_allocating(tmp_path, monkeypatch):
    """账本读取失败：不分配新名（避免覆盖读不出的账本），回退到群号字符串。"""
    errors: list[str] = []
    monkeypatch.setattr(nonebot.logger, "error", lambda m: errors.append(str(m)))
    spaces._AUTO_FILE.write_text("{not valid json", encoding="utf-8")
    spaces.reload()
    assert spaces.resolve_space(1001) == "1001"
    assert any("自动命名账本读取失败" in e for e in errors)
