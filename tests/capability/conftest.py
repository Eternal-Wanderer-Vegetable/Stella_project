# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""capability 包的共享夹具。"""

from __future__ import annotations

import types
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例之间清空能力注册表。

    ``registry`` 是模块级单例（必须如此，见 capability/registry.py 的 docstring），
    用例之间不清会互相污染——上一个用例注册的能力会让下一个用例的 routable() 变长。
    """
    from capability.registry import registry

    registry.clear()
    yield
    registry.clear()


@pytest.fixture(autouse=True)
def _clean_llm_tools():
    """清空插件工具注册表与 provider 单例（同为模块级单例）。"""
    from astrbot_compat.llm.manager import reset_provider_manager
    from astrbot_compat.llm.tool import llm_tools

    llm_tools.tools.clear()
    reset_provider_manager()
    yield
    llm_tools.tools.clear()
    reset_provider_manager()


@pytest.fixture(autouse=True)
def _clean_handler_registry():
    """清空 AstrBot handler 注册表——run_tool_loop 会遍历它触发生命周期钩子。"""
    from astrbot_compat.registry import star_handlers_registry, star_map, star_registry

    star_handlers_registry.clear()
    star_map.clear()
    star_registry.clear()
    yield
    star_handlers_registry.clear()
    star_map.clear()
    star_registry.clear()


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    """兜底：任何用例都不许发真实 HTTP 请求。

    Comes 默认启用且默认走本地 LM Studio，忘了打桩的用例在本机跑着模型时会
    「通过」、在 CI 上则挂掉。需要假响应的用例请求 fake_llm 夹具覆盖它
    （非 autouse 夹具在 autouse 之后建立，patch 后来者胜出）。
    """
    import core.llm.openai_client as oc

    def _boom(*args: Any, **kwargs: Any):
        raise AssertionError(
            "测试里发生了真实的 chat-completions 调用。请用 fake_llm 夹具打桩。",
        )

    monkeypatch.setattr(oc, "chat_completion", _boom)
    monkeypatch.setattr(oc, "chat_completion_stream", _boom)


class FakeLLM:
    """假的 chat_completion：记录每次请求，按脚本返回响应。

    与 tests/astrbot_compat/conftest.py 的同名类同形（那份服务插件链路，
    这份服务 Comes 链路）；刻意各自持有一份，避免跨目录 import 测试辅助代码。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._queue: list[dict] = []
        self.default_text = "好的。"

    def push_text(self, text: str) -> None:
        self._queue.append(
            {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {}},
        )

    def push_tool_call(self, name: str, arguments: str, call_id: str = "call_1") -> None:
        self._queue.append(
            {
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
            "choices": [{"message": {"role": "assistant", "content": self.default_text}}],
            "usage": {},
        }

    @property
    def last_messages(self) -> list[dict]:
        return self.calls[-1]["messages"]

    @property
    def last_tools(self) -> list[dict] | None:
        return self.calls[-1].get("tools")

    @property
    def last_tool_names(self) -> list[str]:
        return [t["function"]["name"] for t in (self.last_tools or [])]


@pytest.fixture
def fake_llm(monkeypatch) -> FakeLLM:
    """把 LLM 打桩在 HTTP 层，全程不发真实请求。

    provider 里是在方法内 ``from core.llm.openai_client import chat_completion``，
    调用时才查模块属性，所以 patch 模块属性就能覆盖。
    """
    import core.llm.openai_client as oc

    stub = FakeLLM()
    monkeypatch.setattr(oc, "chat_completion", stub)
    return stub


class FakeBot:
    """记录出站调用的假 bot。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.actions: list[tuple[str, dict]] = []

    async def send(self, event: Any, message: Any) -> None:
        self.sent.append(str(message))

    async def call_action(self, action: str, **kwargs: Any) -> Any:
        self.actions.append((action, kwargs))
        return {}

    async def send_group_msg(self, group_id: int, message: Any) -> None:
        self.actions.append(("send_group_msg", {"group_id": group_id}))
        self.sent.append(str(message))


class FakeNbEvent:
    """最小化的 OneBot v11 事件替身。"""

    def __init__(self, text: str = "帮我查一下东京天气", group_id: int = 1, user_id: int = 111):
        self._text = text
        self.group_id = group_id
        self.user_id = user_id
        self.self_id = 9
        self.message_id = 42
        self.time = 0
        self.sender = types.SimpleNamespace(
            user_id=user_id, nickname="u", card="", role="member",
        )

    def get_message(self) -> list:
        return [types.SimpleNamespace(type="text", data={"text": self._text})]

    def get_plaintext(self) -> str:
        return self._text


@pytest.fixture
def fake_bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def fake_nb_event() -> FakeNbEvent:
    """裸的 OneBot 事件替身，供需要 ctx.raw_event 的用例使用。"""
    return FakeNbEvent()


@pytest.fixture
def astr_event(fake_bot):
    """用真实的 build_event 造 AstrMessageEvent。

    刻意不做替身：Comes 依赖 event 的 is_stopped / get_result / clear_result /
    send 一整套契约，用替身测等于测替身。
    """
    import asyncio

    from astrbot_compat.events import build_event

    return asyncio.run(build_event(FakeNbEvent(), fake_bot))
