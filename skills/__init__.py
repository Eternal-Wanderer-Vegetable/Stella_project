# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Anthropic 风格 Skills 与受控沙盒执行（plan: docs/plans/2026-09-21-gitnexus-plan-anthropic-skills-sandbox.md）。

Skill 是「完成一类任务的说明书」：``SKILL.md`` 正文 + 可选 ``scripts/`` /
``references/``。它**不是** Capability，也**绝不**进入
``capability.registry.CapabilityRegistry`` 的 Provider 图——Skill 没有可路由的
工具实现，把它伪装成 Provider 只会污染 Router 的候选集（plan §9 首行风险）。

子系统由四个边界组成（plan §3）：

``catalog``      只做发现、解析与优先级合并（metadata-only；不读正文）。
``selector``     只消费名称/描述，输出有限候选；命中前不读正文。
``orchestrator`` 命中后延迟加载正文，组装受限 Agent 调用，压缩结果。
``sandbox``      唯一的脚本/文件操作执行边界；没有安全后端就 fail-closed。

对主链路的承诺：Skills 的任何失败都不阻断回复（与 Memory/Comes 同一
故障隔离纪律）；进 prompt 的只有有界摘要与产物引用，原始 stdout/stderr
与完整正文永远不进。
"""

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

__all__ = [
    "ArtifactRef",
    "SandboxLimits",
    "SandboxSpec",
    "SkillCandidate",
    "SkillErrorCode",
    "SkillInvocation",
    "SkillManifest",
    "SkillResult",
    "SkillSource",
    "SkillStatus",
    "SkillTrustLevel",
    "safe_relative_path",
    "skill_name_is_valid",
    "trust_for_source",
]
