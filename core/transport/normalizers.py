# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Normalize platform events into Stella-owned, transport-neutral values.

Normalizers only describe facts supplied by a trusted adapter. They never infer
authorization, turn display names into identities, or parse an opaque session
string into a group/private relationship.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from core.transport.models import BotRef, SceneRef, UserRef


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """A message event with Stella's stable identity and routing facts."""

    bot_ref: BotRef
    user_ref: UserRef
    scene_ref: SceneRef
    text: str
    platform_message_id: str = ""
    sender_display_name: str = ""
    is_tome: bool = False
    is_self: bool = False
    has_image: bool = False
    has_segments: bool = False
    raw_event: Any = field(default=None, repr=False, compare=False)
    bot_handle: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bot_ref, BotRef):
            raise ValueError("bot_ref must be a BotRef")
        if not isinstance(self.user_ref, UserRef):
            raise ValueError("user_ref must be a UserRef")
        if not isinstance(self.scene_ref, SceneRef):
            raise ValueError("scene_ref must be a SceneRef")
        for name in ("text", "platform_message_id", "sender_display_name"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")


@dataclass(frozen=True, slots=True)
class UnsupportedEvent:
    """A platform event without sufficient trusted chat semantics."""

    reason_code: str


NormalizationResult = NormalizedEvent | UnsupportedEvent
AdmissionPurpose = Literal["passive", "group_chat", "private_chat", "webchat", "plugin"]


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    allowed: bool
    reason_code: str = ""


class EventNormalizer(Protocol):
    def normalize(self, bot: Any, event: Any, *, connection_id: str) -> NormalizationResult:
        """Return a normalized event or an explicit unsupported result."""


def _text_id(value: Any) -> str:
    if value is None:
        return ""
    # Adapter IDs are opaque values. Do not normalize leading/trailing spaces,
    # leading zeroes, delimiters, or Unicode from the platform contract.
    return str(value)


def _plain_text(event: Any) -> str | None:
    getter = getattr(event, "get_plaintext", None)
    if not callable(getter):
        return None
    try:
        text = getter()
    except Exception:
        return None
    return text if isinstance(text, str) else None


def _message_segments(event: Any) -> tuple[Any, ...]:
    getter = getattr(event, "get_message", None)
    try:
        message = getter() if callable(getter) else getattr(event, "message", None)
        return tuple(message) if message is not None else ()
    except Exception:
        return ()


def _has_image(event: Any) -> bool:
    for segment in _message_segments(event):
        kind = getattr(segment, "type", "")
        if not kind and isinstance(segment, dict):
            kind = segment.get("type", "")
        if str(kind).lower() == "image":
            return True
    return False


def _has_segments(event: Any) -> bool:
    return bool(_message_segments(event))


def _is_tome(event: Any) -> bool:
    predicate = getattr(event, "is_tome", None)
    if not callable(predicate):
        return False
    try:
        return bool(predicate())
    except Exception:
        return False


def _display_name(event: Any) -> str:
    sender = getattr(event, "sender", None)
    for value in (getattr(sender, "card", ""), getattr(sender, "nickname", "")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(sender, dict):
        for key in ("card", "nickname"):
            value = sender.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


class OneBot11Normalizer:
    """OneBot v11 message normalizer used by the existing QQ ingress."""

    def normalize(
        self,
        bot: Any,
        event: Any,
        *,
        connection_id: str | None = None,
    ) -> NormalizationResult:
        text = _plain_text(event)
        if text is None:
            return UnsupportedEvent("not_message_event")

        self_id = _text_id(getattr(event, "self_id", None) or getattr(bot, "self_id", None))
        user_id = _text_id(getattr(event, "user_id", None))
        if not self_id or not user_id:
            return UnsupportedEvent("missing_bot_or_user_identity")

        message_type = _text_id(getattr(event, "message_type", None)).lower()
        if message_type == "group" or (
            not message_type and getattr(event, "group_id", None) is not None
        ):
            scene_kind = "group"
            scene_id = _text_id(getattr(event, "group_id", None))
        elif message_type == "private":
            scene_kind = "private"
            scene_id = user_id
        else:
            # A session string is safe as an opaque event-local identity. It is
            # never parsed to guess group membership or grant persistent access.
            session_getter = getattr(event, "get_session_id", None)
            try:
                scene_id = _text_id(session_getter()) if callable(session_getter) else ""
            except Exception:
                scene_id = ""
            if not scene_id:
                return UnsupportedEvent("missing_scene_identity")
            scene_kind = "opaque"
        if not scene_id:
            return UnsupportedEvent("missing_scene_identity")

        connection = connection_id or f"legacy-qq:{self_id}"
        bot_ref = BotRef(connection, "onebot-v11", "qq", self_id)
        user_ref = UserRef("qq:client", user_id, _display_name(event) or None)
        scene_ref = SceneRef(scene_kind, scene_id)
        message_id = _text_id(getattr(event, "message_id", None))
        return NormalizedEvent(
            bot_ref=bot_ref,
            user_ref=user_ref,
            scene_ref=scene_ref,
            text=text,
            platform_message_id=message_id,
            sender_display_name=_display_name(event),
            is_tome=_is_tome(event),
            is_self=user_id == self_id,
            has_image=_has_image(event),
            has_segments=_has_segments(event),
            raw_event=event,
            bot_handle=bot,
        )


class GenericNoneBotNormalizer:
    """Conservative NoneBot fallback for adapters without a dedicated codec.

    Callers must pass their configured connection ID. The fallback retains the
    entire framework session as an opaque scene and uses a connection-scoped
    user domain, so it cannot guess group/private roles or merge accounts.
    """

    def normalize(
        self,
        bot: Any,
        event: Any,
        *,
        connection_id: str,
        adapter_name: str = "",
        platform_scope: str = "",
    ) -> NormalizationResult:
        text = _plain_text(event)
        if text is None:
            return UnsupportedEvent("not_message_event")
        if not connection_id:
            return UnsupportedEvent("connection_id_missing")

        getter_user = getattr(event, "get_user_id", None)
        getter_session = getattr(event, "get_session_id", None)
        try:
            user_id = _text_id(getter_user()) if callable(getter_user) else ""
            session_id = _text_id(getter_session()) if callable(getter_session) else ""
        except Exception:
            return UnsupportedEvent("identity_accessor_failed")
        if not user_id:
            return UnsupportedEvent("user_identity_missing")
        if not session_id:
            return UnsupportedEvent("scene_identity_missing")

        adapter = adapter_name.strip()
        if not adapter:
            adapter_obj = getattr(bot, "adapter", None)
            get_name = getattr(adapter_obj, "get_name", None)
            try:
                adapter = _text_id(get_name()) if callable(get_name) else ""
            except Exception:
                adapter = ""
        self_id = _text_id(getattr(bot, "self_id", None))
        if not adapter or not self_id:
            return UnsupportedEvent("bot_identity_missing")

        bot_ref = BotRef(
            connection_id,
            adapter,
            platform_scope.strip() or adapter,
            self_id,
        )
        user_ref = UserRef(f"connection:{connection_id}", user_id, _display_name(event) or None)
        scene_ref = SceneRef("opaque", session_id)
        message_id_getter = getattr(event, "get_message_id", None)
        try:
            message_id = (
                _text_id(message_id_getter())
                if callable(message_id_getter)
                else _text_id(getattr(event, "message_id", None))
            )
        except Exception:
            message_id = ""
        return NormalizedEvent(
            bot_ref=bot_ref,
            user_ref=user_ref,
            scene_ref=scene_ref,
            text=text,
            platform_message_id=message_id,
            sender_display_name=_display_name(event),
            is_tome=_is_tome(event),
            is_self=user_id == self_id,
            has_image=_has_image(event),
            has_segments=_has_segments(event),
            raw_event=event,
            bot_handle=bot,
        )


class AdmissionPolicy:
    """Shared message admission rules; platform commands remain higher priority."""

    def decide(
        self,
        event: NormalizedEvent,
        *,
        purpose: AdmissionPurpose,
        enabled: bool = True,
        allowed_user_ids: set[str] | frozenset[str] | None = None,
        vision_enabled: bool = False,
        plugin_handled: bool = False,
        command_matched: bool = False,
        allow_opaque_event_reply: bool = False,
    ) -> AdmissionDecision:
        if not enabled:
            return AdmissionDecision(False, "disabled")
        if event.is_self:
            return AdmissionDecision(False, "self_echo")
        if purpose == "passive":
            if event.scene_ref.kind != "group":
                return AdmissionDecision(False, "not_group")
            if command_matched or event.text.strip().startswith("/"):
                return AdmissionDecision(False, "slash_command")
            if not event.text.strip() and not (vision_enabled and event.has_image):
                return AdmissionDecision(False, "empty_text_no_vision")
            return AdmissionDecision(True)
        if purpose == "group_chat" and event.scene_ref.kind != "group":
            return AdmissionDecision(False, "not_group")
        if purpose == "private_chat" and event.scene_ref.kind != "private":
            return AdmissionDecision(False, "not_private")
        if (
            purpose in {"group_chat", "private_chat"}
            and allowed_user_ids
            and event.user_ref.raw_user_id not in allowed_user_ids
        ):
            return AdmissionDecision(False, "user_not_allowed")
        if purpose == "group_chat" and not event.is_tome:
            return AdmissionDecision(False, "not_mentioned")
        if plugin_handled:
            return AdmissionDecision(False, "plugin_handled")
        if command_matched:
            return AdmissionDecision(False, "command_matched")
        if purpose == "plugin":
            if not event.text.strip() and not event.has_segments:
                return AdmissionDecision(False, "empty_message")
        elif not event.text.strip() and not (vision_enabled and event.has_image):
            return AdmissionDecision(False, "empty_text_no_vision")
        if event.scene_ref.kind == "opaque" and not allow_opaque_event_reply:
            return AdmissionDecision(False, "opaque_scene_not_admitted")
        if purpose not in {"group_chat", "private_chat", "webchat", "plugin"}:
            return AdmissionDecision(False, "unsupported_purpose")
        return AdmissionDecision(True)


onebot11_normalizer = OneBot11Normalizer()
generic_nonebot_normalizer = GenericNoneBotNormalizer()


def normalize_trusted_webchat(
    text: str,
    *,
    user_id: str,
    display_name: str = "",
) -> NormalizationResult:
    """Build WebChat identity from the authenticated principal supplied by ingress.

    ``display_name`` is descriptive only; callers must pass an authenticated,
    stable ``user_id`` and must not substitute a username or request body value.
    """
    if not isinstance(text, str):
        return UnsupportedEvent("not_message_event")
    if not user_id:
        return UnsupportedEvent("user_identity_missing")
    bot_ref = BotRef("webchat-local", "webchat", "webchat", "stella")
    user_ref = UserRef("webchat:admin", user_id, display_name or None)
    scene_ref = SceneRef("webchat", user_id)
    return NormalizedEvent(
        bot_ref=bot_ref,
        user_ref=user_ref,
        scene_ref=scene_ref,
        text=text,
        sender_display_name=display_name,
    )


def normalize_onebot11(event: Any, *, connection_id: str | None = None) -> NormalizationResult:
    """Convenience boundary for the current OneBot event matchers."""
    return onebot11_normalizer.normalize(None, event, connection_id=connection_id)


__all__ = [
    "AdmissionDecision",
    "AdmissionPolicy",
    "EventNormalizer",
    "GenericNoneBotNormalizer",
    "NormalizationResult",
    "NormalizedEvent",
    "OneBot11Normalizer",
    "UnsupportedEvent",
    "generic_nonebot_normalizer",
    "normalize_onebot11",
    "normalize_trusted_webchat",
    "onebot11_normalizer",
]
