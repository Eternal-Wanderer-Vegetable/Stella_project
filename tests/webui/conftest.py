# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""webui 测试夹具。

要点（与 tests/test_status_api.py 同一套手法）：
- 目录**不带 __init__.py**——tests/<pkg>/ 带 __init__.py 会在 pytest prepend
  模式下遮蔽顶层同名包（tests/knowledge 的历史教训）；
- webui.routers.status 导入 ``plugins.bot_main.status_api``，源码直跑时该包
  在 ``stella_project/`` 下且其 __init__ 会拉起 ai_gateway（重副作用，import
  期就调 nonebot.get_plugin_config）。先占位一个假包（只指路径、不执行
  __init__），再按需导入真子模块。**注意本文件比 tests/ 深一层，仓库根是
  parents[2] 而不是 parents[1]**——插错层级 sys.path 指到 tests/，首个
  路径分支失效，会静默落到触发 NoneBot 副作用的那条分支（实测）；
- 所有 webui 模块在**调用时**读 config.settings 属性，因此夹具只需
  monkeypatch settings 的 STELLA_HOME / PROJECT_ROOT / LOG_DIR 即可把
  凭据、dist 与审计日志整体隔离进临时目录。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJ / "stella_project"))

_fake_bot_main = types.ModuleType("plugins.bot_main")
_fake_bot_main.__path__ = [str(_PROJ / "stella_project" / "plugins" / "bot_main")]
sys.modules.setdefault("plugins.bot_main", _fake_bot_main)

from fastapi.testclient import TestClient

import config.settings as settings
from webui.app import create_webui_app


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 STELLA_HOME / PROJECT_ROOT / LOG_DIR 全部指到临时目录：
    auth.json、webui/dist 探测、审计日志互不串扰，也不碰开发机真实数据。"""
    monkeypatch.setattr(settings, "STELLA_HOME", tmp_path)
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(settings, "LOG_DIR", tmp_path / "logs")
    return tmp_path


@pytest.fixture
def client(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """关闭静态托管的纯 API 客户端；每个用例独立 app（限流桶随 app 重建）。"""
    monkeypatch.setattr(settings, "WEBUI_SERVE_DIST", False)
    return TestClient(create_webui_app())


@pytest.fixture
def make_dist(isolated_home: Path):
    """造一个最小 dist：index.html + 一个资产文件。返回 dist 目录路径。"""

    def _make(marker: str = "stella-m0-dist") -> Path:
        dist = isolated_home / "webui" / "dist"
        (dist / "assets").mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text(f"<html>{marker}</html>", encoding="utf-8")
        (dist / "assets" / "app.js").write_text("/*app*/", encoding="utf-8")
        return dist

    return _make
