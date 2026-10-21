# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Bounded file transport for Bot-to-Cometa-worker claim policy.

The directory is derived from STELLA_HOME and a hash of instance_id. Files are
small, atomically replaced, and contain no task, prompt, credential, or target
identifier. The host directory and same-user process boundary remain trusted.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import re
import secrets
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

MAX_POLICY_TTL_SECONDS = 10.0
MAX_POLICY_BYTES = 4096
MAX_ACK_BYTES = 2048
MAX_UTC_FUTURE_SKEW_SECONDS = 2.0
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_REASON_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")


@dataclass(frozen=True, slots=True)
class PolicyPaths:
    directory: Path
    policy: Path
    ack: Path


@dataclass(frozen=True, slots=True)
class ClaimDirective:
    claim_allowed: bool
    claim_limit: int
    restart_allowed: bool = False
    reason_code: str = "policy_current"

    def __post_init__(self) -> None:
        if not isinstance(self.claim_allowed, bool):
            raise ValueError("claim_allowed must be bool")
        if not isinstance(self.restart_allowed, bool):
            raise ValueError("restart_allowed must be bool")
        if (
            isinstance(self.claim_limit, bool)
            or not isinstance(self.claim_limit, int)
            or not 0 <= self.claim_limit <= 1024
        ):
            raise ValueError("claim_limit must be an integer from 0 to 1024")
        if self.claim_allowed and self.claim_limit == 0:
            raise ValueError("claim_limit must be positive when claims are allowed")
        if not isinstance(self.reason_code, str) or not _SAFE_REASON_RE.fullmatch(
            self.reason_code
        ):
            raise ValueError("reason_code must be a bounded low-cardinality code")


@dataclass(frozen=True, slots=True)
class CometaPolicyEnvelope:
    schema_version: int
    instance_id: str
    controller_boot_id: str
    worker_id: str
    process_identity_digest: str
    policy_revision: int
    config_hash: str
    issued_utc: float
    ttl_seconds: float
    claim_allowed: bool
    claim_limit: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != 1
        ):
            raise ValueError("unsupported Cometa policy schema")
        for name, value, limit in (
            ("instance_id", self.instance_id, 128),
            ("controller_boot_id", self.controller_boot_id, 128),
            ("worker_id", self.worker_id, 128),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be non-empty and trimmed")
            if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError(f"{name} exceeds the safe identifier bound")
        if (
            isinstance(self.policy_revision, bool)
            or not isinstance(self.policy_revision, int)
            or self.policy_revision < 1
        ):
            raise ValueError("policy_revision must be a positive integer")
        if not isinstance(self.process_identity_digest, str) or not _DIGEST_RE.fullmatch(
            self.process_identity_digest
        ):
            raise ValueError("process_identity_digest is invalid")
        if not isinstance(self.config_hash, str) or not _DIGEST_RE.fullmatch(
            self.config_hash
        ):
            raise ValueError("config_hash is invalid")
        if (
            isinstance(self.issued_utc, bool)
            or not isinstance(self.issued_utc, (int, float))
            or not math.isfinite(float(self.issued_utc))
        ):
            raise ValueError("issued_utc must be finite")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, (int, float))
            or not 0 < float(self.ttl_seconds) <= MAX_POLICY_TTL_SECONDS
        ):
            raise ValueError("ttl_seconds is outside the supported bound")
        if not isinstance(self.claim_allowed, bool):
            raise ValueError("claim_allowed must be bool")
        if (
            isinstance(self.claim_limit, bool)
            or not isinstance(self.claim_limit, int)
            or not 0 <= self.claim_limit <= 1024
        ):
            raise ValueError("claim_limit must be an integer from 0 to 1024")
        if self.claim_allowed and self.claim_limit == 0:
            raise ValueError("claim_limit must be positive when claims are allowed")

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: object) -> "CometaPolicyEnvelope":
        if not isinstance(payload, dict):
            raise ValueError("policy root must be an object")
        expected = {field.name for field in dataclasses.fields(cls)}
        if set(payload) != expected:
            raise ValueError("policy fields do not match schema")
        return cls(**payload)


def process_identity_digest(process_identity: str) -> str:
    if not isinstance(process_identity, str) or not process_identity.strip():
        raise ValueError("process_identity must be non-empty")
    digest = hashlib.sha256(process_identity.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def config_fingerprint(config: object) -> str:
    """Hash the effective typed config without writing any values to the file."""

    if not dataclasses.is_dataclass(config):
        raise TypeError("config must be a dataclass")

    def normalize(value: object) -> object:
        if isinstance(value, Path):
            return str(value.expanduser().resolve())
        if dataclasses.is_dataclass(value):
            return normalize(dataclasses.asdict(value))
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in sorted(value.items())}
        if isinstance(value, (set, frozenset)):
            return sorted(normalize(item) for item in value)
        if isinstance(value, (tuple, list)):
            return [normalize(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise TypeError(f"unsupported config value: {type(value).__name__}")

    wire = json.dumps(
        normalize(config), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return "sha256:" + hashlib.sha256(wire.encode("utf-8")).hexdigest()


def policy_paths(stella_home: str | Path, instance_id: str) -> PolicyPaths:
    if not isinstance(instance_id, str) or not instance_id.strip():
        raise ValueError("instance_id must be non-empty")
    root = Path(stella_home).expanduser().resolve()
    scope = hashlib.sha256(instance_id.encode("utf-8")).hexdigest()[:32]
    directory = root / "state" / "gravitas" / "cometa" / scope
    return PolicyPaths(directory, directory / "policy.json", directory / "ack.json")


def _encode_json(payload: dict[str, object], *, max_bytes: int) -> bytes:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(raw) > max_bytes:
        raise ValueError("policy file exceeds size limit")
    return raw


def atomic_write_json(
    path: str | Path,
    payload: dict[str, object],
    *,
    max_bytes: int = MAX_POLICY_BYTES,
) -> None:
    target = Path(path)
    raw = _encode_json(payload, max_bytes=max_bytes)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        target.parent.chmod(0o700)
    temp_name = f".{target.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    temp_path = target.parent / temp_name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(temp_path, flags, 0o600)
    try:
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        temp_path.replace(target)
        if os.name != "nt":
            with contextlib.suppress(OSError):
                dir_fd = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp_path.unlink()


def read_json_bounded(path: str | Path, *, max_bytes: int) -> dict[str, object]:
    target = Path(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    fd = os.open(target, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("policy file is not a regular file")
        if info.st_size > max_bytes:
            raise ValueError("policy file exceeds size limit")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("policy file exceeds size limit")
    finally:
        os.close(fd)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("policy root must be an object")
    return value


@dataclass(frozen=True, slots=True)
class ClaimDecision:
    allowed: bool
    claim_limit: int = 0
    policy_revision: int = 0
    reason_code: str = "policy_unavailable"

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be bool")
        if (
            isinstance(self.claim_limit, bool)
            or not isinstance(self.claim_limit, int)
            or not 0 <= self.claim_limit <= 1024
        ):
            raise ValueError("claim_limit must be an integer from 0 to 1024")
        if self.allowed and self.claim_limit < 1:
            raise ValueError("claim_limit must be positive when claims are allowed")
        if (
            isinstance(self.policy_revision, bool)
            or not isinstance(self.policy_revision, int)
            or self.policy_revision < 0
        ):
            raise ValueError("policy_revision must be a non-negative integer")
        if not isinstance(self.reason_code, str) or not _SAFE_REASON_RE.fullmatch(
            self.reason_code
        ):
            raise ValueError("reason_code must be a bounded low-cardinality code")


class WorkerPolicyReader:
    """Validate one host policy and fence its TTL with local monotonic time."""

    def __init__(
        self,
        *,
        paths: PolicyPaths,
        instance_id: str,
        controller_boot_id: str,
        worker_id: str,
        process_identity: str,
        config_hash: str,
        monotonic: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.paths = paths
        self.instance_id = instance_id
        self.controller_boot_id = controller_boot_id
        self.worker_id = worker_id
        try:
            self._process_digest = process_identity_digest(process_identity)
        except ValueError:
            self._process_digest = ""
        self.config_hash = config_hash
        self._monotonic = monotonic
        self._wall = wall
        self._last_revision = 0
        self._last_issued_utc = 0.0
        self._accepted_digest = ""
        self._accepted: CometaPolicyEnvelope | None = None
        self._expires_monotonic = 0.0
        self._last_clock_sample: tuple[float, float] | None = None
        self._clock_invalid = False

    def evaluate(self) -> ClaimDecision:
        now_mono = self._monotonic()
        now_wall = self._wall()
        if (
            not math.isfinite(now_mono)
            or not math.isfinite(now_wall)
            or now_mono < 0
            or now_wall < 0
        ):
            self._clock_invalid = True
            return self._deny("policy_clock_invalid", self._last_revision)
        previous_sample = self._last_clock_sample
        self._last_clock_sample = (now_mono, now_wall)
        if previous_sample is not None:
            mono_delta = now_mono - previous_sample[0]
            wall_delta = now_wall - previous_sample[1]
            if (
                mono_delta < 0
                or wall_delta < 0
                or abs(wall_delta - mono_delta) > MAX_UTC_FUTURE_SKEW_SECONDS
            ):
                self._clock_invalid = True
        if self._clock_invalid:
            return self._deny("policy_clock_jump", self._last_revision)
        context = (
            self.instance_id,
            self.controller_boot_id,
            self.worker_id,
            self._process_digest,
            self.config_hash,
        )
        if not all(isinstance(item, str) and item for item in context):
            return self._deny("worker_binding_missing", 0)
        try:
            payload = read_json_bounded(self.paths.policy, max_bytes=MAX_POLICY_BYTES)
            envelope = CometaPolicyEnvelope.from_dict(payload)
        except FileNotFoundError:
            return self._deny("policy_missing", 0)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            return self._deny("policy_invalid", 0)

        if (
            envelope.instance_id != self.instance_id
            or envelope.controller_boot_id != self.controller_boot_id
            or envelope.worker_id != self.worker_id
            or envelope.process_identity_digest != self._process_digest
            or envelope.config_hash != self.config_hash
        ):
            return self._deny("policy_binding_mismatch", envelope.policy_revision)

        digest = hashlib.sha256(_encode_json(payload, max_bytes=MAX_POLICY_BYTES)).hexdigest()
        if envelope.policy_revision == self._last_revision:
            if (
                self._accepted is None
                or digest != self._accepted_digest
                or now_mono >= self._expires_monotonic
            ):
                return self._deny("policy_replay_or_expired", envelope.policy_revision)
            return self._accept(envelope)
        if envelope.policy_revision < self._last_revision:
            return self._deny("policy_replay", envelope.policy_revision)

        age = now_wall - float(envelope.issued_utc)
        if (
            envelope.issued_utc < self._last_issued_utc
            or age < -MAX_UTC_FUTURE_SKEW_SECONDS
            or age >= envelope.ttl_seconds
        ):
            return self._deny("policy_time_invalid", envelope.policy_revision)
        self._last_revision = envelope.policy_revision
        self._last_issued_utc = float(envelope.issued_utc)
        self._accepted_digest = digest
        self._accepted = envelope
        self._expires_monotonic = now_mono + max(0.0, envelope.ttl_seconds - max(0.0, age))
        return self._accept(envelope)

    def _accept(self, envelope: CometaPolicyEnvelope) -> ClaimDecision:
        reason = "policy_current"
        if not envelope.claim_allowed or envelope.claim_limit < 1:
            reason = "claims_paused"
        if not self._write_ack(
            envelope.policy_revision,
            applied=True,
            reason_code=reason,
        ):
            return ClaimDecision(False, reason_code="ack_write_failed")
        return ClaimDecision(
            allowed=envelope.claim_allowed and envelope.claim_limit > 0,
            claim_limit=envelope.claim_limit if envelope.claim_allowed else 0,
            policy_revision=envelope.policy_revision,
            reason_code=reason,
        )

    def _deny(self, reason_code: str, revision: int) -> ClaimDecision:
        self._write_ack(revision, applied=False, reason_code=reason_code)
        return ClaimDecision(False, policy_revision=revision, reason_code=reason_code)

    def _write_ack(self, revision: int, *, applied: bool, reason_code: str) -> bool:
        if not self.instance_id or not self.controller_boot_id or not self.worker_id:
            return False
        try:
            atomic_write_json(
                self.paths.ack,
                {
                    "schema_version": 1,
                    "instance_id": self.instance_id,
                    "controller_boot_id": self.controller_boot_id,
                    "worker_id": self.worker_id,
                    "process_identity_digest": self._process_digest,
                    "policy_revision": max(0, int(revision)),
                    "applied": bool(applied),
                    "acknowledged_utc": float(self._wall()),
                    "reason_code": reason_code,
                },
                max_bytes=MAX_ACK_BYTES,
            )
            return True
        except (OSError, TypeError, ValueError):
            return False


class CometaPolicyPublisher:
    """Bot-side publisher with monotonically increasing transport revisions."""

    def __init__(
        self,
        *,
        paths: PolicyPaths,
        config: object,
        instance_id: str,
        controller_boot_id: str,
        worker_id: Callable[[], str],
        process_identity: Callable[[], str],
        directive: Callable[[], ClaimDirective | None],
        ttl_seconds: float = MAX_POLICY_TTL_SECONDS,
        wall: Callable[[], float] = time.time,
    ) -> None:
        if not 0 < ttl_seconds <= MAX_POLICY_TTL_SECONDS:
            raise ValueError("ttl_seconds is outside the supported bound")
        self.paths = paths
        self.config_hash = config_fingerprint(config)
        self.instance_id = instance_id
        self.controller_boot_id = controller_boot_id
        self._worker_id = worker_id
        self._process_identity = process_identity
        self._directive = directive
        self.ttl_seconds = float(ttl_seconds)
        self._wall = wall
        self._revision = 0
        self._last_envelope: CometaPolicyEnvelope | None = None

    def current_directive(self) -> ClaimDirective:
        try:
            directive = self._directive()
        except Exception:
            directive = None
        if directive is None:
            return ClaimDirective(False, 0, reason_code="policy_unavailable")
        if not isinstance(directive, ClaimDirective):
            return ClaimDirective(False, 0, reason_code="policy_invalid")
        return directive

    def publish_once(
        self, *, directive_override: ClaimDirective | None = None
    ) -> CometaPolicyEnvelope | None:
        worker_id = self._worker_id()
        process_identity = self._process_identity()
        if not self.instance_id or not self.controller_boot_id or not worker_id:
            return None
        directive = directive_override or self.current_directive()
        if not isinstance(directive, ClaimDirective):
            directive = ClaimDirective(False, 0, reason_code="policy_invalid")
        self._revision += 1
        envelope = CometaPolicyEnvelope(
            schema_version=1,
            instance_id=self.instance_id,
            controller_boot_id=self.controller_boot_id,
            worker_id=worker_id,
            process_identity_digest=process_identity_digest(process_identity),
            policy_revision=self._revision,
            config_hash=self.config_hash,
            issued_utc=float(self._wall()),
            ttl_seconds=self.ttl_seconds,
            claim_allowed=directive.claim_allowed,
            claim_limit=directive.claim_limit,
        )
        atomic_write_json(self.paths.policy, envelope.to_dict())
        self._last_envelope = envelope
        return envelope

    def status_snapshot(self) -> dict[str, object]:
        envelope = self._last_envelope
        if envelope is None:
            return {
                "state": "not_received",
                "reason_code": "policy_not_published",
                "policy_revision": 0,
                "applied": False,
            }
        try:
            ack = read_json_bounded(self.paths.ack, max_bytes=MAX_ACK_BYTES)
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
            ack = {}
        ack_fields = {
            "schema_version",
            "instance_id",
            "controller_boot_id",
            "worker_id",
            "process_identity_digest",
            "policy_revision",
            "applied",
            "acknowledged_utc",
            "reason_code",
        }
        ack_revision = ack.get("policy_revision")
        ack_time = ack.get("acknowledged_utc")
        ack_reason = ack.get("reason_code")
        matches = (
            set(ack) == ack_fields
            and isinstance(ack.get("schema_version"), int)
            and not isinstance(ack.get("schema_version"), bool)
            and ack.get("schema_version") == 1
            and ack.get("instance_id") == envelope.instance_id
            and ack.get("controller_boot_id") == envelope.controller_boot_id
            and ack.get("worker_id") == envelope.worker_id
            and ack.get("process_identity_digest") == envelope.process_identity_digest
            and isinstance(ack_revision, int)
            and not isinstance(ack_revision, bool)
            and ack_revision == envelope.policy_revision
            and isinstance(ack.get("applied"), bool)
            and isinstance(ack_time, (int, float))
            and not isinstance(ack_time, bool)
            and math.isfinite(float(ack_time))
            and isinstance(ack_reason, str)
            and _SAFE_REASON_RE.fullmatch(ack_reason) is not None
        )
        applied = bool(matches and ack.get("applied") is True)
        return {
            "state": (
                "applied"
                if applied
                else "rejected"
                if matches
                else "not_received"
            ),
            "reason_code": (
                ack.get("reason_code", "ack_not_received")
                if matches
                else "ack_not_received"
            ),
            "policy_revision": envelope.policy_revision,
            "applied": applied,
            "claim_allowed": envelope.claim_allowed,
            "claim_limit": envelope.claim_limit,
        }

    @property
    def last_envelope(self) -> CometaPolicyEnvelope | None:
        return self._last_envelope


@dataclass(slots=True)
class WorkerRestartBudget:
    """Bound opt-in worker restarts to a sliding window with exponential delay."""

    max_restarts: int = 2
    window_seconds: float = 600.0
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 60.0
    monotonic: Callable[[], float] = time.monotonic
    _attempts: list[float] = field(default_factory=list)

    def reserve_delay(self, *, now: float | None = None) -> float | None:
        current = self.monotonic() if now is None else float(now)
        if not math.isfinite(current):
            return None
        self._attempts = [
            item for item in self._attempts if current - item < self.window_seconds
        ]
        if len(self._attempts) >= self.max_restarts:
            return None
        delay = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** len(self._attempts)),
        )
        self._attempts.append(current)
        return max(0.0, float(delay))


__all__ = [
    "ClaimDecision",
    "ClaimDirective",
    "CometaPolicyEnvelope",
    "CometaPolicyPublisher",
    "PolicyPaths",
    "WorkerPolicyReader",
    "WorkerRestartBudget",
    "atomic_write_json",
    "config_fingerprint",
    "policy_paths",
    "process_identity_digest",
    "read_json_bounded",
]
