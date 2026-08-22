# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""消息段真类 + OneBot 双向转换。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from .exceptions import StellaCompatNotSupported

logger = logging.getLogger("astrbot_compat.components")


class BaseMessageComponent:
    type: str = "base"

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.toJson()})"

    def to_onebot_segment(self) -> MessageSegment:
        raise NotImplementedError


class Plain(BaseMessageComponent):
    type = "plain"

    def __init__(self, text: str, convert: bool = False) -> None:  # noqa: ARG002
        self.text = text
        self.convert = convert

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type, "text": self.text}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.text(self.text)


class At(BaseMessageComponent):
    type = "at"

    def __init__(self, qq: str | int, name: str = "") -> None:
        self.qq = str(qq)
        self.name = name

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type, "qq": self.qq, "name": self.name}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.at(self.qq)


class AtAll(BaseMessageComponent):
    type = "at_all"

    def __init__(self) -> None:
        pass

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.at("all")


class Image(BaseMessageComponent):
    type = "image"

    def __init__(self, file: str = "") -> None:
        self.file = file

    @staticmethod
    def fromURL(url: str) -> Image:  # noqa: N802
        return Image(file=url)

    @staticmethod
    def fromFileSystem(path: str) -> Image:  # noqa: N802
        # 本地路径转 file://
        try:
            p = Path(path)
            if not p.is_absolute():
                # 相对路径按项目根解析不安全，直接 resolve
                pass
            uri = p.resolve().as_uri()
            return Image(file=uri)
        except Exception:
            return Image(file=path)

    @staticmethod
    def fromBase64(b64: str) -> Image:  # noqa: N802
        # 统一前缀 base64://
        if b64.startswith("base64://"):
            return Image(file=b64)
        return Image(file=f"base64://{b64}")

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type, "file": self.file}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.image(self.file)


class Record(BaseMessageComponent):
    type = "record"

    def __init__(self, file: str = "") -> None:
        self.file = file

    @staticmethod
    def fromFileSystem(path: str) -> Record:  # noqa: N802
        try:
            uri = Path(path).resolve().as_uri()
            return Record(file=uri)
        except Exception:
            return Record(file=path)

    @staticmethod
    def fromURL(url: str) -> Record:  # noqa: N802
        return Record(file=url)

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type, "file": self.file}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.record(self.file)


class Reply(BaseMessageComponent):
    type = "reply"

    def __init__(self, id: str | int) -> None:  # noqa: A002
        self.id = str(id)

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type, "id": self.id}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.reply(int(self.id) if self.id.isdigit() else self.id)  # type: ignore[arg-type]


class Face(BaseMessageComponent):
    type = "face"

    def __init__(self, id: int) -> None:  # noqa: A002
        self.id = int(id)

    def toJson(self) -> dict:  # noqa: N802
        return {"type": self.type, "id": self.id}

    def to_onebot_segment(self) -> MessageSegment:
        return MessageSegment.face(self.id)


class Node(BaseMessageComponent):
    type = "node"

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        self.args = args
        self.kwargs = kwargs

    def to_onebot_segment(self) -> MessageSegment:
        raise StellaCompatNotSupported("Node 合并转发暂不支持")


class Nodes(BaseMessageComponent):
    type = "nodes"

    def __init__(self, nodes: list | None = None) -> None:
        self.nodes = nodes or []

    def to_onebot_segment(self) -> MessageSegment:
        raise StellaCompatNotSupported("Nodes 合并转发暂不支持")


def from_onebot_message(msg: Message) -> list[BaseMessageComponent]:
    """OneBot Message -> list[BaseMessageComponent]，未知 type 降级为 Plain。"""
    result: list[BaseMessageComponent] = []
    for seg in msg:
        t = seg.type
        data = seg.data or {}
        try:
            if t == "text":
                result.append(Plain(data.get("text", "")))
            elif t == "at":
                qq = data.get("qq", "")
                if str(qq) == "all":
                    result.append(AtAll())
                else:
                    result.append(At(qq, data.get("name", "")))
            elif t == "image":
                file = data.get("url") or data.get("file") or ""
                result.append(Image.fromURL(file))
            elif t == "record":
                file = data.get("file") or data.get("url") or ""
                result.append(Record(file=file))
            elif t == "reply":
                result.append(Reply(data.get("id", "")))
            elif t == "face":
                result.append(Face(data.get("id", 0)))
            else:
                # 未知 seg 降级
                result.append(Plain(f"[{t}]"))
        except Exception as e:
            logger.warning(f"[components] seg 转换失败 {t}: {e}")
            result.append(Plain(f"[{t}]"))
    return result


def to_onebot_message(chain: list) -> Message:
    """list[BaseMessageComponent|str] -> OneBot Message，部分降级跳过。"""
    segs: list[MessageSegment] = []
    for item in chain:
        try:
            if isinstance(item, str):
                segs.append(MessageSegment.text(item))
            elif isinstance(item, BaseMessageComponent):
                segs.append(item.to_onebot_segment())
            elif isinstance(item, MessageSegment):
                segs.append(item)
            else:
                # 尝试当字符串
                segs.append(MessageSegment.text(str(item)))
        except StellaCompatNotSupported as e:
            logger.warning(f"[components] 跳过不支持的段 {item}: {e}")
            continue
        except Exception as e:
            logger.warning(f"[components] 段转换失败 {item}: {e}")
            continue
    return Message(segs)
