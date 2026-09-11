# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Stable Python-side contract shared by the Python and Rust memory backends."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

BACKEND_API_VERSION = 1
MEMORY_SCHEMA_VERSION = 14


class MemoryBackendError(RuntimeError):
    """Base class for backend selection and execution failures."""


class BackendUnavailableError(MemoryBackendError):
    """Raised when a requested backend cannot be loaded."""


BackendUnavailable = BackendUnavailableError


class BackendContractError(MemoryBackendError):
    """Raised when a backend does not support this Python/schema contract."""


@dataclass(frozen=True)
class RetrievalRequest:
    """Backend-neutral input for a scoped memory retrieval."""

    db_path: Path
    group_shared_space: str
    user_id: int
    query: str
    trigger: str
    mode: str
    pool_limit: int
    semantic_scores: Mapping[str, float] | None = None


class MemoryBackend(Protocol):
    """Minimal interface implemented by Python and native backends."""

    name: str
    api_version: int
    schema_version: int

    def retrieve(self, request: RetrievalRequest) -> Any:
        """Retrieve memories using the backend's implementation."""

    def promote(self, manager: Any) -> Any:
        """Run the bounded promotion operation owned by the backend."""
