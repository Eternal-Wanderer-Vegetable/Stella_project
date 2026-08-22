# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""加载器：从磁盘装载一个真实插件目录并跑通生命周期。

模块路径写死为 `data.plugins.<目录名>.main`，无法搬到 tmp_path，
因此夹具在真实的 data/plugins/ 下建插件（该目录已被 .gitignore 忽略），用完删掉。

CI 用 `pytest -n auto --dist loadgroup` 并行跑，多个 worker 共享同一个
data/plugins/ 目录。所以这里的每个用例都必须自带唯一目录名与唯一插件名：
共用固定名字会互相 mkdir 撞车、互相 rmtree、互相在注册表里塞重复 handler。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid

import pytest

from astrbot_compat import loader
from astrbot_compat.base import StarTools

pytestmark = pytest.mark.xdist_group("astrbot_compat_loader")

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

    @filter.command("{command}")
    async def selftest(self, event, n: int = 1):
        """自检指令"""
        yield event.plain_result(f"ok:{{n}}")
'''

METADATA_YAML = """
name: {name}
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


class InstalledPlugin:
    """一个已落盘的临时插件，带上它的唯一标识。"""

    def __init__(self, path, dir_name: str, plugin_name: str, command: str) -> None:
        self.path = path
        self.dir_name = dir_name
        self.plugin_name = plugin_name
        self.command = command
        self.module_name = f"data.plugins.{dir_name}.main"


@pytest.fixture
def install_plugin(tmp_path, monkeypatch):
    """在 data/plugins/ 下装一个名字唯一的插件，测试结束后清理干净。"""
    from config import settings

    plugins_dir = settings.PROJECT_ROOT / "data" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_CONFIG_DIR", tmp_path / "cfg", raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_DATA_DIR", tmp_path / "pdata", raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", True, raising=False)
    loader._failed.clear()
    loader._loaded_dirs.clear()

    created: list[InstalledPlugin] = []

    def _install() -> InstalledPlugin:
        # 唯一后缀：并行 worker 之间不能共用目录名，也不能共用指令名
        # （两个插件都注册 /selftest 的话，分发会命中两次）
        token = uuid.uuid4().hex[:12]
        dir_name = f"stella_compat_selftest_{token}"
        plugin_name = f"selftest_{token}"
        command = f"selftest{token}"
        path = plugins_dir / dir_name
        path.mkdir()
        (path / "main.py").write_text(
            MAIN_PY.format(command=command),
            encoding="utf-8",
        )
        (path / "metadata.yaml").write_text(
            METADATA_YAML.format(name=plugin_name),
            encoding="utf-8",
        )
        (path / "_conf_schema.json").write_text(json.dumps(CONF_SCHEMA), encoding="utf-8")
        installed = InstalledPlugin(path, dir_name, plugin_name, command)
        created.append(installed)
        return installed

    yield _install

    for installed in created:
        for mod in [m for m in sys.modules if m.startswith(f"data.plugins.{installed.dir_name}")]:
            sys.modules.pop(mod, None)
        shutil.rmtree(installed.path, ignore_errors=True)
    loader._failed.clear()
    loader._loaded_dirs.clear()


def test_load_plugin_reads_full_metadata(install_plugin):
    p = install_plugin()
    md = loader.load_plugin(p.path)

    assert md is not None
    assert md.name == p.plugin_name
    assert md.author == "tester"
    assert md.version == "1.2.3"
    assert md.desc == "自检插件"
    assert md.display_name == "自检"
    assert md.support_platforms == ["aiocqhttp"]
    assert md.plugin_id == f"tester/{p.plugin_name}"  # 上游格式：author/name，保留斜杠
    assert md.root_dir_name == p.dir_name
    assert md.config["greeting"] == "hi"
    assert md.star_cls is not None
    assert md.star_handler_full_names


def test_handler_desc_falls_back_to_docstring(install_plugin):
    from astrbot_compat.registry import star_handlers_registry

    p = install_plugin()
    loader.load_plugin(p.path)

    handler = star_handlers_registry.get_handler_by_full_name(f"{p.module_name}_selftest")
    assert handler is not None
    assert handler.desc == "自检指令"


def test_discovery_finds_the_plugin(install_plugin):
    p = install_plugin()
    # 并行 worker 可能同时装着自己的插件，只断言自己的那个在里面
    assert p.path in loader.discover_plugins()
    assert p.plugin_name in [md.name for md in loader.load_all_plugins()]


def test_lifecycle_hooks_are_called(install_plugin):
    p = install_plugin()
    loader.load_plugin(p.path)

    mod = sys.modules[p.module_name]
    assert mod.TRACE == ["init"]
    asyncio.run(loader.initialize_plugins())
    assert "initialize" in mod.TRACE
    asyncio.run(loader.terminate_plugins())
    assert "terminate" in mod.TRACE


def test_terminate_timeout_is_reported_as_timeout(install_plugin, caplog, monkeypatch):
    """terminate 超时要走「超时」分支而不是「异常」分支。

    这条在 Python 3.10 上才有区分力：3.10 的 asyncio.TimeoutError 与内置
    TimeoutError 是两个不相干的类，接错了就会漏到 except Exception；
    3.11 起两者合并，这条退化为恒真。CI 跑 3.10，所以留着有意义。
    """
    p = install_plugin()
    md = loader.load_plugin(p.path)

    async def hang():
        await asyncio.sleep(3600)

    md.star_cls.terminate = hang

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(aw, timeout):
        _ = timeout
        return await original_wait_for(aw, 0.01)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)

    with caplog.at_level("WARNING"):
        asyncio.run(loader.terminate_plugins())

    assert any("terminate 超时" in r.message for r in caplog.records)
    assert not any("terminate 异常" in r.message for r in caplog.records)


def test_loaded_plugin_responds_to_command(install_plugin, make_event, fake_bot):
    from astrbot_compat.pipeline import dispatch

    p = install_plugin()
    loader.load_plugin(p.path)

    assert asyncio.run(dispatch(make_event(f"/{p.command} 3"), fake_bot)) is True
    assert fake_bot.sent == ["ok:3"]


def test_two_plugins_load_independently(install_plugin, make_event, fake_bot):
    # 同时装两个结构相同、名字不同的插件：注册表不该串味
    first = install_plugin()
    second = install_plugin()
    loader.load_plugin(first.path)
    loader.load_plugin(second.path)

    from astrbot_compat.pipeline import dispatch

    assert asyncio.run(dispatch(make_event(f"/{second.command} 7"), fake_bot)) is True
    assert fake_bot.sent == ["ok:7"]


def test_data_dir_uses_declared_plugin_name(install_plugin, tmp_path):
    p = install_plugin()
    loader.load_plugin(p.path)

    # 上游按 metadata 的 name 建目录，而不是仓库克隆下来的目录名
    path = StarTools.get_data_dir(p.plugin_name)
    assert path == (tmp_path / "pdata" / p.plugin_name).resolve()
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
    loader._failed.clear()


def test_disabled_compat_skips_loading(monkeypatch):
    from astrbot_compat.registry import star_map, star_registry
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", False, raising=False)
    assert loader.load_all_plugins() == []
    assert star_map == {}
    assert star_registry == []


# ---------------------------------------------------------------------------
# 并行安全：CI 的多个 worker 共享同一个 data/plugins/，会互相删目录、互相抢缓存
# ---------------------------------------------------------------------------


def test_discovery_survives_directory_vanishing_mid_scan(tmp_path, monkeypatch):
    """别的 worker 在扫描途中 rmtree 自己的插件目录，不该让整次发现崩掉。"""
    from pathlib import Path

    from config import settings

    plugins_dir = tmp_path / "plugins"
    (plugins_dir / "alive").mkdir(parents=True)
    (plugins_dir / "doomed").mkdir()
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir, raising=False)

    real_is_dir = Path.is_dir

    def flaky_is_dir(self):
        if self.name == "doomed":
            raise OSError(2, "No such file or directory")
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", flaky_is_dir)
    assert [p.name for p in loader.discover_plugins()] == ["alive"]


def test_discovery_survives_unreadable_plugins_dir(tmp_path, monkeypatch):
    from pathlib import Path

    from config import settings

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir, raising=False)
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: (_ for _ in ()).throw(OSError(13, "Permission denied")),
    )
    assert loader.discover_plugins() == []


def test_import_retries_after_invalidating_stale_cache(monkeypatch):
    """命名空间包会缓存目录清单，新建的插件目录首次导入可能假性找不到。"""
    calls = {"import": 0, "invalidate": 0}
    sentinel = object()

    def fake_import(name):
        calls["import"] += 1
        if calls["import"] == 1:
            raise ModuleNotFoundError(f"No module named {name!r}")
        return sentinel

    # 打在 loader 引用的那个 importlib 上
    monkeypatch.setattr(loader.importlib, "import_module", fake_import)
    monkeypatch.setattr(
        loader.importlib,
        "invalidate_caches",
        lambda: calls.__setitem__("invalidate", calls["invalidate"] + 1),
    )

    assert loader._import_plugin_module("data.plugins.x.main") is sentinel
    assert calls == {"import": 2, "invalidate": 1}


def test_plugin_created_after_namespace_import_is_loadable(install_plugin):
    """先把 data.plugins 导进来把缓存坐实，再新建插件目录，仍应能加载。"""
    import importlib

    importlib.import_module("data.plugins")
    p = install_plugin()
    assert loader.load_plugin(p.path) is not None
