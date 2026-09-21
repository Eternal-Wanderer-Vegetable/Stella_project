# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""sandbox 测试共享小工具：构造 SandboxSpec / SandboxAction。

模块名以下划线开头且不带 ``__init__.py``（pytest prepend 模式下
带包标记的 tests 子目录会遮蔽顶层同名包，tests/knowledge 踩过坑）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from skills.model import SandboxAction, SandboxLimits, SandboxSpec


def make_spec(workspace_root: Path, **overrides: Any) -> SandboxSpec:
    """合法的基线 spec；用 kwargs 覆盖单字段构造违规样例。"""
    invocation = overrides.pop("invocation_id", "inv-1")
    session = overrides.pop("session_id", "sess-1")
    workspace = overrides.pop("workspace", workspace_root / session / invocation)
    payload: dict[str, Any] = {
        "backend": "docker",
        "image": "python:3.12-slim",
        "invocation_id": invocation,
        "session_id": session,
        "workspace": workspace,
        "limits": SandboxLimits(),
        "network_enabled": False,
    }
    payload.update(overrides)
    return SandboxSpec(**payload)


def make_action(name: str = "run_shell", **args: str) -> SandboxAction:
    return SandboxAction(action=name, args=dict(args))
