# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Shared transport normalization and admission contracts."""

from __future__ import annotations

from types import SimpleNamespace

from core.transport import (
    AdmissionPolicy,
    GenericNoneBotNormalizer,
    NormalizedEvent,
    OneBot11Normalizer,
    SceneRef,
    UnsupportedEvent,
    UserRef,
    normalize_trusted_webchat,
)
from core.transport.models import BotRef


class _Event:
    def __init__(
        self,
        *,
        user_id="007",
        self_id="bot:1",
        message_type="group",
        group_id="group/雪",
        text="hello",
        message_id="msg:42",
        segments=(),
        mentioned=False,
    ):
        self.user_id = user_id
        self.self_id = self_id
        self.message_type = message_type
        self.group_id = group_id
        self.message_id = message_id
        self.message = tuple(segments)
        self.sender = {"nickname": "display only"}
        self._text = text
        self._mentioned = mentioned

    def get_plaintext(self):
        return self._text

    def get_message(self):
        return self.message

    def is_tome(self):
        return self._mentioned


def test_onebot_normalizer_preserves_ids_and_trusted_qq_domain():
    result = OneBot11Normalizer().normalize(
        None, _Event(), connection_id="qq-main"
    )

    assert isinstance(result, NormalizedEvent)
    assert result.bot_ref == BotRef("qq-main", "onebot-v11", "qq", "bot:1")
    assert result.user_ref.identity_domain == "qq:client"
    assert result.user_ref.raw_user_id == "007"
    assert result.scene_ref == SceneRef("group", "group/雪")
    assert result.platform_message_id == "msg:42"
    assert result.sender_display_name == "display only"


def test_unknown_onebot_scene_stays_opaque_and_needs_explicit_event_reply():
    event = _Event(message_type="notice", group_id=None)
    event.get_session_id = lambda: "adapter:room:thread"
    normalized = OneBot11Normalizer().normalize(None, event)
    assert isinstance(normalized, NormalizedEvent)
    assert normalized.scene_ref == SceneRef("opaque", "adapter:room:thread")

    policy = AdmissionPolicy()
    denied = policy.decide(normalized, purpose="plugin")
    allowed = policy.decide(
        normalized, purpose="plugin", allow_opaque_event_reply=True
    )
    assert not denied.allowed
    assert denied.reason_code == "opaque_scene_not_admitted"
    assert allowed.allowed


def test_generic_normalizer_scopes_unknown_users_to_configured_connection():
    adapter = SimpleNamespace(get_name=lambda: "satori")
    bot = SimpleNamespace(self_id="bot-1", adapter=adapter)

    def event(session):
        return SimpleNamespace(
            get_plaintext=lambda: "hello",
            get_user_id=lambda: "same-id",
            get_session_id=lambda: session,
            message_id="abc/1",
        )

    normalizer = GenericNoneBotNormalizer()
    a = normalizer.normalize(bot, event("thread:7"), connection_id="satori-a")
    b = normalizer.normalize(bot, event("thread:7"), connection_id="satori-b")

    assert isinstance(a, NormalizedEvent)
    assert isinstance(b, NormalizedEvent)
    assert a.user_ref.raw_user_id == b.user_ref.raw_user_id == "same-id"
    assert a.user_ref.subject_key != b.user_ref.subject_key
    assert a.scene_ref == SceneRef("opaque", "thread:7")
    assert a.platform_message_id == "abc/1"


def test_generic_normalizer_rejects_missing_connection_and_non_message_events():
    normalizer = GenericNoneBotNormalizer()
    bot = SimpleNamespace(self_id="bot-1", adapter=SimpleNamespace(get_name=lambda: "satori"))
    event = SimpleNamespace(
        get_plaintext=lambda: "hello",
        get_user_id=lambda: "u1",
        get_session_id=lambda: "s1",
    )
    assert normalizer.normalize(bot, event, connection_id="").reason_code == "connection_id_missing"
    assert isinstance(OneBot11Normalizer().normalize(None, object()), UnsupportedEvent)


def test_admission_keeps_passive_command_and_vision_rules_shared():
    policy = AdmissionPolicy()
    base = NormalizedEvent(
        BotRef("qq-main", "onebot-v11", "qq", "bot"),
        UserRef("qq:client", "42"),
        SceneRef("group", "123"),
        "",
        has_image=True,
    )

    assert policy.decide(base, purpose="passive").reason_code == "empty_text_no_vision"
    assert policy.decide(
        base, purpose="passive", vision_enabled=True
    ).allowed
    pure_image_at = NormalizedEvent(
        base.bot_ref,
        base.user_ref,
        base.scene_ref,
        "",
        is_tome=True,
        has_image=True,
        has_segments=True,
    )
    assert policy.decide(
        pure_image_at, purpose="group_chat"
    ).reason_code == "empty_text_no_vision"
    assert policy.decide(
        pure_image_at, purpose="group_chat", vision_enabled=True
    ).allowed
    slash = NormalizedEvent(
        base.bot_ref, base.user_ref, base.scene_ref, "/admin", has_image=False
    )
    assert policy.decide(slash, purpose="passive").reason_code == "slash_command"
    mentioned = NormalizedEvent(
        base.bot_ref, base.user_ref, base.scene_ref, "hello", is_tome=True
    )
    assert policy.decide(mentioned, purpose="group_chat").allowed
    assert policy.decide(
        mentioned, purpose="group_chat", plugin_handled=True
    ).reason_code == "plugin_handled"
    assert policy.decide(
        NormalizedEvent(
            base.bot_ref, base.user_ref, base.scene_ref, "hello", is_self=True
        ),
        purpose="passive",
    ).reason_code == "self_echo"


def test_webchat_normalizer_does_not_promote_display_name_to_identity():
    event = normalize_trusted_webchat(
        "hello", user_id="fixed-admin-id", display_name="same-id"
    )
    assert isinstance(event, NormalizedEvent)
    assert event.user_ref.raw_user_id == "fixed-admin-id"
    assert event.user_ref.display_name == "same-id"
    assert event.scene_ref.kind == "webchat"
