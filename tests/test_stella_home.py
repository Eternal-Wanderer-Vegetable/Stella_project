# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``STELLA_HOME``（用户数据目录）定位的单元测试。

这层的作用是「升级时数据不动」，所以每条定位规则都要有用例：环境变量、机器级
指针文件、旧布局原地兼容、以及默认的同级 StellaData。另有两条硬要求：

- ``import config`` **不许**有副作用（不建目录、不写指针文件）；
- 定位失败一律回退安装目录，绝不抛异常——那会让 Bot 起不来。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from config import home


@pytest.fixture
def install(tmp_path, monkeypatch):
    """一个干净的「安装目录」，且指针文件被隔离到临时目录。"""
    root = tmp_path / "Stella-3.1.0"
    (root / "core").mkdir(parents=True)
    (root / "bot.py").write_text("# entry\n", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("STELLA_HOME", raising=False)
    return root


def test_env_var_wins(install, monkeypatch):
    """环境变量优先级最高（CI、多实例、把数据放到别的盘都靠它）。"""
    target = install.parent / "elsewhere"
    monkeypatch.setenv("STELLA_HOME", str(target))
    resolved = home.resolve(install)
    assert resolved.path == target
    assert "环境变量" in resolved.source


def test_legacy_layout_stays_in_place(install):
    """安装目录里有 .env → 就地使用，3.0.0 及更早的安装零改动继续工作。"""
    (install / ".env").write_text("ALLOWED_GROUPS=1\n", encoding="utf-8")
    resolved = home.resolve(install)
    assert resolved.path == install
    assert "旧布局" in resolved.source


def test_legacy_layout_detected_by_database_too(install):
    """只有记忆库、没有 .env 的目录也算用过（用户可能删过 .env 重配）。"""
    (install / "memory").mkdir()
    (install / "memory" / "agent_memory.db").write_bytes(b"")
    assert home.resolve(install).path == install


def test_default_is_sibling_data_dir_and_not_created(install):
    """默认落在安装目录同级的 StellaData，且 **import 时不创建**。"""
    resolved = home.resolve(install)
    assert resolved.path == (install.parent / "StellaData").resolve()
    assert not resolved.path.exists()  # 没有 create=True 就不许落盘


def test_create_writes_pointer_file(install):
    """create=True 才建目录并写指针文件——指针在程序目录之外，是「升级一步走」的基础。"""
    resolved = home.resolve(install, create=True)
    assert resolved.path.is_dir()
    pointer = home.pointer_path()
    assert pointer.is_file()
    assert pointer.read_text(encoding="utf-8").strip() == str(resolved.path)


def test_pointer_file_is_followed_by_a_fresh_install(install, tmp_path):
    """换一份新解压的程序也能立刻接上老数据：这正是指针文件存在的理由。"""
    data = tmp_path / "StellaData"
    data.mkdir()
    home.write_pointer(data)

    fresh = tmp_path / "Stella-3.2.0"
    (fresh / "core").mkdir(parents=True)
    resolved = home.resolve(fresh)

    assert resolved.path == data
    assert "指针文件" in resolved.source


def test_pointer_takes_precedence_over_default(install, tmp_path):
    """有指针就不该再去猜同级目录。"""
    data = tmp_path / "Elsewhere"
    data.mkdir()
    home.write_pointer(data)
    assert home.resolve(install).path == data


def test_broken_pointer_falls_back_without_raising(install):
    """指针指向不存在的目录 → 当作没有指针，继续往下走，绝不抛异常。"""
    pointer = home.pointer_path()
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("Z:\\nowhere\\at\\all", encoding="utf-8")
    resolved = home.resolve(install)
    assert resolved.path == (install.parent / "StellaData").resolve()


def _paths_with_home(tmp_path: Path, home_dir: Path) -> dict:
    """在子进程里以指定 STELLA_HOME 解析路径。

    必须用子进程：``config/settings.py`` 的常量在 import 时就冻结了，同一个进程里
    改环境变量不会重新解析（这也是 deploy/__main__.py 记录过的坑）。
    """
    from config import PROJECT_ROOT

    env = {
        **dict(__import__("os").environ),
        "STELLA_HOME": str(home_dir),
        "PYTHONPATH": str(PROJECT_ROOT),
    }
    out = subprocess.run(
        [sys.executable, "-m", "deploy", "paths"],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return json.loads(out[out.index("{") : out.rindex("}") + 1])


def test_user_data_paths_follow_stella_home(tmp_path):
    """端到端：所有「丢了心疼」的路径都跟着 STELLA_HOME 走，程序资源不跟。"""
    data = tmp_path / "StellaData"
    data.mkdir()
    paths = _paths_with_home(tmp_path, data)

    assert paths["stella_home"] == str(data)
    assert paths["db_path"] == str(data / "memory" / "agent_memory.db")
    assert paths["log_dir"] == str(data / "logs")
    assert paths["env_file"] == str(data / ".env")
    assert paths["spaces_dir"] == str(data / "config" / "spaces")
    # 程序资源仍在程序目录：升级时该被新版本替换的东西不能挪到数据目录
    assert paths["env_template"].endswith(".env.example")
    assert paths["project_root"] != paths["stella_home"]
