# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills.model 契约测试（plan §7 步骤 1：先建立单测夹具与数据契约）。"""

from __future__ import annotations

import pytest

from skills.model import (
    ArtifactRef,
    SandboxLimits,
    SandboxSpec,
    SkillCandidate,
    SkillErrorCode,
    SkillInvocation,
    SkillManifest,
    SkillResult,
    SkillSource,
    SkillStatus,
    SkillTrustLevel,
    safe_relative_path,
    skill_name_is_valid,
    trust_for_source,
)


class TestNameValidation:
    def test_accepts_typical_names(self):
        assert skill_name_is_valid("pdf")
        assert skill_name_is_valid("doc-processor")
        assert skill_name_is_valid("web_research.v2")

    def test_rejects_bad_names(self):
        assert not skill_name_is_valid("")
        assert not skill_name_is_valid("Pdf")  # 大写：跨平台目录名冲突
        assert not skill_name_is_valid("has space")
        assert not skill_name_is_valid("..")
        assert not skill_name_is_valid("a/../b")
        assert not skill_name_is_valid("-leading-dash")  # 必须字母/数字开头
        assert not skill_name_is_valid("x" * 65)


class TestSafeRelativePath:
    def test_accepts_normal_relative_paths(self):
        assert safe_relative_path("references/guide.md") is not None
        assert safe_relative_path("scripts/run.py") is not None
        assert safe_relative_path("SKILL.md") is not None

    def test_rejects_escape_attempts(self):
        assert safe_relative_path("../secret") is None
        assert safe_relative_path("a/../../b") is None
        assert safe_relative_path("/etc/passwd") is None
        assert safe_relative_path("C:/Windows/system32") is None
        assert safe_relative_path("C:\\Windows") is None
        assert safe_relative_path("a\\b") is None
        assert safe_relative_path("") is None
        assert safe_relative_path("./") is None


class TestTrustMapping:
    def test_fixed_mapping(self):
        assert trust_for_source(SkillSource.BUILTIN) is SkillTrustLevel.CONTROLLED
        assert trust_for_source(SkillSource.USER) is SkillTrustLevel.MANAGED
        assert trust_for_source(SkillSource.PLUGIN) is SkillTrustLevel.MANAGED
        assert trust_for_source(SkillSource.WORKSPACE) is SkillTrustLevel.UNTRUSTED

    def test_source_priority_order(self):
        from skills.model import SOURCE_PRIORITY

        assert (
            SOURCE_PRIORITY[SkillSource.WORKSPACE]
            > SOURCE_PRIORITY[SkillSource.USER]
            > SOURCE_PRIORITY[SkillSource.PLUGIN]
            > SOURCE_PRIORITY[SkillSource.BUILTIN]
        )


class TestManifest:
    def _manifest(self, source: SkillSource = SkillSource.USER) -> SkillManifest:
        return SkillManifest(
            name="pdf",
            description="处理 PDF",
            source=source,
            root="/tmp/skills/pdf",
            body_size=100,
            content_digest="a" * 64,
        )

    def test_candidate_is_metadata_only(self):
        manifest = self._manifest()
        candidate = manifest.candidate(score=0.8, reason="keyword:pdf")
        assert isinstance(candidate, SkillCandidate)
        # 候选视图不携带磁盘路径——路径属于 catalog 内部
        data = candidate.__dataclass_fields__.keys()
        assert "root" not in data
        assert candidate.name == "pdf"
        assert candidate.trust == SkillTrustLevel.MANAGED
        assert candidate.content_digest == "a" * 64

    def test_version_is_short_digest(self):
        assert self._manifest().version == "a" * 16

    def test_metadata_holds_only_strings(self):
        manifest = self._manifest()
        manifest.metadata["license"] = "MIT"
        assert manifest.metadata["license"] == "MIT"


class TestSandboxLimits:
    def test_rejects_non_positive(self):
        with pytest.raises(ValueError):
            SandboxLimits(cpu=0)
        with pytest.raises(ValueError):
            SandboxLimits(memory_mb=-1)
        with pytest.raises(ValueError):
            SandboxLimits(pids=0)
        with pytest.raises(ValueError):
            SandboxLimits(timeout_seconds=-5)
        with pytest.raises(ValueError):
            SandboxLimits(output_max_chars=0)
        with pytest.raises(ValueError):
            SandboxLimits(artifact_max_bytes=-1)

    def test_narrowed_only_tightens(self):
        base = SandboxLimits(cpu=2.0, memory_mb=512, timeout_seconds=120.0)
        narrowed = base.narrowed(cpu=1.0, timeout_seconds=30.0)
        assert narrowed.cpu == 1.0
        assert narrowed.timeout_seconds == 30.0
        assert narrowed.memory_mb == 512  # 未指定的字段保持不变
        # 更大的 override 不放宽既有预算
        relaxed = base.narrowed(memory_mb=4096)
        assert relaxed.memory_mb == 512

    def test_narrowed_rejects_invalid_override(self):
        base = SandboxLimits()
        with pytest.raises(ValueError):
            base.narrowed(cpu=-1)


class TestSandboxSpec:
    def test_spec_holds_protocol_fields(self):
        limits = SandboxLimits()
        spec = SandboxSpec(
            backend="docker",
            image="python:3.12-slim",
            invocation_id="inv-1",
            session_id="sess-1",
            workspace="/tmp/ws",
            limits=limits,
            network_enabled=False,
        )
        assert spec.backend == "docker"
        assert spec.network_enabled is False
        assert spec.limits is limits


class TestResultContract:
    def test_result_defaults_are_bounded(self):
        result = SkillResult(
            invocation_id="inv-1",
            skill_name="pdf",
            status=SkillStatus.COMPLETED,
            summary="已完成",
            artifacts=(ArtifactRef(path="out/report.md", size_bytes=10),),
            audit_id="audit-1",
        )
        assert result.ok
        assert result.error_code is None
        assert result.artifacts[0].path == "out/report.md"

    def test_failure_carries_error_code(self):
        result = SkillResult(
            invocation_id="inv-1",
            skill_name="pdf",
            status=SkillStatus.UNAVAILABLE,
            error_code=SkillErrorCode.SANDBOX_UNAVAILABLE,
        )
        assert not result.ok
        assert result.error_code is SkillErrorCode.SANDBOX_UNAVAILABLE
        assert result.summary == ""


class TestInvocation:
    def test_invocation_is_frozen_budget_snapshot(self):
        invocation = SkillInvocation(
            invocation_id="inv-1",
            session_id="sess-1",
            skill_name="pdf",
            skill_version="a" * 16,
            source=SkillSource.USER,
            trust=SkillTrustLevel.MANAGED,
            allowed_actions=("run_python", "read_file"),
            total_timeout=120.0,
            max_output_chars=2000,
        )
        with pytest.raises(Exception):  # noqa: B017 - frozen dataclass 冻结校验
            invocation.total_timeout = 1.0  # type: ignore[misc]
