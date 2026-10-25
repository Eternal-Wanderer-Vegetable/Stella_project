# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Shared managed/legacy handling for the versioned conversation policy bundle."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

from dotenv.parser import parse_stream

from stella_bootstrap.transport_settings import (
    TransportSettingsError,
    TransportSettingsV1,
    parse_transport_settings_json,
)
from webui.responses import ApiError
from webui.services import envfile

SETTINGS_KEY = "STELLA_TRANSPORT_SETTINGS_JSON"


def parse_request_body(body: bytes) -> TransportSettingsV1:
    """Parse the raw JSON body so duplicate object keys remain detectable."""
    try:
        raw = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransportSettingsError("transport settings must be valid UTF-8") from exc
    return parse_transport_settings_json(raw)


def parse_stored_value(raw: str | None) -> TransportSettingsV1:
    if raw is None or not raw.strip():
        return parse_transport_settings_json(None)
    return parse_transport_settings_json(raw)


def settings_object(parsed: TransportSettingsV1) -> dict[str, Any]:
    return json.loads(parsed.canonical_json)


def stored_json(parsed: TransportSettingsV1) -> str:
    """Avoid dotenv's `${NAME}` interpolation while keeping valid compact JSON."""
    return parsed.canonical_json.replace("${", r"\u0024{")


def managed_response_data(
    raw: str | None,
    *,
    desired_revision: str,
    applied_revision: str,
    source: str,
    applied_source: str,
) -> dict[str, Any]:
    try:
        parsed = parse_stored_value(raw)
    except TransportSettingsError:
        return {
            "settings": None,
            "valid": False,
            "error_code": "transport_settings_invalid",
            "desired_revision": desired_revision,
            "applied_revision": applied_revision,
            "source": source,
            "applied_source": applied_source,
            "restart_required": True,
        }
    return {
        "settings": settings_object(parsed),
        "valid": True,
        "desired_revision": desired_revision,
        "applied_revision": applied_revision,
        "source": source,
        "applied_source": applied_source,
        "restart_required": desired_revision != applied_revision,
    }


def parse_legacy_if_match(value: str | None) -> str:
    if value is None:
        raise ApiError(
            "conversation settings require If-Match",
            status_code=428,
            data={"code": "if_match_required"},
        )
    normalized = value.strip()
    if normalized.startswith("W/"):
        normalized = normalized[2:].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        normalized = normalized[1:-1]
    if len(normalized) != 71 or not normalized.startswith("sha256:"):
        raise ApiError("if_match_invalid", data={"code": "if_match_invalid"})
    digest = normalized[7:]
    if any(char not in "0123456789abcdef" for char in digest):
        raise ApiError("if_match_invalid", data={"code": "if_match_invalid"})
    return normalized


def legacy_snapshot() -> tuple[dict[str, Any], str, bool]:
    """Return a safe legacy view, its file-content ETag and duplicate-key flag."""
    raw_bytes, digest = envfile.read_snapshot()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        applied = _legacy_applied_settings()
        return (
            {
                "settings": None,
                "valid": False,
                "error_code": "config_source_invalid",
                "desired_revision": digest,
                "applied_revision": None,
                "source": "data_env",
                "effective_settings": None,
                "effective_source": "data_env",
                "applied_settings": settings_object(applied) if applied is not None else None,
                "applied_source": "legacy_process",
                "restart_required": True,
            },
            digest,
            False,
        )

    values, source_invalid = _setting_assignments(text)
    duplicate = len(values) > 1
    raw_value = values[-1] if values else None
    applied = _legacy_applied_settings()
    try:
        if source_invalid:
            raise TransportSettingsError("invalid dotenv setting")
        if duplicate:
            raise TransportSettingsError("duplicate transport settings key")
        base_parsed = parse_stored_value(raw_value)
    except TransportSettingsError:
        base_parsed = None
        base_error = "config_source_invalid" if source_invalid else "transport_settings_invalid"
    else:
        base_error = None

    effective_raw, effective_source, effective_invalid = _legacy_effective_value(
        raw_value, bool(values)
    )
    try:
        if effective_invalid:
            raise TransportSettingsError("invalid effective dotenv setting")
        effective_parsed = parse_stored_value(effective_raw)
    except TransportSettingsError:
        effective_parsed = None

    data = {
        "settings": settings_object(base_parsed) if base_parsed is not None else None,
        "valid": base_error is None,
        "desired_revision": digest,
        "applied_revision": None,
        "source": "data_env" if values else "default",
        "effective_settings": (
            settings_object(effective_parsed) if effective_parsed is not None else None
        ),
        "effective_source": effective_source,
        "applied_settings": settings_object(applied) if applied is not None else None,
        "applied_source": "legacy_process",
        "restart_required": (
            effective_parsed is None
            or applied is None
            or effective_parsed.canonical_json != applied.canonical_json
        ),
    }
    if base_error is not None:
        data["error_code"] = base_error
    return data, digest, duplicate


def _setting_assignments(text: str) -> tuple[list[str | None], bool]:
    values: list[str | None] = []
    invalid = False
    for binding in parse_stream(StringIO(text)):
        if binding.key == SETTINGS_KEY:
            values.append(binding.value)
            invalid = invalid or binding.error or binding.value is None
    return values, invalid


def _legacy_effective_value(
    base_value: str | None, base_present: bool
) -> tuple[str | None, str, bool]:
    try:
        from config import settings
    except ImportError:
        return base_value, "data_env" if base_present else "default", False

    environment = str(getattr(settings, "_ENVIRONMENT", "")).strip().lower()
    overlay_name = {
        "dev": ".env.dev",
        "development": ".env.dev",
        "prod": ".env.prod",
        "production": ".env.prod",
    }.get(environment)
    if overlay_name:
        path = Path(settings.STELLA_HOME) / overlay_name
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else ""
        except (OSError, UnicodeError):
            return None, "dev_overlay" if overlay_name == ".env.dev" else "prod_overlay", True
        values, invalid = _setting_assignments(text)
        if values:
            return (
                values[-1],
                "dev_overlay" if overlay_name == ".env.dev" else "prod_overlay",
                invalid or len(values) > 1,
            )

    external = getattr(settings, "_LEGACY_TRANSPORT_SETTINGS_EXTERNAL", None)
    if external is not None:
        return str(external), "external_environment", False
    return base_value, "data_env" if base_present else "default", False


def _legacy_applied_settings() -> TransportSettingsV1 | None:
    try:
        from config import settings

        return parse_stored_value(
            getattr(settings, SETTINGS_KEY, "")
        )
    except (ImportError, TransportSettingsError):
        return None


def save_legacy(
    parsed: TransportSettingsV1, *, expected_digest: str
) -> tuple[dict[str, Any], str]:
    encoded_value = json.dumps(stored_json(parsed), ensure_ascii=False)
    envfile.write_values(
        {SETTINGS_KEY: encoded_value},
        expected_digest=expected_digest,
        dedupe_keys={SETTINGS_KEY},
    )
    data, digest, duplicate = legacy_snapshot()
    if duplicate or not data["valid"] or data["settings"] != settings_object(parsed):
        raise ApiError(
            "conversation settings readback did not match the saved bundle",
            status_code=409,
            data={"code": "config_readback_conflict", "current_revision": digest},
        )
    return data, digest
