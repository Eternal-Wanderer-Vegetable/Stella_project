# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Load only the NoneBot adapter modules explicitly enabled for this process."""

from __future__ import annotations

import importlib
import re
from typing import Any

DEFAULT_ADAPTER_MODULES = ("nonebot.adapters.onebot.v11",)
_DISABLED_VALUES = {"disabled", "none", "off"}
_MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


class AdapterRegistrationError(RuntimeError):
    """An enabled adapter cannot be imported or registered on the active driver."""


def parse_adapter_modules(raw: str | None) -> tuple[str, ...]:
    """Parse comma-separated import paths; an explicit blank or ``none`` disables all."""
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


def register_enabled_adapters(driver: Any, module_paths: tuple[str, ...]) -> tuple[str, ...]:
    """Import and register selected adapter classes, failing clearly on missing setup.

    Adapter packages are never installed automatically. A package must be installed
    before its module path is enabled. Adapters already registered by the caller are
    accepted only when they are the same class.
    """
    from nonebot.adapters import Adapter

    registered_names: list[str] = []
    existing_adapters = getattr(driver, "_adapters", {})

    for module_path in module_paths:
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError as exc:
            missing = exc.name or module_path
            raise AdapterRegistrationError(
                f"STELLA_ADAPTER_MODULES enables {module_path!r}, but module or "
                f"dependency {missing!r} is missing. Install that adapter package "
                "and its dependencies, or remove it from STELLA_ADAPTER_MODULES."
            ) from exc
        except Exception as exc:
            raise AdapterRegistrationError(
                f"Could not import enabled adapter module {module_path!r}: {exc}"
            ) from exc

        adapter_class = getattr(module, "Adapter", None)
        if not isinstance(adapter_class, type) or not issubclass(
            adapter_class, Adapter
        ):
            raise AdapterRegistrationError(
                f"Enabled module {module_path!r} must expose an Adapter class "
                "derived from nonebot.adapters.Adapter."
            )

        try:
            adapter_name = str(adapter_class.get_name() or "").strip()
        except Exception as exc:
            raise AdapterRegistrationError(
                f"Could not read the adapter name from {module_path!r}: {exc}"
            ) from exc
        if not adapter_name:
            raise AdapterRegistrationError(
                f"Enabled module {module_path!r} returned an empty adapter name."
            )

        existing = existing_adapters.get(adapter_name)
        if existing is not None:
            existing_class = existing if isinstance(existing, type) else type(existing)
            if existing_class is adapter_class:
                registered_names.append(adapter_name)
                continue
            raise AdapterRegistrationError(
                f"Adapter name {adapter_name!r} from {module_path!r} is already "
                "registered by a different class. Remove the duplicate registration."
            )

        try:
            driver.register_adapter(adapter_class)
        except Exception as exc:
            driver_name = type(driver).__name__
            configured_driver = getattr(getattr(driver, "config", None), "driver", None)
            driver_detail = (
                f" (DRIVER={configured_driver!r})" if configured_driver else ""
            )
            raise AdapterRegistrationError(
                f"Adapter {adapter_name!r} from {module_path!r} could not register "
                f"on {driver_name}{driver_detail}: {exc}"
            ) from exc

        registered_names.append(adapter_name)

    return tuple(registered_names)
