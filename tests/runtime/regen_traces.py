# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""一次性再生成 legacy reference traces —— 仅限 M0 初始化执行。

    python tests/runtime/regen_traces.py

此后再运行本脚本等于覆盖迁移 oracle（tests/runtime/test_legacy_reference_traces.py
的基准），违反计划「旧行为 oracle 始终保留」纪律。脚本镜像 tests/conftest.py 的
环境隔离（STELLA_HOME 临时目录 + MEMORY_V2 关闭），保证与 pytest 内重放同路径。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT))

# 必须先于任何 config/core import（与 tests/conftest.py 同理）
os.environ.setdefault("STELLA_HOME", str(Path(tempfile.mkdtemp(prefix="stella-regen-home-"))))

import core.pipeline
import memory.pre_processors
import memory.retrieval_v2

# 镜像 conftest 的 _force_v1_memory_path：捕获走 v1 prompt 分支
core.pipeline.MEMORY_V2_ENABLED = False
memory.pre_processors.MEMORY_V2_ENABLED = False
memory.retrieval_v2.MEMORY_V2_ENABLED = False

import legacy_harness as harness


def main() -> int:
    written = []
    for sc in harness._materialize():
        result = harness.run_scenario(sc)
        path = harness.freeze(result)
        written.append(str(path))
        print(f"frozen: {path}")
    print(f"\n{len(written)} traces frozen。此后禁止再生成（覆盖 oracle）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
