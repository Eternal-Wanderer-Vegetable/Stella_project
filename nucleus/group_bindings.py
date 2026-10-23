# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Crash-recoverable, idempotent Nucleus space-binding operations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any

from webui.responses import ApiError

_SPACE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_GROUP_ID = re.compile(r"^[0-9]{1,20}$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class GroupBindingsStore:
    """Journal each multi-file binding change before replacing any space file."""

    def __init__(self, *, spaces_directory: Path, journal_path: Path) -> None:
        self.spaces_directory = Path(spaces_directory).expanduser().resolve()
        self.journal_path = Path(journal_path).expanduser().resolve()
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.journal_path), threading.RLock())
        self._ensure_schema()
        self.recover_pending()

    @classmethod
    def configured(cls) -> GroupBindingsStore:
        import config.settings as settings
        from stella_bootstrap.identity import resolve_instance_id, runtime_dir
        from webui.services import spaces as spaces_service

        instance_id = resolve_instance_id(Path(settings.PROJECT_ROOT))
        journal = (
            runtime_dir(Path(settings.STELLA_HOME), instance_id)
            / "nucleus"
            / "group_bindings.sqlite3"
        )
        return cls(spaces_directory=spaces_service.spaces_dir(), journal_path=journal)

    def validate(self, payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        bindings = normalize_bindings(payload)
        return bindings, {"digest": self.snapshot_digest()}

    def snapshot_digest(self) -> str:
        return _snapshot_digest(self._read_files())

    def apply(
        self,
        *,
        operation_id: str,
        bindings: Any,
        expected_digest: str,
    ) -> dict[str, Any]:
        canonical = normalize_bindings(bindings)
        request_digest = _digest_json(
            {"bindings": canonical, "expected_digest": expected_digest}
        )
        with self._lock:
            prior = self._one(
                "SELECT request_digest,state,result_json FROM group_binding_operations WHERE operation_id=?",
                (operation_id,),
            )
            if prior is not None:
                if prior[0] != request_digest:
                    raise ApiError("operation_id_conflict", status_code=409)
                if prior[1] == "APPLIED":
                    return json.loads(prior[2])
                if prior[1] in {"PREPARED", "ABORTED"}:
                    raise ApiError(
                        "group_binding_operation_not_applied", status_code=409
                    )
                raise ApiError("group_binding_operation_conflict", status_code=409)

            before = self._read_files()
            before_digest = _snapshot_digest(before)
            if expected_digest != before_digest:
                raise ApiError("spaces_revision_conflict", status_code=409)
            after = _files_with_bindings(before, canonical)
            after_digest = _snapshot_digest(after)
            result = {
                "operation_id": operation_id,
                "applied": True,
                "digest": after_digest,
            }
            self._insert_operation(
                operation_id=operation_id,
                request_digest=request_digest,
                before=before,
                after=after,
                before_digest=before_digest,
                after_digest=after_digest,
                result=result,
            )
            try:
                self._write_files(after, expected_files=before)
                if self.snapshot_digest() != after_digest:
                    raise ApiError("spaces_write_verification_failed", status_code=503)
            except Exception:
                try:
                    restored = self._restore_partial(
                        before=before,
                        after=after,
                        before_digest=before_digest,
                    )
                    state = (
                        "ABORTED" if restored else "CONFLICT"
                    )
                except Exception:
                    state = "CONFLICT"
                self._set_state(operation_id, state)
                raise
            self._set_state(operation_id, "APPLIED")
            return result

    def rollback(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._one(
                "SELECT state,before_json,after_digest FROM group_binding_operations WHERE operation_id=?",
                (operation_id,),
            )
            if row is None:
                return {"operation_id": operation_id, "restored": True, "noop": True}
            state, before_json, after_digest = row
            if state == "ROLLED_BACK":
                return {"operation_id": operation_id, "restored": True}
            if state != "APPLIED":
                return {
                    "operation_id": operation_id,
                    "restored": False,
                    "reason": "operation_not_applied",
                }
            if self.snapshot_digest() != after_digest:
                self._set_state(operation_id, "CONFLICT")
                return {
                    "operation_id": operation_id,
                    "restored": False,
                    "reason": "external_spaces_edit",
                }
            before = _decode_files(json.loads(before_json))
            before_digest = _snapshot_digest(before)
            try:
                self._write_files(before, expected_files=self._read_files())
            except Exception:
                self._set_state(operation_id, "CONFLICT")
                return {
                    "operation_id": operation_id,
                    "restored": False,
                    "reason": "spaces_restore_failed",
                }
            if self.snapshot_digest() != before_digest:
                self._set_state(operation_id, "CONFLICT")
                return {
                    "operation_id": operation_id,
                    "restored": False,
                    "reason": "spaces_restore_verification_failed",
                }
            self._set_state(operation_id, "ROLLED_BACK")
            return {"operation_id": operation_id, "restored": True}

    def recover_pending(self) -> list[dict[str, str]]:
        """Resolve interrupted writes from recorded before/after file snapshots."""
        recovered = []
        with self._lock:
            rows = self._all(
                "SELECT operation_id,state,before_json,after_json,before_digest,after_digest FROM group_binding_operations WHERE state='PREPARED'"
            )
            for (
                operation_id,
                _state,
                before_json,
                _after_json,
                before_digest,
                after_digest,
            ) in rows:
                current = self.snapshot_digest()
                if current == after_digest:
                    state = "APPLIED"
                elif current == before_digest:
                    state = "ABORTED"
                else:
                    try:
                        before = _decode_files(json.loads(before_json))
                        after = _decode_files(json.loads(_after_json))
                        restored = self._restore_partial(
                            before=before,
                            after=after,
                            before_digest=before_digest,
                        )
                        state = "ABORTED" if restored else "CONFLICT"
                    except Exception:
                        state = "CONFLICT"
                self._set_state(operation_id, state)
                recovered.append({"operation_id": operation_id, "state": state})
        return recovered

    def _read_files(self) -> dict[str, bytes]:
        self.spaces_directory.mkdir(parents=True, exist_ok=True)
        files: dict[str, bytes] = {}
        total = 0
        for path in sorted(self.spaces_directory.glob("*.toml")):
            if not _SPACE_NAME.fullmatch(path.stem) or path.is_symlink():
                raise ApiError("spaces_path_unsafe", status_code=409)
            content = path.read_bytes()
            total += len(content)
            if total > 16 * 1024 * 1024:
                raise ApiError("spaces_snapshot_too_large", status_code=413)
            files[path.stem] = content
        return files

    def _write_files(
        self,
        files: dict[str, bytes],
        *,
        expected_files: dict[str, bytes] | None = None,
    ) -> None:
        self.spaces_directory.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            if not _SPACE_NAME.fullmatch(name):
                raise ApiError("spaces_path_unsafe", status_code=409)
            path = self.spaces_directory / f"{name}.toml"
            if path.is_symlink():
                raise ApiError("spaces_path_unsafe", status_code=409)
            current = path.read_bytes() if path.exists() else None
            if expected_files is not None and current != expected_files.get(name):
                raise ApiError("spaces_revision_conflict", status_code=409)
            if current == content:
                continue
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{name}.", suffix=".tmp", dir=self.spaces_directory
            )
            temp_path = Path(temp_name)
            try:
                if os.name != "nt":
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                temp_path.replace(path)
            finally:
                temp_path.unlink(missing_ok=True)
        removed_names = (
            set(expected_files) - set(files) if expected_files is not None else set()
        )
        for name in sorted(removed_names):
            path = self.spaces_directory / f"{name}.toml"
            if path.is_symlink():
                raise ApiError("spaces_path_unsafe", status_code=409)
            current = path.read_bytes() if path.exists() else None
            if current != expected_files[name]:
                raise ApiError("spaces_revision_conflict", status_code=409)
            path.unlink(missing_ok=True)
        try:
            descriptor = os.open(self.spaces_directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
        from config import spaces as spaces_mod

        spaces_mod.reload()

    def _restore_partial(
        self,
        *,
        before: dict[str, bytes],
        after: dict[str, bytes],
        before_digest: str,
    ) -> bool:
        current = self._read_files()
        controlled = set(before) | set(after)
        if set(current) - controlled:
            return False
        for name in controlled:
            if current.get(name) not in {before.get(name), after.get(name)}:
                return False
        self._write_files(before, expected_files=current)
        return self.snapshot_digest() == before_digest

    def _ensure_schema(self) -> None:
        parent = self.journal_path.parent
        if parent.is_symlink():
            raise ApiError("group_binding_journal_unsafe", status_code=503)
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            parent.chmod(0o700)
        if self.journal_path.is_symlink():
            raise ApiError("group_binding_journal_unsafe", status_code=503)
        if not self.journal_path.exists():
            fd = os.open(
                self.journal_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.close(fd)
        if os.name != "nt":
            self.journal_path.chmod(0o600)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS group_binding_operations (
                    operation_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    before_json TEXT NOT NULL,
                    after_json TEXT NOT NULL,
                    before_digest TEXT NOT NULL,
                    after_digest TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _insert_operation(
        self,
        *,
        operation_id: str,
        request_digest: str,
        before: dict[str, bytes],
        after: dict[str, bytes],
        before_digest: str,
        after_digest: str,
        result: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO group_binding_operations
                (operation_id,request_digest,state,before_json,after_json,before_digest,after_digest,result_json)
                VALUES(?,?,'PREPARED',?,?,?,?,?)""",
                (
                    operation_id,
                    request_digest,
                    json.dumps(_encode_files(before), sort_keys=True),
                    json.dumps(_encode_files(after), sort_keys=True),
                    before_digest,
                    after_digest,
                    json.dumps(result, sort_keys=True),
                ),
            )
            conn.commit()

    def _set_state(self, operation_id: str, state: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE group_binding_operations SET state=? WHERE operation_id=?",
                (state, operation_id),
            )
            conn.commit()

    def _one(self, sql: str, params: tuple = ()):
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple = ()):
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.journal_path, timeout=10, isolation_level=None
        )
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA synchronous=FULL")
        return connection


def normalize_bindings(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ApiError("groups_payload_invalid")
    seen: dict[int, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ApiError("groups_payload_invalid")
        raw_group_id = item.get("group_id")
        if isinstance(raw_group_id, bool):
            raise ApiError("group_id_invalid")
        group_text = str(raw_group_id)
        if not _GROUP_ID.fullmatch(group_text):
            raise ApiError("group_id_invalid")
        group_id = int(group_text)
        if group_id <= 0:
            raise ApiError("group_id_invalid")
        space = item.get("space")
        if not isinstance(space, str) or not _SPACE_NAME.fullmatch(space):
            raise ApiError("space_name_invalid")
        prior = seen.get(group_id)
        if prior is not None and prior != space:
            raise ApiError("group_bound_to_multiple_spaces", status_code=409)
        seen[group_id] = space
    return [
        {"group_id": group_id, "space": space}
        for group_id, space in sorted(seen.items())
    ]


def _files_with_bindings(
    before: dict[str, bytes], bindings: list[dict[str, Any]]
) -> dict[str, bytes]:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10
        import tomli as tomllib

    by_space: dict[str, list[int]] = {}
    for item in bindings:
        by_space.setdefault(item["space"], []).append(item["group_id"])
    all_names = set(before) | set(by_space)
    after: dict[str, bytes] = {}
    for name in sorted(all_names):
        prior: dict[str, Any] = {}
        if name in before:
            try:
                prior = tomllib.loads(before[name].decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ApiError("space_config_invalid", status_code=409) from exc
        groups = by_space.get(name, [])
        lines = [f"qq_groups = {json.dumps(groups)}"]
        system_prompt = prior.get("system_prompt")
        if system_prompt:
            if not isinstance(system_prompt, str):
                raise ApiError("space_config_invalid", status_code=409)
            lines.append(f"system_prompt = {json.dumps(system_prompt)}")
        after[name] = ("\n".join(lines) + "\n").encode("utf-8")
    return after


def _snapshot_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        name_bytes = name.encode("utf-8")
        digest.update(len(name_bytes).to_bytes(4, "big"))
        digest.update(name_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _encode_files(files: dict[str, bytes]) -> dict[str, str]:
    return {
        name: base64.b64encode(content).decode("ascii")
        for name, content in files.items()
    }


def _decode_files(files: dict[str, str]) -> dict[str, bytes]:
    return {
        name: base64.b64decode(content, validate=True)
        for name, content in files.items()
    }
