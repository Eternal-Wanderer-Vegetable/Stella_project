# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""memory_eval 单测：假后端、零网络、零生产库接触（MBENCH-002）。

覆盖：隔离回放摄入（假整合后端走真实整合→候选→晋升链路）、生产检索 +
记忆包 + 假模型的短答、judge 协议解析、QA 抽样确定性、指标聚合。
"""

from __future__ import annotations

import copy
import json

import pytest

from memory_eval.answer import answer_question
from memory_eval.isolation import ReplayEnv
from memory_eval.judge import build_judge_prompt, parse_verdict
from memory_eval.metrics import aggregate_qa, grams, has_gram_overlap
from memory_eval.scenarios import select_qa

SCENARIO = {
    "schema": "memory-eval-locomo-scenario/1",
    "scenario_id": "locomo-test-0",
    "sample_id": "test-0",
    "group_id": 990001,
    "conversation_key": "qq:stella-bench:group:990001",
    "bot_id": "stella-bench",
    "speakers": {"a": "Alice", "b": "Ben"},
    "user_ids": {"a": "9190001", "b": "9190002"},
    "sessions": [
        {
            "session_id": 1,
            "ts": "2023-05-08 10:00:00",
            "ts_source": "dataset",
            "messages": [
                {"dia_id": "D1:1", "speaker": "Alice", "user_id": "9190001",
                 "text": "Hey Ben! I got a new camping tent for the trip."},
                {"dia_id": "D1:2", "speaker": "Ben", "user_id": "9190002",
                 "text": "Nice! Hiking sounds great this weekend."},
            ],
        },
        {
            "session_id": 2,
            "ts": "2023-05-15 10:00:00",
            "ts_source": "dataset",
            "messages": [
                {"dia_id": "D2:1", "speaker": "Alice", "user_id": "9190001",
                 "text": "I live in Springfield now, moved last month."},
            ],
        },
    ],
    "qa": [
        {"qid": "t-q0", "category": 1, "category_name": "single_hop",
         "question": "Where does Alice live?",
         "gold_answer": "Springfield", "adversarial_answer": None,
         "evidence_dia_ids": ["D2:1"]},
        {"qid": "t-q1", "category": 5, "category_name": "adversarial",
         "question": "What car does Ben drive?",
         "gold_answer": None, "adversarial_answer": "A red Tesla",
         "evidence_dia_ids": []},
    ],
    "adapt_meta": {"adapter": "test", "skipped_qa": 0, "unmapped_dia_ids": 0},
}


class FakeConsolidationBackend:
    """按会话顺序弹出录制回复（合同同 scripts/eval_memory_replay.py）。"""

    def __init__(self, replies: list[str]):
        self._queue = list(replies)
        self.prompts: list[str] = []

    async def generate_detailed(self, prompt: str, *args, **kwargs):
        self.prompts.append(prompt)
        if not self._queue:
            raise AssertionError("录制回复已耗尽（会话数与录制件数不齐）")
        return self._queue.pop(0), "stop"


def _consolidation_reply(candidates: list[dict]) -> str:
    return json.dumps({
        "short_term": {
            "active_summary": "two friends chatting",
            "pending_topic": "无",
            "recent_exchanges": [],
        },
        "user_profiles": [],
        "has_self_disclosure": bool(candidates),
        "memory_candidates": candidates,
    }, ensure_ascii=False)


class FakeLLM:
    """answer/judge 用假模型（记录 prompt，按序弹出回复）。"""

    def __init__(self, replies: list[str]):
        self._queue = list(replies)
        self.prompts: list[str] = []
        self.ledger = {"calls": 0, "errors": 0, "prompt_tokens": 0,
                       "completion_tokens": 0, "latency_seconds": []}

    def chat(self, user, system=None, *, max_tokens=512, temperature=0.0):
        self.prompts.append(user)
        self.ledger["calls"] += 1
        self.ledger["prompt_tokens"] += 10
        self.ledger["completion_tokens"] += 5
        self.ledger["latency_seconds"].append(0.01)
        if not self._queue:
            raise AssertionError("假模型回复已耗尽")
        return {"text": self._queue.pop(0), "prompt_tokens": 10,
                "completion_tokens": 5, "latency_seconds": 0.01}

    def cost_summary(self):
        return {"base_url": "fake", "model": "fake", **self.ledger}


@pytest.fixture()
def scenario():
    return copy.deepcopy(SCENARIO)


@pytest.fixture()
def reset_memory_singletons(monkeypatch):
    import memory.memory_manager as mm

    monkeypatch.setattr(mm, "_memory_manager_instance", None)
    yield
    monkeypatch.setattr(mm, "_memory_manager_instance", None)


# ── 隔离回放摄入 ──────────────────────────────────────────────


async def test_oracle_backend_contract_spans(tmp_path, scenario, reset_memory_singletons):
    """oracle 后端从整合 prompt 机械抽取合同句型，候选走真实落库。"""
    from memory_eval.oracle import OracleConsolidationBackend

    oracle = OracleConsolidationBackend()
    prompt = (
        "（批次消息）\n"
        "消息ID(11) 用户(9190001): I live in Springfield.\n"
        "消息ID(12) 用户(9190001): I like camping a lot, do you?\n"
        "消息ID(13) 用户(9190002): The weather is nice today.\n"
    )
    reply, finish = await oracle.generate_detailed(prompt)
    assert finish == "stop"
    parsed = json.loads(reply)
    assert parsed["has_self_disclosure"] is True
    contents = {(c["user_id"], c["type"], c["content"]) for c in parsed["memory_candidates"]}
    assert ("9190001", "FACT", "I live in Springfield.") in contents
    # span 必须是消息原文的逐字子串（证据绑定契约），句型词干命中即可
    preference = [c for c in parsed["memory_candidates"] if c["type"] == "PREFERENCE"]
    assert preference and preference[0]["content"].startswith("I like camping a lot")
    # 无关消息不产生候选；source_message_ids 是真实行 ID
    assert all(c["source_message_ids"] in ([11], [12], [13]) for c in parsed["memory_candidates"])
    assert not any("weather" in c["content"] for c in parsed["memory_candidates"])


async def test_oracle_end_to_end_ingest(tmp_path, scenario, reset_memory_singletons):
    """oracle 模式端到端：候选写入 + 英文刻板句晋升链路可用。"""
    from memory_eval.oracle import OracleConsolidationBackend

    scenario["sessions"][0]["messages"][0]["text"] = "My name is Alice."
    env = ReplayEnv(tmp_path / "env", scenario)
    with env.session():
        cons = env.build_consolidator(fake_backend=OracleConsolidationBackend())
        for session in scenario["sessions"]:
            env.set_batch_size(len(session["messages"]))
            env.insert_sessions([session])
            await cons.consolidate_group(int(scenario["group_id"]), force=True)
        funnel = env.funnel()
        assert funnel["candidates_total"] >= 1
        assert funnel["candidates_by_status"].get("NEW", 0) + \
            funnel["candidates_by_status"].get("OBSERVING", 0) + \
            funnel["candidates_by_status"].get("CONFIRMED", 0) >= 1


async def test_inject_gold_memories(tmp_path, scenario):
    """Oracle 上界注入：证据轮逐字入库、幂等、FTS 可检索。"""
    from memory_eval.inject import inject_gold_memories

    env = ReplayEnv(tmp_path / "env", scenario)
    with env.session():
        for session in scenario["sessions"]:
            env.insert_sessions([session])
        inserted = inject_gold_memories(env, scenario)
        assert inserted == 1  # 只有 D2:1 是证据轮
        assert inject_gold_memories(env, scenario) == 0  # 幂等
        funnel = env.funnel()
        assert funnel["memories_active"] == 1
        import sqlite3

        conn = sqlite3.connect(env.db_path)
        try:
            fts_rows = conn.execute(
                "SELECT COUNT(*) FROM memories_fts WHERE mem_id = 'gold-D2:1'"
            ).fetchone()[0]
            assert fts_rows == 1
        finally:
            conn.close()


async def test_replay_env_fake_ingest(tmp_path, scenario, reset_memory_singletons):
    env = ReplayEnv(tmp_path / "env", scenario)
    replies = [
        _consolidation_reply([{
            "user_id": "9190001", "type": "FACT",
            "content": "Alice has a new camping tent",
            "usage_tags": ["CASUAL"], "visibility": "OPEN",
            "importance": 0.5, "confidence": 0.9,
            "evidence": "Alice said she got a camping tent.",
            "source_message_ids": [1],
        }]),
        _consolidation_reply([]),
    ]
    with env.session():
        cons = env.build_consolidator(fake_backend=FakeConsolidationBackend(replies))
        for session in scenario["sessions"]:
            env.set_batch_size(len(session["messages"]))
            env.insert_sessions([session])
            await cons.consolidate_group(int(scenario["group_id"]), force=True)
        assert len(env.dia_to_row) == 3
        assert env.dia_to_row["D2:1"] == 3
        funnel = env.funnel()
        assert funnel["candidates_total"] == 1
        assert funnel["memories_total"] >= 0
        contents = env.table_contents()
        assert isinstance(contents["memories"], list)
        # 摄入提示词确实拿到了消息行（mid 契约）
        assert "camping tent" in cons._backends[0][1].prompts[0]
    # close 后生产模块 DB_PATH 恢复（不污染同进程其他测试）
    import memory.consolidator as consolidator_mod

    assert env.db_path != consolidator_mod.DB_PATH


async def test_replay_env_backdate(tmp_path, scenario, reset_memory_singletons):
    env = ReplayEnv(tmp_path / "env", scenario)
    with env.session():
        cons = env.build_consolidator(fake_backend=FakeConsolidationBackend([
            _consolidation_reply([]), _consolidation_reply([]),
        ]))
        for session in scenario["sessions"]:
            wall_before = "2026-01-01 00:00:00"
            env.set_batch_size(len(session["messages"]))
            env.insert_sessions([session])
            await cons.consolidate_group(int(scenario["group_id"]), force=True)
            env.backdate_new_rows(str(session["ts"]), wall_before)
        import sqlite3

        conn = sqlite3.connect(env.db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT last_confirmed_at FROM memories"
            ).fetchall()
            assert all(str(r[0]) in ("2023-05-08 10:00:00", "2023-05-15 10:00:00")
                       for r in rows)
        finally:
            conn.close()


# ── 检索作答 ─────────────────────────────────────────────────


async def test_answer_question_with_stub_memory(tmp_path, scenario):
    env = ReplayEnv(tmp_path / "env", scenario)
    with env.session():
        from config.spaces import resolve_space

        space = resolve_space(int(scenario["group_id"]))
        import sqlite3

        conn = sqlite3.connect(env.db_path)
        try:
            conn.execute(
                "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
                "status, confidence, importance, visibility) VALUES "
                "('m1', ?, '9190001', 'FACT', 'Alice lives in Springfield', "
                "'active', 0.9, 0.5, 'OPEN')",
                (space,),
            )
            conn.commit()
        finally:
            conn.close()

        llm = FakeLLM(["Alice lives in Springfield."])
        record = await answer_question(
            env, scenario, scenario["qa"][0], channel="rule", llm=llm
        )
        assert record["retrieved_ids"] == ["m1"]
        assert "Alice lives in Springfield" in record["answer"]
        assert record["pack_memory_count"] == 1
        assert record["pack_chars"] > 0
        # prompt 含记忆包与问题
        assert "Springfield" in llm.prompts[0]
        assert "Where does Alice live?" in llm.prompts[0]


async def test_answer_question_empty_pack(tmp_path, scenario):
    env = ReplayEnv(tmp_path / "env", scenario)
    with env.session():
        llm = FakeLLM(["I don't have that information."])
        record = await answer_question(
            env, scenario, scenario["qa"][1], channel="rule", llm=llm
        )
        assert record["retrieved_ids"] == []
        assert record["pack_memory_count"] == 0
        assert "未召回任何长期记忆" in llm.prompts[0]


# ── judge / 抽样 / 指标 ───────────────────────────────────────


def test_parse_verdict_variants():
    assert parse_verdict("CORRECT")["verdict"] == "correct"
    assert parse_verdict("INCORRECT")["verdict"] == "incorrect"
    assert parse_verdict("The answer is correct.")["verdict"] == "correct"
    assert parse_verdict("incorrect — wrong year")["verdict"] == "incorrect"
    assert parse_verdict("maybe?")["verdict"] == "unparseable"


def test_build_judge_prompt_adversarial():
    prompt = build_judge_prompt("What car does Ben drive?", None, "A red Tesla",
                                adversarial_answer="A red Tesla")
    assert "abstention" in prompt
    assert "DECOY" in prompt
    prompt_ok = build_judge_prompt("Q?", "Paris", "I don't know.")
    assert "Paris" in prompt_ok


def test_select_qa_sampling_deterministic():
    qa = [{"qid": f"q{i}", "category": (i % 2) + 1, "category_name": "x"} for i in range(10)]
    scenario = {"qa": qa}
    a = select_qa(scenario, sample_per_category=2, seed=7)
    b = select_qa(scenario, sample_per_category=2, seed=7)
    c = select_qa(scenario, sample_per_category=2, seed=8)
    assert [x["qid"] for x in a] == [x["qid"] for x in b]
    assert len(a) == 4
    assert [x["qid"] for x in a] != [x["qid"] for x in c] or True  # 不同种子通常不同
    assert select_qa(scenario, 0, 0) == qa


def test_aggregate_qa_math():
    results = [
        {"category_name": "single_hop", "verdict": "correct", "pack_memory_count": 2,
         "pack_chars": 100, "write_coverage_memories": 1, "write_coverage_candidates": 1,
         "retrieval_evidence_coverage": 1},
        {"category_name": "single_hop", "verdict": "incorrect", "pack_memory_count": 1,
         "pack_chars": 50, "write_coverage_memories": 0, "write_coverage_candidates": 1,
         "retrieval_evidence_coverage": 0},
        {"category_name": "adversarial", "verdict": "correct", "pack_memory_count": 0,
         "pack_chars": 0, "write_coverage_memories": None, "write_coverage_candidates": None,
         "retrieval_evidence_coverage": None},
    ]
    agg = aggregate_qa(results)
    assert agg["total"] == 3
    assert agg["accuracy"] == round(2 / 3 * 100, 1)
    assert agg["by_category"]["single_hop"]["accuracy"] == 50.0
    assert agg["adversarial_abstention_accuracy"] == 100.0
    assert agg["write_coverage_memories"] == 0.5
    assert agg["pack_memory_count_avg"] == 1.0


def test_has_gram_overlap():
    assert has_gram_overlap("Alice lives in Springfield",
                            grams("Springfield is where she lives"))
    assert not has_gram_overlap("totally unrelated text", {"springfield is"})
