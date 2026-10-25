# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Versioned, SDK-free message event contract for transport adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

MessagePartKind = Literal[
    "text", "mention", "reply", "image", "audio", "video", "file", "unsupported"
]
MessageRelationKind = Literal["reply", "quote", "forward", "mention"]
MessageEventKind = Literal["create", "edit", "delete"]

_PART_KINDS = frozenset(
    {"text", "mention", "reply", "image", "audio", "video", "file", "unsupported"}
)
_RELATION_KINDS = frozenset({"reply", "quote", "forward", "mention"})
_EVENT_KINDS = frozenset({"create", "edit", "delete"})
_ATTACHMENT_REF = re.compile(r"^attachment:[A-Za-z0-9._:-]{1,256}$")


def _opaque_text(name: str, value: str | None, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or value == "" or len(value) > 2048:
        raise ValueError(f"{name} must be a non-empty opaque string of at most 2048 characters")
    if any(ord(char) < 0x20 or ord(char) == 0x7F or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"{name} contains a control character")


@dataclass(frozen=True, slots=True)
class MessagePartV1:
    """One ordered, safe component; never contains an SDK object or raw URL."""

    kind: MessagePartKind
    text: str | None = None
    subject_key: str | None = None
    display_name: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    attachment_ref: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _PART_KINDS:
            raise ValueError("unsupported message part kind")
        for name in ("subject_key", "display_name", "mime_type"):
            _opaque_text(name, getattr(self, name))
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("text must be a string or None")
        if self.size_bytes is not None and (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise ValueError("size_bytes must be a non-negative integer or None")
        if self.attachment_ref is not None and (
            not isinstance(self.attachment_ref, str)
            or not _ATTACHMENT_REF.fullmatch(self.attachment_ref)
        ):
            raise ValueError("attachment_ref must be a controlled attachment reference")
        if self.kind == "text" and self.text is None:
            raise ValueError("text parts must carry text")
        if self.kind == "mention" and self.subject_key is None:
            raise ValueError("mention parts must carry a namespaced subject key")
        if self.kind in {"image", "audio", "video", "file"} and not any(
            value is not None for value in (self.mime_type, self.size_bytes, self.attachment_ref)
        ):
            raise ValueError("media parts must carry a safe description or attachment reference")


@dataclass(frozen=True, slots=True)
class MessageRelationV1:
    """A durable relation target whose unresolved state is preserved explicitly."""

    kind: MessageRelationKind
    target_message_id: str | None = None
    target_connection_id: str | None = None
    target_conversation_key: str | None = None
    subject_key: str | None = None
    resolved: bool = False

    def __post_init__(self) -> None:
        if self.kind not in _RELATION_KINDS:
            raise ValueError("unsupported message relation kind")
        for name in (
            "target_message_id",
            "target_connection_id",
            "target_conversation_key",
            "subject_key",
        ):
            _opaque_text(name, getattr(self, name))
        if self.kind in {"reply", "quote", "forward"} and self.target_message_id is None:
            raise ValueError("message relations must carry an opaque target message ID")
        if self.kind == "mention" and self.subject_key is None:
            raise ValueError("mention relations must carry a namespaced subject key")
        if not isinstance(self.resolved, bool):
            raise ValueError("resolved must be a boolean")


@dataclass(frozen=True, slots=True)
class MessageEventV1:
    """Transport-neutral create/edit/delete event with opaque platform identifiers."""

    platform_message_id: str
    occurred_at: datetime
    components: tuple[MessagePartV1, ...] = ()
    relations: tuple[MessageRelationV1, ...] = ()
    event_kind: MessageEventKind = "create"
    platform_revision_id: str | None = None
    version: Literal[1] = 1

    def __post_init__(self) -> None:
        if self.version != 1 or isinstance(self.version, bool):
            raise ValueError("message event version must be 1")
        if self.event_kind not in _EVENT_KINDS:
            raise ValueError("unsupported message event kind")
        _opaque_text("platform_message_id", self.platform_message_id, required=True)
        _opaque_text("platform_revision_id", self.platform_revision_id)
        if not isinstance(self.occurred_at, datetime):
            raise ValueError("occurred_at must be a datetime")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))
        for name in ("components", "relations"):
            items = getattr(self, name)
            if isinstance(items, (str, bytes)):
                raise ValueError(f"{name} must be a sequence of versioned values")
            try:
                frozen = tuple(items)
            except TypeError as exc:
                raise ValueError(f"{name} must be a sequence of versioned values") from exc
            if len(frozen) > 4096:
                raise ValueError(f"{name} exceeds the 4096 item limit")
            expected = MessagePartV1 if name == "components" else MessageRelationV1
            if any(not isinstance(item, expected) for item in frozen):
                raise ValueError(f"{name} contains an invalid contract value")
            object.__setattr__(self, name, frozen)
        if self.event_kind == "delete" and self.components:
            raise ValueError("delete events must not retain message components")


__all__ = ["MessageEventV1", "MessagePartKind", "MessagePartV1", "MessageRelationKind", "MessageRelationV1"]
