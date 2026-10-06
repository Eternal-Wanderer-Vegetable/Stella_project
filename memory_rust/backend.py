# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Stable Python-side contract shared by the Python and Rust memory backends."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

# v2（计划 §6.7）：请求携带受限 owner/subject/audience scope。无新 scope 的
# 请求明确 SPACE-only（legacy 行为），绝不默认放开全部个人记录。
BACKEND_API_VERSION = 2
# 与 memory/schema.py 的 SCHEMA_VERSION 同步（计划 §6.7：整体合同，
# 旧 schema native 不能读新库，反之亦然）。v17（对话归属复发修复计划 §6.1/§6.3/§6.5）
# 新增的 verification_contract_json / parser_version 列与 sharing 表不在
# native 读写面上，但合同按整库版本精确匹配——native 需以本版本号重新编译才能加载。
MEMORY_SCHEMA_VERSION = 18


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
    # ---- v2 owner scope（计划 §6.6/§6.7）：全部留空 = SPACE-only ----
    # 由可信代码（ownership.scope_for_conversation）生成；模型输入不可构造。
    scope_space_key: str = ""  # "space:<space>"，当前 SPACE owner
    scope_person_owner_key: str = ""  # "person:qq:<bot>:<uid>"
    scope_subject_key: str = ""  # "qq:<uid>"
    scope_person_audiences: tuple[str, ...] = ()  # 允许的 PERSON 受众

    @property
    def has_person_scope(self) -> bool:
        return bool(
            self.scope_space_key
            and self.scope_person_owner_key
            and self.scope_subject_key
            and self.scope_person_audiences
        )


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
    # ---- v2 owner 归属（计划 §6.5/§6.7）：晋升/相似/配额保持归属 ----
    # 留空 = 旧行为（按 space+user，写出的行 owner 由 DEFAULT/迁移语义承接）。
    owner_type: str = ""
    owner_key: str = ""
    subject_key: str = ""
    audience: str = ""
    source_conversation_key: str = ""
    fact_key: str = ""
    policy_version: str = ""


class MemoryBackend(Protocol):
    """Minimal interface implemented by Python and native backends."""

    name: str
    api_version: int
    schema_version: int

    def retrieve(self, request: RetrievalRequest) -> Any:
        """Retrieve memories using the backend's implementation."""

    def promote(self, request: PromotionRequest) -> Any:
        """Run one bounded promotion transaction."""
