# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""生成用例（scripts/generate_benchmark_cases.py）确定性测试。

冻结 digest 断言：generated/ 产物字节级冻结——任何再生成差异（改模板/改池/改
seed）都必须有意识地更新这里的常量，防止生成产物漂移无人察觉。
"""

from __future__ import annotations

import sys
from pathlib import Path

import memory.benchmark as benchmark

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_benchmark_cases as gen

GENERATED_DIR = benchmark.MEMORY_BENCHMARK_DIR / "generated"

# 冻结集合：默认 seed 的产物 digest 与用例总数。有意变更生成器后必须同步更新。
FROZEN_SEED = gen.DEFAULT_SEED
FROZEN_DIGEST = "62e3b22bbaa96246b76f4b65f86e7c9a50a2108906a5fbee331cc2d65c98d69e"
FROZEN_CASE_COUNT = 48
# 自建用例总量目标（手写 + 生成，计划 §6 M1 ≥100）
TOTAL_CASE_TARGET = 100


def test_generator_deterministic_same_seed(tmp_path):
    """同 seed 两次生成 → 字节级一致（digest 相同）。"""
    d1, d2 = tmp_path / "a", tmp_path / "b"
    digest1 = gen.write_cases(d1, 7)
    digest2 = gen.write_cases(d2, 7)
    assert digest1 == digest2
    assert digest1 == gen.digest_dir(d1)


def test_generator_seed_sensitive(tmp_path):
    """不同 seed → 产物不同（确定性≠恒定，种子确实参与噪音轮转）。"""
    d1, d2 = tmp_path / "a", tmp_path / "b"
    digest1 = gen.write_cases(d1, 7)
    digest2 = gen.write_cases(d2, 8)
    assert digest1 != digest2


def test_frozen_generated_dir_matches():
    """仓库内 generated/ 与冻结 digest/计数一致；--check 自校验通过。"""
    assert GENERATED_DIR.exists(), "generated/ 缺失：先运行 scripts/generate_benchmark_cases.py"
    assert gen.digest_dir(GENERATED_DIR) == FROZEN_DIGEST
    cases = benchmark.load_cases(benchmark.MEMORY_BENCHMARK_DIR)
    generated = [c for c in cases if c.get("generator")]
    assert len(generated) == FROZEN_CASE_COUNT
    # 元数据契约：script/seed/template 齐全且可追溯
    assert all(c["generator"]["script"] == gen.GENERATOR_NAME for c in generated)
    assert all(c["generator"]["seed"] == FROZEN_SEED for c in generated)
    assert {c["generator"]["template"] for c in generated} <= {"recommend", "casual", "tech"}


def test_generated_cases_pass_in_main_dataset():
    """生成用例进主数据集后必须全部 ok（与手写用例同一质量门槛）。"""
    metrics = benchmark.run_benchmark(benchmark.MEMORY_BENCHMARK_DIR)
    failures = [r["id"] for r in metrics["results"]
                if not r["ok"] and r.get("category") == "generated"]
    assert failures == []
    # 自建总量目标 ≥100（计划 §6 M1）
    assert metrics["cases_total"] >= TOTAL_CASE_TARGET


def test_check_flag_detects_drift(tmp_path, capsys):
    """--check：产物被篡改后必须报非零（不静默绿）。"""
    tampered = tmp_path / "generated"
    gen.write_cases(tampered, 7)
    victim = next(tampered.rglob("*.json"))
    data = __import__("json").loads(victim.read_text(encoding="utf-8"))
    data["input"] = data["input"] + "改"
    victim.write_text(__import__("json").dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    assert gen.main(["--out", str(tampered), "--seed", "7", "--check"]) == 1
