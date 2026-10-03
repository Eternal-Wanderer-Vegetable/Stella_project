# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""隔离性验收（计划 §6.7.4「隔离」维度 + §6.7.2 fake adapter 合同）。

覆盖：
- ExperimentPaths 路径逃逸拒绝（``..`` 上跳 / 绝对路径越界 / 伪造实例重校验）；
- FakeSender 只记录不触网、恒返回 ``simulated_ack``；FixtureModel 脚本次序；
- export_dataset 只读：生产库 mtime/内容 hash 逐字节不变、无 WAL/journal 残留；
- 两个实验并发互不污染（各自 workdir 沙箱、报告各含各的样本、digest 与顺序
  单跑一致）。
"""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import threading
from pathlib import Path

import pytest

from core.evaluation.adapters import (
    ExperimentPaths,
    FakeSender,
    FixtureEmbedder,
    FixtureExhaustedError,
    FixtureModel,
    PathEscapeError,
    resolve_under,
)
from core.evaluation.dataset import export_dataset, load_dataset
from core.evaluation.runner import ExperimentConfig, run_experiment


def _make_source_db(db_path: Path, rows: list[tuple[str, str, str, str, int, str]]) -> None:
    """构造一个与生产 ``group_messages`` 同构的临时源库（只用于导出测试）。"""
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


def _rows_for(prefix: str, group: str, count: int) -> list[tuple[str, str, str, str, int, str]]:
    return [
        (
            group,
            f"user_{prefix}{i}",
            f"{prefix} 第{i}条：今晚一起看新番吗？",
            "PASSIVE",
            1000 + i,
            f"2026-01-01 10:{i:02d}:00",
        )
        for i in range(count)
    ]


# ── 路径沙箱 ─────────────────────────────────────────────


def test_experiment_paths_rejects_path_escape(tmp_path: Path):
    root = tmp_path / "exp"
    paths = ExperimentPaths.create(root)
    assert paths.db.is_dir() and paths.cache.is_dir() and paths.logs.is_dir() and paths.artifacts.is_dir()
    for value in (paths.db, paths.cache, paths.logs, paths.artifacts):
        assert value.resolve().relative_to(paths.root)  # 全部状态路径在 root 下

    # 相对路径 ``..`` 上跳 → 拒绝
    with pytest.raises(PathEscapeError):
        paths.child("../outside")
    # 越界绝对路径 → 拒绝
    outside = (tmp_path / "outside").resolve()
    with pytest.raises(PathEscapeError):
        resolve_under(paths.root, outside)
    # 从磁盘读回的伪造实例 → validate 重新拦截
    forged = ExperimentPaths(
        root=paths.root, db=outside, cache=paths.cache, logs=paths.logs, artifacts=paths.artifacts
    )
    with pytest.raises(PathEscapeError):
        forged.validate()


# ── fake adapters ────────────────────────────────────────


def test_fake_sender_only_records_and_returns_simulated_ack():
    sender = FakeSender()
    assert sender.send_one("你好", 0) == "simulated_ack"
    assert sender.send_one("第二条", 1) == "simulated_ack"
    assert asyncio.run(sender.asend_one("第三条", 2)) == "simulated_ack"
    # 只追加记录：line/i/序号逐条可查，没有任何网络/发送副作用出口
    assert [s["line"] for s in sender.sent] == ["你好", "第二条", "第三条"]
    assert [s["i"] for s in sender.sent] == [0, 1, 2]
    assert [s["seq"] for s in sender.sent] == [0, 1, 2]
    assert sender.sends_made == 3


def test_fixture_model_follows_script_order_and_refuses_overflow():
    model = FixtureModel(["回复一", "回复二"])
    assert model.generate("prompt-a") == "回复一"
    assert model.generate("prompt-b") == "回复二"
    assert model.calls_made == 2
    with pytest.raises(FixtureExhaustedError):
        model.generate("prompt-c")  # 脚本耗尽必须显式暴露，绝不静默循环


def test_fixture_embedder_miss_returns_zero_vector():
    embedder = FixtureEmbedder({"今晚看新番": [1.0, 0.0], "明天再说": [0.0, 1.0]})
    assert embedder.dimension == 2
    assert embedder.embed("今晚看新番") == [1.0, 0.0]
    assert embedder.lookups == 1 and embedder.hits == 1
    assert embedder.embed("没见过的话") == [0.0, 0.0]  # miss → 零向量（离线、不报错）
    assert embedder.hits == 1 and embedder.lookups == 2


# ── 生产库只读 ───────────────────────────────────────────


def test_export_dataset_leaves_production_db_untouched(tmp_path: Path):
    db = tmp_path / "prod.db"
    _make_source_db(db, _rows_for("a", "1001", 5))
    before_hash = hashlib.sha256(db.read_bytes()).hexdigest()
    before_mtime = db.stat().st_mtime_ns

    export_dataset(db, tmp_path / "ds")

    # mtime 与内容 hash 逐字节不变；连 WAL/journal 残留都不允许出现
    assert db.stat().st_mtime_ns == before_mtime
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before_hash
    assert not (tmp_path / "prod.db-wal").exists()
    assert not (tmp_path / "prod.db-journal").exists()

    _manifest, messages = load_dataset(tmp_path / "ds")
    assert len(messages) == 5
    assert all(m.user != f"user_a{i}" for i, m in enumerate(messages))  # 伪名化
    assert all(m.user.startswith("u") for m in messages)
    assert [m.msg_id for m in messages] == [1000, 1001, 1002, 1003, 1004]  # 源序保持
    assert all(m.ts_utc.tzinfo is not None for m in messages)


def test_export_dataset_rejects_missing_db_without_production_fallback(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        export_dataset(tmp_path / "不存在的库.db", tmp_path / "ds")


# ── 并发实验互不污染 ─────────────────────────────────────


def _run_decision_recompute(dataset_dir: Path, workdir: Path) -> str:
    report = run_experiment(
        ExperimentConfig(mode="decision_recompute", dataset_dir=dataset_dir, workdir=workdir)
    )
    assert report.status == "completed"
    return report.semantic_digest()


def test_two_concurrent_experiments_do_not_pollute(tmp_path: Path):
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    _make_source_db(db_a, _rows_for("alpha", "1001", 6))
    _make_source_db(db_b, _rows_for("beta", "2002", 6))
    export_dataset(db_a, tmp_path / "ds_a")
    export_dataset(db_b, tmp_path / "ds_b")
    _manifest_a, messages_a = load_dataset(tmp_path / "ds_a")
    _manifest_b, messages_b = load_dataset(tmp_path / "ds_b")
    ids_a = {m.event_id for m in messages_a}
    ids_b = {m.event_id for m in messages_b}
    assert ids_a.isdisjoint(ids_b)

    # 顺序基线
    digest_a = _run_decision_recompute(tmp_path / "ds_a", tmp_path / "w_a")
    digest_b = _run_decision_recompute(tmp_path / "ds_b", tmp_path / "w_b")
    assert digest_a != digest_b  # 不同数据集 → 不同语义摘要

    # 并发执行（in-process 双实验，各自 workdir 沙箱）
    results: dict[str, str] = {}

    def worker(key: str, dataset_dir: Path, workdir: Path) -> None:
        results[key] = _run_decision_recompute(dataset_dir, workdir)

    threads = [
        threading.Thread(target=worker, args=("a", tmp_path / "ds_a", tmp_path / "c_a")),
        threading.Thread(target=worker, args=("b", tmp_path / "ds_b", tmp_path / "c_b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert results["a"] == digest_a  # 并发结果与单跑一致：互不污染
    assert results["b"] == digest_b


def test_experiment_never_writes_outside_workdir(tmp_path: Path):
    db = tmp_path / "src.db"
    _make_source_db(db, _rows_for("gamma", "3003", 6))
    export_dataset(db, tmp_path / "ds")
    before = sorted(p.name for p in tmp_path.iterdir())
    run_experiment(
        ExperimentConfig(mode="trace_playback", dataset_dir=tmp_path / "ds", workdir=tmp_path / "w")
    )
    # 实验只在 workdir 下落状态；源库/数据集目录原样保留
    after = sorted(p.name for p in tmp_path.iterdir())
    assert set(before) <= set(after)
    assert (tmp_path / "w" / "artifacts" / "report.json").is_file()
    assert (tmp_path / "src.db").read_bytes() == db.read_bytes()
