# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""插件热重载：摘干净、装回来、能力归属被释放。

与 ``test_loader.py`` 同一个约束：模块路径写死为 ``data.plugins.<目录名>.main``，
所以插件必须建在真实的 ``data/plugins/`` 下（该目录已被 .gitignore 忽略）。
CI 用 ``pytest -n auto --dist loadgroup`` 并行跑，每个用例都自带唯一目录名与
唯一工具名，否则多个 worker 会互相 rmtree、互相往工具表里塞同名工具。

这里盯住的核心是 ``_claimed_tools``：不释放的话重载后插件的声明**抢不到自己的
工具**（``_claim`` 先到先得），而这不报错，只表现为「重载完就路由不到了」。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import uuid

import pytest

from astrbot_compat import loader
from astrbot_compat.registry import star_handlers_registry, star_registry
from capability.registry import registry as capability_registry

pytestmark = pytest.mark.xdist_group("astrbot_compat_loader")


MAIN_PY = '''
from astrbot.api.star import Star
from astrbot.api.event import filter

MARK = "{mark}"
TRACE = []


class SelfTest(Star):
    def __init__(self, context, config=None):
        super().__init__(context, config)
        TRACE.append("init")

    async def initialize(self):
        TRACE.append("initialize")
        self.context.register_task(self._forever(), "poller")

    async def _forever(self):
        await asyncio.sleep(3600)

    async def terminate(self):
        TRACE.append("terminate")

    @filter.command("{command}")
    async def selftest(self, event):
        """自检指令"""
        yield event.plain_result(MARK)

    @filter.llm_tool("{tool}")
    async def query_something(self, event):
        """查一件事。"""
        return MARK
'''

METADATA_YAML = """
name: {name}
author: tester
desc: 热重载自检插件
version: 1.0.0
"""

CAPABILITY_TOML = """
[[capability]]
id = "{cap_id}"
domain = "information"
description = "自检能力"
examples = ["帮我查一件事", "这件事怎么样了"]
providers = ["{tool}"]
"""


class Installed:
    def __init__(self, path, dir_name, plugin_name, command, tool, cap_id) -> None:
        self.path = path
        self.dir_name = dir_name
        self.plugin_name = plugin_name
        self.command = command
        self.tool = tool
        self.cap_id = cap_id
        self.package = f"data.plugins.{dir_name}"
        self.module_name = f"{self.package}.main"


@pytest.fixture
def install_plugin(tmp_path, monkeypatch):
    """在真实 data/plugins/ 下装一个自带声明的插件；用完删干净。"""
    from config import settings

    plugins_dir = settings.PROJECT_ROOT / "data" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGINS_DIR", plugins_dir, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_CONFIG_DIR", tmp_path / "cfg", raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_DATA_DIR", tmp_path / "pdata", raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_AUTO_INSTALL_REQUIREMENTS", False, raising=False)
    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED", True, raising=False)
    # 重载末尾会重跑能力装配；预热要真发 embedding 请求，测试里一律关掉
    monkeypatch.setattr(settings, "ROUTER_SEMANTIC_ENABLED", False, raising=False)
    loader._failed.clear()
    loader._loaded_dirs.clear()
    loader._detached.clear()

    created: list[Installed] = []

    def _install(*, mark: str = "v1", with_declaration: bool = True) -> Installed:
        token = uuid.uuid4().hex[:12]
        dir_name = f"stella_reload_selftest_{token}"
        p = Installed(
            path=plugins_dir / dir_name,
            dir_name=dir_name,
            plugin_name=f"reload_selftest_{token}",
            command=f"reload{token}",
            tool=f"reload_tool_{token}",
            cap_id=f"reload.selftest.{token}",
        )
        p.path.mkdir()
        _write(p, mark=mark, with_declaration=with_declaration)
        created.append(p)
        return p

    def _write(p: Installed, *, mark: str, with_declaration: bool = True) -> None:
        (p.path / "main.py").write_text(
            "import asyncio\n" + MAIN_PY.format(mark=mark, command=p.command, tool=p.tool),
            encoding="utf-8",
        )
        (p.path / "metadata.yaml").write_text(
            METADATA_YAML.format(name=p.plugin_name),
            encoding="utf-8",
        )
        if with_declaration:
            (p.path / "capability.toml").write_text(
                CAPABILITY_TOML.format(cap_id=p.cap_id, tool=p.tool),
                encoding="utf-8",
            )

    _install.rewrite = _write  # type: ignore[attr-defined]
    yield _install

    for p in created:
        for mod in [m for m in sys.modules if m.startswith(p.package)]:
            sys.modules.pop(mod, None)
        shutil.rmtree(p.path, ignore_errors=True)
    loader._failed.clear()
    loader._loaded_dirs.clear()
    loader._detached.clear()


@pytest.fixture(autouse=True)
def _clean_capability_registry():
    capability_registry.clear()
    yield
    capability_registry.clear()


async def _boot(p: Installed):
    """加载插件 → initialize → 跑一遍能力装配，等价于启动时那条链。"""
    from capability.adapters.astrbot import bootstrap

    md = loader.load_plugin(p.path)
    assert md is not None
    if md.star_cls is not None:
        await md.star_cls.initialize()
    bootstrap()
    return md


# ---------------------------------------------------------------- 命令解析


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("重载插件 astrbot_plugin_x", "astrbot_plugin_x"),
        ("重新加载插件 foo", "foo"),
        ("重载插件foo。", "foo"),
        ("帮我重载插件 foo，谢谢", "foo"),
        ("重载插件", None),
        ("重载插件   ", None),
        ("你能做什么", None),
        ("安静", None),
    ],
)
def test_parse_reload_command(text, expected):
    assert loader.parse_reload_command(text) == expected


def test_reload_command_name_may_look_like_a_toggle_word():
    """插件名是任意字符串：命中开关词也必须仍被解析成重载命令。

    ai_gateway 里三个 handler 同优先级且都 block=True，互斥全靠这条判据。
    """
    assert loader.parse_reload_command("重载插件 恢复") == "恢复"
    assert loader.parse_reload_command("重载插件 你能做什么") == "你能做什么"


# ---------------------------------------------------------------- 开关


def test_reload_refused_when_disabled(install_plugin, monkeypatch):
    from config import settings

    p = install_plugin()

    async def scenario():
        await _boot(p)
        monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED", False, raising=False)
        return await loader.reload_plugin(p.dir_name)

    assert asyncio.run(scenario()) is None
    # 拒绝不等于卸载：原插件必须原封不动
    assert p.dir_name in {md.root_dir_name for md in star_registry}


def test_reload_unknown_plugin_returns_none(install_plugin):
    install_plugin()  # 至少装一个，保证不是「注册表为空」造成的 None

    async def scenario():
        return await loader.reload_plugin("no_such_plugin_dir")

    assert asyncio.run(scenario()) is None


# ---------------------------------------------------------------- 重载主流程


def test_reload_picks_up_source_changes(install_plugin):
    """改一行源码重载后，新代码必须真的生效。

    这条同时钉住两层缓存：``sys.modules``（不清就 import 直接命中）与
    ``__pycache__``（``.pyc`` 只按「源文件 mtime 整秒 + 字节数」判有效性）。
    夹具里 v1 → v2 恰好**同字节数、同一秒内**写入，正是调试时最常见的那种编辑
    ——不清字节码的话这条会拿到旧的 MARK，而重载仍然报成功。
    """
    p = install_plugin()

    async def scenario():
        await _boot(p)
        install_plugin.rewrite(p, mark="v2")
        return await loader.reload_plugin(p.dir_name)

    md = asyncio.run(scenario())

    assert md is not None
    assert sys.modules[p.module_name].MARK == "v2"
    assert loader.get_failed_plugins() == {}


def test_reload_leaves_exactly_one_handler_and_one_tool(install_plugin):
    """重载不能留下旧 handler / 旧工具：留下的话一条指令会被响应两次。"""
    from astrbot_compat.llm.tool import llm_tools

    p = install_plugin()

    async def scenario():
        await _boot(p)
        return await loader.reload_plugin(p.dir_name)

    assert asyncio.run(scenario()) is not None

    own = [h for h in star_handlers_registry if h.handler_module_path.startswith(p.package)]
    assert len(own) == 2  # 一个 @command + 一个 @llm_tool
    assert [t.name for t in llm_tools.tools].count(p.tool) == 1
    assert [md.root_dir_name for md in star_registry].count(p.dir_name) == 1


def test_reload_releases_and_reclaims_the_tool(install_plugin):
    """``_claimed_tools`` 必须被释放，否则重载后插件的声明抢不到自己的工具。

    这是热重载最容易漏的一条：不报错，只表现为「重载完就路由不到了」。
    """
    p = install_plugin()
    seen: dict[str, object] = {}

    async def scenario():
        await _boot(p)
        seen["before"] = capability_registry.claimed_by(p.tool)
        await loader.reload_plugin(p.dir_name)
        seen["after"] = capability_registry.claimed_by(p.tool)

    asyncio.run(scenario())

    assert seen["before"] == p.cap_id
    assert seen["after"] == p.cap_id
    capability = capability_registry.get(p.cap_id)
    assert capability is not None
    # 声明重新生效了才算数：examples 在，能力可路由
    assert capability.examples
    assert p.cap_id in {c.id for c in capability_registry.routable()}


def test_reload_purges_the_module_tree(install_plugin):
    """插件包及其子模块都要从 sys.modules 里摘掉，否则 import 直接命中缓存。"""
    p = install_plugin()

    async def scenario():
        await _boot(p)
        (p.path / "extra.py").write_text("VALUE = 1\n", encoding="utf-8")
        __import__(f"{p.package}.extra")
        assert f"{p.package}.extra" in sys.modules
        detached = loader._purge_modules(p.package)
        assert detached >= 2
        assert not [m for m in sys.modules if m.startswith(p.package)]

    asyncio.run(scenario())


def test_reload_cancels_registered_tasks(install_plugin):
    """插件走 register_task 起的后台任务必须在重载时被取消（归属标记生效）。"""
    from astrbot_compat.context import get_context

    p = install_plugin()
    seen: dict[str, object] = {}

    async def scenario():
        await _boot(p)
        ctx = get_context()
        started = [t for t, owner in ctx._tasks.items() if owner.startswith(p.package)]
        seen["started"] = len(started)
        await loader.reload_plugin(p.dir_name)
        await asyncio.sleep(0)
        seen["cancelled"] = all(t.cancelled() or t.done() for t in started)
        # 重载后新实例又登记了一个，归属仍在
        seen["after"] = len(
            [t for t, owner in ctx._tasks.items() if owner.startswith(p.package)]
        )
        get_context().cancel_tasks()

    asyncio.run(scenario())

    assert seen["started"] == 1
    assert seen["cancelled"] is True
    assert seen["after"] == 1


def test_terminate_failure_still_completes_the_reload(install_plugin):
    """terminate 抛异常不能留下半初始化状态：卸载照走，插件照样装回来。"""
    p = install_plugin()

    async def scenario():
        md = await _boot(p)

        async def boom():
            raise RuntimeError("terminate 炸了")

        md.star_cls.terminate = boom
        return await loader.reload_plugin(p.dir_name)

    fresh = asyncio.run(scenario())

    assert fresh is not None
    assert [md.root_dir_name for md in star_registry].count(p.dir_name) == 1
    assert capability_registry.claimed_by(p.tool) == p.cap_id


def test_reload_reports_failure_when_new_code_is_broken(install_plugin):
    """新代码 import 失败时返回 None，并把原因留在 get_failed_plugins()。

    不回滚是刻意的：旧模块已经从 sys.modules 里摘掉了，没有可回滚的东西。
    用户改完再重载一次即可。
    """
    p = install_plugin()

    async def scenario():
        await _boot(p)
        (p.path / "main.py").write_text("import definitely_not_installed_pkg\n", encoding="utf-8")
        return await loader.reload_plugin(p.dir_name)

    assert asyncio.run(scenario()) is None
    assert "definitely_not_installed_pkg" in loader.get_failed_plugins()[p.dir_name]
    assert p.dir_name not in {md.root_dir_name for md in star_registry}


def test_reload_recovers_after_a_broken_reload(install_plugin):
    """把插件改坏、重载失败之后，改回来必须还能再重载一次。

    这条序列（改代码 → 重载 → 语法错 → 装不回来）在调试时必然发生。失败之后插件已经
    不在 star_registry 里了，只按「已加载插件」找的话用户改完错字反而只能重启——而
    重启正是热重载要省掉的那件事。
    """
    p = install_plugin()

    async def scenario():
        await _boot(p)
        (p.path / "main.py").write_text("import definitely_not_installed_pkg\n", encoding="utf-8")
        assert await loader.reload_plugin(p.dir_name) is None
        install_plugin.rewrite(p, mark="v3")
        return await loader.reload_plugin(p.dir_name)

    md = asyncio.run(scenario())

    assert md is not None
    assert md.root_dir_name == p.dir_name
    assert sys.modules[p.module_name].MARK == "v3"
    # 装回来了就不该再留着「上次没装回来」的记录
    assert p.dir_name not in loader._detached
    # 能力也要跟着回来
    assert capability_registry.claimed_by(p.tool) == p.cap_id


def test_reload_accepts_the_plugin_display_name(install_plugin):
    """群里的人看到的可能是插件名而不是目录名，两者都要认。"""
    p = install_plugin()

    async def scenario():
        await _boot(p)
        return await loader.reload_plugin(p.plugin_name)

    md = asyncio.run(scenario())

    assert md is not None
    assert md.root_dir_name == p.dir_name


# ---------------------------------------------------------------- watch 模式


def test_source_stamp_tracks_py_and_declaration_only(install_plugin):
    """mtime 快照只认 *.py 与 capability.toml——数据目录会一直变，算进来就每轮都重载。"""
    p = install_plugin()

    async def scenario():
        md = await _boot(p)
        before = loader.plugin_source_stamp(md)
        # 无关文件不该推进快照
        (p.path / "cache.bin").write_bytes(b"x")
        same = loader.plugin_source_stamp(md)
        install_plugin.rewrite(p, mark="v2")
        after = loader.plugin_source_stamp(md)
        return before, same, after

    before, same, after = asyncio.run(scenario())

    assert before > 0
    assert same == before
    assert after >= before


def test_source_stamps_cover_every_loaded_plugin(install_plugin):
    p = install_plugin()

    async def scenario():
        await _boot(p)
        return loader.plugin_source_stamps()

    stamps = asyncio.run(scenario())

    assert stamps[p.dir_name] > 0
