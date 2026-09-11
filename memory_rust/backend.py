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


@dataclass(frozen=True)
class PromotionRequest:
    """Input for one bounded, already-gated promotion transaction."""

    db_path: Path
    candidate_id: str
    group_shared_space: str
    user_id: str
    memory_type: str
    quota_limit: int
    quota_enforce: bool
    quota_confirmation_cap: int
    quota_weight_importance: float
    quota_weight_confirmation: float
    quota_weight_recency: float
    fts_enabled: bool


class MemoryBackend(Protocol):
    """Minimal interface implemented by Python and native backends."""

    name: str
    api_version: int
    schema_version: int

    def retrieve(self, request: RetrievalRequest) -> Any:
        """Retrieve memories using the backend's implementation."""

    def promote(self, request: PromotionRequest) -> Any:
        """Run one bounded promotion transaction."""
