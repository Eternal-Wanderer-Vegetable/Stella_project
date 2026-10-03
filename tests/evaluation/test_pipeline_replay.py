# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""管线回放验收（计划 §6.7.2 isolated_pipeline / §6.7.3 dataset 合同）。

覆盖：小 fixture 数据集（临时 group_messages 库 → 只读导出）→ isolated_pipeline
两次运行 semantic digest 一致；cutoff 防泄漏（cutoff 后消息绝不出现）；决策
稳定性维度真实执行双遍重算。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.evaluation.dataset import export_dataset, load_dataset
from core.evaluation.runner import ExperimentConfig, run_experiment


def _make_source_db(db_path: Path, rows: list[tuple[str, str, str, str, int, str]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT,
                    user_id TEXT,
                    content TEXT,
                    source_kind TEXT DEFAULT 'PASSIVE',
                    msg_id INTEGER,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for group_id, user_id, content, kind, msg_id, ts in rows:
                conn.execute(
                    "INSERT INTO group_messages (group_id, user_id, content, source_kind, msg_id, timestamp)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (group_id, user_id, content, kind, msg_id, ts),
                )
    finally:
        conn.close()


def _chat_rows() -> list[tuple[str, str, str, str, int, str]]:
    """一个 8 条消息的小群：4 分钟自然聊天，从第 4 条起可评分（热身=3）。"""
    texts = [
        "今天天气真不错啊",
        "是啊，准备出门跑步",
        "晚上有什么安排吗",
        "想去看新上映的电影",
        "那部评分好像不错",
        "一起呗，正好顺路",
        "行，看完吃宵夜",
        "老地方那家？我记得味道可以",
    ]
    return [
        ("4201", f"user_{i % 3}", text, "PASSIVE", 2000 + i, f"2026-01-01 10:{i:02d}:30")
        for i, text in enumerate(texts)
    ]


def _export_default(tmp_path: Path, *, cutoff: datetime | None = None):
    db = tmp_path / "src.db"
    _make_source_db(db, _chat_rows())
    manifest = export_dataset(db, tmp_path / "ds", cutoff_utc=cutoff)
    return manifest, tmp_path / "ds"


def test_isolated_pipeline_twice_same_semantic_digest(tmp_path: Path):
    _manifest, dataset_dir = _export_default(tmp_path)

    report_a = run_experiment(
        ExperimentConfig(
            mode="isolated_pipeline", dataset_dir=dataset_dir, workdir=tmp_path / "w_a", seed=7
        )
    )
    report_b = run_experiment(
        ExperimentConfig(
            mode="isolated_pipeline", dataset_dir=dataset_dir, workdir=tmp_path / "w_b", seed=7
        )
    )

    assert report_a.status == "completed"
    assert report_b.status == "completed"
    # 同 fixtures 两次运行：语义摘要一致（忽略时间戳/UUID/路径/耗时）
    assert report_a.semantic_digest() == report_b.semantic_digest()
    # 两次都是零真实发送（回执只有 simulated_ack 形态）
    assert report_a.send_calls == report_b.send_calls
    assert all(s.send_result in (None, "simulated_ack") for s in report_a.samples)
    # 决策稳定性维度真实跑过双遍重算且通过
    dims = {d.name: d for d in report_a.stability.dimensions}
    assert dims["decision_stability"].status.value == "PASS"
    assert dims["isolation"].status.value == "PASS"
    assert dims["pipeline_execution"].status.value == "PASS"
    # worker 报告落盘在各自 workdir 沙箱
    assert (tmp_path / "w_a" / "artifacts" / "report.json").is_file()
    assert (tmp_path / "w_b" / "artifacts" / "report.json").is_file()


def test_cutoff_prevents_leakage(tmp_path: Path):
    cutoff = datetime(2026, 1, 1, 10, 3, 30, tzinfo=timezone.utc)
    manifest, dataset_dir = _export_default(tmp_path, cutoff=cutoff)

    # 导出侧：cutoff 之后的消息绝不出现
    _m, messages = load_dataset(dataset_dir)
    assert messages
    assert all(m.ts_utc <= cutoff for m in messages)
    assert manifest["dropped_after_cutoff"] == 4
    assert manifest["exported"] == 4

    # 报告侧：泄漏样本不存在于任何样本 id
    report = run_experiment(
        ExperimentConfig(mode="trace_playback", dataset_dir=dataset_dir, workdir=tmp_path / "w")
    )
    sample_ids = {s.event_id for s in report.samples}
    _manifest_full, full_dir = _export_default(tmp_path / "full", cutoff=None)
    _mf, full_messages = load_dataset(full_dir)
    leaked = {m.event_id for m in full_messages if m.ts_utc > cutoff} - sample_ids
    assert len(leaked) == 4  # 全部 4 条 cutoff 后消息都未进报告


def test_source_order_and_ids_survive_roundtrip(tmp_path: Path):
    _manifest, dataset_dir = _export_default(tmp_path)
    _m, messages = load_dataset(dataset_dir)
    assert [m.sequence for m in messages] == list(range(1, 9))
    assert [m.msg_id for m in messages] == [2000 + i for i in range(8)]  # 源 id 映射保持
    assert {m.group_id for m in messages} == {"4201"}
    assert all(m.scope == "group" for m in messages)
    # event_id 稳定：同输入重导出得到同一批 id
    db = tmp_path / "src2.db"
    _make_source_db(db, _chat_rows())
    export_dataset(db, tmp_path / "ds2")
    _m2, messages2 = load_dataset(tmp_path / "ds2")
    assert [m.event_id for m in messages] == [m.event_id for m in messages2]
