# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""全流程（端到端）回归测试。

不验证单个模块，而是串联验证"一条群聊消息从入库到记忆沉淀"的主链路：

1. 消息入库（record_message → group_messages）；
2. 上下文构建（build_context / build_user_context → short_term / user_profile）；
3. Pipeline 编排（pre-hooks → Dummy LLM → post-hooks：parse_output → split_lines → 日志）；
4. 记忆整合（consolidate_group → short_term_context / user_profiles / memory_candidates，
   并驱动 MemoryManager 白名单校验 + 晋升到 memories + FTS 索引）；
5. 召回回环（下次 build_context 读取已落库的短期摘要，而不是原始消息回退）。

整个测试完全不触网：用 Dummy LLM 后端替换真实 LM Studio；不导入
ai_gateway（避免拉起 NoneBot 事件监听）。
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import memory.consolidator as consolidator
import memory.memory_manager as memory_manager_mod
import memory.post_processors as post_processors
import memory.pre_processors as pre_processors
import memory.retriever as retriever
from core.context import ChatContext
from core.pipeline import Pipeline
from config.spaces import resolve_space
from memory.consolidator import MemoryConsolidator


def _patch_all_paths(monkeypatch, db_path: Path, tmp_path: Path):
    """把各模块的 DB_PATH / 日志路径一并指向隔离的临时目录，全程不碰真实库与仓库文件。"""
    for mod in (pre_processors, consolidator, retriever, memory_manager_mod):
        monkeypatch.setattr(mod, "DB_PATH", db_path)
    monkeypatch.setattr(post_processors, "THOUGHT_LOG_PATH", tmp_path / "thought_log.md")
    # 整合日志不写真实仓库
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)

    class _NoCompressor:
        def maybe_compress(self, reason=""):
            return None

    monkeypatch.setattr(memory_manager_mod, "get_compressor", lambda: _NoCompressor())


class DummyBackend:
    """固定回显 preset 文本的伪 LLM 后端，替代真实 LM Studio（不发起任何 HTTP）。"""

    backend_name = "dummy_local"
    model = "dummy-model"

    def __init__(self, raw_output: str):
        self._raw_output = raw_output
        self.last_prompt = ""

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self.last_prompt = prompt
        return self._raw_output


def _make_pipeline(dummy: DummyBackend) -> Pipeline:
    """组装与 ai_gateway 相同顺序的 pre/post hooks。"""
    pipeline = Pipeline(timeout=90.0)
    pipeline.register_pre_hook(pre_processors.record_message, priority=30)
    pipeline.register_pre_hook(pre_processors.build_context, priority=20)
    pipeline.register_pre_hook(pre_processors.build_user_context, priority=10)
    pipeline.set_llm_backend(dummy)
    pipeline.register_post_hook(post_processors.parse_output, priority=30)
    pipeline.register_post_hook(post_processors.bad_phrase_filter, priority=20)
    pipeline.register_post_hook(post_processors.split_lines, priority=10)
    pipeline.register_post_hook(post_processors.log_thought, priority=5)
    return pipeline


def _create_schema(db_path: Path):
    """预建整合相关的公共表（含 memories），让 RAG 检索在空库上也能无异常回退。"""
    conn = sqlite3.connect(db_path)
    MemoryConsolidator.__new__(MemoryConsolidator)._ensure_common_tables(conn)
    conn.commit()
    conn.close()


def test_full_workflow_chat_message_to_reply(tmp_path, monkeypatch):
    """一条群聊 → 入库 → 构建上下文 → Pipeline(权限 + Dummy LLM + 解析/分行/日志)。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    _create_schema(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO user_profiles (group_shared_space, user_id, nickname, personality_traits) VALUES (?, ?, ?, ?)",
        (resolve_space(1001), "111", "阿散", "性格外向，爱运动"),
    )
    conn.commit()
    conn.close()

    _patch_all_paths(monkeypatch, db_path, tmp_path)

    ctx = ChatContext(user_id=111, group_id=1001, msg_id=1, message="你好，今天天气怎么样")
    dummy = DummyBackend(
        "<thought>今天是晴天</thought><action>REPLY</action>"
        "<reply>今天天气很好，记得散步。\n带上一把伞。</reply>"
    )
    pipeline = _make_pipeline(dummy)
    asyncio.run(pipeline.run(ctx))

    # ① 原始消息已入库
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM group_messages").fetchone()[0]
    conn.close()
    assert count == 1

    # ② 结构化上下文注入成功（微画像被 build_user_context 读出）
    assert "性格外向" in ctx.user_profile
    # ③ 诊断信息
    assert ctx.llm_backend == "dummy_local"
    assert ctx.llm_model == "dummy-model"
    assert "今天天气怎么样" in dummy.last_prompt
    # ④ 输出解析与分行
    assert "今天天气很好" in ctx.reply
    assert ctx.action == "REPLY"
    assert ctx.lines == ["今天天气很好，记得散步。", "带上一把伞。"]
    # ⑤ 思考日志已写入（且写在临时目录，而非真实仓库）
    assert (tmp_path / "thought_log.md").exists()


def _write_messages(db_path: Path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT,"
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    cursor.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        [
            ("1001", "111", "我以前练过三年散打"),
            ("1001", "112", "我也喜欢格斗"),
        ],
    )
    conn.commit()
    conn.close()


def test_full_workflow_consolidation_promotes_memory(tmp_path, monkeypatch):
    """群消息 → 整合（Dummy 摘要） → 短期上下文/画像/候选落库 → MemoryManager 晋升长期记忆 + FTS。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    _patch_all_paths(monkeypatch, db_path, tmp_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 1)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE", 1)
    _write_messages(db_path)

    c = MemoryConsolidator.__new__(MemoryConsolidator)

    async def fake_generate(self, group_id, last_id, force=False):
        return (
            json.dumps({
                "short_term": {
                    "active_summary": "在聊格斗训练",
                    "pending_topic": "练体散打经历",
                    "recent_exchanges": [{"user_id": "111", "content": "今天练过三年散打"}],
                },
                "user_profiles": [
                    {"user_id": "111", "nickname": "阿散", "personality_traits": "爱运动，喜欢散打", "agent_attitude": ""},
                ],
                "memory_candidates": [
                    {"user_id": "111", "type": "FACT", "content": "A 说自己练过三年散打", "importance": 0.9, "confidence": 0.9},
                    {"user_id": "999", "type": "FACT", "content": "没发言却被归属的人", "importance": 0.9, "confidence": 0.9},
                ],
            }),
            2,
            "lm_studio",
            ["111", "112"],
            ["111"],
            "",
        )

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_generate)
    asyncio.run(c.consolidate_group(1001))

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 短期上下文已落库（摘要 + 归属发言）
    row = cur.execute(
        "SELECT active_summary, recent_exchanges FROM short_term_context WHERE group_id = '1001'"
    ).fetchone()
    assert row and row[0] == "在聊格斗训练"
    assert "练过三年散打" in json.loads(row[1])[0]["content"]

    # 用户画像已合并写入
    profile = cur.execute(
        "SELECT personality_traits FROM user_profiles WHERE group_shared_space = ? AND user_id = '111'",
        (resolve_space(1001),),
    ).fetchone()
    assert profile and "散打" in profile[0]

    # 候选：白名单过滤（丢 999），晋升后状态 CONFIRMED
    total_candidates = cur.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0]
    bad_candidates = cur.execute(
        "SELECT COUNT(*) FROM memory_candidates WHERE content LIKE '%没发言%'"
    ).fetchone()[0]
    confirmed = cur.execute(
        "SELECT COUNT(*) FROM memory_candidates WHERE status = 'CONFIRMED'"
    ).fetchone()[0]
    assert total_candidates == 1
    assert bad_candidates == 0
    assert confirmed == 1

    # 长期记忆 + FTS 索引入库
    memory = cur.execute("SELECT content FROM memories").fetchone()
    assert memory and "练过三年散打" in memory[0]
    fts_count = cur.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
    conn.close()
    assert fts_count == 1


def test_full_workflow_summary_feeds_next_reply(tmp_path, monkeypatch):
    """短期摘要回环：整合后的摘要应在下一轮对话中被 build_context 读取，而非回退原始消息。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    _patch_all_paths(monkeypatch, db_path, tmp_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 1)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE", 1)
    _write_messages(db_path)

    c = MemoryConsolidator.__new__(MemoryConsolidator)

    async def fake_generate(self, group_id, last_id, force=False):
        return (
            json.dumps({
                "short_term": {
                    "active_summary": "在聊格斗训练",
                    "pending_topic": "练散打经历",
                    "recent_exchanges": [{"user_id": "111", "content": "今天练过三年散打"}],
                },
                "user_profiles": [],
                "memory_candidates": [
                    {"user_id": "111", "type": "FACT", "content": "A 喜欢格斗", "importance": 0.8, "confidence": 0.9},
                ],
            }),
            2,
            "lm_studio",
            ["111", "112"],
            ["111"],
            "",
        )

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_generate)
    asyncio.run(c.consolidate_group(1001))

    # 下一轮对话：build_context 应命中短期摘要（话题层）并附加原始尾巴；
    # recent_exchanges 是摘要的滞后快照，有原始尾巴时被丢弃（2026-08-13 bug 修复）
    ctx = ChatContext(user_id=112, group_id=1001, msg_id=3, message="你们在聊什么")
    asyncio.run(pre_processors.build_context(ctx))

    assert "对话摘要: 在聊格斗训练" in ctx.short_term
    assert "进行中的话题: 练散打经历" in ctx.short_term
    assert "近期关键发言" not in ctx.short_term
    # 原始尾巴补足最近几轮：整合器产出的 recent_exchanges（「今天练过三年散打」）被丢弃，
    # 实际消息以原始形式呈现
    assert "用户(111): 我以前练过三年散打" in ctx.short_term


def test_full_workflow_force_consolidation_small_batch(tmp_path, monkeypatch):
    """@触发/主动前的 force 路径：小阈值下 force 也能正常整合并推进 checkpoint。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    _patch_all_paths(monkeypatch, db_path, tmp_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 100)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE", 1)
    _write_messages(db_path)

    c = MemoryConsolidator.__new__(MemoryConsolidator)

    async def fake_force(self, group_id, last_id, force=False):
        assert force is True
        return (
            json.dumps({
                "short_term": {"active_summary": "聊格斗"},
                "user_profiles": [],
                "memory_candidates": [],
            }),
            2,
            "lm_studio",
            ["111", "112"],
            [],
            "",
        )

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_force)
    asyncio.run(c.consolidate_group(1001, force=True))

    conn = sqlite3.connect(db_path)
    checkpoint = conn.execute(
        "SELECT last_processed_id FROM consolidation_state WHERE group_id = '1001'"
    ).fetchone()
    conn.close()
    assert checkpoint == (2,)
