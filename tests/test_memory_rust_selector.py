from __future__ import annotations

from types import SimpleNamespace

import pytest

from memory_rust.backend import (
    BACKEND_API_VERSION,
    MEMORY_SCHEMA_VERSION,
    BackendContractError,
    BackendUnavailable,
)
from memory_rust.python_backend import PythonMemoryBackend
from memory_rust.selector import get_backend, select_backend


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
