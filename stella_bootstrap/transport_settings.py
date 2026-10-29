# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Pure, bounded parser for the opt-in transport settings bundle."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

MAX_TRANSPORT_SETTINGS_BYTES = 256 * 1024
MAX_CONNECTIONS = 256
MAX_PROFILES = 1024
MAX_BINDINGS = 10_000

_SLUG = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CREDENTIAL_REF = re.compile(
    r"^(?:env|legacy):[A-Z_][A-Z0-9_]{0,127}$"
    r"|^managed:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_CLOCK_TIME = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_WAKE_MODES = frozenset({"mention", "reply", "prefix", "all", "private_direct"})
_FORMAT_MODES = frozenset({"native", "plain", "markdown"})
_SEGMENTATION_MODES = frozenset({"auto", "none", "safe"})
_SCENE_KINDS = frozenset({"private", "group", "channel", "thread", "webchat"})
_POLICY_FIELDS = frozenset(
    {
        "capture_enabled",
        "llm_enabled",
        "wake_mode",
        "wake_prefixes",
        "reply_mention",
        "reply_quote",
        "format_mode",
        "segmentation",
        "proactive_enabled",
        "quiet_hours",
        "requests_per_window",
        "rate_window_seconds",
    }
)


class TransportSettingsError(ValueError):
    """A transport-settings bundle is malformed or exceeds its limits."""


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _object(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise TransportSettingsError(f"{path} must be an object")
    return value


def _fields(value: dict, *, required: set[str], allowed: set[str], path: str) -> None:
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing:
        raise TransportSettingsError(f"{path} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise TransportSettingsError(f"{path} has unknown fields: {', '.join(sorted(unknown))}")


def _text(value: object, path: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise TransportSettingsError(f"{path} must be a non-empty string of at most {maximum} characters")
    if any(
        ord(char) < 0x20
        or ord(char) == 0x7F
        or 0xD800 <= ord(char) <= 0xDFFF
        for char in value
    ):
        raise TransportSettingsError(f"{path} contains a control character")
    return value


def _slug(value: object, path: str) -> str:
    result = _text(value, path, maximum=64)
    if not _SLUG.fullmatch(result):
        raise TransportSettingsError(f"{path} must be a canonical lowercase name")
    return result


def _profile_id(value: object, path: str) -> str:
    result = _text(value, path, maximum=128)
    if not _PROFILE_ID.fullmatch(result):
        raise TransportSettingsError(f"{path} has an invalid identifier")
    return result


def _canonical_uuid(value: object, path: str) -> str:
    raw = _text(value, path, maximum=36)
    try:
        parsed = UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise TransportSettingsError(f"{path} must be a canonical UUID") from exc
    if str(parsed) != raw:
        raise TransportSettingsError(f"{path} must be a lowercase canonical UUID")
    return raw


def validate_policy_values(value: object, path: str = "policy") -> dict[str, object]:
    """Validate known policy fields while preserving explicit false and empty values."""
    values = _object(value, path)
    unknown = values.keys() - _POLICY_FIELDS
    if unknown:
        raise TransportSettingsError(f"{path} has unknown fields: {', '.join(sorted(unknown))}")

    result: dict[str, object] = {}
    boolean_fields = {
        "capture_enabled",
        "llm_enabled",
        "reply_mention",
        "reply_quote",
        "proactive_enabled",
    }
    for name in boolean_fields & values.keys():
        if not isinstance(values[name], bool):
            raise TransportSettingsError(f"{path}.{name} must be a boolean")
        result[name] = values[name]

    if "wake_mode" in values:
        mode = _text(values["wake_mode"], f"{path}.wake_mode", maximum=32)
        if mode not in _WAKE_MODES:
            raise TransportSettingsError(f"{path}.wake_mode is unsupported")
        result["wake_mode"] = mode

    if "wake_prefixes" in values:
        prefixes = values["wake_prefixes"]
        if not isinstance(prefixes, list) or len(prefixes) > 128:
            raise TransportSettingsError(f"{path}.wake_prefixes must be an array of at most 128 strings")
        checked = tuple(_text(item, f"{path}.wake_prefixes[]", maximum=128) for item in prefixes)
        if len(set(checked)) != len(checked):
            raise TransportSettingsError(f"{path}.wake_prefixes contains duplicates")
        result["wake_prefixes"] = checked

    enum_fields = {
        "format_mode": _FORMAT_MODES,
        "segmentation": _SEGMENTATION_MODES,
    }
    for name, choices in enum_fields.items():
        if name in values:
            item = _text(values[name], f"{path}.{name}", maximum=32)
            if item not in choices:
                raise TransportSettingsError(f"{path}.{name} is unsupported")
            result[name] = item

    if "quiet_hours" in values:
        quiet = _object(values["quiet_hours"], f"{path}.quiet_hours")
        _fields(
            quiet,
            required={"start", "end", "timezone"},
            allowed={"start", "end", "timezone"},
            path=f"{path}.quiet_hours",
        )
        start = _text(quiet["start"], f"{path}.quiet_hours.start", maximum=5)
        end = _text(quiet["end"], f"{path}.quiet_hours.end", maximum=5)
        timezone = _text(quiet["timezone"], f"{path}.quiet_hours.timezone", maximum=64)
        if not _CLOCK_TIME.fullmatch(start) or not _CLOCK_TIME.fullmatch(end):
            raise TransportSettingsError(f"{path}.quiet_hours times must use HH:MM")
        result["quiet_hours"] = {"start": start, "end": end, "timezone": timezone}

    if "requests_per_window" in values:
        count = values["requests_per_window"]
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise TransportSettingsError(f"{path}.requests_per_window must be a positive integer")
        result["requests_per_window"] = count

    if "rate_window_seconds" in values:
        seconds = values["rate_window_seconds"]
        if (
            not isinstance(seconds, (int, float))
            or isinstance(seconds, bool)
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            raise TransportSettingsError(f"{path}.rate_window_seconds must be positive and finite")
        result["rate_window_seconds"] = seconds

    return result


@dataclass(frozen=True, slots=True)
class TransportConnectionSettings:
    connection_id: str
    adapter: str
    platform_scope: str
    self_id: str
    credential_ref: str | None
    enabled: bool
    display_name: str | None
    policy: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TransportPolicyProfile:
    policy_profile_id: str
    policy: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ScenePolicyBinding:
    connection_id: str
    scene_kind: str
    scene_id: str
    parent_path: tuple[str, ...]
    thread_id: str | None
    policy_profile_id: str
    persona_ref: str | None
    memory_space: str | None
    context_mode: str
    policy: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class TransportSettingsV1:
    version: int
    connections: tuple[TransportConnectionSettings, ...]
    profiles: tuple[TransportPolicyProfile, ...]
    bindings: tuple[ScenePolicyBinding, ...]
    defaults: Mapping[str, object]
    platform_templates: Mapping[str, Mapping[str, object]]
    canonical_json: str


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise TransportSettingsError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _parse_connection(raw: object, index: int) -> TransportConnectionSettings:
    path = f"connections[{index}]"
    value = _object(raw, path)
    allowed = {
        "connection_id",
        "adapter",
        "platform_scope",
        "self_id",
        "credential_ref",
        "enabled",
        "display_name",
        "policy",
    }
    _fields(
        value,
        required={"connection_id", "adapter", "platform_scope", "self_id"},
        allowed=allowed,
        path=path,
    )
    credential_ref = value.get("credential_ref")
    if credential_ref is not None:
        credential_ref = _text(credential_ref, f"{path}.credential_ref", maximum=256)
        if not _CREDENTIAL_REF.fullmatch(credential_ref):
            raise TransportSettingsError(f"{path}.credential_ref must be a namespaced reference")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise TransportSettingsError(f"{path}.enabled must be a boolean")
    display_name = value.get("display_name")
    if display_name is not None:
        display_name = _text(display_name, f"{path}.display_name", maximum=128)
    policy = validate_policy_values(value.get("policy", {}), f"{path}.policy")
    return TransportConnectionSettings(
        connection_id=_canonical_uuid(value["connection_id"], f"{path}.connection_id"),
        adapter=_slug(value["adapter"], f"{path}.adapter"),
        platform_scope=_slug(value["platform_scope"], f"{path}.platform_scope"),
        self_id=_text(value["self_id"], f"{path}.self_id", maximum=512),
        credential_ref=credential_ref,
        enabled=enabled,
        display_name=display_name,
        policy=_freeze_json(policy),  # type: ignore[arg-type]
    )


def _parse_profile(raw: object, index: int) -> TransportPolicyProfile:
    path = f"profiles[{index}]"
    value = _object(raw, path)
    _fields(
        value,
        required={"policy_profile_id"},
        allowed={"policy_profile_id", "policy"},
        path=path,
    )
    policy = validate_policy_values(value.get("policy", {}), f"{path}.policy")
    return TransportPolicyProfile(
        policy_profile_id=_profile_id(value["policy_profile_id"], f"{path}.policy_profile_id"),
        policy=_freeze_json(policy),  # type: ignore[arg-type]
    )


def _parse_binding(raw: object, index: int) -> ScenePolicyBinding:
    path = f"bindings[{index}]"
    value = _object(raw, path)
    allowed = {
        "connection_id",
        "scene",
        "policy_profile_id",
        "persona_ref",
        "memory_space",
        "context_mode",
        "policy",
    }
    _fields(
        value,
        required={"connection_id", "scene", "policy_profile_id"},
        allowed=allowed,
        path=path,
    )
    scene = _object(value["scene"], f"{path}.scene")
    _fields(
        scene,
        required={"kind", "scene_id"},
        allowed={"kind", "scene_id", "parent_path", "thread_id"},
        path=f"{path}.scene",
    )
    kind = _text(scene["kind"], f"{path}.scene.kind", maximum=32)
    if kind not in _SCENE_KINDS:
        raise TransportSettingsError(f"{path}.scene.kind is unsupported")
    parent_path = scene.get("parent_path", [])
    if not isinstance(parent_path, list) or len(parent_path) > 16:
        raise TransportSettingsError(f"{path}.scene.parent_path must be an array of at most 16 strings")
    checked_parent = tuple(
        _text(part, f"{path}.scene.parent_path[]", maximum=512) for part in parent_path
    )
    thread_id = scene.get("thread_id")
    if thread_id is not None:
        thread_id = _text(thread_id, f"{path}.scene.thread_id", maximum=512)
    context_mode = value.get("context_mode", "scene")
    if context_mode != "scene":
        raise TransportSettingsError(f"{path}.context_mode is unsupported; only scene is implemented")

    def optional_ref(name: str) -> str | None:
        reference = value.get(name)
        return None if reference is None else _text(reference, f"{path}.{name}", maximum=256)

    policy = validate_policy_values(value.get("policy", {}), f"{path}.policy")
    return ScenePolicyBinding(
        connection_id=_canonical_uuid(value["connection_id"], f"{path}.connection_id"),
        scene_kind=kind,
        scene_id=_text(scene["scene_id"], f"{path}.scene.scene_id", maximum=512),
        parent_path=checked_parent,
        thread_id=thread_id,
        policy_profile_id=_profile_id(value["policy_profile_id"], f"{path}.policy_profile_id"),
        persona_ref=optional_ref("persona_ref"),
        memory_space=optional_ref("memory_space"),
        context_mode=context_mode,
        policy=_freeze_json(policy),  # type: ignore[arg-type]
    )


def parse_transport_settings_json(raw: str | None) -> TransportSettingsV1:
    """Parse a version-1 bundle without importing runtime, memory, or adapter packages.

    Missing configuration produces an empty bundle whose connections are all absent;
    declared connections default to disabled. The returned canonical JSON is compact
    and key-sorted so callers can persist a stable one-line value.
    """
    if raw is None:
        payload: object = {"version": 1}
    else:
        if not isinstance(raw, str):
            raise TransportSettingsError("transport settings must be a string or None")
        try:
            raw_size = len(raw.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise TransportSettingsError("transport settings must be valid UTF-8") from exc
        if raw_size > MAX_TRANSPORT_SETTINGS_BYTES:
            raise TransportSettingsError("transport settings exceed the 256 KiB limit")
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_object_pairs)
        except TransportSettingsError:
            raise
        except (json.JSONDecodeError, TypeError) as exc:
            raise TransportSettingsError("transport settings must contain valid JSON") from exc

    root = _object(payload, "transport settings")
    _fields(
        root,
        required={"version"},
        allowed={"version", "connections", "profiles", "bindings", "defaults", "platform_templates"},
        path="transport settings",
    )
    version = root["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise TransportSettingsError("transport settings version must be integer 1")

    connections_raw = root.get("connections", [])
    profiles_raw = root.get("profiles", [])
    bindings_raw = root.get("bindings", [])
    for name, items, maximum in (
        ("connections", connections_raw, MAX_CONNECTIONS),
        ("profiles", profiles_raw, MAX_PROFILES),
        ("bindings", bindings_raw, MAX_BINDINGS),
    ):
        if not isinstance(items, list) or len(items) > maximum:
            raise TransportSettingsError(f"{name} must be an array of at most {maximum} entries")

    connections = tuple(_parse_connection(item, i) for i, item in enumerate(connections_raw))
    connection_ids = [item.connection_id for item in connections]
    if len(connection_ids) != len(set(connection_ids)):
        raise TransportSettingsError("connection_id values must be unique")
    slots = [(item.adapter, item.self_id) for item in connections]
    if len(slots) != len(set(slots)):
        raise TransportSettingsError("adapter and self_id slots must be unique")

    profiles = tuple(_parse_profile(item, i) for i, item in enumerate(profiles_raw))
    profile_ids = [item.policy_profile_id for item in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise TransportSettingsError("policy_profile_id values must be unique")
    profile_id_set = set(profile_ids)
    connection_id_set = set(connection_ids)

    bindings = tuple(_parse_binding(item, i) for i, item in enumerate(bindings_raw))
    binding_keys = [
        (
            item.connection_id,
            item.scene_kind,
            item.scene_id,
            item.parent_path,
            item.thread_id,
        )
        for item in bindings
    ]
    if len(binding_keys) != len(set(binding_keys)):
        raise TransportSettingsError("scene bindings must be unique per connection")
    for index, binding in enumerate(bindings):
        if binding.connection_id not in connection_id_set:
            raise TransportSettingsError(f"bindings[{index}] references an unknown connection_id")
        if binding.policy_profile_id not in profile_id_set:
            raise TransportSettingsError(f"bindings[{index}] references an unknown policy_profile_id")

    defaults = validate_policy_values(root.get("defaults", {}), "defaults")
    templates_raw = _object(root.get("platform_templates", {}), "platform_templates")
    templates: dict[str, Mapping[str, object]] = {}
    for adapter, policy in templates_raw.items():
        key = _slug(adapter, "platform_templates key")
        templates[key] = _freeze_json(
            validate_policy_values(policy, f"platform_templates.{key}")
        )  # type: ignore[assignment]

    canonical_json = json.dumps(
        root,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return TransportSettingsV1(
        version=1,
        connections=connections,
        profiles=profiles,
        bindings=bindings,
        defaults=_freeze_json(defaults),  # type: ignore[arg-type]
        platform_templates=MappingProxyType(templates),
        canonical_json=canonical_json,
    )


__all__ = [
    "MAX_BINDINGS",
    "MAX_CONNECTIONS",
    "MAX_PROFILES",
    "MAX_TRANSPORT_SETTINGS_BYTES",
    "ScenePolicyBinding",
    "TransportConnectionSettings",
    "TransportPolicyProfile",
    "TransportSettingsError",
    "TransportSettingsV1",
    "parse_transport_settings_json",
    "validate_policy_values",
]
