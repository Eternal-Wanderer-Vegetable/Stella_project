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


@pytest.fixture(autouse=True)
def _isolate_space_config(tmp_path, monkeypatch):
    """把共享空间的自动命名账本与 TOML 目录隔离到每个用例独立的临时目录。

    否则测试里 ChatContext.__post_init__ / consolidate_group 触发 resolve_space
    自动分配时，会往仓库真实 memory/ 下写 .space_assignments.json。每用例独立 +
    reload() 清空缓存，保证命名确定性且互不串扰。
    """
    import config.spaces as spaces

    monkeypatch.setattr(spaces, "_AUTO_FILE", tmp_path / ".space_assignments.json")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    spaces.reload()
