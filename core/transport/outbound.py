# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Transport-neutral outbound message, target, exporter, and delivery contracts.

No router or adapter is selected from model text. A send requires either the
explicit Bot handle from the current trusted event or an exact BotRef binding.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import parse_qsl, urlsplit

if TYPE_CHECKING:
    from gravitas.contracts import Deadline

from core.transport.capabilities import (
    AdapterCapabilities,
    CapabilityProvider,
    StaticCapabilityProvider,
)
from core.transport.media import MediaSource
from core.transport.models import BotRef, SceneRef
from core.transport.scheduler import OutboundSendScheduler, SchedulerAdmissionError


class OutboundKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    AT = "at"
    REPLY = "reply"
    NATIVE = "native_extension"


@dataclass(frozen=True, slots=True)
class OutboundSegment:
    kind: OutboundKind
    text: str = ""
    media: MediaSource | None = None
    target_id: str = ""
    display_name: str = ""
    adapter: str = ""
    native_segment: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        kind = OutboundKind(self.kind)
        object.__setattr__(self, "kind", kind)
        if kind is OutboundKind.TEXT:
            if not isinstance(self.text, str):
                raise ValueError("text segment needs string text")
        elif kind in {OutboundKind.IMAGE, OutboundKind.FILE}:
            if self.media is None or self.media.kind != kind.value:
                raise ValueError("media segment kind must match its MediaSource")
        elif kind in {OutboundKind.AT, OutboundKind.REPLY}:
            if not isinstance(self.target_id, str) or not self.target_id:
                raise ValueError(f"{kind.value} segment needs an opaque target ID")
        elif kind is OutboundKind.NATIVE and (not self.adapter or self.native_segment is None):
            raise ValueError("native extension needs an adapter and segment")

    @classmethod
    def text_segment(cls, text: str) -> "OutboundSegment":
        return cls(OutboundKind.TEXT, text=text)

    @classmethod
    def image(cls, media: MediaSource) -> "OutboundSegment":
        return cls(OutboundKind.IMAGE, media=media)

    @classmethod
    def file(cls, media: MediaSource) -> "OutboundSegment":
        return cls(OutboundKind.FILE, media=media)

    @classmethod
    def at(cls, user_id: str, display_name: str = "") -> "OutboundSegment":
        return cls(OutboundKind.AT, target_id=user_id, display_name=display_name)

    @classmethod
    def reply(cls, message_id: str) -> "OutboundSegment":
        return cls(OutboundKind.REPLY, target_id=message_id)

    @classmethod
    def native(cls, adapter: str, segment: Any) -> "OutboundSegment":
        return cls(OutboundKind.NATIVE, adapter=adapter, native_segment=segment)


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """An ordered, immutable sequence of platform-neutral message segments."""

    segments: tuple[OutboundSegment, ...]

    def __post_init__(self) -> None:
        segments = tuple(self.segments)
        if any(not isinstance(segment, OutboundSegment) for segment in segments):
            raise ValueError("OutboundMessage accepts only OutboundSegment values")
        object.__setattr__(self, "segments", segments)

    @classmethod
    def text(cls, text: str) -> "OutboundMessage":
        return cls((OutboundSegment.text_segment(text),))

    def dump(self) -> dict[str, Any]:
        """Return the portable form; process-local native segments are rejected."""
        result: list[dict[str, Any]] = []
        for segment in self.segments:
            if segment.kind is OutboundKind.NATIVE:
                raise ValueError("native extensions cannot be persisted")
            row: dict[str, Any] = {"kind": segment.kind.value}
            if segment.kind is OutboundKind.TEXT:
                row["text"] = segment.text
            elif segment.kind in {OutboundKind.IMAGE, OutboundKind.FILE}:
                assert segment.media is not None
                if _has_short_lived_credentials(segment.media.uri):
                    raise ValueError("short-lived media URLs cannot be persisted")
                row["media"] = {
                    "kind": segment.media.kind,
                    "uri": segment.media.uri,
                    "name": segment.media.name,
                    "mime_type": segment.media.mime_type,
                    "fallback_text": segment.media.fallback_text,
                }
            else:
                row["target_id"] = segment.target_id
                if segment.display_name:
                    row["display_name"] = segment.display_name
            result.append(row)
        return {"version": 1, "segments": result}

    @classmethod
    def load(cls, value: dict[str, Any]) -> "OutboundMessage":
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported OutboundMessage version")
        raw_segments = value.get("segments")
        if not isinstance(raw_segments, list):
            raise ValueError("OutboundMessage segments must be a list")
        segments: list[OutboundSegment] = []
        for raw in raw_segments:
            if not isinstance(raw, dict):
                raise ValueError("OutboundMessage segment must be an object")
            kind = OutboundKind(raw.get("kind", ""))
            if kind is OutboundKind.TEXT:
                segments.append(OutboundSegment.text_segment(raw.get("text", "")))
            elif kind in {OutboundKind.IMAGE, OutboundKind.FILE}:
                media = raw.get("media")
                if not isinstance(media, dict):
                    raise ValueError("media segment needs a media object")
                source = MediaSource(**media)
                segments.append(OutboundSegment.image(source) if kind is OutboundKind.IMAGE
                                else OutboundSegment.file(source))
            elif kind is OutboundKind.AT:
                segments.append(OutboundSegment.at(raw.get("target_id", ""), raw.get("display_name", "")))
            elif kind is OutboundKind.REPLY:
                segments.append(OutboundSegment.reply(raw.get("target_id", "")))
            else:
                raise ValueError("native extensions cannot be deserialized")
        return cls(tuple(segments))


_ROUTE_KEYS = frozenset({"guild_id", "channel_id", "thread_id", "event_id"})


@dataclass(frozen=True, slots=True)
class DeliveryTarget:
    """Versioned destination built from trusted BotRef and SceneRef values."""

    bot: BotRef
    scene: SceneRef
    target_codec_version: int = 1
    routing_parameters: tuple[tuple[str, str], ...] = ()
    expires_at_utc: str = ""
    event_handle: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bot, BotRef) or not isinstance(self.scene, SceneRef):
            raise ValueError("DeliveryTarget requires trusted BotRef and SceneRef")
        if self.target_codec_version != 1:
            raise ValueError("unsupported target codec version")
        pairs = tuple(sorted(self.routing_parameters))
        if any(
            len(pair) != 2 or pair[0] not in _ROUTE_KEYS
            or not isinstance(pair[1], str) or not pair[1]
            for pair in pairs
        ):
            raise ValueError("routing parameters contain an unsupported field")
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("routing parameters must have unique names")
        object.__setattr__(self, "routing_parameters", pairs)
        if not isinstance(self.expires_at_utc, str):
            raise ValueError("expires_at_utc must be a string")

    def dump(self) -> dict[str, Any]:
        """Persist routing identity only; never include the event or Bot handle."""
        return {
            "version": 1,
            "bot": {
                "connection_id": self.bot.connection_id,
                "adapter": self.bot.adapter,
                "platform_scope": self.bot.platform_scope,
                "self_id": self.bot.self_id,
            },
            "scene": {
                "kind": self.scene.kind,
                "scene_id": self.scene.scene_id,
                "parent_path": list(self.scene.parent_path),
                "thread_id": self.scene.thread_id,
            },
            "target_codec_version": self.target_codec_version,
            "routing_parameters": dict(self.routing_parameters),
            "expires_at_utc": self.expires_at_utc,
        }

    def dumps(self) -> str:
        return json.dumps(self.dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def load(cls, value: dict[str, Any]) -> "DeliveryTarget":
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported DeliveryTarget version")
        bot, scene = value.get("bot"), value.get("scene")
        if not isinstance(bot, dict) or not isinstance(scene, dict):
            raise ValueError("DeliveryTarget bot and scene are required")
        routing = value.get("routing_parameters", {})
        if not isinstance(routing, dict):
            raise ValueError("routing_parameters must be an object")
        return cls(
            bot=BotRef(**bot),
            scene=SceneRef(**scene),
            target_codec_version=value.get("target_codec_version", 0),
            routing_parameters=tuple(routing.items()),
            expires_at_utc=value.get("expires_at_utc", ""),
        )

    @classmethod
    def loads(cls, value: str) -> "DeliveryTarget":
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("DeliveryTarget JSON is malformed") from exc
        return cls.load(parsed)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if not self.expires_at_utc:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at_utc.replace("Z", "+00:00"))
        except ValueError:
            return True
        if expiry.tzinfo is None:
            return True
        return expiry <= (now or datetime.now(timezone.utc))


class DeliveryStatus(str, Enum):
    ACCEPTED = "accepted"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class OutboundPartResult:
    part_index: int
    status: DeliveryStatus
    message_ids: tuple[str, ...] = ()
    error_code: str = ""
    attempts: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeliveryStatus(self.status))
        object.__setattr__(self, "message_ids", _opaque_ids(self.message_ids))
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) or self.attempts <= 0:
            raise ValueError("outbound part attempts must be positive")


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    target: DeliveryTarget
    status: DeliveryStatus
    message_ids: tuple[str, ...] = ()
    parts: tuple[OutboundPartResult, ...] = ()
    error_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeliveryStatus(self.status))
        object.__setattr__(self, "message_ids", _opaque_ids(self.message_ids))
        object.__setattr__(self, "parts", tuple(self.parts))


@dataclass(frozen=True, slots=True)
class AdapterSendResult:
    status: DeliveryStatus
    message_ids: tuple[str, ...] = ()
    error_code: str = ""
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", DeliveryStatus(self.status))
        object.__setattr__(self, "message_ids", _opaque_ids(self.message_ids))
        retry_after = self.retry_after_seconds
        if retry_after is not None:
            if (
                isinstance(retry_after, bool)
                or not isinstance(retry_after, (int, float))
                or not math.isfinite(retry_after)
                or retry_after < 0
            ):
                raise ValueError("retry_after_seconds must be finite and non-negative")
            if self.status is not DeliveryStatus.FAILED:
                raise ValueError("retry_after_seconds is valid only for a definite failed send")
            object.__setattr__(self, "retry_after_seconds", float(retry_after))


def _opaque_ids(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, int)) and not isinstance(values, bool):
        values = (values,)
    result: list[str] = []
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        text = str(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


class MessageExporter(Protocol):
    async def send(
        self,
        target: DeliveryTarget,
        message: OutboundMessage,
        *,
        bot_handle: Any,
        capabilities: AdapterCapabilities,
        encoded_target: Any,
    ) -> AdapterSendResult: ...


OutboundExporter = MessageExporter


class TargetCodec(Protocol):
    def encode(self, target: DeliveryTarget, *, bot_handle: Any) -> Any:
        """Encode a trusted target using this adapter's versioned route contract."""


@dataclass(frozen=True, slots=True)
class ExporterBinding:
    exporter: MessageExporter
    target_codec: TargetCodec
    capability_provider: CapabilityProvider


class TransportRegistry:
    """Adapter exporter and exact connection bindings; no random Bot fallback."""

    def __init__(self) -> None:
        self._exporters: dict[str, ExporterBinding] = {}
        self._bots: dict[str, tuple[BotRef, Any]] = {}
        self._connection_slots: dict[tuple[str, str], str] = {}
        self._bot_generations: dict[str, int] = {}

    def register_exporter(
        self,
        adapter: str,
        exporter: MessageExporter,
        capabilities: AdapterCapabilities,
        *,
        target_codec: TargetCodec,
        capability_provider: CapabilityProvider | None = None,
    ) -> None:
        if not adapter or adapter != capabilities.adapter:
            raise ValueError("exporter adapter must match capability identity")
        self._exporters[adapter] = ExporterBinding(
            exporter,
            target_codec,
            capability_provider or StaticCapabilityProvider(capabilities),
        )

    def binding_for(self, adapter: str) -> ExporterBinding | None:
        return self._exporters.get(adapter)

    def bind_bot(self, bot_ref: BotRef, bot_handle: Any) -> None:
        if not isinstance(bot_ref, BotRef) or bot_handle is None:
            raise ValueError("bot binding needs a BotRef and Bot handle")
        if str(getattr(bot_handle, "self_id", "")) != bot_ref.self_id:
            raise ValueError("Bot handle self_id does not match BotRef")
        slot = (bot_ref.adapter, bot_ref.self_id)
        existing_connection = self._connection_slots.get(slot)
        if existing_connection is not None and existing_connection != bot_ref.connection_id:
            raise ValueError("adapter cannot represent duplicate self_id connections")
        existing = self._bots.get(bot_ref.connection_id)
        if existing is not None and existing[0] != bot_ref:
            raise ValueError("connection_id is already bound to a different BotRef")
        if existing is not None and existing[1] is bot_handle:
            return
        self._connection_slots[slot] = bot_ref.connection_id
        self._bots[bot_ref.connection_id] = (bot_ref, bot_handle)
        self._bot_generations[bot_ref.connection_id] = (
            self._bot_generations.get(bot_ref.connection_id, 0) + 1
        )

    def resolve_bot(self, bot_ref: BotRef) -> Any | None:
        item = self._bots.get(bot_ref.connection_id)
        if item is None or item[0] != bot_ref:
            return None
        return item[1]

    def resolve_bot_binding(self, bot_ref: BotRef) -> tuple[Any, int] | None:
        """Return the exact current handle and its monotonically increasing generation."""
        item = self._bots.get(bot_ref.connection_id)
        if item is None or item[0] != bot_ref:
            return None
        return item[1], self._bot_generations[bot_ref.connection_id]

    def unbind_bot(self, bot_ref: BotRef) -> bool:
        """Remove only the matching binding and invalidate any queued generation."""
        item = self._bots.get(bot_ref.connection_id)
        if item is None or item[0] != bot_ref:
            return False
        del self._bots[bot_ref.connection_id]
        self._connection_slots.pop((bot_ref.adapter, bot_ref.self_id), None)
        self._bot_generations[bot_ref.connection_id] = (
            self._bot_generations.get(bot_ref.connection_id, 0) + 1
        )
        return True

    def capabilities_for(self, target: DeliveryTarget) -> AdapterCapabilities | None:
        binding = self._exporters.get(target.bot.adapter)
        if binding is None:
            return None
        return binding.capability_provider.capabilities_for(target)


def split_outbound_message(message: OutboundMessage, max_text_length: int | None) -> tuple[OutboundMessage, ...]:
    """Split overlong text in order, preserving rich segments and their order."""
    if max_text_length is None:
        return (message,)
    if max_text_length <= 0:
        raise ValueError("max_text_length must be positive")
    output: list[OutboundMessage] = []
    current: list[OutboundSegment] = []
    current_text_length = 0

    def flush() -> None:
        nonlocal current, current_text_length
        if current:
            output.append(OutboundMessage(tuple(current)))
            current, current_text_length = [], 0

    for segment in message.segments:
        if segment.kind is not OutboundKind.TEXT or len(segment.text) <= max_text_length:
            if segment.kind is OutboundKind.TEXT and current_text_length + len(segment.text) > max_text_length:
                flush()
            current.append(segment)
            if segment.kind is OutboundKind.TEXT:
                current_text_length += len(segment.text)
            continue
        for offset in range(0, len(segment.text), max_text_length):
            chunk = OutboundSegment.text_segment(segment.text[offset : offset + max_text_length])
            if current_text_length and current_text_length + len(chunk.text) > max_text_length:
                flush()
            current.append(chunk)
            current_text_length += len(chunk.text)
            if current_text_length == max_text_length:
                flush()
    flush()
    return tuple(output) or (OutboundMessage(()),)


class OutboundService:
    def __init__(
        self,
        registry: TransportRegistry | None = None,
        *,
        scheduler: OutboundSendScheduler | None = None,
        max_rate_limit_retries: int = 2,
    ) -> None:
        self.registry = registry or TransportRegistry()
        if (
            isinstance(max_rate_limit_retries, bool)
            or not isinstance(max_rate_limit_retries, int)
            or max_rate_limit_retries < 0
            or max_rate_limit_retries > 5
        ):
            raise ValueError("max_rate_limit_retries must be between 0 and 5")
        self.scheduler = scheduler or OutboundSendScheduler()
        self.max_rate_limit_retries = max_rate_limit_retries
        if self.registry.binding_for("onebot-v11") is None:
            from core.transport.adapters.onebot_v11 import (
                OneBotV11Exporter,
                OneBotV11TargetCodec,
            )
            from core.transport.capabilities import ONEBOT_V11_CAPABILITIES

            self.registry.register_exporter(
                "onebot-v11",
                OneBotV11Exporter(),
                ONEBOT_V11_CAPABILITIES,
                target_codec=OneBotV11TargetCodec(),
            )

    async def send(
        self,
        target: DeliveryTarget,
        message: OutboundMessage,
        *,
        bot_handle: Any = None,
        instance_capabilities: AdapterCapabilities | None = None,
        deadline: "Deadline | None" = None,
    ) -> DeliveryResult:
        if target.is_expired():
            return DeliveryResult(target, DeliveryStatus.EXPIRED, error_code="send_window_expired")
        binding = self.registry.binding_for(target.bot.adapter)
        if binding is None:
            return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="adapter_exporter_missing")
        capabilities = binding.capability_provider.capabilities_for(target)
        if capabilities is None:
            return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="platform_scope_mismatch")
        if instance_capabilities is not None:
            try:
                capabilities = capabilities.narrowed_by(instance_capabilities)
            except ValueError:
                return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="capability_identity_mismatch")

        bot_binding = self.registry.resolve_bot_binding(target.bot)
        if bot_handle is None and bot_binding is None:
            return DeliveryResult(target, DeliveryStatus.FAILED, error_code="exact_bot_binding_missing")
        if bot_handle is not None and str(getattr(bot_handle, "self_id", "")) != target.bot.self_id:
            return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="bot_identity_mismatch")
        allowed_scene = {
            "private": capabilities.private,
            "group": capabilities.group,
            "channel": capabilities.channel,
            "thread": capabilities.thread,
        }.get(target.scene.kind)
        if allowed_scene is None:
            if target.scene.kind != "opaque" or target.event_handle is None:
                return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="scene_kind_unsupported")
        elif not allowed_scene:
            return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="scene_capability_missing")

        projected, error = _apply_capabilities(message, capabilities, target.bot.adapter)
        if error:
            return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code=error)
        physical_messages = split_outbound_message(projected, capabilities.max_text_length)
        parts: list[OutboundPartResult] = []
        message_ids: list[str] = []
        deadline_error = ""

        def current_bot() -> tuple[Any | None, str]:
            latest = self.registry.resolve_bot_binding(target.bot)
            if bot_binding is None:
                return bot_handle, ""
            if latest is None or latest[1] != bot_binding[1]:
                return None, "exact_bot_binding_stale"
            if bot_handle is not None and latest[0] is not bot_handle:
                return None, "exact_bot_binding_stale"
            return (bot_handle if bot_handle is not None else latest[0]), ""

        async def deliver(reserve_part, effective_deadline) -> DeliveryResult:
            nonlocal deadline_error
            bot, bot_error = current_bot()
            if bot_error:
                return DeliveryResult(target, DeliveryStatus.FAILED, error_code=bot_error)
            if bot is None:
                return DeliveryResult(target, DeliveryStatus.FAILED, error_code="exact_bot_binding_missing")
            adapter_getter = getattr(getattr(bot, "adapter", None), "get_name", None)
            runtime_adapter = adapter_getter() if callable(adapter_getter) else ""
            if isinstance(runtime_adapter, str) and runtime_adapter and (
                _adapter_key(runtime_adapter) != _adapter_key(target.bot.adapter)
            ):
                return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="adapter_identity_mismatch")
            try:
                encoded_target = binding.target_codec.encode(target, bot_handle=bot)
            except Exception:
                return DeliveryResult(target, DeliveryStatus.UNSUPPORTED, error_code="target_codec_rejected")

            for index, part in enumerate(physical_messages):
                attempts = 0
                part_ids: list[str] = []
                retry_after = 0.0
                last_result: AdapterSendResult | None = None
                while True:
                    try:
                        await reserve_part(wait_before_seconds=retry_after)
                    except SchedulerAdmissionError as exc:
                        if last_result is not None:
                            parts.append(OutboundPartResult(
                                index,
                                DeliveryStatus.FAILED,
                                tuple(part_ids),
                                f"{last_result.error_code or 'rate_limited'}_retry_not_sent",
                                attempts,
                            ))
                        elif not parts:
                            status = (
                                DeliveryStatus.EXPIRED
                                if exc.error_code in {"turn_deadline", "send_window_expired"}
                                else DeliveryStatus.FAILED
                            )
                            return DeliveryResult(target, status, error_code=exc.error_code)
                        deadline_error = exc.error_code
                        break

                    bot, bot_error = current_bot()
                    if bot_error or bot is None:
                        code = bot_error or "exact_bot_binding_missing"
                        parts.append(OutboundPartResult(
                            index, DeliveryStatus.FAILED, error_code=code, attempts=max(1, attempts)
                        ))
                        break
                    attempts += 1
                    response: list[AdapterSendResult] = []
                    try:
                        async def send_call(
                            current_part=part,
                            current_bot_handle=bot,
                            response_holder=response,
                        ):
                            result = await binding.exporter.send(
                                target,
                                current_part,
                                bot_handle=current_bot_handle,
                                capabilities=capabilities,
                                encoded_target=encoded_target,
                            )
                            response_holder.append(result)
                            return result
                        if effective_deadline is None:
                            result = await send_call()
                        else:
                            from gravitas.deadlines import run_with_deadline

                            result = await run_with_deadline(
                                send_call, effective_deadline, phase="send.physical"
                            )
                    except TimeoutError:
                        result = AdapterSendResult(DeliveryStatus.UNKNOWN, error_code="send_timeout")
                    except Exception as exc:
                        from gravitas.errors import DeadlineExceeded

                        if isinstance(exc, DeadlineExceeded) and response:
                            result = response[-1]
                        else:
                            result = AdapterSendResult(
                                DeliveryStatus.UNKNOWN,
                                error_code=("send_deadline_unknown" if isinstance(exc, DeadlineExceeded)
                                            else "send_result_unknown"),
                            )
                    for message_id in result.message_ids:
                        if message_id not in part_ids:
                            part_ids.append(message_id)
                        if message_id not in message_ids:
                            message_ids.append(message_id)
                    retryable = (
                        result.status is DeliveryStatus.FAILED
                        and not result.message_ids
                        and result.retry_after_seconds is not None
                        and result.error_code.lower() in {
                            "429", "http_429", "rate_limited", "rate_limit_exceeded"
                        }
                    )
                    if retryable and attempts <= self.max_rate_limit_retries:
                        last_result = result
                        retry_after = result.retry_after_seconds or 0.0
                        continue
                    parts.append(OutboundPartResult(
                        index, result.status, tuple(part_ids), result.error_code, attempts
                    ))
                    break
                if not parts or parts[-1].part_index != index:
                    break
                if parts[-1].status is not DeliveryStatus.ACCEPTED:
                    break

            statuses = [part.status for part in parts]
            if (
                statuses
                and len(parts) == len(physical_messages)
                and all(status is DeliveryStatus.ACCEPTED for status in statuses)
            ):
                status = DeliveryStatus.ACCEPTED
            elif any(status is DeliveryStatus.ACCEPTED for status in statuses):
                status = DeliveryStatus.PARTIAL
            elif statuses:
                status = statuses[-1]
            else:
                status = DeliveryStatus.FAILED
            error_code = deadline_error or next(
                (part.error_code for part in reversed(parts) if part.error_code), ""
            )
            return DeliveryResult(target, status, tuple(message_ids), tuple(parts), error_code)

        try:
            return await self.scheduler.run(
                target,
                capabilities.quota_buckets(),
                deadline=deadline,
                send_window_seconds=capabilities.send_window_seconds,
                operation=deliver,
            )
        except SchedulerAdmissionError as exc:
            status = (
                DeliveryStatus.EXPIRED
                if exc.error_code in {"turn_deadline", "send_window_expired"}
                else DeliveryStatus.FAILED
            )
            return DeliveryResult(target, status, error_code=exc.error_code)


def _adapter_key(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _has_short_lived_credentials(uri: str) -> bool:
    parsed = urlsplit(uri)
    if parsed.username or parsed.password:
        return True
    sensitive = (
        "token", "auth", "signature", "secret", "credential", "ticket",
        "access_key", "access_token",
    )
    return any(any(marker in key.lower() for marker in sensitive) for key, _ in parse_qsl(parsed.query))


def _apply_capabilities(
    message: OutboundMessage, capabilities: AdapterCapabilities, adapter: str
) -> tuple[OutboundMessage, str]:
    projected: list[OutboundSegment] = []
    for segment in message.segments:
        if segment.kind is OutboundKind.IMAGE and not capabilities.upload_image:
            assert segment.media is not None
            if segment.media.fallback_text:
                projected.append(OutboundSegment.text_segment(segment.media.fallback_text))
                continue
            return OutboundMessage(()), "image_upload_unsupported"
        if segment.kind is OutboundKind.FILE and not capabilities.upload_file:
            assert segment.media is not None
            if segment.media.fallback_text:
                projected.append(OutboundSegment.text_segment(segment.media.fallback_text))
                continue
            return OutboundMessage(()), "file_upload_unsupported"
        if segment.kind is OutboundKind.AT and not capabilities.mention_user:
            continue
        if segment.kind is OutboundKind.REPLY and not capabilities.quote:
            continue
        if segment.kind is OutboundKind.NATIVE and segment.adapter != adapter:
            return OutboundMessage(()), "native_segment_adapter_mismatch"
        projected.append(segment)
    return OutboundMessage(tuple(projected)), ""


_default_service: OutboundService | None = None


def get_outbound_service() -> OutboundService:
    global _default_service
    if _default_service is None:
        _default_service = OutboundService()
    return _default_service


def reset_outbound_service_for_tests() -> None:
    global _default_service
    _default_service = None


__all__ = [
    "AdapterSendResult",
    "DeliveryResult",
    "DeliveryStatus",
    "DeliveryTarget",
    "MessageExporter",
    "OutboundExporter",
    "OutboundKind",
    "OutboundMessage",
    "OutboundPartResult",
    "OutboundSegment",
    "OutboundService",
    "TargetCodec",
    "TransportRegistry",
    "get_outbound_service",
    "reset_outbound_service_for_tests",
    "split_outbound_message",
]
