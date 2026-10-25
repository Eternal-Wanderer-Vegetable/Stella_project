# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Synthetic P03 ingress fixtures; no platform SDK or live transport is used."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.context import ChatContext
from core.transport.ingress import TransportIngress, sqlite_v2_registrar
from core.transport.keys import conversation_key_v2
from core.transport.message_event import (
    MessageEventV1,
    MessagePartV1,
    MessageRelationV1,
)
from core.transport.models import BotRef, ConversationRefV2, SceneRef, UserRef
from core.transport.normalizers import NormalizedEvent
from memory.ownership import (
    AUDIENCE_PRIVATE_ONLY,
    AUDIENCE_USER_SHARED,
    scope_for_chat_context,
)
from stella_bootstrap.transport_settings import parse_transport_settings_json

CONNECTION_A = "11111111-1111-4111-8111-111111111111"
CONNECTION_B = "22222222-2222-4222-8222-222222222222"
ADAPTER = "synthetic-adapter"


class EchoNormalizer:
    def normalize(self, _bot, event, *, connection_id):
        assert connection_id
        return event


class RecordingFacade:
    def __init__(self):
        self.calls = []

    async def submit_turn(self, key, pipeline, ctx):
        self.calls.append((key, pipeline, ctx))
        return ctx


class LifecyclePipeline:
    async def prepare_turn(self, ctx):
        return SimpleNamespace(ctx=ctx, outcome="generate")

    async def finalize_turn(self, ctx):
        return ctx


def _connection(connection_id=CONNECTION_A, *, self_id="bot-雪", enabled=True):
    return {
        "connection_id": connection_id,
        "adapter": ADAPTER,
        "platform_scope": "synthetic",
        "self_id": self_id,
        "enabled": enabled,
    }


def _settings(
    *,
    defaults=None,
    connections=None,
    templates=None,
    profile_policy=None,
    scene_policy=None,
    scene=None,
    memory_space=None,
):
    bundle = {
        "version": 1,
        "connections": connections or [_connection()],
        "defaults": defaults or {},
        "profiles": [],
        "bindings": [],
        "platform_templates": templates or {},
    }
    if profile_policy is not None or scene_policy is not None:
        bundle["profiles"].append(
            {"policy_profile_id": "fixture-profile", "policy": profile_policy or {}}
        )
        scene_ref = scene or SceneRef("group", "room:007")
        binding = {
            "connection_id": CONNECTION_A,
            "scene": {
                "kind": scene_ref.kind,
                "scene_id": scene_ref.scene_id,
                "parent_path": list(scene_ref.parent_path),
            },
            "policy_profile_id": "fixture-profile",
            "policy": scene_policy or {},
        }
        if scene_ref.thread_id is not None:
            binding["scene"]["thread_id"] = scene_ref.thread_id
        if memory_space is not None:
            binding["memory_space"] = memory_space
        bundle["bindings"].append(binding)
    return parse_transport_settings_json(json.dumps(bundle, ensure_ascii=False))


def _event(
    scene=None,
    *,
    connection_id=CONNECTION_A,
    adapter=ADAPTER,
    platform_scope="synthetic",
    self_id="bot-雪",
    text="hello",
    is_tome=False,
    message_id="message:007",
    relations=(),
    event_kind="create",
):
    bot = BotRef(connection_id, adapter, platform_scope, self_id)
    user = UserRef("synthetic:user", "user:００7", "显示名")
    scene = scene or SceneRef("group", "room:007")
    dto = MessageEventV1(
        platform_message_id=message_id,
        occurred_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
        components=(MessagePartV1("text", text=text),) if text else (),
        relations=tuple(relations),
        event_kind=event_kind,
    )
    return NormalizedEvent(
        bot_ref=bot,
        user_ref=user,
        scene_ref=scene,
        text=text,
        message_event=dto,
        is_tome=is_tome,
        has_segments=bool(text),
    )


def _registrar(calls=None):
    calls = calls if calls is not None else []

    def register(bot, scene, memory_space):
        ref = ConversationRefV2(
            bot=bot,
            scene=scene,
            storage_session_id=-2 - len(calls),
            memory_space=memory_space or f"transport:{conversation_key_v2(bot, scene)}",
        )
        calls.append(ref)
        return ref

    return register


def _service(settings, **kwargs):
    return TransportIngress(
        settings,
        normalizers={ADAPTER: EchoNormalizer()},
        register_conversation=kwargs.pop("register_conversation", _registrar()),
        **kwargs,
    )


@pytest.mark.parametrize(
    ("scene", "overrides", "reason"),
    [
        (SceneRef("opaque", "opaque/session"), {}, "unsupported_or_opaque_scene"),
        (SceneRef("thread", "thread-without-id", ("channel:1",)), {}, "thread_identity_missing"),
        (SceneRef("group", "room:007"), {"connection_id": "33333333-3333-4333-8333-333333333333"}, "connection_not_configured"),
        (SceneRef("group", "room:007"), {"self_id": "spoofed-bot"}, "bot_identity_mismatch"),
    ],
)
def test_untrusted_or_unsupported_events_stop_before_registration_or_writes(
    scene, overrides, reason
):
    registrations, writes = [], []
    service = _service(
        _settings(connections=[_connection()]),
        register_conversation=_registrar(registrations),
        capture_gate=lambda *_: True,
        capture_writer=lambda *_: writes.append("write"),
    )
    connection_id = overrides.get("connection_id", CONNECTION_A)
    event_overrides = {key: value for key, value in overrides.items() if key != "connection_id"}
    event = _event(scene, **event_overrides)
    result = asyncio.run(service.handle_event(connection_id, object(), event))
    assert result.status == "rejected"
    assert result.reason_code == reason
    assert registrations == []
    assert writes == []


def test_disabled_connection_fails_before_normalization():
    service = _service(_settings(connections=[_connection(enabled=False)]))
    result = asyncio.run(service.handle_event(CONNECTION_A, object(), object()))
    assert result.reason_code == "connection_disabled"


def test_capture_disabled_has_no_content_write_and_runtime_uses_opaque_identity():
    facade = RecordingFacade()
    writes = []
    service = _service(
        _settings(defaults={"llm_enabled": True, "wake_mode": "mention"}),
        capture_gate=lambda *_: True,
        capture_writer=lambda *_: writes.append("body"),
        runtime_facade=facade,
        pipeline_factory=lambda *_: object(),
    )
    result = asyncio.run(
        service.handle_event(
            CONNECTION_A,
            object(),
            _event(is_tome=True, message_id="opaque/msg:001"),
        )
    )

    assert result.status == "turn_submitted"
    assert result.capture_status == "not_requested"
    assert result.turn_status == "submitted"
    assert writes == []
    key, _pipeline, ctx = facade.calls[0]
    assert key == ctx.conversation_key
    assert ctx.user_id == "user:００7"
    assert ctx.group_id == 0 and ctx.msg_id == 0
    assert ctx.storage_session_id < 0
    assert ctx.platform_message_id == "opaque/msg:001"
    assert ctx.group_shared_space.startswith("transport:")


def test_closed_capture_gate_writes_no_body_but_keeps_passive_runtime_independent():
    registrations, writes = [], []
    service = _service(
        _settings(defaults={"capture_enabled": True, "llm_enabled": True, "wake_mode": "mention"}),
        register_conversation=_registrar(registrations),
        capture_gate=lambda *_: False,
        capture_writer=lambda *_: writes.append("body"),
        runtime_facade=RecordingFacade(),
        pipeline_factory=lambda *_: object(),
    )
    result = asyncio.run(service.handle_event(CONNECTION_A, object(), _event(is_tome=True)))
    assert result.capture_status == "denied"
    assert result.turn_status == "submitted"
    assert len(registrations) == 1  # metadata registration is separate from message content
    assert writes == []


@pytest.mark.parametrize(("event_kind", "text"), [("edit", "revised"), ("delete", "")])
def test_edits_and_deletes_are_captured_without_starting_a_turn(event_kind, text):
    captured, facade = [], RecordingFacade()
    service = _service(
        _settings(defaults={
            "capture_enabled": True,
            "llm_enabled": True,
            "wake_mode": "all",
        }),
        capture_gate=lambda *_: True,
        capture_writer=lambda _ctx, dto: captured.append(dto.event_kind),
        runtime_facade=facade,
        pipeline_factory=lambda *_: object(),
    )
    result = asyncio.run(
        service.handle_event(
            CONNECTION_A,
            object(),
            _event(event_kind=event_kind, text=text),
        )
    )
    assert result.capture_status == "captured"
    assert result.turn_status == "not_triggered"
    assert captured == [event_kind]
    assert facade.calls == []


def test_capture_denial_happens_before_v2_registration_when_no_turn_is_requested():
    registrations, writes = [], []
    service = _service(
        _settings(defaults={"capture_enabled": True, "llm_enabled": False}),
        register_conversation=_registrar(registrations),
        capture_gate=lambda *_: False,
        capture_writer=lambda *_: writes.append("body"),
    )
    result = asyncio.run(service.handle_event(CONNECTION_A, object(), _event()))
    assert result.status == "capture_not_completed"
    assert result.capture_status == "denied"
    assert result.context is None
    assert registrations == []
    assert writes == []


def test_runtime_is_blocked_when_person_scope_cannot_be_proven(monkeypatch):
    facade = RecordingFacade()
    service = _service(
        _settings(defaults={"llm_enabled": True, "wake_mode": "all"}),
        runtime_facade=facade,
        pipeline_factory=lambda *_: object(),
    )
    monkeypatch.setattr(
        "memory.ownership.scope_for_chat_context", lambda *_args, **_kwargs: None
    )
    result = asyncio.run(
        service.handle_event(
            CONNECTION_A,
            object(),
            _event(SceneRef("channel", "channel:1", ("server:1",))),
        )
    )
    assert result.turn_status == "scope_unavailable"
    assert result.context is not None
    assert facade.calls == []


def test_message_event_id_must_match_normalized_opaque_id():
    event = _event()
    assert event.platform_message_id == "message:007"
    with pytest.raises(ValueError, match="IDs must match"):
        NormalizedEvent(
            bot_ref=event.bot_ref,
            user_ref=event.user_ref,
            scene_ref=event.scene_ref,
            text=event.text,
            platform_message_id="different-id",
            message_event=event.message_event,
        )


def test_normalized_event_keeps_legacy_positional_platform_id_argument():
    event = _event()
    normalized = NormalizedEvent(
        event.bot_ref,
        event.user_ref,
        event.scene_ref,
        "legacy input",
        "opaque:legacy-007",
    )
    assert normalized.platform_message_id == "opaque:legacy-007"
    assert normalized.message_event is None


def test_policy_precedence_and_exact_scene_binding_are_applied():
    scene = SceneRef("thread", "thread:007", ("server:1", "channel:2"), "thread:007")
    settings = _settings(
        defaults={"capture_enabled": True, "llm_enabled": False},
        templates={ADAPTER: {"capture_enabled": False, "wake_mode": "all"}},
        profile_policy={"capture_enabled": False, "llm_enabled": True},
        scene_policy={"capture_enabled": True},
        scene=scene,
        memory_space="shared:team",
    )
    facade = RecordingFacade()
    captured = []
    order = []
    registrations = []
    register = _registrar(registrations)

    def ordered_register(bot, scene, memory_space):
        order.append("register")
        return register(bot, scene, memory_space)

    def ordered_gate(*_):
        order.append("gate")
        return True

    def ordered_capture(ctx, dto):
        order.append("capture")
        captured.append((ctx, dto))

    service = _service(
        settings,
        register_conversation=ordered_register,
        capture_gate=ordered_gate,
        capture_writer=ordered_capture,
        runtime_facade=facade,
        pipeline_factory=lambda *_: object(),
    )
    result = asyncio.run(service.handle_event(CONNECTION_A, object(), _event(scene)))
    assert result.status == "turn_submitted"
    assert result.capture_status == "captured"
    assert result.policy_sources["capture_enabled"] == "scene"
    assert result.policy_sources["llm_enabled"] == "profile"
    assert captured[0][0].group_shared_space == "shared:team"
    assert captured[0][0].thread_id == "thread:007"
    assert facade.calls[0][0] == result.context.conversation_key
    assert order == ["gate", "register", "capture"]


@pytest.mark.parametrize(
    ("mode", "scene", "text", "is_tome", "relations", "prefixes", "wakes"),
    [
        ("mention", SceneRef("group", "g1"), "hi", True, (), (), True),
        ("reply", SceneRef("channel", "c1", ("server",)), "hi", False,
         (MessageRelationV1("reply", target_message_id="parent:1"),), (), True),
        ("prefix", SceneRef("thread", "t1", ("channel",), "t1"), "!go", False, (), ("!",), True),
        ("all", SceneRef("group", "g1"), "hello", False, (), (), True),
        ("private_direct", SceneRef("private", "u1"), "hello", False, (), (), True),
        ("private_direct", SceneRef("channel", "c1"), "hello", False, (), (), False),
        ("mention", SceneRef("group", "g1"), "hi", False, (), (), False),
    ],
)
def test_five_wake_branches_are_explicit_and_channel_thread_aware(
    mode, scene, text, is_tome, relations, prefixes, wakes
):
    facade = RecordingFacade()
    service = _service(
        _settings(defaults={
            "llm_enabled": True,
            "wake_mode": mode,
            "wake_prefixes": list(prefixes),
        }),
        runtime_facade=facade,
        pipeline_factory=lambda *_: object(),
    )
    result = asyncio.run(
        service.handle_event(
            CONNECTION_A,
            object(),
            _event(scene, text=text, is_tome=is_tome, relations=relations),
        )
    )
    assert (result.turn_status == "submitted") is wakes
    assert len(facade.calls) == int(wakes)


def test_channel_and_thread_person_scopes_match_group_but_require_trusted_refs():
    bot = BotRef(CONNECTION_A, ADAPTER, "synthetic", "bot-雪")
    user = UserRef("synthetic:user", "user:007")
    for scene in (
        SceneRef("channel", "channel:1", ("server:1",)),
        SceneRef("thread", "thread:1", ("server:1", "channel:1"), "thread:1"),
    ):
        ctx = ChatContext(
            user_id=user.raw_user_id,
            group_id=0,
            msg_id=0,
            message="hello",
            conversation_kind=scene.kind,
            conversation_key=conversation_key_v2(bot, scene),
            bot_id=bot.self_id,
            connection_id=bot.connection_id,
            scene_kind=scene.kind,
            scene_id=scene.scene_id,
            scene_parent_path=scene.parent_path,
            user_ref=user,
            bot_ref=bot,
            scene_ref=scene,
            thread_id=scene.thread_id or "",
        )
        scope = scope_for_chat_context(ctx, memory_space="space:team")
        assert scope is not None and scope.has_person
        assert scope.person_audiences == (AUDIENCE_USER_SHARED,)

    private = ChatContext(
        user_id=user.raw_user_id, group_id=0, msg_id=0, message="hi",
        conversation_kind="private", connection_id=CONNECTION_A,
        user_ref=user, bot_ref=bot, scene_ref=SceneRef("private", "user:007"),
    )
    private_scope = scope_for_chat_context(private, memory_space="private:user")
    assert private_scope.person_audiences == (AUDIENCE_PRIVATE_ONLY, AUDIENCE_USER_SHARED)

    opaque = ChatContext(
        user_id=user.raw_user_id, group_id=0, msg_id=0, message="hi",
        conversation_kind="opaque", connection_id=CONNECTION_A,
        user_ref=user, bot_ref=bot, scene_ref=SceneRef("opaque", "session"),
    )
    assert scope_for_chat_context(opaque, memory_space="space") is None

    missing_thread = ChatContext(
        user_id=user.raw_user_id, group_id=0, msg_id=0, message="hi",
        conversation_kind="thread", connection_id=CONNECTION_A,
        user_ref=user, bot_ref=bot, scene_ref=SceneRef("thread", "thread:1"),
    )
    assert scope_for_chat_context(missing_thread, memory_space="space") is None


def test_bot_and_thread_keys_keep_conversations_and_memory_spaces_isolated():
    connections = [_connection(), _connection(CONNECTION_B, self_id="bot-B")]
    captured = []
    service = _service(
        _settings(defaults={"capture_enabled": True}, connections=connections),
        capture_gate=lambda *_: True,
        capture_writer=lambda ctx, _dto: captured.append(ctx),
    )
    events = (
        _event(SceneRef("thread", "thread:1", ("server:1", "channel:1"), "thread:1")),
        _event(SceneRef("thread", "thread:2", ("server:1", "channel:1"), "thread:2")),
        _event(
            SceneRef("thread", "thread:1", ("server:1", "channel:1"), "thread:1"),
            connection_id=CONNECTION_B,
            self_id="bot-B",
        ),
    )
    for event in events:
        connection_id = event.bot_ref.connection_id
        result = asyncio.run(service.handle_event(connection_id, object(), event))
        assert result.capture_status == "captured"
    keys = {ctx.conversation_key for ctx in captured}
    spaces = {ctx.group_shared_space for ctx in captured}
    assert len(keys) == 3
    assert len(spaces) == 3


def test_legacy_qq_and_webchat_identities_do_not_match_new_connection():
    registrations = []
    service = _service(
        _settings(defaults={"capture_enabled": True}),
        register_conversation=_registrar(registrations),
        capture_gate=lambda *_: True,
        capture_writer=lambda *_: pytest.fail("legacy identity reached capture"),
    )
    legacy_events = (
        _event(
            connection_id="legacy-qq:bot-雪",
            adapter="onebot-v11",
            platform_scope="qq",
            self_id="bot-雪",
        ),
        _event(
            connection_id="webchat-local",
            adapter="webchat",
            platform_scope="webchat",
            self_id="stella",
        ),
    )
    for event in legacy_events:
        result = asyncio.run(service.handle_event(CONNECTION_A, object(), event))
        assert result.reason_code == "bot_identity_mismatch"
    assert registrations == []


def test_message_event_stays_ephemeral_and_chat_context_projection_remains_v7():
    event = _event(is_tome=True)
    ctx = ChatContext(
        user_id=event.user_ref.raw_user_id,
        group_id=0,
        msg_id=0,
        message=event.text,
        platform_message_id=event.message_event.platform_message_id,
        user_ref=event.user_ref,
        bot_ref=event.bot_ref,
        scene_ref=event.scene_ref,
    )
    projection = ctx.to_json_projection()
    restored = ChatContext.from_json_projection(projection)
    assert ChatContext.PROJECTION_SCHEMA_VERSION == 7
    assert projection["projection_schema_version"] == 7
    assert "message_event" not in projection
    assert restored.user_id == "user:００7"
    assert restored.platform_message_id == "message:007"


def test_sqlite_registrar_uses_v2_identity_and_is_idempotent(tmp_path):
    from memory.conversation_registry import lookup_conversation_v2

    path = tmp_path / "memory.db"
    scene = SceneRef("thread", "thread:雪", ("server:1",), "thread:雪")
    bot = BotRef(CONNECTION_A, ADAPTER, "synthetic", "bot-雪")
    registrar = sqlite_v2_registrar(lambda: sqlite3.connect(path))
    first = registrar(bot, scene, "space:shared")
    second = registrar(bot, scene, "space:shared")
    assert first == second
    assert first.storage_session_id < 0
    assert first.canonical_key == second.canonical_key
    connection = sqlite3.connect(path)
    try:
        assert lookup_conversation_v2(connection, bot, scene) == first
    finally:
        connection.close()


@pytest.mark.parametrize("same_conversation", [True, False])
def test_runtime_facade_serializes_same_key_and_runs_different_keys_in_parallel(same_conversation):
    from core.runtime.facade import RuntimeFacade

    async def exercise():
        started_count = 0
        active = 0
        peak = 0
        release = asyncio.Event()
        two_started = asyncio.Event()

        async def provider(_key, _prompt):
            nonlocal started_count, active, peak
            started_count += 1
            active += 1
            peak = max(peak, active)
            if started_count >= 2:
                two_started.set()
            await release.wait()
            active -= 1
            return "raw"

        facade = RuntimeFacade(provider=provider)
        scene_a = SceneRef("channel", "channel:a", ("server",))
        scene_b = scene_a if same_conversation else SceneRef("channel", "channel:b", ("server",))
        service = _service(
            _settings(defaults={"llm_enabled": True, "wake_mode": "all"}),
            runtime_facade=facade,
            pipeline_factory=lambda *_: LifecyclePipeline(),
            register_conversation=_registrar(),
        )
        first = asyncio.create_task(
            service.handle_event(CONNECTION_A, object(), _event(scene_a))
        )
        if same_conversation:
            while started_count == 0:
                await asyncio.sleep(0)
            second = asyncio.create_task(
                service.handle_event(CONNECTION_A, object(), _event(scene_b))
            )
            await asyncio.sleep(0.05)
            assert started_count == 1
        else:
            second = asyncio.create_task(
                service.handle_event(CONNECTION_A, object(), _event(scene_b))
            )
            await asyncio.wait_for(two_started.wait(), 2)
            assert peak == 2
        release.set()
        results = await asyncio.gather(first, second)
        assert all(result.turn_status == "submitted" for result in results)
        assert peak == (1 if same_conversation else 2)

    asyncio.run(exercise())
