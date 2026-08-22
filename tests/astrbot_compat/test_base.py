# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Star 基类与 StarTools 的 API 面。"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from astrbot_compat.base import Star, StarTools
from astrbot_compat.context import Context
from astrbot_compat.exceptions import StellaCompatNotSupported


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_DATA_DIR", tmp_path, raising=False)

    class Demo(Star):
        pass

    from astrbot_compat.registry import star_map

    star_map[Demo.__module__].name = "demo"
    return Demo(Context())


def test_command_parser_mixin(plugin):
    # 上游 Star 混入 CommandParserMixin，插件常写 self.parse_commands(...)
    tokens = plugin.parse_commands("/cmd  a   b")
    assert tokens.tokens == ["/cmd", "a", "b"]
    assert tokens.len == 3
    assert tokens.get(1) == "a"
    assert tokens.get(99) is None
    assert plugin.regex_match("hello world", r"wor") is True


def test_render_methods_are_async(plugin):
    # 上游是 async；同步实现会让 `await self.text_to_image(...)` 语义不同
    assert inspect.iscoroutinefunction(Star.text_to_image)
    assert inspect.iscoroutinefunction(Star.html_render)
    with pytest.raises(StellaCompatNotSupported):
        asyncio.run(plugin.text_to_image("hi"))
    with pytest.raises(StellaCompatNotSupported):
        asyncio.run(plugin.html_render("<b></b>", {}))


def test_kv_store_persists(plugin, tmp_path):
    asyncio.run(plugin.put_kv_data("k", {"v": 1}))
    assert (tmp_path / "demo" / "kv.json").exists()
    plugin._kv_store.clear()
    assert asyncio.run(plugin.get_kv_data("k")) == {"v": 1}
    assert asyncio.run(plugin.get_kv_data("missing", "dft")) == "dft"
    asyncio.run(plugin.delete_kv_data("k"))
    assert asyncio.run(plugin.get_kv_data("k")) is None


def test_star_tools_send_message_routes_to_context(monkeypatch):
    calls = []

    class FakeCtx:
        async def send_message(self, session, chain):
            calls.append((session, chain))
            return True

    StarTools.initialize(FakeCtx())
    assert asyncio.run(StarTools.send_message("aiocqhttp:GroupMessage:1", "hi")) is True
    assert calls == [("aiocqhttp:GroupMessage:1", "hi")]
    StarTools._context = None


def test_star_tools_unknown_attr_raises_recognisable_error():
    with pytest.raises(StellaCompatNotSupported):
        StarTools.definitely_not_implemented  # noqa: B018


def test_star_tools_data_dir_creates_directory(monkeypatch, tmp_path):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_PLUGIN_DATA_DIR", tmp_path, raising=False)
    p = StarTools.get_data_dir("someplugin")
    assert p == (tmp_path / "someplugin").resolve()
    assert p.is_dir()


def test_context_llm_methods_raise_but_exist():
    ctx = Context()
    assert hasattr(ctx, "llm_generate")
    with pytest.raises(StellaCompatNotSupported):
        asyncio.run(ctx.llm_generate())
    # property 形态：hasattr 优雅降级为 False，直接访问才抛
    assert hasattr(ctx, "conversation_manager") is False
    with pytest.raises(StellaCompatNotSupported):
        _ = ctx.conversation_manager


def test_context_star_registry_views():
    from astrbot_compat.registry import StarMetadata, star_registry

    active = StarMetadata(name="on", author="a")
    inactive = StarMetadata(name="off", author="a", activated=False)
    star_registry.extend([active, inactive])
    ctx = Context()
    assert ctx.get_all_stars() == [active]
    assert ctx.get_registered_star("on") is active
    assert ctx.get_registered_star("off") is None
