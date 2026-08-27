# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""校验构建好的发布目录：用户数据没被打进包，自带可改文件都进了清单。

release CI 在打 zip **之前**跑这一步：

    python scripts/check_release_layout.py dist/Stella

为什么需要它：``deploy/migrate.py`` 的 ``USER_DATA`` 是「什么是用户数据」的唯一定义，
但发布包的排除清单在 ``release.yml`` 里另写了一份。两份清单迟早会对不上——将来新增
一个用户数据目录却忘了加进 rsync 排除，发布包就会带着开发机的数据出门，或者在用户
升级时把他的文件覆盖掉。这一步让「对不上」在发布前就失败。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy import manifest
from deploy.migrate import NEVER_MIGRATE, SHIPPED_EDITABLE, USER_DATA


def _has_user_content(path: Path) -> bool:
    """路径里有没有「真的用户数据」。

    ``data/plugins/.gitkeep`` 这类空目录骨架是发布包刻意带的（保证目录存在），
    不算用户数据；除此以外只要有内容就算。
    """
    if path.is_file():
        return True
    if not path.is_dir():
        return False
    return any(
        child.name != ".gitkeep" and "__pycache__" not in child.as_posix()
        for child in path.rglob("*")
    )


def check(release_dir: Path) -> list[str]:
    """返回问题列表（空 = 通过）。"""
    problems: list[str] = []

    # 1) 用户数据不该被打进发布包（自带默认内容的那两个目录除外）
    for relative in USER_DATA:
        if relative in SHIPPED_EDITABLE:
            continue
        path = release_dir / relative.rstrip("/")
        if _has_user_content(path):
            problems.append(
                f"{relative} 属于用户数据（deploy/migrate.py 的 USER_DATA），"
                f"却带着内容出现在发布包里；请在 release.yml 的 rsync 排除清单里加上它"
            )

    for relative in NEVER_MIGRATE:
        if _has_user_content(release_dir / relative.rstrip("/")):
            problems.append(f"{relative} 是运行期产物，不该出现在发布包里")

    # 2) 清单必须完整且是最新的：漏一个文件，升级时就无法判断用户改没改过它
    #    （会退化为「一律保留旧文件」，用户永远拿不到新默认值）
    expected = manifest.build_manifest(release_dir)
    actual = manifest.load_manifest(release_dir)
    if not actual:
        problems.append(
            f"缺少或读不出 {manifest.MANIFEST_NAME}；"
            f"请在打包前跑 python -m deploy manifest --write"
        )
        return problems
    for key in sorted(expected.keys() - actual.keys()):
        problems.append(f"{key} 不在 {manifest.MANIFEST_NAME} 里（清单需要重新生成）")
    for key in sorted(actual.keys() - expected.keys()):
        problems.append(f"{manifest.MANIFEST_NAME} 里的 {key} 在发布包里不存在（清单已过期）")
    for key in sorted(expected.keys() & actual.keys()):
        if expected[key] != actual[key]:
            problems.append(f"{key} 的哈希与清单不一致（清单在文件改动后没有重新生成）")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法：python scripts/check_release_layout.py <发布目录>")
        return 2
    release_dir = Path(argv[1]).resolve()
    if not release_dir.is_dir():
        print(f"发布目录不存在：{release_dir}")
        return 2
    problems = check(release_dir)
    if problems:
        print("发布包布局校验未通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("✅ 发布包布局校验通过（用户数据未入包，自带可改文件已全部登记）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
