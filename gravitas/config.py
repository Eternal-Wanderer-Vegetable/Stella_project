# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Strict immutable loader for the initial Gravitas TOML profile."""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised by the Python 3.10 CI lane
    import tomli as tomllib


class ConfigError(ValueError):
    """Configuration is malformed or contains unsupported settings."""


class GravitasMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    tick_seconds: float
    fact_ttl_seconds: float


@dataclass(frozen=True, slots=True)
class LimitsConfig:
    turn_timeout_seconds: float
    interactive_queue: int
    background_queue: int
    max_pending_per_conversation: int


@dataclass(frozen=True, slots=True)
class ResourceGroupConfig:
    group_id: str
    slots: tuple[str, ...]
    concurrency: int


@dataclass(frozen=True, slots=True)
class GravitasConfig:
    schema_version: int
    controller: ControllerConfig
    limits: LimitsConfig
    resources: tuple[ResourceGroupConfig, ...]

    def resource(self, group_id: str) -> ResourceGroupConfig | None:
        return next(
            (item for item in self.resources if item.group_id == group_id), None
        )


_RESOURCE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SLOT_ID = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def parse_config(text: str) -> GravitasConfig:
    """Parse strict schema v1; unknown keys fail closed instead of being ignored."""
    if not isinstance(text, str):
        raise ConfigError("configuration must be text")
    try:
        raw = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, TypeError) as exc:
        raise ConfigError(f"invalid TOML: {exc}") from exc
    return _parse_document(raw)


def load_config(path: str | Path) -> GravitasConfig:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read Gravitas configuration: {exc}") from exc
    return parse_config(text)


def _parse_document(raw: object) -> GravitasConfig:
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a table")
    _keys(raw, {"schema_version", "controller", "limits", "resources"}, "root")
    version = _integer(raw.get("schema_version"), "schema_version", minimum=1)
    if version != 1:
        raise ConfigError(f"unsupported schema_version: {version}")

    controller = _table(raw.get("controller"), "controller")
    _keys(controller, {"tick_seconds", "fact_ttl_seconds"}, "controller")
    tick = _number(controller.get("tick_seconds"), "controller.tick_seconds")
    ttl = _number(controller.get("fact_ttl_seconds"), "controller.fact_ttl_seconds")
    if tick <= 0 or ttl <= tick:
        raise ConfigError("controller requires 0 < tick_seconds < fact_ttl_seconds")

    limits = _table(raw.get("limits"), "limits")
    _keys(
        limits,
        {
            "turn_timeout_seconds",
            "interactive_queue",
            "background_queue",
            "max_pending_per_conversation",
        },
        "limits",
    )
    timeout = _number(limits.get("turn_timeout_seconds"), "limits.turn_timeout_seconds")
    if timeout <= 0:
        raise ConfigError("limits.turn_timeout_seconds must be positive")
    limits_config = LimitsConfig(
        turn_timeout_seconds=timeout,
        interactive_queue=_integer(
            limits.get("interactive_queue"), "limits.interactive_queue", minimum=1
        ),
        background_queue=_integer(
            limits.get("background_queue"), "limits.background_queue", minimum=1
        ),
        max_pending_per_conversation=_integer(
            limits.get("max_pending_per_conversation"),
            "limits.max_pending_per_conversation",
            minimum=1,
        ),
    )

    resources_raw = _table(raw.get("resources"), "resources")
    if not resources_raw:
        raise ConfigError("resources must define at least one resource group")
    groups: list[ResourceGroupConfig] = []
    all_slots: set[str] = set()
    for group_id, item in resources_raw.items():
        if not isinstance(group_id, str) or not _RESOURCE_ID.fullmatch(group_id):
            raise ConfigError(f"invalid resource group id: {group_id!r}")
        group = _table(item, f"resources.{group_id}")
        _keys(group, {"slots", "concurrency"}, f"resources.{group_id}")
        slots = group.get("slots")
        if not isinstance(slots, list) or not slots:
            raise ConfigError(f"resources.{group_id}.slots must be a non-empty array")
        if any(
            not isinstance(slot, str) or not _SLOT_ID.fullmatch(slot) for slot in slots
        ):
            raise ConfigError(f"resources.{group_id}.slots contains an invalid slot id")
        if len(set(slots)) != len(slots):
            raise ConfigError(f"resources.{group_id}.slots contains duplicates")
        duplicated = all_slots.intersection(slots)
        if duplicated:
            raise ConfigError(
                f"slots belong to multiple groups: {', '.join(sorted(duplicated))}"
            )
        all_slots.update(slots)
        groups.append(
            ResourceGroupConfig(
                group_id=group_id,
                slots=tuple(slots),
                concurrency=_integer(
                    group.get("concurrency"),
                    f"resources.{group_id}.concurrency",
                    minimum=1,
                ),
            )
        )
    groups.sort(key=lambda item: item.group_id)
    return GravitasConfig(
        schema_version=version,
        controller=ControllerConfig(tick_seconds=tick, fact_ttl_seconds=ttl),
        limits=limits_config,
        resources=tuple(groups),
    )


def _keys(table: dict[str, Any], required: set[str], name: str) -> None:
    missing = required - table.keys()
    unknown = table.keys() - required
    if missing:
        raise ConfigError(f"missing {name} keys: {', '.join(sorted(missing))}")
    if unknown:
        raise ConfigError(f"unknown {name} keys: {', '.join(sorted(unknown))}")


def _table(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ConfigError(f"{name} must be a table")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ConfigError(f"{name} must be finite")
    return result


def _integer(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{name} must be an integer >= {minimum}")
    return value
