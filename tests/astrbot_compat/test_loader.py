# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""加载器：从磁盘装载一个真实插件目录并跑通生命周期。

模块路径是写死的 `data.plugins.<目录名>.main`，无法搬到 tmp_path，
因此夹具在真实的 data/plugins/ 下建临时插件（该目录已被 .gitignore 忽略），用完删掉。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys

import pytest

from astrbot_compat import loader
from astrbot_compat.base import StarTools
from astrbot_compat.registry import star_handlers_registry, star_map, star_registry

PLUGIN_DIR_NAME = "stella_compat_selftest"

MAIN_PY = '''
from astrbot.api.star import Star
from astrbot.api.event import filter

TRACE = []


class SelfTest(Star):
    def __init__(self, context, config=None):
        super().__init__(context, config)
        TRACE.append("init")

    async def initialize(self):
        TRACE.append("initialize")

    async def terminate(self):
        TRACE.append("terminate")

    @filter.command("selftest")
    async def selftest(self, event, n: int = 1):
        """自检指令"""
        yield event.plain_result(f"ok:{n}")
'''

METADATA_YAML = """
name: selftest
author: tester
desc: 自检插件
version: 1.2.3
repo: https://example.invalid/selftest
display_name: 自检
support_platforms:
  - aiocqhttp
astrbot_version: ">=4.0.0"
"""

CONF_SCHEMA = {"greeting": {"type": "string", "default": "hi"}}


@pytest.fixture
def installed_plugin(tmp_path, monkeypatch):
    from config import settings

    plugins_dir = settings.PROJECT_ROOT / "data" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    plugin_dir = plugins_dir / PLUGIN_DIR_NAME
    shutil.rmtree(plugin_dir, ignore_errors=True)
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(MAIN_PY, encoding="utf-8")
    (plugin_dir / "metadata.yaml").write_text(METADATA_YAML, encoding="utf-8")
    (plugin_dir / "_conf_schema.json").write_text(
        json.dumps(CONF_SCHEMA),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_CONFIG_DIR", tmp_path / "cfg", raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_DATA_DIR", tmp_path / "pdata", raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", True, raising=False)
    loader._failed.clear()
    loader._loaded_dirs.clear()

    yield plugin_dir

    for mod in [m for m in sys.modules if m.startswith(f"data.plugins.{PLUGIN_DIR_NAME}")]:
        sys.modules.pop(mod, None)
    shutil.rmtree(plugin_dir, ignore_errors=True)
    loader._failed.clear()
    loader._loaded_dirs.clear()


def test_load_all_plugins_end_to_end(installed_plugin):
    loaded = loader.load_all_plugins()
    names = [md.name for md in loaded]
    assert "selftest" in names

    md = next(m for m in loaded if m.name == "selftest")
    assert md.author == "tester"
    assert md.version == "1.2.3"
    assert md.desc == "自检插件"
    assert md.display_name == "自检"
    assert md.support_platforms == ["aiocqhttp"]
    assert md.plugin_id == "tester/selftest"  # 上游格式：author/name，保留斜杠
    assert md.root_dir_name == PLUGIN_DIR_NAME
    assert md.config["greeting"] == "hi"
    assert md.star_cls is not None
    assert md.star_handler_full_names

    # 指令元数据：desc 应回落到 handler 的 docstring
    handler = star_handlers_registry.get_handler_by_full_name(
        f"data.plugins.{PLUGIN_DIR_NAME}.main_selftest",
    )
    assert handler is not None
    assert handler.desc == "自检指令"


def test_lifecycle_hooks_are_called(installed_plugin):
    loader.load_all_plugins()
    mod = sys.modules[f"data.plugins.{PLUGIN_DIR_NAME}.main"]
    asyncio.run(loader.initialize_plugins())
    assert "initialize" in mod.TRACE
    asyncio.run(loader.terminate_plugins())
    assert "terminate" in mod.TRACE


def test_loaded_plugin_responds_to_command(installed_plugin, make_event, fake_bot):
    from astrbot_compat.pipeline import dispatch

    loader.load_all_plugins()
    assert asyncio.run(dispatch(make_event("/selftest 3"), fake_bot)) is True
    assert fake_bot.sent == ["ok:3"]


def test_data_dir_uses_declared_plugin_name(installed_plugin, tmp_path):
    loader.load_all_plugins()
    # 上游按 metadata 的 name 建目录，而不是仓库克隆下来的目录名
    path = StarTools.get_data_dir("selftest")
    assert path == (tmp_path / "pdata" / "selftest").resolve()
    assert path.is_dir()


def test_bad_directory_name_is_reported(tmp_path, monkeypatch):
    from config import settings

    plugins_dir = tmp_path / "plugins"
    (plugins_dir / "not-an-identifier").mkdir(parents=True)
    (plugins_dir / "not-an-identifier" / "main.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", True, raising=False)
    loader._failed.clear()

    assert loader.load_all_plugins() == []
    assert "not-an-identifier" in loader.get_failed_plugins()


def test_disabled_compat_skips_loading(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", False, raising=False)
    assert loader.load_all_plugins() == []
    assert star_map == {}
    assert star_registry == []
