# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""有界 Agent 运行器的基线：允许清单、四重上限、无事件无钩子、取消检查点。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from stella_project.plugins.bot_main.scheduling.agent import (
    AgentRunLimits,
    ScheduledAgentRunner,
    TaskCancelledError,
    schema_fingerprint,
)


class FakeProvider:
    """最小 provider：按脚本逐轮返回响应，并记录每轮入参供断言。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _resp(text="", *, tools=None, args=None, ids=None):
    from astrbot_compat.llm.entities import LLMResponse

    return LLMResponse(
        role="assistant",
        completion_text=text,
        tools_call_name=tools or [],
        tools_call_args=args or [],
        tools_call_ids=ids or [],
    )


class FakeTool:
    """不依赖 astrbot_compat FunctionTool 的替身（鸭子类型足够）。"""

    def __init__(self, name="mcp_demo_read", result='{"ok": true}', parameters=None,
                 fail=False, delay=0.0):
        self.name = name
        self.description = "demo"
        self.parameters = parameters or {"type": "object", "properties": {}}
        self.result = result
        self.fail = fail
        self.delay = delay
        self.calls: list[dict] = []

    def call(self, context, **kwargs):
        self.calls.append(kwargs)

        async def _invoke():
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail:
                raise RuntimeError("boom")
            return self.result

        return _invoke()


def _limits(**overrides) -> AgentRunLimits:
    params = {
        "max_model_rounds": 4,
        "max_tool_calls": 8,
        "wall_clock_seconds": 10.0,
        "output_max_chars": 1200,
        "tool_timeout_seconds": 5.0,
    }
    params.update(overrides)
    return AgentRunLimits(**params)


def _runner(provider, *, tools=None, cancel_check=None, usage_check=None):
    tool_map = {t.name: t for t in (tools or [])}

    async def resolve_tool(name):
        return tool_map.get(name)

    return ScheduledAgentRunner(
        provider_resolver=AsyncMock(return_value=provider),
        tool_resolver=resolve_tool,
        cancel_check=cancel_check,
        usage_check=usage_check,
    )


# ── 基本成功路径 ─────────────────────────────────────

async def test_plain_completion_without_tools():
    provider = FakeProvider([_resp("今天群里有三个安排，记得看公告")])
    outcome = await _runner(provider).run(
        task_id="t", run_id="r", objective="总结今天", policy={}, context_text="",
        limits=_limits(),
    )
    assert outcome.status == "completed"
    assert outcome.text == "今天群里有三个安排，记得看公告"
    assert outcome.model_rounds == 1 and outcome.tool_calls == 0


async def test_tool_round_then_final_answer():
    tool = FakeTool()
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"], args=[{"q": "x"}], ids=["c1"]),
        _resp("查到了：一切正常"),
    ])
    outcome = await _runner(provider, tools=[tool]).run(
        task_id="t", run_id="r", objective="查一下", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(),
    )
    assert outcome.status == "completed"
    assert outcome.text == "查到了：一切正常"
    assert outcome.model_rounds == 2 and outcome.tool_calls == 1
    assert tool.calls == [{"q": "x"}]
    # 工具结果回喂进了下一轮的 contexts 链
    assert provider.calls[1]["tool_calls_result"] is not None


async def test_tool_without_event_and_without_hooks():
    """受限执行必须无事件直呼：MCP 工具的 context 参数收到 None。"""
    tool = FakeTool()
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"], args=[{"q": "x"}], ids=["c1"]),
        _resp("done"),
    ])
    await _runner(provider, tools=[tool]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(),
    )
    assert tool.calls and tool.calls[0] == {"q": "x"}  # 参数原样，无 event 混入


# ── 允许清单与指纹 ───────────────────────────────────

async def test_tool_not_in_allowlist_is_denied_not_executed():
    """模型点名清单外的工具：不执行、错误回喂、记入 denied_tools。"""
    approved = FakeTool(name="mcp_ok")
    provider = FakeProvider([
        _resp("", tools=["send_group_msg", "mcp_ok"], args=[{}, {}], ids=["a", "b"]),
        _resp("ok"),
    ])
    outcome = await _runner(provider, tools=[approved]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_ok"]},
        context_text="", limits=_limits(max_tool_calls=8),
    )
    assert outcome.status == "completed"
    assert "send_group_msg:not_allowed" in outcome.denied_tools
    assert outcome.tool_calls == 1  # 只有被批准的工具真的执行了


async def test_unresolvable_tool_fails_explicitly_rather_than_bare_running():
    """管理员配了工具但一个都解析不出来：显式失败，不让模型裸跑编造「查过了」。"""
    provider = FakeProvider([_resp("我查过了，一切正常")])
    outcome = await _runner(provider, tools=[]).run(
        task_id="t", run_id="r", objective="x",
        policy={"tools": ["mcp_missing"]}, context_text="", limits=_limits(),
    )
    assert outcome.status == "failed"
    assert outcome.error == "tools_unavailable"
    assert "mcp_missing:unavailable" in outcome.denied_tools
    assert provider.calls == []  # 失败发生在任何模型调用之前


async def test_all_tools_unavailable_fails_explicitly():
    provider = FakeProvider([_resp("x")])
    outcome = await _runner(provider, tools=[]).run(
        task_id="t", run_id="r", objective="x",
        policy={"tools": ["mcp_missing"]}, context_text="", limits=_limits(),
    )
    assert outcome.status == "failed"
    assert outcome.error == "tools_unavailable"


async def test_schema_drift_denies_tool():
    tool = FakeTool(name="mcp_demo_read", parameters={"type": "object", "properties": {}})
    drifted = schema_fingerprint({"type": "object", "properties": {"q": {}}})
    provider = FakeProvider([_resp("直接回答")])
    outcome = await _runner(provider, tools=[tool]).run(
        task_id="t", run_id="r", objective="x",
        policy={"tools": ["mcp_demo_read"], "tool_fingerprints": {"mcp_demo_read": drifted}},
        context_text="", limits=_limits(),
    )
    assert "mcp_demo_read:schema_drift" in outcome.denied_tools
    assert not tool.calls


# ── 四重上限 ─────────────────────────────────────────

async def test_model_round_cap_stops_run():
    endless = [_resp("", tools=["mcp_demo_read"], args=[{}], ids=["c"])] * 3
    provider = FakeProvider(endless)
    outcome = await _runner(provider, tools=[FakeTool()]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(max_model_rounds=2),
    )
    assert outcome.status == "failed"
    assert outcome.error == "max_model_rounds"
    assert outcome.model_rounds == 2


async def test_tool_call_cap_stops_run():
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"] * 3, args=[{}] * 3, ids=["1", "2", "3"]),
    ])
    outcome = await _runner(provider, tools=[FakeTool()]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(max_tool_calls=2),
    )
    assert outcome.status == "failed"
    assert outcome.error == "max_tool_calls"
    assert outcome.tool_calls == 2


async def test_output_cap_truncates():
    provider = FakeProvider([_resp("长" * 500)])
    outcome = await _runner(provider).run(
        task_id="t", run_id="r", objective="x", policy={}, context_text="",
        limits=_limits(output_max_chars=100),
    )
    assert outcome.status == "completed"
    assert len(outcome.text) == 100
    assert outcome.output_truncated


async def test_wall_clock_timeout():
    tool = FakeTool(delay=5.0)
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"], args=[{}], ids=["1"]),
    ])
    outcome = await _runner(provider, tools=[tool]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(wall_clock_seconds=0.5, tool_timeout_seconds=10),
    )
    assert outcome.status == "timeout"
    assert outcome.error == "wall_clock_exceeded"


async def test_tool_timeout_returns_error_text():
    tool = FakeTool(delay=5.0)
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"], args=[{}], ids=["1"]),
        _resp("工具超时了，只能直接回答"),
    ])
    outcome = await _runner(provider, tools=[tool]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(tool_timeout_seconds=0.3, wall_clock_seconds=10),
    )
    assert outcome.status == "completed"
    assert outcome.tool_calls == 1


async def test_tool_exception_becomes_error_text():
    tool = FakeTool(fail=True)
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"], args=[{}], ids=["1"]),
        _resp("好，我不依赖工具了"),
    ])
    outcome = await _runner(provider, tools=[tool]).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(),
    )
    assert outcome.status == "completed"


# ── provider / 预算 / 取消 ───────────────────────────

async def test_missing_provider_fails():
    outcome = await _runner(None).run(
        task_id="t", run_id="r", objective="x", policy={}, context_text="", limits=_limits()
    )
    assert outcome.status == "failed"
    assert outcome.error == "provider_unavailable"


async def test_budget_block_fails_before_provider_call():
    provider = FakeProvider([_resp("x")])

    def usage_check():
        return "今日 token 用量超限"

    outcome = await _runner(provider, usage_check=usage_check).run(
        task_id="t", run_id="r", objective="x", policy={}, context_text="", limits=_limits()
    )
    assert outcome.status == "failed"
    assert outcome.error.startswith("budget_blocked")
    assert provider.calls == []  # 预算拦截发生在任何模型调用之前


async def test_cancel_check_between_rounds():
    provider = FakeProvider([
        _resp("", tools=["mcp_demo_read"], args=[{}], ids=["1"]),
        _resp("不该到达"),
    ])

    async def cancel_check():
        raise TaskCancelledError

    outcome = await _runner(provider, tools=[FakeTool()], cancel_check=cancel_check).run(
        task_id="t", run_id="r", objective="x", policy={"tools": ["mcp_demo_read"]},
        context_text="", limits=_limits(),
    )
    assert outcome.status == "cancelled"


async def test_never_raises_unexpected_exceptions():
    class BrokenProvider:
        async def text_chat(self, **kwargs):
            raise RuntimeError("connection reset")

    outcome = await _runner(BrokenProvider()).run(
        task_id="t", run_id="r", objective="x", policy={}, context_text="", limits=_limits()
    )
    assert outcome.status == "failed"
    assert "RuntimeError" in outcome.error


# ── 指纹 ─────────────────────────────────────────────

def test_schema_fingerprint_is_stable_and_order_insensitive():
    a = schema_fingerprint({"properties": {"a": {}, "b": {}}, "type": "object"})
    b = schema_fingerprint({"type": "object", "properties": {"b": {}, "a": {}}})
    assert a == b and len(a) == 16


def test_session_id_scopes_task_and_run():
    provider = FakeProvider([_resp("x")])

    async def go():
        return await _runner(provider).run(
            task_id="task1", run_id="run9", objective="x", policy={},
            context_text="", limits=_limits(),
        )

    asyncio.run(go())
    assert provider.calls[0]["session_id"] == "scheduling:task1:run9"
