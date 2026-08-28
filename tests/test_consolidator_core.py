# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.consolidator 私有方法的单元测试。

把 consolidator.DB_PATH monkeypatch 指向临时库，直接调用读写私有方法，
覆盖：JSON 容错解析、user_id 规范化、特征合并、checkpoint、
短期上下文/用户画像/候选/旧格式记忆写入、消息表选择与消息获取。
"""

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

import memory.consolidator as consolidator
from memory.consolidator import MemoryConsolidator


def _make_consolidator() -> MemoryConsolidator:
    return MemoryConsolidator.__new__(MemoryConsolidator)


def _insert_group_messages(conn: sqlite3.Connection, group_id: str, count: int) -> None:
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        [(group_id, "111", "m" + str(i)) for i in range(count)],
    )


def _provision(cons: MemoryConsolidator, db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cons._ensure_common_tables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT,"
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS long_term_memories ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, summary TEXT,"
        "importance REAL, access_count INTEGER DEFAULT 0, last_accessed_at TEXT)"
    )
    conn.commit()
    return conn


def test_parse_json_variants():
    cons = _make_consolidator()
    assert cons._parse_json("```json\n{\"a\": 1}\n```") == {"a": 1}
    assert cons._parse_json("{\"a\": 1}") == {"a": 1}
    assert cons._parse_json("散文前缀 {\"a\": {\"b\": \"x\"}} 尾巴") == {"a": {"b": "x"}}
    assert cons._parse_json("完全没有 JSON") is None


def test_normalize_user_id():
    cons = _make_consolidator()
    assert cons._normalize_user_id("3089665724") == "3089665724"
    assert cons._normalize_user_id("用户(3089665724)") == "3089665724"
    assert cons._normalize_user_id("") == ""
    assert cons._normalize_user_id("xxx") == "xxx"


def test_merge_traits_dedupes():
    cons = _make_consolidator()
    merged = cons._merge_traits("爱运动，乐观", "乐观，喜欢AI")
    assert merged.count("乐观") == 1
    assert "爱运动" in merged
    assert "喜欢AI" in merged
    assert cons._merge_traits("", "新") == "新"
    assert cons._merge_traits("旧", "") == "旧"
    assert cons._merge_traits("", "") == ""


def test_checkpoint_and_state_table(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    conn.close()

    assert cons._get_last_processed_id(1001) == 0
    cons._update_checkpoint(1001, 42)
    assert cons._get_last_processed_id(1001) == 42


def test_fetch_next_messages_and_senders(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_OVERLAP", 15)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        [
            ("1001", "111", "第一条"),
            ("1001", "112", "第二条"),
            ("1001", "111", "第三条"),
        ],
    )
    conn.commit()
    conn.close()

    text, batch_end, senders, at_senders = cons._fetch_next_messages(1001, 0, 10)
    assert batch_end == 3
    assert "第一条" in text
    assert senders == ["111", "112"]
    # 表中无 source_kind 列时回退旧查询，全部视为 PASSIVE
    assert at_senders == []
    assert cons._get_message_table(sqlite3.connect(db_path).cursor()) == "group_messages"

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE group_messages")
    conn.commit()
    conn.close()
    assert cons._get_message_table(sqlite3.connect(db_path).cursor()) == "messages"

    text, batch_end, senders, at_senders = cons._fetch_next_messages(1001, 100, 10)
    assert batch_end == 100


def test_fetch_next_messages_source_kind_at_mention(tmp_path, monkeypatch):
    """带 source_kind 列时，AT_MENTION 消息被标注 [对Bot说]，且 at_senders 正确收集。"""
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_OVERLAP", 15)
    monkeypatch.setattr(consolidator, "MEMORY_SOURCE_KIND_ENABLED", True)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    conn.execute("ALTER TABLE group_messages ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'")
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) VALUES (?, ?, ?, ?)",
        [
            ("1001", "111", "普通一句", "PASSIVE"),
            ("1001", "112", "@你 这是什么", "AT_MENTION"),
            ("1001", "111", "又一句", "PASSIVE"),
        ],
    )
    conn.commit()
    conn.close()

    text, batch_end, senders, at_senders = cons._fetch_next_messages(1001, 0, 10)
    assert batch_end == 3
    assert "消息ID(1) 用户(111): 普通一句" in text
    assert "消息ID(2) 用户(112) [对Bot说]: @你 这是什么" in text
    assert senders == ["111", "112"]
    assert at_senders == ["112"]


def test_count_new_messages_and_has_new(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        [("1001", "111", "a"), ("1001", "111", "b")],
    )
    conn.commit()
    conn.close()
    assert cons._count_new_messages(1001, 0) == 2
    assert cons._count_new_messages(1001, 1) == 1
    assert cons.has_new_messages_to_consolidate(1001, threshold=3) == 0
    assert cons.has_new_messages_to_consolidate(1001) == 2


def test_write_short_term_upsert(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    _provision(cons, db_path)

    cons._write_short_term(
        1001,
        {
            "active_summary": "摘要A",
            "pending_topic": "话题",
            "recent_exchanges": [
                {"user_id": "111", "content": "说话"},
                {"user_id": "用户(222)", "content": "说话2"},
                {"user_id": "", "content": "无归属"},
                "not-a-dict",
            ],
        },
    )
    cons._write_short_term(1001, {"active_summary": "摘要B", "pending_topic": "无"})


def test_write_user_profiles_new_and_merge(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    _provision(cons, db_path)

    cons._write_user_profiles(
        "1001",
        [
            {"user_id": "用户(111)", "nickname": "阿散", "personality_traits": "爱运动", "agent_attitude": "友好"},
            {"user_id": "", "nickname": "无名", "personality_traits": "x"},
        ],
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT personality_traits, interaction_count FROM user_profiles WHERE group_shared_space='1001' AND user_id='111'").fetchone()
    assert row and "爱运动" in row[0]
    assert row[1] == 1
    assert conn.execute("SELECT COUNT(*) FROM user_profiles").fetchone()[0] == 1
    conn.close()

    cons._write_user_profiles(
        "1001",
        [{"user_id": "111", "nickname": "", "personality_traits": "乐观", "agent_attitude": "更友好"}],
    )
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT interaction_count, agent_attitude, personality_traits FROM user_profiles WHERE group_shared_space='1001' AND user_id='111'").fetchone()
    conn.close()
    assert row[0] == 2
    assert "更友好" in row[1]
    assert row[2].count("爱运动") == 1


def test_write_memory_candidates_whitelist(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    _provision(cons, db_path)

    cons._write_memory_candidates(
        "1001",
        [
            {"user_id": "111", "type": "fact", "content": "会写程序", "importance": "0.8", "confidence": "0.9", "source_message_ids": [1, 2]},
            {"user_id": "999", "type": "FACT", "content": "不在白名单", "importance": 0.9, "confidence": 0.9, "source_message_ids": "not-json-["},
            {"user_id": "222", "type": "", "content": "", "importance": 0.1, "confidence": 0.1},
        ],
        sender_ids=["111"],
    )
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    count_in = cur.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0]
    bad = cur.execute("SELECT COUNT(*) FROM memory_candidates WHERE content LIKE '%不在白名单%'").fetchone()[0]
    saved = cur.execute("SELECT type, source_message_ids, status FROM memory_candidates WHERE content='会写程序'").fetchone()
    conn.close()
    assert count_in == 1
    assert bad == 0
    assert saved is not None
    assert saved[0] == "FACT"
    assert json.loads(saved[1]) == ["1", "2"]
    assert saved[2] == "NEW"


def test_write_long_term_memories(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    _provision(cons, db_path)

    cons._write_long_term_memories(
        "1001",
        [
            {"user_id": "111", "summary": "程序员", "importance": 8},
            {"user_id": "111", "summary": "程序员", "importance": 7},
            {"user_id": "222", "summary": "", "importance": 9},
            {"user_id": "333", "summary": "低重要度", "importance": 2},
        ],
    )
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM long_term_memories").fetchone()[0]
    conn.close()
    assert count == 1


def test_build_prompt_and_fetch_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    _provision(cons, db_path)

    assert cons._fetch_current_summary(1001) == ""
    cons._write_short_term(
        1001,
        {
            "active_summary": "在聊技术",
            "pending_topic": "部署",
            "recent_exchanges": [{"user_id": "111", "content": "我用Linux"}],
        },
    )
    summary = cons._fetch_current_summary(1001)
    assert "在聊技术" in summary
    assert "用户(111)" in summary
    prompt = cons._build_prompt(1001, "【消息】 hello")
    assert "在聊技术" in prompt
    assert "hello" in prompt


# ── 整合积压（backlog / drain_group） ────────────────────

def test_backlog_counts_unprocessed(tmp_path, monkeypatch):
    """backlog() 返回 checkpoint 之后的未整合消息数。"""
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    _insert_group_messages(conn, "1001", 5)
    conn.commit()
    conn.close()

    assert cons.backlog(1001) == 5
    cons._update_checkpoint(1001, 3)
    assert cons.backlog(1001) == 2
    cons._update_checkpoint(1001, 5)
    assert cons.backlog(1001) == 0


def test_drain_group_processes_up_to_max_rounds(tmp_path, monkeypatch):
    """积压 3 批以上时 drain_group(max_rounds=3) 恰好完成 3 批、checkpoint 推进 3 批。"""
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 10)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    _insert_group_messages(conn, "1001", 35)
    conn.commit()
    conn.close()

    async def fake_generate(self, group_id, last_id, force=False):
        _, batch_end, senders, _ = cons._fetch_next_messages(group_id, last_id, 10)
        return "{}", batch_end, "fake", senders, [], ""

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_generate)

    rounds = asyncio.run(cons.drain_group(1001, max_rounds=3))
    assert rounds == 3
    assert cons._get_last_processed_id(1001) == 30
    assert cons.backlog(1001) == 5


def test_drain_group_skips_when_below_batch(tmp_path, monkeypatch):
    """积压不足一批时返回 0 且不调用 LLM。"""
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 10)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    _insert_group_messages(conn, "1001", 5)
    conn.commit()
    conn.close()

    called: list[bool] = []

    async def fake_generate(self, group_id, last_id, force=False):
        called.append(True)
        raise AssertionError("积压不足一批不应调用 LLM")

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_generate)

    rounds = asyncio.run(cons.drain_group(1001, max_rounds=3))
    assert rounds == 0
    assert called == []


def test_drain_group_stops_when_checkpoint_not_advancing(tmp_path, monkeypatch):
    """某批 checkpoint 未推进（后端抛异常模拟）时提前停止本轮排空。"""
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 10)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    _insert_group_messages(conn, "1001", 20)
    conn.commit()
    conn.close()

    async def fake_generate(self, group_id, last_id, force=False):
        raise RuntimeError("后端不可用")

    monkeypatch.setattr(consolidator.MemoryConsolidator, "_generate", fake_generate)

    rounds = asyncio.run(cons.drain_group(1001, max_rounds=3))
    assert rounds == 0
    # checkpoint 未推进
    assert cons._get_last_processed_id(1001) == 0


# ── 输出截断（finish_reason=length）不许丢消息 ──────────────────────
class _FakeBackend:
    """按预设的 finish_reason 序列应答，并记录每次收到的 prompt。"""

    def __init__(self, finishes, reply: str = "{}"):
        self.model = "fake-model"
        self._finishes = list(finishes)
        self.reply = reply
        self.prompts: list[str] = []

    async def generate_detailed(self, prompt: str, system_prompt: str = ""):
        self.prompts.append(prompt)
        finish = self._finishes[min(len(self.prompts) - 1, len(self._finishes) - 1)]
        return self.reply, finish


def test_batch_ladder_halves_down_to_floor():
    """退让阶梯：逐级减半、下界 _TRUNCATION_MIN_BATCH、级数不超过上限。

    在线端点下每一级都是一次真实计费调用，所以级数必须有上限。
    """
    assert consolidator._batch_ladder(30) == [30, 15, 7]
    assert consolidator._batch_ladder(10) == [10, 5]
    assert consolidator._batch_ladder(5) == [5]
    assert consolidator._batch_ladder(1) == [1]
    for base in (1, 5, 10, 30, 100):
        ladder = consolidator._batch_ladder(base)
        assert len(ladder) <= consolidator._TRUNCATION_MAX_ATTEMPTS
        assert ladder == sorted(ladder, reverse=True)
        assert ladder[-1] >= min(base, consolidator._TRUNCATION_MIN_BATCH)


def _prepare_generate(tmp_path, monkeypatch, finishes, count: int = 30):
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 30)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    cons = _make_consolidator()
    conn = _provision(cons, db_path)
    _insert_group_messages(conn, "1001", count)
    conn.commit()
    conn.close()
    backend = _FakeBackend(finishes)
    cons._backends = [("fake", backend)]
    return cons, backend


def test_generate_shrinks_batch_when_output_truncated(tmp_path, monkeypatch):
    """截断后缩小批次重试：第二次成功，checkpoint 只推进实际整合过的那一段。

    截断的 JSON 必然解析不完整，而解析失败路径会推进 checkpoint 防同批重跑——
    若不在这里拦住，那批消息就永久丢了。
    """
    cons, backend = _prepare_generate(tmp_path, monkeypatch, ["length", "stop"])

    result, batch_end, name, senders, _at_senders, messages = asyncio.run(
        cons._generate(1001, 0)
    )

    assert result == "{}"
    assert len(backend.prompts) == 2, "截断后应当再试一次"
    assert len(backend.prompts[1]) < len(backend.prompts[0]), "重试的 prompt 必须更短"
    # 第二次只取 15 条（30 的一半），checkpoint 相应只推进到第 15 条
    assert batch_end == 15
    assert name == "fake"
    assert senders and messages


def test_generate_raises_when_still_truncated_at_floor(tmp_path, monkeypatch):
    """退到底仍截断 → 抛 OutputTruncatedError（配置问题，重试解决不了）。"""
    cons, backend = _prepare_generate(tmp_path, monkeypatch, ["length"])

    with pytest.raises(consolidator.OutputTruncatedError):
        asyncio.run(cons._generate(1001, 0))
    assert len(backend.prompts) == len(consolidator._batch_ladder(30))


def test_consolidate_group_keeps_checkpoint_when_truncated(tmp_path, monkeypatch):
    """截断到底时 checkpoint 必须停在原地，这批消息完整留待重跑。"""
    cons, _ = _prepare_generate(tmp_path, monkeypatch, ["length"])

    asyncio.run(cons.consolidate_group(1001))

    assert cons._get_last_processed_id(1001) == 0


def test_consolidate_group_advances_checkpoint_on_unparsable_output(tmp_path, monkeypatch):
    """对照组：非截断的 JSON 解析失败仍推进 checkpoint（模型胡言乱语，重跑无益）。"""
    cons, _ = _prepare_generate(tmp_path, monkeypatch, ["stop"])
    cons._backends[0][1].reply = "完全没有 JSON"

    asyncio.run(cons.consolidate_group(1001))

    assert cons._get_last_processed_id(1001) == 30
