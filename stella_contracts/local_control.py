# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Stdlib-only client contract for the loopback Corona deploy API."""

from __future__ import annotations

import http.client
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .control import CONTROL_PROTOCOL_VERSION

LOCAL_STATUS_PATH = "/_corona/local/v1/status"
LOCAL_STOP_PATH = "/_corona/local/v1/stop"
_OPERATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class LocalControlError(RuntimeError):
    """The local deploy-control contract could not be satisfied."""


@dataclass(frozen=True)
class LocalControlRecord:
    instance_id: str
    controller_boot_id: str
    host: str
    port: int
    capability: str

    def to_dict(self) -> dict[str, object]:
        return {
            "control_protocol_version": CONTROL_PROTOCOL_VERSION,
            "instance_id": self.instance_id,
            "controller_boot_id": self.controller_boot_id,
            "host": self.host,
            "port": self.port,
            "capability": self.capability,
        }


def local_control_record_path(stella_home: Path, instance_id: str) -> Path:
    return Path(stella_home) / ".stella" / "instances" / instance_id / "corona" / "local-control.json"


def read_local_control_record(path: Path) -> LocalControlRecord:
    """Read the private endpoint and capability published by one Corona owner."""
    path = Path(path)
    if path.is_symlink():
        raise LocalControlError("local control record is unsafe")
    try:
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise LocalControlError("local control record is not a regular file")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) != 0o600:
            raise LocalControlError("local control record permissions are unsafe")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except LocalControlError:
        raise
    except (OSError, UnicodeError, ValueError) as exc:
        raise LocalControlError("local control record is unavailable or invalid") from exc
    if not isinstance(payload, dict) or not _protocol_v1(payload.get("control_protocol_version")):
        raise LocalControlError("local control protocol is unsupported")
    try:
        record = LocalControlRecord(
            instance_id=_text(payload, "instance_id"),
            controller_boot_id=_text(payload, "controller_boot_id"),
            host=_text(payload, "host"),
            port=payload["port"],
            capability=_text(payload, "capability"),
        )
    except (KeyError, TypeError) as exc:
        raise LocalControlError("local control record is invalid") from exc
    if (
        record.host != "127.0.0.1"
        or isinstance(record.port, bool)
        or not isinstance(record.port, int)
        or not 1 <= record.port <= 65535
    ):
        raise LocalControlError("local control endpoint is invalid")
    if not record.capability or not record.capability.isascii():
        raise LocalControlError("local control capability is invalid")
    return record


class LocalControlClient:
    """Small authenticated HTTP client that never follows redirects."""

    def __init__(self, record: LocalControlRecord, *, timeout: float = 3.0) -> None:
        self.record = record
        self.timeout = float(timeout)
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")

    @classmethod
    def from_record_file(cls, path: Path, *, timeout: float = 3.0) -> LocalControlClient:
        return cls(read_local_control_record(path), timeout=timeout)

    def status(self) -> dict[str, object]:
        payload = self._request("GET", LOCAL_STATUS_PATH)
        self._validate_identity(payload)
        return payload

    def stop(self, operation_id: str) -> dict[str, object]:
        if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
            raise LocalControlError("local control operation id is invalid")
        body = {
            "control_protocol_version": CONTROL_PROTOCOL_VERSION,
            "instance_id": self.record.instance_id,
            "controller_boot_id": self.record.controller_boot_id,
            "operation_id": operation_id,
        }
        payload = self._request("POST", LOCAL_STOP_PATH, body)
        self._validate_identity(payload)
        if payload.get("operation_id") != operation_id:
            raise LocalControlError("late stop acknowledgement")
        return payload

    def _request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> dict[str, object]:
        connection = http.client.HTTPConnection(
            self.record.host, self.record.port, timeout=self.timeout
        )
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        try:
            connection.request(
                method,
                path,
                body=encoded,
                headers={
                    "Authorization": f"Bearer {self.record.capability}",
                    "X-Stella-Control-Protocol-Version": str(CONTROL_PROTOCOL_VERSION),
                    "X-Stella-Instance-ID": self.record.instance_id,
                    "X-Stella-Controller-Boot-ID": self.record.controller_boot_id,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise LocalControlError("local control response is too large")
            try:
                payload = json.loads(data)
            except (UnicodeDecodeError, ValueError) as exc:
                raise LocalControlError("local control response is invalid") from exc
            expected_status = 200 if method == "GET" else 202
            if response.status != expected_status:
                code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None
                raise LocalControlError(str(code or "local control request failed"))
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise LocalControlError("local control response is invalid")
            return payload
        except OSError as exc:
            raise LocalControlError("Corona local control is unavailable") from exc
        finally:
            connection.close()

    def _validate_identity(self, payload: dict[str, object]) -> None:
        if payload.get("control_protocol_version") != CONTROL_PROTOCOL_VERSION:
            raise LocalControlError("local control protocol mismatch")
        if (
            payload.get("instance_id") != self.record.instance_id
            or payload.get("controller_boot_id") != self.record.controller_boot_id
        ):
            raise LocalControlError("local control identity mismatch")


def _text(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise TypeError(key)
    return value


def _protocol_v1(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value == CONTROL_PROTOCOL_VERSION
    )


__all__ = [
    "LOCAL_STATUS_PATH",
    "LOCAL_STOP_PATH",
    "LocalControlClient",
    "LocalControlError",
    "LocalControlRecord",
    "local_control_record_path",
    "read_local_control_record",
]
