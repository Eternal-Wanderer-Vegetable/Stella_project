# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""短期记忆说话人归属（attribution）的回归测试。

背景：曾经短期摘要只存"主题"，丢掉了"谁说了什么"，导致聊天模型把
A 的发言（如"我练了三年散打"）误当成当前 @ 的用户 B 说的。

覆盖：
- _write_short_term 会落库 recent_exchanges（带 user_id），build_context 能拼回带归属的上下文；
- 旧库没有 recent_exchanges 列时 build_context / _fetch_current_summary 能优雅回退；
- build_prompt_context 在给定 current_user_id 时注入"不要把别人发言归给当前用户"的提示；
- _write_memory_candidates 会把 user_id 不在本批发送者名单里的候选丢弃（防长期记忆张冠李戴）。
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import memory.consolidator as consolidator
import memory.pre_processors as pre_processors
from memory.consolidator import MemoryConsolidator
from memory.prompt_builder import build_prompt_context


def _make_consolidator() -> MemoryConsolidator:
    """绕过 __init__（避免构造 LLM 后端），只取方法做测试。"""
    return MemoryConsolidator.__new__(MemoryConsolidator)


def _write_messages(db_path: Path):
    """写入一条消息：A 说练了三年散打，B 否认。"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT,"
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    rows = [
        ("1001", "111", "我以前练散打学了三年"),
        ("1001", "222", "其实没有"),
    ]
    cursor.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def test_write_and_read_short_term_keeps_attribution(tmp_path, monkeypatch):
    """整合器写入带归属的关键发言后，build_context 应输出「用户(id): 内容」而非主题碎片。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(pre_processors, "DB_PATH", db_path)

    c = _make_consolidator()
    c._write_short_term(1001, {
        "active_summary": "聊散打",
        "pending_topic": "练散打经历",
        "recent_exchanges": [
            {"user_id": "111", "content": "我以前练散打学了三年"},
            {"user_id": "222", "content": "其实没有"},
        ],
    })

    ctx = _make_chat_context(user_id=222, group_id=1001)
    asyncio.run(pre_processors.build_context(ctx))

    assert "用户(111): 我以前练散打学了三年" in ctx.short_term
    assert "用户(222): 其实没有" in ctx.short_term


def test_build_context_falls_back_when_column_missing(tmp_path, monkeypatch):
    """旧库 short_term_context 无 recent_exchanges 列时，build_context 不应报错，仍输出摘要。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE short_term_context (
            group_id TEXT PRIMARY KEY,
            active_summary TEXT,
            pending_topic TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "INSERT INTO short_term_context (group_id, active_summary, pending_topic) VALUES (?, ?, ?)",
        ("1001", "聊散打", "练散打经历"),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(pre_processors, "DB_PATH", db_path)

    ctx = _make_chat_context(user_id=222, group_id=1001)
    asyncio.run(pre_processors.build_context(ctx))

    assert "对话摘要: 聊散打" in ctx.short_term


def test_fetch_current_summary_includes_exchanges(tmp_path, monkeypatch):
    """_fetch_current_summary 应把 recent_exchanges 一并带出，供下一批整合保持归属连续。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)

    c = _make_consolidator()
    c._write_short_term(1001, {
        "active_summary": "聊散打",
        "recent_exchanges": [
            {"user_id": "111", "content": "我以前练散打学了三年"},
        ],
    })
    summary = c._fetch_current_summary(1001)

    assert "用户(111): 我以前练散打学了三年" in summary


def test_memory_candidates_drop_unknown_sender(tmp_path, monkeypatch):
    """候选记忆的 user_id 不在本批发送者名单内时，应被丢弃，防止张冠李戴进入长期记忆。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)

    c = _make_consolidator()
    candidates = [
        {"user_id": "111", "type": "FACT", "content": "A 说自己练过三年散打", "importance": 0.8, "confidence": 0.9},
        {"user_id": "222", "type": "FACT", "content": "B 否认练过散打", "importance": 0.8, "confidence": 0.9},
        {"user_id": "999", "type": "FACT", "content": "C 根本没发言却被归属", "importance": 0.8, "confidence": 0.9},
    ]
    c._write_memory_candidates(1001, candidates, sender_ids=["111", "222"])

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memory_candidates WHERE content LIKE '%C 根本没发言%'")
    bad = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM memory_candidates")
    total = cursor.fetchone()[0]
    conn.close()

    assert bad == 0
    assert total == 2


def test_prompt_builder_attributes_current_user(tmp_path):
    """给定 current_user_id 时，prompt 应注入归属说明；0/None 时（主动发言）不注入。"""
    short_term = "对话摘要: 聊散打\n近期关键发言:\n用户(111): 我以前练散打学了三年"
    prompt = build_prompt_context(short_term, "", [], current_user_id=222)
    assert "当前与你对话的用户 QQ 号：222" in prompt

    prompt_proactive = build_prompt_context(short_term, "", [], current_user_id=0)
    assert "当前与你对话的用户" not in prompt_proactive


def test_consolidate_group_unpacks_senders(tmp_path, monkeypatch):
    """整合主流程应把 _generate 返回的发送者列表正确解包，并用它对记忆候选做白名单校验。

    回归保护：曾因 senders 只在 _generate 内部定义、未随返回值带出，导致
    consolidate_group 抛 NameError，整批整合失败。
    """
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    # 压小阈值，让 2 条消息即可触发整合
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 1)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE", 1)

    class DummyManager:
        def process_new_candidates(self):
            pass

    monkeypatch.setattr(consolidator, "get_memory_manager", lambda: DummyManager())

    _write_messages(db_path)  # 群 1001：用户 111、222 各一条

    c = _make_consolidator()
    c._backends = []  # 跳过 __init__ 后手动补上 backends 字段

    async def fake_generate(self, group_id, last_id, force=False):
        return (
            json.dumps({
                "short_term": {
                    "active_summary": "聊散打",
                    "recent_exchanges": [{"user_id": "111", "content": "我以前练散打学了三年"}],
                },
                "user_profiles": [],
                "memory_candidates": [
                    {"user_id": "111", "type": "FACT", "content": "A 说自己练过三年散打", "importance": 0.8, "confidence": 0.9},
                    {"user_id": "999", "type": "FACT", "content": "C 根本没发言却被归属", "importance": 0.8, "confidence": 0.9},
                ],
            }),
            2,
            "lm_studio",
            ["111", "222"],
        )

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_generate)

    asyncio.run(c.consolidate_group(1001))

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memory_candidates")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM memory_candidates WHERE content LIKE '%C 根本没发言%'")
    bad = cursor.fetchone()[0]
    cursor.execute("SELECT last_processed_id FROM consolidation_state WHERE group_id = '1001'")
    checkpoint = cursor.fetchone()[0]
    conn.close()

    assert total == 1
    assert bad == 0
    assert checkpoint == 2


def _make_chat_context(user_id: int, group_id: int) -> object:
    """构造一个最简 ChatContext（仅用 build_context 会读到的字段）。"""
    from core.context import ChatContext
    return ChatContext(
        user_id=user_id,
        group_id=group_id,
        msg_id=1,
        message="其实没有",
    )
