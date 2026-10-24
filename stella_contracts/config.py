# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Versioned, secret-bearing configuration revision contract."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

REVISION_FORMAT_VERSION = 1
REVISION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SOURCE_KINDS = frozenset(
    {"data_env", "external_environment", "dev_overlay", "prod_overlay"}
)


class ConfigRevisionError(ValueError):
    """A configuration revision is malformed or unsupported."""


@dataclass(frozen=True)
class ConfigRevision:
    """Immutable in-memory view of one effective configuration revision.

    ``values`` contains configuration values and is therefore secret-bearing. Use
    :meth:`public_metadata` for status and diagnostics; it never returns values or
    source digests.
    """

    revision_id: str
    created_at: str
    project_root: str
    stella_home: str
    environment: str
    values: Mapping[str, str]
    sources: Mapping[str, str]
    source_digests: Mapping[str, str]
    external_override_keys: tuple[str, ...] = ()
    format_version: int = REVISION_FORMAT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.format_version, int) or isinstance(self.format_version, bool):
            raise ConfigRevisionError("configuration revision format must be an integer")
        if self.format_version != REVISION_FORMAT_VERSION:
            raise ConfigRevisionError(
                f"unsupported configuration revision format: {self.format_version}"
            )
        if not isinstance(self.revision_id, str) or not REVISION_ID_PATTERN.fullmatch(self.revision_id):
            raise ConfigRevisionError("invalid configuration revision id")
        if not isinstance(self.created_at, str):
            raise ConfigRevisionError("invalid configuration revision timestamp")
        try:
            created_at = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ConfigRevisionError("invalid configuration revision timestamp") from exc
        if created_at.tzinfo is None:
            raise ConfigRevisionError("configuration revision timestamp must include a timezone")
        for name, value in (
            ("project_root", self.project_root),
            ("stella_home", self.stella_home),
        ):
            if not isinstance(value, str) or not value or not Path(value).is_absolute():
                raise ConfigRevisionError(f"{name} must be an absolute path")
        if not isinstance(self.environment, str) or self.environment not in {
            "", "dev", "development", "prod", "production"
        }:
            raise ConfigRevisionError("invalid ENVIRONMENT profile")

        values = dict(self.values)
        sources = dict(self.sources)
        digests = dict(self.source_digests)
        if any(not isinstance(key, str) for key in values) or any(
            not ENV_KEY_PATTERN.fullmatch(key) for key in values
        ):
            raise ConfigRevisionError("invalid environment key in configuration revision")
        if any(not isinstance(value, str) for value in values.values()):
            raise ConfigRevisionError("configuration revision values must be strings")
        if set(sources) != set(values) or any(
            not isinstance(source, str) or source not in SOURCE_KINDS
            for source in sources.values()
        ):
            raise ConfigRevisionError("configuration revision sources do not match values")
        if any(
            not isinstance(key, str)
            or not isinstance(digest, str)
            or key not in {".env", ".env.dev", ".env.prod"}
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for key, digest in digests.items()
        ):
            raise ConfigRevisionError("invalid configuration source digest")
        overrides = tuple(self.external_override_keys)
        if any(not isinstance(key, str) for key in overrides) or len(set(overrides)) != len(overrides) or any(
            key not in values or sources.get(key) != "external_environment"
            for key in overrides
        ):
            raise ConfigRevisionError("invalid external override key list")

        object.__setattr__(self, "values", MappingProxyType(values))
        object.__setattr__(self, "sources", MappingProxyType(sources))
        object.__setattr__(self, "source_digests", MappingProxyType(digests))
        object.__setattr__(self, "external_override_keys", overrides)

    def to_dict(self) -> dict:
        """Serialize the private revision file, including configuration values."""
        return {
            "format_version": self.format_version,
            "revision_id": self.revision_id,
            "created_at": self.created_at,
            "project_root": self.project_root,
            "stella_home": self.stella_home,
            "environment": self.environment,
            "values": dict(self.values),
            "sources": dict(self.sources),
            "source_digests": dict(self.source_digests),
            "external_override_keys": list(self.external_override_keys),
        }

    @classmethod
    def from_dict(cls, payload: object) -> ConfigRevision:
        if not isinstance(payload, dict):
            raise ConfigRevisionError("configuration revision must be a JSON object")
        required = {
            "format_version",
            "revision_id",
            "created_at",
            "project_root",
            "stella_home",
            "environment",
            "values",
            "sources",
            "source_digests",
            "external_override_keys",
        }
        if set(payload) != required:
            raise ConfigRevisionError("configuration revision fields do not match v1")
        for field in ("revision_id", "created_at", "project_root", "stella_home", "environment"):
            if not isinstance(payload[field], str):
                raise ConfigRevisionError(f"{field} must be a string")
        for field in ("values", "sources", "source_digests"):
            if not isinstance(payload[field], dict):
                raise ConfigRevisionError(f"{field} must be an object")
        overrides = payload["external_override_keys"]
        if not isinstance(overrides, list) or any(not isinstance(key, str) for key in overrides):
            raise ConfigRevisionError("external_override_keys must be a string array")
        if not isinstance(payload["format_version"], int) or isinstance(
            payload["format_version"], bool
        ):
            raise ConfigRevisionError("format_version must be an integer")
        return cls(
            format_version=payload["format_version"],
            revision_id=payload["revision_id"],
            created_at=payload["created_at"],
            project_root=payload["project_root"],
            stella_home=payload["stella_home"],
            environment=payload["environment"],
            values=payload["values"],
            sources=payload["sources"],
            source_digests=payload["source_digests"],
            external_override_keys=tuple(overrides),
        )

    def public_metadata(self) -> dict:
        """Return safe source metadata without paths, values, or content digests."""
        return {
            "revision_id": self.revision_id,
            "format_version": self.format_version,
            "created_at": self.created_at,
            "environment": self.environment,
            "keys": sorted(self.values),
            "sources": dict(self.sources),
            "external_override_keys": list(self.external_override_keys),
        }
