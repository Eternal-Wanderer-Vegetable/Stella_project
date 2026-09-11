from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

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
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, importance, confidence, status) "
        "VALUES (?, 'space', '100', 'FACT', '高质量候选', 0.8, ?, 'NEW')",
        (candidate_id, confidence),
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
