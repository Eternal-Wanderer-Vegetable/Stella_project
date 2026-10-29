# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Transport-neutral identity contracts used at platform boundaries."""

from core.transport.capabilities import (
    ONEBOT_V11_CAPABILITIES,
    AdapterCapabilities,
    CapabilityProvider,
    RateLimitBucket,
    StaticCapabilityProvider,
)
from core.transport.keys import (
    conversation_key_v2,
    decode_conversation_key_v2,
    subject_key_v2,
)
from core.transport.media import MediaSource
from core.transport.models import BotRef, ConversationRefV2, SceneRef, UserRef
from core.transport.normalizers import (
    AdmissionDecision,
    AdmissionPolicy,
    GenericNoneBotNormalizer,
    NormalizedEvent,
    OneBot11Normalizer,
    UnsupportedEvent,
    normalize_onebot11,
    normalize_trusted_webchat,
)
from core.transport.outbound import (
    AdapterSendResult,
    DeliveryResult,
    DeliveryStatus,
    DeliveryTarget,
    MessageExporter,
    OutboundExporter,
    OutboundKind,
    OutboundMessage,
    OutboundPartResult,
    OutboundSegment,
    OutboundService,
    TargetCodec,
    TransportRegistry,
    get_outbound_service,
    split_outbound_message,
)
from core.transport.scheduler import OutboundSendScheduler

__all__ = [
    "ONEBOT_V11_CAPABILITIES",
    "AdapterCapabilities",
    "AdapterSendResult",
    "AdmissionDecision",
    "AdmissionPolicy",
    "BotRef",
    "CapabilityProvider",
    "ConversationRefV2",
    "DeliveryResult",
    "DeliveryStatus",
    "DeliveryTarget",
    "GenericNoneBotNormalizer",
    "MediaSource",
    "MessageExporter",
    "NormalizedEvent",
    "OneBot11Normalizer",
    "OutboundExporter",
    "OutboundKind",
    "OutboundMessage",
    "OutboundPartResult",
    "OutboundSegment",
    "OutboundSendScheduler",
    "OutboundService",
    "RateLimitBucket",
    "SceneRef",
    "StaticCapabilityProvider",
    "TargetCodec",
    "TransportRegistry",
    "UnsupportedEvent",
    "UserRef",
    "conversation_key_v2",
    "decode_conversation_key_v2",
    "get_outbound_service",
    "normalize_onebot11",
    "normalize_trusted_webchat",
    "split_outbound_message",
    "subject_key_v2",
]
