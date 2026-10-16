# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""memory.benchmark 运行器测试：确认能跑通内置测试集且指标合理。"""

import base64
import hashlib
import json
from pathlib import Path

import pytest

import memory.benchmark as benchmark
from config import MEMORY_BENCHMARK_DIR

np = pytest.importorskip("numpy", reason="embedding fixture 的向量计算依赖 numpy（见 requirements-dev.txt）")


def _synthetic_fixture():
    """确定性合成 fixture：结构保持向量，验证 embedding 路径 plumbing 不破坏红线。

    与查询「语义相关」的记忆（expected/expected_behavior）取与查询向量同向
    （cos=1，模拟真实 embedding 的相关信号）；其余（噪音/禁止）取正交方向
    （cos=0，不额外抬分）。这样 embedding 路径的排序相对 rule-only 保序，
    forbidden_activation_rate==0 红线在两种路径下都必须成立。
    """
    cases = benchmark.load_cases(MEMORY_BENCHMARK_DIR)
    texts: dict[str, list[float]] = {}

    def unit(idx: int) -> list[float]:
        vec = [0.0] * 16
        vec[idx % 16] = 1.0
        return vec

    for c in cases:
        query = (c.get("input") or "").strip()
        if not query:
            continue
        qv = unit(0)
        texts[query] = qv
        relevant = set(c.get("expected_memory") or []) | set(c.get("expected_behavior_memory") or [])
        for mid, m in (c.get("memories") or {}).items():
            content = (m.get("content") or "").strip()
            if not content or content in texts:
                continue
            texts[content] = qv if mid in relevant else unit(
                int(hashlib.sha256(mid.encode("utf-8")).hexdigest(), 16) % 15 + 1)
    data = {
        benchmark._text_digest(t): base64.b64encode(np.asarray(v, dtype=np.float32).astype(np.float16).tobytes()).decode()
        for t, v in texts.items()
    }
    return {"model": "synthetic", "dim": 16, "dtype": "float16", "normalized": True, "keys": sorted(data), "data": data}


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


def test_benchmark_results_expose_ranked_all_and_separation():
    """诊断增强：每个用例应暴露全部进入排序的候选（含截断标记）与正/噪音分离间隔。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    assert "separation_margin" in metrics
    for r in metrics["results"]:
        assert isinstance(r["ranked_all"], dict)
        assert all({"id", "score", "cut"} <= set(item) for item in r["ranked_all"].values())


def test_benchmark_ok_flag_reflects_expected():
    """每个用例的 ok 标志：期望记忆全命中、期望行为约束被 Behavior Guard 命中且未泄漏、
    无禁止激活、超召回未超过容忍上限、无跨空间泄漏、血缘期望无缺口。"""
    for r in benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)["results"]:
        assert isinstance(r["over_recall"], bool)
        assert r["ok"] == (
            r["found_expected"] == sorted(r["expected"])
            and r["found_behavior"] == sorted(r["expected_behavior"])
            and not r["behavior_leaked"]
            and not r["activated_forbidden"]
            and not r["over_recall"]
            and not r["cross_scope_leak"]
            and not r["lineage_missing"]
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


def test_benchmark_embedding_fixture_path():
    """--embedding-fixture 路径：合成 fixture 能跑通，且禁止激活仍为 0（红线不变）。"""
    fixture = _synthetic_fixture()
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR, embedding_fixture=fixture, retrieval_mode="embedding")
    assert metrics["forbidden_activation_rate"] == 0.0
    # synthetic 随机向量语义≈0，行为应接近 rule-only（不崩溃、指标在合理范围）
    assert 0.0 <= metrics["memory_precision"] <= 100.0
    assert isinstance(metrics["separation_margin"], (float, type(None)))


# ── M0 报告契约 ──────────────────────────────────────────────


def test_load_cases_excludes_underscore_prefixed_directories(tmp_path):
    """排除规则泛化：任何 `_` 前缀路径段都不是用例（_public/_replay 等同理）。"""
    (tmp_path / "rank").mkdir()
    (tmp_path / "_fixtures").mkdir()
    (tmp_path / "_public").mkdir()
    _case = {"id": "c1", "input": "q", "expected_memory": []}
    (tmp_path / "rank" / "a.json").write_text(json.dumps(_case), encoding="utf-8")
    (tmp_path / "_fixtures" / "b.json").write_text(json.dumps(_case | {"id": "c2"}), encoding="utf-8")
    (tmp_path / "_public" / "c.json").write_text(json.dumps([_case | {"id": "c3"}]), encoding="utf-8")

    cases = benchmark.load_cases(tmp_path)
    assert [c["id"] for c in cases] == ["c1"]
    assert cases[0]["_source_path"] == "rank/a.json"


def test_run_fingerprint_stable_and_input_sensitive(tmp_path):
    """同输入同指纹；数据集或检索模式变化必须改变指纹。"""
    (tmp_path / "cat").mkdir()
    case = {"id": "c1", "input": "q", "expected_memory": [], "memories": {}}
    (tmp_path / "cat" / "a.json").write_text(json.dumps(case), encoding="utf-8")
    cases = benchmark.load_cases(tmp_path)
    f1, comp1 = benchmark.build_run_fingerprint(tmp_path, cases, backend="python", retrieval_mode="rule")
    f2, _ = benchmark.build_run_fingerprint(tmp_path, cases, backend="python", retrieval_mode="rule")
    assert f1 == f2
    f3, _ = benchmark.build_run_fingerprint(tmp_path, cases, backend="python", retrieval_mode="fts")
    assert f3 != f1
    # 数据集内容变化 → 摘要变化
    (tmp_path / "cat" / "a.json").write_text(json.dumps(case | {"input": "q2"}), encoding="utf-8")
    cases2 = benchmark.load_cases(tmp_path)
    f4, comp4 = benchmark.build_run_fingerprint(tmp_path, cases2, backend="python", retrieval_mode="rule")
    assert f4 != f1
    assert comp1["dataset_sha256"] != comp4["dataset_sha256"]


def test_category_metrics_split_by_directory():
    """分类聚合：目录 = 数据集根下第一级路径段，指标口径与全局一致。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    cats = metrics["category_metrics"]
    assert set(cats)  # 既有数据集已按目录分好类
    assert sum(c["cases_total"] for c in cats.values()) == metrics["cases_total"]
    assert sum(c["cases_ok"] for c in cats.values()) == metrics["cases_ok"]
    for r in metrics["results"]:
        assert r["category"] in cats


def test_report_document_contract(tmp_path):
    """报告契约 v1：schema/fingerprint/指标定义版本/分类聚合齐备，逐例带 category。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    doc = benchmark.build_report_document(MEMORY_BENCHMARK_DIR, metrics)
    assert doc["schema"] == benchmark.REPORT_SCHEMA
    assert doc["metric_definitions_version"] == benchmark.METRIC_DEFINITIONS_VERSION
    assert set(doc["fingerprint_components"]) == {
        "code_version", "source_digest", "dataset_sha256", "backend",
        "retrieval_mode", "clock_anchor", "metric_definitions_version",
    }
    assert doc["metrics"]["cases_total"] == metrics["cases_total"]
    manifest = benchmark.write_evidence_manifest(tmp_path)
    assert manifest.exists()


def test_baseline_compare_drift_detection(tmp_path):
    """基线对比正反例：同数值通过；指标漂移与硬零违规必须失败；新指标不算漂移。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    metrics_no_dims = {k: v for k, v in metrics.items() if k != "dimensions"}
    baseline_doc = benchmark.build_baseline_document(metrics_no_dims)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline_doc), encoding="utf-8")

    ok, drift = benchmark.compare_baseline(metrics, baseline_path)
    assert ok and all(row["ok"] for row in drift)

    drifted = dict(metrics)
    drifted["memory_recall"] = metrics["memory_recall"] - 1.0
    ok2, drift2 = benchmark.compare_baseline(drifted, baseline_path)
    assert not ok2
    assert any(row["status"] == "drift" and row["metric"] == "memory_recall" for row in drift2)

    hard = dict(metrics)
    hard["forbidden_activation_rate"] = 12.5
    ok3, _ = benchmark.compare_baseline(hard, baseline_path)
    assert not ok3  # 硬零指标不容差

    with_new_metric = {k: v for k, v in metrics.items() if k != "dimensions"}
    with_new_metric["dimensions"] = {"temporal": {"temporal_accuracy": 100.0}}
    ok4, drift4 = benchmark.compare_baseline(with_new_metric, baseline_path)
    assert ok4  # 新指标缺席基线 → 标记 new，不算漂移
    assert any(row["status"] == "new" for row in drift4)

    missing = {k: v for k, v in metrics.items() if k != "mode_accuracy"}
    ok5, drift5 = benchmark.compare_baseline(missing, baseline_path)
    assert not ok5
    assert any(row["status"] == "missing" and row["metric"] == "mode_accuracy" for row in drift5)



# ── M2 检索模式矩阵（Python 侧）──────────────────────────────


def test_evaluate_case_mode_validation(tmp_path):
    """模式校验：embedding 无语义分 / rule 带语义分 / 未知模式都必须报错。"""
    case = {"id": "m", "input": "q", "memories": {}, "expected_memory": []}
    with pytest.raises(ValueError, match="embedding fixture"):
        benchmark.evaluate_case(case, tmp_path, 0, None, "embedding")
    with pytest.raises(ValueError, match="不接受语义分"):
        benchmark.evaluate_case(case, tmp_path, 0, {"x": 0.5}, "rule")
    with pytest.raises(ValueError, match="未知检索模式"):
        benchmark.evaluate_case(case, tmp_path, 0, None, "bm25")


def test_fts_mode_populates_index_and_accounts(tmp_path):
    """fts 模式：用例库填充 FTS 索引；run_benchmark 记录 FTS 调用计量。"""
    case = {
        "id": "fts-x",
        "scenario": {"group_id": 40, "user_id": 40},
        "input": "有什么游戏推荐吗",
        "mode": "RECOMMEND",
        "memories": {
            "M1": {"content": "用户喜欢的游戏是塞尔达传说", "type": "PREFERENCE",
                   "usage_tags": ["RECOMMEND"], "visibility": "OPEN"},
        },
        "expected_memory": ["M1"],
    }
    result = benchmark.evaluate_case(case, tmp_path, 0, None, "fts")
    assert result["final"] == ["M1"]  # FTS 路径（或回退）仍能召回期望

    import sqlite3 as _sq
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        db = Path(td) / "c.db"
        benchmark._write_case_db(db, case, populate_fts=True)
        conn = _sq.connect(db)
        rows = conn.execute("SELECT mem_id FROM memories_fts").fetchall()
        conn.close()
        assert ("M1",) in rows

    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR, retrieval_mode="fts")
    assert set(metrics["retrieval_path"]) == {"queries", "candidate_rows"}
    assert metrics["retrieval_path"]["queries"] >= len(metrics["results"])
    metrics_rule = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR, retrieval_mode="rule")
    assert metrics_rule["retrieval_path"]["queries"] == 0


def test_embedding_mode_skips_uncovered_cases_explicitly():
    """fixture 覆盖缺口：embedding 模式显式 skip 未覆盖用例并记账（不静默绿）。"""
    fixture = _synthetic_fixture()  # 覆盖全部用例
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR, embedding_fixture=fixture,
                                      retrieval_mode="embedding")
    assert metrics["fixture_coverage"]["skipped"] == 0
    assert metrics["fixture_coverage"]["covered"] == metrics["cases_total"]

    # 按 id 精确构造 partial fixture：只保留 casual_001 一例的向量
    keep = next(c for c in benchmark.load_cases(MEMORY_BENCHMARK_DIR) if c["id"] == "casual_001")
    keep_digests = {benchmark._text_digest(keep.get("input") or "")} | {
        benchmark._text_digest(m.get("content") or "") for m in keep["memories"].values()
    }
    partial = {"model": "partial", "dim": 16, "dtype": "float16", "normalized": True,
               "keys": [], "data": {k: v for k, v in fixture["data"].items() if k in keep_digests}}
    metrics2 = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR, embedding_fixture=partial,
                                       retrieval_mode="embedding")
    assert metrics2["fixture_coverage"]["skipped"] > 0
    assert metrics2["cases_total"] == metrics2["fixture_coverage"]["covered"] == 1
    assert metrics2["results"][0]["id"] == "casual_001"
    assert benchmark.HARD_ZERO_METRICS  # 硬零门禁常量在位
    assert metrics2["forbidden_activation_rate"] == 0.0


def test_cost_metrics_present_and_not_gated():
    """cost 段：延迟分位数/库尺寸在位；不进基线对比标量（机器相关不门禁）。"""
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    cost = metrics["cost"]
    assert cost["retrieval_latency_ms"]["samples"] == metrics["cases_total"]
    assert cost["retrieval_latency_ms"]["p50"] is not None
    assert cost["db_bytes_total"] > 0
    assert cost["embedding_service"] is None  # 未探测必须诚实记 null
    scalars = benchmark.comparable_scalars(metrics)
    assert not any(k.startswith("cost") for k in scalars)


# ── M6 基线逐指标容差门禁 ────────────────────────────────────

FROZEN_BASELINE = MEMORY_BENCHMARK_DIR / "_fixtures" / "baselines" / "2026-10-16.json"


def test_baseline_gate_per_metric_zero_tolerance():
    """基线门禁（M6，替换旧粗阈值断言）：冻结基线逐指标零容差对比。

    数据集/打分任何漂移都会在此变红；有意变更必须重生成基线并过审。
    硬零指标（forbidden/cross_scope）不容差。基线如实记录既有失败
    （rank-casual-001），门禁盯的是「不再恶化」。
    """
    assert FROZEN_BASELINE.exists(), "冻结基线缺失"
    metrics = benchmark.run_benchmark(MEMORY_BENCHMARK_DIR)
    all_ok, drift = benchmark.compare_baseline(metrics, FROZEN_BASELINE)
    bad = [row for row in drift if not row["ok"]]
    assert all_ok, f"基线漂移: {[(r['metric'], r['baseline'], r['current']) for r in bad]}"
    # 硬零双门禁在基线对比之外再显式断言一次（防基线本身被改坏）
    assert metrics["forbidden_activation_rate"] == 0.0
    assert metrics["dimensions"]["scope_privacy"]["cross_scope_leak_rate"] == 0.0
