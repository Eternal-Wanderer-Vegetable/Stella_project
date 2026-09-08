# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""受限 Planner（设计阶段五）的测试。

钉住验收项：
- 普通路径 1 次 LLM、深度路径 2 次 LLM（名额统一扣减）；
- 每轮最多 1 次深度记忆查询，结果压缩后回填；
- WAIT 只对主动路径生效、且不触发回复 LLM（wait 不轮询）；
- 快速路径 / 回复 prompt 不包含 Planner 的动作表（工具 schema）；
- 本地触发判定零 LLM：未命中时一次调用都不发生。
"""

import asyncio

import core.planner as planner_mod
from core.context import ChatContext
from core.pipeline import Pipeline
from core.planner import (
    RestrictedPlanner,
    _compress_memories,
    detect_trigger,
    parse_action,
)


class _FakeBackend:
    """按脚本回放的伪后端。"""

    backend_name = "fake"
    model = "fake-model"

    def __init__(self, reply: str = "<action>REPLY</action>"):
        self.reply = reply
        self.calls = 0
        self.last_prompt = ""
        self.last_system_prompt = ""

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.calls += 1
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt
        return self.reply


def _ctx(**kw):
    base = {"user_id": 100, "group_id": 1, "msg_id": 0, "message": "上次说的旅行计划怎么样了"}
    base.update(kw)
    return ChatContext(**base)


# ============================================================
# 本地触发判定（零 LLM）
# ============================================================


def test_history_reference_triggers_deep_path():
    trig = detect_trigger("上次说的那个游戏叫什么来着", trigger="reply")
    assert trig is not None and trig.kind == "history_reference"


def test_short_deixis_triggers_ambiguity():
    trig = detect_trigger("那个怎么样了", trigger="reply")
    assert trig is not None and trig.kind == "ambiguity"


def test_plain_message_stays_fast_path():
    assert detect_trigger("今天天气不错，出去走走", trigger="reply") is None


def test_instruction_intent_never_triggers():
    # 主动 @ 的 message 是任务指令，不是用户内容
    assert detect_trigger("上次说的那句确认话术", trigger="reply", intent="proactive_at") is None


def test_proactive_requires_opt_in(monkeypatch):
    monkeypatch.setattr(planner_mod, "PLANNER_PROACTIVE_WAIT_ENABLED", False)
    assert detect_trigger("随便说点什么", trigger="proactive") is None
    monkeypatch.setattr(planner_mod, "PLANNER_PROACTIVE_WAIT_ENABLED", True)
    trig = detect_trigger("随便说点什么", trigger="proactive")
    assert trig is not None and trig.kind == "proactive_unclear"


# ============================================================
# 动作解析与结果压缩
# ============================================================


def test_parse_action_tagged_and_bare_forms():
    assert parse_action("<action>QUERY_MEMORY: 旅行 计划</action>") == ("QUERY_MEMORY", "旅行 计划")
    assert parse_action("<action>WAIT</action>") == ("WAIT", "")
    assert parse_action("QUERY_MEMORY: 旅行") == ("QUERY_MEMORY", "旅行")
    # 垃圾输出按 REPLY 处理（安全默认：宁可快速回复也不卡死）
    assert parse_action("我觉得应该先聊聊") == ("REPLY", "")


def test_compress_memories_caps_lines_and_keeps_fields(monkeypatch):
    monkeypatch.setattr(planner_mod, "PLANNER_QUERY_MEMORY_MAX_LINES", 2)
    mems = [
        {
            "content": f"记忆内容{i}" + "很长的" * 30,
            "user_id": "100",
            "confidence": 0.8,
            "last_confirmed_at": "2026-09-01 10:00:00",
        }
        for i in range(5)
    ]
    out = _compress_memories(mems)
    assert out.startswith("[深度记忆] ")
    assert out.count("事实：") == 2  # 行数上限
    assert "时间：2026-09-01" in out and "参与者：用户100" in out and "置信度：0.80" in out
    assert "…" in out  # 超长事实被截断
    assert _compress_memories([]) == ""


# ============================================================
# Planner 硬限制
# ============================================================


def _planner(reply: str) -> tuple[RestrictedPlanner, _FakeBackend]:
    backend = _FakeBackend(reply)
    return RestrictedPlanner(backend, timeout=5.0), backend


def test_no_trigger_means_zero_llm(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    planner, backend = _planner("<action>WAIT</action>")
    ctx = _ctx(message="今天天气不错")  # 不命中触发词
    asyncio.run(planner.maybe_plan(ctx))
    assert backend.calls == 0
    assert ctx.llm_call_count == 0
    assert ctx.planner_trigger == ""


def test_query_memory_runs_once_and_compresses(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    monkeypatch.setattr(
        planner_mod.RestrictedPlanner,
        "_query_memory",
        lambda self, ctx, q: "[深度记忆] 事实：用户想去东京",
    )
    planner, backend = _planner("<action>QUERY_MEMORY: 旅行 计划</action>")
    ctx = _ctx()
    asyncio.run(planner.maybe_plan(ctx))
    assert backend.calls == 1
    assert ctx.llm_call_count == 1
    assert ctx.planner_action == "QUERY_MEMORY"
    assert ctx.deep_tool_calls == 1
    assert ctx.tool_summaries == ["[深度记忆] 事实：用户想去东京"]

    # 名额守卫：再规划一次不产生第二次 LLM（要给 Replyer 留名额）
    asyncio.run(planner.maybe_plan(ctx))
    assert backend.calls == 1


def test_tool_call_budget_blocks_second_query(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    planner, _backend = _planner("<action>QUERY_MEMORY: 旅行</action>")
    ctx = _ctx()
    ctx.deep_tool_calls = 1  # 已用完本轮深度查询名额
    asyncio.run(planner.maybe_plan(ctx))
    assert ctx.tool_summaries == []
    assert ctx.deep_tool_calls == 1  # 不再增加


def test_wait_only_honored_on_proactive(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    planner, _ = _planner("<action>WAIT</action>")

    ctx_reply = _ctx(trigger="reply")
    asyncio.run(planner.maybe_plan(ctx_reply))
    assert ctx_reply.planner_wait is False  # @ 硬触发不能被吞

    ctx_proactive = _ctx(trigger="proactive")
    asyncio.run(planner.maybe_plan(ctx_proactive))
    assert ctx_proactive.planner_wait is True


def test_budget_block_skips_planner(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: "daily budget exhausted")
    planner, backend = _planner("<action>WAIT</action>")
    ctx = _ctx()
    asyncio.run(planner.maybe_plan(ctx))
    assert backend.calls == 0
    assert ctx.planner_wait is False  # 预算被拦时连 WAIT 都不该发生，正常回复路径继续


# ============================================================
# Pipeline 集成：深度路径 2 次 LLM、wait 0 次、快速路径无动作表
# ============================================================


class _ReplyBackend(_FakeBackend):
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.calls += 1
        self.last_prompt = prompt
        return "<reply>好呀</reply>"


def test_deep_path_total_two_llm_calls(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    monkeypatch.setattr(
        planner_mod.RestrictedPlanner,
        "_query_memory",
        lambda self, ctx, q: "[深度记忆] 事实：用户想去东京旅行",
    )
    planner_backend = _FakeBackend("<action>QUERY_MEMORY: 旅行 计划</action>")
    planner = RestrictedPlanner(planner_backend, timeout=5.0)

    reply_backend = _ReplyBackend()
    pipeline = Pipeline(timeout=5.0)
    pipeline.set_llm_backend(reply_backend)
    pipeline.set_planner(planner)

    ctx = asyncio.run(pipeline.run(_ctx()))
    # 验收项：深度路径最多 2 次 LLM（Planner 1 + Replyer 1）
    assert planner_backend.calls == 1
    assert reply_backend.calls == 1
    assert ctx.llm_call_count == 2
    # 工具结果压缩回填进了回复 prompt（渲染在「刚刚查到的信息」段）
    assert "刚刚查到的信息" in ctx.prompt_log
    assert "[深度记忆]" in ctx.prompt_log
    # 验收项：回复 prompt 不包含 Planner 动作表（快速路径/Replyer 无工具 schema）
    assert "<action>QUERY_MEMORY" not in ctx.prompt_log
    # 动作表（工具 schema）只出现在 Planner 自己的 system prompt 里
    assert "<action>QUERY_MEMORY" in planner_backend.last_system_prompt


def test_fast_path_prompt_has_no_tool_schema(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    planner_backend = _FakeBackend("<action>WAIT</action>")
    planner = RestrictedPlanner(planner_backend, timeout=5.0)

    reply_backend = _ReplyBackend()
    pipeline = Pipeline(timeout=5.0)
    pipeline.set_llm_backend(reply_backend)
    pipeline.set_planner(planner)

    ctx = asyncio.run(pipeline.run(_ctx(message="今天天气不错")))
    assert planner_backend.calls == 0  # 本地判定未命中，零 LLM
    assert reply_backend.calls == 1
    assert ctx.llm_call_count == 1
    assert "<action>" not in ctx.prompt_log


def test_wait_skips_reply_llm_entirely(monkeypatch):
    monkeypatch.setattr(planner_mod, "budget_blocked", lambda role: None)
    monkeypatch.setattr(planner_mod, "PLANNER_PROACTIVE_WAIT_ENABLED", True)
    planner_backend = _FakeBackend("<action>WAIT</action>")
    planner = RestrictedPlanner(planner_backend, timeout=5.0)

    reply_backend = _ReplyBackend()
    pipeline = Pipeline(timeout=5.0)
    pipeline.set_llm_backend(reply_backend)
    pipeline.set_planner(planner)

    ctx = asyncio.run(pipeline.run(_ctx(trigger="proactive", user_id=0)))
    # 验收项：wait 不轮询 LLM——只有 Planner 的 1 次调用，Replyer 完全不跑
    assert planner_backend.calls == 1
    assert reply_backend.calls == 0
    assert ctx.llm_call_count == 1
    assert ctx.planner_wait is True
    assert ctx.raw_output == ""
