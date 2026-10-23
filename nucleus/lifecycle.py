# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Managed Nucleus admission, private control endpoints, and shutdown budget."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import inspect
import ipaddress
import json
import math
import os
import stat
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from typing_extensions import Self

CONTROL_PROTOCOL_VERSION = 1
HEALTH_PATH = "/_nucleus/v1/health"
DRAIN_PATH = "/_nucleus/v1/lifecycle/drain"
STOP_PATH = "/_nucleus/v1/lifecycle/stop"
DEFAULT_SHUTDOWN_BUDGET_SECONDS = 45.0
FORCE_EXIT_GRACE_SECONDS = 10.0
_ACTIVE_LIFECYCLE: NucleusLifecycle | None = None


class BusinessRootLockError(RuntimeError):
    """The configured business database is already owned by another core."""


class BusinessRootLock:
    """Process-held OS lock keyed to the canonical configured database path."""

    def __init__(self, database_path: Path, lock_path: Path, descriptor: int) -> None:
        self.database_path = database_path
        self.lock_path = lock_path
        self._descriptor = descriptor

    @classmethod
    def acquire(cls, database_path: Path) -> BusinessRootLock:
        database = Path(database_path).expanduser().resolve(strict=False)
        if not database.is_absolute() or not database.name:
            raise BusinessRootLockError("configured business database path is invalid")
        try:
            database.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BusinessRootLockError("could not prepare business database lock directory") from exc
        lock_path = database.with_name(f".{database.name}.nucleus.lock")
        if lock_path.is_symlink():
            raise BusinessRootLockError("business database lock path is unsafe")
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise BusinessRootLockError("could not open business database lock") from exc

        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise BusinessRootLockError("business database lock is not a regular file")
            if os.name == "nt":
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"\0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise BusinessRootLockError(
                        "business database is already owned by a managed core"
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise BusinessRootLockError(
                        "business database is already owned by a managed core"
                    ) from exc
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            return cls(database, lock_path, descriptor)
        except BusinessRootLockError:
            os.close(descriptor)
            raise
        except OSError as exc:
            os.close(descriptor)
            raise BusinessRootLockError("could not establish business database lock") from exc
        except Exception:
            os.close(descriptor)
            raise

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor < 0:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            # Closing the OS handle is the final release on both supported lock
            # implementations; a redundant explicit unlock may fail at exit.
            pass
        finally:
            os.close(descriptor)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def set_active_lifecycle(lifecycle: NucleusLifecycle | None) -> None:
    global _ACTIVE_LIFECYCLE
    _ACTIVE_LIFECYCLE = lifecycle


def active_lifecycle() -> NucleusLifecycle:
    if _ACTIVE_LIFECYCLE is None:
        raise RuntimeError("managed Nucleus lifecycle is not active")
    return _ACTIVE_LIFECYCLE


class NucleusLifecycle:
    """One generation's identity and single monotonic shutdown deadline."""

    def __init__(
        self,
        *,
        instance_id: str,
        controller_boot_id: str,
        generation_id: str,
        revision_id: str,
        launch_token: str,
        internal_host: str,
        internal_port: int,
        shutdown_budget_seconds: float = DEFAULT_SHUTDOWN_BUDGET_SECONDS,
        force_exit: Callable[[int], Any] = os._exit,
    ) -> None:
        self.instance_id = instance_id
        self.controller_boot_id = controller_boot_id
        self.generation_id = generation_id
        self.revision_id = revision_id
        self.launch_token = launch_token
        self.internal_host = internal_host
        self.internal_port = internal_port
        self.shutdown_budget_seconds = float(shutdown_budget_seconds)
        self._force_exit = force_exit
        self._phase = "starting"
        self._server: Any | None = None
        self._deadline: float | None = None
        self._watchdog: threading.Timer | None = None
        self._watchdog_deadline: float | None = None
        self._lock = threading.Lock()

    @property
    def phase(self) -> str:
        with self._lock:
            return self._phase

    @property
    def server(self) -> Any | None:
        return self._server

    @property
    def is_ready(self) -> bool:
        return self.phase == "ready"

    def attach_server(self, server: Any) -> None:
        self._server = server

    def mark_ready(self) -> None:
        with self._lock:
            if self._phase == "starting":
                self._phase = "ready"

    def mark_startup_failed(self) -> None:
        with self._lock:
            if self._phase not in {"stopped", "stopping"}:
                self._phase = "startup_failed"

    def mark_stopped(self) -> None:
        with self._lock:
            self._phase = "stopped"

    def begin_drain(self, timeout_seconds: float | None = None) -> float:
        requested = self.shutdown_budget_seconds if timeout_seconds is None else timeout_seconds
        if isinstance(requested, bool) or not isinstance(requested, (int, float)):
            raise ValueError("shutdown timeout must be numeric")
        if not math.isfinite(float(requested)) or requested < 0:
            raise ValueError("shutdown timeout must be finite and non-negative")
        timeout = min(float(requested), self.shutdown_budget_seconds)
        candidate = time.monotonic() + timeout
        with self._lock:
            if self._phase in {"stopped", "startup_failed"}:
                return 0.0
            if self._phase != "stopping":
                self._phase = "draining"
            self._deadline = candidate if self._deadline is None else min(self._deadline, candidate)
            remaining = max(0.0, self._deadline - time.monotonic())
            force_deadline = self._deadline + FORCE_EXIT_GRACE_SECONDS
            if (
                self._watchdog is None
                or not self._watchdog.is_alive()
                or self._watchdog_deadline is None
                or force_deadline < self._watchdog_deadline
            ):
                if self._watchdog is not None:
                    self._watchdog.cancel()
                self._watchdog = threading.Timer(
                    max(0.0, force_deadline - time.monotonic()),
                    self._force_shutdown_exit,
                )
                self._watchdog.daemon = True
                self._watchdog.start()
                self._watchdog_deadline = force_deadline
            return remaining

    def begin_shutdown(self) -> float:
        with self._lock:
            has_deadline = self._deadline is not None
        if not has_deadline:
            self.begin_drain()
        with self._lock:
            if self._phase not in {"stopped", "startup_failed"}:
                self._phase = "stopping"
        return self.remaining_shutdown_seconds()

    def remaining_shutdown_seconds(self) -> float:
        with self._lock:
            deadline = self._deadline
        if deadline is None:
            return self.shutdown_budget_seconds
        return max(0.0, deadline - time.monotonic())

    def request_stop(self) -> bool:
        with self._lock:
            if self._phase not in {"draining", "stopping"} or self._server is None:
                return False
            self._phase = "stopping"
            self._server.should_exit = True
            return True

    async def run_shutdown_callback(self, callback: Callable[[], Any]) -> None:
        """Run one shutdown hook within the shared deadline, then continue safely."""
        remaining = self.begin_shutdown()
        if remaining <= 0:
            _safe_stderr(
                f"[nucleus] shutdown budget exhausted; skipped {_callable_name(callback)}"
            )
            return

        async def invoke() -> None:
            if _is_async_callable(callback):
                result = callback()
            else:
                result = await asyncio.to_thread(callback)
            if inspect.isawaitable(result):
                await result

        task = asyncio.create_task(invoke(), name=f"nucleus-shutdown-{_callable_name(callback)}")
        done, _pending = await asyncio.wait({task}, timeout=remaining)
        if not done:
            task.cancel()
            task.add_done_callback(_consume_task_result)
            _safe_stderr(f"[nucleus] shutdown hook exceeded shared budget: {_callable_name(callback)}")
            return
        try:
            task.result()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _safe_stderr(
                f"[nucleus] shutdown hook failed: {_callable_name(callback)} ({type(exc).__name__})"
            )

    def _force_shutdown_exit(self) -> None:
        _safe_stderr("[nucleus] force-exit grace elapsed; terminating this managed generation")
        self._force_exit(124)

    def cancel_watchdog(self) -> None:
        with self._lock:
            watchdog, self._watchdog = self._watchdog, None
            self._watchdog_deadline = None
        if watchdog is not None:
            watchdog.cancel()


def _callable_name(callback: Callable[..., Any]) -> str:
    return str(getattr(callback, "__qualname__", getattr(callback, "__name__", "callback")))


def _is_async_callable(callback: Callable[..., Any]) -> bool:
    if inspect.iscoroutinefunction(callback):
        return True
    for cls in type(callback).__mro__:
        call_method = cls.__dict__.get("__call__")
        if call_method is not None:
            return inspect.iscoroutinefunction(call_method)
    return False


def _consume_task_result(task: asyncio.Task) -> None:
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.exception()


def _safe_stderr(message: str) -> None:
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass


class ManagedNucleusASGI:
    """Wrap NoneBot's app with admission fencing and private lifecycle endpoints."""

    def __init__(self, application: Any, lifecycle: NucleusLifecycle) -> None:
        self.application = application
        self.lifecycle = lifecycle

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            async def observe_lifespan(message: dict[str, Any]) -> None:
                if message.get("type") == "lifespan.startup.complete":
                    self.lifecycle.mark_ready()
                elif message.get("type") == "lifespan.startup.failed":
                    self.lifecycle.mark_startup_failed()
                elif message.get("type") == "lifespan.shutdown.complete":
                    self.lifecycle.mark_stopped()
                await send(message)

            await self.application(scope, receive, observe_lifespan)
            return

        path = scope.get("path", "")
        if scope_type == "http" and path in {HEALTH_PATH, DRAIN_PATH, STOP_PATH}:
            await self._control(scope, receive, send)
            return

        phase = self.lifecycle.phase
        if phase != "ready":
            code = "core_starting" if phase == "starting" else "core_draining"
            if phase == "startup_failed":
                code = "startup_failed"
            if phase == "stopped":
                code = "core_unavailable"
            if scope_type == "websocket":
                await receive()
                await send({"type": "websocket.close", "code": 1013, "reason": code})
            elif scope_type == "http":
                await _send_json(send, 503, {"ok": False, "error": {"code": code}})
            else:
                await self.application(scope, receive, send)
            return
        await self.application(scope, receive, send)

    async def _control(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        client = scope.get("client")
        try:
            peer = ipaddress.ip_address(client[0]) if client else None
        except (ValueError, TypeError):
            peer = None
        if peer is None or not peer.is_loopback:
            await _send_json(send, 404, {"ok": False, "error": {"code": "not_found"}})
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        expected = f"Bearer {self.lifecycle.launch_token}".encode("ascii")
        supplied = headers.get(b"authorization", b"")
        if not hmac.compare_digest(supplied, expected):
            await _send_json(send, 401, {"ok": False, "error": {"code": "unauthorized"}})
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET").upper()
        if path == HEALTH_PATH:
            if method != "GET":
                await _send_json(send, 405, {"ok": False, "error": {"code": "method_not_allowed"}})
                return
            phase = self.lifecycle.phase
            await _send_json(send, 200, {
                "control_protocol_version": CONTROL_PROTOCOL_VERSION,
                "instance_id": self.lifecycle.instance_id,
                "controller_boot_id": self.lifecycle.controller_boot_id,
                "generation_id": self.lifecycle.generation_id,
                "revision_id": self.lifecycle.revision_id,
                "pid": os.getpid(),
                "phase": phase,
                "ready": phase == "ready",
                "draining": phase in {"draining", "stopping"},
                "shutdown_remaining_seconds": self.lifecycle.remaining_shutdown_seconds()
                    if phase in {"draining", "stopping"} else None,
            })
            return

        if method != "POST":
            await _send_json(send, 405, {"ok": False, "error": {"code": "method_not_allowed"}})
            return
        body, too_large = await _read_body(receive)
        if too_large:
            await _send_json(send, 413, {"ok": False, "error": {"code": "request_too_large"}})
            return
        try:
            payload = json.loads(body or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            await _send_json(send, 400, {"ok": False, "error": {"code": "invalid_json"}})
            return
        if not isinstance(payload, dict) or not self._identity_matches(payload):
            await _send_json(send, 409, {"ok": False, "error": {"code": "identity_mismatch"}})
            return

        if path == DRAIN_PATH:
            timeout = payload.get("timeout_seconds", self.lifecycle.shutdown_budget_seconds)
            try:
                remaining = self.lifecycle.begin_drain(timeout)
            except (TypeError, ValueError):
                await _send_json(send, 400, {"ok": False, "error": {"code": "invalid_shutdown_budget"}})
                return
            await _send_json(send, 202, {
                "ok": True,
                "phase": self.lifecycle.phase,
                "generation_id": self.lifecycle.generation_id,
                "remaining_seconds": remaining,
            })
            return

        if path == STOP_PATH:
            if self.lifecycle.phase not in {"draining", "stopping"}:
                await _send_json(send, 409, {"ok": False, "error": {"code": "core_not_draining"}})
                return
            if not self.lifecycle.request_stop():
                await _send_json(send, 503, {"ok": False, "error": {"code": "core_unavailable"}})
                return
            await _send_json(send, 202, {
                "ok": True,
                "phase": self.lifecycle.phase,
                "generation_id": self.lifecycle.generation_id,
            })
            return

        await _send_json(send, 404, {"ok": False, "error": {"code": "not_found"}})

    def _identity_matches(self, payload: dict[str, Any]) -> bool:
        for key, expected in (
            ("instance_id", self.lifecycle.instance_id),
            ("controller_boot_id", self.lifecycle.controller_boot_id),
            ("generation_id", self.lifecycle.generation_id),
            ("revision_id", self.lifecycle.revision_id),
        ):
            candidate = payload.get(key)
            if not isinstance(candidate, str) or not candidate.isascii():
                return False
            if not hmac.compare_digest(candidate, expected):
                return False
        return True


async def _read_body(receive: Any, limit: int = 8192) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            return b"", False
        if message.get("type") != "http.request":
            continue
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > limit:
            return b"", True
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks), False


async def _send_json(send: Any, status: int, body: dict[str, Any]) -> None:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"cache-control", b"no-store"),
            (b"content-length", str(len(encoded)).encode("ascii")),
        ],
    })
    await send({"type": "http.response.body", "body": encoded})
