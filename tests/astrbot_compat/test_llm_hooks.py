# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 生命周期钩子：触发顺序与实参。"""

from __future__ import annotations

import asyncio

import astrbot_compat.filters as filter  # noqa: A004  # 插件侧惯用名
from astrbot_compat.base import Star
from astrbot_compat.events import build_event
from astrbot_compat.llm import ProviderRequest, ToolSet
from astrbot_compat.pipeline import run_provider_request


def _tool(handler, **kwargs):
    from astrbot_compat.llm import FunctionTool

    return FunctionTool(name="t", handler=handler, **kwargs)


def _run(event, req):
    return asyncio.run(run_provider_request(event, req))


def test_hook_order_without_tools(register_plugin, fake_llm, fake_bot, make_event):
    seen: list[str] = []

    class Demo(Star):
        @filter.on_waiting_llm_request()
        async def a(self, event):
            seen.append("waiting")

        @filter.on_llm_request()
        async def b(self, event, req):
            seen.append("request")

        @filter.on_llm_response()
        async def c(self, event, resp):
            seen.append("response")

        @filter.on_agent_begin()
        async def d(self, event, run_context):
            seen.append("agent_begin")

        @filter.on_agent_done()
        async def e(self, event, run_context, resp):
            seen.append("agent_done")

        @filter.on_decorating_result()
        async def f(self, event):
            seen.append("decorating")

    register_plugin(Demo)
    fake_llm.push_text("答案")
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q"))

    assert seen == [
        "waiting",
        "request",
        "agent_begin",
        "response",
        "agent_done",
        "decorating",
    ]


def test_on_llm_request_receives_the_request(register_plugin, fake_llm, fake_bot, make_event):
    captured = {}

    class Demo(Star):
        @filter.on_llm_request()
        async def h(self, event, req):
            captured["prompt"] = req.prompt
            captured["type"] = type(req).__name__

    register_plugin(Demo)
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="我的问题"))
    assert captured == {"prompt": "我的问题", "type": "ProviderRequest"}


def test_on_llm_request_can_mutate(register_plugin, fake_llm, fake_bot, make_event):
    """钩子改 req 要能影响真正发出去的请求。"""

    class Demo(Star):
        @filter.on_llm_request()
        async def h(self, event, req):
            req.system_prompt = "被钩子改过"

    register_plugin(Demo)
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q"))
    assert fake_llm.last_messages[0]["content"] == "被钩子改过"


def test_on_llm_response_receives_response(register_plugin, fake_llm, fake_bot, make_event):
    captured = {}

    class Demo(Star):
        @filter.on_llm_response()
        async def h(self, event, resp):
            captured["text"] = resp.completion_text

    register_plugin(Demo)
    fake_llm.push_text("模型说的话")
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q"))
    assert captured["text"] == "模型说的话"


def test_tool_hooks_argument_contract(register_plugin, fake_llm, fake_bot, make_event):
    """on_using_llm_tool 收过滤后的参数，on_llm_tool_respond 收未过滤的。"""
    seen: list[tuple] = []

    class Demo(Star):
        @filter.on_using_llm_tool()
        async def a(self, event, tool, args):
            seen.append(("using", tool.name, dict(args)))

        @filter.on_llm_tool_respond()
        async def b(self, event, tool, args, result):
            seen.append(("respond", tool.name, dict(args), result))

    register_plugin(Demo)

    async def handler(event, a: str):
        return "工具结果"

    tools = ToolSet()
    tools.add_tool(
        _tool(handler, parameters={"type": "object", "properties": {"a": {"type": "string"}}}),
    )
    fake_llm.push_tool_call("t", '{"a": "1", "多余": "x"}')
    fake_llm.push_text("最终答案")

    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q", func_tool=tools))

    using = next(s for s in seen if s[0] == "using")
    respond = next(s for s in seen if s[0] == "respond")
    assert using[2] == {"a": "1"}  # 已过滤
    assert respond[2] == {"a": "1", "多余": "x"}  # 未过滤
    assert respond[3] == "工具结果"


def test_stop_event_in_hook_aborts(register_plugin, fake_llm, fake_bot, make_event):
    class Demo(Star):
        @filter.on_llm_request()
        async def h(self, event, req):
            event.stop_event()

    register_plugin(Demo)
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q"))
    assert fake_llm.calls == []
    assert fake_bot.sent == []


def test_hook_exception_does_not_break_the_chain(
    register_plugin,
    fake_llm,
    fake_bot,
    make_event,
):
    class Demo(Star):
        @filter.on_llm_request()
        async def boom(self, event, req):
            raise RuntimeError("钩子炸了")

    register_plugin(Demo)
    fake_llm.push_text("照样回答")
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q"))
    assert fake_bot.sent == ["照样回答"]


def test_non_async_hook_is_skipped(register_plugin, fake_llm, fake_bot, make_event, caplog):
    """上游要求钩子必须是 async def，同步函数跳过并告警。"""
    called = []

    class Demo(Star):
        @filter.on_llm_request()
        def sync_hook(self, event, req):
            called.append(1)

    register_plugin(Demo)
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    with caplog.at_level("WARNING"):
        _run(event, ProviderRequest(prompt="q"))
    assert called == []
    assert any("async def" in r.message for r in caplog.records)


def test_result_is_marked_as_llm_result(register_plugin, fake_llm, fake_bot, make_event):
    from astrbot_compat.events import ResultContentType

    captured = {}

    class Demo(Star):
        @filter.on_decorating_result()
        async def h(self, event):
            captured["type"] = event.get_result().result_content_type

    register_plugin(Demo)
    fake_llm.push_text("答案")
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _run(event, ProviderRequest(prompt="q"))
    assert captured["type"] is ResultContentType.LLM_RESULT


def test_llm_disabled_tells_the_user(fake_bot, make_event, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_ENABLED", False, raising=False)
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    assert _run(event, ProviderRequest(prompt="q")) is True
    assert "未启用" in fake_bot.sent[0]


def test_llm_failure_is_reported_not_swallowed(fake_bot, make_event, monkeypatch):
    import core.llm.openai_client as oc

    async def boom(*a, **k):
        raise oc.OpenAIClientError("连不上模型")

    monkeypatch.setattr(oc, "chat_completion", boom)
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    assert _run(event, ProviderRequest(prompt="q")) is True
    assert "大模型请求失败" in fake_bot.sent[0]
