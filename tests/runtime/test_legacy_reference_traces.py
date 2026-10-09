# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Legacy reference traces 护栏（保留 M0，逐字段核对 P2 协议基线）。

每个场景在当前实现上重放，并与独立的 ``fixtures/legacy_traces/p2_protocol``
快照逐字段比对。根目录中的 M0 oracle 保持原样，P2 只吸收经审阅的协议、
预算和格式差异，避免把新输出覆盖成旧基线。

``regen_traces.py`` 仍只用于 M0 初始化；P2 oracle 需按本阶段审阅清单更新。
"""

from __future__ import annotations

import json

import legacy_harness as harness
import pytest


@pytest.mark.parametrize("sc", harness._materialize(), ids=lambda s: s.name)
def test_legacy_reference_trace_unchanged(sc):
    # JSON 往返对齐序列化语义（tuple→list），与冻结文件同构
    result = json.loads(json.dumps(harness.run_scenario(sc)))
    m0 = harness.load_frozen(sc.name, generation="m0")
    frozen = harness.load_frozen(sc.name, generation="p2_protocol")
    assert m0 is not None, f"M0 原始 oracle 缺失：{sc.name}"
    assert frozen is not None, (
        f"缺少 P2 review trace fixtures/legacy_traces/p2_protocol/{sc.name}.json；"
        "不得使用 M0 regen 脚本覆盖原始 oracle"
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
