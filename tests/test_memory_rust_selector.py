from __future__ import annotations

from types import SimpleNamespace

import pytest

import memory.retrieval_v2 as retrieval_v2
from memory_rust.backend import (
    BACKEND_API_VERSION,
    MEMORY_SCHEMA_VERSION,
    BackendContractError,
    BackendUnavailable,
)
from memory_rust.python_backend import PythonMemoryBackend
from memory_rust.selector import BackendDecision, get_backend, select_backend


def _native(**overrides):
    values = {
        "BACKEND_API_VERSION": BACKEND_API_VERSION,
        "MEMORY_SCHEMA_VERSION": MEMORY_SCHEMA_VERSION,
        "retrieve": lambda request: request,
        "promote": lambda manager: manager,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_python_is_the_default_backend(monkeypatch):
    monkeypatch.delenv("MEMORY_BACKEND", raising=False)

    decision = select_backend()
    backend = get_backend()

    assert decision.selected == "python"
    assert backend.name == "python"
    assert isinstance(backend, PythonMemoryBackend)


def test_auto_falls_back_when_native_extension_is_missing():
    def missing():
        raise BackendUnavailable("missing")

    decision = select_backend("auto", native_loader=missing)
    backend = get_backend("auto", native_loader=missing)

    assert decision.selected == "python"
    assert decision.fallback_reason == "missing"
    assert backend.name == "python"


def test_shadow_falls_back_but_retains_shadow_intent():
    def missing():
        raise BackendUnavailable("missing")

    decision = select_backend("shadow", native_loader=missing)

    assert decision.selected == "python"
    assert decision.shadow is True
    assert decision.fallback_reason == "missing"


def test_strict_exposes_native_failure():
    def missing():
        raise BackendUnavailable("missing")

    with pytest.raises(BackendUnavailable, match="missing"):
        get_backend("strict", native_loader=missing)


def test_rust_requires_matching_contract():
    def incompatible():
        return _native(MEMORY_SCHEMA_VERSION=13)

    with pytest.raises(BackendContractError, match="schema mismatch"):
        get_backend("rust", native_loader=incompatible)


def test_invalid_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "sideways")

    with pytest.raises(ValueError, match="invalid MEMORY_BACKEND"):
        select_backend()


def _retrieval_db(path):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
            user_id TEXT,
            type TEXT,
            content TEXT,
            importance REAL,
            confidence REAL,
            status TEXT,
            usage_tags TEXT,
            visibility TEXT,
            trigger_data TEXT,
            behavior_rule TEXT,
            last_accessed_at TEXT,
            last_confirmed_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO memories (
            id, group_shared_space, user_id, type, content, importance, confidence,
            status, usage_tags, visibility, last_accessed_at
        ) VALUES ('python', 'space', '1', 'PREFERENCE', '用户喜欢游戏', .8, .9,
                  'active', '["TOPIC_CONTINUE"]', 'OPEN', '2026-09-01 00:00:00')
        """
    )
    conn.commit()
    conn.close()


def test_shadow_returns_python_result_and_attaches_parity_report(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    _retrieval_db(db_path)
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    monkeypatch.setenv("MEMORY_BACKEND", "shadow")

    rust_result = retrieval_v2.RetrievalResult(
        mode="CASUAL_REPLY",
        conversation_memories=[],
        behavior_constraints=[],
        trace={},
    )
    fake_backend = SimpleNamespace(retrieve=lambda request: rust_result)
    monkeypatch.setattr(
        "memory_rust.selector.resolve_backend",
        lambda: (
            BackendDecision("shadow", "rust", shadow=True),
            fake_backend,
        ),
    )

    result = retrieval_v2.retrieve_memories("space", 1, "喜欢什么游戏")

    assert [item["id"] for item in result.conversation_memories] == ["python"]
    assert result.trace["rust_shadow"]["match"] is False
    assert result.trace["rust_shadow"]["rust_ids"] == []


def test_auto_falls_back_after_native_runtime_error(tmp_path, monkeypatch):
    db_path = tmp_path / "memory.db"
    _retrieval_db(db_path)
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    monkeypatch.setenv("MEMORY_BACKEND", "auto")

    class BrokenBackend:
        def retrieve(self, request):
            raise RuntimeError("native query failed")

    monkeypatch.setattr(
        "memory_rust.selector.resolve_backend",
        lambda: (BackendDecision("auto", "rust"), BrokenBackend()),
    )

    result = retrieval_v2.retrieve_memories("space", 1, "喜欢什么游戏")

    assert [item["id"] for item in result.conversation_memories] == ["python"]
