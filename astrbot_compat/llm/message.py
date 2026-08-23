# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""OpenAI 消息模型（对齐 astrbot.core.agent.message）。

上游是 pydantic 模型，插件会 `model_dump()`、会按字段名读写，因此这里也用 pydantic
（项目已依赖）。字段名与上游逐一对齐，不做"改进"。
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, PrivateAttr


class ContentPart(BaseModel):
    """多模态内容块基类。"""

    __content_part_registry: ClassVar[dict[str, type[ContentPart]]] = {}

    type: str
    _no_save: bool = PrivateAttr(default=False)

    def model_dump_for_context(self) -> dict:
        """转成可直接进 messages 的 dict。"""
        return self.model_dump(exclude_none=True)


class TextPart(ContentPart):
    type: str = "text"
    text: str


class ThinkPart(ContentPart):
    type: str = "think"
    think: str
    encrypted: str | None = None

    def model_dump_for_context(self) -> dict:
        # think 块不是 OpenAI 标准内容类型，回传上下文时降级为普通文本
        return {"type": "text", "text": self.think}


class ImageURL(BaseModel):
    url: str
    detail: str | None = None


class ImageURLPart(ContentPart):
    type: str = "image_url"
    image_url: ImageURL


class AudioURL(BaseModel):
    url: str
    format: str | None = None


class AudioURLPart(ContentPart):
    type: str = "audio_url"
    audio_url: AudioURL


class ToolCall(BaseModel):
    """OpenAI function-calling 的一次工具调用。"""

    class FunctionBody(BaseModel):
        name: str
        arguments: str
        """JSON 字符串，不是 dict——OpenAI 就是这么定的。"""

    type: Literal["function"] = "function"
    id: str
    function: FunctionBody
    extra_content: dict[str, Any] | None = None


class Message(BaseModel):
    """一条 OpenAI 格式消息。"""

    role: str
    content: str | list[ContentPart] | None = None
    tool_calls: list[ToolCall] | list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    _no_save: bool = PrivateAttr(default=False)

    def to_openai(self) -> dict:
        """转成可直接送给 API 的 dict。"""
        out: dict[str, Any] = {"role": self.role}
        if isinstance(self.content, list):
            out["content"] = [
                c.model_dump_for_context() if isinstance(c, ContentPart) else c
                for c in self.content
            ]
        elif self.content is not None:
            out["content"] = self.content
        if self.tool_calls:
            out["tool_calls"] = [
                tc.model_dump(exclude_none=True) if isinstance(tc, ToolCall) else tc
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.name:
            out["name"] = self.name
        return out


class UserMessageSegment(Message):
    role: str = "user"


class AssistantMessageSegment(Message):
    role: str = "assistant"


class ToolCallMessageSegment(Message):
    role: str = "tool"


class SystemMessageSegment(Message):
    role: str = "system"


def to_openai_dict(msg: Message | dict) -> dict:
    """messages 数组里既可能是 Message 也可能是裸 dict，统一成 dict。"""
    return msg.to_openai() if isinstance(msg, Message) else dict(msg)


__all__ = [
    "AssistantMessageSegment",
    "AudioURL",
    "AudioURLPart",
    "ContentPart",
    "ImageURL",
    "ImageURLPart",
    "Message",
    "SystemMessageSegment",
    "TextPart",
    "ThinkPart",
    "ToolCall",
    "ToolCallMessageSegment",
    "UserMessageSegment",
    "to_openai_dict",
]
