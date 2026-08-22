# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""事件与结果对象。"""

from __future__ import annotations

import contextlib
import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .components import (
    At,
    AtAll,
    BaseMessageComponent,
    File,
    Image,
    Plain,
    Record,
    Reply,
    Video,
    from_onebot_message,
)
from .exceptions import StellaCompatNotSupported

logger = logging.getLogger("astrbot_compat.events")

_ADMINS: set[str] | None = None
_WAKE_PREFIXES: list[str] | None = None


def _get_admins() -> set[str]:
    global _ADMINS
    if _ADMINS is not None:
        return _ADMINS
    admins: set[str] = set()
    with contextlib.suppress(Exception):
        from config import PROACTIVE_TOGGLE_ADMINS

        admins = {str(a) for a in PROACTIVE_TOGGLE_ADMINS}
    _ADMINS = admins
    return _ADMINS


def _get_wake_prefixes() -> list[str]:
    global _WAKE_PREFIXES
    if _WAKE_PREFIXES is not None:
        return _WAKE_PREFIXES
    prefixes = ["/"]
    with contextlib.suppress(Exception):
        from config.settings import ASTRBOT_WAKE_PREFIXES

        prefixes = [p for p in ASTRBOT_WAKE_PREFIXES if p]
    _WAKE_PREFIXES = prefixes
    return _WAKE_PREFIXES


# ============================================================
# 会话标识
# ============================================================


class MessageType(enum.Enum):
    GROUP_MESSAGE = "GroupMessage"
    FRIEND_MESSAGE = "FriendMessage"
    OTHER_MESSAGE = "OtherMessage"


@dataclass
class MessageSession:
    """`platform_id:message_type:session_id`。"""

    platform_name: str
    message_type: MessageType
    session_id: str
    platform_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.platform_id = self.platform_name

    def __str__(self) -> str:
        return f"{self.platform_id}:{self.message_type.value}:{self.session_id}"

    @staticmethod
    def from_str(session_str: str) -> MessageSession:
        platform_id, message_type, session_id = session_str.split(":", 2)
        return MessageSession(platform_id, MessageType(message_type), session_id)


MessageSesion = MessageSession  # 上游拼写错误的历史别名


# ============================================================
# 结果对象
# ============================================================


class ResultContentType(enum.Enum):
    LLM_RESULT = "LLM_RESULT"
    AGENT_RUNNER_ERROR = "AGENT_RUNNER_ERROR"
    GENERAL_RESULT = "GENERAL_RESULT"
    STREAMING_RESULT = "STREAMING_RESULT"
    STREAMING_FINISH = "STREAMING_FINISH"


class EventResultType(enum.Enum):
    CONTINUE = "CONTINUE"
    STOP = "STOP"


@dataclass
class MessageChain:
    chain: list[BaseMessageComponent] = field(default_factory=list)
    use_t2i_: bool | None = None
    use_markdown_: bool | None = None
    type: str | None = None

    def derive(self, chain: list[BaseMessageComponent] | None = None) -> MessageChain:
        """基于当前链创建新链，继承 use_t2i_ / use_markdown_ / type。"""
        new = MessageChain(chain=chain if chain is not None else [])
        new.use_t2i_ = self.use_t2i_
        new.use_markdown_ = self.use_markdown_
        new.type = self.type
        return new

    def message(self, message: str) -> MessageChain:
        self.chain.append(Plain(message))
        return self

    def plain(self, text: str) -> MessageChain:
        """Stella 扩展别名，等价于 `message()`。"""
        return self.message(text)

    def error(self, message: str) -> MessageChain:
        """上游已标注 deprecated，行为等同 `message()`。"""
        self.chain.append(Plain(message))
        return self

    def at(self, name: Any = None, qq: Any = None) -> MessageChain:
        """@某人。

        上游签名是 `at(name, qq)`；只传一个位置参数时按历史用法当作 qq 处理。
        """
        if qq is None:
            qq, name = name, None
        self.chain.append(At(qq=qq if qq is not None else "", name=name or ""))
        return self

    def at_all(self) -> MessageChain:
        self.chain.append(AtAll())
        return self

    def url_image(self, url: str) -> MessageChain:
        self.chain.append(Image.fromURL(url))
        return self

    def file_image(self, path: str) -> MessageChain:
        self.chain.append(Image.fromFileSystem(path))
        return self

    def base64_image(self, base64_str: str) -> MessageChain:
        self.chain.append(Image.fromBase64(base64_str))
        return self

    def record(self, file: str) -> MessageChain:
        """Stella 扩展：按是否为 http(s) 自动分流。"""
        if file.startswith(("http://", "https://")):
            self.chain.append(Record.fromURL(file))
        else:
            self.chain.append(Record.fromFileSystem(file))
        return self

    def video(self, file: str) -> MessageChain:
        """Stella 扩展：按是否为 http(s) 自动分流。"""
        if file.startswith(("http://", "https://")):
            self.chain.append(Video.fromURL(file))
        else:
            self.chain.append(Video.fromFileSystem(file))
        return self

    def file(self, path: str, name: str = "") -> MessageChain:
        """Stella 扩展：追加一个文件段。"""
        self.chain.append(File(name=name or path.rsplit("/", 1)[-1], file=path))
        return self

    def reply(self, id: str | int) -> MessageChain:  # noqa: A002
        """Stella 扩展：追加一个引用段。"""
        self.chain.append(Reply(id=id))
        return self

    def use_t2i(self, use_t2i: bool) -> MessageChain:
        self.use_t2i_ = use_t2i
        return self

    def use_markdown(self, use: bool | None = True) -> MessageChain:
        self.use_markdown_ = use
        return self

    def get_plain_text(self, with_other_comps_mark: bool = False) -> str:
        """拼接纯文本。与上游一致，用空格分隔。"""
        if not with_other_comps_mark:
            return " ".join(c.text for c in self.chain if isinstance(c, Plain))
        texts: list[str] = []
        for comp in self.chain:
            if isinstance(comp, Plain):
                texts.append(comp.text)
            else:
                texts.append(f"[{comp.__class__.__name__}]")
        return " ".join(texts)

    def squash_plain(self) -> MessageChain | None:
        """把所有 Plain 段合并到第一个 Plain 段里。"""
        if not self.chain:
            return None
        new_chain: list[BaseMessageComponent] = []
        first_plain: Plain | None = None
        plain_texts: list[str] = []
        for comp in self.chain:
            if isinstance(comp, Plain):
                if first_plain is None:
                    first_plain = comp
                    new_chain.append(comp)
                plain_texts.append(comp.text)
            else:
                new_chain.append(comp)
        if first_plain is not None:
            first_plain.text = "".join(plain_texts)
        self.chain = new_chain
        return self


@dataclass
class MessageEventResult(MessageChain):
    result_type: EventResultType | None = EventResultType.CONTINUE
    result_content_type: ResultContentType | None = ResultContentType.GENERAL_RESULT
    async_stream: Any | None = None

    def __post_init__(self) -> None:
        # 历史调用把 ResultContentType 传进 result_type，这里做一次纠偏。
        if isinstance(self.result_type, ResultContentType):
            self.result_content_type = self.result_type
            self.result_type = EventResultType.CONTINUE
        if self.chain is None:
            self.chain = []

    def stop_event(self) -> MessageEventResult:
        self.result_type = EventResultType.STOP
        return self

    def continue_event(self) -> MessageEventResult:
        self.result_type = EventResultType.CONTINUE
        return self

    def is_stopped(self) -> bool:
        return self.result_type == EventResultType.STOP

    def set_async_stream(self, stream: Any) -> MessageEventResult:
        self.async_stream = stream
        return self

    def set_result_content_type(self, typ: ResultContentType) -> MessageEventResult:
        self.result_content_type = typ
        return self

    def set_console_log(self, *args: Any, **kwargs: Any) -> MessageEventResult:
        """上游早期 API，仅打一条 debug 日志。"""
        logger.debug(f"[events] set_console_log {args} {kwargs}")
        return self

    def is_llm_result(self) -> bool:
        return self.result_content_type == ResultContentType.LLM_RESULT

    def is_general_result(self) -> bool:
        return self.result_content_type == ResultContentType.GENERAL_RESULT

    def is_model_result(self) -> bool:
        return self.result_content_type in (
            ResultContentType.LLM_RESULT,
            ResultContentType.AGENT_RUNNER_ERROR,
        )


CommandResult = MessageEventResult
EventResult = MessageEventResult


# ============================================================
# 平台元数据 / 消息对象
# ============================================================


@dataclass
class PlatformMetadata:
    name: str
    description: str
    id: str


_AIOCQHTTP_META = PlatformMetadata(
    name="aiocqhttp",
    description="Stella OneBot V11 bridge",
    id="aiocqhttp",
)


@dataclass
class MessageMember:
    user_id: str = ""
    nickname: str | None = None
    card: str = ""

    def __str__(self) -> str:
        return f"User ID: {self.user_id},Nickname: {self.nickname or 'N/A'}"


SenderObj = MessageMember  # Stella 早期命名


@dataclass
class Group:
    group_id: str = ""
    group_name: str | None = None
    group_avatar: str | None = None
    group_owner: str | None = None
    group_admins: list[str] | None = None
    members: list[MessageMember] | None = None


@dataclass
class AstrBotMessage:
    type: MessageType = MessageType.GROUP_MESSAGE
    self_id: str = ""
    session_id: str = ""
    message_id: str = ""
    group: Group | None = None
    sender: MessageMember = field(default_factory=MessageMember)
    message: list[BaseMessageComponent] = field(default_factory=list)
    message_str: str = ""
    raw_message: Any | None = None
    timestamp: int = 0

    @property
    def group_id(self) -> str:
        return self.group.group_id if self.group else ""

    @group_id.setter
    def group_id(self, value: str | None) -> None:
        if value:
            if self.group:
                self.group.group_id = value
            else:
                self.group = Group(group_id=value)
        else:
            self.group = None


AstrMessageObj = AstrBotMessage  # Stella 早期命名


# ============================================================
# AstrMessageEvent
# ============================================================


class AstrMessageEvent:
    def __init__(
        self,
        nb_event: Any = None,
        bot: Any = None,
        message_str: str = "",
        message_obj: AstrBotMessage | None = None,
        platform_meta: PlatformMetadata | None = None,
        session_id: str | None = None,
    ) -> None:
        self._nb_event = nb_event
        self._bot = bot
        self.bot = bot  # 公开别名，供插件 await event.bot.call_action(...)
        self.message_str = message_str
        self.message_obj = message_obj if message_obj is not None else AstrBotMessage()
        self.platform_meta = platform_meta or _AIOCQHTTP_META
        self.platform = self.platform_meta  # 上游 back-compat 别名
        self.session = MessageSession(
            platform_name=self.platform_meta.id,
            message_type=self.message_obj.type,
            session_id=session_id or self.message_obj.session_id,
        )
        self.role = "member"
        self.is_wake = False
        self.is_at_or_wake_command = False
        self.plugins_name: list[str] | None = None
        self._has_send_oper = False
        self._result: MessageEventResult | None = None
        self._force_stopped = False
        self._extras: dict[str, Any] = {}
        self._temporary_local_files: list[str] = []
        self.call_llm: bool | None = None

    # ---------- 会话标识 ----------
    @property
    def unified_msg_origin(self) -> str:
        return str(self.session)

    @unified_msg_origin.setter
    def unified_msg_origin(self, value: str) -> None:
        self.session = MessageSession.from_str(value)

    @property
    def session_id(self) -> str:
        return self.session.session_id

    @session_id.setter
    def session_id(self, value: str) -> None:
        self.session.session_id = value

    def get_session_id(self) -> str:
        return self.session_id

    # ---------- 同步取值 ----------
    def get_sender_id(self) -> str:
        if self._nb_event is not None:
            uid = getattr(self._nb_event, "user_id", None)
            if uid is not None:
                return str(uid)
        return str(self.message_obj.sender.user_id or "")

    def get_sender_name(self) -> str:
        sender = getattr(self._nb_event, "sender", None)
        if sender is not None:
            card = getattr(sender, "card", "") or ""
            nick = getattr(sender, "nickname", "") or ""
            if card or nick:
                return card or nick
        s = self.message_obj.sender
        return (s.card or "") or (s.nickname or "")

    def get_group_id(self) -> str:
        gid = getattr(self._nb_event, "group_id", None)
        if gid is not None:
            return str(gid)
        return self.message_obj.group_id or ""

    def get_self_id(self) -> str:
        sid = getattr(self._nb_event, "self_id", None)
        return str(sid) if sid is not None else str(self.message_obj.self_id or "")

    def get_message_str(self) -> str:
        return self.message_str

    def get_message_outline(self) -> str:
        parts: list[str] = []
        for seg in self.message_obj.message:
            if isinstance(seg, Plain):
                parts.append(seg.text)
            elif isinstance(seg, Image):
                parts.append("[图片]")
            elif isinstance(seg, Record):
                parts.append("[语音]")
            elif isinstance(seg, Video):
                parts.append("[视频]")
            elif isinstance(seg, File):
                parts.append("[文件]")
            elif isinstance(seg, AtAll):
                parts.append("@全体成员")
            elif isinstance(seg, At):
                parts.append(f"@{seg.qq}")
            else:
                parts.append(f"[{seg.__class__.__name__}]")
        return "".join(parts) if parts else self.message_str

    def get_messages(self) -> list[BaseMessageComponent]:
        return self.message_obj.message

    def get_platform_name(self) -> str:
        return self.platform_meta.name

    def get_platform_id(self) -> str:
        return self.platform_meta.id

    def get_message_type(self) -> MessageType:
        return self.message_obj.type

    def is_private_chat(self) -> bool:
        return self.get_message_type() == MessageType.FRIEND_MESSAGE

    def is_admin(self) -> bool:
        return self.role == "admin"

    def is_wake_up(self) -> bool:
        return self.is_wake

    # ---------- extras ----------
    def set_extra(self, key: str, value: Any) -> None:
        self._extras[key] = value

    def get_extra(self, key: str | None = None, default: Any = None) -> Any:
        if key is None:
            return self._extras
        return self._extras.get(key, default)

    def clear_extra(self) -> None:
        self._extras.clear()

    def track_temporary_local_file(self, path: str) -> None:
        if path and path not in self._temporary_local_files:
            self._temporary_local_files.append(path)

    def cleanup_temporary_local_files(self) -> None:
        paths = list(self._temporary_local_files)
        self._temporary_local_files.clear()
        for path in paths:
            try:
                p = Path(path)
                if p.exists():
                    p.unlink()
            except OSError as e:
                logger.warning(f"[events] 临时文件清理失败 {path}: {e}")

    # ---------- 结果构造 ----------
    def make_result(self) -> MessageEventResult:
        return MessageEventResult()

    def plain_result(self, text: str) -> MessageEventResult:
        return MessageEventResult().message(text)

    def image_result(self, url_or_path: str) -> MessageEventResult:
        if url_or_path.startswith(("http://", "https://", "base64://")):
            return MessageEventResult().url_image(url_or_path)
        return MessageEventResult().file_image(url_or_path)

    def chain_result(self, chain: list | MessageChain) -> MessageEventResult:
        mer = MessageEventResult()
        mer.chain = list(chain.chain) if isinstance(chain, MessageChain) else list(chain)
        return mer

    def set_result(self, result: MessageEventResult | MessageChain | str) -> None:
        """与上游一致：传入字符串会自动包装成 `MessageEventResult`。"""
        if isinstance(result, str):
            result = MessageEventResult().message(result)
        elif isinstance(result, MessageChain) and not isinstance(
            result,
            MessageEventResult,
        ):
            result = MessageEventResult(chain=list(result.chain))
        if isinstance(result, MessageEventResult) and result.chain is None:
            result.chain = []
        self._result = result

    def get_result(self) -> MessageEventResult | None:
        return self._result

    def clear_result(self) -> None:
        self._result = None

    # ---------- 事件流控制 ----------
    def stop_event(self) -> None:
        self._force_stopped = True
        if self._result is None:
            self.set_result(MessageEventResult().stop_event())
        else:
            self._result.stop_event()

    def continue_event(self) -> None:
        self._force_stopped = False
        if self._result is None:
            self.set_result(MessageEventResult().continue_event())
        else:
            self._result.continue_event()

    def is_stopped(self) -> bool:
        if self._force_stopped:
            return True
        if self._result is None:
            return False
        return self._result.is_stopped()

    def should_call_llm(self, call_llm: bool | None = None) -> bool | None:
        """上游签名要求必填参数并返回 None；这里额外允许无参读取当前值。"""
        if call_llm is not None:
            self.call_llm = call_llm
            return None
        return self.call_llm

    # ---------- 异步发送 ----------
    @staticmethod
    def _normalize_chain(chain: Any) -> list:
        if isinstance(chain, MessageChain):
            return list(chain.chain)
        if isinstance(chain, list):
            return list(chain)
        if isinstance(chain, str):
            return [Plain(chain)]
        if isinstance(chain, BaseMessageComponent):
            return [chain]
        return [Plain(str(chain))]

    async def send(self, message: Any) -> None:
        lst = self._normalize_chain(message)
        try:
            await self._send_components(lst)
            self._has_send_oper = True
        except Exception as e:
            logger.error(f"[events] send 失败: {e}", exc_info=True)

    async def _send_components(self, lst: list) -> None:
        from .components import split_forward_nodes, to_onebot_message

        forwards, rest = split_forward_nodes(lst)
        for nodes in forwards:
            await self._send_forward(nodes)
        if not rest:
            return
        msg = to_onebot_message(rest)
        if not msg:
            logger.debug("[events] send 跳过空消息（可能仅含不支持段）")
            return
        if self._bot is None or self._nb_event is None:
            raise StellaCompatNotSupported("AstrMessageEvent.send（缺少 bot/event）")
        await self._bot.send(self._nb_event, msg)

    async def _send_forward(self, nodes: Any) -> None:
        """合并转发走 OneBot 的 send_group_forward_msg / send_private_forward_msg。"""
        if self._bot is None:
            raise StellaCompatNotSupported("合并转发（缺少 bot）")
        payload = await nodes.to_dict()
        gid = self.get_group_id()
        if gid:
            payload["group_id"] = int(gid) if gid.isdigit() else gid
            await self._bot.call_action("send_group_forward_msg", **payload)
        else:
            uid = self.get_sender_id()
            payload["user_id"] = int(uid) if uid.isdigit() else uid
            await self._bot.call_action("send_private_forward_msg", **payload)

    async def send_streaming(
        self,
        generator: Any,
        use_fallback: bool = False,
    ) -> None:
        """把异步生成器产出的分片聚合成一条消息发送（无平台原生流式时的兜底）。"""
        _ = use_fallback
        buffer: MessageChain | None = None
        async for chain in generator:
            if not isinstance(chain, MessageChain):
                chain = MessageChain(chain=self._normalize_chain(chain))
            if buffer is None:
                buffer = chain
            else:
                buffer.chain.extend(chain.chain)
        if buffer is not None and buffer.chain:
            await self.send(buffer)

    # 历史拼写，保留别名
    send_streamed = send_streaming

    async def send_typing(self) -> None:
        """OneBot v11 无输入态动作，静默忽略。"""
        logger.debug("[events] send_typing 在 OneBot v11 下无对应动作，已忽略")

    async def stop_typing(self) -> None:
        logger.debug("[events] stop_typing 在 OneBot v11 下无对应动作，已忽略")

    async def react(self, emoji: str) -> None:
        """表情回应。优先用 NapCat/go-cqhttp 的 set_msg_emoji_like，失败则退化为发消息。"""
        mid = self.message_obj.message_id
        if self._bot is not None and mid:
            try:
                await self._bot.call_action(
                    "set_msg_emoji_like",
                    message_id=int(mid) if str(mid).isdigit() else mid,
                    emoji_id=str(emoji),
                )
                return
            except Exception as e:
                logger.debug(f"[events] set_msg_emoji_like 不可用，退化为发送消息: {e}")
        await self.send(MessageChain([Plain(emoji)]))

    async def get_group(self, group_id: str | None = None, **kwargs: Any) -> Group | None:
        """获取群信息（含成员列表）。不传 group_id 时取当前群；私聊返回 None。"""
        if group_id is None:
            group_id = self.get_group_id()
        if not group_id:
            return None
        if self._bot is None:
            raise StellaCompatNotSupported("AstrMessageEvent.get_group（缺少 bot）")
        gid = int(group_id) if str(group_id).isdigit() else group_id
        info: dict = await self._bot.call_action("get_group_info", group_id=gid, **kwargs)
        members: list[dict] = await self._bot.call_action(
            "get_group_member_list",
            group_id=gid,
        )
        owner_id = None
        admin_ids: list[str] = []
        for member in members or []:
            role = member.get("role")
            if role == "owner":
                owner_id = member.get("user_id")
            elif role == "admin":
                admin_ids.append(str(member.get("user_id")))
        return Group(
            group_id=str(group_id),
            group_name=(info or {}).get("group_name"),
            group_avatar="",
            group_owner=str(owner_id) if owner_id is not None else None,
            group_admins=admin_ids,
            members=[
                MessageMember(
                    user_id=str(m.get("user_id")),
                    nickname=m.get("nickname"),
                    card=m.get("card", "") or "",
                )
                for m in (members or [])
            ],
        )

    # ---------- LLM ----------
    def request_llm(self, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("AstrMessageEvent.request_llm")


# ============================================================
# 工厂
# ============================================================


def _resolve_wake(
    event: AstrMessageEvent,
    chain: list[BaseMessageComponent],
) -> None:
    """按上游 WakingCheckStage 的规则判定 is_at_or_wake_command，并剥掉唤醒前缀。

    命中条件（任一）：唤醒前缀开头 / @机器人 / @全体 / 引用机器人的消息 / 私聊。
    """
    self_id = event.get_self_id()
    for prefix in _get_wake_prefixes():
        if not event.message_str.startswith(prefix):
            continue
        # 群聊里若首段 @ 的不是机器人也不是全体，则不算唤醒
        if (
            not event.is_private_chat()
            and chain
            and isinstance(chain[0], At)
            and not isinstance(chain[0], AtAll)
            and str(chain[0].qq) != str(self_id)
        ):
            break
        event.is_at_or_wake_command = True
        event.is_wake = True
        event.message_str = event.message_str[len(prefix) :].strip()
        return

    for seg in chain:
        if (
            (isinstance(seg, At) and not isinstance(seg, AtAll) and str(seg.qq) == str(self_id))
            or isinstance(seg, AtAll)
            or (isinstance(seg, Reply) and str(seg.sender_id) == str(self_id))
        ):
            event.is_at_or_wake_command = True
            event.is_wake = True
            return

    if event.is_private_chat():
        event.is_at_or_wake_command = True
        event.is_wake = True


async def build_event(nb_event: Any, bot: Any) -> AstrMessageEvent:
    """OneBot 事件 -> AstrMessageEvent。"""
    chain: list[BaseMessageComponent] = []
    with contextlib.suppress(Exception):
        raw_msg = nb_event.get_message()
        if raw_msg is not None:
            chain = from_onebot_message(raw_msg)

    message_str = ""
    with contextlib.suppress(Exception):
        message_str = nb_event.get_plaintext().strip()

    gid = getattr(nb_event, "group_id", None)
    uid = getattr(nb_event, "user_id", 0)
    group_id = str(gid) if gid is not None else ""
    session_id = group_id or str(uid)
    self_id = str(getattr(nb_event, "self_id", "") or "")
    message_id = str(getattr(nb_event, "message_id", "") or "")
    timestamp = 0
    with contextlib.suppress(TypeError, ValueError):
        timestamp = int(getattr(nb_event, "time", 0) or 0)

    sender_obj = MessageMember()
    sender = getattr(nb_event, "sender", None)
    with contextlib.suppress(TypeError, ValueError):
        if sender is not None:
            sender_obj.user_id = str(getattr(sender, "user_id", "") or uid or "")
            sender_obj.nickname = str(getattr(sender, "nickname", "") or "")
            sender_obj.card = str(getattr(sender, "card", "") or "")
        else:
            sender_obj.user_id = str(uid or "")

    msg_type = MessageType.GROUP_MESSAGE if group_id else MessageType.FRIEND_MESSAGE
    message_obj = AstrBotMessage(
        type=msg_type,
        self_id=self_id,
        session_id=session_id,
        message_id=message_id,
        group=Group(group_id=group_id) if group_id else None,
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

    # 角色判定：群主/管理员，或配置里的全局管理员
    role = getattr(sender, "role", "") if sender is not None else ""
    if role in ("owner", "admin") or str(uid) in _get_admins():
        event.role = "admin"

    _resolve_wake(event, chain)
    return event
