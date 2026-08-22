# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""消息段真类 + OneBot 双向转换。

`type` 字段沿用上游的大写枚举值（`"Plain"` / `"At"` / `"Image"` …），因为上游是
`ComponentType(str, Enum)`，插件里 `seg.type == "Image"` 这种写法很常见。转成
OneBot 段时才降为小写。
"""

from __future__ import annotations

import base64 as _base64
import contextlib
import enum
import json
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from .exceptions import StellaCompatNotSupported

logger = logging.getLogger("astrbot_compat.components")

_URL_PREFIXES = ("http://", "https://")


class ComponentType(str, enum.Enum):
    """与上游 `astrbot.core.message.components.ComponentType` 保持一致。"""

    Plain = "Plain"
    Image = "Image"
    Record = "Record"
    Video = "Video"
    File = "File"
    Face = "Face"
    At = "At"
    Node = "Node"
    Nodes = "Nodes"
    Poke = "Poke"
    Reply = "Reply"
    Forward = "Forward"
    RPS = "RPS"
    Dice = "Dice"
    Shake = "Shake"
    Share = "Share"
    Contact = "Contact"
    Location = "Location"
    Music = "Music"
    Json = "Json"
    Unknown = "Unknown"


def _truncate(value: Any) -> Any:
    """截断 base64 / 超长字符串，避免日志被正文淹没（对齐上游 __repr_args__）。"""
    if isinstance(value, str):
        if value.startswith("base64://"):
            return f"base64://<{len(value) - 9} chars>"
        if len(value) > 64:
            return f"{value[:64]}...<{len(value)} chars>"
    return value


def _is_url(s: str) -> bool:
    return s.startswith(_URL_PREFIXES)


class BaseMessageComponent:
    """所有消息段的基类。

    子类构造函数一律接受 `**kwargs`：上游是 pydantic 模型，插件传入未声明的字段不会
    报错，这里用「多余字段挂到实例上」来近似这一宽容度。
    """

    type: ComponentType = ComponentType.Unknown

    def __init__(self, **kwargs: Any) -> None:
        self._absorb(kwargs)

    def _absorb(self, kwargs: dict[str, Any]) -> None:
        for k, v in kwargs.items():
            if k == "type":
                continue
            with contextlib.suppress(AttributeError):
                setattr(self, k, v)

    def _data_fields(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if v is None or k == "type":
                continue
            data["type" if k == "_type" else k] = v
        return data

    def toDict(self) -> dict:  # noqa: N802
        """OneBot 风格字典。基类实现对齐上游：type 降为小写，其余字段进 data。"""
        return {"type": _type_name(self), "data": self._data_fields()}

    async def to_dict(self) -> dict:
        """异步版本，默认回退到同步 `toDict()`。"""
        return self.toDict()

    def toJson(self) -> dict:  # noqa: N802
        """历史遗留别名，等价于 `toDict()`。"""
        return self.toDict()

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={_truncate(v)!r}" for k, v in self.__dict__.items())
        return f"{self.__class__.__name__}({args})"

    def to_onebot_segment(self) -> MessageSegment:
        raise NotImplementedError


def _type_name(comp: BaseMessageComponent | Any) -> str:
    """组件的 OneBot 段名（小写）。`ComponentType` 是 str Enum，str() 会带类名前缀。"""
    t = getattr(comp, "type", "")
    return (t.value if isinstance(t, ComponentType) else str(t)).lower()


class Plain(BaseMessageComponent):
    type = ComponentType.Plain

    def __init__(self, text: str = "", convert: bool = True, **kwargs: Any) -> None:
        self.text = text
        self.convert = convert
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "text", "data": {"text": self.text}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.text(self.text)


class Face(BaseMessageComponent):
    type = ComponentType.Face

    def __init__(self, id: int = 0, **kwargs: Any) -> None:  # noqa: A002
        self.id = int(id)
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "face", "data": {"id": str(self.id)}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.face(self.id)


class At(BaseMessageComponent):
    type = ComponentType.At

    def __init__(
        self,
        qq: str | int = "",
        name: str | None = "",
        **kwargs: Any,
    ) -> None:
        self.qq = str(qq)
        self.name = name or ""
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "at", "data": {"qq": str(self.qq)}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.at(self.qq)


class AtAll(At):
    """@全体成员。继承 `At`，与上游一致（`isinstance(AtAll(), At)` 为 True）。"""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.pop("qq", None)
        super().__init__(qq="all", **kwargs)

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.at("all")


class _FileLike(BaseMessageComponent):
    """`Image` / `Record` / `Video` 的公共部分：file/url/path 三态与四个工厂方法。"""

    _onebot_factory: str = ""

    def __init__(self, file: str | None = "", **kwargs: Any) -> None:
        self.file = file or ""
        self.url = kwargs.pop("url", "") or ""
        self.path = kwargs.pop("path", "") or ""
        super().__init__(**kwargs)

    @classmethod
    def fromURL(cls, url: str, **kwargs: Any):  # noqa: N802
        if not _is_url(url):
            raise ValueError(f"not a valid url: {url!r}")
        return cls(file=url, **kwargs)

    @classmethod
    def fromFileSystem(cls, path: str, **kwargs: Any):  # noqa: N802
        try:
            resolved = Path(path).resolve(strict=False)
            return cls(file=resolved.as_uri(), path=str(resolved), **kwargs)
        except (ValueError, OSError):
            return cls(file=path, path=path, **kwargs)

    @classmethod
    def fromBase64(cls, base64: str, **kwargs: Any):  # noqa: N802
        if base64.startswith("base64://"):
            return cls(file=base64, **kwargs)
        return cls(file=f"base64://{base64}", **kwargs)

    @classmethod
    def fromBytes(cls, byte: bytes, **kwargs: Any):  # noqa: N802
        return cls.fromBase64(_base64.b64encode(byte).decode(), **kwargs)

    @classmethod
    def fromIO(cls, IO, **kwargs: Any):  # noqa: N802,N803
        return cls.fromBytes(IO.read(), **kwargs)

    def _local_path(self) -> str:
        """已经落在本地的路径，没有则返回空串。"""
        for candidate in (self.path, self.file):
            if not candidate or candidate.startswith("base64://"):
                continue
            p = candidate
            if p.startswith("file://"):
                with contextlib.suppress(ValueError, OSError):
                    from urllib.parse import unquote, urlparse

                    parsed = urlparse(p)
                    p = unquote(parsed.path)
                    if p.startswith("/") and len(p) > 2 and p[2] == ":":
                        p = p[1:]
            with contextlib.suppress(OSError):
                if Path(p).is_file():
                    return str(Path(p).resolve())
        return ""

    async def convert_to_file_path(self) -> str:
        """统一转成本地绝对路径；网络图片会先下载，base64 会先落盘。"""
        local = self._local_path()
        if local:
            return local
        src = self.file or self.url
        if src.startswith("base64://"):
            raw = _base64.b64decode(src[9:])
            tmp = Path(tempfile.gettempdir()) / f"stella_compat_{uuid.uuid4().hex}"
            tmp.write_bytes(raw)
            self.path = str(tmp)
            return str(tmp)
        if _is_url(src):
            import httpx

            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(src)
                resp.raise_for_status()
                raw = resp.content
            tmp = Path(tempfile.gettempdir()) / f"stella_compat_{uuid.uuid4().hex}"
            tmp.write_bytes(raw)
            self.path = str(tmp)
            return str(tmp)
        raise StellaCompatNotSupported(
            f"{self.__class__.__name__}.convert_to_file_path（无法解析来源 {src!r}）",
        )

    async def convert_to_base64(self) -> str:
        """统一转成不带 `base64://` 前缀的 base64 字符串。"""
        src = self.file or self.url
        if src.startswith("base64://"):
            return src[9:]
        path = await self.convert_to_file_path()
        return _base64.b64encode(Path(path).read_bytes()).decode()

    def to_onebot_segment(self) -> MessageSegment:
        factory = getattr(MessageSegment, self._onebot_factory)
        return factory(self.file or self.url)


class Image(_FileLike):
    type = ComponentType.Image
    _onebot_factory = "image"

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "image", "data": {"file": self.file or self.url}}


class Record(_FileLike):
    type = ComponentType.Record
    _onebot_factory = "record"

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "record", "data": {"file": self.file or self.url}}


class Video(_FileLike):
    type = ComponentType.Video
    _onebot_factory = "video"

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "video", "data": {"file": self.file or self.url}}


class File(BaseMessageComponent):
    """文件消息段。上游把本地路径存在 `file_`，`file` 是带下载语义的 property。"""

    type = ComponentType.File

    def __init__(self, name: str = "", file: str = "", url: str = "", **kwargs: Any) -> None:
        self.name = name
        self.file_ = ""
        self.url = url
        if file:
            self.file = file
        super().__init__(**kwargs)

    @property
    def file(self) -> str:
        if self.file_:
            with contextlib.suppress(OSError):
                if Path(self.file_).is_file():
                    return str(Path(self.file_).resolve())
        return self.file_ or ""

    @file.setter
    def file(self, value: str) -> None:
        if _is_url(value):
            self.url = value
        else:
            self.file_ = value

    async def get_file(self, allow_return_url: bool = False) -> str:
        if allow_return_url and self.url:
            return self.url
        if self.file_:
            with contextlib.suppress(OSError):
                if Path(self.file_).is_file():
                    return str(Path(self.file_).resolve())
        if self.url:
            import httpx

            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                resp = await client.get(self.url)
                resp.raise_for_status()
                raw = resp.content
            tmp = Path(tempfile.gettempdir()) / (self.name or f"stella_{uuid.uuid4().hex}")
            tmp.write_bytes(raw)
            self.file_ = str(tmp)
            return str(tmp)
        return ""

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "file", "data": {"name": self.name, "file": self.file_ or self.url}}

    async def to_dict(self) -> dict:
        target = await self.get_file(allow_return_url=True)
        return {"type": "file", "data": {"name": self.name, "file": target}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment("file", {"name": self.name, "file": self.file_ or self.url})


class Reply(BaseMessageComponent):
    """回复段。字段与上游对齐，收到的引用消息会带上被引用者信息。"""

    type = ComponentType.Reply

    def __init__(self, id: str | int = "", **kwargs: Any) -> None:  # noqa: A002
        self.id = str(id)
        self.chain: list[BaseMessageComponent] = kwargs.pop("chain", None) or []
        self.sender_id = kwargs.pop("sender_id", 0)
        self.sender_nickname = kwargs.pop("sender_nickname", "") or ""
        self.time = kwargs.pop("time", 0) or 0
        self.message_str = kwargs.pop("message_str", "") or ""
        # 上游标注 deprecated，但仍在字段表里，保留以免插件读取时 AttributeError
        self.text = kwargs.pop("text", "") or ""
        self.qq = kwargs.pop("qq", 0)
        self.seq = kwargs.pop("seq", 0)
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "reply", "data": {"id": str(self.id)}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.reply(int(self.id) if str(self.id).isdigit() else self.id)


class Poke(BaseMessageComponent):
    type = ComponentType.Poke

    def __init__(self, poke_type: str | int | None = None, **kwargs: Any) -> None:
        legacy_type = kwargs.pop("type", None)
        if poke_type is None:
            poke_type = legacy_type
        if poke_type in (None, "", "poke", "Poke"):
            poke_type = "126"
        self._type = str(poke_type)
        self.id = kwargs.pop("id", 0)
        self.qq = kwargs.pop("qq", 0)
        super().__init__(**kwargs)

    def target_id(self) -> str | None:
        for value in (self.id, self.qq):
            if value is None:
                continue
            text = str(value).strip()
            if text and text != "0":
                return text
        return None

    def toDict(self) -> dict:  # noqa: N802
        data = {"type": str(self._type or "126")}
        target = self.target_id()
        if target:
            data["id"] = target
        return {"type": "poke", "data": data}

    def to_onebot_segment(self) -> MessageSegment:
        d = self.toDict()
        return MessageSegment("poke", d["data"])


class Forward(BaseMessageComponent):
    type = ComponentType.Forward

    def __init__(self, id: str = "", **kwargs: Any) -> None:  # noqa: A002
        self.id = str(id)
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "forward", "data": {"id": self.id}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment("forward", {"id": self.id})


class Node(BaseMessageComponent):
    """合并转发中的单个节点。"""

    type = ComponentType.Node

    def __init__(
        self,
        content: list[BaseMessageComponent] | BaseMessageComponent | str | None = None,
        **kwargs: Any,
    ) -> None:
        if isinstance(content, Node):
            content = [content]
        elif isinstance(content, str):
            content = [Plain(content)]
        elif isinstance(content, BaseMessageComponent):
            content = [content]
        self.content: list[BaseMessageComponent] = list(content or [])
        self.id = kwargs.pop("id", 0)
        self.name = kwargs.pop("name", "") or ""
        self.uin = str(kwargs.pop("uin", "0") or "0")
        self.seq = kwargs.pop("seq", "")
        self.time = kwargs.pop("time", 0) or 0
        super().__init__(**kwargs)

    async def to_dict(self) -> dict:
        data_content = []
        for comp in self.content:
            if isinstance(comp, _FileLike):
                bs64 = await comp.convert_to_base64()
                data_content.append(
                    {
                        "type": _type_name(comp),
                        "data": {"file": f"base64://{bs64}"},
                    },
                )
            elif isinstance(comp, (Node, Nodes, File)):
                data_content.append(await comp.to_dict())
            else:
                data_content.append(comp.toDict())
        return {
            "type": "node",
            "data": {
                "user_id": str(self.uin),
                "nickname": self.name,
                "content": data_content,
            },
        }

    def toDict(self) -> dict:  # noqa: N802
        return {
            "type": "node",
            "data": {
                "user_id": str(self.uin),
                "nickname": self.name,
                "content": [c.toDict() for c in self.content],
            },
        }

    def to_onebot_segment(self) -> MessageSegment:
        raise StellaCompatNotSupported(
            "Node 需要走 send_group_forward_msg，不能作为普通消息段发送",
        )


class Nodes(BaseMessageComponent):
    """合并转发消息（多个 `Node`）。"""

    type = ComponentType.Nodes

    def __init__(self, nodes: list[Node] | None = None, **kwargs: Any) -> None:
        self.nodes: list[Node] = list(nodes or [])
        super().__init__(**kwargs)

    async def to_dict(self) -> dict:
        return {"messages": [await node.to_dict() for node in self.nodes]}

    def toDict(self) -> dict:  # noqa: N802
        return {"messages": [node.toDict() for node in self.nodes]}

    def to_onebot_segment(self) -> MessageSegment:
        raise StellaCompatNotSupported(
            "Nodes 需要走 send_group_forward_msg，不能作为普通消息段发送",
        )


class Json(BaseMessageComponent):
    type = ComponentType.Json

    def __init__(self, data: str | dict | None = None, **kwargs: Any) -> None:
        if isinstance(data, str):
            with contextlib.suppress(ValueError):
                data = json.loads(data)
        self.data = data if data is not None else {}
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        if isinstance(self.data, str):
            payload = self.data
        else:
            payload = json.dumps(self.data, ensure_ascii=False)
        return {"type": "json", "data": {"data": payload}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.json(self.toDict()["data"]["data"])


class Music(BaseMessageComponent):
    type = ComponentType.Music

    def __init__(self, type_: str = "qq", id: str | int = "", **kwargs: Any) -> None:  # noqa: A002
        self.type_ = type_
        self.id = str(id)
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {"type": "music", "data": {"type": self.type_, "id": self.id}}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.music(self.type_, int(self.id) if self.id.isdigit() else 0)


class Share(BaseMessageComponent):
    type = ComponentType.Share

    def __init__(self, url: str = "", title: str = "", **kwargs: Any) -> None:
        self.url = url
        self.title = title
        self.content = kwargs.pop("content", "") or ""
        self.image = kwargs.pop("image", "") or ""
        super().__init__(**kwargs)

    def toDict(self) -> dict:  # noqa: N802
        return {
            "type": "share",
            "data": {
                "url": self.url,
                "title": self.title,
                "content": self.content,
                "image": self.image,
            },
        }

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.share(self.url, self.title, self.content, self.image)


class Location(BaseMessageComponent):
    type = ComponentType.Location

    def __init__(self, lat: float = 0.0, lon: float = 0.0, **kwargs: Any) -> None:
        self.lat = lat
        self.lon = lon
        self.title = kwargs.pop("title", "") or ""
        self.content = kwargs.pop("content", "") or ""
        super().__init__(**kwargs)

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.location(self.lat, self.lon, self.title, self.content)


class Dice(BaseMessageComponent):
    type = ComponentType.Dice

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.dice()


class RPS(BaseMessageComponent):
    type = ComponentType.RPS

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.rps()


class Shake(BaseMessageComponent):
    type = ComponentType.Shake

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.shake()


class Contact(BaseMessageComponent):
    type = ComponentType.Contact

    def __init__(self, type_: str = "qq", id: str | int = "", **kwargs: Any) -> None:  # noqa: A002
        self.type_ = type_
        self.id = str(id)
        super().__init__(**kwargs)

    def to_onebot_segment(self) -> MessageSegment:
        if not self.id.isdigit():
            return MessageSegment.text("")
        if self.type_ == "group":
            return MessageSegment.contact_group(int(self.id))
        return MessageSegment.contact_user(int(self.id))


class Unknown(BaseMessageComponent):
    type = ComponentType.Unknown

    def __init__(self, text: str = "", **kwargs: Any) -> None:
        self.text = text
        super().__init__(**kwargs)

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.text(self.text)


# ============================================================
# OneBot 双向转换
# ============================================================

_SEG_BUILDERS = {
    "text": lambda d: Plain(d.get("text", "")),
    "image": lambda d: Image(file=d.get("url") or d.get("file") or "", url=d.get("url") or ""),
    "record": lambda d: Record(file=d.get("file") or d.get("url") or "", url=d.get("url") or ""),
    "video": lambda d: Video(file=d.get("file") or d.get("url") or "", url=d.get("url") or ""),
    "face": lambda d: Face(id=d.get("id", 0)),
    "forward": lambda d: Forward(id=d.get("id", "")),
    "json": lambda d: Json(d.get("data", "")),
    "poke": lambda d: Poke(d.get("type"), id=d.get("id", 0)),
    "share": lambda d: Share(
        url=d.get("url", ""),
        title=d.get("title", ""),
        content=d.get("content", ""),
        image=d.get("image", ""),
    ),
    "file": lambda d: File(
        name=d.get("name", "") or d.get("file", ""),
        file=d.get("path", "") or d.get("file", ""),
        url=d.get("url", ""),
    ),
    "dice": lambda _d: Dice(),
    "rps": lambda _d: RPS(),
    "shake": lambda _d: Shake(),
}


def _build_at(data: dict) -> BaseMessageComponent:
    qq = data.get("qq", "")
    if str(qq) == "all":
        return AtAll()
    return At(qq=qq, name=data.get("name", ""))


def _build_reply(data: dict) -> Reply:
    """OneBot 的 reply 段在 NapCat/go-cqhttp 下可能带被引用消息的完整信息。"""
    inner_chain: list[BaseMessageComponent] = []
    raw_inner = data.get("message") or data.get("content")
    if isinstance(raw_inner, list):
        with contextlib.suppress(Exception):
            inner_chain = from_onebot_dicts(raw_inner)
    sender = data.get("sender") or {}
    return Reply(
        id=data.get("id", ""),
        chain=inner_chain,
        sender_id=data.get("user_id") or sender.get("user_id") or 0,
        sender_nickname=data.get("nickname") or sender.get("nickname") or "",
        time=data.get("time", 0) or 0,
        message_str="".join(c.text for c in inner_chain if isinstance(c, Plain)),
    )


def _build_component(seg_type: str, data: dict) -> BaseMessageComponent:
    if seg_type == "at":
        return _build_at(data)
    if seg_type == "reply":
        return _build_reply(data)
    builder = _SEG_BUILDERS.get(seg_type)
    if builder is not None:
        return builder(data)
    return Unknown(text=f"[{seg_type}]")


def from_onebot_dicts(segs: list) -> list[BaseMessageComponent]:
    """`[{"type":..., "data":{...}}, ...]` -> 组件列表。"""
    result: list[BaseMessageComponent] = []
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        t = str(seg.get("type", ""))
        data = seg.get("data") or {}
        try:
            result.append(_build_component(t, data))
        except Exception as e:
            logger.warning(f"[components] seg 转换失败 {t}: {e}")
            result.append(Unknown(text=f"[{t}]"))
    return result


def from_onebot_message(msg: Message) -> list[BaseMessageComponent]:
    """OneBot Message -> 组件列表，未知 type 降级为 `Unknown`。"""
    result: list[BaseMessageComponent] = []
    for seg in msg:
        t = seg.type
        data = seg.data or {}
        try:
            result.append(_build_component(t, data))
        except Exception as e:
            logger.warning(f"[components] seg 转换失败 {t}: {e}")
            result.append(Unknown(text=f"[{t}]"))
    return result


def to_onebot_message(chain: list) -> Message:
    """组件列表 -> OneBot Message，不支持的段跳过（合并转发需走 forward 动作）。"""
    segs: list[MessageSegment] = []
    for item in chain:
        try:
            if isinstance(item, str):
                segs.append(MessageSegment.text(item))
            elif isinstance(item, MessageSegment):
                segs.append(item)
            elif isinstance(item, BaseMessageComponent):
                segs.append(item.to_onebot_segment())
            else:
                segs.append(MessageSegment.text(str(item)))
        except StellaCompatNotSupported as e:
            logger.warning(f"[components] 跳过不支持的段 {item}: {e}")
            continue
        except Exception as e:
            logger.warning(f"[components] 段转换失败 {item}: {e}")
            continue
    return Message(segs)


def split_forward_nodes(chain: list) -> tuple[list[Nodes], list]:
    """把合并转发段从普通段里分出来，供发送侧分别走不同的 OneBot 动作。"""
    forwards: list[Nodes] = []
    rest: list = []
    for item in chain:
        if isinstance(item, Nodes):
            forwards.append(item)
        elif isinstance(item, Node):
            forwards.append(Nodes([item]))
        else:
            rest.append(item)
    return forwards, rest


__all__ = [
    "RPS",
    "At",
    "AtAll",
    "BaseMessageComponent",
    "ComponentType",
    "Contact",
    "Dice",
    "Face",
    "File",
    "Forward",
    "Image",
    "Json",
    "Location",
    "Music",
    "Node",
    "Nodes",
    "Plain",
    "Poke",
    "Record",
    "Reply",
    "Shake",
    "Share",
    "Unknown",
    "Video",
    "from_onebot_dicts",
    "from_onebot_message",
    "split_forward_nodes",
    "to_onebot_message",
]
