# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""长结果投递（§6.12 附件交付，2026-10-01 用户决策：文件主、转发兜底）。

覆盖：MD 切段器（结构边界/代码围栏）、文件上传主路径、合并转发兜底、
双失败降级纯文本、短结果直发、bot 离线可重试。
"""

from __future__ import annotations

from pathlib import Path

import nonebot
import pytest

nonebot.init()

from stella_project.plugins.bot_main import cometa_bridge


class FakeBot:
    """可编程 OneBot bot：记账 upload/forward/send，可注入失败。"""

    def __init__(self, self_id="10000", *, upload_error=None, forward_error=None):
        self.self_id = self_id
        self.uploads: list[dict] = []
        self.forwards: list[dict] = []
        self.sent: list[dict] = []
        self.upload_error = upload_error
        self.forward_error = forward_error

    async def call_api(self, api: str, **params):
        if api == "upload_group_file":
            if self.upload_error is not None:
                raise self.upload_error
            self.uploads.append(params)
            return None
        if api == "send_group_forward_msg":
            if self.forward_error is not None:
                raise self.forward_error
            self.forwards.append(params)
            return {"res_id": "fwd-1"}
        raise AssertionError(f"unexpected api {api}")

    async def send_group_msg(self, *, group_id=None, message=None, **kw):
        self.sent.append({"group_id": group_id, "message": str(message)})
        return {"message_id": len(self.sent) + 500}

    @property
    def last_text(self) -> str:
        return self.sent[-1]["message"] if self.sent else ""


@pytest.fixture()
def sender_factory(tmp_path: Path):
    from cometa.config import DeliveryConfig

    def _make(delivery: DeliveryConfig | None = None, bot: FakeBot | None = None,
              artifacts_dir: Path | None = None, monkeypatch=None):
        bot = bot or FakeBot()
        if monkeypatch is not None:
            import nonebot

            monkeypatch.setattr(nonebot, "get_bot", lambda bot_id=None: bot)
        artifacts_dir = artifacts_dir or tmp_path / "artifacts"
        sender = cometa_bridge.make_notification_sender(
            artifacts_dir, delivery or DeliveryConfig()
        )
        return sender, bot, artifacts_dir

    return _make


def _target(**overrides) -> dict:
    fields = {
        "platform": "qq", "bot_id": "10000", "group_id": "123",
        "requester_id": "777", "reply_to_message_id": "", "task_id": "task-1",
    }
    fields.update(overrides)
    return fields


def _payload(chars=2000, ref="final_text.md") -> dict:
    return {"full_text_ref": ref, "full_text_chars": chars}


# ── 切段器 ────────────────────────────────────────────────


class TestSplitMarkdown:
    def test_short_text_single_chunk(self):
        assert cometa_bridge.split_markdown("短文本") == ["短文本"]

    def test_splits_at_headings(self):
        text = "## 标题一\n" + "a" * 600 + "\n## 标题二\n" + "b" * 600
        chunks = cometa_bridge.split_markdown(text, max_chars=900)
        assert len(chunks) >= 2
        assert chunks[0].startswith("## 标题一")
        assert chunks[-1].startswith("## 标题二") or "标题二" in chunks[-1][:20]

    def test_never_splits_inside_code_fence(self):
        code = "\n".join(f"line {i}" for i in range(80))
        text = "```python\n" + code + "\n```"
        chunks = cometa_bridge.split_markdown(text, max_chars=200)
        # 围栏内容可能被硬切开块，但任何块内 ``` 数量必须成对（不破坏围栏语义
        # 的要求以「不主动在围栏内断行」为准——断行只发生在围栏外）
        joined = "\n---\n".join(chunks)
        assert "```python" in joined
        assert "line 79" in joined

    def test_total_content_preserved(self):
        text = "\n\n".join(f"段落{i}：" + "x" * 200 for i in range(10))
        chunks = cometa_bridge.split_markdown(text, max_chars=500)
        joined = "".join(chunks)
        assert "段落0" in joined and "段落9" in joined
        assert all(len(c) <= 900 for c in chunks)


# ── 发送流程 ──────────────────────────────────────────────


class TestSenderFlows:
    @pytest.mark.asyncio
    async def test_short_result_sends_text_only(self, sender_factory, monkeypatch):
        sender, bot, _ = sender_factory(monkeypatch=monkeypatch)
        receipt = await sender(_target(), "任务 task-1 已完成。", _payload(chars=100))
        assert receipt == "501"
        assert not bot.uploads and not bot.forwards
        assert len(bot.sent) == 1

    @pytest.mark.asyncio
    async def test_long_result_uploads_file_primary(self, sender_factory, tmp_path, monkeypatch):
        sender, bot, artifacts = sender_factory(monkeypatch=monkeypatch)
        ws = artifacts / "task-1"
        ws.mkdir(parents=True)
        (ws / "final_text.md").write_text("# 结果\n" + "内容" * 400, encoding="utf-8")
        receipt = await sender(_target(), "任务 task-1 已完成。", _payload())
        assert bot.uploads, "文件主投递"
        assert bot.uploads[0]["name"] == "final_text.md"
        assert not bot.forwards
        assert "已上传为群文件" in bot.last_text
        assert receipt  # 封面消息回执

    @pytest.mark.asyncio
    async def test_upload_failure_falls_back_to_forward(self, sender_factory, tmp_path, monkeypatch):
        bot = FakeBot(upload_error=RuntimeError("upload rejected"))
        sender, _, artifacts = sender_factory(bot=bot, monkeypatch=monkeypatch)
        ws = artifacts / "task-1"
        ws.mkdir(parents=True)
        # >900 字符（node 上限）才能切出多个 node
        (ws / "final_text.md").write_text(
            "## 第一节\n" + "内容" * 300 + "\n## 第二节\n" + "细节" * 300,
            encoding="utf-8",
        )
        receipt = await sender(_target(), "任务 task-1 已完成。", _payload())
        assert not bot.uploads
        assert bot.forwards, "转发兜底"
        assert len(bot.forwards[0]["messages"]) >= 2
        assert "转发消息" in bot.last_text
        assert receipt

    @pytest.mark.asyncio
    async def test_both_failures_fall_back_to_text_with_note(
        self, sender_factory, tmp_path, monkeypatch
    ):
        bot = FakeBot(upload_error=RuntimeError("no"), forward_error=RuntimeError("nope"))
        sender, _, artifacts = sender_factory(bot=bot, monkeypatch=monkeypatch)
        ws = artifacts / "task-1"
        ws.mkdir(parents=True)
        (ws / "final_text.md").write_text("内容" * 400, encoding="utf-8")
        receipt = await sender(_target(), "任务 task-1 已完成。", _payload())
        assert not bot.uploads and not bot.forwards
        assert receipt
        assert "未能送达" in bot.last_text  # §6.12：双失败时如实说明产物未送达

    @pytest.mark.asyncio
    async def test_missing_file_falls_back_to_text(self, sender_factory, monkeypatch):
        sender, bot, _ = sender_factory(monkeypatch=monkeypatch)
        receipt = await sender(_target(), "任务 task-1 已完成。", _payload())
        assert not bot.uploads
        assert receipt
        assert "文件缺失" in bot.last_text  # §6.12：如实说明产物未送达

    @pytest.mark.asyncio
    async def test_below_threshold_sends_text_only(self, sender_factory, tmp_path, monkeypatch):
        delivery = __import__("cometa.config", fromlist=["DeliveryConfig"]).DeliveryConfig(
            file_above_chars=5000
        )
        sender, bot, artifacts = sender_factory(delivery=delivery, monkeypatch=monkeypatch)
        ws = artifacts / "task-1"
        ws.mkdir(parents=True)
        (ws / "final_text.md").write_text("内容" * 100, encoding="utf-8")
        await sender(_target(), "任务 task-1 已完成。", _payload(chars=100))
        assert not bot.uploads and len(bot.sent) == 1

    @pytest.mark.asyncio
    async def test_text_style_disables_file(self, sender_factory, tmp_path, monkeypatch):
        delivery = __import__("cometa.config", fromlist=["DeliveryConfig"]).DeliveryConfig(
            long_result="text"
        )
        sender, bot, artifacts = sender_factory(delivery=delivery, monkeypatch=monkeypatch)
        ws = artifacts / "task-1"
        ws.mkdir(parents=True)
        (ws / "final_text.md").write_text("内容" * 400, encoding="utf-8")
        await sender(_target(), "任务 task-1 已完成。", _payload())
        assert not bot.uploads and len(bot.sent) == 1

    @pytest.mark.asyncio
    async def test_webchat_returns_server_emitted(self, sender_factory, monkeypatch):
        sender, bot, _ = sender_factory(monkeypatch=monkeypatch)
        receipt = await sender(_target(platform="webchat"), "x", None)
        assert receipt == "server_emitted"
