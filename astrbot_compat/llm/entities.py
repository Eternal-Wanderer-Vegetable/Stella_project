# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Provider 相关实体（对齐 astrbot.core.provider.entities）。

上游这个模块直接 import openai / anthropic / google-genai 三家 SDK 只为给
`raw_completion` 标类型。兼容层不引这条依赖链，该字段用 Any。
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field
from typing import Any

from astrbot_compat.po import Conversation

from .message import (
    AssistantMessageSegment,
    ContentPart,
    ToolCall,
    ToolCallMessageSegment,
)
from .tool import ToolSet


class ProviderType(enum.Enum):
    CHAT_COMPLETION = "chat_completion"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    EMBEDDING = "embedding"
    RERANK = "rerank"


@dataclass
class ProviderMeta:
    """provider 实例的基础元数据。"""

    id: str
    model: str | None
    type: str
    provider_type: ProviderType = ProviderType.CHAT_COMPLETION


@dataclass
class ProviderMetaData(ProviderMeta):
    """注册用的适配器元数据。继承 ProviderMeta，所以 id/model/type 是必填。"""

    desc: str = ""
    cls_type: Any = None
    default_config_tmpl: dict | None = None
    provider_display_name: str | None = None


@dataclass
class ToolCallsResult:
    tool_calls_info: AssistantMessageSegment
    tool_calls_result: list[ToolCallMessageSegment]

    def to_openai_messages(self) -> list[dict]:
        return [
            self.tool_calls_info.to_openai(),
            *[item.to_openai() for item in self.tool_calls_result],
        ]

    def to_openai_messages_model(self) -> list[Any]:
        return [self.tool_calls_info, *self.tool_calls_result]


@dataclass
class TokenUsage:
    input_other: int = 0
    input_cached: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        return self.input_other + self.input_cached + self.output

    @property
    def input(self) -> int:
        return self.input_other + self.input_cached

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_other=self.input_other + other.input_other,
            input_cached=self.input_cached + other.input_cached,
            output=self.output + other.output,
        )

    def __sub__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_other=self.input_other - other.input_other,
            input_cached=self.input_cached - other.input_cached,
            output=self.output - other.output,
        )


@dataclass
class RerankResult:
    index: int
    relevance_score: float


@dataclass
class ProviderRequest:
    prompt: str | None = None
    session_id: str | None = ""
    image_urls: list[str] = field(default_factory=list)
    audio_urls: list[str] = field(default_factory=list)
    extra_user_content_parts: list[ContentPart] = field(default_factory=list)
    func_tool: ToolSet | None = None
    contexts: list[dict] = field(default_factory=list)
    system_prompt: str = ""
    conversation: Conversation | None = None
    tool_calls_result: list[ToolCallsResult] | ToolCallsResult | None = None
    model: str | None = None

    def __repr__(self) -> str:
        cid = self.conversation.cid if self.conversation else "N/A"
        return (
            f"ProviderRequest(prompt={self.prompt}, session_id={self.session_id}, "
            f"image_count={len(self.image_urls or [])}, "
            f"audio_count={len(self.audio_urls or [])}, "
            f"func_tool={self.func_tool}, "
            f"contexts={len(self.contexts or [])} msgs, "
            f"system_prompt={self.system_prompt[:40]!r}, "
            f"conversation_id={cid})"
        )

    __str__ = __repr__

    def append_tool_calls_result(self, tool_calls_result: ToolCallsResult) -> None:
        if not self.tool_calls_result:
            self.tool_calls_result = []
        if isinstance(self.tool_calls_result, ToolCallsResult):
            self.tool_calls_result = [self.tool_calls_result]
        self.tool_calls_result.append(tool_calls_result)

    async def assemble_context(self) -> dict:
        """把 prompt / image_urls 组装成一条 user 消息。

        与上游一致：只有单一文本块且无额外内容时降级成简单字符串形式，
        否则用多模态内容块数组。
        """
        blocks: list[dict] = []
        if self.prompt and self.prompt.strip():
            blocks.append({"type": "text", "text": self.prompt})
        elif self.image_urls:
            blocks.append({"type": "text", "text": "[图片]"})
        elif self.audio_urls:
            blocks.append({"type": "text", "text": "[音频]"})

        for part in self.extra_user_content_parts or []:
            blocks.append(
                part.model_dump_for_context()
                if isinstance(part, ContentPart)
                else dict(part),
            )

        for image_url in self.image_urls or []:
            url = await _to_image_data_url(image_url)
            if url:
                blocks.append({"type": "image_url", "image_url": {"url": url}})

        if (
            len(blocks) == 1
            and blocks[0]["type"] == "text"
            and not self.extra_user_content_parts
            and not self.image_urls
            and not self.audio_urls
        ):
            return {"role": "user", "content": blocks[0]["text"]}
        return {"role": "user", "content": blocks}


async def _to_image_data_url(src: str) -> str:
    """把图片来源统一成可直接进 messages 的 URL 或 data URL。"""
    import base64
    import contextlib
    from pathlib import Path

    if not src:
        return ""
    if src.startswith(("http://", "https://")):
        return src
    if src.startswith("base64://"):
        return f"data:image/jpeg;base64,{src[9:]}"
    if src.startswith("data:"):
        return src
    with contextlib.suppress(OSError):
        p = Path(src)
        if p.is_file():
            b64 = base64.b64encode(p.read_bytes()).decode()
            return f"data:image/jpeg;base64,{b64}"
    return ""


@dataclass
class LLMResponse:
    """一次 LLM 响应。

    注意：这是 dataclass，但**有自定义 __init__**，第二个位置参数是
    `completion_text` 而不是 `result_chain`；`completion_text` 本身是 property，
    挂了 result_chain 时读写都作用在链上。这两点都照抄上游，改了会打断插件。
    """

    role: str = "assistant"
    result_chain: Any = None
    tools_call_args: list[dict[str, Any]] = field(default_factory=list)
    tools_call_name: list[str] = field(default_factory=list)
    tools_call_ids: list[str] = field(default_factory=list)
    tools_call_extra_content: dict[str, dict[str, Any]] = field(default_factory=dict)
    reasoning_content: str | None = None
    reasoning_signature: str | None = None
    raw_completion: Any = None
    _completion_text: str = ""
    is_chunk: bool = False
    id: str | None = None
    usage: TokenUsage | None = None

    def __init__(
        self,
        role: str = "assistant",
        completion_text: str | None = None,
        result_chain: Any = None,
        tools_call_args: list[dict[str, Any]] | None = None,
        tools_call_name: list[str] | None = None,
        tools_call_ids: list[str] | None = None,
        tools_call_extra_content: dict[str, dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        reasoning_signature: str | None = None,
        raw_completion: Any = None,
        is_chunk: bool = False,
        id: str | None = None,  # noqa: A002
        usage: TokenUsage | None = None,
    ) -> None:
        self.role = role
        self._completion_text = ""
        self.result_chain = result_chain
        self.completion_text = completion_text or ""
        self.tools_call_args = tools_call_args if tools_call_args is not None else []
        self.tools_call_name = tools_call_name if tools_call_name is not None else []
        self.tools_call_ids = tools_call_ids if tools_call_ids is not None else []
        self.tools_call_extra_content = (
            tools_call_extra_content if tools_call_extra_content is not None else {}
        )
        self.reasoning_content = reasoning_content
        self.reasoning_signature = reasoning_signature
        self.raw_completion = raw_completion
        self.is_chunk = is_chunk
        self.id = id
        self.usage = usage

    @property
    def completion_text(self) -> str:
        if self.result_chain:
            return self.result_chain.get_plain_text()
        return self._completion_text

    @completion_text.setter
    def completion_text(self, value: str) -> None:
        if self.result_chain:
            from astrbot_compat.components import Plain

            self.result_chain.chain = [
                c for c in self.result_chain.chain if not isinstance(c, Plain)
            ]
            self.result_chain.chain.insert(0, Plain(value))
        else:
            self._completion_text = value

    def to_openai_tool_calls(self) -> list[dict]:
        ret = []
        for idx, args in enumerate(self.tools_call_args):
            payload: dict[str, Any] = {
                "id": self.tools_call_ids[idx],
                "function": {
                    "name": self.tools_call_name[idx],
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
                "type": "function",
            }
            extra = self.tools_call_extra_content.get(self.tools_call_ids[idx])
            if extra:
                payload["extra_content"] = extra
            ret.append(payload)
        return ret

    def to_openai_tool_calls_model(self) -> list[ToolCall]:
        return [
            ToolCall(
                id=self.tools_call_ids[idx],
                function=ToolCall.FunctionBody(
                    name=self.tools_call_name[idx],
                    arguments=json.dumps(args, ensure_ascii=False),
                ),
                extra_content=self.tools_call_extra_content.get(
                    self.tools_call_ids[idx],
                ),
            )
            for idx, args in enumerate(self.tools_call_args)
        ]

    # 上游历史拼写错误的别名，老插件在用
    def to_openai_to_calls_model(self) -> list[ToolCall]:
        return self.to_openai_tool_calls_model()


__all__ = [
    "Conversation",
    "LLMResponse",
    "ProviderMeta",
    "ProviderMetaData",
    "ProviderRequest",
    "ProviderType",
    "RerankResult",
    "TokenUsage",
    "ToolCallsResult",
]
