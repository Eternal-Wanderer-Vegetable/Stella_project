# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""skills 测试夹具：在临时目录里搭出四层技能树的工厂。

不写 ``__init__.py``（tests 子目录带包标记会在 pytest prepend 模式下遮蔽
顶层 ``skills`` 包，tests/knowledge 踩过同一个坑）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest


def write_skill(
    root: Path,
    name: str,
    *,
    description: str = "测试技能",
    body: str = "",
    front_matter: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    """在 root 下写一个最小合法的技能目录，返回 SKILL.md 路径。"""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    if front_matter is None:
        front_matter = f"name: {name}\ndescription: {description}\n"
    text = f"---\n{front_matter}---\n\n# {name}\n\n{body or f'{name} 的使用说明。'}\n"
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    for rel, content in (extra_files or {}).items():
        target = skill_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return skill_dir / "SKILL.md"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def skill_tree(tmp_path: Path) -> Callable[..., Path]:
    """可调用的技能树工厂：``skill_tree("user", "pdf", description=...)``。

    第一段是层名（builtin/plugin/user/workspace），映射到夹具目录下的
    同名子目录；调用方再把这些根目录接到被测对象上。
    """

    def _build(layer: str, name: str, **kwargs: object) -> Path:
        return write_skill(tmp_path / layer, name, **kwargs)  # type: ignore[arg-type]

    return _build
