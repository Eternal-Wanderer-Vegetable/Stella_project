# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Transport identity codecs preserve opaque IDs and full scene identity."""

from __future__ import annotations

import pytest

from core.transport.keys import (
    conversation_key_v2,
    decode_conversation_key_v2,
    decode_subject_key_v2,
    subject_key_v2,
)
from core.transport.models import BotRef, SceneRef, UserRef


@pytest.mark.parametrize("raw_id", ["42", "-42", "007", "abc:def", "频道/雪"])
def test_conversation_key_round_trips_opaque_scene_identifiers(raw_id: str) -> None:
    bot = BotRef(
        connection_id="connection:blue/1",
        adapter="example-adapter",
        platform_scope="example-platform",
        self_id="bot:007",
    )
    scene = SceneRef(
        kind="thread",
        scene_id=raw_id,
        parent_path=("server/雪", "channel:main"),
        thread_id="thread/opaque:9",
    )

    encoded = conversation_key_v2(bot, scene)

    assert encoded.startswith("c2.")
    assert decode_conversation_key_v2(encoded) == (bot, scene)


def test_conversation_key_separates_bot_parent_and_thread_identity() -> None:
    bot = BotRef("connection-a", "adapter", "platform", "same-self-id")
    same_other_connection = BotRef("connection-b", "adapter", "platform", "same-self-id")
    scene = SceneRef("thread", "same-id", ("guild", "channel"), "thread-1")

    keys = {
        conversation_key_v2(bot, scene),
        conversation_key_v2(same_other_connection, scene),
        conversation_key_v2(bot, SceneRef("thread", "same-id", ("guild-2", "channel"), "thread-1")),
        conversation_key_v2(bot, SceneRef("thread", "same-id", ("guild", "channel"), "thread-2")),
    }

    assert len(keys) == 4


def test_subject_key_keeps_identity_domain_separate_for_same_opaque_id() -> None:
    qq_user = UserRef("qq:connection-a", "007:雪")
    other_user = UserRef("matrix:server.example", "007:雪")

    assert qq_user.raw_user_id == other_user.raw_user_id
    assert qq_user.subject_key != other_user.subject_key
    assert decode_subject_key_v2(qq_user.subject_key) == ("qq:connection-a", "007:雪")
    assert decode_subject_key_v2(other_user.subject_key) == (
        "matrix:server.example",
        "007:雪",
    )


@pytest.mark.parametrize("bad_key", ["c2.", "c2.%%%", "legacy:platform:group:1"])
def test_conversation_decoder_rejects_noncanonical_or_legacy_keys(bad_key: str) -> None:
    with pytest.raises(ValueError):
        decode_conversation_key_v2(bad_key)


def test_subject_decoder_rejects_wrong_codec_prefix() -> None:
    with pytest.raises(ValueError):
        decode_subject_key_v2(subject_key_v2("domain", "opaque-id").replace("u2.", "c2."))
