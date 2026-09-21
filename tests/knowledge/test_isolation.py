# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆隔离护栏测试（plan §6.7：知识证据不得成为个人记忆候选）。"""

from __future__ import annotations

from core.context import ChatContext
from knowledge.isolation import evidence_leaked_into_memory


def _ctx() -> ChatContext:
    return ChatContext(user_id=1, group_id=1, msg_id=0, message="问题")


def test_clean_ctx_has_no_leak() -> None:
    ctx = _ctx()
    ctx.knowledge_evidence = [{"text": "数据库每日全量备份。", "citation": "《手册》"}]
    ctx.memories_for_prompt = [{"content": "用户喜欢在晚上聊天"}]
    assert evidence_leaked_into_memory(ctx) == []


def test_evidence_copied_into_memory_field_is_detected() -> None:
    ctx = _ctx()
    evidence_text = "数据库每日全量备份，保留三十天。"
    ctx.knowledge_evidence = [{"text": evidence_text, "citation": "《手册》"}]
    # 模拟某个未来改动把证据整段写进了记忆字段（契约被打破）
    ctx.memories_for_prompt = [{"content": f"用户说过：{evidence_text}"}]
    leaked = evidence_leaked_into_memory(ctx)
    assert leaked and leaked[0].startswith("数据库每日全量备份")


def test_leak_detected_in_short_term_and_conversation() -> None:
    ctx = _ctx()
    ctx.knowledge_evidence = [{"text": "服务器 root 密码每季度轮换一次。"}]
    ctx.short_term = "……服务器 root 密码每季度轮换一次。"
    assert evidence_leaked_into_memory(ctx)
    ctx2 = _ctx()
    ctx2.knowledge_evidence = [{"text": "发布窗口为周二凌晨。"}]
    ctx2.conversation_memories = [{"text": "发布窗口为周二凌晨。"}]
    assert evidence_leaked_into_memory(ctx2)


def test_no_evidence_no_leak() -> None:
    ctx = _ctx()
    ctx.short_term = "任何内容"
    assert evidence_leaked_into_memory(ctx) == []


def test_paraphrased_memory_is_not_a_leak() -> None:
    """记忆整合的是聊天记录；对证据的**改写**（非照抄）不算泄漏。"""
    ctx = _ctx()
    ctx.knowledge_evidence = [{"text": "数据库每日凌晨两点执行全量备份并保留三十天历史。"}]
    ctx.memories_for_prompt = [{"content": "用户最近在整理备份策略的资料"}]
    assert evidence_leaked_into_memory(ctx) == []


def test_isolation_guard_in_hooks_clears_evidence(monkeypatch) -> None:
    """hooks 的护栏：发现泄漏时清空证据（宁丢证据不污染记忆）且不抛异常。"""
    import asyncio

    from capability.hooks import _check_memory_isolation

    ctx = _ctx()
    ctx.knowledge_evidence = [{"text": "将被判定为泄漏的整段证据文本。"}]
    ctx.memories_for_prompt = [{"content": "将被判定为泄漏的整段证据文本。"}]
    asyncio.run(asyncio.to_thread(_check_memory_isolation, ctx))
    assert ctx.knowledge_evidence == []


def test_isolation_guard_keeps_clean_evidence() -> None:
    import asyncio

    from capability.hooks import _check_memory_isolation

    async def _run() -> None:
        ctx = _ctx()
        ctx.knowledge_evidence = [{"text": "干净的证据。"}]
        ctx.memories_for_prompt = [{"content": "无关记忆"}]
        _check_memory_isolation(ctx)
        assert ctx.knowledge_evidence == [{"text": "干净的证据。"}]

    asyncio.run(_run())
