# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""M1 可信观测合同（计划 §6.1/§8.2）：per-run 完整性、脱敏、spec 归档、
迁移、心跳与对象履历。

O03 正确合同：producer 结束 ≠ persisted complete——writer 提交确认后落
``integrity`` 终值；写失败按 **per-run** 账本归账，不串线到并发 run。
O07：summary/metrics 双重脱敏（键清洗 + 秘密形状打码），异常以稳定
``error_code`` 记录。O08：首次 root 引用前归档不可变 spec。
"""

from __future__ import annotations

import queue
import sqlite3

import pytest

from core.observability import entity_history, message_flow, turn_trace
from core.observability.message_flow import sanitize_text


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


def _trace_row(db: sqlite3.PathLike, trace_id: str) -> tuple:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT status, complete, loss, integrity, lost_events, "
            "producer_ended, persisted_events FROM message_traces "
            "WHERE trace_id=?", (trace_id,)).fetchone()
    finally:
        conn.close()


class TestPerRunIntegrity:
    def test_normal_end_finalizes_producer_ended_and_integrity(self, flow_db):
        """O03：正常结束 → writer 提交确认后 producer_ended=1、integrity=complete。"""
        root = message_flow.begin_trace(root_kind="webchat", trace_id="pi-ok")
        with message_flow.span(root, "web.session_lock"):
            pass
        message_flow.end_trace(root, outcome="delivered")
        message_flow.flush()
        status, complete, loss, integrity, lost, producer_ended, persisted = (
            _trace_row(flow_db, "pi-ok"))
        assert (status, complete, loss) == ("closed", 1, 0)
        assert producer_ended == 1
        assert integrity == "complete"
        assert lost == 0
        assert persisted > 0

    def test_leaked_spans_produce_partial_integrity(self, flow_db):
        """未闭合 span → producer 自报不完整，writer 终值 partial。"""
        root = message_flow.begin_trace(root_kind="webchat", trace_id="pi-leak")
        message_flow.span(root, "web.session_lock")  # 故意不 with
        message_flow.end_trace(root)
        message_flow.flush()
        row = _trace_row(flow_db, "pi-leak")
        assert row[1] == 0 and row[3] == "partial"

    def test_late_writer_failure_corrects_only_its_run(self, flow_db, monkeypatch):
        """O03 核心：writer 晚失败只纠正**本 run**完整性，不污染并发 run。

        失败注入在 trace_end 行：trace 行与事件已持久化，异步失败把已结束
        run 的完整性纠正为 partial（producer_ended 永不虚报）。
        """
        original_insert = message_flow._Writer._insert

        def selective_fail(self, conn, table, v):
            trace_id = message_flow._row_trace_id((table, v))
            if trace_id == "pi-late" and table == "trace_end":
                raise RuntimeError("simulated disk failure")
            return original_insert(self, conn, table, v)

        other = message_flow.begin_trace(root_kind="webchat", trace_id="pi-other")
        with message_flow.span(other, "web.session_lock"):
            pass
        message_flow.end_trace(other, outcome="delivered")
        bad = message_flow.begin_trace(root_kind="webchat", trace_id="pi-late")
        with message_flow.span(bad, "chat.group_lock"):
            pass
        # 先让 trace 行与事件落库（真实场景：晚失败发生在后续批次）
        message_flow.flush()
        monkeypatch.setattr(message_flow._Writer, "_insert", selective_fail)
        message_flow.end_trace(bad, outcome="delivered")
        message_flow.flush()
        monkeypatch.undo()
        message_flow.flush()
        # 失败 run：损失账本归账 + 完整性纠正为 partial（trace 行已被纠正）
        lost_row = _trace_row(flow_db, "pi-late")
        assert lost_row is not None
        assert lost_row[2] == 1 and lost_row[1] == 0
        assert lost_row[3] == "partial" and lost_row[4] > 0
        ledger = _rows(flow_db, "SELECT lost FROM flow_run_loss WHERE trace_id='pi-late'")
        assert ledger and ledger[0][0] > 0
        # 并发 run 不受污染
        ok_row = _trace_row(flow_db, "pi-other")
        assert ok_row[1] == 1 and ok_row[3] == "complete" and ok_row[4] == 0

    def test_queue_full_loss_attributed_per_run(self):
        """队列拒绝按 trace 归账（pending loss），不串线。"""
        w = message_flow._Writer()
        w._ensure_thread = lambda: None  # 不起线程：纯队列满行为
        w._q = queue.Queue(maxsize=1)
        # 占满队列（t-a 的一条，直接 put 绕过计数）
        w._q.put((("event", ("e0", "t-a", "", "", "n", "", 0, "start", "running",
                             "", "2026-01-01T00:00:00.000", None, "", "{}", 1,
                             0, "", "")), None))
        # t-b 三条全部被拒
        for i in range(3):
            w.submit(("event", (f"e{i}", "t-b", "", "", "n", "", i, "start",
                                "running", "", "2026-01-01T00:00:00.000", None,
                                "", "{}", 1, 0, "", "")))
        # t-a 第二条被拒
        w.submit(("event", ("e9", "t-a", "", "", "n", "", 1, "finish", "succeeded",
                            "", "2026-01-01T00:00:00.000", None, "", "{}", 1,
                            0, "", "")))
        pending = w.pending_loss()
        assert pending.get("t-b") == 3
        assert pending.get("t-a") == 1

    def test_storage_unavailable_records_loss_not_raise(self, flow_db, monkeypatch):
        """存储整体不可用 → 批次按 per-run 归账，submit/flush 绝不上抛。"""
        def dead_connect():
            return None

        monkeypatch.setattr(message_flow, "_connect", dead_connect)
        root = message_flow.begin_trace(root_kind="webchat", trace_id="pi-dead")
        root2 = message_flow.begin_trace(root_kind="webchat", trace_id="pi-dead2")
        with message_flow.span(root, "web.session_lock"):
            pass
        message_flow.end_trace(root)
        message_flow.end_trace(root2)
        message_flow.flush()  # 不抛
        pending = message_flow._writer.pending_loss()
        assert pending.get("pi-dead", 0) > 0 and pending.get("pi-dead2", 0) > 0
        monkeypatch.undo()


class TestSanitization:
    def test_bearer_and_token_shapes_redacted(self, flow_db):
        """O07：Authorization/Bearer/token 形状在 summary/metrics 一律打码。"""
        root = message_flow.begin_trace(root_kind="webchat", trace_id="san-1")
        message_flow.decision(
            root, "gate.test", status="blocked",
            summary="调用失败: Authorization: Bearer sk-secret123 token=abc",
            metrics={"Authorization": "Bearer sk-xyz",
                     "nested": {"api_key": "kkk", "note": "正常内容保留"}})
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        row = conn.execute(
            "SELECT summary, metrics FROM flow_events WHERE trace_id='san-1' "
            "AND kind='decision'").fetchone()
        conn.close()
        blob = f"{row[0]}|{row[1]}"
        assert "sk-secret123" not in blob
        assert "token=abc" not in blob
        assert "<redacted>" in blob
        assert "sk-xyz" not in blob and "kkk" not in blob
        assert "正常内容保留" in blob

    def test_exception_records_stable_error_code_not_secrets(self, flow_db):
        """异常 span：error_code=类名；summary 脱敏后不含秘密形状。"""
        root = message_flow.begin_trace(root_kind="webchat", trace_id="san-2")
        with pytest.raises(ValueError), message_flow.span(root, "gate.test"):
            raise ValueError("boom Authorization: Bearer sk-leaky")
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        row = conn.execute(
            "SELECT status, reason_code, error_code, summary FROM flow_events "
            "WHERE trace_id='san-2' AND kind='finish'").fetchone()
        conn.close()
        assert row[0] == "failed"
        assert row[1] == "ValueError"
        assert row[2] == "ValueError"
        assert "sk-leaky" not in row[3] and "<redacted>" in row[3]

    def test_sanitize_text_direct(self):
        assert sanitize_text("Bearer abc123") == "<redacted>"
        assert sanitize_text("api_key: xyz, ok") == "<redacted>, ok"
        assert sanitize_text("普通中文不受影响") == "普通中文不受影响"


class TestSpecArchive:
    def test_spec_archived_on_first_root_reference(self, flow_db):
        """O08：begin_trace 归档当前拓扑 spec（幂等、可读）。"""
        root = message_flow.begin_trace(root_kind="webchat", trace_id="sp-1")
        message_flow.end_trace(root)
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        rows = conn.execute(
            "SELECT topology_version, spec_json FROM flow_specs "
            "WHERE topology_version=?",
            (root.topology_version,)).fetchall()
        conn.close()
        assert rows, "spec 必须在 root 引用前归档"
        import json

        spec = json.loads(rows[0][1])
        assert spec.get("topology_version") == root.topology_version
        assert spec.get("nodes"), "归档 spec 必须携带节点目录"

    def test_trace_row_carries_process_identity(self, flow_db):
        root = message_flow.begin_trace(
            root_kind="webchat", trace_id="sp-2", origin="message",
            trigger="webchat", business_ts="2026-10-03T10:00:00+08:00")
        message_flow.end_trace(root)
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        row = conn.execute(
            "SELECT process_kind, origin, trigger, business_ts, "
            "last_heartbeat_utc FROM message_traces WHERE trace_id='sp-2'"
        ).fetchone()
        conn.close()
        assert row[0] == "webchat"
        assert row[1] == "message" and row[2] == "webchat"
        assert row[3] == "2026-10-03T10:00:00+08:00"
        assert row[4]  # 初始心跳 = started


class TestHeartbeat:
    def test_heartbeat_tick_touches_running_runs(self, flow_db):
        root = message_flow.begin_trace(root_kind="webchat", trace_id="hb-1")
        message_flow.flush()
        # 伪造成旧心跳，再强制 tick → 恢复新鲜
        conn = sqlite3.connect(flow_db)
        conn.execute("UPDATE message_traces SET last_heartbeat_utc='2020-01-01' "
                     "WHERE trace_id='hb-1'")
        conn.commit()
        conn.close()
        message_flow._writer._heartbeat_tick(force=True)
        after = _trace_hb(flow_db, "hb-1")
        assert after != "2020-01-01"
        message_flow.end_trace(root)
        message_flow.flush()

    def test_heartbeat_skips_ended_runs(self, flow_db):
        root = message_flow.begin_trace(root_kind="webchat", trace_id="hb-2")
        message_flow.end_trace(root)
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        conn.execute("UPDATE message_traces SET last_heartbeat_utc='2020-01-01' "
                     "WHERE trace_id='hb-2'")
        conn.commit()
        conn.close()
        message_flow._writer._heartbeat_tick(force=True)
        assert _trace_hb(flow_db, "hb-2") == "2020-01-01"


def _trace_hb(db, trace_id: str) -> str:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT last_heartbeat_utc FROM message_traces WHERE trace_id=?",
            (trace_id,)).fetchone()[0]
    finally:
        conn.close()


class TestSchemaMigration:
    def test_v1_database_migrates_additively(self, tmp_path):
        """旧 schema 1 库 → 打开即补列；legacy 行可读、running 判 interrupted。"""
        db = tmp_path / "turn_trace.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE message_traces (trace_id TEXT PRIMARY KEY, "
            "root_kind TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT '', "
            "scope TEXT NOT NULL DEFAULT '', source_message_key TEXT NOT NULL "
            "DEFAULT '', topology_version TEXT NOT NULL DEFAULT '', "
            "process_instance_id TEXT NOT NULL DEFAULT '', started_utc TEXT NOT NULL, "
            "ended_utc TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL DEFAULT '', "
            "status TEXT NOT NULL DEFAULT 'running', complete INTEGER NOT NULL "
            "DEFAULT 0, loss INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '{}')")
        conn.execute(
            "INSERT INTO message_traces (trace_id, root_kind, started_utc, status) "
            "VALUES ('legacy-1', 'qq_chat', '2026-09-01T00:00:00.000', 'running')")
        conn.commit()
        conn.close()
        turn_trace.configure(db)
        try:
            root = message_flow.begin_trace(root_kind="webchat", trace_id="mig-1")
            message_flow.end_trace(root)
            message_flow.flush()
            row = _trace_row(db, "mig-1")
            assert row[3] == "complete"  # integrity 列已存在并落账
            # legacy running 行（旧化身、无心跳）→ reader 判 interrupted
            from webui.services import flow as flow_service

            items = flow_service.messages()
            legacy = next(i for i in items["items"] if i["trace_id"] == "legacy-1")
            assert legacy["status"] == "interrupted"
        finally:
            message_flow.flush()
            turn_trace.configure(None)


class TestEntityHistory:
    def test_record_and_history_roundtrip(self, flow_db):
        root = message_flow.begin_trace(root_kind="memory_consolidate",
                                        trace_id="eh-1")
        eid = entity_history.record(
            "memory_candidate", "cand-1", scope="shared", trace_id="eh-1",
            from_state="NEW", to_state="OBSERVING", version="policy:1",
            changed_fields={"occurrence": 2})
        message_flow.flush()
        assert eid
        hist = entity_history.history("memory_candidate", "cand-1")
        assert len(hist) == 1
        assert hist[0]["from_state"] == "NEW"
        assert hist[0]["to_state"] == "OBSERVING"
        assert hist[0]["trace_id"] == "eh-1"
        assert hist[0]["changed_fields"] == {"occurrence": 2}
        latest = entity_history.latest_state("memory_candidate", "cand-1")
        assert latest["to_state"] == "OBSERVING"
        by_run = entity_history.for_trace("eh-1")
        assert [e["entity_id"] for e in by_run] == ["cand-1"]
        message_flow.end_trace(root)
        message_flow.flush()

    def test_record_never_raises_and_requires_identity(self, flow_db):
        assert entity_history.record("", "x") == ""
        assert entity_history.record("t", "") == ""
        assert entity_history.history("t", "missing") == []


def _rows(db, sql):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()
