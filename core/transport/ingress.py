# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Opt-in transport-neutral message ingress.

This service is deliberately not registered as a NoneBot matcher. A future
adapter entry point must select an explicitly enabled connection and inject its
trusted normalizer, V2 registrar, capture gate/writer and runtime pipeline.
Legacy QQ and WebChat entry points therefore keep their existing ownership.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from core.context import ChatContext
from core.transport.connection_registry import ConfiguredConnectionRegistry
from core.transport.message_event import MessageEventV1
from core.transport.models import BotRef, ConversationRefV2, SceneRef
from core.transport.normalizers import (
    EventNormalizer,
    NormalizedEvent,
    UnsupportedEvent,
)
from core.transport.policy import EffectivePolicy, PolicyLayer, resolve_policy
from stella_bootstrap.transport_settings import (
    ScenePolicyBinding,
    TransportConnectionSettings,
    TransportSettingsV1,
)

CaptureGate = Callable[
    [NormalizedEvent, EffectivePolicy], object | Awaitable[object]
]
CaptureWriter = Callable[
    [ChatContext, MessageEventV1], object | Awaitable[object]
]
ConversationRegistrar = Callable[
    [BotRef, SceneRef, str | None], ConversationRefV2
]
PipelineFactory = Callable[[ChatContext, EffectivePolicy], object]


class RuntimeFacadeLike(Protocol):
    async def submit_turn(
        self, key: str, pipeline: object, ctx: ChatContext
    ) -> ChatContext:
        """Submit one turn through the process-local runtime owner."""

_SUPPORTED_SCENES = frozenset({"private", "group", "channel", "thread", "webchat"})


@dataclass(frozen=True, slots=True)
class IngressResult:
    """Bounded result metadata; raw adapter objects never leave the ingress."""

    status: str
    reason_code: str = ""
    capture_status: str = "not_requested"
    turn_status: str = "not_requested"
    context: ChatContext | None = None
    turn_context: ChatContext | None = None
    policy_sources: Mapping[str, str] | None = None


def sqlite_v2_registrar(
    connection_factory: Callable[[], Any],
) -> ConversationRegistrar:
    """Adapt a memory SQLite connection factory to the V2 registry contract.

    Importing this module does not open user storage or import the memory package;
    the registration boundary runs only after an enabled, trusted event is admitted.
    """

    if not callable(connection_factory):
        raise TypeError("connection_factory must be callable")

    def register(bot: BotRef, scene: SceneRef, memory_space: str | None) -> ConversationRefV2:
        from memory.conversation_registry import register_conversation_v2

        connection = connection_factory()
        try:
            return register_conversation_v2(
                connection, bot, scene, memory_space=memory_space
            )
        finally:
            connection.close()

    return register


async def _maybe_await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


def _thaw_policy(values: Mapping[str, object]) -> dict[str, object]:
    """Convert parser-frozen arrays to the JSON shape expected by PolicyLayer."""

    def thaw(value: object) -> object:
        if isinstance(value, Mapping):
            return {key: thaw(item) for key, item in value.items()}
        if isinstance(value, tuple):
            return [thaw(item) for item in value]
        return value

    return {key: thaw(value) for key, value in values.items()}


def _policy_layers(
    settings: TransportSettingsV1,
    connection: TransportConnectionSettings,
    binding: ScenePolicyBinding | None,
) -> EffectivePolicy:
    layers = [PolicyLayer("global_defaults", _thaw_policy(settings.defaults))]
    template = settings.platform_templates.get(connection.adapter)
    if template is not None:
        layers.append(PolicyLayer("platform_template", _thaw_policy(template)))
    layers.append(PolicyLayer("connection_default", _thaw_policy(connection.policy)))
    profiles = {item.policy_profile_id: item for item in settings.profiles}
    if binding is not None:
        profile = profiles.get(binding.policy_profile_id)
        if profile is None:  # Parser normally proves this; keep the runtime boundary fail-closed.
            raise ValueError("scene policy profile is unavailable")
        layers.append(PolicyLayer("profile", _thaw_policy(profile.policy)))
        layers.append(PolicyLayer("scene", _thaw_policy(binding.policy)))
    return resolve_policy(layers)


def _wake_reason(event: NormalizedEvent, policy: EffectivePolicy) -> str:
    """Return the configured wake reason or an empty string for passive input."""
    mode = str(policy.values.get("wake_mode", "mention"))
    has_content = bool(
        event.text.strip()
        or (event.message_event and event.message_event.components)
    )
    if mode == "mention":
        return "mention" if event.is_tome and event.text.strip() else ""
    if mode == "reply":
        is_reply = bool(
            event.message_event
            and any(relation.kind == "reply" for relation in event.message_event.relations)
        )
        return "reply" if is_reply and event.text.strip() else ""
    if mode == "prefix":
        prefixes = policy.values.get("wake_prefixes", ())
        if not isinstance(prefixes, (tuple, list)):
            return ""
        return "prefix" if event.text and any(event.text.startswith(item) for item in prefixes) else ""
    if mode == "all":
        return "all" if has_content and event.text.strip() else ""
    if mode == "private_direct" and (
        event.scene_ref.kind in {"private", "webchat"} and event.text.strip()
    ):
        return "private_direct"
    return ""


class TransportIngress:
    """Coordinate trusted normalization, policy, registration and one runtime turn.

    The constructor has no database or network side effects. Adapters are wired
    explicitly by connection ID; this class never registers matchers itself.
    """

    def __init__(
        self,
        settings: TransportSettingsV1,
        *,
        normalizers: Mapping[str, EventNormalizer],
        register_conversation: ConversationRegistrar,
        capture_gate: CaptureGate | None = None,
        capture_writer: CaptureWriter | None = None,
        runtime_facade: RuntimeFacadeLike | None = None,
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        if not isinstance(settings, TransportSettingsV1):
            raise TypeError("settings must be a parsed TransportSettingsV1")
        self._settings = settings
        self._normalizers = dict(normalizers)
        self._register_conversation = register_conversation
        self._capture_gate = capture_gate
        self._capture_writer = capture_writer
        self._runtime_facade = runtime_facade
        self._pipeline_factory = pipeline_factory
        self._connections = {item.connection_id: item for item in settings.connections}
        self._connection_registry = ConfiguredConnectionRegistry()
        for connection in settings.connections:
            self._connection_registry.bind_bot(
                BotRef(
                    connection.connection_id,
                    connection.adapter,
                    connection.platform_scope,
                    connection.self_id,
                )
            )

    def _binding_for(
        self, connection_id: str, scene: SceneRef
    ) -> ScenePolicyBinding | None:
        matches = [
            binding
            for binding in self._settings.bindings
            if binding.connection_id == connection_id
            and binding.scene_kind == scene.kind
            and binding.scene_id == scene.scene_id
            and binding.parent_path == scene.parent_path
            and binding.thread_id == scene.thread_id
        ]
        if len(matches) > 1:
            raise ValueError("multiple scene policies match one trusted scene")
        return matches[0] if matches else None

    def _context(
        self,
        event: NormalizedEvent,
        conversation: ConversationRefV2,
        wake_reason: str,
    ) -> ChatContext:
        scene = conversation.scene
        direct = scene.kind in {"private", "webchat"}
        ctx = ChatContext(
            user_id=event.user_ref.raw_user_id,
            group_id=0,
            msg_id=0,
            message=event.text,
            source_kind=(
                "PASSIVE"
                if not wake_reason
                else "PRIVATE_DIRECT"
                if direct
                else "AT_MENTION"
            ),
            group_shared_space=conversation.memory_space,
            conversation_kind=scene.kind,
            conversation_key=conversation.canonical_key,
            bot_id=conversation.bot.self_id,
            peer_id=scene.scene_id,
            storage_session_id=conversation.storage_session_id,
            user_ref=event.user_ref,
            bot_ref=conversation.bot,
            scene_ref=scene,
            connection_id=conversation.bot.connection_id,
            adapter_name=conversation.bot.adapter,
            platform_scope=conversation.bot.platform_scope,
            scene_kind=scene.kind,
            scene_id=scene.scene_id,
            scene_parent_path=scene.parent_path,
            thread_id=scene.thread_id or "",
            platform_message_id=event.message_event.platform_message_id
            if event.message_event is not None
            else event.platform_message_id,
            sender_display_name=event.sender_display_name,
        )
        ctx.trigger = "reply"
        ctx.gate_path = f"transport:{wake_reason}" if wake_reason else "transport:passive"
        return ctx

    async def handle_event(
        self,
        connection_id: str,
        bot: Any,
        raw_event: Any,
        *,
        command_matched: bool = False,
        plugin_handled: bool = False,
    ) -> IngressResult:
        """Process one adapter event; no opaque or unconfigured scene is admitted."""
        connection = self._connections.get(connection_id)
        if connection is None:
            return IngressResult("rejected", "connection_not_configured")
        if not connection.enabled:
            return IngressResult("rejected", "connection_disabled")
        configured_slot = self._connection_registry.by_connection_id(connection_id)
        if configured_slot is None:
            return IngressResult("rejected", "connection_identity_unavailable")
        normalizer = self._normalizers.get(connection.adapter)
        if normalizer is None:
            return IngressResult("rejected", "adapter_normalizer_unavailable")
        try:
            normalized = normalizer.normalize(bot, raw_event, connection_id=connection_id)
        except Exception:
            return IngressResult("rejected", "normalization_failed")
        if isinstance(normalized, UnsupportedEvent):
            return IngressResult("rejected", normalized.reason_code)
        if not isinstance(normalized, NormalizedEvent):
            return IngressResult("rejected", "invalid_normalization_result")
        expected_bot = BotRef(
            connection.connection_id,
            connection.adapter,
            connection.platform_scope,
            connection.self_id,
        )
        if normalized.bot_ref != expected_bot:
            return IngressResult("rejected", "bot_identity_mismatch")
        if normalized.scene_ref.kind not in _SUPPORTED_SCENES:
            return IngressResult("rejected", "unsupported_or_opaque_scene")
        if normalized.scene_ref.kind == "thread" and not normalized.scene_ref.thread_id:
            return IngressResult("rejected", "thread_identity_missing")
        if normalized.is_self:
            return IngressResult("rejected", "self_echo")
        message_event = normalized.message_event
        if message_event is None:
            return IngressResult("rejected", "message_event_contract_missing")
        if message_event.event_kind != "create":
            return IngressResult("rejected", "event_kind_not_supported")
        if command_matched or plugin_handled or normalized.text.strip().startswith("/"):
            return IngressResult("rejected", "command_or_plugin_precedence")

        try:
            binding = self._binding_for(connection_id, normalized.scene_ref)
            effective = _policy_layers(self._settings, connection, binding)
        except (TypeError, ValueError):
            return IngressResult("rejected", "scene_policy_invalid")
        wake_reason = _wake_reason(normalized, effective)
        turn_requested = bool(
            effective.values.get("llm_enabled") and wake_reason and normalized.text.strip()
        )
        capture_requested = bool(effective.values.get("capture_enabled"))
        capture_available = self._capture_gate is not None and self._capture_writer is not None
        capture_status = (
            "not_requested"
            if not capture_requested
            else "unavailable"
            if not capture_available
            else "pending"
        )
        capture_allowed = False
        if capture_requested and capture_available:
            try:
                decision = await _maybe_await(self._capture_gate(normalized, effective))
                gate_allowed = getattr(decision, "allowed", None)
                if type(gate_allowed) is bool:
                    capture_allowed = gate_allowed
                elif type(decision) is bool:
                    capture_allowed = decision
                capture_status = "pending" if capture_allowed else "denied"
            except Exception:
                capture_status = "failed"

        if not turn_requested and not capture_allowed:
            if capture_requested:
                status = "capture_not_completed"
                reason_code = f"capture_{capture_status}"
            else:
                status = "not_triggered" if effective.values.get("llm_enabled") else "disabled"
                reason_code = ""
            return IngressResult(
                status,
                reason_code,
                capture_status=capture_status,
                turn_status="not_triggered" if effective.values.get("llm_enabled") else "disabled",
                policy_sources=effective.sources,
            )

        memory_space = binding.memory_space if binding is not None else None
        try:
            conversation = self._register_conversation(
                normalized.bot_ref, normalized.scene_ref, memory_space
            )
        except Exception:
            return IngressResult("rejected", "conversation_registration_failed")
        if (
            not isinstance(conversation, ConversationRefV2)
            or conversation.bot != normalized.bot_ref
            or conversation.scene != normalized.scene_ref
            or (memory_space is not None and conversation.memory_space != memory_space)
        ):
            return IngressResult("rejected", "conversation_registration_mismatch")
        ctx = self._context(normalized, conversation, wake_reason)
        if capture_requested and not capture_allowed:
            if capture_status in {"denied", "unavailable"}:
                ctx.capture_result = "not_captured_unavailable"
            elif capture_status == "failed":
                ctx.capture_result = "not_captured_error"

        turn_status = "not_triggered"
        turn_context = None
        if turn_requested:
            try:
                from memory.ownership import scope_for_chat_context

                scope_available = scope_for_chat_context(
                    ctx, memory_space=conversation.memory_space
                ) is not None
            except Exception:
                scope_available = False
            if not scope_available:
                turn_requested = False
                turn_status = "scope_unavailable"

        if capture_allowed:
            try:
                saved = await _maybe_await(
                    self._capture_writer(ctx, message_event)  # type: ignore[misc]
                )
                if isinstance(saved, ChatContext):
                    explicit_result = saved.capture_result
                    capture_status = (
                        "captured"
                        if explicit_result in {"captured", "ok"}
                        or saved.recorded_row_id > 0
                        else "failed"
                    )
                    if capture_status == "failed" and not saved.capture_result:
                        saved.capture_result = "not_captured_error"
                else:
                    capture_status = "captured"
                    ctx.capture_result = "captured"
            except Exception:
                # Gate and writer failures fail closed for capture; they do not
                # fabricate a captured result or suppress an independently allowed reply.
                capture_status = "failed"
                if not ctx.capture_result:
                    ctx.capture_result = "not_captured_error"

        if turn_requested:
            if self._runtime_facade is None or self._pipeline_factory is None:
                turn_status = "runtime_unavailable"
            else:
                try:
                    pipeline = self._pipeline_factory(ctx, effective)
                except Exception:
                    turn_status = "runtime_unavailable"
                else:
                    # Preserve RuntimeFacade deadline/cancellation/fencing errors
                    # for the adapter owner to handle; never downgrade them to success.
                    turn_context = await self._runtime_facade.submit_turn(
                        conversation.canonical_key, pipeline, ctx
                    )
                    turn_status = "submitted"

        if turn_status == "submitted":
            status = "turn_submitted"
        elif turn_status in {"failed", "runtime_unavailable", "scope_unavailable"}:
            status = "turn_not_completed"
        elif capture_status == "captured":
            status = "captured"
        elif capture_status in {"denied", "failed", "unavailable"}:
            status = "capture_not_completed"
        else:
            status = "admitted"
        return IngressResult(
            status,
            capture_status=capture_status,
            turn_status=turn_status,
            context=ctx,
            turn_context=turn_context,
            policy_sources=effective.sources,
        )


__all__ = ["IngressResult", "TransportIngress", "sqlite_v2_registrar"]
