# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""事件与结果对象。"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any

from .components import At, BaseMessageComponent, Image, Plain, Record, Reply, Face
from .exceptions import StellaCompatNotSupported

logger = logging.getLogger("astrbot_compat.events")

_ADMINS: set[int] | None = None


def _get_admins() -> set[int]:
    global _ADMINS
    if _ADMINS is not None:
        return _ADMINS
    try:
        from config import PROACTIVE_TOGGLE_ADMINS

        _ADMINS = set(PROACTIVE_TOGGLE_ADMINS)
    except Exception:
        _ADMINS = set()
    return _ADMINS


# ============================================================
# 结果对象
# ============================================================


class ResultContentType(enum.Enum):
    LLM_RESULT = "LLM_RESULT"
    GENERAL_RESULT = "GENERAL_RESULT"


class EventResultType(enum.Enum):
    CONTINUE = "CONTINUE"
    STOP = "STOP"


@dataclass
class EventResult:
    result_type: EventResultType = EventResultType.CONTINUE
    message_chain: Any | None = None


@dataclass
class MessageChain:
    chain: list[BaseMessageComponent] = field(default_factory=list)

    def message(self, text: str) -> MessageChain:
        self.chain.append(Plain(text))
        return self

    def plain(self, text: str) -> MessageChain:
        return self.message(text)

    def at(self, qq: str | int) -> MessageChain:
        self.chain.append(At(qq))
        return self

    def url_image(self, url: str) -> MessageChain:
        self.chain.append(Image.fromURL(url))
        return self

    def file_image(self, path: str) -> MessageChain:
        self.chain.append(Image.fromFileSystem(path))
        return self

    def base64_image(self, b64: str) -> MessageChain:
        self.chain.append(Image.fromBase64(b64))
        return self

    def record(self, file: str) -> MessageChain:
        # 简化：判断 file 是否 http
        if file.startswith("http://") or file.startswith("https://"):
            self.chain.append(Record.fromURL(file))
        else:
            self.chain.append(Record.fromFileSystem(file))
        return self

    def reply(self, id: str | int) -> MessageChain:  # noqa: A002
        self.chain.append(Reply(id))
        return self

    def get_plain_text(self) -> str:
        return "".join(c.text for c in self.chain if isinstance(c, Plain))


class MessageEventResult(MessageChain):
    def __init__(
        self,
        chain: list[BaseMessageComponent] | None = None,
        result_type: EventResultType | ResultContentType = EventResultType.CONTINUE,
        result_content_type: ResultContentType = ResultContentType.GENERAL_RESULT,
        use_t2i_: bool | None = None,
        async_stream: Any | None = None,  # noqa: ARG002
    ) -> None:
        super().__init__(chain=chain or [])
        # 兼容旧调用：result_type 传入的是 ResultContentType 时，视为 result_content_type
        if isinstance(result_type, ResultContentType):
            result_content_type = result_type
            result_type = EventResultType.CONTINUE
        self.result_type: EventResultType = result_type  # type: ignore[assignment]
        self.result_content_type: ResultContentType = result_content_type
        # 保留旧字段别名（插件若直接读 result_type 期望 ResultContentType，仍可通过 result_content_type 访问）
        # 为了兼容，将已废弃的 result_type 别名保留为 result_content_type 的镜像？不，保持分离
        self.use_t2i_ = use_t2i_
        self.async_stream = async_stream

    def use_t2i(self, flag: bool) -> MessageEventResult:
        self.use_t2i_ = flag
        return self

    def set_result_content_type(self, t: ResultContentType) -> MessageEventResult:
        self.result_content_type = t
        return self

    def is_llm_result(self) -> bool:
        return self.result_content_type == ResultContentType.LLM_RESULT

    def is_general_result(self) -> bool:
        return self.result_content_type == ResultContentType.GENERAL_RESULT


# ============================================================
# PlatformMetadata / AstrMessageObj
# ============================================================


@dataclass
class PlatformMetadata:
    name: str
    description: str
    id: str


_AIOCQHTTP_META = PlatformMetadata(
    name="aiocqhttp", description="Stella OneBot V11 bridge", id="aiocqhttp"
)


@dataclass
class SenderObj:
    user_id: int = 0
    nickname: str = ""
    card: str = ""


@dataclass
class AstrMessageObj:
    type: str = "GroupMessage"
    self_id: str = ""
    session_id: str = ""
    message_id: str = ""
    group_id: str = ""
    sender: SenderObj = field(default_factory=SenderObj)
    message: list[BaseMessageComponent] = field(default_factory=list)
    message_str: str = ""
    raw_message: Any | None = None
    timestamp: int = 0


# ============================================================
# AstrMessageEvent
# ============================================================


class AstrMessageEvent:
    def __init__(
        self,
        nb_event: Any,
        bot: Any,
        message_str: str,
        message_obj: AstrMessageObj,
        platform_meta: PlatformMetadata | None = None,
        session_id: str | None = None,
    ) -> None:
        self._nb_event = nb_event
        self._bot = bot
        self.bot = bot  # 公开别名，供插件 await event.bot.call_action(...)
        self.message_str = message_str
        self.message_obj = message_obj
        self.platform_meta = platform_meta or _AIOCQHTTP_META
        self.session_id = session_id or message_obj.session_id
        self.role = "member"
        try:
            r = getattr(getattr(nb_event, "sender", None), "role", "")
            if r in ("owner", "admin"):
                self.role = "admin"
            else:
                if int(getattr(nb_event, "user_id", 0)) in _get_admins():
                    self.role = "admin"
        except Exception:
            pass
        self.is_wake = False
        self._has_send_oper = False
        self._result: MessageEventResult | None = None
        self._stopped = False
        self._extras: dict[str, Any] = {}
        self._should_call_llm: bool | None = None

    # ---------- 同步取值 ----------
    def get_sender_id(self) -> str:
        return str(getattr(self._nb_event, "user_id", ""))

    def get_sender_name(self) -> str:
        sender = getattr(self._nb_event, "sender", None)
        if sender is not None:
            card = getattr(sender, "card", "")
            nick = getattr(sender, "nickname", "")
            return card or nick or ""
        return getattr(self.message_obj.sender, "nickname", "") or getattr(self.message_obj.sender, "card", "") or ""

    def get_group_id(self) -> str:
        gid = getattr(self._nb_event, "group_id", None)
        if gid is not None:
            return str(gid)
        return self.message_obj.group_id or ""

    def get_self_id(self) -> str:
        return str(getattr(self._nb_event, "self_id", "") or self.message_obj.self_id or "")

    def get_message_str(self) -> str:
        return self.message_str

    def get_message_outline(self) -> str:
        # 图片段换成 [图片]
        parts: list[str] = []
        for seg in self.message_obj.message:
            if isinstance(seg, Image):
                parts.append("[图片]")
            elif isinstance(seg, Plain):
                parts.append(seg.text)
            elif isinstance(seg, At):
                parts.append(f"@{seg.qq}")
            elif isinstance(seg, Record):
                parts.append("[语音]")
            else:
                # 尝试取 text
                t = getattr(seg, "text", None)
                if t:
                    parts.append(t)
                else:
                    parts.append(f"[{seg.type}]")
        return "".join(parts) if parts else self.message_str

    def get_messages(self) -> list[BaseMessageComponent]:
        return self.message_obj.message

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_platform_id(self) -> str:
        return "aiocqhttp"

    def get_message_type(self) -> str:
        return self.message_obj.type

    @property
    def unified_msg_origin(self) -> str:
        gid = self.get_group_id()
        typ = "GroupMessage" if gid else "FriendMessage"
        return f"aiocqhttp:{typ}:{self.session_id}"

    def is_private_chat(self) -> bool:
        gid = self.get_group_id()
        return not gid

    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_at_or_wake_command(self) -> bool:
        try:
            return bool(self._nb_event.is_tome())
        except Exception:
            return False

    @property
    def is_wake_command(self) -> bool:
        return self.is_at_or_wake_command

    # ---------- 结果构造 ----------
    def plain_result(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text)

    def image_result(self, url_or_path: str) -> MessageEventResult:
        r = MessageEventResult()
        if url_or_path.startswith("http://") or url_or_path.startswith("https://") or url_or_path.startswith("base64://"):
            r.url_image(url_or_path)
        else:
            r.file_image(url_or_path)
        return r

    def make_result(self) -> MessageEventResult:
        return MessageEventResult()

    def chain_result(self, chain: list) -> MessageEventResult:
        # chain 可能是 list[BaseMessageComponent] 或 MessageChain
        if isinstance(chain, MessageChain):
            return MessageEventResult(chain=chain.chain)
        return MessageEventResult(chain=list(chain))

    def set_result(self, r: MessageEventResult) -> None:
        self._result = r

    def get_result(self) -> MessageEventResult | None:
        return self._result

    def clear_result(self) -> None:
        self._result = None

    # ---------- 异步发送 ----------
    async def send(self, chain: Any) -> None:
        # 归一
        if isinstance(chain, MessageChain):
            lst = chain.chain
        elif isinstance(chain, MessageEventResult):
            lst = chain.chain
        elif isinstance(chain, list):
            lst = chain
        elif isinstance(chain, str):
            lst = [Plain(chain)]
        elif isinstance(chain, BaseMessageComponent):
            lst = [chain]
        else:
            lst = [Plain(str(chain))]
        try:
            from .components import to_onebot_message

            msg = to_onebot_message(lst)
            if not msg:
                logger.debug("[events] send 跳过空消息（可能仅含不支持段）")
                return
            await self._bot.send(self._nb_event, msg)
            self._has_send_oper = True
        except Exception as e:
            logger.error(f"[events] send 失败: {e}", exc_info=True)

    async def send_streamed(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        raise StellaCompatNotSupported("AstrMessageEvent.send_streamed")

    # ---------- 事件流控制 ----------
    def stop_event(self) -> None:
        self._stopped = True
        # 同步写入 result 的 result_type，保持与上游一致
        if self._result is not None:
            try:
                self._result.result_type = EventResultType.STOP
            except Exception:
                pass

    def continue_event(self) -> None:
        self._stopped = False
        if self._result is not None:
            try:
                self._result.result_type = EventResultType.CONTINUE
            except Exception:
                pass

    def is_stopped(self) -> bool:
        return self._stopped

    def should_call_llm(self, flag: bool | None = None) -> bool | None:
        if flag is not None:
            self._should_call_llm = flag
        return self._should_call_llm

    @property
    def call_llm(self) -> bool | None:
        return self._should_call_llm

    @call_llm.setter
    def call_llm(self, value: bool | None) -> None:
        self._should_call_llm = value

    # ---------- LLM / extra ----------
    def get_extra(self, key: str, default: Any = None) -> Any:
        return self._extras.get(key, default)

    def set_extra(self, key: str, value: Any) -> None:
        self._extras[key] = value

    def request_llm(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        raise StellaCompatNotSupported("AstrMessageEvent.request_llm")


# ============================================================
# 工厂
# ============================================================


async def build_event(nb_event: Any, bot: Any) -> AstrMessageEvent:
    from .components import from_onebot_message

    # OneBot Message -> chain
    try:
        raw_msg = nb_event.get_message()
    except Exception:
        raw_msg = None
    chain: list[BaseMessageComponent] = []
    if raw_msg is not None:
        try:
            chain = from_onebot_message(raw_msg)
        except Exception as e:
            logger.warning(f"[events] from_onebot_message 失败: {e}")
            chain = []

    try:
        message_str = nb_event.get_plaintext().strip()
    except Exception:
        message_str = ""

    # session_id / group_id
    try:
        gid = getattr(nb_event, "group_id", None)
        uid = getattr(nb_event, "user_id", 0)
        session_id = str(gid) if gid is not None else str(uid)
        group_id = str(gid) if gid is not None else ""
        self_id = str(getattr(nb_event, "self_id", ""))
        message_id = str(getattr(nb_event, "message_id", ""))
        timestamp = int(getattr(nb_event, "time", 0) or 0)
    except Exception:
        session_id = ""
        group_id = ""
        self_id = ""
        message_id = ""
        timestamp = 0

    # sender
    sender_obj = SenderObj()
    try:
        sender = getattr(nb_event, "sender", None)
        if sender is not None:
            sender_obj.user_id = int(getattr(sender, "user_id", 0) or getattr(nb_event, "user_id", 0) or 0)
            sender_obj.nickname = str(getattr(sender, "nickname", "") or "")
            sender_obj.card = str(getattr(sender, "card", "") or "")
        else:
            sender_obj.user_id = int(getattr(nb_event, "user_id", 0) or 0)
    except Exception:
        pass

    # type
    typ = "GroupMessage" if group_id else "FriendMessage"

    message_obj = AstrMessageObj(
        type=typ,
        self_id=self_id,
        session_id=session_id,
        message_id=message_id,
        group_id=group_id,
        sender=sender_obj,
        message=chain,
        message_str=message_str,
        raw_message=nb_event,
        timestamp=timestamp,
    )

    event = AstrMessageEvent(
        nb_event=nb_event,
        bot=bot,
        message_str=message_str,
        message_obj=message_obj,
        platform_meta=_AIOCQHTTP_META,
        session_id=session_id,
    )
    return event
