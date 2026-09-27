# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Legacy reference traces 冻结护栏（M0 建立的迁移 oracle）。

每个冻结场景在**当前实现**上重放，并与 ``fixtures/legacy_traces/<场景>.json``
逐字段比对。任何改动 Pipeline 业务语义的提交都必须让这些 trace 保持不变；
差异即破坏兼容基线（docs/migration/cortico/baseline-report.md §4）。

再生成只允许发生在 M0（``python tests/runtime/regen_traces.py``）；
此后任何「重新生成让测试变绿」的操作都等于覆盖旧 oracle，禁止。
"""

from __future__ import annotations

import json

import legacy_harness as harness
import pytest


@pytest.mark.parametrize("sc", harness._materialize(), ids=lambda s: s.name)
def test_legacy_reference_trace_unchanged(sc):
    # JSON 往返对齐序列化语义（tuple→list），与冻结文件同构
    result = json.loads(json.dumps(harness.run_scenario(sc)))
    frozen = harness.load_frozen(sc.name)
    assert frozen is not None, (
        f"缺少冻结 trace fixtures/legacy_traces/{sc.name}.json；"
        "仅 M0 允许执行 tests/runtime/regen_traces.py 初始化"
    )
    assert result == frozen, (
        f"场景 {sc.name} 的可观察行为偏离冻结基线。"
        "迁移实现必须复现 legacy 行为；若差异确属预期，按计划走 oracle 修订流程，"
        "不得直接再生成。差异：\n"
        + json.dumps(_diff(frozen, result), ensure_ascii=False, indent=2)
    )


def _diff(old: dict, new: dict, path: str = "") -> dict:
    if isinstance(old, dict) and isinstance(new, dict):
        out = {}
        for key in sorted(set(old) | set(new)):
            sub_path = f"{path}.{key}" if path else key
            if key not in old:
                out[sub_path] = {"<frozen>": None, "<actual>": new[key]}
            elif key not in new:
                out[sub_path] = {"<frozen>": old[key], "<actual>": None}
            else:
                nested = _diff(old[key], new[key], sub_path)
                if nested:
                    out.update(nested)
        return out
    if old != new:
        return {path or "<root>": {"<frozen>": old, "<actual>": new}}
    return {}
