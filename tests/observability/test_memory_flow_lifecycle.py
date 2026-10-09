# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆整合/晋升/维护生命周期观测探针合同（计划 §6.3 / M2 退出条件）。

覆盖（计划 §8.3 tests/observability/test_memory_flow_lifecycle.py 行）：
- (a) memory_consolidate root 生命周期与消费窗口事实（含 caused_by 关联、
  候选写入计数、晋升作为子 span 复用同一 root）；
- (a2) 解析失败推进 checkpoint 与截断停 checkpoint 必须不同 reason_code；
- (b) promotion root 逐候选 gate decision：阈值与实际值出现在 metrics；
- (c) memory.promotion.commit 事实在业务 commit 之后；commit 失败 →
  failed(rolled_back) + 候选状态未变 + 不落对象履历（事务诚实，计划 §6.1）；
- (d) 弱候选冲突现状复现（计划 §5 登记的 Python/Rust parity 案例，本轮只
  观测不修业务）：Python 置 OBSERVING 后上层晋升继续、最终改写 CONFIRMED；
- (e) quota 只在新建分支记录（计划 §5：合并不增加条数，不虚构配额执行）；
- (f) 观测异常不影响晋升结果（旁路纪律，计划 §6.3 最高优先级）。

MemoryManager / MemoryConsolidator 的构造沿用 tests/test_memory_manager.py 与
tests/test_consolidator_core.py 的 fixture 方式（tmp 库 + monkeypatch DB_PATH +
fake LLM 后端）；只测探针合同，不测抽取 prompt 与评分词表本身。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

import memory.consolidator as consolidator
import memory.memory_manager as memory_manager
from core.observability import entity_history, message_flow, turn_trace

# 整合 LLM 的确定性应答：1 条候选（发送者白名单内），无自我披露（不唤醒 stage2）
_CONSOLIDATE_REPLY = json.dumps({
    "short_term": {"active_summary": "聊整合", "recent_exchanges": []},
    "user_profiles": [],
    "memory_candidates": [
        {"user_id": "111", "type": "FACT", "content": "使用RTX5080显卡",
         "importance": 0.8, "confidence": 0.9},
    ],
})


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


class _FakeBackend:
    """按预设 finish_reason 序列应答（同 tests/test_consolidator_core.py 的替身）。"""

    def __init__(self, reply: str = "{}", finishes: tuple = ("stop",)):
        self.model = "fake-model"
        self.reply = reply
        self._finishes = list(finishes)
        self.prompts: list[str] = []

    async def generate_detailed(self, prompt: str, system_prompt: str = ""):
        self.prompts.append(prompt)
        finish = self._finishes[min(len(self.prompts) - 1, len(self._finishes) - 1)]
        return self.reply, finish


@pytest.fixture()
def cons_env(tmp_path, monkeypatch):
    """MemoryConsolidator 临时库（沿用 test_consolidator_core 的构造方式）。"""
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 30)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    # 晋升侧同库 + Dummy 压缩器；清单例让本用例的 DB_PATH 生效
    monkeypatch.setattr(memory_manager, "DB_PATH", db)
    # 本文件验证的是 **python 晋升路径** 的 flow 观测合同（merge/create/quota
    # span 是 python 分支的节点）；native 后端有独立测试。钉住后端保证
    # 本机装了 v18 native 时这些用例仍然测它们声称的东西。
    monkeypatch.setenv("MEMORY_BACKEND", "python")
    monkeypatch.setattr(
        memory_manager, "get_compressor",
        lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})(),
    )
    monkeypatch.setattr(memory_manager, "_memory_manager_instance", None)
    cons = consolidator.MemoryConsolidator.__new__(consolidator.MemoryConsolidator)
    conn = sqlite3.connect(db)
    cons._ensure_common_tables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT,"
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS long_term_memories ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, summary TEXT,"
        "importance REAL, access_count INTEGER DEFAULT 0, last_accessed_at TEXT)"
    )
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        [("1001", "111", "m" + str(i)) for i in range(30)],
    )
    conn.commit()
    conn.close()
    return cons


@pytest.fixture()
def mem_env(tmp_path, monkeypatch):
    """MemoryManager 临时库（沿用 test_memory_manager 的构造方式）。"""
    db = tmp_path / "agent_memory.db"
    db.touch()
    monkeypatch.setattr(memory_manager, "DB_PATH", db)
    # 本文件验证 python 晋升路径的 flow 观测合同（merge/create/quota 是
    # python 分支节点）；native 后端有独立测试（test_memory_rust_promotion）。
    monkeypatch.setenv("MEMORY_BACKEND", "python")
    monkeypatch.setattr(
        memory_manager, "get_compressor",
        lambda: type("Dummy", (), {"maybe_compress": lambda self, reason: None})(),
    )
    monkeypatch.setattr(memory_manager, "_memory_manager_instance", None)
    return db


def _insert_candidate(db, cid: str, content: str, *, confidence: float,
                      importance: float = 0.8, status: str = "NEW",
                      occurrence: int = 1, user_id: str = "100", type_: str = "FACT"):
    """Seed an accepted source packet for promotion-path observation tests."""
    from memory.evidence_contract import ASSESSMENT_VERSION, source_digest

    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT, "
        "source_kind TEXT, conversation_key TEXT, bot_id TEXT)"
    )
    source_id = int(conn.execute(
        "SELECT COALESCE(MAX(id), 0) + 1 FROM group_messages"
    ).fetchone()[0])
    conversation_key = "qq:test-bot:group:1"
    owner_key = "space:1"
    fact_key = f"claim:v1:{cid}"
    snapshot = {
        "id": source_id,
        "group_id": "1",
        "user_id": str(user_id),
        "content": content,
        "source_kind": "AT_MENTION",
        "conversation_key": conversation_key,
        "bot_id": "test-bot",
    }
    digest = source_digest(snapshot)
    provenance = {
        "assessment_version": ASSESSMENT_VERSION,
        "verification_status": "accepted",
        "claim_key": fact_key,
        "recording_author_key": f"qq:{user_id}",
        "fact_object_key": f"qq:{user_id}",
        "exact_support_span": content,
        "conversation_key": conversation_key,
        "source_id": source_id,
        "source_snapshot": snapshot,
    }
    conn.execute(
        "INSERT INTO memory_candidates (id, group_shared_space, user_id, type, content, "
        "importance, confidence, status, occurrence_count, owner_type, owner_key, "
        "subject_key, audience, fact_key, source_conversation_key, source_message_ids) "
        "VALUES (?, '1', ?, ?, ?, ?, ?, ?, ?, 'SPACE', ?, '', 'CURRENT_SPACE', ?, ?, ?)",
        (cid, user_id, type_, content, importance, confidence, status, occurrence,
         owner_key, fact_key, conversation_key, json.dumps([str(source_id)])),
    )
    conn.execute(
        "INSERT INTO group_messages "
        "(id, group_id, user_id, content, source_kind, conversation_key, bot_id) "
        "VALUES (?, '1', ?, ?, 'AT_MENTION', ?, 'test-bot')",
        (source_id, str(user_id), content, conversation_key),
    )
    evidence_id = f"evidence:{cid}:{source_id}"
    conn.execute(
        "INSERT INTO memory_evidence "
        "(id, owner_type, owner_key, subject_key, audience, fact_key, "
        "source_conversation_key, source_row_id, candidate_id, fact_subject_key, "
        "source_digest, verification_status, provenance_json) "
        "VALUES (?, 'SPACE', ?, '', 'CURRENT_SPACE', ?, ?, ?, ?, ?, ?, 'accepted', ?)",
        (evidence_id, owner_key, fact_key, conversation_key, source_id, cid,
         f"qq:{user_id}", digest,
         json.dumps(provenance, ensure_ascii=False, separators=(",", ":"))),
    )
    for entity_type, entity_id, projection_slot in (
        ("memory_candidate", cid, "candidate"),
        ("claim_state", fact_key, "eligibility"),
    ):
        conn.execute(
            "INSERT INTO memory_claim_links "
            "(id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key, "
            "projection_slot, slot_digest, status) "
            "VALUES (?, ?, ?, 'CURRENT_SPACE', ?, ?, ?, ?, ?, 'active')",
            (f"link:{cid}:{source_id}:{projection_slot}", evidence_id, owner_key,
             entity_type, entity_id, fact_key, projection_slot, digest),
        )
    conn.commit()
    conn.close()


def _events(db, trace_id: str, node_id: str | None = None,
            kind: str | None = None) -> list[SimpleNamespace]:
    conn = sqlite3.connect(db)
    try:
        sql = ("SELECT kind, node_id, status, reason_code, metrics, instance_key, fact_kind "
               "FROM flow_events WHERE trace_id=?")
        params: list[str] = [trace_id]
        if node_id:
            sql += " AND node_id=?"
            params.append(node_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    finally:
        conn.close()
    out = []
    for k, n, s, r, m, ik, fk in rows:
        try:
            metrics = json.loads(m) if m else {}
        except json.JSONDecodeError:
            metrics = {}
        out.append(SimpleNamespace(kind=k, node_id=n, status=s, reason_code=r,
                                   metrics=metrics, instance_key=ik, fact_kind=fk))
    return out


def _spans(db, trace_id: str, node_id: str) -> list[SimpleNamespace]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT node_id, instance_key, status, reason_code FROM flow_spans "
            "WHERE trace_id=? AND node_id=? ORDER BY seq", (trace_id, node_id)).fetchall()
    finally:
        conn.close()
    return [SimpleNamespace(node_id=n, instance_key=ik, status=s, reason_code=r)
            for n, ik, s, r in rows]


def _latest_trace(db, root_kind: str):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT trace_id, origin, scope, outcome, status FROM message_traces "
            "WHERE root_kind=? ORDER BY started_utc DESC LIMIT 1",
            (root_kind,)).fetchone()
    finally:
        conn.close()


def _trace_detail(db, trace_id: str) -> dict:
    conn = sqlite3.connect(db)
    try:
        raw = conn.execute(
            "SELECT detail FROM message_traces WHERE trace_id=?", (trace_id,)).fetchone()
    finally:
        conn.close()
    return json.loads(raw[0]) if raw and raw[0] else {}


# ── (a) memory_consolidate root 生命周期与消费窗口事实 ────────────────


class TestConsolidateRootLifecycle:
    def test_root_window_write_and_promotion_child(self, flow_db, cons_env):
        """整合 root 独立建/正常收口；窗口事实、gate2、写入计数、晋升子 span。"""
        cons = cons_env
        cons._backends = [("fake", _FakeBackend(_CONSOLIDATE_REPLY))]
        asyncio.run(cons.consolidate_group(1001))
        message_flow.flush()

        row = _latest_trace(flow_db, "memory_consolidate")
        assert row is not None
        trace_id, origin, scope, outcome, _status = row
        assert origin == "spawn"
        assert scope == "qq:1001"
        assert outcome == "checkpoint_advanced"
        assert _trace_detail(flow_db, trace_id).get("force") is False

        # 入口事实：force / checkpoint 位置 / 积压计数 / 批次阈值
        entry = _events(flow_db, trace_id, node_id="memory.consolidate.entry",
                        kind="checkpoint")
        assert entry and entry[0].metrics["force"] is False
        assert entry[0].metrics["new_count"] == 30
        assert entry[0].metrics["threshold"] == 30

        # 消费窗口事实：真实消费的 id 范围与条数（计划 §6.3 memory.consolidate.window）
        window = _events(flow_db, trace_id, node_id="memory.consolidate.window",
                         kind="checkpoint")
        assert window
        m = window[0].metrics
        assert m["consumed_from"] == 1
        assert m["consumed_to"] == 30
        assert m["consumed_count"] == 30
        assert m["backend"] == "fake"

        # gate2：无自我披露 → skipped（不唤醒 stage2）
        gate2 = _events(flow_db, trace_id, node_id="memory.extract.gate2",
                        kind="decision")
        assert gate2 and gate2[0].reason_code == "no_self_disclosure"

        # 候选写入计数（1 写入；无白名单外候选）
        write = _events(flow_db, trace_id, node_id="memory.candidate.write",
                        kind="finish")
        assert write and write[0].metrics["written"] == 1

        # 晋升复用同一 root（不自建 promotion root）；逐候选 gate + commit 事实
        assert _latest_trace(flow_db, "memory_promotion") is None
        gate = _events(flow_db, trace_id, node_id="memory.promotion.gate",
                       kind="decision")
        assert gate and "threshold_high_confidence" in gate[0].metrics
        commit = _events(flow_db, trace_id, node_id="memory.promotion.commit",
                         kind="decision")
        assert commit
        assert commit[0].fact_kind == "commit" and commit[0].status == "succeeded"
        # 候选创建履历关联到整合 root（业务提交后落账，计划 §6.1）
        hist = entity_history.for_trace(trace_id)
        assert any(h["entity_type"] == "memory_candidate" and h["to_state"] == "NEW"
                   for h in hist)

    def test_parent_link_when_flow_ctx_passed(self, flow_db, cons_env):
        """调用方显式传 flow_ctx → 入口建 caused_by relation（不靠 ambient 猜）。"""
        cons = cons_env
        cons._backends = [("fake", _FakeBackend("{}"))]
        parent = message_flow.begin_trace(root_kind="qq_chat", trace_id="msg-root-1")
        asyncio.run(cons.consolidate_group(1001, flow_ctx=parent))
        message_flow.end_trace(parent)
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        try:
            rel = conn.execute(
                "SELECT parent_trace_id, child_trace_id, kind FROM trace_relations "
                "WHERE parent_trace_id='msg-root-1'").fetchall()
        finally:
            conn.close()
        assert rel and rel[0][2] == "caused_by"

    def test_parse_failed_and_truncated_have_distinct_reason_codes(self, flow_db, cons_env):
        """计划 §6.3：解析失败**推进** checkpoint 与截断**停** checkpoint 必须可区分。"""
        cons = cons_env
        # 解析失败：模型胡言乱语 → 推进 checkpoint（重跑无益）
        cons._backends = [("fake", _FakeBackend("完全没有 JSON"))]
        asyncio.run(cons.consolidate_group(1001))
        message_flow.flush()
        row = _latest_trace(flow_db, "memory_consolidate")
        assert row[3] == "checkpoint_advanced_parse_failed"
        advanced = _events(flow_db, row[0], node_id="memory.consolidate.window",
                           kind="decision")
        assert advanced
        assert advanced[0].reason_code == "parse_failed_advance_checkpoint"
        assert cons._get_last_processed_id(1001) == 30

        # 截断：配置问题 → checkpoint 停在原地等人改配置
        cons._update_checkpoint(1001, 0)
        cons._backends = [("fake", _FakeBackend("{}", finishes=("length",)))]
        asyncio.run(cons.consolidate_group(1001))
        message_flow.flush()
        row2 = _latest_trace(flow_db, "memory_consolidate")
        assert row2[3] == "checkpoint_held_truncated"
        held = _events(flow_db, row2[0], node_id="memory.consolidate.window",
                       kind="decision")
        assert held
        assert held[0].reason_code == "truncated_hold_checkpoint"
        assert held[0].status == "blocked"
        assert cons._get_last_processed_id(1001) == 0
        assert advanced[0].reason_code != held[0].reason_code


# ── (b) promotion root 与逐候选 gate decision ────────────────────────


class TestPromotionRootGate:
    def test_root_and_gate_threshold_metrics(self, flow_db, mem_env, monkeypatch):
        """自建 promotion root；gate decision 携带阈值与实际值（计划 §6.3）。"""
        db = mem_env
        monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)
        manager = memory_manager.MemoryManager()
        _insert_candidate(db, "c2", "高质量候选", confidence=0.9, user_id="200")
        _insert_candidate(db, "c1", "低价值候选", confidence=0.3, importance=0.5,
                          user_id="100")

        manager.process_new_candidates()
        message_flow.flush()

        row = _latest_trace(flow_db, "memory_promotion")
        assert row is not None
        trace_id, origin, scope, outcome, _status = row
        assert origin == "spawn" and scope == "memory_shared" and outcome == "done"
        # 后端决策：mem_env 钉了 python 后端（本文件只测 python 路径的观测）
        backend = _events(flow_db, trace_id, node_id="memory.promotion.backend",
                          kind="decision")
        assert backend and backend[0].reason_code == "python"
        # 批次事实：actual scope 与条数
        batch = _events(flow_db, trace_id, node_id="memory.promotion.batch",
                        kind="checkpoint")
        assert batch and batch[-1].metrics["candidates"] == 2
        assert set(batch[-1].metrics["spaces"]) == {"1"}

        gates = _events(flow_db, trace_id, node_id="memory.promotion.gate",
                        kind="decision")
        by_cand = {e.instance_key: e for e in gates}
        high = by_cand["cand:c2"]
        assert high.status == "succeeded"
        assert high.metrics["confidence"] == pytest.approx(0.9)
        assert high.metrics["importance"] == pytest.approx(0.8)
        assert high.metrics["threshold_high_confidence"] == pytest.approx(0.5)
        low = by_cand["cand:c1"]
        assert low.status == "skipped"
        assert low.reason_code == "low_confidence"
        assert low.metrics["occurrence"] == 1
        assert low.metrics["threshold_low_confidence"] == pytest.approx(0.6)
        assert low.metrics["threshold_min_importance"] == pytest.approx(0.3)

        commit = _events(flow_db, trace_id, node_id="memory.promotion.commit",
                         kind="decision")
        assert commit and commit[0].fact_kind == "commit"
        assert commit[0].status == "succeeded"
        assert commit[0].metrics["backend"] == "python"
        # 对象履历：候选 NEW→CONFIRMED；长期记忆 NEW→active
        cand_hist = entity_history.history("memory_candidate", "c2")
        assert cand_hist and cand_hist[-1]["to_state"] == "CONFIRMED"
        mem_hist = [h for h in entity_history.for_trace(trace_id)
                    if h["entity_type"] == "long_term_memory"]
        assert mem_hist and mem_hist[0]["from_state"] == "NEW"
        assert mem_hist[0]["to_state"] == "active"

    def test_gate_hold_records_observing_history(self, flow_db, mem_env):
        """门槛未过的候选：gate decision skipped + 履历 NEW→OBSERVING。"""
        db = mem_env
        manager = memory_manager.MemoryManager()
        _insert_candidate(db, "c1", "低价值候选", confidence=0.3, importance=0.5)

        manager.process_new_candidates()
        message_flow.flush()

        row = _latest_trace(flow_db, "memory_promotion")
        gate = _events(flow_db, row[0], node_id="memory.promotion.gate",
                       kind="decision")
        assert gate and gate[0].status == "skipped"
        hist = entity_history.history("memory_candidate", "c1")
        assert hist and hist[-1]["from_state"] == "NEW"
        assert hist[-1]["to_state"] == "OBSERVING"


# ── (c) commit 事实与事务诚实 ────────────────────────────────────────


class TestCommitFacts:
    def test_commit_failure_records_rolled_back(self, flow_db, mem_env, monkeypatch):
        """commit 失败 → failed(rolled_back)、候选状态未变、不落对象履历。"""
        db = mem_env
        monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)
        manager = memory_manager.MemoryManager()  # 建表提交发生在装 shim 之前
        _insert_candidate(db, "c1", "高质量候选", confidence=0.9)

        # 注入：memory_manager 模块内 sqlite3.connect 返回包装连接，第 2 次
        # commit（批次提交）失败——第 1 次是 process 内 _ensure_tables 的提交。
        real_connect = sqlite3.connect
        counter = {"n": 0}

        class _FailingConn:
            def __init__(self, conn):
                self._conn = conn

            def __getattr__(self, item):
                return getattr(self._conn, item)

            def commit(self):
                counter["n"] += 1
                if counter["n"] == 2:
                    raise sqlite3.OperationalError("injected commit failure")
                return self._conn.commit()

        class _Shim:
            @staticmethod
            def connect(*args, **kwargs):
                return _FailingConn(real_connect(*args, **kwargs))

        monkeypatch.setattr(memory_manager, "sqlite3", _Shim)

        with pytest.raises(sqlite3.OperationalError):
            manager.process_new_candidates()
        message_flow.flush()

        row = _latest_trace(flow_db, "memory_promotion")
        assert row[3] == "error"
        commit = _events(flow_db, row[0], node_id="memory.promotion.commit",
                         kind="decision")
        assert commit and commit[0].status == "failed"
        assert commit[0].reason_code == "rolled_back"
        assert commit[0].fact_kind == "commit"
        # 业务未提交：候选保持 NEW（回滚），且对象履历不落「已发生」的假事实
        conn = sqlite3.connect(db)
        try:
            status = conn.execute(
                "SELECT status FROM memory_candidates WHERE id='c1'").fetchone()[0]
        finally:
            conn.close()
        assert status == "NEW"
        assert entity_history.history("memory_candidate", "c1") == []


# ── (d) 弱候选冲突现状复现（计划 §5 登记的 parity 案例）───────────────


class TestWeakConflictParity:
    def test_weak_candidate_stays_observing(self, flow_db, mem_env):
        """行为变更（2026-10-03 parity 修复，对齐 Rust observing_conflict）：
        弱候选（置信度低于旧记忆）被冲突解决压回 OBSERVING 后，晋升循环
        **不再**合并/新建/确认——终态保持 OBSERVING，不产生新记忆，旧记忆
        不动。履历只记录 NEW→OBSERVING 一次业务写入。

        修复前（bug 现状）：循环无视 weak_demoted 返回值，候选被改写
        CONFIRMED，矛盾两条 active 记忆并存。
        """
        db = mem_env
        manager = memory_manager.MemoryManager()
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
            "importance, confidence, status) "
            "VALUES ('old1', '1', '100', 'PREFERENCE', '用户喜欢Helldivers2', 0.8, 0.9, 'active')")
        conn.commit()
        conn.close()
        _insert_candidate(db, "c1", "用户不喜欢Helldivers2", confidence=0.7,
                          importance=0.9, occurrence=2, type_="PREFERENCE")

        manager.process_new_candidates()
        message_flow.flush()

        conn = sqlite3.connect(db)
        try:
            old_status = conn.execute(
                "SELECT status FROM memories WHERE id='old1'").fetchone()[0]
            cand_status = conn.execute(
                "SELECT status FROM memory_candidates WHERE id='c1'").fetchone()[0]
            new_memories = conn.execute(
                "SELECT COUNT(*) FROM memories WHERE id != 'old1'").fetchone()[0]
        finally:
            conn.close()
        # 修复合同：弱候选终态 OBSERVING；旧记忆不动；没有新记忆产生
        assert old_status == "active"
        assert cand_status == "OBSERVING"
        assert new_memories == 0
        row = _latest_trace(flow_db, "memory_promotion")
        conflicts = _events(flow_db, row[0], node_id="memory.promotion.conflict",
                            kind="decision")
        assert conflicts
        assert conflicts[0].reason_code == "weak_candidate_observing"
        assert conflicts[0].status == "skipped"
        assert conflicts[0].metrics["old_confidence"] == pytest.approx(0.9)
        # gate span 以 conflict_weak_observing 收尾（跳过合并/新建的可见事实）
        gates = _events(flow_db, row[0], node_id="memory.promotion.gate",
                        kind="finish")
        assert any(g.reason_code == "conflict_weak_observing" for g in gates)
        # 履历只记录 NEW→OBSERVING 一次业务写入，无 CONFIRMED 改写
        states = [e["to_state"] for e in entity_history.history("memory_candidate", "c1")]
        assert states == ["OBSERVING"]

    def test_evidence_reversal_promotes_and_marks_old_conflict(
            self, flow_db, mem_env, monkeypatch):
        """翻案语义保留：弱候选留 OBSERVING 后，复现推高 confidence 反超
        旧记忆时走「强候选」分支——旧记忆标 CONFLICT、候选正常晋升。"""
        db = mem_env
        manager = memory_manager.MemoryManager()
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
            "importance, confidence, status) "
            "VALUES ('old1', '1', '100', 'PREFERENCE', '用户喜欢Helldivers2', 0.8, 0.9, 'active')")
        conn.commit()
        conn.close()
        _insert_candidate(db, "c1", "用户不喜欢Helldivers2", confidence=0.7,
                          importance=0.9, occurrence=2, type_="PREFERENCE")
        manager.process_new_candidates()
        message_flow.flush()
        # 态度真的变了：更多证据把 confidence 推过旧记忆（0.9）
        conn = sqlite3.connect(db)
        conn.execute(
            "UPDATE memory_candidates SET confidence = 0.95 WHERE id = 'c1'")
        conn.commit()
        conn.close()
        manager.process_new_candidates()
        message_flow.flush()

        conn = sqlite3.connect(db)
        try:
            old_status = conn.execute(
                "SELECT status FROM memories WHERE id='old1'").fetchone()[0]
            cand_status = conn.execute(
                "SELECT status FROM memory_candidates WHERE id='c1'").fetchone()[0]
        finally:
            conn.close()
        assert old_status == "conflict"   # 旧记忆让位
        assert cand_status == "CONFIRMED"  # 新态度晋升
        states = [e["to_state"] for e in entity_history.history("memory_candidate", "c1")]
        assert states[-1] == "CONFIRMED"
        old_states = [e["to_state"] for e in entity_history.history("long_term_memory", "old1")]
        assert old_states[-1] == "conflict"


# ── (e) quota 只在新建分支记录 ───────────────────────────────────────


class TestQuotaOnlyOnCreate:
    def test_quota_span_recorded_only_for_create_branch(self, flow_db, mem_env,
                                                        monkeypatch):
        """计划 §5：quota 在 create 分支，不虚构为每次 merge 都执行。"""
        db = mem_env
        monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)
        monkeypatch.setattr(memory_manager, "MEMORY_USER_QUOTA", 1)
        monkeypatch.setattr(memory_manager, "MEMORY_QUOTA_ENFORCE", True)
        manager = memory_manager.MemoryManager()
        conn = sqlite3.connect(db)
        # 预置：旧记忆（相似命中 → merge 分支）+ 弱记忆（配额淘汰对象）
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
            "importance, confidence, status, confirmation_count, last_accessed_at) "
            "VALUES ('m-old', '1', '100', 'FACT', '他在杭州做后端开发', 0.5, 0.8, "
            "'active', 1, '2026-08-12 10:00:00')")
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
            "importance, confidence, status, confirmation_count, last_accessed_at) "
            "VALUES ('m-weak', '1', '100', 'FACT', '弱记忆', 0.1, 0.0, "
            "'active', 0, '2020-01-01 00:00:00')")
        conn.commit()
        conn.close()
        _insert_candidate(db, "ca", "他在杭州做后端开发", confidence=0.9)   # merge 分支
        _insert_candidate(db, "cb", "用户喜欢Helldivers2", confidence=0.9)  # create 分支

        manager.process_new_candidates()
        message_flow.flush()

        row = _latest_trace(flow_db, "memory_promotion")
        quota_spans = _spans(flow_db, row[0], node_id="memory.promotion.quota")
        merge_spans = _spans(flow_db, row[0], node_id="memory.promotion.merge")
        create_spans = _spans(flow_db, row[0], node_id="memory.promotion.create")
        assert len(merge_spans) == 1 and merge_spans[0].instance_key == "cand:ca"
        assert len(create_spans) == 1 and create_spans[0].instance_key == "cand:cb"
        # quota 只出现一次，且挂在新建候选实例上
        assert len(quota_spans) == 1
        assert quota_spans[0].instance_key == "cand:cb"
        # 配额真实执行：最弱的记忆被归档，履历记录 active→archived
        conn = sqlite3.connect(db)
        try:
            statuses = dict(conn.execute(
                "SELECT id, status FROM memories").fetchall())
        finally:
            conn.close()
        assert statuses["m-weak"] == "archived"
        archived = [h for h in entity_history.for_trace(row[0])
                    if h["entity_type"] == "long_term_memory"
                    and h["to_state"] == "archived"]
        assert archived


# ── (f) 旁路纪律 ─────────────────────────────────────────────────────


class TestProbeBypass:
    def test_probe_exceptions_never_break_promotion(self, flow_db, mem_env,
                                                    monkeypatch):
        """观测通道全挂 → 晋升结果不变、不上抛（计划 §6.3 旁路纪律）。"""
        from core.observability import message_flow as mf

        def boom(*args, **kwargs):
            raise RuntimeError("观测注入故障")

        monkeypatch.setattr(mf, "decision", boom)
        monkeypatch.setattr(mf, "span", boom)
        db = mem_env
        monkeypatch.setattr(memory_manager, "MEMORY_CONFIRM_HIGH_CONFIDENCE", 0.5)
        manager = memory_manager.MemoryManager()
        _insert_candidate(db, "c1", "高质量候选", confidence=0.9)

        manager.process_new_candidates()  # 不得抛

        conn = sqlite3.connect(db)
        try:
            cand = conn.execute(
                "SELECT status FROM memory_candidates WHERE id='c1'").fetchone()[0]
            mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        finally:
            conn.close()
        assert cand == "CONFIRMED"
        assert mem_count == 1
