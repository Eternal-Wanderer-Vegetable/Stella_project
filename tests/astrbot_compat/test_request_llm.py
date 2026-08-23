# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""端到端：插件调用 LLM 的两条路径。

一是 `yield event.request_llm(...)` 交给管道跑，
二是 `context.get_using_provider_async()` 后直接 `provider.text_chat(...)`。
"""

from __future__ import annotations

import asyncio
import json

import astrbot_compat.filters as filter  # noqa: A004  # 插件侧惯用名
from astrbot_compat.base import Star
from astrbot_compat.events import AstrMessageEvent, build_event
from astrbot_compat.filters import GreedyStr
from astrbot_compat.pipeline import dispatch


def _dispatch(nb_event, bot):
    return asyncio.run(dispatch(nb_event, bot))


# ---------------------------------------------------------------- request_llm 语义


def test_request_llm_returns_a_provider_request(fake_bot, make_event):
    from astrbot_compat.llm import ProviderRequest

    event = asyncio.run(build_event(make_event("q"), fake_bot))
    req = event.request_llm(prompt="hi", system_prompt="S")
    assert isinstance(req, ProviderRequest)
    assert req.prompt == "hi"
    assert req.system_prompt == "S"


def test_func_tool_manager_is_silently_ignored(fake_bot, make_event):
    """上游 4.27.4 把这个参数注释掉了，只认 tool_set。照抄，不"修正"。"""
    from astrbot_compat.llm import ToolSet

    event = asyncio.run(build_event(make_event("q"), fake_bot))
    ts = ToolSet()
    assert event.request_llm(prompt="hi", func_tool_manager=ts).func_tool is None
    assert event.request_llm(prompt="hi", tool_set=ts).func_tool is ts


def test_contexts_clears_conversation(fake_bot, make_event):
    from astrbot_compat.po import Conversation

    event = asyncio.run(build_event(make_event("q"), fake_bot))
    conv = Conversation(platform_id="p", user_id="u", cid="c")
    req = event.request_llm(prompt="hi", contexts=[{"role": "user", "content": "x"}], conversation=conv)
    assert req.conversation is None
    # 没有 contexts 时保留
    assert event.request_llm(prompt="hi", conversation=conv).conversation is conv


def test_list_args_are_independent(fake_bot, make_event):
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    a = event.request_llm(prompt="1")
    a.image_urls.append("x")
    assert event.request_llm(prompt="2").image_urls == []


# ---------------------------------------------------------------- 端到端


def test_yielded_request_reaches_the_user(register_plugin, fake_llm, fake_bot, make_event):
    class Demo(Star):
        @filter.command("ask")
        async def ask(self, event: AstrMessageEvent, q: GreedyStr):
            yield event.request_llm(prompt=q)

    register_plugin(Demo)
    fake_llm.push_text("模型的回答")
    assert _dispatch(make_event("/ask 今天天气"), fake_bot) is True
    assert fake_bot.sent == ["模型的回答"]
    assert fake_llm.last_messages[-1]["content"] == "今天天气"


def test_direct_text_chat_path(register_plugin, fake_llm, fake_bot, make_event):
    class Demo(Star):
        @filter.command("direct")
        async def direct(self, event: AstrMessageEvent):
            provider = await self.context.get_using_provider_async()
            resp = await provider.text_chat(prompt="你好", session_id=event.unified_msg_origin)
            yield event.plain_result(resp.completion_text)

    register_plugin(Demo)
    fake_llm.push_text("你也好")
    assert _dispatch(make_event("/direct"), fake_bot) is True
    assert fake_bot.sent == ["你也好"]


def test_llm_generate_helper(register_plugin, fake_llm, fake_bot, make_event):
    class Demo(Star):
        @filter.command("gen")
        async def gen(self, event: AstrMessageEvent):
            resp = await self.context.llm_generate(chat_provider_id="stella", prompt="q")
            yield event.plain_result(resp.completion_text)

    register_plugin(Demo)
    fake_llm.push_text("生成结果")
    assert _dispatch(make_event("/gen"), fake_bot) is True
    assert fake_bot.sent == ["生成结果"]


def test_tool_loop_agent_helper(register_plugin, fake_llm, fake_bot, make_event):
    from astrbot_compat.llm import FunctionTool, ToolSet

    class Demo(Star):
        @filter.command("agent")
        async def run(self, event: AstrMessageEvent):
            async def handler(evt):
                return "工具说：42"

            ts = ToolSet()
            ts.add_tool(FunctionTool(name="t", description="d", handler=handler))
            resp = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id="stella",
                prompt="q",
                tools=ts,
            )
            yield event.plain_result(resp.completion_text)

    register_plugin(Demo)
    fake_llm.push_tool_call("t", "{}")
    fake_llm.push_text("答案是 42")
    assert _dispatch(make_event("/agent"), fake_bot) is True
    assert fake_bot.sent == ["答案是 42"]


def test_end_to_end_with_registered_tool(register_plugin, fake_llm, fake_bot, make_event):
    """@filter.llm_tool 注册的工具能被 request_llm 用上。"""
    called = []

    class Demo(Star):
        @filter.llm_tool("get_weather")
        async def weather(self, event, location: str):
            """查天气。

            Args:
                location(string): 城市
            """
            called.append(location)
            return f"{location}: 晴"

        @filter.command("w")
        async def w(self, event: AstrMessageEvent, city: GreedyStr):
            yield event.request_llm(
                prompt=f"{city}天气如何",
                tool_set=self.context.get_llm_tool_manager(),
            )

    register_plugin(Demo)
    fake_llm.push_tool_call("get_weather", '{"location": "北京"}')
    fake_llm.push_text("北京今天晴。")

    assert _dispatch(make_event("/w 北京"), fake_bot) is True
    assert called == ["北京"]
    assert fake_bot.sent == ["北京今天晴。"]


def test_conversation_history_is_used_and_persisted(
    register_plugin,
    fake_llm,
    fake_bot,
    make_event,
    llm_db,
):
    from astrbot_compat.conversation import get_conversation_manager

    cm = get_conversation_manager()
    cid = asyncio.run(
        cm.new_conversation(
            "aiocqhttp:GroupMessage:1",
            content=[{"role": "user", "content": "上一轮"}],
        ),
    )
    conv = asyncio.run(cm.get_conversation("aiocqhttp:GroupMessage:1", cid))

    class Demo(Star):
        @filter.command("chat")
        async def chat(self, event: AstrMessageEvent, q: GreedyStr):
            yield event.request_llm(prompt=q, conversation=conv)

    register_plugin(Demo)
    fake_llm.push_text("这一轮的回答")
    assert _dispatch(make_event("/chat 新问题"), fake_bot) is True

    # 历史被当成上下文送出去了
    assert any(m.get("content") == "上一轮" for m in fake_llm.last_messages)
    # 这一轮被追加回库里
    updated = asyncio.run(cm.get_conversation("aiocqhttp:GroupMessage:1", cid))
    history = json.loads(updated.history)
    assert history[-2:] == [
        {"role": "user", "content": "新问题"},
        {"role": "assistant", "content": "这一轮的回答"},
    ]


def test_no_conversation_means_no_persistence(
    register_plugin,
    fake_llm,
    fake_bot,
    make_event,
    llm_db,
):
    """插件没挂 conversation 就不落库——历史由插件自己管（上游语义）。"""
    from astrbot_compat.conversation import get_conversation_manager

    class Demo(Star):
        @filter.command("once")
        async def once(self, event: AstrMessageEvent):
            yield event.request_llm(prompt="q")

    register_plugin(Demo)
    fake_llm.push_text("答")
    _dispatch(make_event("/once"), fake_bot)
    assert asyncio.run(get_conversation_manager().get_conversations()) == []


def test_plugin_llm_still_goes_through_the_scheduler(
    register_plugin,
    fake_llm,
    fake_bot,
    make_event,
    monkeypatch,
):
    """本地只有一块 GPU，插件调用必须和主对话走同一个闸门排队。"""
    acquired: list[str] = []
    import core.llm as core_llm

    real_acquire = core_llm.acquire

    def spy(resource, tag="", priority=0):
        acquired.append(resource)
        return real_acquire(resource, tag=tag, priority=priority)

    monkeypatch.setattr(core_llm, "acquire", spy)

    class Demo(Star):
        @filter.command("q")
        async def q(self, event: AstrMessageEvent):
            yield event.request_llm(prompt="hi")

    register_plugin(Demo)
    fake_llm.push_text("ok")
    _dispatch(make_event("/q"), fake_bot)
    assert acquired == [core_llm.RESOURCE_CHAT]
