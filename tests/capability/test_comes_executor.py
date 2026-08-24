# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Comes 执行器的单测。

最重要的一条：**上下文隔离**。受限 agent 的请求里只能有本次命中能力的工具，
不能有其它插件的工具，也不能有 Stella 的人格与聊天上下文——这是整个升级方案
要解决的核心问题（方案第 3.1 节）。见 test_only_scoped_tools_reach_the_model。

其余围绕 status 判定（方案第 5 节「工具调用成功不代表任务成功」）与
「绝不抛异常」的契约。
"""

import asyncio

import pytest

from capability.comes import execute_all
from capability.comes.executor import can_direct_call, execute, resolve_tools
from capability.registry import (
    KIND_MCP,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from core.tasks import Result, ResultStatus, Task, TaskType


def _run(coro):
    return asyncio.run(coro)


def _task(capability: str = "weather.query", objective: str = "查东京明天天气", **kw) -> Task:
    return Task(
        task_id="t1",
        type=TaskType.TOOL_EXECUTE,
        capability=capability,
        objective=objective,
        **kw,
    )


def _register_tool(name: str, handler, required: list[str] | None = None, desc: str = ""):
    """往全局 llm_tools 里登记一个工具（conftest 的 autouse 夹具负责清理）。"""
    from astrbot_compat.llm.tool import FunctionTool, llm_tools

    params = {"type": "object", "properties": {}}
    for p in required or []:
        params["properties"][p] = {"type": "string", "description": p}
    if required:
        params["required"] = list(required)
    tool = FunctionTool(name=name, description=desc or name, parameters=params, handler=handler)
    llm_tools.add_tool(tool)
    return tool


def _registry_with(capability_id: str, tool_names: list[str]) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(
        Capability(
            id=capability_id,
            description=f"{capability_id} 描述",
            providers=[
                CapabilityProvider(
                    provider_id=f"{capability_id}#{t}",
                    capability_id=capability_id,
                    tool_name=t,
                )
                for t in tool_names
            ],
        ),
    )
    return reg


@pytest.fixture(autouse=True)
def _comes_defaults(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "COMES_ENABLED", True)
    monkeypatch.setattr(settings, "COMES_DIRECT_CALL_NO_ARGS", True)
    monkeypatch.setattr(settings, "COMES_MAX_TOOL_STEPS", 3)
    monkeypatch.setattr(settings, "COMES_TOOL_TIMEOUT", 5.0)
    monkeypatch.setattr(settings, "COMES_TASK_TIMEOUT", 10.0)
    monkeypatch.setattr(settings, "COMES_SUMMARY_MAX_CHARS", 300)
    monkeypatch.setattr(settings, "ASTRBOT_LLM_ENABLED", True)


# ---------- Provider → ToolSet ----------


def test_resolve_tools_reports_missing_plugins():
    """声明里写了 provider 但插件没装是常态，应带着剩下的工具继续跑。"""
    _register_tool("present", lambda event: "ok")
    providers = [
        CapabilityProvider(provider_id="p1", capability_id="c", tool_name="present"),
        CapabilityProvider(provider_id="p2", capability_id="c", tool_name="absent"),
    ]
    tool_set, missing = resolve_tools(providers)
    assert tool_set.names() == ["present"]
    assert missing == ["absent"]


def test_resolve_tools_skips_inactive_tools():
    tool = _register_tool("off", lambda event: "ok")
    tool.active = False
    providers = [CapabilityProvider(provider_id="p", capability_id="c", tool_name="off")]
    tool_set, missing = resolve_tools(providers)
    assert tool_set.empty()
    assert missing == ["off"]


def test_resolve_tools_reports_unsupported_kind():
    """MCP / API / native 本轮不实现，要明确报告而不是静默当成缺工具。"""
    providers = [
        CapabilityProvider(
            provider_id="p", capability_id="c", tool_name="x", kind=KIND_MCP,
        ),
    ]
    tool_set, missing = resolve_tools(providers)
    assert tool_set.empty()
    assert "暂不支持" in missing[0]


def test_can_direct_call_only_for_single_no_arg_tool():
    from astrbot_compat.llm.tool import FunctionTool, ToolSet

    no_args = FunctionTool(name="a", parameters={"type": "object", "properties": {}})
    with_args = FunctionTool(
        name="b",
        parameters={"type": "object", "properties": {"c": {}}, "required": ["c"]},
    )
    assert can_direct_call(ToolSet(tools=[no_args])) is True
    assert can_direct_call(ToolSet(tools=[with_args])) is False
    assert can_direct_call(ToolSet(tools=[no_args, no_args])) is False
    assert can_direct_call(ToolSet(tools=[])) is False


# ---------- 早退路径 ----------


def test_disabled_comes_fails_fast(monkeypatch, astr_event):
    from config import settings

    monkeypatch.setattr(settings, "COMES_ENABLED", False)
    r = _run(execute(_task(), event=astr_event, target=_registry_with("weather.query", [])))
    assert r.status is ResultStatus.FAILED
    assert "未启用" in r.metadata["reason"]


def test_missing_event_fails_fast():
    """工具 handler 普遍依赖 event，没有它无法执行（主动发言路径就是这样）。"""
    r = _run(execute(_task(), event=None, target=_registry_with("weather.query", ["x"])))
    assert r.status is ResultStatus.FAILED
    assert "缺少事件对象" in r.metadata["reason"]


def test_unknown_capability_fails(astr_event):
    r = _run(execute(_task("nope.gone"), event=astr_event, target=CapabilityRegistry()))
    assert r.status is ResultStatus.FAILED
    assert "未注册" in r.metadata["reason"]


def test_capability_without_provider_fails(astr_event):
    r = _run(execute(_task(), event=astr_event, target=_registry_with("weather.query", [])))
    assert r.status is ResultStatus.FAILED
    assert "没有可用 provider" in r.metadata["reason"]


def test_all_tools_unavailable_fails(astr_event):
    """能力声明了工具但插件全没装。"""
    reg = _registry_with("weather.query", ["absent"])
    r = _run(execute(_task(), event=astr_event, target=reg))
    assert r.status is ResultStatus.FAILED
    assert r.metadata["missing"] == ["absent"]


# ---------- 无参直调 ----------


def test_direct_call_skips_the_model(astr_event):
    """单个无参工具时那次 27B 往返纯属浪费。fake_llm 未请求 → 一旦调模型就会炸。"""
    calls = []

    async def handler(event):
        calls.append(event)
        return "现在 12:00"

    _register_tool("get_time", handler)
    reg = _registry_with("time.now", ["get_time"])

    r = _run(execute(_task("time.now", "现在几点"), event=astr_event, target=reg))
    assert r.status is ResultStatus.SUCCESS
    assert r.summary == "现在 12:00"
    assert r.metadata["direct_call"] is True
    assert len(calls) == 1


def test_direct_call_can_be_disabled(monkeypatch, astr_event, fake_llm):
    from config import settings

    monkeypatch.setattr(settings, "COMES_DIRECT_CALL_NO_ARGS", False)

    async def handler(event):
        return "现在 12:00"

    _register_tool("get_time", handler)
    reg = _registry_with("time.now", ["get_time"])
    fake_llm.push_tool_call("get_time", "{}")
    fake_llm.push_text("现在 12 点。")

    r = _run(execute(_task("time.now", "现在几点"), event=astr_event, target=reg))
    assert r.metadata["direct_call"] is False
    assert len(fake_llm.calls) == 2


def test_direct_call_passes_task_input_as_args(astr_event):
    seen = {}

    async def handler(event, **kwargs):
        seen.update(kwargs)
        return "ok"

    _register_tool("t", handler)
    reg = _registry_with("c", ["t"])
    _run(execute(_task("c", "obj", input={"city": "东京"}), event=astr_event, target=reg))
    assert seen == {"city": "东京"}


# ---------- 受限 agent ----------


def test_only_scoped_tools_reach_the_model(astr_event, fake_llm):
    """**核心不变量**：模型只看到本次命中能力的工具。

    方案第 3.1 节要解决的正是「把所有插件工具塞进上下文」。这里注册三个工具、
    只把一个挂进能力，请求里就必须只有那一个。
    """
    async def handler(event, city: str = ""):
        return f"{city} 27℃"

    _register_tool("get_weather", handler, required=["city"], desc="查天气")
    _register_tool("unrelated_a", handler, required=["city"], desc="别的插件A")
    _register_tool("unrelated_b", handler, required=["city"], desc="别的插件B")

    reg = _registry_with("weather.query", ["get_weather"])
    fake_llm.push_tool_call("get_weather", '{"city": "东京"}')
    fake_llm.push_text("东京 27℃。")

    r = _run(execute(_task(), event=astr_event, target=reg))
    assert r.status is ResultStatus.SUCCESS
    # 只有 get_weather 的 schema 进了请求
    assert fake_llm.calls[0]["tools"] is not None
    names = [t["function"]["name"] for t in fake_llm.calls[0]["tools"]]
    assert names == ["get_weather"]


def test_stella_persona_and_chat_context_never_reach_comes(astr_event, fake_llm):
    """Comes 的请求里不能有 Stella 的人格或聊天上下文，只有执行器人格 + 任务目标。"""
    async def handler(event, city: str = ""):
        return "27℃"

    _register_tool("get_weather", handler, required=["city"])
    reg = _registry_with("weather.query", ["get_weather"])
    fake_llm.push_text("好的。")

    _run(execute(_task(objective="查东京明天天气"), event=astr_event, target=reg))

    messages = fake_llm.calls[0]["messages"]
    system = [m for m in messages if m["role"] == "system"]
    user = [m for m in messages if m["role"] == "user"]
    assert len(system) == 1
    assert "工具执行器" in system[0]["content"]
    # 只有一条 user 消息，内容就是任务目标
    assert len(user) == 1
    assert "查东京明天天气" in str(user[0]["content"])


def test_objective_carries_known_slots(astr_event, fake_llm):
    async def handler(event, city: str = ""):
        return "27℃"

    _register_tool("get_weather", handler, required=["city"])
    reg = _registry_with("weather.query", ["get_weather"])
    fake_llm.push_text("好的。")

    _run(execute(_task(input={"city": "东京"}), event=astr_event, target=reg))
    user = [m for m in fake_llm.calls[0]["messages"] if m["role"] == "user"]
    assert "city=东京" in str(user[0]["content"])


def test_agent_completion_becomes_summary(astr_event, fake_llm):
    """受限 agent 读完工具输出写的那句话天然就是摘要，不必再调模型压缩。"""
    async def handler(event, city: str = ""):
        return '{"temp": 27, "cond": "sunny", "pop": 0.1}'

    _register_tool("get_weather", handler, required=["city"])
    reg = _registry_with("weather.query", ["get_weather"])
    fake_llm.push_tool_call("get_weather", '{"city": "东京"}')
    fake_llm.push_text("东京明天 27℃，晴，降雨概率 10%。")

    r = _run(execute(_task(), event=astr_event, target=reg))
    assert r.summary == "东京明天 27℃，晴，降雨概率 10%。"
    # data 保留工具原始返回，供日志追溯——但它不进 prompt
    assert r.data == [("get_weather", '{"temp": 27, "cond": "sunny", "pop": 0.1}')]


# ---------- status 判定（方案第 5 节） ----------


def test_no_tool_called_is_failed(astr_event, fake_llm):
    """模型一个工具都没调：它认为不需要，或没理解目标。都算任务没完成。

    并且 summary 必须为空：失败时的 completion 是受限 agent 的自言自语，
    它会被冠上「刚刚查到的信息（真实数据）」送给 Stella，于是 Stella 把执行器的
    嘟囔当成事实转述给用户。模型原话留在 metadata 里供排查。
    """
    async def handler(event, city: str = ""):
        return "27℃"

    _register_tool("get_weather", handler, required=["city"])
    reg = _registry_with("weather.query", ["get_weather"])
    fake_llm.push_text("我觉得不用查。")

    r = _run(execute(_task(), event=astr_event, target=reg))
    assert r.status is ResultStatus.FAILED
    assert r.summary == ""
    assert r.metadata["model_text"] == "我觉得不用查。"


def test_tool_error_is_failed(astr_event):
    """API 跑了但抛异常 → failed。execute_tool 把它变成 "error: ..."。"""
    async def handler(event):
        raise RuntimeError("上游 500")

    _register_tool("broken", handler)
    reg = _registry_with("c", ["broken"])
    r = _run(execute(_task("c"), event=astr_event, target=reg))
    assert r.status is ResultStatus.FAILED
    assert r.summary == ""


def test_partial_when_some_tools_fail(astr_event, fake_llm):
    """三个工具里两个查到了，那两条照样该给 Stella。"""
    async def ok(event, q: str = ""):
        return "有结果"

    async def bad(event, q: str = ""):
        raise RuntimeError("boom")

    _register_tool("ok_tool", ok, required=["q"])
    _register_tool("bad_tool", bad, required=["q"])
    reg = _registry_with("c", ["ok_tool", "bad_tool"])

    # 一轮里同时请求两个工具
    fake_llm.calls.clear()
    fake_llm._queue.append(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "ok_tool", "arguments": '{"q": "x"}'},
                            },
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {"name": "bad_tool", "arguments": '{"q": "x"}'},
                            },
                        ],
                    },
                },
            ],
            "usage": {},
        },
    )
    fake_llm.push_text("查到一部分。")

    r = _run(execute(_task("c"), event=astr_event, target=reg))
    assert r.status is ResultStatus.PARTIAL
    assert r.summary == "查到一部分。"


def test_timeout_is_failed_not_raised(monkeypatch, astr_event):
    from config import settings

    monkeypatch.setattr(settings, "COMES_TASK_TIMEOUT", 0.05)

    async def slow(event):
        await asyncio.sleep(1.0)
        return "late"

    _register_tool("slow", slow)
    reg = _registry_with("c", ["slow"])
    r = _run(execute(_task("c"), event=astr_event, target=reg))
    assert r.status is ResultStatus.FAILED
    assert "超时" in r.metadata["reason"]


def test_llm_disabled_is_failed_not_raised(monkeypatch, astr_event):
    """ASTRBOT_LLM_ENABLED=false 时 provider 为 None，必须降级而不是击穿。"""
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_LLM_ENABLED", False)

    async def handler(event, city: str = ""):
        return "27℃"

    _register_tool("get_weather", handler, required=["city"])
    reg = _registry_with("weather.query", ["get_weather"])
    r = _run(execute(_task(), event=astr_event, target=reg))
    assert r.status is ResultStatus.FAILED
    assert "LLM 未启用" in r.metadata["reason"]


# ---------- execute_all ----------


def test_execute_all_returns_in_input_order(astr_event):
    async def a(event):
        return "结果A"

    async def b(event):
        return "结果B"

    _register_tool("ta", a)
    _register_tool("tb", b)
    reg = CapabilityRegistry()
    for cid, tool in (("ca", "ta"), ("cb", "tb")):
        reg.register(
            Capability(
                id=cid,
                description=cid,
                providers=[
                    CapabilityProvider(provider_id=f"{cid}#{tool}", capability_id=cid, tool_name=tool),
                ],
            ),
        )

    tasks = [
        Task(task_id="t1", type=TaskType.TOOL_EXECUTE, capability="ca", objective="o"),
        Task(task_id="t2", type=TaskType.TOOL_EXECUTE, capability="cb", objective="o"),
    ]
    results = _run(execute_all(tasks, event=astr_event, target=reg))
    assert [r.task_id for r in results] == ["t1", "t2"]
    assert [r.summary for r in results] == ["结果A", "结果B"]


def test_execute_all_empty_returns_empty(astr_event):
    assert _run(execute_all([], event=astr_event)) == []


def test_execute_all_survives_a_broken_task(monkeypatch, astr_event):
    """一个任务炸了不能让其它任务的结果一起丢。"""
    import capability.comes as comes_pkg

    async def boom(task, **kwargs):
        if task.task_id == "t1":
            raise RuntimeError("gather 层异常")
        return Result(task_id=task.task_id, status=ResultStatus.SUCCESS, summary="ok")

    monkeypatch.setattr(comes_pkg, "execute", boom)
    tasks = [
        Task(task_id="t1", type=TaskType.TOOL_EXECUTE, capability="ca", objective="o"),
        Task(task_id="t2", type=TaskType.TOOL_EXECUTE, capability="cb", objective="o"),
    ]
    results = _run(execute_all(tasks, event=astr_event))
    assert results[0].status is ResultStatus.FAILED
    assert results[1].status is ResultStatus.SUCCESS


# ---------- Provider 健康度记账 ----------


def test_failure_is_recorded_on_the_provider(monkeypatch, astr_event):
    """连续失败到阈值后退避：坏掉的 provider 每次都占一次 27B 往返再失败。"""
    from config import settings

    monkeypatch.setattr(settings, "COMES_PROVIDER_FAILURE_THRESHOLD", 2)
    monkeypatch.setattr(settings, "COMES_PROVIDER_RECOVER_SECONDS", 600.0)

    async def handler(event):
        raise RuntimeError("上游 500")

    _register_tool("broken", handler)
    reg = _registry_with("c", ["broken"])
    provider = reg.find_providers("c")[0]

    _run(execute(_task("c"), event=astr_event, target=reg))
    assert provider.failures == 1
    assert provider.available() is True

    _run(execute(_task("c"), event=astr_event, target=reg))
    assert provider.failures == 2
    assert provider.available() is False


def test_success_clears_recorded_failures(monkeypatch, astr_event):
    from config import settings

    monkeypatch.setattr(settings, "COMES_PROVIDER_FAILURE_THRESHOLD", 5)
    state = {"fail": True}

    async def handler(event):
        if state["fail"]:
            raise RuntimeError("boom")
        return "好了"

    _register_tool("flaky", handler)
    reg = _registry_with("c", ["flaky"])
    provider = reg.find_providers("c")[0]

    _run(execute(_task("c"), event=astr_event, target=reg))
    assert provider.failures == 1

    state["fail"] = False
    _run(execute(_task("c"), event=astr_event, target=reg))
    assert provider.failures == 0


def test_uncalled_providers_are_not_charged(monkeypatch, astr_event, fake_llm):
    """模型没选中的 provider 既不算成功也不算失败。

    给它记账会让「一直没被选中」慢慢累积成退避。
    """
    from config import settings

    monkeypatch.setattr(settings, "COMES_PROVIDER_FAILURE_THRESHOLD", 2)

    async def ok(event, q: str = ""):
        return "有结果"

    async def never(event, q: str = ""):
        return "不会被调"

    _register_tool("used", ok, required=["q"])
    _register_tool("unused", never, required=["q"])
    reg = _registry_with("c", ["used", "unused"])
    fake_llm.push_tool_call("used", '{"q": "x"}')
    fake_llm.push_text("查到了。")

    _run(execute(_task("c"), event=astr_event, target=reg))
    by_id = {p.tool_name: p for p in reg.get("c").providers}
    assert by_id["used"].failures == 0
    assert by_id["unused"].failures == 0


def test_backed_off_provider_is_skipped_next_time(monkeypatch, astr_event):
    from config import settings

    monkeypatch.setattr(settings, "COMES_PROVIDER_FAILURE_THRESHOLD", 1)
    monkeypatch.setattr(settings, "COMES_PROVIDER_RECOVER_SECONDS", 600.0)

    async def handler(event):
        raise RuntimeError("boom")

    _register_tool("broken", handler)
    reg = _registry_with("c", ["broken"])

    _run(execute(_task("c"), event=astr_event, target=reg))
    # 退避后该能力已无可用 provider，下一次直接快速失败（不再调工具）
    r = _run(execute(_task("c"), event=astr_event, target=reg))
    assert r.status is ResultStatus.FAILED
    assert "没有可用 provider" in r.metadata["reason"]
