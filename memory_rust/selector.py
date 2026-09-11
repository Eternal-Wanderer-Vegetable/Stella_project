# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Select the optional Rust backend without changing Python defaults."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

from memory_rust.backend import (
    BACKEND_API_VERSION,
    MEMORY_SCHEMA_VERSION,
    BackendContractError,
    BackendUnavailable,
    MemoryBackend,
    PromotionRequest,
)
from memory_rust.python_backend import python_backend

_VALID_MODES = frozenset({"python", "rust", "auto", "shadow", "strict"})
_NATIVE_MODULE = "memory_rust._native"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class BackendDecision:
    """The resolved mode and the reason a fallback was taken, if any."""

    requested: str
    selected: str
    shadow: bool = False
    strict: bool = False
    fallback_reason: str | None = None


def configured_mode() -> str:
    """Read and validate the backend mode from the environment."""

    value = os.getenv("MEMORY_BACKEND", "").strip().lower()
    if not value:
        if _env_flag("MEMORY_RUST_STRICT"):
            value = "strict"
        elif _env_flag("MEMORY_RUST_SHADOW"):
            value = "shadow"
        else:
            value = "python"
    if value not in _VALID_MODES:
        raise ValueError(
            f"invalid MEMORY_BACKEND={value!r}; expected one of "
            f"{', '.join(sorted(_VALID_MODES))}"
        )
    return value


def _env_flag(name: str) -> bool:
    """Interpret the legacy boolean rollout flags without truthiness surprises."""

    return os.getenv(name, "").strip().lower() in _TRUE_VALUES


def _load_native() -> ModuleType:
    try:
        return importlib.import_module(_NATIVE_MODULE)
    except (ImportError, OSError) as exc:
        raise BackendUnavailable(
            "Rust memory extension is not installed or could not be loaded"
        ) from exc


def _validate_native(native: ModuleType) -> None:
    api_version = getattr(native, "BACKEND_API_VERSION", None)
    schema_version = getattr(native, "MEMORY_SCHEMA_VERSION", None)
    if api_version != BACKEND_API_VERSION:
        raise BackendContractError(
            f"Rust memory API mismatch: expected {BACKEND_API_VERSION}, "
            f"got {api_version!r}"
        )
    if schema_version != MEMORY_SCHEMA_VERSION:
        raise BackendContractError(
            f"Rust memory schema mismatch: expected {MEMORY_SCHEMA_VERSION}, "
            f"got {schema_version!r}"
        )


class RustMemoryBackend:
    """Lazy adapter for the PyO3 native module."""

    name = "rust"
    api_version = BACKEND_API_VERSION
    schema_version = MEMORY_SCHEMA_VERSION

    def __init__(self, native: ModuleType):
        _validate_native(native)
        self._native = native

    def retrieve(self, request):
        payload = {
            "db_path": str(request.db_path),
            "group_shared_space": request.group_shared_space,
            "user_id": request.user_id,
            "query": request.query,
            "trigger": request.trigger,
            "mode": request.mode,
            "pool_limit": request.pool_limit,
            "semantic_scores": dict(request.semantic_scores or {}),
        }
        raw = self._native.retrieve(json.dumps(payload, ensure_ascii=False))
        if isinstance(raw, str):
            raw = json.loads(raw)
        from memory.retrieval_v2 import RetrievalResult

        return RetrievalResult(**raw)

    def promote(self, request: PromotionRequest):
        payload = {
            "db_path": str(request.db_path),
            "candidate_id": request.candidate_id,
            "group_shared_space": request.group_shared_space,
            "user_id": request.user_id,
            "memory_type": request.memory_type,
            "quota_limit": request.quota_limit,
            "quota_enforce": request.quota_enforce,
            "quota_confirmation_cap": request.quota_confirmation_cap,
            "quota_weight_importance": request.quota_weight_importance,
            "quota_weight_confirmation": request.quota_weight_confirmation,
            "quota_weight_recency": request.quota_weight_recency,
            "fts_enabled": request.fts_enabled,
        }
        raw = self._native.promote(json.dumps(payload, ensure_ascii=False))
        return json.loads(raw) if isinstance(raw, str) else raw


def _try_rust(
    native_loader: Callable[[], ModuleType] = _load_native,
) -> MemoryBackend:
    return RustMemoryBackend(native_loader())


def select_backend(
    mode: str | None = None,
    *,
    native_loader: Callable[[], ModuleType] = _load_native,
) -> BackendDecision:
    """Resolve a requested mode and expose deterministic fallback semantics."""

    requested = (mode or configured_mode()).strip().lower()
    if requested not in _VALID_MODES:
        raise ValueError(
            f"invalid MEMORY_BACKEND={requested!r}; expected one of "
            f"{', '.join(sorted(_VALID_MODES))}"
        )

    if requested == "python":
        return BackendDecision(requested, "python")

    try:
        _try_rust(native_loader)
    except (BackendUnavailable, BackendContractError) as exc:
        if requested in {"rust", "strict"}:
            raise
        return BackendDecision(
            requested,
            "python",
            shadow=requested == "shadow",
            fallback_reason=str(exc),
        )

    if requested == "shadow":
        return BackendDecision(requested, "rust", shadow=True)
    return BackendDecision(requested, "rust", strict=requested == "strict")


def get_backend(
    mode: str | None = None,
    *,
    native_loader: Callable[[], ModuleType] = _load_native,
) -> MemoryBackend:
    """Instantiate the resolved backend; Python remains the safe default."""

    _, backend = resolve_backend(mode, native_loader=native_loader)
    return backend


def resolve_backend(
    mode: str | None = None,
    *,
    native_loader: Callable[[], ModuleType] = _load_native,
) -> tuple[BackendDecision, MemoryBackend]:
    """Resolve a mode once so callers can retain shadow/fallback metadata."""

    decision = select_backend(mode, native_loader=native_loader)
    if decision.selected == "python":
        return decision, python_backend()
    return decision, _try_rust(native_loader)
