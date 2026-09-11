# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Adapter for the existing Python memory implementation."""

from __future__ import annotations

from typing import Any

from memory_rust.backend import (
    BACKEND_API_VERSION,
    MEMORY_SCHEMA_VERSION,
    MemoryBackend,
    PromotionRequest,
    RetrievalRequest,
)


class PythonMemoryBackend:
    """Expose the current Python engine through the backend contract.

    Imports stay lazy so installing or importing the optional Rust package does
    not eagerly initialize the existing memory stack.
    """

    name = "python"
    api_version = BACKEND_API_VERSION
    schema_version = MEMORY_SCHEMA_VERSION

    def retrieve(self, request: RetrievalRequest) -> Any:
        from memory.retrieval_v2 import retrieve_memories

        return retrieve_memories(
            request.group_shared_space,
            request.user_id,
            request.query,
            trigger=request.trigger,
            mode=request.mode,
            semantic_scores=dict(request.semantic_scores or {}),
            _bypass_backend=True,
        )

    def promote(self, request: PromotionRequest) -> Any:
        raise RuntimeError(
            "Python promotion is owned by MemoryManager and is not delegated"
        )


def python_backend() -> MemoryBackend:
    """Return the Python compatibility backend."""

    return PythonMemoryBackend()
