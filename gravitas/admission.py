# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Small, pure admission-contract checks; policy decisions arrive in G02."""

from __future__ import annotations

import math

from gravitas.contracts import Operation, PolicySnapshot

SUPPORTED_OPERATIONS = frozenset(item.value for item in Operation)


def is_operation_supported(operation: str) -> bool:
    """Unknown operations are never eligible for an enforce allowlist."""
    return isinstance(operation, str) and operation in SUPPORTED_OPERATIONS


def snapshot_is_current(
    snapshot: PolicySnapshot,
    *,
    now: float,
    expected_boot_id: str,
) -> bool:
    """A policy expires by control time and cannot survive controller restart."""
    if not isinstance(snapshot, PolicySnapshot):
        return False
    if (
        snapshot.schema_version != 1
        or snapshot.controller_boot_id != expected_boot_id
        or isinstance(now, bool)
        or not isinstance(now, (int, float))
        or not math.isfinite(now)
    ):
        return False
    return now >= snapshot.issued_at and now < snapshot.expires_at
