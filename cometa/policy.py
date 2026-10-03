# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""委派可行性判定（方案 §6.4/§6.9/§6.13）。

policy 是提交路径的**确定性**守门员：访问白名单、profile/workspace 绑定、
后端可用性全部在这里判，判不过给明确 reason_code——不静默换厂商（§6.4.4），
不把模型输出当授权依据（§1.3 不变量 4）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import CometaConfig
from .models import Origin, TaskSpec


@dataclass(slots=True)
class PolicyDecision:
    """提交/委派判定结果。ok=False 时 reason_code 给出可解释原因。"""

    ok: bool
    reason_code: str = ""
    message: str = ""
    backend_id: str = ""
    profile: str = ""
    workspace_id: str = ""
    workspace_key: str = ""


class SubmissionPolicy:
    """无状态判定器；配置经构造注入（调用方负责同一性）。"""

    def __init__(self, config: CometaConfig):
        self.config = config

    def check(self, *, origin: Origin, spec: TaskSpec) -> PolicyDecision:
        """校验一次委派提交。通过时给出解析后的 backend/profile/workspace。"""
        if not self.config.enabled:
            return PolicyDecision(ok=False, reason_code="disabled", message="cometa 未启用")
        if not spec.objective.strip():
            return PolicyDecision(
                ok=False, reason_code="empty_objective", message="任务目标不能为空"
            )
        # 访问白名单（§6.13：空列表表示未授权；WebUI 管理员走现有认证）
        if origin.platform == "qq":
            access = self.config.access
            try:
                requester = int(origin.requester_id)
            except (TypeError, ValueError):
                return PolicyDecision(
                    ok=False, reason_code="invalid_origin", message="QQ 身份不合法"
                )
            if requester not in access.qq_user_ids:
                return PolicyDecision(
                    ok=False,
                    reason_code="user_not_allowed",
                    message="该用户未获委派授权",
                )
            # 会话种类（计划 §6.8）：私聊走用户级授权，绝不匹配群白名单——
            # 既不因「私聊用户号 == 某群号」误放行，也不把私聊当未授权会话。
            kind = origin.conversation_kind or (
                "webchat" if origin.platform == "webchat" else "group"
            )
            if kind == "group":
                try:
                    conversation = int(origin.conversation_id)
                except (TypeError, ValueError):
                    return PolicyDecision(
                        ok=False, reason_code="invalid_origin", message="QQ 身份不合法"
                    )
                if conversation not in access.qq_group_ids:
                    return PolicyDecision(
                        ok=False,
                        reason_code="conversation_not_allowed",
                        message="该会话未获委派授权",
                    )
        elif origin.platform == "webchat":
            pass  # 单管理员模型：WebUI 认证即授权（§2 现有行为）
        else:
            return PolicyDecision(
                ok=False, reason_code="unsupported_platform", message="未知来源平台"
            )

        # profile：必须显式或唯一默认
        profile_name = spec.permission_profile.strip()
        if not profile_name:
            # 显式命令（QQ 委派/WebUI 表单）没有 profile 槽位：单 profile 直接
            # 用它；多 profile 则用管理员声明的 default_profile（§6.9 管理员
            # 预授权语义），两者都没有才拒绝。
            if len(self.config.profiles) == 1:
                profile_name = next(iter(self.config.profiles))
            elif self.config.default_profile:
                profile_name = self.config.default_profile
            else:
                return PolicyDecision(
                    ok=False,
                    reason_code="profile_required",
                    message="未指定权限 profile（多 profile 部署需在 toml 配 default_profile）",
                )
        profile = self.config.profile_of(profile_name)
        if profile is None:
            return PolicyDecision(
                ok=False, reason_code="profile_unknown", message=f"未知 profile {profile_name!r}"
            )

        # workspace 绑定（§6.9：用户提交 ID，模型不能指定任意 cwd）
        workspace_id = spec.workspace_id.strip() or profile.workspace
        if workspace_id and workspace_id not in self.config.workspaces:
            return PolicyDecision(
                ok=False,
                reason_code="workspace_unknown",
                message=f"工作区 {workspace_id!r} 未在配置中声明",
            )

        # 后端选择：显式点名不可用必须告知原因，不静默换（§6.4.4）
        backend_id = spec.backend_preference.strip() or profile.backend
        backend = self.config.backend_of(backend_id)
        if backend is None or not backend.enabled:
            return PolicyDecision(
                ok=False,
                reason_code="backend_unavailable",
                message=f"后端 {backend_id!r} 不可用",
                profile=profile_name,
                workspace_id=workspace_id,
            )

        workspace_key = f"ws:{workspace_id}" if workspace_id else ""
        return PolicyDecision(
            ok=True,
            backend_id=backend_id,
            profile=profile_name,
            workspace_id=workspace_id,
            workspace_key=workspace_key,
        )


__all__ = ["PolicyDecision", "SubmissionPolicy"]
