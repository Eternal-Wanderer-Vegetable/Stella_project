from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import memory.memory_manager as memory_manager
from memory_rust.backend import PromotionRequest
from memory_rust.selector import BackendDecision


def _prepare_db(tmp_path: Path, monkeypatch) -> Path:
    db = tmp_path / "memory.db"
    monkeypatch.setattr(memory_manager, "DB_PATH", db)
    monkeypatch.setattr(
        memory_manager,
        "get_compressor",
        lambda: SimpleNamespace(maybe_compress=lambda reason=None: None),
    )
    memory_manager.MemoryManager()
    return db


def _seed(db: Path, candidate_id: str, *, confidence: float = 0.95) -> None:
    """Seed one candidate with an accepted source packet and active claim links."""
    from memory.evidence_contract import ASSESSMENT_VERSION, source_digest

    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT, "
        "source_kind TEXT, conversation_key TEXT, bot_id TEXT)"
    )
    group_id = "space"
    user_id = "100"
    content = "高质量候选"
    source_id = int(conn.execute(
        "SELECT COALESCE(MAX(id), 0) + 1 FROM group_messages"
    ).fetchone()[0])
    conversation_key = "qq:test-bot:group:space"
    owner_key = f"space:{group_id}"
    fact_key = f"claim:v1:{candidate_id}"
    snapshot = {
        "id": source_id,
        "group_id": group_id,
        "user_id": user_id,
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
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, importance, confidence, status, "
        "owner_type, owner_key, subject_key, audience, fact_key, source_conversation_key, "
        "source_message_ids) "
        "VALUES (?, ?, ?, 'FACT', ?, 0.8, ?, 'NEW', 'SPACE', ?, '', 'CURRENT_SPACE', ?, ?, ?)",
        (candidate_id, group_id, user_id, content, confidence, owner_key, fact_key,
         conversation_key, json.dumps([str(source_id)])),
    )
    conn.execute(
        "INSERT INTO group_messages "
        "(id, group_id, user_id, content, source_kind, conversation_key, bot_id) "
        "VALUES (?, ?, ?, ?, 'AT_MENTION', ?, 'test-bot')",
        (source_id, group_id, user_id, content, conversation_key),
    )
    evidence_id = f"evidence:{candidate_id}:{source_id}"
    conn.execute(
        "INSERT INTO memory_evidence "
        "(id, owner_type, owner_key, subject_key, audience, fact_key, "
        "source_conversation_key, source_row_id, candidate_id, fact_subject_key, "
        "source_digest, verification_status, provenance_json) "
        "VALUES (?, 'SPACE', ?, '', 'CURRENT_SPACE', ?, ?, ?, ?, ?, ?, 'accepted', ?)",
        (evidence_id, owner_key, fact_key, conversation_key, source_id, candidate_id,
         f"qq:{user_id}", digest,
         json.dumps(provenance, ensure_ascii=False, separators=(",", ":"))),
    )
    for entity_type, entity_id, projection_slot in (
        ("memory_candidate", candidate_id, "candidate"),
        ("claim_state", fact_key, "eligibility"),
    ):
        conn.execute(
            "INSERT INTO memory_claim_links "
            "(id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key, "
            "projection_slot, slot_digest, status) "
            "VALUES (?, ?, ?, 'CURRENT_SPACE', ?, ?, ?, ?, ?, 'active')",
            (f"link:{candidate_id}:{source_id}:{projection_slot}", evidence_id,
             owner_key, entity_type, entity_id, fact_key, projection_slot, digest),
        )
    conn.commit()
    conn.close()


def test_rust_promotion_receives_bounded_request_and_runs_hooks_once(tmp_path, monkeypatch):
    db = _prepare_db(tmp_path, monkeypatch)
    _seed(db, "c1")
    calls: list[PromotionRequest] = []
    history_calls: list[bool] = []
    compressor_calls: list[str | None] = []

    class FakeRustBackend:
        name = "rust"

        def promote(self, request):
            calls.append(request)
            conn = sqlite3.connect(request.db_path)
            conn.execute(
                "UPDATE memory_candidates SET status = 'CONFIRMED' WHERE id = ?",
                (request.candidate_id,),
            )
            conn.commit()
            conn.close()
            return {"promoted": True, "action": "create"}

    monkeypatch.setattr(
        "memory_rust.selector.resolve_backend",
        lambda mode: (BackendDecision(mode, "rust"), FakeRustBackend()),
    )
    monkeypatch.setattr(memory_manager, "bump_memory_history", lambda: history_calls.append(True))
    monkeypatch.setattr(
        memory_manager,
        "get_compressor",
        lambda: SimpleNamespace(
            maybe_compress=lambda reason=None: compressor_calls.append(reason)
        ),
    )
    monkeypatch.setenv("MEMORY_BACKEND", "rust")

    memory_manager.MemoryManager().process_new_candidates()

    assert len(calls) == 1
    request = calls[0]
    assert isinstance(request, PromotionRequest)
    assert request.db_path == db
    assert request.candidate_id == "c1"
    assert request.group_shared_space == "space"
    assert request.user_id == "100"
    assert request.memory_type == "FACT"
    assert history_calls == [True]
    assert compressor_calls == ["candidate_processed"]


def test_rust_promotion_keeps_observing_gate_in_python(tmp_path, monkeypatch):
    db = _prepare_db(tmp_path, monkeypatch)
    _seed(db, "c1", confidence=0.2)
    calls: list[str] = []

    class FakeRustBackend:
        name = "rust"

        def promote(self, request):
            calls.append(request.candidate_id)
            return {"promoted": True}

    monkeypatch.setattr(
        "memory_rust.selector.resolve_backend",
        lambda mode: (BackendDecision(mode, "rust"), FakeRustBackend()),
    )
    monkeypatch.setenv("MEMORY_BACKEND", "rust")

    memory_manager.MemoryManager().process_new_candidates()

    conn = sqlite3.connect(db)
    status = conn.execute(
        "SELECT status FROM memory_candidates WHERE id = 'c1'"
    ).fetchone()[0]
    conn.close()
    assert status == "OBSERVING"
    assert calls == []


def test_auto_falls_back_to_python_after_rust_runtime_failure(tmp_path, monkeypatch):
    db = _prepare_db(tmp_path, monkeypatch)
    _seed(db, "c1")
    python_calls: list[bool] = []

    class BrokenRustBackend:
        name = "rust"

        def promote(self, request):
            raise RuntimeError("native transaction failed")

    monkeypatch.setattr(
        "memory_rust.selector.resolve_backend",
        lambda mode: (BackendDecision(mode, "rust"), BrokenRustBackend()),
    )
    monkeypatch.setenv("MEMORY_BACKEND", "auto")
    manager = memory_manager.MemoryManager()
    monkeypatch.setattr(
        manager,
        "_process_new_candidates_python",
        lambda: python_calls.append(True),
    )

    manager.process_new_candidates()

    assert python_calls == [True]


def test_strict_rust_runtime_failure_is_not_swallowed(tmp_path, monkeypatch):
    db = _prepare_db(tmp_path, monkeypatch)
    _seed(db, "c1")
    python_calls: list[bool] = []

    class BrokenRustBackend:
        name = "rust"

        def promote(self, request):
            raise RuntimeError("native transaction failed")

    monkeypatch.setattr(
        "memory_rust.selector.resolve_backend",
        lambda mode: (BackendDecision(mode, "rust"), BrokenRustBackend()),
    )
    monkeypatch.setenv("MEMORY_BACKEND", "strict")
    manager = memory_manager.MemoryManager()
    monkeypatch.setattr(
        manager,
        "_process_new_candidates_python",
        lambda: python_calls.append(True),
    )

    with pytest.raises(RuntimeError, match="native transaction failed"):
        manager.process_new_candidates()

    assert python_calls == []
