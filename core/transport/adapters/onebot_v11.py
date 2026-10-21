# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""OneBot v11 outbound codec implemented with the locked UniMessage API."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from core.transport.capabilities import AdapterCapabilities
from core.transport.media import MediaSource
from core.transport.outbound import (
    AdapterSendResult,
    DeliveryStatus,
    DeliveryTarget,
    OutboundKind,
    OutboundMessage,
)


class OneBotV11Exporter:
    """Map supported Stella segments to UniMessage and keep Bot selection explicit."""

    async def send(
        self,
        target: DeliveryTarget,
        message: OutboundMessage,
        *,
        bot_handle: Any,
        capabilities: AdapterCapabilities,
        encoded_target: Any,
    ) -> AdapterSendResult:
        from nonebot_plugin_alconna.uniseg import (
            At,
            File,
            Image,
            Reply,
            Text,
            UniMessage,
        )

        segments: list[Any] = []
        for segment in message.segments:
            if segment.kind is OutboundKind.TEXT:
                if segment.text:
                    segments.append(Text(segment.text))
            elif segment.kind is OutboundKind.IMAGE:
                assert segment.media is not None
                segments.append(_uniseg_media(Image, segment.media))
            elif segment.kind is OutboundKind.FILE:
                assert segment.media is not None
                segments.append(_uniseg_media(File, segment.media))
            elif segment.kind is OutboundKind.AT:
                segments.append(At("user", segment.target_id, display=segment.display_name or None))
            elif segment.kind is OutboundKind.REPLY:
                segments.append(Reply(segment.target_id))
            elif segment.kind is OutboundKind.NATIVE:
                segments.append(segment.native_segment)
        if not segments:
            return AdapterSendResult(DeliveryStatus.UNSUPPORTED, error_code="empty_after_export")

        try:
            receipt = await UniMessage(segments).send(
                target=encoded_target,
                bot=bot_handle,
            )
        except TimeoutError:
            return AdapterSendResult(DeliveryStatus.UNKNOWN, error_code="send_timeout")
        except Exception as exc:
            # Uniseg SerializeFailed happens before the adapter send; all other
            # exceptions are conservatively unknown because an API side effect
            # may already have occurred.
            if exc.__class__.__name__ in {"SerializeFailed", "ActionFailed"}:
                return AdapterSendResult(DeliveryStatus.FAILED, error_code="adapter_rejected")
            raise
        ids = tuple(_id_text(value) for value in getattr(receipt, "msg_ids", ()) if _id_text(value))
        return AdapterSendResult(DeliveryStatus.ACCEPTED, ids)


class OneBotV11TargetCodec:
    def encode(self, target: DeliveryTarget, *, bot_handle: Any) -> Any:
        from nonebot_plugin_alconna.uniseg import Target

        if target.target_codec_version != 1:
            raise ValueError("OneBot target codec version is unsupported")
        if target.bot.adapter != "onebot-v11" or target.bot.platform_scope != "qq":
            raise ValueError("OneBot target identity mismatch")
        if target.scene.kind == "opaque":
            if target.event_handle is None:
                raise ValueError("opaque target is not event-bound")
            return target.event_handle
        if target.scene.kind not in {"group", "private"}:
            raise ValueError("OneBot v11 has no channel or thread target codec")
        if target.scene.thread_id or target.scene.parent_path:
            raise ValueError("OneBot v11 cannot address a nested scene")
        adapter = getattr(bot_handle, "adapter", None)
        adapter_get_name = getattr(adapter, "get_name", None)
        adapter_name = adapter_get_name() if callable(adapter_get_name) else ""
        if not isinstance(adapter_name, str) or not adapter_name:
            raise ValueError("Bot adapter name is unavailable")
        return Target(
            id=target.scene.scene_id,
            private=target.scene.kind == "private",
            self_id=target.bot.self_id,
            adapter=adapter_name,
            platform=target.bot.platform_scope,
        )


def _uniseg_media(segment_type: Any, media: MediaSource) -> Any:
    source = media.uri
    parsed = urlsplit(source)
    kwargs: dict[str, Any] = {"mimetype": media.mime_type or None}
    if parsed.scheme in {"http", "https"}:
        kwargs["url"] = source
    elif parsed.scheme == "data":
        header, separator, body = source.partition(",")
        if not separator or ";base64" not in header:
            raise ValueError("only base64 data URIs are supported")
        try:
            raw = base64.b64decode(body, validate=True)
        except binascii.Error as exc:
            raise ValueError("invalid base64 media URI") from exc
        kwargs["raw"] = BytesIO(raw)
        if not media.mime_type:
            kwargs["mimetype"] = header[5:].split(";", 1)[0]
    elif parsed.scheme == "base64":
        try:
            kwargs["raw"] = BytesIO(base64.b64decode(unquote(parsed.path or parsed.netloc), validate=True))
        except binascii.Error as exc:
            raise ValueError("invalid base64 media URI") from exc
    else:
        path = url2pathname(unquote(parsed.path)) if parsed.scheme == "file" else source
        kwargs["path"] = Path(path)
    if media.name:
        kwargs["name"] = media.name
    return segment_type(**kwargs)


def _id_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value)
