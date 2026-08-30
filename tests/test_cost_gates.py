# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Tier 1 成本闸门的行为基线（判据部分既不触库也不触网）。

四件事在这里守住：

1. **跳过 = 攒批，不是丢弃**：闸门跳过时只写 ``skip_streak``，
   **绝不推进 checkpoint**——推进了这批消息就永久没人整合了。
2. **连续跳过有上限**：撞到 ``CONSOLIDATION_MAX_SKIP_STREAK`` 就强制整合一次，
   最坏情况只是「延迟」，不会变成「某个群的消息永远不整合」。
3. **判据宁松勿紧**：拿不准一律不跳（没读到数据、还没有摘要、向量拿不到）。
   多花一次钱只是钱，漏掉一条「用户亲口说的信息」是记忆缺失。
4. **在线 / 本地各取自己那组键**：批量与重叠窗口按端点类型选。
"""
import asyncio
import sqlite3

import pytest

import memory.consolidator as consolidator
import memory.cost_gates as gates
from memory.consolidator import MemoryConsolidator

# ── T1-1 判据：图片 / 表情 / 单字附和 ──────────────────────


@pytest.mark.parametrize(
    "text",
    ["", "   ", None, "[CQ:image,file=abc.jpg]", "[CQ:face,id=1][CQ:face,id=2]",
     "。。。", "！？", "🤣🤣🤣", "嗯", "哈哈哈", "666", "ok", "早", "啊"],
)
def test_trivial_lines_carry_no_information(text):
    assert gates.is_trivial_line(text) is True


@pytest.mark.parametrize(
    "text",
    ["我在北京做后端开发", "嗯，这个方案我觉得可行", "[CQ:image,file=a.jpg] 这是我家的猫",
     "晚安啦，明天还要早起赶飞机"],
)
def test_substantive_lines_are_kept(text):
    assert gates.is_trivial_line(text) is False


def test_at_mention_source_always_wins():
    """只要有人对 Bot 说过话就一定整合——AT_MENTION 是唯一稳定的信息源。"""
    assert gates.should_skip_by_source_ratio(["111"], ["嗯", "哈哈"]) is None


def test_all_trivial_and_no_at_mention_skips():
    reason = gates.should_skip_by_source_ratio([], ["嗯", "[CQ:image,file=a.jpg]", "666"])
    assert reason and "全为图片/表情/单字附和" in reason


def test_one_substantive_line_is_enough_to_consolidate():
    assert gates.should_skip_by_source_ratio([], ["嗯", "我明年打算去日本读研"]) is None


def test_empty_batch_is_no_data_not_all_noise():
    """``lines`` 为空是「没读到数据」而不是「全是废话」，交给条数阈值判断。"""
    assert gates.should_skip_by_source_ratio([], []) is None
    assert gates.should_skip_by_source_ratio(None, None) is None


# ── T1-2 只喂 AT_MENTION 行及其上下文 ──────────────────────


def _numbered(n: int, marked: set[int]) -> str:
    return "\n".join(
        f"消息ID({i}) 用户(111){' ' + gates.AT_MENTION_MARKER if i in marked else ''}: 第{i}句"
        for i in range(n)
    )


def test_slice_keeps_at_mention_with_context():
    """保留命中行及其前后 N 行——用户的「对，就是这个」只有配上上一句才有意义。"""
    sliced = gates.at_mention_slice(_numbered(20, {10}), context_lines=2)
    kept = sliced.split("\n")
    assert len(kept) == 5
    assert "第8句" in kept[0] and "第12句" in kept[-1]
    assert gates.AT_MENTION_MARKER in kept[2]


def test_slice_merges_overlapping_windows_without_duplicates():
    sliced = gates.at_mention_slice(_numbered(20, {5, 6}), context_lines=2)
    lines = sliced.split("\n")
    assert len(lines) == len(set(lines))
    assert len(lines) == 6  # 3..8


def test_slice_without_any_at_mention_returns_original_text():
    """掐成空串等于静默关掉阶段2 提取，那种故障极难排查。"""
    text = _numbered(8, set())
    assert gates.at_mention_slice(text) == text


def test_slice_with_zero_context_keeps_only_hits():
    sliced = gates.at_mention_slice(_numbered(10, {3}), context_lines=0)
    assert sliced.count("\n") == 0
    assert gates.AT_MENTION_MARKER in sliced


# ── T1-3 / T1-4 语义新颖度 ────────────────────────────────


def _skip(batch: str, summary: str) -> str | None:
    return asyncio.run(gates.should_skip_by_novelty(batch, summary))


def test_first_batch_always_runs():
    """没有对照物时一律放行，否则新群永远等不到第一份摘要。"""
    assert _skip("我在上海做设计", "") is None
    assert _skip("", "已有一份摘要") is None


def test_lexical_repetition_skips_when_summary_already_says_it(monkeypatch):
    """T1-4：拿不到向量时落到词面判据——覆盖率分母只算本批（非对称）。"""
    monkeypatch.setattr(gates, "_embedding_similarity", _fake_embedding(None))
    reason = _skip("我们去吃饭吧今天天气很好", "今天天气很好呀，我们去吃饭吧")
    assert reason and "词面重复率过高" in reason


def test_lexical_substring_branch_skips(monkeypatch):
    monkeypatch.setattr(gates, "_embedding_similarity", _fake_embedding(None))
    reason = _skip(
        "今天天气很好我们去吃饭吧",
        "早些时候大家聊到今天天气很好我们去吃饭吧然后又说起别的",
    )
    assert reason and "互为子串" in reason


def test_new_topic_is_not_skipped(monkeypatch):
    monkeypatch.setattr(gates, "_embedding_similarity", _fake_embedding(None))
    assert _skip("讨论了显卡驱动的安装步骤和内核版本", "今天天气很好呀，我们去吃饭吧") is None


def _fake_embedding(value: float | None):
    async def _f(a: str, b: str) -> float | None:
        return value

    return _f


def test_vector_decides_when_available(monkeypatch):
    """T1-3：向量可用时由它定论，词面判据不再插手（哪怕词面看着重复）。"""
    monkeypatch.setattr(gates, "_embedding_similarity", _fake_embedding(0.42))
    assert _skip("今天天气很好我们去吃饭吧", "今天天气很好我们去吃饭吧再加点别的") is None

    monkeypatch.setattr(gates, "_embedding_similarity", _fake_embedding(0.97))
    reason = _skip("完全不相关的一句话", "另一句毫不相干的摘要")
    assert reason and "语义新颖度不足" in reason


def test_embedding_disabled_yields_no_vector(monkeypatch):
    """``MEMORY_EMBEDDING_ENABLED`` 默认关闭 → 必须落到 T1-4，否则这道闸永不触发。"""
    import config

    monkeypatch.setattr(config, "MEMORY_EMBEDDING_ENABLED", False)
    assert asyncio.run(gates._embedding_similarity("甲", "乙")) is None


def test_embedding_failure_never_breaks_the_gate(monkeypatch):
    """编码服务炸了就当「无从判断」→ 不跳过。闸门绝不能成为整合的失败点。"""
    import config

    monkeypatch.setattr(config, "MEMORY_EMBEDDING_ENABLED", True, raising=False)

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("embedding 服务没起")

    import memory.embeddings as embeddings

    monkeypatch.setattr(embeddings, "EmbeddingService", _Boom)
    assert asyncio.run(gates._embedding_similarity("甲", "乙")) is None


# ── 接进 consolidator：跳过 ≠ 丢弃 ────────────────────────


def _provision(cons: MemoryConsolidator, db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    cons._ensure_common_tables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT,"
        "source_kind TEXT DEFAULT 'PASSIVE',"
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    return conn


@pytest.fixture
def cons(tmp_path, monkeypatch):
    """一个挂在临时库上的整合器；预算与整合日志都短路掉，只留成本闸门这条链。"""
    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    monkeypatch.setattr(consolidator, "budget_blocked", lambda role: None)
    obj = MemoryConsolidator.__new__(MemoryConsolidator)
    conn = _provision(obj, db_path)
    conn.close()
    return obj


def _fill(cons_obj, group_id: int, contents, kind: str = "PASSIVE") -> None:
    conn = sqlite3.connect(consolidator.DB_PATH)
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) "
        "VALUES (?, ?, ?, ?)",
        [(str(group_id), "111", c, kind) for c in contents],
    )
    conn.commit()
    conn.close()


def _spy_generate(monkeypatch) -> list:
    """把 _generate 换成只记账的假实现（仍返回合法 6 元组，约束 3）。"""
    calls: list = []

    async def _fake(self, group_id, last_id, force=False):
        calls.append((group_id, last_id, force))
        return "", last_id, "fake", [], [], ""

    monkeypatch.setattr(MemoryConsolidator, "_generate", _fake)
    return calls


def test_gate_skip_does_not_advance_checkpoint(cons, monkeypatch):
    """T1-1 跳过时**只 return**：checkpoint 停在原地，这批消息留着攒下一轮。"""
    calls = _spy_generate(monkeypatch)
    _fill(cons, 7001, ["[CQ:image,file=a.jpg]"] * 40)

    asyncio.run(cons.consolidate_group(7001))

    assert calls == [], "闸门跳过之后不该再调 LLM"
    assert cons._get_last_processed_id(7001) == 0, "跳过路径推进了 checkpoint，消息会永久丢失"
    assert cons._get_skip_streak(7001) == 1


def test_at_mention_batch_is_never_skipped(cons, monkeypatch):
    """同一批全是废话，但有人对 Bot 说过话 → 照样整合。

    AT_MENTION 落在**本批窗口内**（窥批只看即将整合的那 threshold 条，
    窗口之外的消息属于下一批，不该影响这一批的判断）。
    """
    calls = _spy_generate(monkeypatch)
    _fill(cons, 7002, ["嗯"] * 10)
    _fill(cons, 7002, ["你好呀"], kind="AT_MENTION")
    _fill(cons, 7002, ["嗯"] * 29)

    asyncio.run(cons.consolidate_group(7002))

    assert len(calls) == 1
    assert cons._get_skip_streak(7002) == 0


def test_skip_streak_cap_forces_one_run(cons, monkeypatch):
    """连跳到上限强制整合一次，并把计数清零重新开始攒。"""
    calls = _spy_generate(monkeypatch)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_MAX_SKIP_STREAK", 3)
    _fill(cons, 7003, ["[CQ:face,id=1]"] * 40)

    for expected in (1, 2, 3):
        asyncio.run(cons.consolidate_group(7003))
        assert calls == []
        assert cons._get_skip_streak(7003) == expected

    asyncio.run(cons.consolidate_group(7003))
    assert len(calls) == 1, "撞到上限必须强制整合，否则这个群的消息会无限滞留"
    assert cons._get_skip_streak(7003) == 0


def test_zero_cap_means_no_backstop(cons, monkeypatch):
    """上限设 0 = 关掉兜底：连跳多少次都不强制（配置注释里写明了不推荐）。"""
    calls = _spy_generate(monkeypatch)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_MAX_SKIP_STREAK", 0)
    _fill(cons, 7004, ["666"] * 40)

    for _ in range(5):
        asyncio.run(cons.consolidate_group(7004))
    assert calls == []
    assert cons._get_skip_streak(7004) == 5


def test_force_path_bypasses_the_gate(cons, monkeypatch):
    """force 是 @ 触发前的即时总结：拦它只会让回复用上过期的摘要。"""
    calls = _spy_generate(monkeypatch)
    _fill(cons, 7005, ["[CQ:image,file=a.jpg]"] * 15)

    asyncio.run(cons.consolidate_group(7005, force=True))
    assert len(calls) == 1
    assert calls[0][2] is True


def test_peek_batch_excludes_bot_lines_and_reports_at_senders(cons):
    """窥批只统计用户发言；Bot 自己的话是上下文，不是「用户说的话」。"""
    _fill(cons, 7006, ["我在深圳"], kind="BOT_SELF")
    _fill(cons, 7006, ["我在广州工作"], kind="PASSIVE")
    _fill(cons, 7006, ["你在哪"], kind="AT_MENTION")

    lines, at_senders = cons._peek_batch(7006, 0, 10)
    assert lines == ["我在广州工作", "你在哪"]
    assert at_senders == ["111"]


def test_peek_batch_survives_a_missing_table(cons, monkeypatch, tmp_path):
    """读不到数据就返回空 → 判据放行。闸门绝不能成为整合的失败点。"""
    monkeypatch.setattr(consolidator, "DB_PATH", tmp_path / "nope.db")
    assert cons._peek_batch(7007, 0, 10) == ([], [])


def test_active_summary_lookup_ignores_recent_exchanges(cons):
    """新颖度只跟 active_summary 比：拿原话摘录去比重复率会虚高成必然跳过。"""
    conn = sqlite3.connect(consolidator.DB_PATH)
    conn.execute(
        "INSERT INTO short_term_context (group_id, active_summary, recent_exchanges) "
        "VALUES (?, ?, ?)",
        ("7008", "大家在讨论周末聚餐", "用户(111): 我要吃火锅"),
    )
    conn.commit()
    conn.close()
    assert cons._fetch_active_summary(7008) == "大家在讨论周末聚餐"
    assert cons._fetch_active_summary(7009) == ""


# ── 在线 / 本地各取自己那组键 ──────────────────────────────


def test_batch_size_and_overlap_follow_endpoint_kind(monkeypatch):
    monkeypatch.setattr(consolidator, "CONSOLIDATION_ONLINE_BATCH_SIZE", 60)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE", 30)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_ONLINE_OVERLAP", 0)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 30)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE", 10)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_OVERLAP", 15)

    monkeypatch.setattr(consolidator, "role_is_online", lambda role: True)
    assert consolidator._batch_size(False) == 60
    assert consolidator._batch_size(True) == 30
    assert consolidator._overlap() == 0

    monkeypatch.setattr(consolidator, "role_is_online", lambda role: False)
    assert consolidator._batch_size(False) == 30
    assert consolidator._batch_size(True) == 10
    assert consolidator._overlap() == 15


def test_unresolvable_endpoint_falls_back_to_local_keys(monkeypatch):
    """判不出端点类型时按本地取值（保守侧：小批量 + 有重叠窗口）。"""

    def _boom(role):
        raise RuntimeError("registry 还没初始化")

    monkeypatch.setattr(consolidator, "role_is_online", _boom)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_LOCAL_BATCH_SIZE", 30)
    monkeypatch.setattr(consolidator, "CONSOLIDATION_OVERLAP", 15)
    assert consolidator._consolidation_is_online() is False
    assert consolidator._batch_size(False) == 30
    assert consolidator._overlap() == 15
