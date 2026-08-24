# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Capability 前置钩子的单测。

三条不变量：

1. **绝不抛异常**。能力层是增量功能，它坏掉的后果应该是「这轮没用上工具」，
   而不是「Stella 不说话了」；
2. **记忆门控默认关闭**。ROUTER_GATE_MEMORY=false 时记忆检索无条件执行，
   Router 只观测——误判 memory=False 是静默退化（「它突然不记得你了」）；
3. **两条分支并行且互不拖累**。一条炸了另一条照样出结果。
"""

import asyncio

import pytest

from capability.hooks import (
    HOOK_PRIORITY,
    activate_capabilities,
    build_tool_tasks,
    register,
)
from capability.registry import Capability, CapabilityProvider
from capability.registry import registry as singleton
from capability.router.types import CapabilityHit, Route
from core.context import ChatContext
from core.tasks import Result, ResultStatus, TaskType


def _run(coro):
    return asyncio.run(coro)


def _ctx(message: str = "帮我查一下东京天气", **kw) -> ChatContext:
    return ChatContext(user_id=111, group_id=1, msg_id=42, message=message, **kw)


@pytest.fixture(autouse=True)
def _hook_defaults(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_GATE_MEMORY", False)
    monkeypatch.setattr(settings, "COMES_ENABLED", True)
    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", True)


@pytest.fixture
def stub_route(monkeypatch):
    """把 Router 换成可控替身——本文件测的是钩子编排，不是路由判定。"""
    import capability.router as router_mod

    holder = {}

    def _set(route: Route):
        async def _fake(message, **kwargs):
            holder["message"] = message
            holder["kwargs"] = kwargs
            return route

        monkeypatch.setattr(router_mod, "route", _fake)
        return holder

    return _set


@pytest.fixture
def spy_memory(monkeypatch):
    """记录 build_user_context 是否被调用。"""
    import memory.pre_processors as pre

    calls = []

    async def _fake(ctx):
        calls.append(ctx)
        ctx.user_profile = "画像"
        return ctx

    monkeypatch.setattr(pre, "build_user_context", _fake)
    return calls


@pytest.fixture
def spy_comes(monkeypatch):
    """把 execute_all 换成替身，避免拉起真实工具链。"""
    import capability.comes as comes_pkg

    calls = []

    async def _fake(tasks, *, event, target=None, tool_manager=None):
        calls.append({"tasks": tasks, "event": event})
        return [
            Result(
                task_id=t.task_id,
                status=ResultStatus.SUCCESS,
                summary=f"{t.capability} 的结果",
                metadata={"capability": t.capability},
            )
            for t in tasks
        ]

    monkeypatch.setattr(comes_pkg, "execute_all", _fake)
    return calls


# ---------- 任务构造 ----------


def test_build_tool_tasks_uses_user_message_as_objective():
    """objective 用用户原话：提炼只会丢信息（「东京明天」提炼后城市和日期就没了）。"""
    route = Route(tool=True, capabilities=[CapabilityHit("weather.query", 0.82)])
    tasks = build_tool_tasks(route, "帮我查一下东京明天天气")
    assert len(tasks) == 1
    assert tasks[0].type is TaskType.TOOL_EXECUTE
    assert tasks[0].capability == "weather.query"
    assert tasks[0].objective == "帮我查一下东京明天天气"
    assert tasks[0].constraints["router_score"] == 0.82


def test_build_tool_tasks_one_per_capability():
    route = Route(
        tool=True,
        capabilities=[CapabilityHit("a", 0.9), CapabilityHit("b", 0.5)],
    )
    tasks = build_tool_tasks(route, "msg")
    assert [t.capability for t in tasks] == ["a", "b"]
    # task_id 必须互不相同（并行管理与 DAG 都靠它）
    assert len({t.task_id for t in tasks}) == 2


def test_build_tool_tasks_empty_route():
    assert build_tool_tasks(Route(), "msg") == []


# ---------- 记忆门控 ----------


def test_memory_runs_when_gate_disabled(stub_route, spy_memory):
    """默认（门控关闭）：Router 说不要记忆也照样检索，只观测不生效。"""
    stub_route(Route(memory=False, tool=False))
    ctx = _run(activate_capabilities(_ctx()))
    assert len(spy_memory) == 1
    assert ctx.user_profile == "画像"


def test_memory_skipped_when_gate_enabled(monkeypatch, stub_route, spy_memory):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_GATE_MEMORY", True)
    stub_route(Route(memory=False, tool=False))
    _run(activate_capabilities(_ctx()))
    assert spy_memory == []


def test_memory_runs_when_gate_enabled_and_route_wants_it(monkeypatch, stub_route, spy_memory):
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_GATE_MEMORY", True)
    stub_route(Route(memory=True, tool=False))
    _run(activate_capabilities(_ctx()))
    assert len(spy_memory) == 1


# ---------- 路由结果落到 ctx ----------


def test_route_is_stored_on_context(stub_route, spy_memory):
    route = Route(tool=False, reason="测试原因")
    stub_route(route)
    ctx = _run(activate_capabilities(_ctx()))
    assert ctx.route is route


def test_intent_and_trigger_are_passed_to_router(stub_route, spy_memory):
    holder = stub_route(Route())
    _run(activate_capabilities(_ctx(intent="proactive_at", trigger="reply")))
    assert holder["kwargs"]["intent"] == "proactive_at"
    assert holder["kwargs"]["trigger"] == "reply"


# ---------- Comes 分支 ----------


def test_comes_runs_and_fills_summaries(stub_route, spy_memory, spy_comes, fake_bot, fake_nb_event):
    stub_route(Route(tool=True, capabilities=[CapabilityHit("weather.query", 0.8)]))
    ctx = _ctx(raw_event=fake_nb_event, bot=fake_bot)
    _run(activate_capabilities(ctx))

    assert len(spy_comes) == 1
    assert ctx.tool_summaries == ["weather.query 的结果"]
    assert len(ctx.task_results) == 1


def test_comes_skipped_without_platform_handles(stub_route, spy_memory, spy_comes):
    """主动发言路径没有用户事件，工具能力自然不可用——属正常，不该报错。"""
    stub_route(Route(tool=True, capabilities=[CapabilityHit("weather.query", 0.8)]))
    ctx = _run(activate_capabilities(_ctx()))
    assert spy_comes == []
    assert ctx.tool_summaries == []


def test_comes_skipped_when_disabled(
    monkeypatch, stub_route, spy_memory, spy_comes, fake_bot, fake_nb_event,
):
    from config import settings

    monkeypatch.setattr(settings, "COMES_ENABLED", False)
    stub_route(Route(tool=True, capabilities=[CapabilityHit("weather.query", 0.8)]))
    _run(activate_capabilities(_ctx(raw_event=fake_nb_event, bot=fake_bot)))
    assert spy_comes == []


def test_comes_skipped_when_compat_disabled(
    monkeypatch, stub_route, spy_memory, spy_comes, fake_bot, fake_nb_event,
):
    from config import settings

    monkeypatch.setattr(settings, "ASTRBOT_COMPAT_ENABLED", False)
    stub_route(Route(tool=True, capabilities=[CapabilityHit("weather.query", 0.8)]))
    _run(activate_capabilities(_ctx(raw_event=fake_nb_event, bot=fake_bot)))
    assert spy_comes == []


def test_failed_results_do_not_reach_the_prompt(
    monkeypatch, stub_route, spy_memory, fake_bot, fake_nb_event,
):
    """失败任务不告知 Stella：它不该向用户解释某个工具报了什么错。"""
    import capability.comes as comes_pkg

    async def _fake(tasks, *, event, target=None, tool_manager=None):
        return [
            Result(task_id="t1", status=ResultStatus.FAILED, summary="", metadata={}),
            Result(task_id="t2", status=ResultStatus.SUCCESS, summary="真实结果", metadata={}),
        ]

    monkeypatch.setattr(comes_pkg, "execute_all", _fake)
    stub_route(Route(tool=True, capabilities=[CapabilityHit("a", 0.8), CapabilityHit("b", 0.7)]))
    ctx = _ctx(raw_event=fake_nb_event, bot=fake_bot)
    _run(activate_capabilities(ctx))

    assert ctx.tool_summaries == ["真实结果"]
    # 完整结果仍全部留在 ctx 上，供日志追溯
    assert len(ctx.task_results) == 2


# ---------- 并行与异常隔离 ----------


def test_both_branches_run_concurrently(stub_route, monkeypatch, fake_bot, fake_nb_event):
    """方案第 17 节：Memory 与 Comes 并行。两条各睡 150ms，串行会到 300ms。"""
    import capability.comes as comes_pkg
    import memory.pre_processors as pre

    async def slow_memory(ctx):
        await asyncio.sleep(0.15)
        return ctx

    async def slow_comes(tasks, *, event, target=None, tool_manager=None):
        await asyncio.sleep(0.15)
        return [Result(task_id="t1", status=ResultStatus.SUCCESS, summary="ok", metadata={})]

    monkeypatch.setattr(pre, "build_user_context", slow_memory)
    monkeypatch.setattr(comes_pkg, "execute_all", slow_comes)
    stub_route(Route(tool=True, capabilities=[CapabilityHit("a", 0.8)]))

    async def _timed():
        started = asyncio.get_running_loop().time()
        await activate_capabilities(_ctx(raw_event=fake_nb_event, bot=fake_bot))
        return asyncio.get_running_loop().time() - started

    elapsed = _run(_timed())
    assert elapsed < 0.25, f"两条分支似乎串行了（耗时 {elapsed:.3f}s）"


def test_memory_failure_does_not_kill_comes(
    stub_route, monkeypatch, spy_comes, fake_bot, fake_nb_event,
):
    import memory.pre_processors as pre

    async def boom(ctx):
        raise RuntimeError("记忆库炸了")

    monkeypatch.setattr(pre, "build_user_context", boom)
    stub_route(Route(tool=True, capabilities=[CapabilityHit("a", 0.8)]))
    ctx = _ctx(raw_event=fake_nb_event, bot=fake_bot)
    _run(activate_capabilities(ctx))
    assert ctx.tool_summaries == ["a 的结果"]


def test_comes_failure_does_not_kill_memory(
    stub_route, monkeypatch, spy_memory, fake_bot, fake_nb_event,
):
    import capability.comes as comes_pkg

    async def boom(tasks, *, event, target=None, tool_manager=None):
        raise RuntimeError("工具链炸了")

    monkeypatch.setattr(comes_pkg, "execute_all", boom)
    stub_route(Route(tool=True, capabilities=[CapabilityHit("a", 0.8)]))
    ctx = _ctx(raw_event=fake_nb_event, bot=fake_bot)
    _run(activate_capabilities(ctx))
    assert len(spy_memory) == 1
    assert ctx.tool_summaries == []


def test_router_entry_failure_degrades_to_memory(monkeypatch, spy_memory):
    """路由入口本身炸了（import 出问题等）也必须降级，不能击穿主链路。"""
    import capability.router as router_mod

    async def boom(message, **kwargs):
        raise RuntimeError("路由入口炸了")

    monkeypatch.setattr(router_mod, "route", boom)
    ctx = _run(activate_capabilities(_ctx()))
    assert len(spy_memory) == 1
    assert ctx.route is not None
    assert ctx.route.tool is False


def test_no_jobs_returns_context_unchanged(monkeypatch, stub_route, spy_memory):
    """门控开启 + 无工具：两条分支都不跑，直接返回。"""
    from config import settings

    monkeypatch.setattr(settings, "ROUTER_GATE_MEMORY", True)
    stub_route(Route(memory=False, tool=False))
    ctx = _ctx()
    assert _run(activate_capabilities(ctx)) is ctx
    assert spy_memory == []


# ---------- 注册 ----------


def test_register_uses_priority_below_build_context():
    """必须小于 build_context(50)：短期上下文永远该先组装好。"""
    assert HOOK_PRIORITY < 50

    registered = []

    class FakePipeline:
        def register_pre_hook(self, hook, priority=10):
            registered.append((hook, priority))

    register(FakePipeline())
    assert registered == [(activate_capabilities, HOOK_PRIORITY)]


def test_registry_singleton_is_used_by_default():
    """钩子默认走模块级注册表（生产路径），不是每次新建一个。"""
    singleton.register(
        Capability(
            id="x.y",
            description="d",
            providers=[
                CapabilityProvider(provider_id="x.y#t", capability_id="x.y", tool_name="t"),
            ],
        ),
    )
    assert singleton.get("x.y") is not None
