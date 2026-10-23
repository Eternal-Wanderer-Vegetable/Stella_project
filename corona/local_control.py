# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Capability-protected, loopback-only deploy control for Corona."""

from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stella_contracts.control import CONTROL_PROTOCOL_VERSION
from stella_contracts.local_control import (
    LOCAL_STATUS_PATH,
    LOCAL_STOP_PATH,
    LocalControlError,
    LocalControlRecord,
    local_control_record_path,
)
from stella_contracts.local_control import (
    LocalControlClient as LocalControlClient,
)
from stella_contracts.local_control import (
    read_local_control_record as read_local_control_record,
)

_OPERATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
logger = logging.getLogger("corona.local-control")


def create_local_control_record(bootstrap: Any) -> LocalControlRecord:
    """Publish the current listener and a per-controller capability privately."""
    record = LocalControlRecord(
        instance_id=bootstrap.instance_id,
        controller_boot_id=bootstrap.controller_boot_id,
        host="127.0.0.1",
        port=int(bootstrap.local_control_port),
        capability=secrets.token_urlsafe(32),
    )
    path = local_control_record_path(bootstrap.stella_home, bootstrap.instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise LocalControlError("local control directory is unsafe")
    if os.name != "nt":
        path.parent.chmod(0o700)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(record.to_dict(), stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        if os.name != "nt":
            path.chmod(0o600)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(OSError):
            temporary.unlink()
        raise
    return record


def create_local_control_app(
    bootstrap: Any, supervisor: Any, record: LocalControlRecord
) -> FastAPI:
    app = FastAPI(
        title="Stella local deploy control",
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.supervisor = supervisor
    app.state.stop_operation_id = None
    app.state.stop_task = None
    app.state.controller_app = None

    @app.get(LOCAL_STATUS_PATH)
    async def status(request: Request):
        denied = _authorize(request, record)
        if denied is not None:
            return denied
        return JSONResponse(
            {
                "ok": True,
                "control_protocol_version": CONTROL_PROTOCOL_VERSION,
                "instance_id": record.instance_id,
                "controller_boot_id": record.controller_boot_id,
                "controller_pid": os.getpid(),
                "public_host": bootstrap.public_host,
                "public_port": bootstrap.public_port,
                "webui_enabled": bootstrap.webui_enabled,
                "core": supervisor.snapshot.public(),
            }
        )

    @app.post(LOCAL_STOP_PATH)
    async def stop(request: Request):
        denied = _authorize(request, record)
        if denied is not None:
            return denied
        try:
            raw_body = await request.body()
        except (OSError, RuntimeError):
            return _failure(400, "invalid_json")
        if len(raw_body) > 8192:
            return _failure(413, "request_too_large")
        try:
            payload = json.loads(raw_body or b"{}")
        except (UnicodeDecodeError, ValueError):
            return _failure(400, "invalid_json")
        if not isinstance(payload, dict):
            return _failure(400, "invalid_request")
        if not _protocol_v1(payload.get("control_protocol_version")):
            return _failure(409, "protocol_mismatch")
        if (
            payload.get("instance_id") != record.instance_id
            or payload.get("controller_boot_id") != record.controller_boot_id
        ):
            return _failure(409, "identity_mismatch")
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
            return _failure(400, "invalid_operation_id")
        active_operation = app.state.stop_operation_id
        if active_operation is not None and active_operation != operation_id:
            return _failure(409, "operation_in_progress")
        app.state.stop_operation_id = operation_id
        if app.state.stop_task is None:
            app.state.stop_task = asyncio.create_task(
                _stop_controller(app, supervisor), name="corona-local-control-stop"
            )
        return JSONResponse(
            {
                "ok": True,
                "control_protocol_version": CONTROL_PROTOCOL_VERSION,
                "instance_id": record.instance_id,
                "controller_boot_id": record.controller_boot_id,
                "operation_id": operation_id,
                "phase": "stopping",
            },
            status_code=202,
        )

    return app


async def _stop_controller(app: FastAPI, supervisor: Any) -> None:
    try:
        await supervisor.stop()
    except Exception as exc:
        logger.exception("local stop operation failed (%s)", type(exc).__name__)
        return
    controller_app = app.state.controller_app
    callback = getattr(
        getattr(controller_app, "state", None), "request_controller_shutdown", None
    )
    if callable(callback):
        callback()


def _authorize(request: Request, record: LocalControlRecord) -> JSONResponse | None:
    host = request.client.host if request.client else ""
    try:
        if not ipaddress.ip_address(host).is_loopback:
            return _failure(404, "not_found")
    except ValueError:
        return _failure(404, "not_found")
    protected = {
        b"authorization",
        b"x-stella-control-protocol-version",
        b"x-stella-instance-id",
        b"x-stella-controller-boot-id",
    }
    headers: dict[bytes, bytes] = {}
    for name, value in request.scope.get("headers", ()):
        name = bytes(name).lower()
        if name in protected:
            if name in headers:
                return _failure(400, "invalid_request")
            headers[name] = bytes(value)
    supplied = headers.get(b"authorization", b"")
    expected = f"Bearer {record.capability}"
    if not hmac.compare_digest(supplied, expected.encode("ascii")):
        return _failure(401, "unauthorized")
    if headers.get(b"x-stella-control-protocol-version") != str(CONTROL_PROTOCOL_VERSION).encode("ascii"):
        return _failure(409, "protocol_mismatch")
    if (
        headers.get(b"x-stella-instance-id") != record.instance_id.encode("ascii")
        or headers.get(b"x-stella-controller-boot-id")
        != record.controller_boot_id.encode("ascii")
    ):
        return _failure(409, "identity_mismatch")
    return None


def _protocol_v1(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value == CONTROL_PROTOCOL_VERSION
    )


def _failure(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )
