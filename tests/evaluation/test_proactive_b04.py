# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""B04 isolated ingress, exact lineage, lifecycle, and resume-contract checks."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from memory_eval.b04 import (
    BudgetedBackend,
    BudgetedEmbeddingService,
    BudgetedEvalLLM,
    BudgetExceededError,
    RunBudget,
    _apply_memory_backend_overrides,
    _check_resume,
    _ensure_capture_gate_open,
    _json_digest,
    _memory_backend_base_url,
    _memory_backend_identity,
    _memory_backend_overrides,
    _select_qa_plan,
    _select_scenarios,
)
from memory_eval.b04_ingress import ProductionReplayEnv
from memory_eval.b04_lineage import build_lineage, retrieval_source_alignment
from memory_eval.isolation import ensure_eval_home

SCENARIO = {
    "schema": "memory-eval-locomo-scenario/1",
    "scenario_id": "locomo-b04-test",
    "group_id": 990091,
    "conversation_key": "qq:stella-bench:group:990091",
    "bot_id": "stella-bench",
    "sessions": [
        {
            "session_id": 1,
            "ts": "2024-01-01 10:00:00",
            "messages": [
                {"dia_id": "B04:1", "user_id": "u1", "text": "I prefer tea."},
                {"dia_id": "B04:2", "user_id": "u2", "text": "/skip this command"},
            ],
        }
    ],
}


def test_qa_sampling_is_deterministic_per_category_across_scenarios():
    scenarios = [
        {
            "scenario_id": "locomo-a",
            "qa": [
                {"qid": f"a-{category}-{index}", "category": category}
                for category in (1, 2)
                for index in range(2)
            ],
        },
        {
            "scenario_id": "locomo-b",
            "qa": [
                {"qid": f"b-{category}-{index}", "category": category}
                for category in (1, 2)
                for index in range(2)
            ],
        },
    ]

    first = _select_qa_plan(scenarios, sample_per_category=1, seed=42)
    second = _select_qa_plan(scenarios, sample_per_category=1, seed=42)
    selected = [row for rows in first.values() for row in rows]

    assert first == second
    assert len(selected) == 2
    assert sorted(row["category"] for row in selected) == [1, 2]
    assert sum(map(len, _select_qa_plan(scenarios, 0, 42).values())) == 8


def test_scenario_range_selects_offset_after_loading_the_catalog():
    scenarios = [{"scenario_id": f"locomo-{index}"} for index in range(1, 5)]

    selected = _select_scenarios(scenarios, count=2, start=2)

    assert [scenario["scenario_id"] for scenario in selected] == ["locomo-2", "locomo-3"]
    with pytest.raises(ValueError, match="at least 1"):
        _select_scenarios(scenarios, count=1, start=0)


def test_memory_backend_url_normalizes_v1_suffix_for_production_backend():
    assert _memory_backend_base_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234"
    assert _memory_backend_base_url("https://model.example/proxy/v1/") == "https://model.example/proxy"
    assert _memory_backend_base_url("http://127.0.0.1:1234") == "http://127.0.0.1:1234"


def test_memory_backend_configuration_is_explicit_and_secret_safe(monkeypatch):
    args = SimpleNamespace(
        memory_base_url="http://127.0.0.1:1234/v1",
        memory_model="memory-model-test",
        memory_kind="online",
        memory_api_key="do-not-report-this-key",
        max_consolidation_tokens=777,
        max_extract_tokens=555,
    )
    overrides = _memory_backend_overrides(args)
    identity = _memory_backend_identity(args)

    assert overrides["LLM_ENDPOINT_MEMORY_BASE_URL"] == "http://127.0.0.1:1234"
    assert overrides["LLM_ROLE_CONSOLIDATION_MODEL"] == "memory-model-test"
    assert overrides["LLM_ROLE_EXTRACT_MODEL"] == "memory-model-test"
    assert overrides["LLM_ROLE_CONSOLIDATION_MAX_TOKENS"] == "777"
    assert overrides["LLM_ROLE_EXTRACT_MAX_TOKENS"] == "555"
    assert overrides["LLM_FALLBACK_ENABLED"] == "false"
    assert identity["api_key_configured"] is True
    assert "do-not-report-this-key" not in json.dumps(identity)

    for key in overrides:
        monkeypatch.setitem(os.environ, key, os.environ.get(key, ""))
    settings = SimpleNamespace()
    reset_state = Mock()
    monkeypatch.setitem(sys.modules, "config.settings", settings)
    monkeypatch.setitem(sys.modules, "core.llm.registry", SimpleNamespace(reset_state=reset_state))

    _apply_memory_backend_overrides(overrides)

    assert os.environ["LLM_ENDPOINT_MEMORY_BASE_URL"] == "http://127.0.0.1:1234"
    assert settings.LLM_ENDPOINT_MEMORY_BASE_URL == "http://127.0.0.1:1234"
    assert settings.LLM_ENDPOINT_MEMORY_API_KEY == "do-not-report-this-key"
    assert settings.LLM_ROLE_CONSOLIDATION_MAX_TOKENS == 777
    assert pytest.approx(0.2) == settings.LLM_ROLE_EXTRACT_TEMPERATURE
    assert settings.LLM_FALLBACK_ENABLED is False
    reset_state.assert_called_once_with()


@pytest.mark.asyncio
async def test_capture_gate_lease_renewal_is_budgeted_and_checkpointed(tmp_path):
    class FakeGate:
        allowed = False

        def capture_allowed(self):
            return self.allowed

        def status_snapshot(self):
            return {
                "state": "ready" if self.allowed else "unavailable",
                "allowed": self.allowed,
                "last_probe_at": "2026-11-05T00:00:00+00:00",
                "last_success_at": "2026-11-05T00:00:00+00:00" if self.allowed else "",
                "error_category": "" if self.allowed else "lease_expired",
                "next_retry_in_seconds": 0,
            }

        def decision(self):
            return SimpleNamespace(reason_code="lease_expired")

    class FakeEnv:
        def __init__(self):
            self.capture_gate = FakeGate()
            self.probe_calls = 0
            self.probe_results = [False, True, True]

        async def open_capture_gate(self):
            self.probe_calls += 1
            result = self.probe_results.pop(0)
            self.capture_gate.allowed = result
            return result

    env = FakeEnv()
    budget = RunBudget(max_calls=3, max_seconds=10)
    meta = {"capture_gates": {}}

    first = await _ensure_capture_gate_open(env, tmp_path, "production/test", meta, budget)
    assert first["allowed"] is True
    assert first["probe_count"] == 2
    env.capture_gate.allowed = False
    second = await _ensure_capture_gate_open(env, tmp_path, "production/test", meta, budget)

    assert second["allowed"] is True
    assert second["probe_count"] == 3
    assert second["renewal_policy"] == "explicit_before_fixture_session_ingress"
    assert env.probe_calls == 3
    assert [call["role"] for call in budget.calls] == ["capture_gate_probe"] * 3
    assert len(meta["capture_gates"]["production/test"]["probe_history"]) == 3


def test_budgeted_eval_llm_clamps_tokens_and_reserves_calls():
    class FakeLLM:
        timeout = 0

        def chat(self, *_args, **kwargs):
            self.max_tokens = kwargs["max_tokens"]
            self.reasoning_effort = kwargs.get("reasoning_effort")
            return {"text": "ok"}

    budget = RunBudget(max_calls=1, max_seconds=10)
    inner = FakeLLM()
    llm = BudgetedEvalLLM(inner, budget, "answer", max_tokens=32, reasoning_effort="none")

    assert llm.chat("prompt", max_tokens=2048)["text"] == "ok"
    assert inner.max_tokens == 32
    assert inner.reasoning_effort == "none"
    with pytest.raises(BudgetExceededError, match="call budget"):
        llm.chat("second prompt", max_tokens=8)


@pytest.mark.asyncio
async def test_budgeted_backend_meters_role_endpoint_attempts():
    class FakeEndpoint:
        slot = "MEMORY"

        async def generate_single_attempt(self, prompt, system_prompt=""):
            return "reply", "stop"

    class FakeRoleBackend:
        primary = "primary-marker"
        fallback = None

        def attempt_plan(self):
            return FakeEndpoint(), False

        def record_attempt_result(self, endpoint, error):
            return endpoint is self.primary

    budget = RunBudget(max_calls=1, max_seconds=10)
    backend = BudgetedBackend(FakeRoleBackend(), budget, "consolidation:live")

    endpoint, degraded = backend.attempt_plan()
    assert degraded is False
    assert await endpoint.generate_single_attempt("p", "s") == ("reply", "stop")
    with pytest.raises(BudgetExceededError, match="call budget"):
        await endpoint.generate_single_attempt("p", "s")
    assert [call["role"] for call in budget.calls] == ["consolidation:live"]
    assert backend.record_attempt_result(endpoint, RuntimeError("x")) is False
    assert backend.record_attempt_result(
        SimpleNamespace(_inner="primary-marker"), RuntimeError("x")
    ) is True


@pytest.mark.asyncio
async def test_budgeted_embedding_service_counts_and_caches_requests(monkeypatch):
    from mneme.embeddings import EmbeddingService

    async def fake_request(self, _base_url, _model, _text):
        return [1.0, 0.0]

    monkeypatch.setattr(EmbeddingService, "_request_embedding", fake_request)
    budget = RunBudget(max_calls=2, max_seconds=10)
    service = BudgetedEmbeddingService("http://127.0.0.1:1234", "embedding-test", budget)

    assert await service.similarity("question", "memory") == pytest.approx(1.0)
    assert await service.similarity("question", "memory") == pytest.approx(1.0)
    assert len(budget.calls) == 2
    assert all(call["role"] == "embedding" for call in budget.calls)
    assert service.summary()["api_calls"] == 2
    assert service.summary()["api_failures"] == 0


@pytest.mark.asyncio
async def test_budgeted_embedding_service_fails_closed_at_call_budget(monkeypatch):
    from mneme.embeddings import EmbeddingService

    async def fake_request(self, _base_url, _model, _text):
        return [1.0, 0.0]

    monkeypatch.setattr(EmbeddingService, "_request_embedding", fake_request)
    budget = RunBudget(max_calls=1, max_seconds=10)
    service = BudgetedEmbeddingService("http://127.0.0.1:1234", "embedding-test", budget)

    with pytest.raises(BudgetExceededError, match="call budget"):
        await service.similarity("question", "memory")

    assert len(budget.calls) == 1
    assert budget.calls[0]["role"] == "embedding"
    assert service.summary()["budget_exhausted"] is True


@pytest.mark.asyncio
async def test_budgeted_embedding_service_does_not_start_fallback(monkeypatch):
    import sys
    from unittest.mock import Mock

    from mneme.embeddings import EmbeddingService

    async def failed_request(self, _base_url, _model, _text):
        raise OSError("embedding endpoint unavailable")

    fallback = Mock()
    fallback.ensure_local_embedding_service = Mock(
        side_effect=AssertionError("B04 must not auto-start embedding services")
    )
    monkeypatch.setitem(sys.modules, "deploy.llama", fallback)
    monkeypatch.setattr(EmbeddingService, "_request_embedding", failed_request)
    budget = RunBudget(max_calls=4, max_seconds=10)
    service = BudgetedEmbeddingService("http://127.0.0.1:1234", "embedding-test", budget)

    assert await service.similarity("question", "memory") is None
    assert service.summary()["api_calls"] == 2
    assert service.summary()["api_failures"] == 2
    fallback.ensure_local_embedding_service.assert_not_called()


def _restore_env(workdir: Path):
    old_home = os.environ.get("STELLA_HOME")
    old_db = os.environ.get("DB_PATH")
    ensure_eval_home(workdir)

    def restore():
        if old_home is None:
            os.environ.pop("STELLA_HOME", None)
        else:
            os.environ["STELLA_HOME"] = old_home
        if old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = old_db

    return restore


@pytest.mark.asyncio
async def test_production_track_uses_admission_capture_and_idempotent_transport_events(tmp_path):
    restore = _restore_env(tmp_path)
    async def ready_probe():
        return True, ""

    env = ProductionReplayEnv(tmp_path / "prod", SCENARIO, capture_probe=ready_probe)
    import mneme.consolidator as consolidator

    threshold_names = (
        "CONSOLIDATION_LOCAL_BATCH_SIZE",
        "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE",
        "CONSOLIDATION_ONLINE_BATCH_SIZE",
        "CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE",
    )
    before = {name: getattr(consolidator, name) for name in threshold_names}
    try:
        with env.session():
            assert {name: getattr(consolidator, name) for name in threshold_names} == before
            assert await env.open_capture_gate() is True
            first = await env.record_fixture_session(SCENARIO["sessions"][0])
            second = await env.record_fixture_session(SCENARIO["sessions"][0])
            assert first == second
            assert set(first) == {"B04:1"}
            assert env.admission_counts == {"allowed": 2, "denied": 2}

            conn = sqlite3.connect(env.db_path)
            try:
                from mneme.schema import (
                    create_memory_claim_links_table,
                    create_memory_evidence_table,
                )

                create_memory_evidence_table(conn)
                create_memory_claim_links_table(conn)
                rows = conn.execute(
                    "SELECT id, content FROM group_messages WHERE platform_message_id = 'B04:1'"
                ).fetchall()
                assert len(rows) == 1
                source_row_id = int(rows[0][0])
                conn.execute(
                    "INSERT INTO memory_evidence (id, owner_type, owner_key, subject_key, audience, "
                    "fact_key, source_conversation_key, source_row_id, candidate_id, source_digest, "
                    "verification_status, provenance_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("e1", "SPACE", "990091", "", "CURRENT_SPACE", "pref:tea",
                     SCENARIO["conversation_key"], source_row_id, "c1", "digest-1", "accepted", "{}"),
                )
                conn.execute(
                    "INSERT INTO memory_candidates (id, group_shared_space, user_id, type, content, "
                    "status, source_message_ids, owner_type, owner_key, subject_key, audience, "
                    "source_conversation_key, fact_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("c1", "990091", "u1", "PREFERENCE", "I prefer tea.", "OBSERVING",
                     json.dumps([source_row_id]), "SPACE", "990091", "", "CURRENT_SPACE",
                     SCENARIO["conversation_key"], "pref:tea"),
                )
                conn.execute(
                    "INSERT INTO memory_claim_links (id, evidence_id, owner_key, audience, entity_type, "
                    "entity_id, claim_key, projection_slot, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    ("l1", "e1", "990091", "CURRENT_SPACE", "memory", "m1", "pref:tea", "content", "active"),
                )
                conn.commit()
            finally:
                conn.close()

            lineage = build_lineage(env.db_path)
            assert lineage["counts"]["sources_with_candidates"] == 1
            assert lineage["counts"]["sources_with_evidence"] == 1
            aligned = retrieval_source_alignment(lineage, ["m1"], ["B04:1"])
            assert aligned["gold_source_alignment"] == "aligned"
            assert aligned["answer_support_status"] == "ALIGNMENT_UNRESOLVED"

            edited_session = {
                "session_id": 2,
                "ts": "2024-01-01 10:05:00",
                "messages": [
                    {"dia_id": "B04:1", "user_id": "u1", "text": "I prefer coffee."}
                ],
            }
            edited = await env.record_fixture_session(
                edited_session,
                event_kind="edit",
                platform_revision_id="B04:1-revision-2",
            )
            assert edited["B04:1"] != source_row_id
            lineage = build_lineage(env.db_path)
            old_source = next(
                row for row in lineage["sources"] if row["source_row_id"] == source_row_id
            )
            assert old_source["source_state"] == "superseded"
            assert old_source["source_effective"] is False
            assert lineage["counts"]["active_claim_links_with_noncurrent_sources"] == 1
            aligned_after_edit = retrieval_source_alignment(lineage, ["m1"], ["B04:1"])
            assert aligned_after_edit["gold_source_alignment"] == "ALIGNMENT_UNRESOLVED"

            deleted = await env.record_source_deletion("B04:1")
            assert deleted == source_row_id
            conn = sqlite3.connect(env.db_path)
            try:
                status = conn.execute(
                    "SELECT verification_status FROM memory_evidence WHERE id = 'e1'"
                ).fetchone()[0]
                assert status == "source_unavailable"
            finally:
                conn.close()

            await env.capture_gate.stop()
            with pytest.raises(RuntimeError, match="capture gate closed"):
                await env.record_fixture_session(SCENARIO["sessions"][0])
    finally:
        env.close()
        restore()


def test_expired_observing_candidate_is_rejected_by_memory_manager(tmp_path):
    restore = _restore_env(tmp_path)
    try:
        from mneme.memory_manager import MemoryManager
        from mneme.schema import MEMORY_CANDIDATES_TABLE_DDL

        db = tmp_path / "expired.db"
        conn = sqlite3.connect(db)
        try:
            conn.execute(MEMORY_CANDIDATES_TABLE_DDL)
            conn.execute(
                "INSERT INTO memory_candidates (id, type, status, first_seen_at) VALUES (?, ?, ?, ?)",
                ("stale-event", "EVENT", "OBSERVING", "2000-01-01 00:00:00"),
            )
            manager = MemoryManager.__new__(MemoryManager)
            rejected = manager._reject_stale_candidates(conn.cursor())
            conn.commit()
            status = conn.execute(
                "SELECT status FROM memory_candidates WHERE id = 'stale-event'"
            ).fetchone()[0]
            assert rejected == 1
            assert status == "REJECTED"
        finally:
            conn.close()
    finally:
        restore()


def test_resume_fingerprint_requires_schema_match_and_exact_identity(tmp_path):
    fingerprint = _json_digest({"dataset": "locomo", "revision": "fixed"})
    initial = _check_resume(tmp_path / "run", fingerprint, resume=False)
    assert initial["schema"] == "memory-eval-resume/2"
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "meta.json").write_text(json.dumps(initial), encoding="utf-8")
    assert _check_resume(tmp_path / "run", fingerprint, resume=True)["fingerprint"] == fingerprint
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        _check_resume(tmp_path / "run", _json_digest({"dataset": "locomo", "revision": "other"}), resume=True)

