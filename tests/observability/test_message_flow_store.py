# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""消息流程存储与目录（core/observability.message_flow / flow_catalog）测试。

计划 §8.1：存储侧覆盖 writer 批事务、有界队列 known loss、完整性计算、
敏感键清洗、prune；目录侧覆盖 ID/边/入口引用一致性与钩子映射。
测试注入独立临时 trace 库（与 turn_trace 同库路径约定），绝不触碰
STELLA_HOME 的真实诊断库。
"""

from __future__ import annotations

import sqlite3

import pytest

from core.observability import flow_catalog, message_flow, turn_trace


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


def _rows(db, sql: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


class TestSpanLifecycle:
    def test_span_start_finish_pairs_and_projection(self, flow_db):
        ctx = message_flow.begin_trace(
            root_kind="webchat", platform="webchat", scope="webchat",
            trace_id="r-1", source_message_key="web:1")
        with message_flow.span(ctx, "web.session_lock") as sp:
            assert sp.node_id == "web.session_lock"
        with message_flow.span(ctx, "web.output", parent=sp):
            pass
        message_flow.end_trace(ctx, outcome="delivered")
        message_flow.flush()

        events = _rows(flow_db, "SELECT kind, node_id, status FROM flow_events "
                                "WHERE trace_id='r-1' ORDER BY id")
        kinds = [(k, n, s) for k, n, s in events]
        # root start + 2 spans (start+finish each) + trace_end；
        # root span 的节点身份 = 目录入口节点（webchat → web.auth_input）
        assert kinds[0] == ("start", "web.auth_input", "running")
        assert ("start", "web.session_lock", "running") in kinds
        assert ("finish", "web.session_lock", "succeeded") in kinds
        assert kinds[-1] == ("trace_end", "web.auth_input", "closed")

        spans = _rows(flow_db, "SELECT span_id, node_id, parent_span_id, status, "
                               "duration_ms FROM flow_spans WHERE trace_id='r-1'")
        by_node = {r[1]: r for r in spans}
        assert by_node["web.session_lock"][2] == "root"
        assert by_node["web.output"][2] == by_node["web.session_lock"][0]
        assert by_node["web.output"][3] == "succeeded"
        assert by_node["web.output"][3] is not None

        trace = _rows(flow_db, "SELECT status, outcome, complete FROM message_traces "
                               "WHERE trace_id='r-1'")[0]
        assert trace == ("closed", "delivered", 1)

    def test_exception_marks_failed_and_reraises(self, flow_db):
        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="r-2")
        with pytest.raises(ValueError), message_flow.span(ctx, "chat.context"):
            raise ValueError("boom")
        with message_flow.span(ctx, "chat.group_lock"):
            pass
        message_flow.end_trace(ctx, outcome="failed")
        message_flow.flush()
        finish = _rows(flow_db, "SELECT status, reason_code FROM flow_events "
                                "WHERE trace_id='r-2' AND kind='finish' "
                                "AND node_id='chat.context'")[0]
        assert finish == ("failed", "ValueError")
        # 失败 span 不影响后续 span 与 trace 关闭
        trace = _rows(flow_db, "SELECT complete FROM message_traces "
                               "WHERE trace_id='r-2'")[0][0]
        assert trace == 1

    def test_cancelled_span_status(self, flow_db):
        import asyncio

        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="r-3")
        with pytest.raises(asyncio.CancelledError),                 message_flow.span(ctx, "turn.generate"):
            raise asyncio.CancelledError
        message_flow.end_trace(ctx, outcome="cancelled")
        message_flow.flush()
        status = _rows(flow_db, "SELECT status FROM flow_events "
                                "WHERE trace_id='r-3' AND kind='finish'")[0][0]
        assert status == "cancelled"

    def test_leaked_span_marked_unknown_and_partial(self, flow_db):
        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="r-4")
        # 开 span 但不用 with 关闭：模拟异常路径漏配对（spans 未闭合）
        message_flow.span(ctx, "chat.group_lock")
        message_flow.end_trace(ctx, outcome="closed")
        message_flow.flush()
        leaked = _rows(flow_db, "SELECT status, reason_code, ended_utc != '' "
                                "FROM flow_spans WHERE trace_id='r-4' "
                                "AND node_id='chat.group_lock'")[0]
        assert leaked == ("unknown", "span_not_closed", 1)
        complete = _rows(flow_db, "SELECT complete FROM message_traces "
                                  "WHERE trace_id='r-4'")[0][0]
        assert complete == 0

    def test_end_trace_is_idempotent(self, flow_db):
        ctx = message_flow.begin_trace(root_kind="webchat", trace_id="r-5")
        message_flow.end_trace(ctx, outcome="a")
        message_flow.end_trace(ctx, outcome="b")
        message_flow.flush()
        count = _rows(flow_db, "SELECT COUNT(*) FROM flow_events "
                               "WHERE trace_id='r-5' AND kind='trace_end'")[0][0]
        assert count == 1


class TestDecisionsAndLinks:
    def test_decision_and_checkpoint(self, flow_db):
        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="r-6")
        message_flow.decision(ctx, "chat.daily_budget", status="blocked",
                              reason_code="pause_all",
                              metrics={"role": "chat"})
        message_flow.checkpoint(ctx, "chat.consolidate_trigger",
                                summary="spawned, not awaited")
        message_flow.end_trace(ctx, outcome="blocked")
        message_flow.flush()
        rows = _rows(flow_db, "SELECT kind, node_id, status, reason_code, metrics "
                              "FROM flow_events WHERE trace_id='r-6' "
                              "AND kind IN ('decision','checkpoint') ORDER BY id")
        assert rows[0][:4] == ("decision", "chat.daily_budget", "blocked", "pause_all")
        assert '"role"' in rows[0][4] and "chat" in rows[0][4]
        assert rows[1][:3] == ("checkpoint", "chat.consolidate_trigger", "succeeded")

    def test_relation_links_both_traces(self, flow_db):
        parent = message_flow.begin_trace(root_kind="qq_chat", trace_id="p-1")
        child = message_flow.begin_trace(root_kind="consolidate", trace_id="c-1")
        message_flow.link("p-1", "c-1", kind="spawned", evidence="consolidation")
        message_flow.end_trace(parent, outcome="delivered")
        message_flow.end_trace(child, outcome="closed")
        message_flow.flush()
        rel = _rows(flow_db, "SELECT parent_trace_id, child_trace_id, kind "
                             "FROM trace_relations")[0]
        assert rel == ("p-1", "c-1", "spawned")
        # 双侧 link 事件（父 spawned / 子 spawned_by）
        child_links = _rows(flow_db, "SELECT instance_key FROM flow_events "
                                     "WHERE trace_id='c-1' AND kind='link'")
        assert child_links == [("spawned_by",)]

    def test_self_link_ignored(self, flow_db):
        # 先跑一笔让 schema 初始化（link 早退不触碰 writer）
        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="warm")
        message_flow.end_trace(ctx)
        message_flow.flush()
        message_flow.link("x", "x")
        message_flow.flush()
        assert _rows(flow_db, "SELECT COUNT(*) FROM trace_relations")[0][0] == 0


class TestWriterDiscipline:
    def test_flush_drains_queue(self, flow_db):
        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="r-7")
        for i in range(50):
            message_flow.checkpoint(ctx, "chat.context", summary=f"e{i}")
        message_flow.end_trace(ctx)
        message_flow.flush()
        assert message_flow.flow_health()["queue"] == 0
        n = _rows(flow_db, "SELECT COUNT(*) FROM flow_events "
                           "WHERE trace_id='r-7'")[0][0]
        assert n >= 50

    def test_sensitive_keys_scrubbed(self, flow_db):
        ctx = message_flow.begin_trace(root_kind="qq_chat", trace_id="r-8")
        message_flow.decision(ctx, "capability.route", status="succeeded",
                              metrics={"api_key": "sk-secret",
                                       "nested": {"token": "t"},
                                       "safe": "ok"})
        message_flow.end_trace(ctx)
        message_flow.flush()
        metrics = _rows(flow_db, "SELECT metrics FROM flow_events "
                                 "WHERE trace_id='r-8' AND kind='decision'")[0][0]
        assert "sk-secret" not in metrics
        assert "t" + "secret" not in metrics.replace("[REDACTED]", "")
        assert "ok" in metrics

    def test_unknown_root_kind_recorded(self, flow_db):
        """root_kind 即目录入口节点 ID：存原值，由 reader/目录解释。"""
        ctx = message_flow.begin_trace(root_kind="qq_passive", trace_id="r-9",
                                       source_message_key="qq:b:g:42")
        message_flow.end_trace(ctx)
        message_flow.flush()
        row = _rows(flow_db, "SELECT root_kind, source_message_key, status "
                             "FROM message_traces WHERE trace_id='r-9'")[0]
        assert row == ("qq_passive", "qq:b:g:42", "closed")


class TestCatalog:
    def test_catalog_internal_consistency(self):
        assert flow_catalog.validate() == []

    def test_hook_mappings_reference_catalog_nodes(self):
        for mapping in (flow_catalog.HOOK_NODE_IDS, flow_catalog.POST_HOOK_NODE_IDS):
            for node_id in mapping.values():
                assert node_id in flow_catalog.NODES
        for node_id in flow_catalog.ENTRY_ROOTS.values():
            assert node_id in flow_catalog.NODES

    def test_every_node_has_lane_and_label(self):
        lanes = {lid for lid, _ in flow_catalog.LANES}
        for node in flow_catalog.NODES.values():
            assert node.lane in lanes
            assert node.label
            assert not node.id.endswith(".")

    def test_main_chain_connected_from_entry(self):
        """主链（receive→…→post.done→send.segment）在静态边上是连通的。"""
        adjacency: dict[str, list[str]] = {}
        for e in flow_catalog.EDGES:
            if e.kind in ("order", "condition"):
                adjacency.setdefault(e.src, []).append(e.dst)
        seen = set()

        def walk(node: str) -> None:
            if node in seen:
                return
            seen.add(node)
            for nxt in adjacency.get(node, []):
                walk(nxt)

        walk("ingress.receive")
        for required in ("chat.daily_budget", "turn.generate", "post.done",
                         "send.segment", "reply.bookkeeping"):
            assert required in seen, required

    def test_topology_version_format(self):
        assert flow_catalog.TOPOLOGY_VERSION
        assert flow_catalog.CATALOG_SCHEMA_VERSION >= 1
