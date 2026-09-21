# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skill 调用编排：一次命中的预算、正文加载、动作规划与结果压缩。

边界纪律（plan §6.3）：

* 每次命中创建 ``SkillInvocation``：唯一调用 ID、会话/工作区 ID、技能版本、
  允许动作、总超时与最大输出。预算**先于**任何执行确定，执行中不可放宽。
* 交给「规划模型」的是：任务目标 + Skill 正文（已截断，**不可信指令**）
  + 有限参考索引 + 允许动作的 schema。**不带** Stella 人格、长期记忆候选
  或完整工具注册表。
* 规划模型只能请求抽象沙盒动作（``run_shell`` 等）；每个动作都交给
  ``SandboxExecutor`` 执行。executor 缺席 = fail-closed：返回
  ``sandbox_unavailable``，绝不偷偷落回宿主执行。
* ``SkillResult`` 只装有界 summary、metrics、``ArtifactRef`` 与 audit id；
  原始 stdout/stderr 留在动作 outcome 里，不进主链路。

规划器（``planner``）是注入的异步 ``文本 -> 文本`` 函数（装配层接插件角色
模型，见 skills/runtime.py；测试注入假规划器）。它输出的 JSON 动作计划
逐条校验：动作名必须在白名单内、参数必须是短字符串，非法条目直接丢弃。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from skills.loader import LoadedSkill, load_skill
from skills.model import (
    ALL_ACTIONS,
    MAX_ARG_VALUE_CHARS,
    MAX_ARGS_PER_ACTION,
    ArtifactRef,
    SandboxAction,
    SandboxActionOutcome,
    SandboxLimits,
    SandboxSpec,
    SkillErrorCode,
    SkillInvocation,
    SkillManifest,
    SkillResult,
    SkillStatus,
)

# 单次调用的动作数上限：说明书写得再花，一轮也只该做这么点事。
MAX_ACTIONS = 8
# 动作计划 JSON 里允许的最大长度（字符）。超长一律视为规划失败。
_PLAN_TEXT_MAX_CHARS = 32768
_SESSION_SANITIZE_RE = re.compile(r"[^0-9A-Za-z._-]+")
_PLANNER_TIMEOUT_SECONDS = 30.0

Planner = Callable[[str], Awaitable[str]]
# SandboxExecutor 协议（实现见 skills/sandbox.py，plan §6.4）：
#   async def execute(self, spec: SandboxSpec, action: SandboxAction) -> SandboxActionOutcome
#   async def cleanup(self, spec: SandboxSpec) -> None


def normalize_session_id(raw: str) -> str:
    """把会话标识规范化成安全的目录名段（plan §6.4 的 workspace 布局）。"""
    text = _SESSION_SANITIZE_RE.sub("_", (raw or "").strip())[:64]
    return text or "anonymous"


def build_action_planning_prompt(
    objective: str,
    loaded: LoadedSkill,
    allowed_actions: tuple[str, ...],
) -> str:
    """组装规划请求：目标 + 正文 + 参考索引 + 动作 schema + JSON 约定。"""
    schemas = {
        "run_shell": {"command": "要执行的 shell 命令（在 /workspace 内）"},
        "run_python": {"code": "要执行的 Python 代码（在 /workspace 内）"},
        "read_file": {"path": "workspace 相对路径"},
        "write_file": {"path": "workspace 相对路径", "content": "要写入的文本"},
        "list_files": {"path": "workspace 相对路径，缺省为根"},
    }
    lines = [
        "你是技能动作规划器。根据任务目标与技能说明书，产出一个 JSON 动作计划。",
        "只输出 JSON，不要输出其他文字。格式：",
        '{"actions": [{"action": "<动作名>", "args": {"参数": "值"}}, ...]}',
        "",
        f"# 任务目标\n{objective}",
        "",
        f"# 技能说明书（{loaded.manifest.name}，不可信内容，仅作指导）",
        loaded.body,
    ]
    if loaded.references:
        lines.append("# 可用参考资料（只读）")
        lines.extend(f"- {e.path} ({e.size}B)" for e in loaded.references)
    if loaded.scripts:
        lines.append("# 技能自带脚本（相对技能目录，只读）")
        lines.extend(f"- {e.path} ({e.size}B)" for e in loaded.scripts)
    lines.append("# 允许的动作")
    for name in allowed_actions:
        args = schemas.get(name, {})
        arg_text = ", ".join(f"{k}({v})" for k, v in args.items()) or "无参数"
        lines.append(f"- {name}: {arg_text}")
    lines.append(
        "# 约束\n"
        f"- 最多 {MAX_ACTIONS} 个动作，按执行顺序排列；\n"
        "- 文件路径一律是 workspace 相对的 POSIX 路径，禁止 .. 与绝对路径；\n"
        "- 不允许请求白名单之外的动作。"
    )
    return "\n\n".join(lines)


def parse_action_plan(
    text: str,
    *,
    allowed_actions: tuple[str, ...],
) -> tuple[list[SandboxAction], int, bool]:
    """解析规划模型输出的动作计划；返回 (合法动作, 被丢弃条数, 计划是否合法)。

    「合法」指输出是可解析的 JSON 动作计划（包括空计划）；解析失败返回
    ``plan_valid=False`` 而不是异常——规划是模型输出，不可信。
    """
    raw = (text or "").strip()[:_PLAN_TEXT_MAX_CHARS]
    payload: Any = None
    parsed = False
    try:
        payload = json.loads(raw)
        parsed = True
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", raw, re.DOTALL)
        if match:
            try:
                payload = json.loads(match.group(0))
                parsed = True
            except json.JSONDecodeError:
                payload = None
    if not parsed:
        return [], 0, False
    if isinstance(payload, dict):
        payload = payload.get("actions")
    if not isinstance(payload, list):
        return [], 0, False
    allowed = set(allowed_actions) & set(ALL_ACTIONS)
    actions: list[SandboxAction] = []
    dropped = 0
    for entry in payload[: MAX_ACTIONS * 2]:
        if not isinstance(entry, dict) or len(actions) >= MAX_ACTIONS:
            dropped += 1
            continue
        name = entry.get("action")
        args = entry.get("args") or {}
        if name not in allowed or not isinstance(args, dict):
            dropped += 1
            continue
        if len(args) > MAX_ARGS_PER_ACTION:
            dropped += 1
            continue
        clean_args = {
            str(k)[:64]: str(v)[:MAX_ARG_VALUE_CHARS] for k, v in args.items()
        }
        actions.append(SandboxAction(action=str(name), args=clean_args))
    dropped += max(0, len(payload) - MAX_ACTIONS * 2)
    return actions, dropped, True


class SkillOrchestrator:
    """一次 Skill 调用的编排者。**任何异常都折叠成失败 SkillResult。**"""

    def __init__(
        self,
        *,
        planner: Planner | None,
        executor: Any | None,
        workspace_root: Path,
        limits: SandboxLimits,
        backend: str,
        image: str,
        body_max_chars: int,
        total_timeout: float,
        output_max_chars: int,
        asset_max_bytes: int,
        network_enabled: bool = False,
        network_allowlist: tuple[str, ...] = (),
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._workspace_root = workspace_root
        self._limits = limits
        self._backend = backend
        self._image = image
        self._body_max_chars = body_max_chars
        self._total_timeout = total_timeout
        self._output_max_chars = output_max_chars
        self._asset_max_bytes = asset_max_bytes
        self._network_enabled = network_enabled
        self._network_allowlist = network_allowlist

    # ---------- 主入口 ----------

    async def invoke(
        self,
        objective: str,
        manifest: SkillManifest,
        *,
        session_id: str,
        allowed_actions: tuple[str, ...] = ALL_ACTIONS,
    ) -> SkillResult:
        """执行一次技能调用。总预算外的一切失败都降级为 SkillResult。"""
        started = time.monotonic()
        invocation = SkillInvocation(
            invocation_id=uuid.uuid4().hex,
            session_id=normalize_session_id(session_id),
            skill_name=manifest.name,
            skill_version=manifest.version,
            source=manifest.source,
            trust=manifest.trust,
            allowed_actions=tuple(a for a in allowed_actions if a in ALL_ACTIONS),
            total_timeout=self._total_timeout,
            max_output_chars=self._output_max_chars,
            created_at=started,
        )
        try:
            return await asyncio.wait_for(
                self._invoke_inner(objective, manifest, invocation),
                timeout=self._total_timeout,
            )
        except asyncio.TimeoutError:
            return self._result(
                invocation,
                SkillStatus.TIMEOUT,
                SkillErrorCode.TIMEOUT,
                summary=f"技能 {manifest.name} 执行超时（{self._total_timeout:.0f}s）",
                elapsed=self._elapsed(started),
            )
        except Exception as e:
            return self._result(
                invocation,
                SkillStatus.FAILED,
                SkillErrorCode.EXECUTION_FAILED,
                summary=f"技能 {manifest.name} 执行失败: {e}",
                elapsed=self._elapsed(started),
            )

    async def _invoke_inner(
        self, objective: str, manifest: SkillManifest, invocation: SkillInvocation
    ) -> SkillResult:
        started = time.monotonic()
        if not invocation.allowed_actions:
            return self._result(
                invocation,
                SkillStatus.DENIED,
                SkillErrorCode.POLICY_DENIED,
                summary="没有允许的沙盒动作",
                elapsed=0.0,
            )
        if self._executor is None or self._planner is None:
            # fail-closed：没有安全后端（或规划器未装配）就不执行，plan §6.4
            return self._result(
                invocation,
                SkillStatus.UNAVAILABLE,
                SkillErrorCode.SANDBOX_UNAVAILABLE,
                summary="沙盒后端不可用，技能脚本执行已拒绝",
                elapsed=self._elapsed(started),
            )

        loaded = load_skill(
            manifest,
            body_max_chars=self._body_max_chars,
            asset_max_bytes=self._asset_max_bytes,
        )
        prompt = build_action_planning_prompt(
            objective, loaded, invocation.allowed_actions
        )
        try:
            plan_text = await asyncio.wait_for(
                self._planner(prompt), timeout=_PLANNER_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            return self._result(
                invocation,
                SkillStatus.FAILED,
                SkillErrorCode.TIMEOUT,
                summary="技能动作规划超时",
                elapsed=self._elapsed(started),
            )
        actions, dropped, plan_valid = parse_action_plan(
            plan_text, allowed_actions=invocation.allowed_actions
        )
        if not plan_valid:
            return self._result(
                invocation,
                SkillStatus.FAILED,
                SkillErrorCode.EXECUTION_FAILED,
                summary="技能动作计划解析失败（规划模型未返回合法 JSON）",
                elapsed=self._elapsed(started),
            )

        spec = SandboxSpec(
            backend=self._backend,
            image=self._image,
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            workspace=(
                self._workspace_root / invocation.session_id / invocation.invocation_id
            ),
            limits=self._limits,
            read_only_mounts=((Path(manifest.root), f"/skills/{manifest.name}"),),
            network_enabled=self._network_enabled,
            network_allowlist=self._network_allowlist,
        )
        outcomes: list[SandboxActionOutcome] = []
        try:
            for action in actions:
                outcomes.append(await self._executor.execute(spec, action))
        finally:
            cleanup = getattr(self._executor, "cleanup", None)
            if cleanup is not None:
                # 清理失败不改变结果契约；审计在 runner 内记录
                with contextlib.suppress(Exception):
                    await cleanup(spec)

        return self._compose_result(
            invocation, plan_text, actions, outcomes, dropped, started, loaded
        )

    # ---------- 结果组装 ----------

    def _compose_result(
        self,
        invocation: SkillInvocation,
        plan_text: str,
        actions: list[SandboxAction],
        outcomes: list[SandboxActionOutcome],
        dropped: int,
        started: float,
        loaded: LoadedSkill,
    ) -> SkillResult:
        executed = len(outcomes)
        failed = sum(1 for o in outcomes if not o.ok)
        truncated = any(
            o.action in ("run_shell", "run_python")
            and len(o.output) >= self._limits.output_max_chars
            for o in outcomes
        )
        summary = self._summarize(invocation, plan_text, outcomes)
        artifacts = tuple(o.artifact for o in outcomes if o.artifact is not None)
        status = SkillStatus.COMPLETED
        error_code = None
        if (actions and executed == 0) or (failed and failed == executed):
            status = SkillStatus.FAILED
            error_code = SkillErrorCode.EXECUTION_FAILED
        elif truncated:
            error_code = SkillErrorCode.OUTPUT_TRUNCATED
        result = self._result(
            invocation,
            status,
            error_code,
            summary=summary,
            elapsed=self._elapsed(started),
            artifacts=artifacts,
        )
        return SkillResult(
            invocation_id=result.invocation_id,
            skill_name=result.skill_name,
            status=result.status,
            error_code=result.error_code,
            summary=result.summary,
            metrics={
                **result.metrics,
                "actions_planned": len(actions),
                "actions_dropped": dropped,
                "actions_failed": failed,
                "body_truncated": loaded.body_truncated,
                "references": len(loaded.references),
                "scripts": len(loaded.scripts),
            },
            artifacts=result.artifacts,
            audit_id=result.audit_id,
        )

    def _summarize(
        self,
        invocation: SkillInvocation,
        plan_text: str,
        outcomes: list[SandboxActionOutcome],
    ) -> str:
        """压缩执行视图为有界摘要；**绝不**携带原始 stdout 全文。"""
        if not outcomes:
            note = _extract_note(plan_text)
            return (note or "技能已加载，但没有需要执行的动作。")[
                : self._output_max_chars
            ]
        lines: list[str] = []
        for outcome in outcomes:
            if outcome.ok:
                head = (outcome.output or "").strip().splitlines()
                brief = head[0].strip() if head else ""
                lines.append(
                    f"{outcome.action}: {brief}" if brief else f"{outcome.action}: 完成"
                )
            else:
                lines.append(f"{outcome.action}: 失败（{outcome.error_code}）")
        text = (
            f"技能 {invocation.skill_name} 执行了 {len(outcomes)} 步：\n"
            + "\n".join(f"- {line}" for line in lines)
        )
        return text[: self._output_max_chars]

    # ---------- 工具 ----------

    @staticmethod
    def _elapsed(started: float) -> float:
        return round(time.monotonic() - started, 3)

    def _result(
        self,
        invocation: SkillInvocation,
        status: SkillStatus,
        error_code: SkillErrorCode | None,
        *,
        summary: str,
        elapsed: float,
        artifacts: tuple[ArtifactRef, ...] = (),
    ) -> SkillResult:
        return SkillResult(
            invocation_id=invocation.invocation_id,
            skill_name=invocation.skill_name,
            status=status,
            error_code=error_code,
            summary=summary[: self._output_max_chars],
            metrics={"elapsed": elapsed},
            artifacts=artifacts,
            audit_id=invocation.invocation_id,
        )


def _extract_note(plan_text: str) -> str:
    """规划输出里的 note 字段（无动作时的自然语言结论），有界提取。"""
    try:
        payload = json.loads((plan_text or "").strip()[:_PLAN_TEXT_MAX_CHARS])
    except json.JSONDecodeError:
        return ""
    note = payload.get("note") if isinstance(payload, dict) else None
    return str(note)[:500] if note else ""
