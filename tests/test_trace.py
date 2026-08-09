# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.trace 决策追踪的单元测试。

通过 monkeypatch 把 trace.DB_PATH / MEMORY_TRACE_ENABLED / MEMORY_TRACE_TABLE
指向临时数据库与自定义表名，覆盖 record_trace 的写入、序列化、统计与大字段截断。
"""

import json
import sqlite3
from pathlib import Path

import memory.trace as trace
from memory.trace import (
    _dump_ids,
    _dump_scores,
    _parse_ids,
    memory_statistics,
    prune_traces,
    record_trace,
)


def _trace_db(tmp_path: Path, monkeypatch) -> Path:
    db_path = tmp_path / "memory.db"
    db_path.touch()
    monkeypatch.setattr(trace, "DB_PATH", db_path)
    monkeypatch.setattr(trace, "MEMORY_TRACE_ENABLED", True)
    monkeypatch.setattr(trace, "MEMORY_TRACE_TABLE", "memory_traces")
    return db_path


def test_record_trace_disabled(monkeypatch):
    monkeypatch.setattr(trace, "MEMORY_TRACE_ENABLED", False)
    record_trace(group_id=1, user_id=2, message="x")
    assert True


def test_record_trace_creates_table_and_inserts(tmp_path, monkeypatch):
    db_path = _trace_db(tmp_path, monkeypatch)
    record_trace(
        group_id="g1",
        user_id="u1",
        message="你好",
        mode="CASUAL_REPLY",
        trigger="reply",
        candidates=[{"id": 1}],
        allowed=[{"id": 1}],
        final=[{"id": 1, "_score": 0.9}],
        rejected=[{"id": 2}],
        behavior=[],
        prompt_snapshot="prompt",
        output="response",
        debug=True,
    )
    record_trace(group_id="g1", user_id="u1", message="", debug=False)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM memory_traces").fetchall()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(memory_traces)")]
    conn.close()
    assert len(rows) == 2
    row = dict(zip(cols, rows[0], strict=True))
    assert row["mode"] == "CASUAL_REPLY"
    assert json.loads(row["final_ids"]) == [1]
    assert json.loads(row["score_map"]) == {"1": 0.9}
    assert json.loads(row["rejected_ids"]) == [2]
    assert row["debug"] == 1
    assert row["message"] == "你好"


def test_record_trace_truncates_long_fields(tmp_path, monkeypatch):
    db_path = _trace_db(tmp_path, monkeypatch)
    record_trace(
        group_id="g",
        user_id="u",
        message="x" * 2000,
        prompt_snapshot="p" * 20000,
        output="o" * 5000,
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT message, prompt_snapshot, output FROM memory_traces").fetchone()
    conn.close()
    assert len(row[0]) == 500
    assert len(row[1]) == 8000
    assert len(row[2]) == 2000


def test_record_trace_no_memory_fields(tmp_path, monkeypatch):
    db_path = _trace_db(tmp_path, monkeypatch)
    record_trace(group_id=None, user_id=None, message=None)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT group_id, user_id, message, candidate_ids, score_map FROM memory_traces"
    ).fetchone()
    conn.close()
    assert row[0] == "None"
    assert row[1] == "None"
    assert row[2] == ""
    assert row[3] == "[]"
    assert row[4] == "{}"


def test_dump_and_parse_helpers():
    assert _dump_ids(None) == "[]"
    assert _dump_ids([{"id": "a"}, {"foo": 1}]) == '["a"]'
    assert _dump_scores(None) == "{}"
    assert _dump_scores([{"id": 1, "_score": 0.5}, {"id": None, "_score": 1.0}]) == '{"1": 0.5}'
    assert _parse_ids('[1, 2]') == [1, 2]
    assert _parse_ids("not json") == []
    assert _parse_ids(None) == []


def test_memory_statistics(tmp_path, monkeypatch):
    _trace_db(tmp_path, monkeypatch)
    record_trace(group_id="g", user_id="u", message="m", mode="CASUAL_REPLY",
                 final=[{"id": 1}, {"id": 2}])
    record_trace(group_id="g", user_id="u", message="m2", mode="ACTIVE_JOIN",
                 final=[{"id": 3}])
    stats = memory_statistics(days=7.0)
    assert stats["total_traces"] == 2
    assert stats["recent_traces"] == 2
    assert stats["avg_memories_per_reply"] == 1.5
    assert stats["by_mode"]["CASUAL_REPLY"] == 2.0
    assert stats["by_mode"]["ACTIVE_JOIN"] == 1.0


def test_memory_statistics_empty_and_missing_db(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(trace, "DB_PATH", missing)
    monkeypatch.setattr(trace, "MEMORY_TRACE_ENABLED", True)
    assert memory_statistics(days=1.0) == {}
    _trace_db(tmp_path, monkeypatch)
    stats = memory_statistics(days=1.0)
    assert stats["total_traces"] == 0
    assert stats["avg_memories_per_reply"] == 0.0


def test_prune_traces(tmp_path, monkeypatch):
    db_path = _trace_db(tmp_path, monkeypatch)
    record_trace(group_id="g", user_id="u", message="m")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE memory_traces SET ts = datetime('now', '-40 days')")
    conn.commit()
    conn.close()
    deleted = prune_traces(keep_days=30.0)
    assert deleted >= 1
    conn = sqlite3.connect(db_path)
    left = conn.execute("SELECT COUNT(*) FROM memory_traces").fetchone()[0]
    conn.close()
    assert left == 0


def test_prune_traces_no_db():
    assert prune_traces(keep_days=30.0) == 0


def test_statistics_on_broken_rows(tmp_path, monkeypatch):
    _trace_db(tmp_path, monkeypatch)
    record_trace(group_id="g", user_id="u", message="m", mode="", final=[])
    stats = memory_statistics(days=0.0)
    assert stats["by_mode"]["UNKNOWN"] == 0.0
