# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills 测试的共享小工具（skills_helpers）（模块名以下划线开头，不会遮蔽任何顶层包）。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def make_manifest(
    skill_dir: Path,
    *,
    source: Any = None,
    description: str = "测试技能",
) -> Any:
    """按磁盘上的真实 SKILL.md 构造 manifest（懒 import 避免夹具环）。"""
    from skills.model import SkillManifest, SkillSource

    data = (skill_dir / "SKILL.md").read_bytes()
    return SkillManifest(
        name=skill_dir.name,
        description=description,
        source=source or SkillSource.USER,
        root=skill_dir,
        body_size=len(data),
        content_digest=hashlib.sha256(data).hexdigest(),
    )
