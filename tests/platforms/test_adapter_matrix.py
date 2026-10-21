# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Frozen platform denominator and representative real-adapter fixture."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = Path(__file__).with_name("adapter_matrix.json")
INVENTORY_PATH = ROOT / "docs/plans/2026-10-20-cross-platform-inventory.md"


def _matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _inventory_rows() -> list[tuple[str, str, str, str]]:
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    section = inventory.split("## B. 适配器验收分母", 1)[1].split("## C.", 1)[0]
    rows: list[tuple[str, str, str, str]] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0] == "平台/协议" or set(cells[0]) <= {"-"}:
            continue
        module = re.search(r"`([^`]*)`", cells[1])
        package = re.search(r"`([^`]*)`", cells[2])
        assert module is not None and package is not None
        rows.append((cells[0], module.group(1), package.group(1), cells[3]))
    return rows


def test_adapter_matrix_matches_the_frozen_official_denominator():
    matrix = _matrix()
    inventory = INVENTORY_PATH.read_text(encoding="utf-8")
    snapshot = re.search(r"SHA-256 `([0-9a-f]{64})`", inventory)

    assert snapshot is not None
    assert matrix["source"]["sha256"] == snapshot.group(1)
    assert matrix["source"]["url"] in inventory

    rows = matrix["adapters"]
    assert len(rows) == matrix["denominator"] == 32
    observed = [
        (row["platform"], row["module_name"], row["package_name"], row["priority"])
        for row in rows
    ]
    assert observed == _inventory_rows()
    assert len({row["module_name"] for row in rows}) == 32

    for row in rows:
        assert row["final_status"] in {"not_certified", "certified"}
        assert set(row["levels"]) == {"L0", "L1", "L2", "L3"}
        assert row["status_evidence"]
        for level in row["levels"].values():
            assert level["local"] in {"pass", "not_run", "blocked"}
            assert level["fixture"] in {"pass", "partial", "not_run", "blocked"}
            assert level["live"] in {"pass", "not_run", "blocked"}

        if row["final_status"] == "certified":
            assert row["levels"]["L0"]["local"] == "pass"
            assert all(
                row["levels"][level][kind] == "pass"
                for level in ("L1", "L2", "L3")
                for kind in ("fixture", "live")
            )


@pytest.mark.asyncio
async def test_onebot_v11_real_group_event_routes_reply_to_same_bot_and_group(monkeypatch):
    import warnings

    with warnings.catch_warnings():
        # The fixture intentionally uses the adapter model without starting a Bot.
        warnings.filterwarnings(
            "ignore", message="Failed to get nonebot adapters:.*", category=RuntimeWarning
        )
        warnings.filterwarnings(
            "ignore", message="No adapters found,.*", category=RuntimeWarning
        )
        from nonebot.adapters.onebot.v11 import Message, MessageSegment
        from nonebot.adapters.onebot.v11.event import GroupMessageEvent, Sender
        from nonebot_plugin_alconna.uniseg import UniMessage

    from core.transport.adapters.onebot_v11 import (
        OneBotV11Exporter,
        OneBotV11TargetCodec,
    )
    from core.transport.capabilities import AdapterCapabilities
    from core.transport.normalizers import NormalizedEvent, OneBot11Normalizer
    from core.transport.outbound import DeliveryTarget, OutboundMessage

    inbound = Message([MessageSegment.text("hello")])
    event = GroupMessageEvent(
        time=1,
        self_id=9001,
        post_type="message",
        sub_type="normal",
        user_id=777,
        message_type="group",
        message_id=202,
        message=inbound,
        original_message=inbound,
        raw_message="hello",
        font=0,
        sender=Sender(user_id=777, nickname="Ada"),
        group_id=123,
    )
    bot = SimpleNamespace(
        self_id="9001",
        adapter=SimpleNamespace(get_name=lambda: "OneBot V11"),
    )

    normalized = OneBot11Normalizer().normalize(
        bot, event, connection_id="wp11-onebot-fixture"
    )
    assert isinstance(normalized, NormalizedEvent)
    assert normalized.user_ref.raw_user_id == "777"
    assert normalized.scene_ref.kind == "group"
    assert normalized.scene_ref.scene_id == "123"
    assert normalized.platform_message_id == "202"
    assert normalized.text == "hello"

    target = DeliveryTarget(normalized.bot_ref, normalized.scene_ref)
    encoded_target = OneBotV11TargetCodec().encode(target, bot_handle=bot)
    sent: dict[str, object] = {}

    async def fake_send(message, *, target=None, bot=None, **kwargs):
        sent["segments"] = list(message)
        sent["target"] = target
        sent["bot"] = bot
        return SimpleNamespace(msg_ids=["reply:203"])

    monkeypatch.setattr(UniMessage, "send", fake_send)
    result = await OneBotV11Exporter().send(
        target,
        OutboundMessage.text("hello back"),
        bot_handle=bot,
        capabilities=AdapterCapabilities("onebot-v11", "qq", group=True),
        encoded_target=encoded_target,
    )

    assert result.status.value == "accepted"
    assert result.message_ids == ("reply:203",)
    assert sent["target"] is encoded_target
    assert sent["bot"] is bot
    assert [segment.text for segment in sent["segments"]] == ["hello back"]
    assert encoded_target.id == "123"
    assert encoded_target.self_id == "9001"
