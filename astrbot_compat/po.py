# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""持久化对象（对齐 astrbot.core.db.po 里插件会用到的那几个）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


@dataclass
class Conversation:
    """LLM 对话。

    注意 `history` 是 **JSON 字符串**而不是 list——上游就是这样，插件里到处是
    `json.loads(conv.history)`，改成 list 会把它们全打断。
    """

    platform_id: str
    user_id: str
    cid: str
    """对话 ID，uuid 字符串"""
    history: str = ""
    """JSON 字符串形式的消息列表"""
    title: str | None = ""
    persona_id: str | None = ""
    created_at: int = 0
    updated_at: int = 0
    token_usage: int = 0


class Personality(TypedDict, total=False):
    """LLM 人格。上游是 TypedDict，访问方式是 `persona["prompt"]` 而非属性。"""

    prompt: str
    name: str
    begin_dialogs: list[str]
    mood_imitation_dialogs: list[str]
    tools: list[str] | None
    skills: list[str] | None
    custom_error_message: str | None
    _begin_dialogs_processed: list[dict]
    _mood_imitation_dialogs_processed: str


__all__ = ["Conversation", "Personality"]
