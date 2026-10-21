# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""ChatContext v7 transport identities and v6 projection compatibility."""

from __future__ import annotations

import json

import pytest

from core.context import ChatContext, MessageIdentityEnvelope
from core.transport.models import BotRef, SceneRef, UserRef


def test_v7_projection_roundtrips_refs_and_keeps_row_id_separate():
    context = ChatContext(
        user_id="user:007/猫",
        group_id="guild:alpha/channel:07",
        msg_id=314,
        platform_message_id="msg:007/猫",
        message="hello",
        conversation_kind="channel",
        conversation_key="conn:discord/channel:07/thread:alpha",
        storage_session_id=-42,
        user_ref=UserRef("discord:user", "user:007/猫", "Mochi"),
        bot_ref=BotRef("discord-main", "discord", "discord", "bot-01"),
        scene_ref=SceneRef(
            "thread", "thread:alpha", ("guild:alpha", "channel:07"), "thread:alpha"
        ),
        connection_id="discord-main",
        adapter_name="discord",
        platform_scope="discord",
        scene_kind="thread",
        scene_id="thread:alpha",
        scene_parent_path=("guild:alpha", "channel:07"),
        thread_id="thread:alpha",
        recorded_row_id=903,
    )

    projection = context.to_json_projection()
    assert projection["projection_schema_version"] == 7
    assert json.loads(json.dumps(projection, ensure_ascii=False)) == projection
    restored = ChatContext.from_json_projection(projection)

    assert restored.user_ref == context.user_ref
    assert restored.bot_ref == context.bot_ref
    assert restored.scene_ref == context.scene_ref
    assert restored.subject_key == context.user_ref.subject_key
    assert restored.raw_user_id == "user:007/猫"
    assert restored.platform_message_id == "msg:007/猫"
    assert restored.recorded_row_id == 903
    assert restored.msg_id == 314  # legacy platform field, never the DB row ID
    envelope = MessageIdentityEnvelope.from_context(restored)
    assert envelope.platform_message_id == "msg:007/猫"
    assert envelope.recorded_row_id == 903


def test_v6_projection_reads_only_confirmed_legacy_fields():
    context = ChatContext(
        user_id=2001, group_id=0, msg_id=77, message="legacy",
        conversation_kind="", conversation_key="legacy-opaque-key",
    )
    projection = context.to_json_projection()
    for name in ChatContext._V7_ONLY_FIELDS:
        projection.pop(name, None)
    projection["projection_schema_version"] = 6

    restored = ChatContext.from_json_projection(projection)
    assert restored.user_id == 2001
    assert restored.platform_message_id == "77"
    assert restored.user_ref is None
    assert restored.subject_key == ""


@pytest.mark.parametrize("version", [5, 8, True, "7"])
def test_projection_rejects_unknown_or_malformed_versions(version):
    projection = ChatContext(
        user_id=1, group_id=0, msg_id=0, message="x"
    ).to_json_projection()
    projection["projection_schema_version"] = version
    with pytest.raises(ValueError, match="projection version"):
        ChatContext.from_json_projection(projection)


def test_v6_projection_cannot_smuggle_v7_identity_fields():
    projection = ChatContext(
        user_id=1, group_id=0, msg_id=0, message="x"
    ).to_json_projection()
    projection["projection_schema_version"] = 6
    projection["user_ref"] = {
        "identity_domain": "discord:user",
        "raw_user_id": "user-1",
        "display_name": None,
    }
    with pytest.raises(ValueError, match="unknown ChatContext projection field"):
        ChatContext.from_json_projection(projection)


@pytest.mark.parametrize("field", ["connection_id", "platform_message_id"])
def test_v7_projection_rejects_non_string_transport_ids(field):
    projection = ChatContext(
        user_id=1, group_id=0, msg_id=0, message="x"
    ).to_json_projection()
    projection[field] = {"raw": "not-an-id"}
    with pytest.raises(ValueError, match=f"{field} must be"):
        ChatContext.from_json_projection(projection)
