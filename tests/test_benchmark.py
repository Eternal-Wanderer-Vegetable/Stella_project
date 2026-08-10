# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""memory.benchmark 运行器测试：确认能跑通内置测试集且指标合理。"""

import memory.benchmark as benchmark
from config import MEMORY_BENCHMARK_DIR


def test_benchmark_loads_cases():
    """benchmark 目录下的用例应全部能被加载。"""
    cases = benchmark.load_cases()
    assert len(cases) >= 6
    assert all(("expected_memory" in c) or ("expected_behavior_memory" in c) for c in cases)


def test_benchmark_run_metrics_within_targets():
    """数据集应有区分能力：排序用例（合法候选超过 mode_limit）应让 precision 落回 100% 以下。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    assert metrics["cases_total"] >= 8
    assert 0.0 <= metrics["memory_precision"] < 100.0
    assert 0.0 <= metrics["memory_recall"] <= 100.0
    # 安全属性不可妥协：禁止记忆绝不能进入会话
    assert metrics["forbidden_activation_rate"] == 0.0


def test_benchmark_ok_flag_reflects_expected():
    """每个用例的 ok 标志：期望记忆全命中、期望行为约束被 Behavior Guard 命中且未泄漏、
    无禁止激活、超召回未超过容忍上限（max_retrieved 或期望数 × 2）。"""
    for r in benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)["results"]:
        assert isinstance(r["over_recall"], bool)
        assert r["ok"] == (
            r["found_expected"] == sorted(r["expected"])
            and r["found_behavior"] == sorted(r["expected_behavior"])
            and not r["behavior_leaked"]
            and not r["activated_forbidden"]
            and not r["over_recall"]
        )


def test_benchmark_rank_recommend_001_is_ok():
    """评价里的关键目标：rank-recommend-001 的 CONTEXTUAL 记忆（usage 强命中）不再被
    词面相似度二次否决，M01/M02/M03 全部进入会话。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    target = next(r for r in metrics["results"] if r["id"] == "rank-recommend-001")
    assert target["final"] == ["M01", "M02", "M03"] or set(target["expected"]) <= set(target["final"])
    assert target["found_expected"] == ["M01", "M02", "M03"]


def test_benchmark_verbose_scores_present():
    """evaluate_case 应暴露每条进会话记忆的 _score，供 --verbose 观察分数分布。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    for r in metrics["results"]:
        assert set(r["scores"].keys()) <= set(r["final"])
