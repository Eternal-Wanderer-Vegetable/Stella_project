# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""函数工具：docstring 解析、注册、调用循环。"""

from __future__ import annotations

import asyncio

import pytest

import astrbot_compat.filters as filter  # noqa: A004  # 插件侧惯用名
from astrbot_compat.base import Star
from astrbot_compat.filters import parse_tool_docstring
from astrbot_compat.llm import (
    ProviderRequest,
    StellaChatProvider,
    ToolSet,
    llm_tools,
    run_tool_loop,
)
from astrbot_compat.llm.agent import NO_RETURN_NOTICE, _filter_args, execute_tool

# ---------------------------------------------------------------- docstring


def test_parses_args_section():
    doc = """获取天气信息。

    Args:
        location(string): 地点
        days(int): 天数
    """
    desc, args = parse_tool_docstring(doc)
    assert desc == "获取天气信息。"
    assert args == [
        {"name": "location", "type": "string", "description": "地点"},
        {"name": "days", "type": "integer", "description": "天数"},
    ]


def test_parses_list_type():
    _, args = parse_tool_docstring("d\n\nArgs:\n    xs(list[string]): 一组")
    assert args[0]["type"] == "array"
    assert args[0]["items"] == {"type": "string"}


def test_returns_section_is_not_description():
    doc = """真正的描述。

    Args:
        a(string): x

    Returns:
        不该出现在描述里
    """
    desc, _ = parse_tool_docstring(doc)
    assert desc == "真正的描述。"
    assert "不该出现" not in desc


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("string", "string"), ("int", "integer"), ("bool", "boolean"), ("未知类型", "string")],
)
def test_type_mapping(raw, expected):
    _, args = parse_tool_docstring(f"d\n\nArgs:\n    a({raw}): x")
    assert args[0]["type"] == expected


def test_empty_docstring():
    assert parse_tool_docstring(None) == ("", [])
    assert parse_tool_docstring("只有描述") == ("只有描述", [])


# ---------------------------------------------------------------- 注册


def test_llm_tool_registers_into_global_table(register_plugin):
    class Demo(Star):
        @filter.llm_tool("get_weather")
        async def weather(self, event, location: str):
            """查天气。

            Args:
                location(string): 城市
            """
            return f"{location}: 晴"

    register_plugin(Demo)
    tool = llm_tools.get_tool("get_weather")
    assert tool is not None
    assert tool.description == "查天气。"
    assert tool.parameters["properties"]["location"]["type"] == "string"


def test_tool_handler_is_bound_after_load(register_plugin):
    """工具在类体执行时注册，那时 handler 还没绑 self；loader 之后才重绑。"""

    class Demo(Star):
        @filter.llm_tool()
        async def ping(self, event):
            """ping。"""
            return "pong"

    register_plugin(Demo)
    tool = llm_tools.get_tool("ping")
    assert asyncio.run(execute_tool(tool, object(), {}, 5.0)) == "pong"


def test_tool_name_defaults_to_function_name(register_plugin):
    class Demo(Star):
        @filter.llm_tool()
        async def my_tool_name(self, event):
            """d。"""

    register_plugin(Demo)
    assert llm_tools.get_tool("my_tool_name") is not None


# ---------------------------------------------------------------- 参数过滤


def test_extra_args_are_dropped():
    from astrbot_compat.llm import FunctionTool

    tool = FunctionTool(
        name="t",
        parameters={"type": "object", "properties": {"a": {"type": "string"}}},
        handler=lambda e, a: a,
    )
    assert _filter_args(tool, {"a": "1", "多余": "x"}) == {"a": "1"}


def test_tools_without_handler_pass_everything_through():
    from astrbot_compat.llm import FunctionTool

    tool = FunctionTool(name="t", parameters={"type": "object", "properties": {"a": {}}})
    assert _filter_args(tool, {"a": 1, "b": 2}) == {"a": 1, "b": 2}


# ---------------------------------------------------------------- 执行


def _tool(handler, **kwargs):
    from astrbot_compat.llm import FunctionTool

    return FunctionTool(name="t", handler=handler, **kwargs)


def test_string_return_is_fed_back():
    async def handler(event):
        return "结果"

    assert asyncio.run(execute_tool(_tool(handler), object(), {}, 5.0)) == "结果"


def test_none_return_becomes_notice():
    async def handler(event):
        return None

    assert asyncio.run(execute_tool(_tool(handler), object(), {}, 5.0)) == NO_RETURN_NOTICE


def test_exception_becomes_error_string():
    async def handler(event):
        raise RuntimeError("炸了")

    assert asyncio.run(execute_tool(_tool(handler), object(), {}, 5.0)) == "error: 炸了"


def test_timeout_is_reported(caplog):
    async def handler(event):
        await asyncio.sleep(10)

    with caplog.at_level("WARNING"):
        out = asyncio.run(execute_tool(_tool(handler), object(), {}, 0.01))
    assert "timed out" in out


def test_async_generator_tool(fake_bot, make_event):
    """yield 出 MessageEventResult 的工具：结果挂到 event 上。"""
    from astrbot_compat.events import MessageEventResult, build_event

    event = asyncio.run(build_event(make_event("x"), fake_bot))

    async def handler(evt):
        yield MessageEventResult().message("直接发给用户")

    out = asyncio.run(execute_tool(_tool(handler), event, {}, 5.0))
    assert out == NO_RETURN_NOTICE
    assert event.get_result().get_plain_text() == "直接发给用户"


# ---------------------------------------------------------------- 循环


def _loop(fake_llm, tools, event, **kwargs):
    provider = StellaChatProvider()
    req = ProviderRequest(prompt="q", func_tool=tools)
    return asyncio.run(run_tool_loop(provider, req, event, **kwargs))


def test_full_tool_loop(fake_llm, fake_bot, make_event):
    from astrbot_compat.events import build_event

    called = []

    async def handler(event, location: str):
        called.append(location)
        return f"{location}: 晴"

    tools = ToolSet()
    tools.add_tool(
        _tool(
            handler,
            parameters={"type": "object", "properties": {"location": {"type": "string"}}},
        ),
    )
    fake_llm.push_tool_call("t", '{"location": "北京", "多余": 1}')
    fake_llm.push_text("北京今天晴。")

    event = asyncio.run(build_event(make_event("q"), fake_bot))
    resp = _loop(fake_llm, tools, event)

    assert called == ["北京"]  # 多余参数被丢掉
    assert resp.completion_text == "北京今天晴。"
    assert len(fake_llm.calls) == 2
    assert any(m.get("role") == "tool" for m in fake_llm.last_messages)


def test_unknown_tool_reports_to_model(fake_llm, fake_bot, make_event):
    from astrbot_compat.events import build_event

    fake_llm.push_tool_call("不存在的工具", "{}")
    fake_llm.push_text("好的")
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    _loop(fake_llm, ToolSet(), event)
    tool_msgs = [m for m in fake_llm.last_messages if m.get("role") == "tool"]
    assert tool_msgs and "not found" in tool_msgs[0]["content"]


def test_step_limit_stops_the_loop(fake_llm, fake_bot, make_event, caplog):
    from astrbot_compat.events import build_event

    async def handler(event):
        return "还要继续"

    tools = ToolSet()
    tools.add_tool(_tool(handler))
    # 模型每轮都要求调工具，永不收敛
    for _ in range(10):
        fake_llm.push_tool_call("t", "{}")

    event = asyncio.run(build_event(make_event("q"), fake_bot))
    with caplog.at_level("WARNING"):
        _loop(fake_llm, tools, event, max_steps=3)
    assert len(fake_llm.calls) == 3
    assert any("达到上限" in r.message for r in caplog.records)


def test_no_tools_means_single_call(fake_llm, fake_bot, make_event):
    from astrbot_compat.events import build_event

    fake_llm.push_text("直接回答")
    event = asyncio.run(build_event(make_event("q"), fake_bot))
    resp = _loop(fake_llm, None, event)
    assert resp.completion_text == "直接回答"
    assert len(fake_llm.calls) == 1


# ---------------------------------------------------------------- 启停


def test_activate_and_deactivate_route_to_the_global_table():
    """Context 与 StarTools 的启停都作用在同一张全局工具表上。"""
    from astrbot_compat.base import StarTools
    from astrbot_compat.context import Context

    async def handler(event):
        return "ok"

    llm_tools.add_tool(_tool(handler))
    ctx = Context()

    assert ctx.deactivate_llm_tool("t") is True
    assert llm_tools.get_tool("t").active is False
    # 停用的工具不再进入送给模型的工具集
    assert llm_tools.get_full_tool_set().names() == []

    assert StarTools.activate_llm_tool("t") is True
    assert llm_tools.get_tool("t").active is True
    assert llm_tools.get_full_tool_set().names() == ["t"]

    # 不存在的工具返回 False，而不是抛异常
    assert ctx.activate_llm_tool("不存在") is False
    assert StarTools.deactivate_llm_tool("不存在") is False


def test_star_tools_register_llm_tool_uses_the_same_table():
    from astrbot_compat.base import StarTools

    async def handler(event, city: str):
        return city

    StarTools.register_llm_tool(
        "legacy",
        [{"name": "city", "type": "string", "description": "城市"}],
        "旧式注册",
        handler,
    )
    tool = llm_tools.get_tool("legacy")
    assert tool is not None
    assert tool.parameters["properties"]["city"]["type"] == "string"

    StarTools.unregister_llm_tool("legacy")
    assert llm_tools.get_tool("legacy") is None
