# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""Transport-neutral identity contracts used at platform boundaries."""

from core.transport.keys import (
    conversation_key_v2,
    decode_conversation_key_v2,
    subject_key_v2,
)
from core.transport.models import BotRef, ConversationRefV2, SceneRef, UserRef

__all__ = [
    "BotRef",
    "ConversationRefV2",
    "SceneRef",
    "UserRef",
    "conversation_key_v2",
    "decode_conversation_key_v2",
    "subject_key_v2",
]
