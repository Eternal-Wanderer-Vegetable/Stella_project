# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""astrbot_compat 的共享夹具：注入 shim、提供假 OneBot 事件与 Bot。"""

from __future__ import annotations

import types
from typing import Any

import pytest

from astrbot_compat import install_shim

install_shim()


class FakeSender:
    def __init__(self, user_id: int = 111, nickname: str = "u", card: str = "", role: str = "member"):
        self.user_id = user_id
        self.nickname = nickname
        self.card = card
        self.role = role


class FakeBot:
    """记录所有出站调用，便于断言。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.actions: list[tuple[str, dict]] = []
        self.action_results: dict[str, Any] = {}

    async def send(self, event: Any, message: Any) -> None:
        _ = event
        self.sent.append(str(message))

    async def call_action(self, action: str, **kwargs: Any) -> Any:
        self.actions.append((action, kwargs))
        return self.action_results.get(action, {})

    async def send_group_msg(self, group_id: int, message: Any) -> None:
        self.actions.append(("send_group_msg", {"group_id": group_id}))
        self.sent.append(str(message))

    async def send_private_msg(self, user_id: int, message: Any) -> None:
        self.actions.append(("send_private_msg", {"user_id": user_id}))
        self.sent.append(str(message))


def seg(seg_type: str, **data: Any) -> Any:
    return types.SimpleNamespace(type=seg_type, data=data)


class FakeEvent:
    """最小化的 OneBot v11 事件替身。"""

    def __init__(
        self,
        text: str,
        segs: list | None = None,
        group_id: int | None = 1,
        self_id: int = 9,
        user_id: int = 111,
        role: str = "member",
        message_id: int = 42,
    ) -> None:
        self._text = text
        self._segs = segs if segs is not None else [seg("text", text=text)]
        self.group_id = group_id
        self.user_id = user_id
        self.self_id = self_id
        self.message_id = message_id
        self.time = 0
        self.sender = FakeSender(user_id=user_id, role=role)

    def get_message(self) -> list:
        return self._segs

    def get_plaintext(self) -> str:
        return self._text


@pytest.fixture
def fake_bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def make_event():
    """按 `[{"type": "at", "qq": "9"}, ...]` 的简写构造假事件。"""

    def _make(
        text: str,
        segs: list[dict] | None = None,
        group_id: int | None = 1,
        **kwargs: Any,
    ) -> FakeEvent:
        built = None
        if segs is not None:
            built = [seg(d["type"], **{k: v for k, v in d.items() if k != "type"}) for d in segs]
            if text:
                built.append(seg("text", text=text))
        return FakeEvent(text, built, group_id=group_id, **kwargs)

    return _make


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例之间清空注册表，避免 handler 互相污染。"""
    from astrbot_compat.registry import star_handlers_registry, star_map, star_registry

    star_handlers_registry.clear()
    star_map.clear()
    star_registry.clear()
    yield
    star_handlers_registry.clear()
    star_map.clear()
    star_registry.clear()


@pytest.fixture
def register_plugin():
    """把一个 Star 子类登记成「已加载插件」：填元数据、实例化、重绑定 handler。"""
    import functools

    from astrbot_compat.context import Context
    from astrbot_compat.registry import star_handlers_registry, star_map

    def _register(star_cls: type, name: str = "demo", author: str = "tester") -> Any:
        module_path = star_cls.__module__
        md = star_map[module_path]
        md.name = name
        md.author = author
        md.version = "1.0.0"
        md.root_dir_name = name
        inst = star_cls(Context())
        md.star_cls = inst
        for h in star_handlers_registry.get_handlers_by_module_name(module_path):
            raw = h.handler
            if isinstance(raw, functools.partial):
                raw = raw.func
            h.handler = functools.partial(raw, inst)
        md.star_handler_full_names = [
            h.handler_full_name
            for h in star_handlers_registry.get_handlers_by_module_name(module_path)
        ]
        return inst

    return _register
