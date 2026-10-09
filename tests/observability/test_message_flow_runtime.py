# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""消息流程运行时事实（计划 §8.1）：facade 全出口 + 逐段交付的真实事件。

覆盖验收矩阵的同步半边：正常轮次（A01 精简版）、DIRECT 早退（A11）、
provider 异常（A13）、no_backend（A12）、取消（A14 的 facade 半边）、
逐段发送 partial/失败停止/取消（A16/A14 的交付半边）。全部走真实
TurnService/facade/deliver_lines 代码路径，只断言 flow_events 事实，
业务行为断言沿用既有 runtime 测试。
"""

from __future__ import annotations

import sqlite3

import pytest

from core.context import ChatContext
from core.observability import message_flow, turn_trace
from core.runtime.facade import RuntimeFacade
from core.runtime.turn_service import TurnService
from memory.post_processors import bad_phrase_filter, parse_output, split_lines


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


def _events(db, trace_id: str, kinds: tuple[str, ...] | None = None) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        sql = "SELECT kind, node_id, status, COALESCE(summary, '') FROM flow_events WHERE trace_id=?"
        if kinds:
            marks = ",".join("?" * len(kinds))
            sql += f" AND kind IN ({marks})"
        return conn.execute(sql, (trace_id, *(kinds or ()))).fetchall()
    finally:
        conn.close()


def _nodes(db, trace_id: str) -> set[tuple[str, str]]:
    return {(n, s) for _, n, s, _ in _events(db, trace_id)}


class _Backend:
    backend_name = "scripted"
    model = "m"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.calls += 1
        return "<thought>好</thought><action>NONE</action><reply>脚本回复</reply>"


def _pipeline(backend=None) -> TurnService:
    p = TurnService(timeout=10.0)
    if backend is not None:
        p.set_llm_backend(backend)
    p.register_post_hook(parse_output, priority=100)
    p.register_post_hook(bad_phrase_filter, priority=80)
    p.register_post_hook(split_lines, priority=60)
    return p


async def _submit(facade, pipeline, ctx, **kw):
    return await facade.submit_turn("qq:1:g", pipeline, ctx, **kw)


class TestFacadeTurnFacts:
    async def test_generate_turn_full_facts(self, flow_db, tmp_path):
        backend = _Backend()
        root = message_flow.begin_trace(root_kind="qq_chat", platform="qq",
                                        scope="qq:1", trace_id="rf-1")
        ctx = ChatContext(user_id=2, group_id=1, msg_id=9, message="在吗",
                          trace_id=root.trace_id)
        message_flow.attach(ctx, root)
        facade = RuntimeFacade(store=None)
        out = await _submit(facade, _pipeline(backend), ctx)
        message_flow.attach(out, root)
        message_flow.end_trace(root, outcome="delivered")
        message_flow.flush()

        assert out.lines == ["脚本回复"]
        nodes = _nodes(flow_db, "rf-1")
        for node, status in [
            ("turn.identity", "running"),          # start 事件
            ("turn.prepare", "running"),
            ("turn.generate", "succeeded"),
            ("turn.generated", "succeeded"),
            ("finalize.trace", "succeeded"),
            ("post.parse", "succeeded"),
            ("post.split", "succeeded"),
            ("prompt.fit", "succeeded"),
        ]:
            assert (node, status) in nodes, (node, status)
        # 生成的轮次一定有根 start 与 trace_end
        kinds = [k for k, *_ in _events(flow_db, "rf-1")]
        assert kinds.count("start") >= 1 and "trace_end" in kinds

    async def test_direct_early_exit_skips_generation_and_finalize(self, flow_db):
        root = message_flow.begin_trace(root_kind="qq_chat", trace_id="rf-2")
        p = _pipeline(_Backend())

        async def hook(ctx):
            ctx.reply = "已被拦截"
            return ctx

        p.register_pre_hook(hook, priority=10)
        facade = RuntimeFacade(store=None)
        await _submit(facade, p, ChatContext(user_id=2, group_id=1,
                                             msg_id=1, message="x",
                                             trace_id=root.trace_id))
        message_flow.flush()
        nodes = _nodes(flow_db, "rf-2")
        assert ("prepare.direct", "succeeded") in nodes
        assert ("turn.direct_silent", "skipped") in nodes
        assert ("finalize.trace", "succeeded") not in nodes
        # 直回不产生 provider 调用
        assert "turn.generated" not in {n for n, _ in nodes}

    async def test_provider_error_marks_turn_error(self, flow_db):
        root = message_flow.begin_trace(root_kind="qq_chat", trace_id="rf-3")
        p = _pipeline(_Backend())

        async def boom(key, prompt):
            raise RuntimeError("后端爆炸")

        facade = RuntimeFacade(provider=boom, store=None)
        out = await _submit(facade, p, ChatContext(user_id=2, group_id=1,
                                                   msg_id=2, message="x",
                                                   trace_id=root.trace_id))
        message_flow.flush()
        nodes = _nodes(flow_db, "rf-3")
        assert ("turn.error", "failed") in nodes
        assert ("finalize.trace", "succeeded") in nodes  # 兜底仍走 finalize
        assert out.lines == ["......？"]

    async def test_no_backend_fallback(self, flow_db):
        root = message_flow.begin_trace(root_kind="qq_chat", trace_id="rf-4")
        facade = RuntimeFacade(store=None)
        await _submit(facade, _pipeline(None), ChatContext(user_id=2, group_id=1,
                                                           msg_id=3, message="x",
                                                           trace_id=root.trace_id))
        message_flow.flush()
        nodes = _nodes(flow_db, "rf-4")
        assert ("prepare.backend_budget", "blocked") in nodes
        assert ("turn.fallback", "blocked") in nodes
        assert ("turn.generate", "succeeded") not in nodes

    async def test_cancelled_turn_facts(self, flow_db, tmp_path):
        root = message_flow.begin_trace(root_kind="qq_chat", trace_id="rf-5")
        p = _pipeline(_Backend())
        facade = RuntimeFacade(store=None, default_deadline=0.2)

        import asyncio

        gate = asyncio.Event()

        async def slow(key, prompt):
            await asyncio.wait_for(gate.wait(), timeout=15.0)
            return "<reply>慢</reply>"

        facade._provider = slow
        task = asyncio.create_task(_submit(
            facade, p, ChatContext(user_id=2, group_id=1, msg_id=4, message="x",
                                   trace_id=root.trace_id)))
        await asyncio.sleep(0.05)
        await facade.cancel_turn("qq:1:g")
        from core.runtime.facade import RuntimeTurnError

        with pytest.raises(RuntimeTurnError):
            await task
        message_flow.flush()
        nodes = _nodes(flow_db, "rf-5")
        assert ("turn.cancel", "cancelled") in nodes
        assert ("turn.generate", "cancelled") in nodes


class TestDeliverySegmentFacts:
    async def test_partial_send_second_segment_fails_stop(self, flow_db):
        root = message_flow.begin_trace(root_kind="qq_chat", trace_id="rd-1")
        sent: list[str] = []

        async def send_one(line: str, i: int) -> str | None:
            if i == 1:
                raise RuntimeError("平台异常")
            sent.append(line)
            return 100 + i

        from core.social.delivery import (
            create_delivery_draft,
            deliver_lines,
            seal_delivery_plan,
        )

        draft = create_delivery_draft(
            trace_id=root.trace_id, turn_id="t-1", source_kind="model",
            protocol_version="test", disposition="deliver",
            conversation_key="qq:test:group:delivery", segments=["一", "二", "三"],
        )

        receipts = await deliver_lines(
            seal_delivery_plan(draft), scope=None, trace_id=root.trace_id,
            turn_id="t-1", send_one=send_one)
        message_flow.end_trace(root, outcome="partial")
        message_flow.flush()
        assert [r.status for r in receipts] == ["acknowledged", "failed"]
        assert sent == ["一"]
        # 逐段事实：seg:0 成功、seg:1 失败、seg:2 未尝试（无事件即无事实）
        conn = sqlite3.connect(flow_db)
        rows = conn.execute(
            "SELECT instance_key, status FROM flow_events "
            "WHERE trace_id='rd-1' AND node_id='send.segment' AND kind='finish' "
            "ORDER BY id"
        ).fetchall()
        conn.close()
        assert rows == [("seg:0", "succeeded"), ("seg:1", "failed")]
        # 聚合事实：partial 在 summary/metrics，不伪装成全失败或全成功
        agg = [r for r in _events(flow_db, "rd-1")
               if r[1] == "send.aggregate"]
        assert agg and agg[0][2] == "succeeded" and agg[0][3] == "partial"

    async def test_abort_marks_unattempted_segments(self, flow_db):
        root = message_flow.begin_trace(root_kind="qq_chat", trace_id="rd-2")

        async def send_one(line: str, i: int) -> str | None:
            return str(200 + i)

        from core.social.delivery import (
            create_delivery_draft,
            deliver_lines,
            seal_delivery_plan,
        )

        draft = create_delivery_draft(
            trace_id=root.trace_id, turn_id="t-2", source_kind="model",
            protocol_version="test", disposition="deliver",
            conversation_key="qq:test:group:delivery", segments=["一", "二"],
        )

        await deliver_lines(
            seal_delivery_plan(draft), scope=None, trace_id=root.trace_id,
            turn_id="t-2", send_one=send_one, abort_check=lambda: True)
        message_flow.flush()
        rows = [(n, s) for _, n, s, _ in _events(flow_db, "rd-2")
                if n == "send.segment"]
        assert ("send.segment", "skipped") in rows

    async def test_delivery_without_root_is_silent(self, flow_db):
        """没有流程 root（旧路径/未接入）时交付完全空转。"""
        # 先跑一笔让 schema 初始化（本用例的 trace 不存在）
        warm = message_flow.begin_trace(root_kind="qq_chat", trace_id="warm")
        message_flow.end_trace(warm)
        message_flow.flush()
        from core.social.delivery import (
            create_delivery_draft,
            deliver_lines,
            seal_delivery_plan,
        )

        async def send_one(line: str, i: int) -> str | None:
            return str(300 + i)

        plan = seal_delivery_plan(create_delivery_draft(
            trace_id="no-such-trace", turn_id="t-3", source_kind="model",
            protocol_version="test", disposition="deliver",
            conversation_key="qq:test:group:delivery", segments=["一"],
        ))
        receipts = await deliver_lines(
            plan, scope=None, trace_id="no-such-trace", turn_id="t-3",
            send_one=send_one)
        assert receipts[0].status == "acknowledged"
        message_flow.flush()
        assert _events(flow_db, "no-such-trace") == []


class TestRootLifecycle:
    def test_attach_and_flow_of(self, flow_db):
        root = message_flow.begin_trace(root_kind="webchat", trace_id="rl-1")
        ctx = ChatContext(user_id=1, group_id=-1, msg_id=0, message="hi",
                          trace_id="not-registered")
        assert message_flow.flow_of(ctx) is None  # 未 attach 且 trace 未注册
        message_flow.attach(ctx, root)
        assert message_flow.flow_of(ctx) is root
        # trace_id 回查兜底
        ctx2 = ChatContext(user_id=1, group_id=-1, msg_id=0, message="hi",
                           trace_id="rl-1")
        assert message_flow.flow_of(ctx2) is root
        # trace_id 回查兜底
        ctx2 = ChatContext(user_id=1, group_id=-1, msg_id=0, message="hi",
                           trace_id="rl-1")
        assert message_flow.flow_of(ctx2) is root

    def test_begin_is_idempotent_for_active_trace(self, flow_db):
        root = message_flow.begin_trace(root_kind="webchat", trace_id="rl-2")
        again = message_flow.begin_trace(root_kind="webchat", trace_id="rl-2")
        assert again is root

    def test_end_trace_sets_outcome_and_complete(self, flow_db):
        root = message_flow.begin_trace(root_kind="webchat", trace_id="rl-3")
        with message_flow.span(root, "web.session_lock"):
            pass
        message_flow.end_trace(root, outcome="delivered")
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        row = conn.execute(
            "SELECT status, outcome, complete FROM message_traces "
            "WHERE trace_id='rl-3'").fetchone()
        conn.close()
        assert row == ("closed", "delivered", 1)


class TestAsyncLoopLinks:
    def test_by_source_key_lookup(self, flow_db):
        root = message_flow.begin_trace(root_kind="cometa_task",
                                        source_message_key="cometa:task-1")
        assert message_flow.by_source_key("cometa:task-1") is root
        message_flow.end_trace(root)
        # 已结束的 root 不再命中：worker 重开同一任务时按需新建
        assert message_flow.by_source_key("cometa:task-1") is None

    def test_relation_dedup(self, flow_db):
        message_flow.link("p", "c", kind="spawned", evidence="x")
        message_flow.link("p", "c", kind="spawned", evidence="x")
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        n = conn.execute(
            "SELECT COUNT(*) FROM trace_relations "
            "WHERE parent_trace_id='p' AND child_trace_id='c'").fetchone()[0]
        conn.close()
        assert n == 1

    async def test_compact_root_linked_to_parent(self, flow_db, monkeypatch):
        """schedule_compact 建独立 root 并 caused_by 关联触发 trace（计划 §6.2）。"""
        import memory.session_compact as sc

        message_flow.begin_trace(root_kind="qq_chat", trace_id="rp-1")
        called = []

        async def fake_compact_once(group_id, tail_start_id):
            called.append((group_id, tail_start_id))

        monkeypatch.setattr(sc, "compact_once", fake_compact_once)
        sc.schedule_compact(1, 42, parent_trace_id="rp-1")
        for _ in range(100):
            if called:
                break
            import asyncio

            await asyncio.sleep(0.01)
        message_flow.flush()
        assert called == [(1, 42)]
        conn = sqlite3.connect(flow_db)
        rows = conn.execute(
            "SELECT parent_trace_id, child_trace_id, kind FROM trace_relations"
        ).fetchall()
        roots = conn.execute(
            "SELECT root_kind FROM message_traces WHERE root_kind='compact'"
        ).fetchall()
        conn.close()
        assert rows and rows[0][0] == "rp-1" and rows[0][2] == "caused_by"
        assert roots == [("compact",)]


class TestTransitionFacts:
    """修复计划 §6.4（M3）：显式边级跳转事实合同。"""

    def test_transition_writes_versioned_fact(self, flow_db):
        root = message_flow.begin_trace(root_kind="webchat", trace_id="tr-1")
        with message_flow.span(root, "turn.prepare") as sp:
            message_flow.transition(
                root, from_node="turn.prepare", to_node="turn.generate",
                from_span=sp, attempt=0)
        message_flow.end_trace(root)
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        try:
            row = conn.execute(
                "SELECT kind, fact_kind, node_id, metrics FROM flow_events "
                "WHERE trace_id='tr-1' AND fact_kind='transition'").fetchone()
        finally:
            conn.close()
        assert row is not None
        kind, fact_kind, node_id, metrics = row
        assert kind == "decision" and fact_kind == "transition"
        assert node_id == "turn.prepare"
        import json

        m = json.loads(metrics)
        assert m["transition_v"] == 1
        assert m["edge_id"] == "turn.prepare->turn.generate:order"
        assert m["from_node"] == "turn.prepare" and m["to_node"] == "turn.generate"
        assert m["from_span_id"]  # 真实 span 句柄被记录

    def test_transition_no_span_occurrence_still_records(self, flow_db):
        """无 span 的 decision 边（occurrence 事实）不臆造 parent span。"""
        root = message_flow.begin_trace(root_kind="webchat", trace_id="tr-2")
        message_flow.transition(
            root, from_node="chat.daily_budget", to_node="turn.identity",
            relation_kind="condition", summary="放行")
        message_flow.end_trace(root)
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        try:
            m = conn.execute(
                "SELECT metrics FROM flow_events WHERE trace_id='tr-2' "
                "AND fact_kind='transition'").fetchone()[0]
        finally:
            conn.close()
        import json

        assert json.loads(m)["edge_id"] == "chat.daily_budget->turn.identity:condition"
