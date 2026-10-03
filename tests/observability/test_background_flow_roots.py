# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""后台运行根探针（计划 §6.5 M4）：social worker / knowledge ingest。

合同：有工作才有 root（空转不刷屏）；逐作业/逐导入事实可查；观测异常
绝不影响业务结果。
"""

from __future__ import annotations

import sqlite3

import pytest

from core.observability import entity_history, message_flow, turn_trace


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


class TestSocialWorkerRoot:
    def test_no_jobs_creates_no_root(self, flow_db):
        from memory import social_worker

        # 先写一笔让 schema 初始化（无作业时 social worker 不产生任何行）
        warm = message_flow.begin_trace(root_kind="webchat", trace_id="warm-sw")
        message_flow.end_trace(warm)
        message_flow.flush()
        stats = social_worker.run_due_jobs()
        message_flow.flush()
        assert stats["claimed"] == 0
        conn = sqlite3.connect(flow_db)
        rows = conn.execute(
            "SELECT COUNT(*) FROM message_traces WHERE root_kind='social_worker'"
        ).fetchone()[0]
        conn.close()
        assert rows == 0

    def test_job_lifecycle_records_root_and_outcome(self, flow_db, monkeypatch):
        from memory import social_worker

        calls: list[str] = []

        def fake_handler(payload):
            calls.append(payload.get("k", ""))
            return True

        assert social_worker.enqueue_job(
            "resolve_effect", dedupe_key="d1", payload_refs={"k": "v"})
        monkeypatch.setitem(social_worker._HANDLERS, "resolve_effect",
                            fake_handler)
        stats = social_worker.run_due_jobs()
        message_flow.flush()
        assert stats["claimed"] == 1 and stats["done"] == 1
        conn = sqlite3.connect(flow_db)
        outcomes = conn.execute(
            "SELECT status, reason_code FROM flow_events WHERE trace_id IN "
            "(SELECT trace_id FROM message_traces WHERE root_kind='social_worker') "
            "AND kind='decision' AND fact_kind='state'").fetchall()
        roots = conn.execute(
            "SELECT status, outcome FROM message_traces "
            "WHERE root_kind='social_worker'").fetchone()
        conn.close()
        assert calls == ["v"]
        assert outcomes == [("done", "done")]
        assert roots[0] == "closed" and "done=1" in roots[1]
        hist = entity_history.for_trace(roots_trace_id(flow_db))
        assert hist and hist[-1]["entity_type"] == "social_job"
        assert hist[-1]["to_state"] == "done"

    def test_no_handler_marks_dead(self, flow_db, monkeypatch):
        from memory import social_worker

        assert social_worker.enqueue_job("nonexistent_type_xyz",
                                         dedupe_key="d2")
        stats = social_worker.run_due_jobs()
        message_flow.flush()
        assert stats["dead"] == 1
        hist = entity_history.for_trace(roots_trace_id(flow_db))
        assert hist and hist[-1]["to_state"] == "dead"


def roots_trace_id(db) -> str:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT trace_id FROM message_traces WHERE root_kind='social_worker' "
            "ORDER BY started_utc DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()


class TestKnowledgeIngestRoot:
    def test_parse_failure_records_failed_root(self, flow_db, tmp_path):
        """解析失败 → failed root + 实体履历缺省（版本未建立）。"""
        from knowledge import ingest
        from knowledge.parsers import ParseError

        class _Store:
            def create_job(self, *a, **kw):
                pass

            def finish_job(self, job_id, doc_id=None, version_no=None,
                           error=None):
                self.error = error

        class _KB:
            id = "kb1"

        store = _Store()

        def boom(*a, **kw):
            raise ParseError("bad bytes")


        orig = ingest._parse
        ingest._parse = boom  # 直接替换（模块函数,monkeypatch 等价）
        try:
            outcome = ingest.ingest_content(store, _KB(), "txt", b"\x00",
                                            title="t")
        finally:
            ingest._parse = orig
        message_flow.flush()
        assert outcome.state == "failed"
        conn = sqlite3.connect(flow_db)
        rows = conn.execute(
            "SELECT status, outcome, process_kind FROM message_traces "
            "WHERE root_kind='knowledge_ingest'").fetchall()
        decisions = conn.execute(
            "SELECT status, reason_code FROM flow_events WHERE trace_id IN "
            "(SELECT trace_id FROM message_traces WHERE "
            "root_kind='knowledge_ingest') AND fact_kind='state'").fetchall()
        conn.close()
        assert rows and rows[0][0] == "closed" and rows[0][1] == "failed"
        assert rows[0][2] == "knowledge"
        assert decisions == [("failed", "parse_error")]

    def test_probe_failure_never_breaks_ingest(self, flow_db, monkeypatch):
        """观测层自身抛错：导入结果不受影响（旁路纪律）。"""
        from knowledge import ingest

        class _Store:
            def create_job(self, *a, **kw):
                pass

            def finish_job(self, job_id, doc_id=None, version_no=None,
                           error=None):
                pass

        class _KB:
            id = "kb1"

        monkeypatch.setattr(
            message_flow, "begin_trace",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("probe down")))
        monkeypatch.setattr(ingest, "_parse", lambda *a, **kw: None)
        monkeypatch.setattr(
            ingest, "_build_version",
            lambda *a, **kw: ingest.ImportOutcome(
                state="ready", doc_id="d1", version_no=1))
        outcome = ingest.ingest_content(_Store(), _KB(), "txt", "x", title="t")
        assert outcome.state == "ready"
        message_flow.flush()
