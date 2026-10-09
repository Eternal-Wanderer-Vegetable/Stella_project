# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Legacy reference trace 捕获器（M0 冻结，docs/migration/cortico/baseline-report.md §4）。

用可脚本化的后端/Planner/前置钩子驱动**当前（提取前）**的 ``Pipeline.run``，把可观察
行为固化为规范化 JSON（``tests/runtime/fixtures/legacy_traces/<场景>.json``）：

- M2 从 Pipeline.run 提取 prepare/generate/finalize 后，同场景 trace 必须与冻结值一致；
- M9 差异回放以这些 JSON 为 legacy 基准（旧 oracle 不随实现修改、不被新输出覆盖）。

覆盖映射（计划 M0「冻结 legacy reference traces」）：普通1次 / 直回0次 / Planner 分支
（WAIT、调用上限、深度后回复）/ 超时 / 后端异常 / 破防兜底 / QQ 分行 / 主动 @ 指令前置 /
工具+证据段落。WebChat、主动发送、调度的入口级行为由既有测试文件冻结
（tests/webui/test_webui_chat.py、tests/test_proactive_*.py、tests/scheduling/），
映射表见 docs/migration/cortico/feature-parity.md。

规范化：``llm_elapsed`` 等计时字段与任何时间戳不入 trace；其余可观察字段全量保留。
再生成仅限 M0 执行一次：``python tests/runtime/regen_traces.py``；此后再生成即破坏 oracle。
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.context import ChatContext
from core.pipeline import Pipeline
from memory.post_processors import (
    bad_phrase_filter,
    log_thought,
    parse_output,
    split_lines,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "legacy_traces"

# 规范化（计划 §7 M9「仅规范化时间/随机ID等已列出字段」的 M0 部分）：
# v1 prompt_builder 会在 prompt 首行注入墙钟时间，重放时刻不同必然不同，
# 以占位符替换；除此之外 prompt 逐字冻结。
_TIME_LINE = re.compile(r"^现在是 \d{4}-\d{2}-\d{2} \d{2}:\d{2}，星期[一二三四五六日]。$", re.MULTILINE)
_NORMALIZED_TIME_LINE = "现在是 <normalized-time>。"


def _normalize_prompt(prompt: str) -> str:
    return _TIME_LINE.sub(_NORMALIZED_TIME_LINE, prompt)

_DEFAULT_SYSTEM_PROMPT = "你是Stella，一个群聊里的伙伴。"


class ScriptedBackend:
    """按脚本逐次返回固定响应的伪后端；记录每次收到的 prompt。"""

    backend_name = "scripted"
    model = "scripted-model"

    def __init__(self, script: list):
        self.script = list(script)
        self.prompts: list[str] = []
        self.system_prompts: list[str] = []

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        if not self.script:
            raise AssertionError("脚本耗尽：场景声明的调用次数与实际不符")
        step = self.script.pop(0)
        if isinstance(step, tuple) and step[0] == "sleep":
            await asyncio.sleep(step[1])
            return ""
        if isinstance(step, Exception):
            raise step
        return step


class ScriptedPlanner:
    """脚本化 Planner：可消耗 deep 调用名额 / 触发 WAIT。"""

    def __init__(self, deep_calls: int = 0, wait: bool = False):
        self.deep_calls = deep_calls
        self.wait = wait

    async def maybe_plan(self, ctx: ChatContext) -> ChatContext:
        ctx.planner_trigger = "scripted"
        if self.deep_calls:
            ctx.llm_call_count += self.deep_calls
            ctx.planner_action = "deep"
        if self.wait:
            ctx.planner_wait = True
            ctx.planner_action = "wait"
        return ctx


async def _direct_reply_hook(ctx: ChatContext):
    """模拟 capability 直回：写入最终答复，Pipeline 应零生成短路。"""
    ctx.reply = "东京明天 27℃，晴。"
    ctx.lines = [ctx.reply]
    return ctx


async def _context_hook(ctx: ChatContext):
    """模拟 build_context/build_user_context：写入确定性的短期上下文。"""
    ctx.short_term = "我: 昨天聚会好开心\n用户(2): 是啊下次再约"
    return ctx


@dataclass
class Scenario:
    name: str
    message: str
    backend_script: list
    # 预置字段（模拟 pre hooks 的产出）
    short_term: str = ""
    tool_summaries: list = field(default_factory=list)
    knowledge_evidence: list = field(default_factory=list)
    trigger: str = "reply"
    intent: str = ""
    # 装配
    pre_direct: bool = False
    pre_context: bool = False
    planner_deep_calls: int = 0
    planner_wait: bool = False
    timeout: float = 5.0
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    use_resolver: bool = False


def _build_ctx(sc: Scenario) -> ChatContext:
    return ChatContext(
        user_id=1001,
        group_id=1,
        msg_id=42,
        message=sc.message,
        trigger=sc.trigger,
        intent=sc.intent,
        short_term=sc.short_term,
        tool_summaries=list(sc.tool_summaries),
        knowledge_evidence=[dict(e) for e in sc.knowledge_evidence],
    )


def _wrap(recorder: list, name: str, hook):
    async def wrapped(ctx):
        recorder.append(name)
        return await hook(ctx)

    return wrapped


async def _capture(sc: Scenario) -> dict:
    backend = ScriptedBackend(sc.backend_script)
    pipeline = Pipeline(timeout=sc.timeout)
    if sc.planner_deep_calls or sc.planner_wait:
        pipeline.set_planner(ScriptedPlanner(sc.planner_deep_calls, sc.planner_wait))
    if sc.use_resolver:
        pipeline.system_prompt_resolver = (
            lambda ctx: f"空间人格[{ctx.group_shared_space or 'implicit'}]：{_DEFAULT_SYSTEM_PROMPT}"
        )
    else:
        pipeline.system_prompt = sc.system_prompt
    pipeline.set_llm_backend(backend)

    pre_ran: list[str] = []
    post_ran: list[str] = []
    # 重建 pre 钩子为带记录的包装（保持注册顺序 = 声明顺序）
    pipeline._pre_hooks = []
    if sc.pre_direct:
        pipeline.register_pre_hook(_wrap(pre_ran, "direct_reply", _direct_reply_hook), priority=50)
    if sc.pre_context:
        pipeline.register_pre_hook(_wrap(pre_ran, "build_context", _context_hook), priority=50)
    # 标准后置钩子（与 ai_gateway.py:223-226 同序同优先级）
    for pri, name, hook in (
        (100, "parse_output", parse_output),
        (80, "bad_phrase_filter", bad_phrase_filter),
        (60, "split_lines", split_lines),
        (40, "log_thought", log_thought),
    ):
        pipeline.register_post_hook(_wrap(post_ran, name, hook), priority=pri)

    ctx = await pipeline.run(_build_ctx(sc))

    return {
        "scenario": sc.name,
        "input": {
            "message": sc.message,
            "trigger": sc.trigger,
            "intent": sc.intent,
            "short_term": sc.short_term,
            "tool_summaries": sc.tool_summaries,
            "knowledge_evidence": sc.knowledge_evidence,
            "system_prompt": sc.system_prompt if not sc.use_resolver else "<resolver>",
        },
        "backend_script": [
            s if isinstance(s, str) else ["sleep", s[1]] if isinstance(s, tuple) else "raise"
            for s in sc.backend_script_source
        ],
        "trace": {
            "llm_calls": [
                {"prompt": _normalize_prompt(p), "system_prompt": _normalize_prompt(s)}
                for p, s in zip(backend.prompts, backend.system_prompts, strict=True)
            ],
            "llm_call_count": ctx.llm_call_count,
            "raw_output": ctx.raw_output,
            "thought": ctx.thought,
            "action": ctx.action,
            "reply": ctx.reply,
            "lines": ctx.lines,
            "pre_hooks_run": pre_ran,
            "post_hooks_run": post_ran,
            "planner": {
                "trigger": getattr(ctx, "planner_trigger", ""),
                "action": getattr(ctx, "planner_action", ""),
                "wait": bool(getattr(ctx, "planner_wait", False)),
            },
            "diagnostics": {
                "llm_backend": ctx.llm_backend,
                "llm_model": ctx.llm_model,
                "context_window_tokens": ctx.context_window_tokens,
                "prompt_budget_tokens": ctx.prompt_budget_tokens,
                "prompt_estimated_tokens": ctx.prompt_estimated_tokens,
                "prompt_truncated": ctx.prompt_truncated,
                "system_prompt_len": ctx.system_prompt_len,
            },
        },
    }


def run_scenario(sc: Scenario) -> dict:
    sc.backend_script_source = list(sc.backend_script)
    return asyncio.run(_capture(sc))


def load_frozen(name: str, generation: str = "m0") -> dict | None:
    if generation == "m0":
        root = FIXTURE_DIR
    elif generation == "p2_protocol":
        root = FIXTURE_DIR / generation
    else:
        raise ValueError(f"unknown trace generation: {generation}")
    path = root / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def freeze(result: dict) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{result['scenario']}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 冻结场景全集（M0 定稿；增删场景 = 修改验收范围，须经迁移计划修订）
# ---------------------------------------------------------------------------

SCENARIOS: list[Scenario] = [
    Scenario(
        name="normal_single_call",
        message="在吗",
        backend_script=["<thought>想想</thought><action>NONE</action><reply>在的呀(joy)\n刚刚在整理照片</reply>"],
        pre_context=True,
    ),
    Scenario(
        name="direct_reply_zero_call",
        message="查东京天气",
        backend_script=[],
        pre_direct=True,
    ),
    Scenario(
        name="planner_wait_silent",
        message="今天讨论度好高",
        backend_script=[],
        planner_wait=True,
    ),
    Scenario(
        name="planner_call_limit_exhausted",
        message="来个深度整理",
        backend_script=[],
        planner_deep_calls=2,
    ),
    Scenario(
        name="planner_deep_then_reply",
        message="结合记忆聊聊",
        backend_script=["<thought>补充</thought><action>NONE</action><reply>你之前提过想再约一次</reply>"],
        planner_deep_calls=1,
        pre_context=True,
    ),
    Scenario(
        name="timeout_fallback",
        message="回复我一下",
        backend_script=[("sleep", 0.5)],
        timeout=0.05,
    ),
    Scenario(
        name="backend_error_fallback",
        message="触发异常",
        backend_script=[RuntimeError("boom")],
    ),
    Scenario(
        name="bad_phrase_fallback",
        message="说句不该说的",
        backend_script=None,  # 运行时以 BAD_PHRASES[0] 构造，见 _materialize
    ),
    Scenario(
        name="proactive_at_instruction_first",
        message="说出那句确认的话",
        backend_script=["<thought>照做</thought><action>NONE</action><reply>昨天玩得很开心呀</reply>"],
        intent="proactive_at",
        short_term="我: 手机好用吗\n用户(2): 还行",
    ),
    Scenario(
        name="tool_and_evidence_sections",
        message="备份怎么做",
        backend_script=["<thought>有手册</thought><action>NONE</action><reply>每日全量备份<ref>1</ref></reply>"],
        tool_summaries=["东京 27℃"],
        knowledge_evidence=[
            {"text": "数据库每日全量备份，保留 30 天。", "citation": "《运维手册》 备份策略（资料库:群资料库）", "doc_title": "运维手册"}
        ],
    ),
]


def _materialize() -> list[Scenario]:
    """把场景中需要引用运行时常量的占位补齐（BAD_PHRASES 等）。"""
    from config import BAD_PHRASES, FALLBACK_REPLY

    for sc in SCENARIOS:
        if sc.backend_script is None:
            sc.backend_script = [
                f"<thought>破防测试</thought><action>NONE</action><reply>{BAD_PHRASES[0]}</reply>",
                f"placeholder:{FALLBACK_REPLY}",
            ]
            # 第二个元素不会被消费（本场景只调用一次），仅为脚本可读性
            sc.backend_script = sc.backend_script[:1]
    return SCENARIOS
