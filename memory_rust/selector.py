# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Select the optional Rust backend without changing Python defaults."""

from __future__ import annotations

import importlib
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
)
from memory_rust.python_backend import python_backend

_VALID_MODES = frozenset({"python", "rust", "auto", "shadow", "strict"})
_NATIVE_MODULE = "memory_rust._native"


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

    value = os.getenv("MEMORY_BACKEND", "python").strip().lower() or "python"
    if value not in _VALID_MODES:
        raise ValueError(
            f"invalid MEMORY_BACKEND={value!r}; expected one of "
            f"{', '.join(sorted(_VALID_MODES))}"
        )
    return value


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
        return self._native.retrieve(request)

    def promote(self, manager):
        return self._native.promote(manager)


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

    decision = select_backend(mode, native_loader=native_loader)
    if decision.selected == "python":
        return python_backend()
    return _try_rust(native_loader)
