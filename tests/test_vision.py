# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""core/vision.py 的测试。

守的是「显式配置才启用」这条契约：

- ``vision_available()`` 是全部新行为的唯一开关：VISION 角色未绑定（出厂默认）
  时必须返回 False，整条链路与旧版逐字节一致；
- ``describe_images`` 在功能不可用 / 预算拦下 / 输入为空时返回 ``[]``，
  单张图失败不拖累其余图，绝不抛异常；
- ``extract_image_sources`` 只认 image 段（mface / face 不算），引用消息
  由 ``VISION_INCLUDE_QUOTED`` 控制。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

import core.vision as vision

# ── 最小 OneBot 消息段 / 事件替身 ──────────────────────────


@dataclass
class _Seg:
    type: str
    data: dict = field(default_factory=dict)


class _Message(list):
    pass


@dataclass
class _Reply:
    message: _Message


@dataclass
class _Event:
    message: _Message
    reply: _Reply | None = None

    def get_message(self):
        return self.message


def _event_with(*segs, quoted=None) -> _Event:
    reply = _Reply(message=_Message(quoted)) if quoted else None
    return _Event(message=_Message(segs), reply=reply)


# ── 环境替身 ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _vision_env(monkeypatch):
    """把 vision 钉在「功能启用」态；用例再用 _off/_budget 覆盖。

    模块常量（VISION_ENABLED 等）在 import 期绑定，所以 patch 的是
    core.vision 自己的名字——与 settings 侧的值无关。
    """
    monkeypatch.setattr(vision, "VISION_ENABLED", True, raising=False)
    monkeypatch.setattr(vision, "VISION_MAX_IMAGES", 3, raising=False)
    monkeypatch.setattr(vision, "VISION_INCLUDE_QUOTED", True, raising=False)
    monkeypatch.setattr(vision, "VISION_DESCRIBE_TIMEOUT", 5.0, raising=False)
    monkeypatch.setattr(vision, "VISION_MAX_IMAGE_BYTES", 8 * 1024 * 1024, raising=False)
    # 默认判定：角色已绑定（单测不去真解析 registry）
    monkeypatch.setattr(vision, "backend_for", lambda role: object(), raising=False)
    monkeypatch.setattr(vision, "budget_blocked", lambda role: None, raising=False)
    monkeypatch.setattr(
        vision,
        "endpoint_of",
        lambda role: type("E", (), {"kind": "online", "base_url": "https://x"})(),
        raising=False,
    )
    vision._caption_cache.clear()
    yield
    vision._caption_cache.clear()


def _bind_vision_args(monkeypatch):
    """让 _vision_call_args 返回一个可辨识的调用参数包。"""
    monkeypatch.setattr(
        vision,
        "_vision_call_args",
        lambda: {"base_url": "https://x", "model": "vlm", "timeout": 10},
        raising=False,
    )


# ============================================================
# vision_available / extract_image_sources
# ============================================================


def test_vision_available_requires_enabled_and_backend(monkeypatch):
    assert vision.vision_available() is True
    monkeypatch.setattr(vision, "backend_for", lambda role: None, raising=False)
    assert vision.vision_available() is False


def test_vision_available_respects_kill_switch(monkeypatch):
    monkeypatch.setattr(vision, "VISION_ENABLED", False, raising=False)
    assert vision.vision_available() is False


def test_extract_picks_image_segments_only():
    ev = _event_with(
        _Seg("at", {"qq": "42"}),
        _Seg("text", {"text": "看看"}),
        _Seg("image", {"url": "https://cdn.qq/img1.jpg", "file": "abc.jpg"}),
        _Seg("face", {"id": 14}),  # QQ 表情不算图片
    )
    assert vision.extract_image_sources(ev) == ["https://cdn.qq/img1.jpg"]


def test_extract_falls_back_to_file_and_path():
    ev = _event_with(
        _Seg("image", {"file": "file:///tmp/a.png"}),
        _Seg("image", {"path": "C:\\cache\\b.jpg"}),
    )
    assert vision.extract_image_sources(ev) == ["/tmp/a.png", "C:\\cache\\b.jpg"]


def test_extract_includes_quoted_message_images():
    ev = _event_with(
        _Seg("text", {"text": "这个呢"}),
        quoted=[_Seg("image", {"url": "https://cdn.qq/quoted.png"})],
    )
    assert vision.extract_image_sources(ev) == ["https://cdn.qq/quoted.png"]


def test_extract_quoted_can_be_disabled(monkeypatch):
    monkeypatch.setattr(vision, "VISION_INCLUDE_QUOTED", False, raising=False)
    ev = _event_with(quoted=[_Seg("image", {"url": "https://cdn.qq/quoted.png"})])
    assert vision.extract_image_sources(ev) == []


def test_extract_dedupes_and_caps(monkeypatch):
    monkeypatch.setattr(vision, "VISION_MAX_IMAGES", 2, raising=False)
    ev = _event_with(
        _Seg("image", {"url": "u1"}),
        _Seg("image", {"url": "u1"}),  # 重复来源只取一次
        _Seg("image", {"url": "u2"}),
        _Seg("image", {"url": "u3"}),
    )
    assert vision.extract_image_sources(ev) == ["u1", "u2"]


# ============================================================
# describe_images
# ============================================================


def test_describe_returns_empty_when_unavailable(monkeypatch):
    monkeypatch.setattr(vision, "backend_for", lambda role: None, raising=False)
    assert asyncio.run(vision.describe_images(["https://x/a.jpg"])) == []


def test_describe_returns_empty_when_budget_blocked(monkeypatch):
    monkeypatch.setattr(
        vision, "budget_blocked", lambda role: "超预算", raising=False
    )
    assert asyncio.run(vision.describe_images(["https://x/a.jpg"])) == []


def test_describe_uses_image_block_and_caches(monkeypatch):
    _bind_vision_args(monkeypatch)
    calls: list[dict] = []

    async def fake_chat(messages, **kw):
        calls.append(messages[0]["content"])
        return {"choices": [{"message": {"content": "一只橘猫趴在键盘上"}}]}

    import core.llm.openai_client as oc

    monkeypatch.setattr(oc, "chat_completion", fake_chat)
    # acquire 的闸门解析打不到真 scheduler——换成直通上下文管理器
    import contextlib

    monkeypatch.setattr(
        vision, "acquire", lambda *a, **k: contextlib.asynccontextmanager(
            lambda: _async_noop()
        )(),
        raising=False,
    )
    caps = asyncio.run(vision.describe_images(["https://cdn.qq/cat.jpg"]))
    assert caps == ["一只橘猫趴在键盘上"]
    # 发出的必须是多模态 block：text + image_url
    blocks = calls[0]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"] == "https://cdn.qq/cat.jpg"  # 在线端点直传 URL
    # 缓存命中：第二张同源图不再调模型
    asyncio.run(vision.describe_images(["https://cdn.qq/cat.jpg"]))
    assert len(calls) == 1


async def _async_noop():
    yield


def test_describe_partial_failure_keeps_others(monkeypatch):
    _bind_vision_args(monkeypatch)

    async def fake_chat(messages, **kw):
        url = messages[0]["content"][1]["image_url"]["url"]
        if "bad" in url:
            raise RuntimeError("boom")
        return {"choices": [{"message": {"content": f"desc:{url}"}}]}

    import contextlib

    import core.llm.openai_client as oc

    monkeypatch.setattr(oc, "chat_completion", fake_chat)
    monkeypatch.setattr(
        vision, "acquire", lambda *a, **k: contextlib.asynccontextmanager(
            lambda: _async_noop()
        )(),
        raising=False,
    )
    caps = asyncio.run(
        vision.describe_images(["https://x/good.jpg", "https://x/bad.jpg"])
    )
    assert caps == ["desc:https://x/good.jpg"]


def test_local_endpoint_downloads_instead_of_url(monkeypatch):
    """本地端点拿不到 QQ CDN 图——必须下载成 data URL。"""
    _bind_vision_args(monkeypatch)
    monkeypatch.setattr(
        vision,
        "endpoint_of",
        lambda role: type("E", (), {"kind": "local", "base_url": "http://l"})(),
        raising=False,
    )
    monkeypatch.setattr(
        vision, "_download_image", lambda url: _dl_stub(url), raising=False
    )
    seen: list[str] = []

    async def fake_chat(messages, **kw):
        seen.append(messages[0]["content"][1]["image_url"]["url"])
        return {"choices": [{"message": {"content": "图"}}]}

    import contextlib

    import core.llm.openai_client as oc

    monkeypatch.setattr(oc, "chat_completion", fake_chat)
    monkeypatch.setattr(
        vision, "acquire", lambda *a, **k: contextlib.asynccontextmanager(
            lambda: _async_noop()
        )(),
        raising=False,
    )
    caps = asyncio.run(vision.describe_images(["https://cdn.qq/x.jpg"]))
    assert caps == ["图"]
    assert seen == ["data:image/jpeg;base64,ZmFrZQ=="]


async def _dl_stub(url):
    return "data:image/jpeg;base64,ZmFrZQ=="


def test_describe_timeout_yields_placeholder_not_exception(monkeypatch):
    _bind_vision_args(monkeypatch)

    async def slow_chat(messages, **kw):
        await asyncio.sleep(30)
        return {"choices": [{"message": {"content": "never"}}]}

    import contextlib

    import core.llm.openai_client as oc

    monkeypatch.setattr(oc, "chat_completion", slow_chat)
    monkeypatch.setattr(vision, "VISION_DESCRIBE_TIMEOUT", 0.05, raising=False)
    monkeypatch.setattr(
        vision, "acquire", lambda *a, **k: contextlib.asynccontextmanager(
            lambda: _async_noop()
        )(),
        raising=False,
    )
    # 超时被吞掉、返回 []，而不是抛 TimeoutError 击穿回复链路
    assert asyncio.run(vision.describe_images(["https://x/slow.jpg"])) == []


# ============================================================
# update_recorded_message（占位 → 带描述回写）
# ============================================================


def test_update_recorded_message_rewrites_by_msg_id(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " group_id TEXT, user_id TEXT, content TEXT, source_kind TEXT, msg_id INTEGER)"
    )
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind, msg_id)"
        " VALUES ('1', '9', '[图片]', 'AT_MENTION', 777)"
    )
    conn.commit()
    conn.close()

    import config

    monkeypatch.setattr(config, "DB_PATH", db, raising=False)
    # core.vision 在函数内惰性 import config.DB_PATH——patch config 包属性即可
    ok = asyncio.run(
        vision.update_recorded_message(1, 777, "[图片]「图片内容：一只猫」")
    )
    assert ok is True
    row = sqlite3.connect(db).execute(
        "SELECT content FROM group_messages WHERE msg_id = 777"
    ).fetchone()
    assert row[0] == "[图片]「图片内容：一只猫」"


def test_update_recorded_message_missing_row_is_noop(tmp_path, monkeypatch):
    import sqlite3

    db = tmp_path / "m.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " group_id TEXT, content TEXT, msg_id INTEGER)"
    )
    conn.commit()
    conn.close()

    import config

    monkeypatch.setattr(config, "DB_PATH", db, raising=False)
    assert asyncio.run(vision.update_recorded_message(1, 999, "x")) is False
    assert asyncio.run(vision.update_recorded_message(1, 0, "x")) is False
