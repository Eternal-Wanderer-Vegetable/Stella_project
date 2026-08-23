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


@pytest.fixture(autouse=True)
def _clean_llm_state():
    """清掉全局工具表与 provider 单例，避免用例之间串味。"""
    from astrbot_compat.llm.manager import reset_provider_manager
    from astrbot_compat.llm.tool import llm_tools

    llm_tools.tools.clear()
    reset_provider_manager()
    yield
    llm_tools.tools.clear()
    reset_provider_manager()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """兜底：任何用例都不许发真实 HTTP 请求。

    LLM 现在默认是**开启**的（ASTRBOT_LLM_ENABLED=true），所以忘了用 fake_llm 的
    用例会直接打到本机 LM Studio——本机跑着模型时它会"通过"，CI 上则挂掉。
    这里先把两个出口换成会炸的桩，需要假响应的用例再请求 fake_llm 夹具覆盖它
    （非 autouse 夹具在 autouse 之后建立，patch 会后来者胜出）。
    """
    import core.llm.openai_client as oc

    def _boom(*args: Any, **kwargs: Any):
        raise AssertionError(
            "测试里发生了真实的 chat-completions 调用。"
            "请用 fake_llm 夹具打桩，或把 ASTRBOT_LLM_ENABLED 设为 False。",
        )

    monkeypatch.setattr(oc, "chat_completion", _boom)
    monkeypatch.setattr(oc, "chat_completion_stream", _boom)


class FakeLLM:
    """假的 chat_completion。记录每次请求，按脚本返回响应。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._queue: list[dict] = []
        self.default_text = "好的。"

    def push(self, raw: dict) -> None:
        """排一个原始响应。用完队列后回落到 default_text。"""
        self._queue.append(raw)

    def push_text(self, text: str) -> None:
        self.push(
            {
                "id": "resp",
                "choices": [{"message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    def push_tool_call(self, name: str, arguments: str, call_id: str = "call_1") -> None:
        self.push(
            {
                "id": "resp",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {"name": name, "arguments": arguments},
                                },
                            ],
                        },
                    },
                ],
                "usage": {},
            },
        )

    async def __call__(self, messages: list[dict], **kwargs: Any) -> dict:
        self.calls.append({"messages": messages, **kwargs})
        if self._queue:
            return self._queue.pop(0)
        return {
            "id": "resp",
            "choices": [{"message": {"role": "assistant", "content": self.default_text}}],
            "usage": {},
        }

    @property
    def last_messages(self) -> list[dict]:
        return self.calls[-1]["messages"]

    @property
    def last_tools(self) -> list[dict] | None:
        return self.calls[-1].get("tools")


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    """把 LLM 打桩在 HTTP 层，全程不发真实请求。

    provider 里是在方法内 `from core.llm.openai_client import chat_completion`，
    这种写法在调用时才查模块属性，所以 patch 模块属性就能覆盖。
    """
    import core.llm.openai_client as oc

    stub = FakeLLM()
    monkeypatch.setattr(oc, "chat_completion", stub)
    return stub


@pytest.fixture
def llm_db(tmp_path, monkeypatch):
    """把兼容层的会话 / 偏好表指到临时库，并清掉进程内缓存。

    沿用项目惯例：patch 各模块自己绑定的 DB_PATH，而不是 config.DB_PATH
    （每个模块在 import 时就把值绑死了）。
    """
    from astrbot_compat import conversation as conv_mod
    from astrbot_compat import preferences as pref_mod

    db = tmp_path / "astrbot_compat.db"
    monkeypatch.setattr(pref_mod, "DB_PATH", db)
    monkeypatch.setattr(conv_mod, "DB_PATH", db)
    pref_mod.sp.reset_cache()
    conv_mod.get_conversation_manager().reset_cache()
    yield db
    pref_mod.sp.reset_cache()
    conv_mod.get_conversation_manager().reset_cache()


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
