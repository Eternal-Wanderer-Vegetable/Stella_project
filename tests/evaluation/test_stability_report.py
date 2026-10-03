# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""稳定性报告验收（计划 §6.7.4）。

覆盖：0 样本绝不 PASS（必须 INSUFFICIENT_SAMPLES/SKIPPED）；dropped 带原因；
故障 case 能定位到样本 id；semantic digest 忽略非语义字段且对语义变化敏感；
端到端空数据集走 trace_playback 也遵守 0 样本铁律。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.evaluation.dataset import export_dataset
from core.evaluation.report import (
    DimensionStatus,
    ExperimentReport,
    SampleRecord,
    StabilityReport,
)
from core.evaluation.runner import ExperimentConfig, run_experiment


def _sample(event_id: str, sequence: int, **kw) -> SampleRecord:
    return SampleRecord(event_id=event_id, sequence=sequence, group_id="4201", **kw)


# ── 0 样本铁律 ───────────────────────────────────────────


def test_zero_samples_never_pass():
    report = StabilityReport.build([])
    assert report.total == 0 and report.valid == 0 and report.coverage == 0.0
    report.add_dimension("pipeline_execution", DimensionStatus.PASS, "全部执行")
    report.add_dimension("snapshot_coverage", DimensionStatus.SKIPPED, "未提供 snapshot")
    report.finalize()
    statuses = {d.name: d.status for d in report.dimensions}
    # PASS 必须降级为 INSUFFICIENT_SAMPLES；SKIPPED 保持原样
    assert statuses["pipeline_execution"] is DimensionStatus.INSUFFICIENT_SAMPLES
    assert statuses["snapshot_coverage"] is DimensionStatus.SKIPPED
    assert all(d.status is not DimensionStatus.PASS for d in report.dimensions)


def test_empty_dataset_via_trace_playback_never_pass(tmp_path: Path):
    """端到端：空源库 → 空数据集 → trace_playback → 无任何 PASS。"""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(db)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT, user_id TEXT, content TEXT,
                    source_kind TEXT DEFAULT 'PASSIVE', msg_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
    finally:
        conn.close()
    export_dataset(db, tmp_path / "ds")

    report = run_experiment(
        ExperimentConfig(mode="trace_playback", dataset_dir=tmp_path / "ds", workdir=tmp_path / "w")
    )
    assert report.stability.valid == 0 and report.stability.total == 0
    assert report.stability.dimensions, "维度必须已登记"
    assert all(d.status is not DimensionStatus.PASS for d in report.stability.dimensions)


# ── dropped 带原因 ───────────────────────────────────────


def test_dropped_samples_carry_reason_and_coverage():
    samples = [
        _sample("evtA", 1, status="ok", decision_level="OBSERVE", score=51.5),
        _sample("evtB", 2, status="dropped", drop_reason="observe_error:ValueError"),
        _sample("evtC", 3, status="dropped", drop_reason="budget_exceeded"),
    ]
    report = StabilityReport.build(samples)
    assert report.valid == 1 and report.total == 3
    assert report.coverage == round(1 / 3, 6)
    assert report.dropped == [
        {"event_id": "evtB", "reason": "observe_error:ValueError"},
        {"event_id": "evtC", "reason": "budget_exceeded"},
    ]
    report.add_dimension("pipeline_execution", DimensionStatus.INCOMPLETE, "预算截断")
    report.finalize()  # valid=1 → 不触发 0 样本降级
    assert report.dimensions[0].status is DimensionStatus.INCOMPLETE


# ── 故障 case 定位到样本 id ──────────────────────────────


def test_fail_dimension_locates_sample_ids():
    samples = [
        _sample("evtA", 1, status="ok", decision_level="OBSERVE", score=51.5),
        _sample("evtB", 2, status="ok", decision_level="CANDIDATE", score=71.25),
        _sample("evtC", 3, status="ok", decision_level="IGNORE", score=10.0),
    ]
    report = StabilityReport.build(samples)
    report.add_dimension(
        "decision_stability", DimensionStatus.FAIL, "第二遍重算与第一遍不一致",
        sample_ids=["evtB"],
    )
    report.finalize()
    dimension = report.to_dict()["dimensions"][0]
    assert dimension["name"] == "decision_stability"
    assert dimension["status"] == "FAIL"
    assert dimension["sample_ids"] == ["evtB"]  # 从报告直达故障样本


# ── semantic digest ──────────────────────────────────────


def _base_report() -> ExperimentReport:
    report = ExperimentReport(
        run_id="run-aaa",
        mode="isolated_pipeline",
        status="completed",
        seed=7,
        dataset_digest="dataset-digest-1",
        model_calls=1,
        send_calls=1,
        workdir="/tmp/w_a",
        samples=[
            _sample("evtA", 1, status="ok", decision_level="OBSERVE", score=51.5),
            _sample("evtB", 2, status="ok", decision_level="ALLOW_LLM", score=88.0, send_result="simulated_ack"),
        ],
    )
    report.stability = StabilityReport.build(report.samples)
    report.stability.add_dimension("pipeline_execution", DimensionStatus.PASS, "全部执行")
    report.stability.add_dimension("decision_stability", DimensionStatus.PASS, "一致")
    return report


def test_semantic_digest_ignores_volatile_fields():
    report_a = _base_report()
    report_a.started_utc = "2026-01-01T00:00:00+00:00"
    report_a.finished_utc = "2026-01-01T00:00:03+00:00"
    report_a.duration_ms = 3000

    report_b = _base_report()
    # 非语义字段全部不同：run_id / workdir / 时间戳 / 耗时
    report_b.run_id = "run-bbb"
    report_b.workdir = "/tmp/w_b"
    report_b.started_utc = "2026-02-02T12:34:56+00:00"
    report_b.finished_utc = "2026-02-02T12:35:10+00:00"
    report_b.duration_ms = 14000

    assert report_a.semantic_digest() == report_b.semantic_digest()


def test_semantic_digest_detects_semantic_changes():
    baseline = _base_report()

    # 单条样本决策变化 → digest 必须变（同一 score 精度内不变）
    changed_decision = _base_report()
    changed_decision.samples[0].decision_level = "CANDIDATE"
    assert baseline.semantic_digest() != changed_decision.semantic_digest()

    # 新增丢弃样本 → digest 必须变
    added_drop = _base_report()
    added_drop.samples.append(
        _sample("evtC", 3, status="dropped", drop_reason="not_executed:worker_terminated")
    )
    added_drop.stability = StabilityReport.build(added_drop.samples)
    assert baseline.semantic_digest() != added_drop.semantic_digest()

    # 维度结论变化 → digest 必须变
    changed_dimension = _base_report()
    changed_dimension.stability.dimensions[0].status = DimensionStatus.FAIL
    assert baseline.semantic_digest() != changed_dimension.semantic_digest()
