# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""pytest 全局夹具。

默认把 MEMORY_V2_ENABLED 关掉（回到旧记忆系统路径），保证既有 v1 测试
（test_full_workflow / test_short_term_attribution 等）行为稳定；专门测试
记忆系统 v2 的用例（test_policy / test_retrieval_v2 等）在各自用例里显式开启。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _force_v1_memory_path(monkeypatch):
    """把涉及 v2 开关的模块内 MEMORY_V2_ENABLED 统一置为 False（每个用例自动生效）。"""
    import core.pipeline
    import memory.pre_processors
    import memory.retrieval_v2

    monkeypatch.setattr(core.pipeline, "MEMORY_V2_ENABLED", False)
    monkeypatch.setattr(memory.pre_processors, "MEMORY_V2_ENABLED", False)
    monkeypatch.setattr(memory.retrieval_v2, "MEMORY_V2_ENABLED", False)
