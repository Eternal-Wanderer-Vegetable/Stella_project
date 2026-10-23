# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Adapter availability rules shared by the control plane and Bot runtime."""

import sys

BLOCKED_ADAPTERS = {
    "nonebot_adapter_walleq": "walleQ",
    "nonebot.adapters.ntchat": "ntchat",
    "nonebot.adapters.mail": "mailSecurityCompatibility",
}


def unavailable_adapter_reasons() -> dict[str, str]:
    """Return adapters blocked by policy or unsupported on the current Python."""
    unavailable = dict(BLOCKED_ADAPTERS)
    if sys.version_info < (3, 11):
        unavailable["nonebot.adapters.heybox"] = "requiresPython311"
    return unavailable
