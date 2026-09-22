# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""DisabledSandboxExecutor 与策略校验测试（plan §7 步骤 5）。

核心断言：**没有后端时绝不偷偷使用宿主 subprocess**——禁用后端对一切
动作返回 sandbox_unavailable，包括看似无害的 list_files。
"""

from __future__ import annotations

import asyncio

import pytest
from sandbox_helpers import make_action, make_spec

from skills.audit import AuditLog, reset_audit
from skills.model import SkillErrorCode
from skills.sandbox import (
    BACKEND_DISABLED,
    DisabledSandboxExecutor,
    SandboxAvailability,
    create_executor,
    executor_status,
    validate_spec,
)


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    """审计单例钉到每个用例自己的临时文件。"""
    import skills.audit as audit_mod
    import skills.sandbox as sandbox_mod

    log = AuditLog(tmp_path / "audit" / "skills_audit.jsonl")
    monkeypatch.setattr(audit_mod, "_default", log)
    monkeypatch.setattr(sandbox_mod, "audit", lambda: log)
    yield log
    reset_audit()


class TestDisabledExecutor:
    def test_refuses_every_action(self, tmp_path):
        executor = DisabledSandboxExecutor()
        spec = make_spec(tmp_path)
        for action in (
            make_action("run_shell", command="ls"),
            make_action("run_python", code="print(1)"),
            make_action("read_file", path="a.txt"),
            make_action("write_file", path="a.txt", content="x"),
            make_action("list_files", path="."),
        ):
            outcome = asyncio.run(executor.execute(spec, action))
            assert outcome.ok is False
            assert outcome.error_code == SkillErrorCode.SANDBOX_UNAVAILABLE.value
            assert outcome.output == ""

    def test_availability_reports_disabled(self):
        info = DisabledSandboxExecutor().availability()
        assert isinstance(info, SandboxAvailability)
        assert info.backend == BACKEND_DISABLED
        assert info.available is False
        assert info.reason

    def test_cleanup_is_noop(self, tmp_path):
        asyncio.run(DisabledSandboxExecutor().cleanup(make_spec(tmp_path)))


class TestCreateExecutor:
    def test_disabled_backend_by_default(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "SANDBOX_BACKEND", "disabled")
        executor = create_executor()
        assert executor.backend == BACKEND_DISABLED
        assert executor.availability().available is False

    def test_unknown_backend_fails_closed_to_disabled(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "SANDBOX_BACKEND", "teleport")
        executor = create_executor()
        assert executor.backend == BACKEND_DISABLED
        assert "teleport" in executor.availability().reason

    def test_docker_backend_selects_docker_runner(self, monkeypatch):
        """步骤 6 交付 Docker runner 后：docker 后端返回受限容器执行器。"""
        from config import settings
        from skills.runners.docker import DockerSandboxExecutor

        monkeypatch.setattr(settings, "SANDBOX_BACKEND", "docker")
        executor = create_executor()
        assert isinstance(executor, DockerSandboxExecutor)
        assert executor.backend == "docker"


class TestExecutorStatus:
    def test_none_executor_reports_disabled(self):
        status = executor_status(None)
        assert status["backend"] == BACKEND_DISABLED
        assert status["available"] is False

    def test_disabled_executor_status(self, tmp_path):
        status = executor_status(DisabledSandboxExecutor())
        assert status["available"] is False
        assert status["reason"]


class TestValidateSpec:
    def test_valid_spec_passes(self, tmp_path):
        problems = validate_spec(make_spec(tmp_path), workspace_root=tmp_path)
        assert problems == []

    def test_workspace_outside_root_rejected(self, tmp_path):
        spec = make_spec(tmp_path, workspace=tmp_path.parent / "elsewhere" / "inv")
        problems = validate_spec(spec, workspace_root=tmp_path)
        assert any("workspace" in p for p in problems)

    def test_workspace_equal_to_root_rejected(self, tmp_path):
        spec = make_spec(tmp_path, workspace=tmp_path)
        problems = validate_spec(spec, workspace_root=tmp_path)
        assert any("workspace" in p for p in problems)

    def test_network_without_allowlist_rejected(self, tmp_path):
        spec = make_spec(tmp_path, network_enabled=True)
        problems = validate_spec(spec, workspace_root=tmp_path)
        assert any("allowlist" in p for p in problems)

    def test_nonpositive_limits_rejected(self, tmp_path):
        """SandboxLimits 构造期已拒绝负数；这里验证校验器的纵深防御分支。"""
        from skills.model import SandboxLimits

        limits = SandboxLimits()
        object.__setattr__(limits, "timeout_seconds", -1)
        spec = make_spec(tmp_path, limits=limits)
        problems = validate_spec(spec, workspace_root=tmp_path)
        assert any("预算" in p for p in problems)


class TestAuditTrail:
    def test_refusal_is_audited(self, tmp_path, _isolated_audit):
        asyncio.run(
            DisabledSandboxExecutor().execute(
                make_spec(tmp_path), make_action("run_shell", command="rm -rf /")
            )
        )
        events = _isolated_audit.read_recent()
        assert len(events) == 1
        assert events[0]["event"] == "sandbox_refused"
        assert events[0]["action"] == "run_shell"

    def test_emit_never_raises_on_unwritable_path(self, tmp_path):
        # 父路径是普通文件：追加写入必然失败，emit 必须吞掉异常只计数
        blocker = tmp_path / "blocker"
        blocker.write_text("我是文件，不是目录", encoding="utf-8")
        log = AuditLog(blocker / "audit.jsonl")
        log.emit("test_event", command="whatever")
        assert log.dropped == 1
        assert log.emitted == 0
