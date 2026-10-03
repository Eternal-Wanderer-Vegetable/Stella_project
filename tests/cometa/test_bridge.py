# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""QQ 桥接基线（方案 §8.1 test_delivery 的 ack 竞争半边 + §6.5/§6.11）。

- build_origin 只从真实事件字段构造；
- deliver_ack 与泵的 CAS 竞争：入口赢 → 发送并记 sent；泵赢 → 入口放弃；
  发送异常 → delivery_unknown 不重发；
- notification_sender：WebChat 占位回执（不声称已阅读）、bot 离线可退避。
"""

from __future__ import annotations

from types import SimpleNamespace

import nonebot
import pytest

# cometa_bridge 顶层 import nonebot.logger：测试环境不需要真实驱动，
# init() 只是让 nonebot 的全局对象可用（与 tests/scheduling 同款）。
nonebot.init()

from cometa.models import NotificationState
from cometa.service import Actor, CometaService
from stella_project.plugins.bot_main import cometa_bridge
from tests.cometa_helpers import make_origin, make_spec


@pytest.fixture()
def service(cometa_store, cometa_config):
    cometa_config.enabled = True
    cometa_config.access.qq_user_ids = {777}
    cometa_config.access.qq_group_ids = {12345}
    svc = CometaService(cometa_store, cometa_config, instance_id="inst-test")
    from cometa import runtime as cometa_runtime

    cometa_runtime.set_current(
        SimpleNamespace(config=cometa_config, store=cometa_store, service=svc, enabled=True)
    )
    yield svc
    cometa_runtime.set_current(None)


def _submit(service) -> dict:
    receipt = service.submit(
        make_spec(),
        actor=Actor(kind="qq_user", id="777"),
        origin=make_origin(),
        idempotency_key="k-bridge",
    )
    return {
        "task_id": receipt.task_id,
        "ack_notification_id": receipt.ack_notification_id,
        "ack_text": "已受理外部任务。",
    }


class TestBuildOrigin:
    @staticmethod
    def _group_event(self_id="10000", group_id=12345, user_id=777, message_id=42):
        # v2 build_origin 按 isinstance 分流群/私聊（计划 §6.8），用真实事件类型
        from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

        return GroupMessageEvent(
            time=0, self_id=self_id, post_type="message", sub_type="normal",
            user_id=user_id, message_type="group", message_id=message_id,
            group_id=group_id, message=Message("你好"), original_message=Message("你好"),
            raw_message="你好", font=0, sender={"nickname": "u", "role": "member"},
        )

    def test_from_event_fields(self):
        event = self._group_event()
        bot = SimpleNamespace(self_id="10000")
        origin = cometa_bridge.build_origin(event, bot, instance_id="inst-test")
        assert origin["platform"] == "qq"
        assert origin["requester_id"] == "777"
        assert origin["conversation_id"] == "12345"
        assert origin["source_request_id"] == "msg-42"
        # v2 会话身份完整（计划 §6.8）
        assert origin["conversation_kind"] == "group"
        assert origin["peer_id"] == "12345"
        assert origin["conversation_key"] == "qq:10000:group:12345"

    def test_requires_instance(self):
        event = self._group_event(self_id="1", group_id=1, user_id=1, message_id=1)
        assert cometa_bridge.build_origin(event, None, instance_id="") is None

    def test_private_event_yields_private_origin(self):
        from nonebot.adapters.onebot.v11 import Message, PrivateMessageEvent

        event = PrivateMessageEvent(
            time=0, self_id="10000", post_type="message", sub_type="friend",
            user_id=777, message_type="private", message_id=43,
            message=Message("帮我调研"), original_message=Message("帮我调研"),
            raw_message="帮我调研", font=0, sender={"nickname": "u"},
        )
        bot = SimpleNamespace(self_id="10000")
        origin = cometa_bridge.build_origin(event, bot, instance_id="inst-test")
        assert origin["conversation_kind"] == "private"
        assert origin["peer_id"] == "777"
        assert origin["conversation_key"] == "qq:10000:private:777"
        assert origin["conversation_id"] == "qq:10000:private:777"


class TestDeliverAck:
    @pytest.mark.asyncio
    async def test_entry_wins_and_marks_sent(self, service):
        submission = _submit(service)
        sends: list[str] = []

        async def send(text: str) -> str | None:
            sends.append(text)
            return "msg-99"

        outcome = await cometa_bridge.deliver_ack(submission, send)
        assert outcome == "sent"
        assert sends == ["已受理外部任务。"]
        ack = service.store.notification_of_dedupe(
            submission["task_id"], f"ack:{submission['task_id']}"
        )
        assert ack.state is NotificationState.SENT
        assert ack.receipt == "msg-99"

    @pytest.mark.asyncio
    async def test_pump_owned_skips_entry_send(self, service):
        submission = _submit(service)
        # 泵先认领（claim 后保持 sending）
        ack = service.store.notification_of_dedupe(
            submission["task_id"], f"ack:{submission['task_id']}"
        )
        assert service.store.claim_notification(ack.notification_id) is not None

        sends: list[str] = []

        async def send(text: str) -> str | None:
            sends.append(text)
            return None

        outcome = await cometa_bridge.deliver_ack(submission, send)
        assert outcome == "pump_owned"
        assert sends == []  # 入口放弃发送，双发被 CAS 挡住

    @pytest.mark.asyncio
    async def test_send_error_is_delivery_unknown(self, service):
        submission = _submit(service)

        async def send(text: str) -> str | None:
            raise RuntimeError("platform gone")

        outcome = await cometa_bridge.deliver_ack(submission, send)
        assert outcome == "unknown"
        ack = service.store.notification_of_dedupe(
            submission["task_id"], f"ack:{submission['task_id']}"
        )
        assert ack.state is NotificationState.DELIVERY_UNKNOWN
        # 泵不再重投 unknown 终态
        assert all(
            n.notification_id != ack.notification_id
            for n in service.store.due_notifications()
        )


class TestNotificationSender:
    @pytest.mark.asyncio
    async def test_webchat_is_server_emitted(self):
        receipt = await cometa_bridge.notification_sender(
            {"platform": "webchat"}, "结果在任务中心"
        )
        assert receipt == "server_emitted"

    @pytest.mark.asyncio
    async def test_offline_bot_raises_retryable(self, monkeypatch):
        import nonebot

        from cometa.delivery import SenderUnavailable

        def _no_bot(bot_id=None):
            raise ValueError("no bot connected")

        monkeypatch.setattr(nonebot, "get_bot", _no_bot)
        with pytest.raises(SenderUnavailable):
            await cometa_bridge.notification_sender(
                {"platform": "qq", "group_id": "12345", "bot_id": "10000"}, "hi"
            )

    @pytest.mark.asyncio
    async def test_qq_send_returns_receipt(self, monkeypatch):
        import nonebot

        captured: dict = {}

        class FakeBot:
            self_id = "10000"

            async def send_group_msg(self, *, group_id, message):
                captured["group_id"] = group_id
                captured["message"] = message
                return {"message_id": 555}

        monkeypatch.setattr(nonebot, "get_bot", lambda bot_id=None: FakeBot())
        receipt = await cometa_bridge.notification_sender(
            {
                "platform": "qq",
                "group_id": "12345",
                "bot_id": "10000",
                "requester_id": "777",
                "reply_to_message_id": "42",
            },
            "任务完成",
        )
        assert receipt == "555"
        assert captured["group_id"] == 12345
        text = str(captured["message"])
        assert "任务完成" in text
        # 引用原消息 + @ 请求者是桥接刻意构造的段（§6.11）；Agent 文字本身
        # 以 MessageSegment.text 附加，不会被二次解释成控制码。
        assert text.startswith("[CQ:reply,id=42][CQ:at,qq=777]任务完成")
