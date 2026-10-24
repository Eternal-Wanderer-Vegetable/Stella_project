# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Side-effect-free parser for configured adapter import paths."""

from __future__ import annotations

import re

DEFAULT_ADAPTER_MODULES = ("nonebot.adapters.onebot.v11",)
_DISABLED_VALUES = {"disabled", "none", "off"}
_MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


def parse_adapter_modules(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_ADAPTER_MODULES
    value = raw.strip()
    if not value or value.casefold() in _DISABLED_VALUES:
        return ()
    modules = tuple(part.strip() for part in value.split(",") if part.strip())
    if not modules:
        return ()
    if len(set(modules)) != len(modules):
        raise ValueError("STELLA_ADAPTER_MODULES contains a duplicate module path")
    invalid = [module for module in modules if not _MODULE_NAME.fullmatch(module)]
    if invalid:
        raise ValueError(
            "STELLA_ADAPTER_MODULES entries must be valid Python module paths; "
            f"invalid: {', '.join(invalid)}"
        )
    return modules
