# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Immutable, transport-neutral identity values.

External identifiers remain opaque strings. These values are data contracts only:
they do not decide authorization, merge account identities, or resolve memory spaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _require_text(name: str, value: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class BotRef:
    """A configured bot connection and its platform identity."""

    connection_id: str
    adapter: str
    platform_scope: str
    self_id: str

    def __post_init__(self) -> None:
        for name in ("connection_id", "adapter", "platform_scope", "self_id"):
            _require_text(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class UserRef:
    """A sender identity in an explicitly named identity domain."""

    identity_domain: str
    raw_user_id: str
    display_name: str | None = None
    subject_key: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text("identity_domain", self.identity_domain)
        _require_text("raw_user_id", self.raw_user_id)
        if self.display_name is not None and not isinstance(self.display_name, str):
            raise ValueError("display_name must be a string or None")
        # Local import keeps the model module independent of codec implementation
        # details while making subject identity deterministic at construction.
        from core.transport.keys import subject_key_v2

        object.__setattr__(
            self, "subject_key", subject_key_v2(self.identity_domain, self.raw_user_id)
        )


@dataclass(frozen=True, slots=True)
class SceneRef:
    """A conversation scene, retaining its full parent path and optional thread."""

    kind: str
    scene_id: str
    parent_path: tuple[str, ...] = ()
    thread_id: str | None = None

    def __post_init__(self) -> None:
        _require_text("kind", self.kind)
        _require_text("scene_id", self.scene_id)
        if isinstance(self.parent_path, (str, bytes)):
            raise ValueError("parent_path must be a sequence of strings")
        try:
            parent_path = tuple(self.parent_path)
        except TypeError as exc:
            raise ValueError("parent_path must be a sequence of strings") from exc
        if any(not isinstance(part, str) or part == "" for part in parent_path):
            raise ValueError("parent_path entries must be non-empty strings")
        object.__setattr__(self, "parent_path", parent_path)
        if self.thread_id is not None:
            _require_text("thread_id", self.thread_id)


@dataclass(frozen=True, slots=True)
class ConversationRefV2:
    """A registered V2 conversation plus its internal storage and memory routing."""

    bot: BotRef
    scene: SceneRef
    storage_session_id: int
    memory_space: str
    legacy_aliases: tuple[str, ...] = ()
    canonical_key: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bot, BotRef) or not isinstance(self.scene, SceneRef):
            raise ValueError("bot and scene must use the transport identity models")
        if not isinstance(self.storage_session_id, int) or isinstance(
            self.storage_session_id, bool
        ):
            raise ValueError("storage_session_id must be an integer")
        _require_text("memory_space", self.memory_space)
        if isinstance(self.legacy_aliases, (str, bytes)):
            raise ValueError("legacy_aliases must be a sequence of strings")
        aliases = tuple(dict.fromkeys(self.legacy_aliases))
        if any(not isinstance(alias, str) or alias == "" for alias in aliases):
            raise ValueError("legacy aliases must be non-empty strings")
        object.__setattr__(self, "legacy_aliases", aliases)
        from core.transport.keys import conversation_key_v2

        object.__setattr__(self, "canonical_key", conversation_key_v2(self.bot, self.scene))

    @property
    def kind(self) -> str:
        return self.scene.kind

    @property
    def is_group(self) -> bool:
        return self.scene.kind == "group"

    @property
    def is_private(self) -> bool:
        return self.scene.kind == "private"
