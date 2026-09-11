# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Optional Rust-backed memory runtime.

The package is intentionally usable without its native extension.  The
selector keeps the existing Python memory implementation as the default.
"""

from memory_rust.backend import (
    BACKEND_API_VERSION,
    MEMORY_SCHEMA_VERSION,
    BackendContractError,
    BackendUnavailable,
    MemoryBackend,
    RetrievalRequest,
)
from memory_rust.selector import (
    BackendDecision,
    get_backend,
    resolve_backend,
    select_backend,
)

__all__ = [
    "BACKEND_API_VERSION",
    "MEMORY_SCHEMA_VERSION",
    "BackendContractError",
    "BackendDecision",
    "BackendUnavailable",
    "MemoryBackend",
    "RetrievalRequest",
    "get_backend",
    "resolve_backend",
    "select_backend",
]
