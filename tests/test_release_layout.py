# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""发布包布局与用户数据清单的闭环校验。

``deploy/migrate.py`` 的 ``USER_DATA`` 是「什么是用户数据」的唯一定义，但发布包的
排除清单在 ``release.yml`` 里另写了一份，``.gitignore`` 里还有第三份。三份迟早对不上，
而对不上的后果是：发布包带着开发机的数据出门，或者升级时把用户的文件覆盖掉。

这里在**单元测试**层面就把闭环钉住（CI 的 release 阶段还会对真实产物再查一遍，
见 ``scripts/check_release_layout.py``）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from config import PROJECT_ROOT
from deploy.migrate import NEVER_MIGRATE, SHIPPED_EDITABLE, USER_DATA

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _release_excludes() -> set[str]:
    """release.yml 里 rsync 的 --exclude 值。"""
    text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    excludes = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--exclude "):
            excludes.add(stripped.removeprefix("--exclude ").strip().strip("'\"").rstrip("\\").strip())
    return excludes


def _gitignore_entries() -> set[str]:
    """.gitignore 里「被忽略」的路径，规范化为不带前后斜杠的形式。

    ``!`` 开头是**取消**忽略（如 ``!/data/plugins/.gitkeep``），不算被忽略；
    ``/data/plugins/*`` 这种带尾部通配的按目录本身算。
    """
    text = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    entries = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        line = line.lstrip("/")
        line = line.removesuffix("/*")
        entries.add(line.rstrip("/"))
    return entries


def test_every_user_data_path_is_kept_out_of_the_release():
    """USER_DATA 的每一项都必须被 rsync 排除或被 .gitignore 挡住。

    自带默认内容的两个目录（人格、能力配置）例外——它们**应当**随包发布，
    靠 .stella-manifest.json 判断用户改没改过。
    """
    excludes = _release_excludes()
    ignored = _gitignore_entries()
    uncovered = []
    for relative in USER_DATA:
        if relative in SHIPPED_EDITABLE:
            continue
        name = relative.rstrip("/")
        covered = (
            name in excludes
            or name in ignored
            or Path(name).name in excludes
            or Path(name).name in ignored
            # 目录被整体排除时，其下文件自然也被排除
            or any(name.startswith(f"{entry}/") for entry in excludes | ignored if entry)
            # *.db 这类通配
            or (name.endswith(".db") and "*.db" in excludes)
        )
        if not covered:
            uncovered.append(relative)
    assert not uncovered, (
        f"这些用户数据既没被 release.yml 排除、也不在 .gitignore 里：{uncovered}。"
        f"它们会被打进发布包，升级时覆盖用户的数据。"
    )


def test_never_migrate_paths_are_excluded_from_release():
    """日志与缓存也不该进发布包。"""
    excludes = _release_excludes()
    ignored = _gitignore_entries()
    for relative in NEVER_MIGRATE:
        name = relative.rstrip("/").lstrip(".")
        assert any(
            name in candidate or candidate in relative.rstrip("/")
            for candidate in excludes | ignored
        ), f"{relative} 应当被 release.yml 或 .gitignore 排除"
