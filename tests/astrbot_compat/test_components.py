# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""消息段：与上游 astrbot.core.message.components 的语义对齐。"""

from __future__ import annotations

import asyncio

from astrbot_compat.components import (
    At,
    AtAll,
    ComponentType,
    Face,
    File,
    Image,
    Node,
    Nodes,
    Plain,
    Poke,
    Record,
    Reply,
    Video,
    from_onebot_dicts,
    split_forward_nodes,
    to_onebot_message,
)


def test_type_values_are_upstream_capitalized():
    # 上游 ComponentType 是 str Enum，插件里 `seg.type == "Image"` 是常见写法
    assert Plain("x").type == "Plain"
    assert At(qq=1).type == "At"
    assert Image(file="x").type == "Image"
    assert Record(file="x").type == "Record"
    assert ComponentType.Video == "Video"


def test_atall_is_an_at():
    # 上游 AtAll 继承 At，插件靠 isinstance(seg, At) 检测提及
    assert isinstance(AtAll(), At)
    assert AtAll().qq == "all"


def test_todict_lowers_type_without_enum_prefix():
    assert Plain("hi").toDict() == {"type": "text", "data": {"text": "hi"}}
    assert At(qq=5).toDict() == {"type": "at", "data": {"qq": "5"}}
    assert Face(id=3).toDict() == {"type": "face", "data": {"id": "3"}}
    assert Video.fromURL("https://a/b.mp4").toDict()["type"] == "video"


def test_components_accept_unknown_kwargs():
    # 上游是 pydantic 模型，插件传入未声明字段不该炸
    img = Image(file="x", summary="内含图片", extra=1)
    assert img.file == "x"
    assert img.summary == "内含图片"


def test_reply_carries_quoted_message_info():
    r = Reply(id=7, sender_id=42, sender_nickname="张三", message_str="原文")
    assert (r.id, r.sender_id, r.sender_nickname, r.message_str) == ("7", 42, "张三", "原文")
    assert r.toDict() == {"type": "reply", "data": {"id": "7"}}


def test_image_factories():
    assert Image.fromBytes(b"ab").file == "base64://YWI="
    assert Image.fromBase64("YWI=").file == "base64://YWI="
    assert Image.fromURL("https://x/y.png").file == "https://x/y.png"
    assert Image.fromFileSystem("a.png").file.startswith("file://")


def test_from_onebot_dicts_roundtrip():
    chain = from_onebot_dicts(
        [
            {"type": "text", "data": {"text": "hi"}},
            {"type": "at", "data": {"qq": "9"}},
            {"type": "at", "data": {"qq": "all"}},
            {"type": "image", "data": {"url": "https://x/y.png"}},
            {"type": "face", "data": {"id": "1"}},
            {"type": "somethingnew", "data": {}},
        ],
    )
    assert [type(c).__name__ for c in chain] == [
        "Plain",
        "At",
        "AtAll",
        "Image",
        "Face",
        "Unknown",
    ]


def test_reply_segment_parses_nested_sender():
    chain = from_onebot_dicts(
        [
            {
                "type": "reply",
                "data": {
                    "id": "12",
                    "user_id": "9",
                    "message": [{"type": "text", "data": {"text": "原话"}}],
                },
            },
        ],
    )
    reply = chain[0]
    assert isinstance(reply, Reply)
    assert reply.sender_id == "9"
    assert reply.message_str == "原话"


def test_to_onebot_message_skips_forward_nodes():
    msg = to_onebot_message([Plain("a"), Node("b")])
    assert "a" in str(msg)
    assert "node" not in str(msg)


def test_split_forward_nodes():
    forwards, rest = split_forward_nodes([Plain("a"), Node("b"), Nodes([Node("c")])])
    assert len(forwards) == 2
    assert [type(c).__name__ for c in rest] == ["Plain"]


def test_nodes_to_dict_shape():
    node = Node([Plain("hello"), Image.fromBase64("YWI=")], name="bot", uin="10001")
    payload = asyncio.run(Nodes([node]).to_dict())
    assert payload["messages"][0]["data"]["user_id"] == "10001"
    content = payload["messages"][0]["data"]["content"]
    assert content[0] == {"type": "text", "data": {"text": "hello"}}
    assert content[1]["data"]["file"] == "base64://YWI="


def test_poke_and_file_payloads():
    assert Poke(126, id=7).toDict() == {"type": "poke", "data": {"type": "126", "id": "7"}}
    f = File(name="a.txt", file="/tmp/a.txt")
    assert f.toDict() == {"type": "file", "data": {"name": "a.txt", "file": "/tmp/a.txt"}}
