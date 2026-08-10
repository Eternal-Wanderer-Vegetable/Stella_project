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
    assert all("expected_memory" in c for c in cases)


def test_benchmark_run_metrics_within_targets():
    """核心指标应达标：Precision ≥ 80%、Forbidden Activation ≈ 0%。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    assert metrics["cases_total"] >= 6
    assert metrics["memory_precision"] >= 80.0
    assert metrics["forbidden_activation_rate"] == 0.0
    assert metrics["cases_ok_rate"] >= 80.0


def test_benchmark_ok_flag_reflects_expected():
    """每个用例的 ok 标志：期望记忆全被找到且无禁止记忆激活。"""
    for r in benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)["results"]:
        assert r["ok"] == (r["found_expected"] == sorted(r["expected"]) and not r["activated_forbidden"])
