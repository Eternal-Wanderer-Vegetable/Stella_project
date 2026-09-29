#!/usr/bin/env python3
"""Reject runtime payloads from a standalone release archive."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path, PurePosixPath

# 仅拒绝**归档顶层**的负载目录（开发机的嵌入式 runtime/、用户数据 napcat/、
# 模型 models/）。核心代码包的同名子目录（如 core/runtime/，runtime-manager
# 工作的 Python 包）是正常发布内容，绝不能按组件名误伤——v6.0.1 CI 实测：
# 未锚定的 'runtime' 会把 Standalone 归档剥成跑不起来的空壳。
FORBIDDEN_ROOT_COMPONENTS = frozenset({"runtime", "napcat", "models"})
# 负载二进制名（llama.cpp server，Linux 无扩展名 / Windows 带 .exe）无论
# 出现在哪一层都不该进 Standalone。
FORBIDDEN_COMPONENTS = frozenset({"llama-server"})


def _forbidden_component(part: str) -> bool:
    return part in FORBIDDEN_COMPONENTS or part.startswith("llama-server.")


def forbidden_members(archive: Path) -> list[str]:
    """Return archive members whose top-level component or any component is forbidden."""
    with zipfile.ZipFile(archive) as bundle:
        return [
            info.filename
            for info in bundle.infolist()
            if PurePosixPath(info.filename).parts[0] in FORBIDDEN_ROOT_COMPONENTS
            or any(_forbidden_component(part) for part in PurePosixPath(info.filename).parts)
        ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()

    matches = forbidden_members(args.archive)
    if not matches:
        return 0
    print(f"forbidden release content in {args.archive}:")
    for member in matches:
        print(f"  {member}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
