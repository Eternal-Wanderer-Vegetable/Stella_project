# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Versioned, stdlib-only contracts shared by Corona and managed Nucleus."""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

CONTROL_PROTOCOL_VERSION = 1
HEALTH_PATH = "/_nucleus/v1/health"
DRAIN_PATH = "/_nucleus/v1/lifecycle/drain"
STOP_PATH = "/_nucleus/v1/lifecycle/stop"

HEADER_PROTOCOL = "x-stella-control-protocol-version"
HEADER_CAPABILITY = "x-stella-internal-capability"
HEADER_INSTANCE = "x-stella-instance-id"
HEADER_CONTROLLER = "x-stella-controller-boot-id"
HEADER_GENERATION = "x-stella-generation-id"
HEADER_REVISION = "x-stella-revision-id"
HEADER_ACTOR_ID = "x-stella-actor-id"
HEADER_ACTOR_KIND = "x-stella-actor-kind"
HEADER_ACTOR_AUTH = "x-stella-actor-authentication"
HEADER_REQUEST_ID = "x-stella-request-id"

_INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_ACTOR_ID = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")
_ACTOR_KINDS = frozenset({"admin", "adapter", "system"})
_AUTHENTICATIONS = frozenset({"jwt", "adapter", "system"})


class ControlContractError(ValueError):
    """A control-plane value does not satisfy protocol v1."""


@dataclass(frozen=True)
class ControlIdentity:
    instance_id: str
    controller_boot_id: str
    generation_id: str
    revision_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.instance_id, str) or not _INSTANCE_ID.fullmatch(self.instance_id):
            raise ControlContractError("instance_id is invalid")
        for key in ("controller_boot_id", "generation_id", "revision_id"):
            value = getattr(self, key)
            if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
                raise ControlContractError(f"{key} is invalid")

    def to_payload(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "controller_boot_id": self.controller_boot_id,
            "generation_id": self.generation_id,
            "revision_id": self.revision_id,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> ControlIdentity:
        return cls(
            instance_id=value.get("instance_id", ""),  # type: ignore[arg-type]
            controller_boot_id=value.get("controller_boot_id", ""),  # type: ignore[arg-type]
            generation_id=value.get("generation_id", ""),  # type: ignore[arg-type]
            revision_id=value.get("revision_id", ""),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class TrustedActor:
    actor_id: str
    kind: str
    authentication: str

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not _ACTOR_ID.fullmatch(self.actor_id):
            raise ControlContractError("trusted actor id is invalid")
        if self.kind not in _ACTOR_KINDS or self.authentication not in _AUTHENTICATIONS:
            raise ControlContractError("trusted actor type is invalid")
        if (self.kind, self.authentication) not in {
            ("admin", "jwt"), ("adapter", "adapter"), ("system", "system")
        }:
            raise ControlContractError("trusted actor authentication does not match its type")

    def to_dict(self) -> dict[str, str]:
        return {
            "actor_id": self.actor_id,
            "kind": self.kind,
            "authentication": self.authentication,
        }


def new_request_id() -> str:
    return uuid.uuid4().hex


def valid_request_id(value: str) -> bool:
    return isinstance(value, str) and bool(_REQUEST_ID.fullmatch(value))


def identity_headers(identity: ControlIdentity) -> dict[str, str]:
    return {
        HEADER_PROTOCOL: str(CONTROL_PROTOCOL_VERSION),
        HEADER_INSTANCE: identity.instance_id,
        HEADER_CONTROLLER: identity.controller_boot_id,
        HEADER_GENERATION: identity.generation_id,
        HEADER_REVISION: identity.revision_id,
    }


def internal_headers(
    *,
    identity: ControlIdentity,
    capability: str,
    actor: TrustedActor,
    request_id: str | None = None,
) -> dict[str, str]:
    if not isinstance(capability, str) or not capability or not capability.isascii():
        raise ControlContractError("internal capability is invalid")
    request_id = request_id or new_request_id()
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ControlContractError("request_id is invalid")
    return {
        **identity_headers(identity),
        HEADER_CAPABILITY: capability,
        HEADER_ACTOR_ID: base64.urlsafe_b64encode(
            actor.actor_id.encode("utf-8")
        ).decode("ascii").rstrip("="),
        HEADER_ACTOR_KIND: actor.kind,
        HEADER_ACTOR_AUTH: actor.authentication,
        HEADER_REQUEST_ID: request_id,
    }


def actor_id_from_header(value: bytes) -> str:
    try:
        padded = value + b"=" * (-len(value) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ControlContractError("trusted actor id is invalid") from exc
    if not _ACTOR_ID.fullmatch(decoded):
        raise ControlContractError("trusted actor id is invalid")
    return decoded


def lifecycle_payload(
    identity: ControlIdentity, *, operation_id: str, **extra: object
) -> dict[str, object]:
    if not isinstance(operation_id, str) or not _REQUEST_ID.fullmatch(operation_id):
        raise ControlContractError("operation_id is invalid")
    return {
        "control_protocol_version": CONTROL_PROTOCOL_VERSION,
        **identity.to_payload(),
        "operation_id": operation_id,
        **extra,
    }


def validate_health_payload(
    payload: Mapping[str, object], expected: ControlIdentity
) -> None:
    if payload.get("control_protocol_version") != CONTROL_PROTOCOL_VERSION:
        raise ControlContractError("protocol_mismatch")
    try:
        actual = ControlIdentity.from_payload(payload)
    except ControlContractError as exc:
        raise ControlContractError("identity_mismatch") from exc
    if actual != expected:
        raise ControlContractError("identity_mismatch")


def validate_lifecycle_ack(
    payload: Mapping[str, object],
    *,
    expected: ControlIdentity,
    operation_id: str,
) -> None:
    if payload.get("control_protocol_version") != CONTROL_PROTOCOL_VERSION:
        raise ControlContractError("protocol_mismatch")
    try:
        actual = ControlIdentity.from_payload(payload)
    except ControlContractError as exc:
        raise ControlContractError("identity_mismatch") from exc
    if actual != expected:
        raise ControlContractError("identity_mismatch")
    if payload.get("operation_id") != operation_id:
        raise ControlContractError("late_ack")
