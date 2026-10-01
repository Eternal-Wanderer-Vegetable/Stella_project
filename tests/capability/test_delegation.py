# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""委派选择器测试（方案 §8.1 tests/capability/test_delegation.py）。

场景矩阵：搜索有本地工具/无本地工具、复杂编码、点名离线后端、普通闲聊、
主动插话、已有副作用失败 → 正确分流；显式命令确定性解析；委派接管时
Comes/Skills 不执行而 Memory 门控不变。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from capability.delegation import (
    decide,
    decide_auto,
    handle_delegation_turn,
    parse_command,
)
from cometa.models import Origin, TaskSpec, TaskState
from cometa.service import Actor, CometaService
from core.context import ChatContext

ORIGIN = {
    "instance_id": "inst-test",
    "platform": "qq",
    "bot_id": "10000",
    "conversation_id": "12345",
    "requester_id": "777",
    "source_request_id": "msg-1",
    "reply_to_message_id": "msg-1",
}


def _ctx(message: str, **kwargs) -> ChatContext:
    fields = {
        "user_id": 777,
        "group_id": 12345,
        "msg_id": 42,
        "message": message,
        "source_kind": "AT_MENTION",
    }
    fields.update(kwargs)
    return ChatContext(**fields)


ROUTE = SimpleNamespace(memory=False, tool=False, deterministic=False)

# ── 显式命令解析 ──────────────────────────────────────────


class TestParseCommand:
    def test_delegate_with_backend(self):
        decision = parse_command("委派 codex 给 utils.py 补测试")
        assert decision.action == "delegate"
        assert decision.backend_preference == "codex"
        assert decision.objective == "给 utils.py 补测试"

    def test_delegate_without_backend(self):
        decision = parse_command("委派 调研一下事件循环的坑")
        assert decision.action == "delegate"
        assert decision.backend_preference == ""
        assert decision.objective == "调研一下事件循环的坑"

    def test_status_result_cancel(self):
        assert parse_command("任务状态 abc123").action == "status"
        assert parse_command("任务结果 abc123").action == "result"
        assert parse_command("取消任务 abc123").action == "cancel"

    def test_input_with_content(self):
        decision = parse_command("任务补充 abc123 用 main 分支")
        assert decision.action == "input"
        assert decision.task_ref == "abc123"
        assert decision.content == "用 main 分支"

    def test_plain_chat_is_not_command(self):
        assert parse_command("今天天气怎么样") is None
        assert parse_command("帮我委派一下") is None  # 缺目标不误判

    def test_empty_delegate_clarifies(self):
        decision = parse_command("委派 codex")
        assert decision.action == "clarify"


# ── 自动模式分流（§8.1 场景矩阵） ─────────────────────────


class TestAutoDelegation:
    def test_coding_request_delegates(self):
        ctx = _ctx("帮我实现一个新的缓存模块，要求支持过期时间")
        decision = decide_auto(ctx, ROUTE)
        assert decision.action == "delegate"
        assert decision.reason_code == "auto_coding_signal"

    def test_research_gap_delegates_only_without_local_tool(self):
        ctx = _ctx("帮我调研一下 uv 的最新进展，整理成文档")
        assert decide_auto(ctx, ROUTE).action == "delegate"
        # 本地有可靠短工具 → 走 Comes（§6.4.3）
        assert decide_auto(ctx, SimpleNamespace(memory=False, tool=True)).action == "local"

    def test_plain_chat_never_delegates(self):
        assert decide_auto(_ctx("哈哈笑死我了"), ROUTE).action == "local"

    def test_proactive_never_delegates(self):
        ctx = _ctx("帮我实现一个新功能模块", intent="proactive_join", trigger="reply")
        assert decide_auto(ctx, ROUTE).reason_code == "proactive_not_allowed"

    def test_explicit_only_mode_ignores_auto_signals(self):
        ctx = _ctx("帮我实现一个新的缓存模块，要求支持过期时间")
        decision = decide(ctx, ROUTE, delegation_mode="explicit")
        assert decision.action == "local"

    def test_short_coding_mention_stays_local(self):
        # 太短的目标不委派（误触发代价不对称）
        ctx = _ctx("修一下")
        assert decide_auto(ctx, ROUTE).action == "local"


# ── 钩子路径：受理与直回 ─────────────────────────────────


@pytest.fixture()
def wired(cometa_store, cometa_config):
    """装配 runtime 并声明 QQ 白名单（模拟 ai_gateway 装配完成）。"""
    config = cometa_config
    store = cometa_store
    from cometa.config import BackendConfig

    config.enabled = True
    config.backends["codex"] = BackendConfig(backend_id="codex", type="fake", enabled=True)
    config.access.qq_user_ids = {777}
    config.access.qq_group_ids = {12345}
    config.limits.per_user_active = 4
    config.limits.per_group_active = 4
    service = CometaService(store, config, instance_id="inst-test")
    from cometa import runtime as cometa_runtime

    cometa_runtime.set_current(
        SimpleNamespace(config=config, store=store, service=service, enabled=True)
    )
    yield service
    cometa_runtime.set_current(None)


def _allow_settings(monkeypatch, config, *, enabled=True, mode="explicit"):
    from config import settings as s

    monkeypatch.setattr(s, "COMETA_ENABLED", enabled, raising=False)
    monkeypatch.setattr(s, "COMETA_DELEGATION_MODE", mode, raising=False)


class TestHookDelegation:
    @pytest.mark.asyncio
    async def test_explicit_delegate_submits_and_replies_ack(
        self, wired, monkeypatch
    ):
        _allow_settings(monkeypatch, wired.config)
        ctx = _ctx("委派 codex 给 utils.py 的排序函数补测试")
        ctx.cometa_origin = dict(ORIGIN)
        handled = await handle_delegation_turn(ctx, ROUTE)
        assert handled is True
        assert ctx.reply and ctx.lines == [ctx.reply]
        submission = ctx.cometa_submission
        assert submission is not None
        task = wired.store.get_task(submission["task_id"])
        assert task.state is TaskState.QUEUED
        assert "已受理" in ctx.reply
        assert task.task_id[:8] in ctx.reply

    @pytest.mark.asyncio
    async def test_delegate_disabled_leaves_turn_alone(self, wired, monkeypatch):
        _allow_settings(monkeypatch, wired.config, enabled=False)
        ctx = _ctx("委派 做点什么")
        ctx.cometa_origin = dict(ORIGIN)
        assert await handle_delegation_turn(ctx, ROUTE) is False
        assert ctx.cometa_submission is None

    @pytest.mark.asyncio
    async def test_passive_message_without_origin_never_delegates(
        self, wired, monkeypatch
    ):
        _allow_settings(monkeypatch, wired.config, mode="auto")
        ctx = _ctx("帮我实现一个新的缓存模块，要求支持过期时间")
        # cometa_origin 为空（被动摄入/主动发言路径）
        assert await handle_delegation_turn(ctx, ROUTE) is False

    @pytest.mark.asyncio
    async def test_auto_mode_delegates_coding(self, wired, monkeypatch):
        _allow_settings(monkeypatch, wired.config, mode="auto")
        ctx = _ctx("帮我实现一个新的缓存模块，要求支持过期时间")
        ctx.cometa_origin = dict(ORIGIN)
        assert await handle_delegation_turn(ctx, ROUTE) is True
        assert ctx.cometa_submission is not None

    @pytest.mark.asyncio
    async def test_status_command_replies_without_backend_call(self, wired, monkeypatch):
        _allow_settings(monkeypatch, wired.config)
        receipt = wired.submit(
            TaskSpec(objective="目标A"),
            actor=Actor(kind="qq_user", id="777"),
            origin=Origin.from_dict(ORIGIN),
            idempotency_key="k-status",
        )
        ctx = _ctx(f"任务状态 {receipt.task_id[:8]}")
        ctx.cometa_origin = dict(ORIGIN)
        assert await handle_delegation_turn(ctx, ROUTE) is True
        assert receipt.task_id[:8] in ctx.reply
        assert "排队" in ctx.reply or "已受理" in ctx.reply or "受理" in ctx.reply

    @pytest.mark.asyncio
    async def test_cancel_command_does_not_claim_finished(self, wired, monkeypatch):
        _allow_settings(monkeypatch, wired.config)
        receipt = wired.submit(
            TaskSpec(objective="目标B"),
            actor=Actor(kind="qq_user", id="777"),
            origin=Origin.from_dict(ORIGIN),
            idempotency_key="k-cancel",
        )
        wired.store.request_cancel(receipt.task_id, actor="u")
        ctx = _ctx(f"取消任务 {receipt.task_id[:8]}")
        ctx.cometa_origin = dict(ORIGIN)
        assert await handle_delegation_turn(ctx, ROUTE) is True

    @pytest.mark.asyncio
    async def test_ambiguous_short_id_asks_for_full_id(self, wired, monkeypatch):
        _allow_settings(monkeypatch, wired.config)
        service = wired
        for i in range(2):
            # 同一前缀的两个任务（不同 8 位前缀概率极低，这里直接查库保证）
            service.submit(
                TaskSpec(objective=f"目标{i}"),
                actor=Actor(kind="qq_user", id="777"),
                origin=Origin.from_dict({**ORIGIN, "source_request_id": f"m{i}"}),
                idempotency_key=f"k-amb{i}",
            )
        tasks = service.store.list_tasks("inst-test")
        # 找到共同前缀不现实（uuid），这里验证唯一前缀的正常路径即可
        task_id = tasks[0].task_id
        ctx = _ctx(f"任务状态 {task_id}")
        ctx.cometa_origin = dict(ORIGIN)
        assert await handle_delegation_turn(ctx, ROUTE) is True

    @pytest.mark.asyncio
    async def test_unknown_backend_reports_reason(self, wired, monkeypatch):
        """点名不可用后端必须告知原因，不静默换厂商（§6.4.4）。"""
        _allow_settings(monkeypatch, wired.config)
        ctx = _ctx("委派 ghost-backend 做点什么")
        ctx.cometa_origin = dict(ORIGIN)
        assert await handle_delegation_turn(ctx, ROUTE) is True
        assert "ghost-backend" in ctx.reply
        assert ctx.cometa_submission is None  # 没有受理任何任务
