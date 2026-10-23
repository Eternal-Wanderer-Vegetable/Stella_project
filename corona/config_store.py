# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Crash-recoverable Corona-owned configuration revisions and ``.env`` writes."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella_bootstrap.adapter_names import parse_adapter_modules
from stella_bootstrap.config import (
    ConfigBuildError,
    build_config_revision,
    load_revision,
    revision_path,
    write_revision,
)
from stella_bootstrap.identity import INSTANCE_ID_PATTERN, runtime_dir
from stella_contracts.config import ConfigRevision, ConfigRevisionError

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SENSITIVE_MARKERS = ("TOKEN", "PASSWORD", "SECRET", "API_KEY")
_EXTRA_FIELDS = {
    "HOST": {"key": "HOST", "type": "string", "default": "0.0.0.0"},
    "PORT": {"key": "PORT", "type": "int", "default": "8080"},
    "ONEBOT_WS_URLS": {"key": "ONEBOT_WS_URLS", "type": "str_list", "default": ""},
    "ONEBOT_ACCESS_TOKEN": {
        "key": "ONEBOT_ACCESS_TOKEN",
        "type": "string",
        "default": "",
        "sensitive": True,
    },
}
_PROVIDER_DEFAULTS = {
    "CHAT": {
        "BASE_URL": "http://127.0.0.1:1234",
        "API_KEY": "",
        "MODEL": "",
        "KIND": "local",
        "CONCURRENCY": "1",
        "TIMEOUT": "120",
    },
    "MEMORY": {
        "BASE_URL": "http://127.0.0.1:1234",
        "API_KEY": "",
        "MODEL": "",
        "KIND": "local",
        "CONCURRENCY": "1",
        "TIMEOUT": "120",
    },
    "VISION": {
        "BASE_URL": "",
        "API_KEY": "",
        "MODEL": "",
        "KIND": "local",
        "CONCURRENCY": "1",
        "TIMEOUT": "120",
    },
}
_PROVIDER_TYPES = {
    "BASE_URL": "string",
    "API_KEY": "string",
    "MODEL": "string",
    "KIND": "choice",
    "CONCURRENCY": "int",
    "TIMEOUT": "float",
}
_PROVIDER_FIELDS = []
for _slot, _defaults in _PROVIDER_DEFAULTS.items():
    for _field, _default in _defaults.items():
        _schema_field = {
            "key": f"LLM_ENDPOINT_{_slot}_{_field}",
            "type": _PROVIDER_TYPES[_field],
            "default": _default,
        }
        if _field == "API_KEY":
            _schema_field["sensitive"] = True
        if _field == "KIND":
            _schema_field["choices"] = ["local", "online"]
        _PROVIDER_FIELDS.append(_schema_field)
_TERMINAL_TX = {"COMMITTED", "ABORTED", "CONFLICT"}
_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


class ConfigStoreError(RuntimeError):
    """A configuration commit could not be performed safely."""

    def __init__(self, code: str, *, current_revision: str | None = None):
        super().__init__(code)
        self.code = code
        self.current_revision = current_revision


@dataclass(frozen=True)
class ConfigStoreState:
    desired_revision: str
    applied_revision: str
    desired_core: str
    external_conflict: bool


def control_database_path(stella_home: Path, instance_id: str) -> Path:
    if not INSTANCE_ID_PATTERN.fullmatch(instance_id):
        raise ConfigStoreError("invalid_instance_id")
    return runtime_dir(stella_home, instance_id) / "corona" / "control.sqlite3"


class ConfigStore:
    """Serialize desired config writes and preserve enough state to recover a crash.

    The SQLite row is deliberately a recovery journal, not an attempt to claim that
    a SQLite commit and an ``.env`` rename form one atomic transaction.
    """

    def __init__(
        self,
        *,
        stella_home: Path,
        instance_id: str,
        project_root: Path,
        external_environment: Mapping[str, str] | None = None,
        settings_path: Path | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.stella_home = stella_home.expanduser().resolve()
        self.instance_id = instance_id
        if not INSTANCE_ID_PATTERN.fullmatch(instance_id):
            raise ConfigStoreError("invalid_instance_id")
        self.project_root = project_root.expanduser().resolve()
        self.settings_path = (
            settings_path or self.project_root / "config" / "settings.py"
        )
        self.external_environment = (
            None if external_environment is None else dict(external_environment)
        )
        self.env_path = self.stella_home / ".env"
        self.database_path = control_database_path(self.stella_home, instance_id)
        self.fault_hook = fault_hook
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.database_path), threading.RLock())

    def initialize(self, initial_revision: ConfigRevision) -> ConfigStoreState:
        """Create metadata on first launch, then recover transactions and edits."""
        with self._lock:
            self._ensure_database()
            self._ensure_schema()
            if self._meta("desired_revision") is None:
                revision = initial_revision
                try:
                    current = self._build_revision()
                    if current.source_digests != dict(initial_revision.source_digests):
                        revision = current
                except ConfigBuildError:
                    # Keep the known-good startup revision available to the
                    # repair UI; applying over invalid external contents fails closed.
                    pass
                path = revision_path(
                    self.stella_home, self.instance_id, revision.revision_id
                )
                if path.exists():
                    existing = load_revision(path)
                    if existing.to_dict() != revision.to_dict():
                        raise ConfigStoreError("revision_id_content_conflict")
                else:
                    path = write_revision(self.stella_home, self.instance_id, revision)
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    self._record_revision(
                        conn,
                        revision,
                        path,
                        origin="bootstrap",
                        actor={"via": "bootstrap"},
                    )
                    self._set_meta(conn, "desired_revision", revision.revision_id)
                    self._set_meta(conn, "applied_revision", revision.revision_id)
                    self._set_meta(conn, "desired_core", "running")
                    conn.commit()
            self.recover_pending_transactions()
            self._import_external_edits()
            return self.state()

    def state(self) -> ConfigStoreState:
        return ConfigStoreState(
            desired_revision=self._meta("desired_revision") or "",
            applied_revision=self._meta("applied_revision") or "",
            desired_core=self._meta("desired_core") or "running",
            external_conflict=self._meta("external_conflict") == "1",
        )

    def get_revision(self, revision_id: str) -> tuple[ConfigRevision, Path]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", revision_id or ""):
            raise ConfigStoreError("revision_not_found")
        row = self._one(
            "SELECT revision_path FROM config_revisions WHERE revision_id=?",
            (revision_id,),
        )
        if row is None:
            raise ConfigStoreError("revision_not_found")
        path = Path(row[0])
        try:
            revision = load_revision(path)
        except (OSError, ConfigRevisionError) as exc:
            raise ConfigStoreError("revision_unreadable") from exc
        if revision.revision_id != revision_id:
            raise ConfigStoreError("revision_unreadable")
        return revision, path

    def current_revision(self, which: str = "desired") -> tuple[ConfigRevision, Path]:
        revision_id = (
            self.state().applied_revision
            if which == "applied"
            else self.state().desired_revision
        )
        return self.get_revision(revision_id)

    def schema(self) -> list[dict[str, Any]]:
        from stella_bootstrap.env_schema import build_schema

        schema = build_schema(self.settings_path).get("fields", [])
        fields = {field["key"]: dict(field) for field in schema}
        for key, field in _EXTRA_FIELDS.items():
            fields.setdefault(key, dict(field))
        for field in _PROVIDER_FIELDS:
            fields.setdefault(field["key"], dict(field))
        return list(fields.values())

    def public_config(self) -> dict[str, Any]:
        revision, _path = self.current_revision("desired")
        applied = self.state().applied_revision
        fields = []
        for field in self.schema():
            key = field["key"]
            sensitive = _is_sensitive(key) or bool(field.get("sensitive"))
            value = revision.values.get(key)
            fields.append(
                {
                    "key": key,
                    "type": field.get("type"),
                    "default": field.get("default"),
                    "choices": field.get("choices") or field.get("options"),
                    "comment": field.get("description") or field.get("comment"),
                    "inherits": field.get("inherits"),
                    "sensitive": sensitive,
                    "present": key in revision.values,
                    "current_value": None if sensitive else value,
                    "has_value": bool(value),
                    "source": revision.sources.get(key, "default"),
                }
            )
        return {
            "fields": fields,
            "desired_revision": revision.revision_id,
            "applied_revision": applied,
            "env_file": str(self.env_path),
            "external_conflict": self.state().external_conflict,
        }

    def save(
        self,
        values: Mapping[str, Any],
        *,
        expected_revision: str | None,
        idempotency_key: str | None,
        actor: Mapping[str, str] | None = None,
        allowed_extra_keys: Iterable[str] = (),
        remove_keys: Iterable[str] = (),
        quote_keys: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Validate, stage, PREPARE, replace, and COMMIT one immutable revision."""
        updates, removals = self._normalize_updates(
            values,
            allowed_extra_keys=allowed_extra_keys,
            remove_keys=remove_keys,
        )
        quoted = set(quote_keys).intersection(updates)
        canonical = json.dumps(
            {
                "updates": updates,
                "remove": sorted(removals),
                "quote": sorted(quoted),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        request_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = _idempotency_key(idempotency_key)
        with self._lock:
            self._ensure_database()
            self._ensure_schema()
            if key:
                prior = self._one(
                    "SELECT request_digest, result_json FROM config_idempotency WHERE idempotency_key=?",
                    (key,),
                )
                if prior is not None:
                    if prior[0] != request_digest:
                        raise ConfigStoreError(
                            "idempotency_conflict",
                            current_revision=self.state().desired_revision,
                        )
                    return json.loads(prior[1])

            current_id = self.state().desired_revision
            if expected_revision is not None and expected_revision != current_id:
                raise ConfigStoreError("revision_conflict", current_revision=current_id)

            try:
                current_revision, _ = self.get_revision(current_id)
                before_bytes = (
                    self.env_path.read_bytes() if self.env_path.exists() else b""
                )
                if self._source_digests(
                    expected=current_revision.source_digests,
                    environment=current_revision.environment,
                ) != dict(current_revision.source_digests):
                    imported = self._import_external_edits()
                    raise ConfigStoreError(
                        "external_edit_conflict",
                        current_revision=imported or self.state().desired_revision,
                    )
                before_text = before_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ConfigStoreError(
                    "config_source_not_utf8", current_revision=current_id
                ) from exc
            except ConfigBuildError as exc:
                raise ConfigStoreError(
                    "config_source_invalid", current_revision=current_id
                ) from exc

            after_text = _patch_env(before_text, updates, removals, quoted)
            if after_text == before_text:
                result = self._save_result(
                    current_revision,
                    changed_keys=[],
                    sources=current_revision.sources,
                    restart_scope="nucleus",
                )
                self._record_idempotency(key, request_digest, result)
                return result

            try:
                candidate = build_config_revision(
                    project_root=self.project_root,
                    stella_home=self.stella_home,
                    external_environment=self.external_environment,
                    source_text_overrides={".env": after_text},
                    settings_path=self.settings_path,
                )
            except ConfigBuildError as exc:
                raise ConfigStoreError(
                    "config_validation_failed", current_revision=current_id
                ) from exc
            self._validate_extra_values(candidate, updates)
            for key_name, value in updates.items():
                source = candidate.sources.get(key_name)
                if source == "data_env" and candidate.values.get(key_name) != value:
                    raise ConfigStoreError(
                        "config_value_not_roundtrippable", current_revision=current_id
                    )

            candidate_path = write_revision(
                self.stella_home, self.instance_id, candidate
            )
            self._fault("revision_written")
            temp_path, after_digest, before_mode, before_exists = self._stage_env(
                after_text
            )
            self._fault("env_temp_fsynced")
            transaction_id = secrets.token_urlsafe(24)
            changed_keys = sorted(
                key_name
                for key_name in set(current_revision.values) | set(candidate.values)
                if current_revision.values.get(key_name)
                != candidate.values.get(key_name)
            )
            source_digests = candidate.source_digests
            actor_record = _safe_actor(actor)
            now = _now()
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                # Recheck both CAS inputs after all parsing and private-file writes.
                latest_id = self._meta_with(conn, "desired_revision") or ""
                if latest_id != current_id or self._source_digests(
                    expected=current_revision.source_digests,
                    environment=current_revision.environment,
                ) != dict(current_revision.source_digests):
                    conn.rollback()
                    temp_path.unlink(missing_ok=True)
                    raise ConfigStoreError(
                        "external_edit_conflict", current_revision=latest_id
                    )
                conn.execute(
                    """INSERT INTO config_transactions
                    (transaction_id,state,expected_revision,revision_id,before_digest,after_digest,
                     before_env,before_exists,after_exists,before_mode,source_digests_json,
                     changed_keys_json,actor_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        transaction_id,
                        "PREPARED",
                        current_id,
                        candidate.revision_id,
                        _sha256(before_bytes),
                        after_digest,
                        before_bytes,
                        int(before_exists),
                        1,
                        before_mode,
                        json.dumps(dict(source_digests), sort_keys=True),
                        json.dumps(changed_keys),
                        json.dumps(actor_record, sort_keys=True),
                        now,
                    ),
                )
                self._record_revision(
                    conn,
                    candidate,
                    candidate_path,
                    origin="save",
                    actor=actor_record,
                    expected_revision=current_id,
                    changed_keys=changed_keys,
                )
                conn.commit()
            self._fault("transaction_prepared")

            # Source digests other than .env must still match the before revision.
            if self._source_digests(
                expected=current_revision.source_digests,
                environment=current_revision.environment,
            ) != dict(current_revision.source_digests):
                self._mark_transaction(transaction_id, "CONFLICT")
                temp_path.unlink(missing_ok=True)
                raise ConfigStoreError(
                    "external_edit_conflict", current_revision=current_id
                )
            temp_path.replace(self.env_path)
            self._protect_file(self.env_path)
            _fsync_directory(self.env_path.parent)
            self._fault("env_replaced")
            if _sha256(self.env_path.read_bytes()) != after_digest:
                self._mark_transaction(transaction_id, "CONFLICT")
                raise ConfigStoreError(
                    "env_replace_verification_failed", current_revision=current_id
                )

            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE config_transactions SET state='COMMITTED' WHERE transaction_id=? AND state='PREPARED'",
                    (transaction_id,),
                )
                self._set_meta(conn, "desired_revision", candidate.revision_id)
                self._set_meta(conn, "external_conflict", "0")
                scope = _restart_scope(changed_keys)
                result = self._save_result(
                    candidate,
                    changed_keys=changed_keys,
                    sources=candidate.sources,
                    restart_scope=scope,
                )
                if key:
                    conn.execute(
                        "INSERT INTO config_idempotency(idempotency_key,request_digest,result_json,created_at) VALUES(?,?,?,?)",
                        (
                            key,
                            request_digest,
                            json.dumps(result, sort_keys=True),
                            _now(),
                        ),
                    )
                conn.commit()
            self._fault("transaction_committed")
            return result

    def recover_pending_transactions(self) -> list[dict[str, str]]:
        """Resolve PREPARED rows from the actual file digest; never guess."""
        results: list[dict[str, str]] = []
        with self._lock:
            self._ensure_database()
            self._ensure_schema()
            rows = self._all(
                "SELECT transaction_id,revision_id,before_digest,after_digest,before_exists,after_exists FROM config_transactions WHERE state='PREPARED' ORDER BY created_at"
            )
            actual = (
                _sha256(self.env_path.read_bytes())
                if self.env_path.exists()
                else _sha256(b"")
            )
            for (
                transaction_id,
                revision_id,
                before_digest,
                after_digest,
                before_exists,
                after_exists,
            ) in rows:
                actual_exists = self.env_path.exists()
                after_matches = actual == after_digest and actual_exists == bool(
                    after_exists
                )
                before_matches = actual == before_digest and actual_exists == bool(
                    before_exists
                )
                if after_matches:
                    with self._connect() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        conn.execute(
                            "UPDATE config_transactions SET state='COMMITTED' WHERE transaction_id=? AND state='PREPARED'",
                            (transaction_id,),
                        )
                        self._set_meta(conn, "desired_revision", revision_id)
                        self._set_meta(conn, "external_conflict", "0")
                        conn.commit()
                    results.append(
                        {"transaction_id": transaction_id, "state": "COMMITTED"}
                    )
                elif before_matches:
                    self._mark_transaction(transaction_id, "ABORTED")
                    results.append(
                        {"transaction_id": transaction_id, "state": "ABORTED"}
                    )
                else:
                    self._mark_transaction(transaction_id, "CONFLICT")
                    self._set_meta_value("external_conflict", "1")
                    results.append(
                        {"transaction_id": transaction_id, "state": "CONFLICT"}
                    )
            return results

    def restore_transaction_if_unchanged(self, transaction_id: str) -> dict[str, Any]:
        """Conditionally restore the exact prior ``.env`` bytes for one saved revision."""
        with self._lock:
            row = self._one(
                """SELECT state,expected_revision,revision_id,after_digest,before_env,before_exists,
                          before_mode,source_digests_json,changed_keys_json,purpose
                   FROM config_transactions WHERE transaction_id=?""",
                (transaction_id,),
            )
            if (
                row is None
                or row[0] not in {"COMMITTED", "PREPARED"}
                or row[9] != "save"
            ):
                raise ConfigStoreError("rollback_transaction_unavailable")
            (
                _state,
                previous_id,
                target_id,
                after_digest,
                before_env,
                before_exists,
                _before_mode,
                digests_json,
                changed_json,
                _purpose,
            ) = row
            current_revision_id = self.state().desired_revision
            if current_revision_id != target_id:
                return {
                    "restored": False,
                    "reason": "newer_desired_revision",
                    "desired_revision": current_revision_id,
                }
            if not self.env_path.exists():
                return {
                    "restored": False,
                    "reason": "external_env_edit",
                    "desired_revision": current_revision_id,
                }
            current_bytes = self.env_path.read_bytes()
            if _sha256(current_bytes) != after_digest:
                return {
                    "restored": False,
                    "reason": "external_env_edit",
                    "desired_revision": current_revision_id,
                }
            source_digests = json.loads(digests_json)
            target_revision, _target_path = self.get_revision(target_id)
            live_sources = self._source_digests(
                skip_env=True,
                expected=source_digests,
                environment=target_revision.environment,
            )
            expected_sources = {
                key: value for key, value in source_digests.items() if key != ".env"
            }
            if live_sources != expected_sources:
                return {
                    "restored": False,
                    "reason": "external_source_edit",
                    "desired_revision": current_revision_id,
                }

            previous, previous_path = self.get_revision(previous_id)
            restore_bytes = bytes(before_env)
            restore_digest = _sha256(restore_bytes) if before_exists else _sha256(b"")
            current_mode = stat.S_IMODE(self.env_path.stat().st_mode)
            restore_id = secrets.token_urlsafe(24)
            temp_path = (
                self._stage_bytes(restore_bytes, current_mode)
                if before_exists
                else None
            )
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                latest_id = self._meta_with(conn, "desired_revision") or ""
                if (
                    latest_id != target_id
                    or not self.env_path.exists()
                    or _sha256(self.env_path.read_bytes()) != after_digest
                ):
                    conn.rollback()
                    if temp_path is not None:
                        temp_path.unlink(missing_ok=True)
                    return {
                        "restored": False,
                        "reason": "newer_desired_revision",
                        "desired_revision": latest_id,
                    }
                conn.execute(
                    """INSERT INTO config_transactions
                    (transaction_id,state,expected_revision,revision_id,before_digest,after_digest,
                     before_env,before_exists,after_exists,before_mode,source_digests_json,
                     changed_keys_json,actor_json,created_at,purpose)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        restore_id,
                        "PREPARED",
                        target_id,
                        previous_id,
                        _sha256(current_bytes),
                        restore_digest,
                        current_bytes,
                        1,
                        int(bool(before_exists)),
                        current_mode,
                        json.dumps(dict(previous.source_digests), sort_keys=True),
                        json.dumps(json.loads(changed_json)),
                        json.dumps({"via": "config_recovery"}),
                        _now(),
                        "rollback",
                    ),
                )
                conn.commit()
            self._fault("rollback_prepared")

            if before_exists:
                assert temp_path is not None
                temp_path.replace(self.env_path)
                self._protect_file(self.env_path)
                _fsync_directory(self.env_path.parent)
            else:
                self.env_path.unlink(missing_ok=True)
                _fsync_directory(self.env_path.parent)
            self._fault("rollback_env_replaced")
            actual = (
                _sha256(self.env_path.read_bytes())
                if self.env_path.exists()
                else _sha256(b"")
            )
            if actual != restore_digest or self.env_path.exists() != bool(
                before_exists
            ):
                self._mark_transaction(restore_id, "CONFLICT")
                return {
                    "restored": False,
                    "reason": "rollback_replace_verification_failed",
                    "desired_revision": current_revision_id,
                }

            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE config_transactions SET state='COMMITTED' WHERE transaction_id=? AND state='PREPARED'",
                    (restore_id,),
                )
                conn.execute(
                    "UPDATE config_transactions SET state='ROLLED_BACK' WHERE transaction_id=?",
                    (transaction_id,),
                )
                self._set_meta(conn, "desired_revision", previous_id)
                self._set_meta(conn, "external_conflict", "0")
                conn.commit()
            self._fault("rollback_committed")
            return {
                "restored": True,
                "desired_revision": previous.revision_id,
                "revision_path": str(previous_path),
            }

    def set_applied_revision(self, revision_id: str) -> None:
        self.get_revision(revision_id)
        self._set_meta_value("applied_revision", revision_id)

    def refresh_external_edits(self) -> str | None:
        """Import a valid on-disk edit as a new desired revision without overwriting it."""
        with self._lock:
            return self._import_external_edits()

    def validate_revision(self, revision: ConfigRevision) -> None:
        if (
            Path(revision.project_root).resolve() != self.project_root
            or Path(revision.stella_home).resolve() != self.stella_home
        ):
            raise ConfigStoreError("revision_identity_mismatch")
        fields = {field["key"]: field for field in self.schema()}
        for key, value in revision.values.items():
            field = fields.get(key)
            if field is not None:
                _validate_field(key, value, field)
        self._validate_extra_values(revision, {})

    def set_desired_core(self, desired: str) -> None:
        if desired not in {"running", "stopped"}:
            raise ConfigStoreError("invalid_desired_core")
        self._set_meta_value("desired_core", desired)

    def transaction_for_revision(self, revision_id: str) -> str | None:
        row = self._one(
            "SELECT transaction_id FROM config_transactions WHERE revision_id=? AND state='COMMITTED' AND purpose='save' ORDER BY created_at DESC LIMIT 1",
            (revision_id,),
        )
        return row[0] if row else None

    def revision_record(self, revision_id: str) -> dict[str, Any] | None:
        row = self._one(
            "SELECT origin,expected_revision,changed_keys_json,actor_json,created_at FROM config_revisions WHERE revision_id=?",
            (revision_id,),
        )
        if row is None:
            return None
        return {
            "origin": row[0],
            "expected_revision": row[1],
            "changed_keys": json.loads(row[2]),
            "actor": json.loads(row[3]),
            "created_at": row[4],
        }

    def _normalize_updates(
        self,
        values: Mapping[str, Any],
        *,
        allowed_extra_keys: Iterable[str] = (),
        remove_keys: Iterable[str] = (),
    ) -> tuple[dict[str, str], set[str]]:
        if not isinstance(values, Mapping):
            raise ConfigStoreError("config_payload_invalid")
        fields = {field["key"]: field for field in self.schema()}
        updates: dict[str, str] = {}
        extras = set(allowed_extra_keys)
        removals = set(remove_keys)
        for key in extras | removals:
            if not isinstance(key, str) or not _ENV_KEY.fullmatch(key):
                raise ConfigStoreError("config_key_unknown")
        for key in extras:
            if key not in fields:
                fields[key] = {
                    "key": key,
                    "type": "string",
                    "sensitive": _is_sensitive(key),
                }
        if removals - fields.keys():
            raise ConfigStoreError("config_key_unknown")
        try:
            from deploy import env_keys
        except Exception:
            env_keys = None
        for key, raw_value in values.items():
            if (
                not isinstance(key, str)
                or key not in fields
                or not _ENV_KEY.fullmatch(key)
            ):
                raise ConfigStoreError("config_key_unknown")
            if env_keys is not None and (
                env_keys.deprecation_reason(key) or env_keys.superseded_by(key)
            ):
                raise ConfigStoreError("config_key_deprecated")
            field = fields[key]
            value = _scalar_to_text(raw_value)
            if "\n" in value or "\r" in value or "\x00" in value:
                raise ConfigStoreError("config_value_line_injection")
            sensitive = _is_sensitive(key) or bool(field.get("sensitive"))
            if sensitive and value == "":
                continue
            if field.get("inherits") and value == "":
                removals.add(key)
                continue
            choices = field.get("choices") or field.get("options") or ()
            if choices and value not in {str(choice) for choice in choices}:
                raise ConfigStoreError("config_value_choice_invalid")
            _validate_field(key, value, field)
            updates[key] = value
        if removals.intersection(updates):
            raise ConfigStoreError("config_key_unknown")
        return updates, removals

    def _validate_extra_values(
        self, revision: ConfigRevision, updates: Mapping[str, str]
    ) -> None:
        values = dict(revision.values)
        checks = dict(updates)
        checks.update({key: values[key] for key in _EXTRA_FIELDS if key in values})
        for key, value in checks.items():
            if key == "HOST":
                import ipaddress

                try:
                    ipaddress.ip_address(value)
                except ValueError as exc:
                    raise ConfigStoreError("config_value_invalid") from exc
            elif key == "PORT":
                _validate_port(value)
            elif key == "ONEBOT_WS_URLS":
                try:
                    urls = json.loads(value)
                except ValueError as exc:
                    raise ConfigStoreError("config_value_invalid") from exc
                if not isinstance(urls, list) or any(
                    not isinstance(url, str) or not url.startswith(("ws://", "wss://"))
                    for url in urls
                ):
                    raise ConfigStoreError("config_value_invalid")
            elif key == "STELLA_ADAPTER_MODULES":
                try:
                    parse_adapter_modules(value)
                except ValueError as exc:
                    raise ConfigStoreError("config_value_invalid") from exc

    def _build_revision(self) -> ConfigRevision:
        return build_config_revision(
            project_root=self.project_root,
            stella_home=self.stella_home,
            external_environment=self.external_environment,
            settings_path=self.settings_path,
        )

    def _import_external_edits(self) -> str | None:
        desired_id = self._meta("desired_revision")
        if not desired_id:
            return None
        try:
            desired, _ = self.get_revision(desired_id)
            if self._source_digests(
                expected=desired.source_digests,
                environment=desired.environment,
            ) == dict(desired.source_digests):
                self._set_meta_value("external_conflict", "0")
                return None
            imported = self._build_revision()
        except (ConfigBuildError, ConfigStoreError):
            self._set_meta_value("external_conflict", "1")
            return None
        path = write_revision(self.stella_home, self.instance_id, imported)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._record_revision(
                conn,
                imported,
                path,
                origin="external_edit",
                actor={"via": "external"},
                expected_revision=desired_id,
                changed_keys=sorted(
                    key
                    for key in set(desired.values) | set(imported.values)
                    if desired.values.get(key) != imported.values.get(key)
                ),
            )
            self._set_meta(conn, "desired_revision", imported.revision_id)
            self._set_meta(conn, "external_conflict", "0")
            conn.commit()
        return imported.revision_id

    def _source_digests(
        self,
        *,
        skip_env: bool = False,
        expected: Mapping[str, str] | None = None,
        environment: str | None = None,
    ) -> dict[str, str]:
        digests: dict[str, str] = {}
        names = set(expected) if expected is not None else {".env"}
        if environment and environment.strip().lower() in {"dev", "development"}:
            names.add(".env.dev")
        elif environment and environment.strip().lower() in {"prod", "production"}:
            names.add(".env.prod")
        for name in (".env", ".env.dev", ".env.prod"):
            if name not in names or (skip_env and name == ".env"):
                continue
            path = self.stella_home / name
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise ConfigBuildError("configuration source is unsafe")
                digests[name] = _sha256(path.read_bytes())
        return digests

    def _stage_env(self, text: str) -> tuple[Path, str, int, bool]:
        existed = self.env_path.exists()
        mode = stat.S_IMODE(self.env_path.stat().st_mode) if existed else 0o600
        temp_path = self._stage_bytes(text.encode("utf-8"), mode)
        return temp_path, _sha256(text.encode("utf-8")), mode, existed

    def _stage_bytes(self, payload: bytes, mode: int) -> Path:
        if self.env_path.is_symlink():
            raise ConfigStoreError("config_source_unsafe")
        self.env_path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(
            prefix=f".{self.env_path.name}.{secrets.token_hex(8)}.",
            suffix=".tmp",
            dir=self.env_path.parent,
        )
        path = Path(raw_path)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":
                path.chmod(0o600)
            else:
                _protect_windows_path(path)
            return path
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def _protect_file(self, path: Path) -> None:
        if os.name != "nt":
            path.chmod(0o600)
        else:
            _protect_windows_path(path)

    def _save_result(
        self,
        revision: ConfigRevision,
        *,
        changed_keys: list[str],
        sources: Mapping[str, str],
        restart_scope: str,
    ) -> dict[str, Any]:
        return {
            "revision_id": revision.revision_id,
            "changed_keys": list(changed_keys),
            "sources": {key: sources[key] for key in changed_keys if key in sources},
            "restart_scope": restart_scope,
            "desired_revision": revision.revision_id,
            "applied_revision": self.state().applied_revision,
        }

    def _record_idempotency(
        self, key: str | None, request_digest: str, result: dict
    ) -> None:
        if not key:
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO config_idempotency(idempotency_key,request_digest,result_json,created_at) VALUES(?,?,?,?)",
                (key, request_digest, json.dumps(result, sort_keys=True), _now()),
            )
            conn.commit()

    def _ensure_database(self) -> None:
        parent = self.database_path.parent
        for directory in (
            parent.parents[2],
            parent.parents[1],
            parent.parents[0],
            parent,
        ):
            if directory.is_symlink():
                raise ConfigStoreError("control_store_path_unsafe")
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                directory.chmod(0o700)
        if self.database_path.is_symlink():
            raise ConfigStoreError("control_store_path_unsafe")
        if not self.database_path.exists():
            fd = os.open(
                self.database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            os.close(fd)
        if os.name != "nt":
            self.database_path.chmod(0o600)
        else:
            _protect_windows_path(self.database_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS control_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS config_revisions (
                    revision_id TEXT PRIMARY KEY,
                    revision_path TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    expected_revision TEXT,
                    changed_keys_json TEXT NOT NULL,
                    actor_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS config_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    expected_revision TEXT NOT NULL,
                    revision_id TEXT NOT NULL,
                    before_digest TEXT NOT NULL,
                    after_digest TEXT NOT NULL,
                    before_env BLOB NOT NULL,
                    before_exists INTEGER NOT NULL,
                    after_exists INTEGER NOT NULL DEFAULT 1,
                    before_mode INTEGER NOT NULL,
                    source_digests_json TEXT NOT NULL,
                    changed_keys_json TEXT NOT NULL,
                    actor_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT 'save'
                );
                CREATE INDEX IF NOT EXISTS config_transactions_state_idx
                    ON config_transactions(state, created_at);
                CREATE TABLE IF NOT EXISTS config_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(config_transactions)")
            }
            if "after_exists" not in columns:
                conn.execute(
                    "ALTER TABLE config_transactions ADD COLUMN after_exists INTEGER NOT NULL DEFAULT 1"
                )
            if "purpose" not in columns:
                conn.execute(
                    "ALTER TABLE config_transactions ADD COLUMN purpose TEXT NOT NULL DEFAULT 'save'"
                )
            conn.commit()

    def _record_revision(
        self,
        conn: sqlite3.Connection,
        revision: ConfigRevision,
        path: Path,
        *,
        origin: str,
        actor: Mapping[str, str],
        expected_revision: str | None = None,
        changed_keys: list[str] | None = None,
    ) -> None:
        conn.execute(
            """INSERT OR IGNORE INTO config_revisions
            (revision_id,revision_path,origin,expected_revision,changed_keys_json,actor_json,created_at)
            VALUES(?,?,?,?,?,?,?)""",
            (
                revision.revision_id,
                str(path),
                origin,
                expected_revision,
                json.dumps(changed_keys or []),
                json.dumps(_safe_actor(actor), sort_keys=True),
                revision.created_at,
            ),
        )

    def _mark_transaction(self, transaction_id: str, state: str) -> None:
        if state not in _TERMINAL_TX:
            raise ConfigStoreError("invalid_transaction_state")
        with self._connect() as conn:
            conn.execute(
                "UPDATE config_transactions SET state=? WHERE transaction_id=? AND state='PREPARED'",
                (state, transaction_id),
            )
            conn.commit()

    def _meta(self, key: str) -> str | None:
        row = self._one("SELECT value FROM control_meta WHERE key=?", (key,))
        return row[0] if row else None

    def _meta_with(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute(
            "SELECT value FROM control_meta WHERE key=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO control_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _set_meta_value(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._set_meta(conn, key, value)
            conn.commit()

    def _one(self, sql: str, parameters: tuple = ()):
        with self._connect() as conn:
            return conn.execute(sql, parameters).fetchone()

    def _all(self, sql: str, parameters: tuple = ()):
        with self._connect() as conn:
            return conn.execute(sql, parameters).fetchall()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _fault(self, boundary: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(boundary)


def _patch_env(
    text: str,
    updates: Mapping[str, str],
    removals: set[str],
    quote_keys: set[str] | frozenset[str] = frozenset(),
) -> str:
    def encode(key: str, value: str) -> str:
        if key not in quote_keys:
            return value
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines = text.splitlines(keepends=True)
    output: list[str] = []
    for line in lines:
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        matched = False
        for key in removals:
            if _assignment_matches(body, key) and not _is_commented(body):
                matched = True
                break
        if matched:
            continue
        for key, value in updates.items():
            if _assignment_matches(body, key):
                output.append(f"{key}={encode(key, value)}{newline}")
                matched = True
                break
        if not matched:
            output.append(line)

    result = "".join(output)
    for key, value in updates.items():
        if not any(_assignment_matches(line.rstrip("\r\n"), key) for line in output):
            if result and not result.endswith(("\n", "\r")):
                result += "\n"
            result += f"{key}={encode(key, value)}\n"
    return result


def _assignment_matches(line: str, key: str) -> bool:
    return bool(re.match(rf"^\s*#?\s*{re.escape(key)}\s*=", line))


def _is_commented(line: str) -> bool:
    return line.lstrip().startswith("#")


def _scalar_to_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ConfigStoreError("config_value_invalid")
        return str(value)
    raise ConfigStoreError("config_value_scalar_required")


def _validate_field(key: str, value: str, field: Mapping[str, Any]) -> None:
    kind = field.get("type")
    stripped = value.strip()
    try:
        if kind == "int" and stripped:
            int(stripped)
        elif kind == "float" and stripped:
            if not math.isfinite(float(stripped)):
                raise ValueError
        elif kind == "bool" and stripped:
            if stripped.strip("\"'").lower() not in {
                "true",
                "false",
                "yes",
                "no",
                "1",
                "0",
                "on",
                "off",
            }:
                raise ValueError
        elif kind == "int_set" and stripped:
            for part in stripped.replace("，", ",").split(","):
                if part.strip():
                    int(part.strip())
        elif kind == "path" and stripped:
            Path(stripped).expanduser()
        elif kind == "choice" and stripped:
            choices = field.get("choices") or ()
            if choices and stripped.lower() not in {
                str(choice).lower() for choice in choices
            }:
                raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConfigStoreError("config_value_invalid") from exc
    if key == "PORT":
        _validate_port(stripped)


def _validate_port(value: str) -> None:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigStoreError("config_value_invalid") from exc
    if not 1 <= port <= 65535:
        raise ConfigStoreError("config_value_invalid")


def _is_sensitive(key: str) -> bool:
    return key.upper() == "ONEBOT_ACCESS_TOKEN" or any(
        marker in key.upper() for marker in _SENSITIVE_MARKERS
    )


def _restart_scope(keys: list[str]) -> str:
    control_prefixes = ("WEBUI_", "STELLA_CORONA_")
    if any(
        key in {"HOST", "PORT", "LOG_DIR"} or key.startswith(control_prefixes)
        for key in keys
    ):
        return "corona"
    return "nucleus"


def _idempotency_key(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    key = value.strip()
    if len(key) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
        raise ConfigStoreError("idempotency_key_invalid")
    return key


def _safe_actor(actor: Mapping[str, str] | None) -> dict[str, str]:
    if not actor:
        return {"via": "unknown"}
    safe = {}
    for key in ("username", "via"):
        value = actor.get(key)
        if isinstance(value, str):
            safe[key] = value[:128]
    return safe or {"via": "unknown"}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _protect_windows_path(path: Path) -> None:
    from stella_bootstrap.config import _set_windows_private_acl

    _set_windows_private_acl(path, is_directory=path.is_dir())
