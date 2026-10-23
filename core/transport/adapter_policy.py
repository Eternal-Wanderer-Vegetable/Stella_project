# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Backward-compatible import path for the shared adapter availability policy."""

from stella_bootstrap.adapter_policy import (
    BLOCKED_ADAPTERS,
    unavailable_adapter_reasons,
)

__all__ = ["BLOCKED_ADAPTERS", "unavailable_adapter_reasons"]
