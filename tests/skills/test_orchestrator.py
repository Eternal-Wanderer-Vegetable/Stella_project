# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills.orchestrator 测试：预算快照、fail-closed、动作计划解析、结果契约。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from _helpers import make_manifest

from skills.model import (
    ACTION_LIST_FILES,
    ACTION_RUN_SHELL,
    ArtifactRef,
    SandboxActionOutcome,
    SandboxLimits,
    SkillErrorCode,
    SkillStatus,
)
from skills.orchestrator import (
    MAX_ACTIONS,
    SkillOrchestrator,
    normalize_session_id,
    parse_action_plan,
)

BODY_MAX = 24000
TOTAL_TIMEOUT = 30.0
OUTPUT_MAX = 2000
ASSET_MAX = 524288


def _orchestrator(planner=None, executor=None, tmp_path=None) -> SkillOrchestrator:
    return SkillOrchestrator(
        planner=planner,
        executor=executor,
        workspace_root=(tmp_path or Path()) / "workspaces",
        limits=SandboxLimits(),
        backend="docker",
        image="python:3.12-slim",
        body_max_chars=BODY_MAX,
        total_timeout=TOTAL_TIMEOUT,
        output_max_chars=OUTPUT_MAX,
        asset_max_bytes=ASSET_MAX,
    )


class _FakeExecutor:
    """记录收到的 spec/action，按脚本回放 outcome。"""

    def __init__(self, script=None):
        self.script = script or (
            lambda spec, action: SandboxActionOutcome(
                action=action.action, ok=True, output=f"{action.action} ok"
            )
        )
        self.specs = []
        self.actions = []
        self.cleaned = []

    async def execute(self, spec, action):
        self.specs.append(spec)
        self.actions.append(action)
        return self.script(spec, action)

    async def cleanup(self, spec):
        self.cleaned.append(spec.invocation_id)


ALL = ("run_shell", "run_python", "read_file", "write_file", "list_files")


class TestFailClosed:
    def test_no_executor_yields_unavailable(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        result = asyncio.run(
            _orchestrator(planner=_ok_planner, tmp_path=tmp_path).invoke(
                "做点事", make_manifest(tmp_path / "pdf"), session_id="s1"
            )
        )
        assert result.status is SkillStatus.UNAVAILABLE
        assert result.error_code is SkillErrorCode.SANDBOX_UNAVAILABLE
        assert result.summary  # 有可读摘要

    def test_no_planner_yields_unavailable(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        result = asyncio.run(
            _orchestrator(executor=_FakeExecutor(), tmp_path=tmp_path).invoke(
                "做点事", make_manifest(tmp_path / "pdf"), session_id="s1"
            )
        )
        assert result.status is SkillStatus.UNAVAILABLE

    def test_empty_allowed_actions_denied(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        result = asyncio.run(
            _orchestrator(
                planner=_ok_planner, executor=_FakeExecutor(), tmp_path=tmp_path
            ).invoke(
                "做点事",
                make_manifest(tmp_path / "pdf"),
                session_id="s1",
                allowed_actions=(),
            )
        )
        assert result.status is SkillStatus.DENIED
        assert result.error_code is SkillErrorCode.POLICY_DENIED


class TestInvocationFlow:
    def test_planned_actions_executed_and_summarized(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf", extra_files={"references/spec.md": "x"})

        def _script(spec, action):
            if action.action == ACTION_RUN_SHELL:
                return SandboxActionOutcome(
                    action=action.action,
                    ok=True,
                    output="生成完毕",
                    artifact=ArtifactRef(path="out/report.md", size_bytes=10),
                )
            return SandboxActionOutcome(action=action.action, ok=True, output="done")

        executor = _FakeExecutor(script=_script)
        result = asyncio.run(
            _orchestrator(
                planner=_ok_planner, executor=executor, tmp_path=tmp_path
            ).invoke(
                "整理这份资料", make_manifest(tmp_path / "pdf"), session_id="群1: 123"
            )
        )
        assert result.status is SkillStatus.COMPLETED
        assert result.metrics["actions_planned"] == 2
        assert result.metrics["actions_failed"] == 0
        assert [a.action for a in executor.actions] == [
            ACTION_RUN_SHELL,
            ACTION_LIST_FILES,
        ]
        # workspace 目录由 会话规范化/invocation 组成，挂在配置的工作区根下
        spec = executor.specs[0]
        assert spec.workspace.is_absolute()
        assert "s1" not in str(spec.workspace)  # 会话标识被规范化（"群1: 123"）
        assert result.artifacts and result.artifacts[0].path == "out/report.md"
        assert "run_shell: 生成完毕" in result.summary
        assert executor.cleaned == [result.invocation_id]  # 清理被调用

    def test_actions_whitelisted_and_args_coerced(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        planner_plan = (
            '{"actions": ['
            '{"action": "run_shell", "args": {"command": "ls", "junk": 1}}, '
            '{"action": "format_disk", "args": {}}, '  # 白名单外：丢弃
            '{"action": "read_file", "args": "not-a-dict"}'  # 参数不是 dict：丢弃
            "]}"
        )

        async def _plan(prompt):
            return planner_plan

        executor = _FakeExecutor()
        result = asyncio.run(
            _orchestrator(planner=_plan, executor=executor, tmp_path=tmp_path).invoke(
                "x", make_manifest(tmp_path / "pdf"), session_id="s"
            )
        )
        assert result.status is SkillStatus.COMPLETED
        assert result.metrics["actions_planned"] == 1  # 只有 run_shell 合法
        assert result.metrics["actions_dropped"] == 2
        assert [a.action for a in executor.actions] == ["run_shell"]
        assert executor.actions[0].args["command"] == "ls"
        assert executor.actions[0].args["junk"] == "1"  # 标量被归一成字符串

    def test_invalid_plan_is_failure_not_noop(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")

        async def _plan(prompt):
            return "我觉得不需要执行任何动作（纯文本，非 JSON）"

        result = asyncio.run(
            _orchestrator(
                planner=_plan, executor=_FakeExecutor(), tmp_path=tmp_path
            ).invoke("x", make_manifest(tmp_path / "pdf"), session_id="s")
        )
        assert result.status is SkillStatus.FAILED
        assert result.error_code is SkillErrorCode.EXECUTION_FAILED

    def test_all_actions_failed_is_failure(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        executor = _FakeExecutor(
            script=lambda spec, action: SandboxActionOutcome(
                action=action.action, ok=False, error_code="execution_failed"
            )
        )
        result = asyncio.run(
            _orchestrator(
                planner=_ok_planner, executor=executor, tmp_path=tmp_path
            ).invoke("x", make_manifest(tmp_path / "pdf"), session_id="s")
        )
        assert result.status is SkillStatus.FAILED

    def test_summary_bounded_and_no_raw_output(self, tmp_path, write_skill):
        write_skill(tmp_path, "pdf")
        executor = _FakeExecutor(
            script=lambda spec, action: SandboxActionOutcome(
                action=action.action, ok=True, output="x" * 100000
            )
        )
        result = asyncio.run(
            _orchestrator(
                planner=_ok_planner, executor=executor, tmp_path=tmp_path
            ).invoke("x", make_manifest(tmp_path / "pdf"), session_id="s")
        )
        assert len(result.summary) <= OUTPUT_MAX


class TestParsePlan:
    def test_accepts_bare_list_and_actions_key(self):
        actions, dropped, ok = parse_action_plan(
            '[{"action": "list_files", "args": {}}]', allowed_actions=ALL
        )
        assert ok and not dropped
        assert [a.action for a in actions] == [ACTION_LIST_FILES]
        actions, _, ok = parse_action_plan(
            '{"actions": [{"action": "list_files", "args": {}}]}', allowed_actions=ALL
        )
        assert ok and len(actions) == 1

    def test_garbage_returns_invalid(self):
        actions, dropped, ok = parse_action_plan("完全不是 JSON", allowed_actions=ALL)
        assert not ok and not actions and dropped == 0

    def test_max_actions_enforced(self):
        plan = (
            '{"actions": ['
            + ",".join(
                '{"action": "list_files", "args": {}}' for _ in range(MAX_ACTIONS + 5)
            )
            + "]}"
        )
        actions, dropped, _ok = parse_action_plan(plan, allowed_actions=ALL)
        assert len(actions) == MAX_ACTIONS
        assert dropped >= 5


class TestSessionNormalization:
    def test_dangerous_chars_replaced(self):
        assert normalize_session_id("../../etc") == ".._.._etc"
        assert normalize_session_id("  ") == "anonymous"
        assert normalize_session_id("群:123") == "_123"  # 连续坏字符合并为单个 _


async def _ok_planner(prompt):
    assert "任务目标" in prompt  # 规划请求必须带目标
    assert "run_shell" in prompt  # 与动作 schema
    return (
        '{"actions": ['
        '{"action": "run_shell", "args": {"command": "python make_report.py"}}, '
        '{"action": "list_files", "args": {}}]}'
    )
