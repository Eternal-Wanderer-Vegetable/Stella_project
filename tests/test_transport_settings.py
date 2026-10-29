# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Versioned transport settings are bounded, strict, and preserve opaque IDs."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from stella_bootstrap.transport_settings import (
    MAX_TRANSPORT_SETTINGS_BYTES,
    TransportSettingsError,
    parse_transport_settings_json,
)

CONNECTION_A = "11111111-1111-4111-8111-111111111111"
CONNECTION_B = "22222222-2222-4222-8222-222222222222"


def _bundle(**updates):
    result = {
        "version": 1,
        "connections": [
            {
                "connection_id": CONNECTION_A,
                "adapter": "telegram",
                "platform_scope": "telegram",
                "self_id": "007:雪",
                "credential_ref": "env:TELEGRAM_BOT_TOKEN",
            }
        ],
        "profiles": [{"policy_profile_id": "default", "policy": {}}],
        "bindings": [],
    }
    result.update(updates)
    return result


def test_missing_settings_is_empty_and_new_connections_default_closed():
    empty = parse_transport_settings_json(None)
    assert empty.version == 1
    assert empty.connections == ()
    assert empty.canonical_json == '{"version":1}'

    parsed = parse_transport_settings_json(json.dumps(_bundle()))
    connection = parsed.connections[0]
    assert connection.enabled is False
    assert connection.self_id == "007:雪"
    assert connection.credential_ref == "env:TELEGRAM_BOT_TOKEN"
    assert json.loads(parsed.canonical_json)["connections"][0]["self_id"] == "007:雪"


def test_canonical_uuid_and_connection_slots_are_stable_across_order_and_name():
    first = _bundle()
    second = _bundle(connections=[{**first["connections"][0], "display_name": "renamed"}])
    parsed_first = parse_transport_settings_json(json.dumps(first))
    parsed_second = parse_transport_settings_json(json.dumps(second))
    assert parsed_first.connections[0].connection_id == str(UUID(CONNECTION_A))
    assert parsed_first.connections[0].connection_id == parsed_second.connections[0].connection_id
    assert parsed_first.connections[0].self_id == parsed_second.connections[0].self_id


def test_same_opaque_self_id_on_different_adapters_is_allowed():
    bundle = _bundle(
        connections=[
            _bundle()["connections"][0],
            {
                "connection_id": CONNECTION_B,
                "adapter": "discord",
                "platform_scope": "discord",
                "self_id": "007:雪",
            },
        ]
    )
    parsed = parse_transport_settings_json(json.dumps(bundle))
    assert [item.self_id for item in parsed.connections] == ["007:雪", "007:雪"]


@pytest.mark.parametrize(
    "connections",
    [
        [
            {
                "connection_id": CONNECTION_A,
                "adapter": "telegram",
                "platform_scope": "telegram",
                "self_id": "bot",
            },
            {
                "connection_id": CONNECTION_A,
                "adapter": "discord",
                "platform_scope": "discord",
                "self_id": "other",
            },
        ],
        [
            {
                "connection_id": CONNECTION_A,
                "adapter": "telegram",
                "platform_scope": "telegram",
                "self_id": "007",
            },
            {
                "connection_id": CONNECTION_B,
                "adapter": "telegram",
                "platform_scope": "other-scope",
                "self_id": "007",
            },
        ],
    ],
)
def test_duplicate_connection_ids_and_adapter_slots_are_rejected(connections):
    with pytest.raises(TransportSettingsError):
        parse_transport_settings_json(json.dumps(_bundle(connections=connections)))


def test_duplicate_json_keys_and_unknown_fields_are_rejected():
    with pytest.raises(TransportSettingsError, match="duplicate JSON object key"):
        parse_transport_settings_json('{"version":1,"version":1}')
    with pytest.raises(TransportSettingsError, match="unknown fields"):
        parse_transport_settings_json(json.dumps(_bundle(token="must-not-be-stored")))


def test_credential_values_must_be_references_not_raw_secrets():
    bundle = _bundle()
    bundle["connections"][0]["credential_ref"] = "env:123:raw-token"
    with pytest.raises(TransportSettingsError, match="namespaced reference"):
        parse_transport_settings_json(json.dumps(bundle))
    bundle["connections"][0]["credential_ref"] = "managed:raw-secret"
    with pytest.raises(TransportSettingsError, match="namespaced reference"):
        parse_transport_settings_json(json.dumps(bundle))


def test_unknown_policy_enum_and_member_context_mode_are_rejected():
    bundle = _bundle(
        profiles=[
            {"policy_profile_id": "default", "policy": {"wake_mode": "random"}}
        ]
    )
    with pytest.raises(TransportSettingsError, match="wake_mode"):
        parse_transport_settings_json(json.dumps(bundle))

    bundle = _bundle(
        bindings=[
            {
                "connection_id": CONNECTION_A,
                "scene": {"kind": "group", "scene_id": "007"},
                "policy_profile_id": "default",
                "context_mode": "member",
            }
        ]
    )
    with pytest.raises(TransportSettingsError, match="only scene"):
        parse_transport_settings_json(json.dumps(bundle))


def test_dangling_binding_references_and_duplicate_scene_bindings_are_rejected():
    binding = {
        "connection_id": CONNECTION_A,
        "scene": {
            "kind": "thread",
            "scene_id": "channel:007",
            "parent_path": ["server:1"],
            "thread_id": "thread/猫",
        },
        "policy_profile_id": "missing",
    }
    with pytest.raises(TransportSettingsError, match="unknown policy_profile_id"):
        parse_transport_settings_json(json.dumps(_bundle(bindings=[binding])))

    repeated = {**binding, "policy_profile_id": "default"}
    with pytest.raises(TransportSettingsError, match="scene bindings must be unique"):
        parse_transport_settings_json(json.dumps(_bundle(bindings=[repeated, repeated])))


def test_false_and_empty_policy_values_are_explicit_and_immutable():
    bundle = _bundle(
        defaults={"capture_enabled": True, "wake_prefixes": ["!"]},
        profiles=[
            {
                "policy_profile_id": "default",
                "policy": {"capture_enabled": False, "wake_prefixes": []},
            }
        ],
    )
    parsed = parse_transport_settings_json(json.dumps(bundle))
    profile = parsed.profiles[0].policy
    assert profile["capture_enabled"] is False
    assert profile["wake_prefixes"] == ()
    with pytest.raises(TypeError):
        profile["capture_enabled"] = True


def test_payload_and_collection_limits_are_checked_before_processing():
    oversized = '{"version":1,"padding":"' + ("x" * MAX_TRANSPORT_SETTINGS_BYTES) + '"}'
    with pytest.raises(TransportSettingsError, match="256 KiB"):
        parse_transport_settings_json(oversized)

    with pytest.raises(TransportSettingsError, match="connections"):
        parse_transport_settings_json(json.dumps({"version": 1, "connections": [{}] * 257}))
