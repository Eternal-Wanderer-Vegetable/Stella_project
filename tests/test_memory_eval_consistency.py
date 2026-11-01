# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""MBENCH-003 P0-5：评测一致性测试——数据 pin、类别映射、指标口径漂移即报错。

数据依赖 ``memory/benchmark/_public/locomo/adapted``（gitignored）：目录缺失时
跳过；存在时任何漂移（数据集版本、题目数、类别分布、映射表）都必须显式失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memory_eval.metrics import evidence_metrics
from memory_eval.scenarios import (
    INDEX_SCHEMA,
    SCENARIO_SCHEMA,
    load_index,
    load_scenarios,
)

# ── 固定契约（改动这里 = 有意识地换数据集/协议，必须有记录）──────────
PINNED_DATASET_REVISION = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
# locomo10.json @ PINNED_DATASET_REVISION 的 sha256（fetch_locomo.py manifest 同值）
PINNED_SOURCE_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
PINNED_TOTAL_QA = 1986
PINNED_SCENARIOS = 10
# 类别编号→名称（已对照 snap-research/locomo task_eval/evaluation.py 与
# 数据内容核实；编号语义错位是 MBENCH-002 的已修复事故，见报告勘误）
PINNED_CATEGORY_NAMES = {
    1: "multi_hop",
    2: "temporal_reasoning",
    3: "open_domain_knowledge",
    4: "single_hop",
    5: "adversarial",
}
PINNED_CATEGORY_COUNTS = {  # 全量 1,986 题的类别分布
    "multi_hop": 282,
    "temporal_reasoning": 321,
    "open_domain_knowledge": 96,
    "single_hop": 841,
    "adversarial": 446,
}
PINNED_PROTOCOLS = {
    "scenario": "memory-eval-locomo-scenario/1",
    "index": "memory-eval-locomo-index/1",
}

ADAPTED_DIR = Path("memory/benchmark/_public/locomo/adapted")


def test_category_mapping_frozen():
    """类别映射回归：编号语义错位是已发生的事故（MBENCH-002），必须钉死。"""
    import scripts.adapt_locomo as adapter

    assert adapter.CATEGORY_NAMES == PINNED_CATEGORY_NAMES
    assert adapter.ADAPTER_VERSION == "locomo-adapter/2"


def test_protocol_versions_frozen():

    assert PINNED_PROTOCOLS["scenario"] == SCENARIO_SCHEMA
    assert PINNED_PROTOCOLS["index"] == INDEX_SCHEMA


def test_evidence_metrics_exact():
    """gold ID 精确指标：any/all@K、MRR、完整覆盖的固定口径。"""
    gold = {"gold-D1:3", "gold-D18:21"}
    m = evidence_metrics(
        ["gold-D18:21", "m2", "m3", "gold-D1:3", "m5"], gold, ks=(1, 3, 5, 10)
    )
    assert m["any@K"] == {"@1": True, "@3": True, "@5": True, "@10": True}
    assert m["all@K"] == {"@1": False, "@3": False, "@5": True, "@10": True}
    assert m["mrr"] == 1.0
    assert m["evidence_completeness"] == 1.0
    assert m["best_rank"] == 1

    m2 = evidence_metrics(["m1", "m2", "gold-D1:3"], gold, ks=(1, 3, 5))
    assert m2["any@K"] == {"@1": False, "@3": True, "@5": True}
    assert m2["all@K"]["@5"] is False  # 只覆盖 1/2 证据
    assert m2["evidence_completeness"] == 0.5
    assert m2["mrr"] == round(1 / 3, 4)

    assert evidence_metrics(["m1"], set()) == {}  # adversarial 无 gold


def test_evidence_metrics_requires_ordered_ids():
    """MRR 依赖排序次序：乱序输入会给出错误排名——契约上 retrieved_ids 必须有序。"""
    gold = {"gold-A"}
    ordered = evidence_metrics(["m1", "gold-A"], gold, ks=(1, 2))
    assert ordered["best_rank"] == 2 and ordered["mrr"] == 0.5


@pytest.mark.skipif(
    not ADAPTED_DIR.exists(), reason="adapted 数据不存在（gitignored，先跑 fetch/adapt）"
)
def test_adapted_dataset_contract():
    """适配产物的冻结契约：版本、场景数、题目数、类别分布、源 revision。"""
    index = load_index(ADAPTED_DIR)
    assert index["schema"] == PINNED_PROTOCOLS["index"]
    assert index["source"]["sha256"] == PINNED_SOURCE_SHA256, (
        f"数据源 sha256 漂移：{index['source'].get('sha256')} ≠ pin")
    assert len(index["scenarios"]) == PINNED_SCENARIOS

    scenarios = load_scenarios(ADAPTED_DIR)
    assert len(scenarios) == PINNED_SCENARIOS
    counts: dict[str, int] = {}
    total = 0
    for scenario in scenarios:
        assert scenario["schema"] == PINNED_PROTOCOLS["scenario"]
        for qa in scenario["qa"]:
            counts[qa["category_name"]] = counts.get(qa["category_name"], 0) + 1
            total += 1
    assert total == PINNED_TOTAL_QA, f"题目总数漂移：{total} ≠ {PINNED_TOTAL_QA}"
    assert counts == PINNED_CATEGORY_COUNTS, f"类别分布漂移：{counts}"
