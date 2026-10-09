# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话压缩执行侧的行为基线（不触网，LLM 后端被替换为假实现）。

重点覆盖三件事：压缩 prompt 的防编造条款、待压缩区间的边界正确性、
以及「调用失败」与「模型判定无内容」两种空结果的区别处理。
"""
import asyncio
import json
import sqlite3

import pytest

from memory import session_compact as compact
from memory import session_context as sc
from memory.summary_packet import (
    SummarySourceMessage,
    build_summary_evidence,
    build_summary_packet,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sc.reset_state()
    compact.reset_state()
    monkeypatch.setattr(sc, "SESSION_CONTEXT_ENABLED", True)
    yield
    sc.reset_state()
    compact.reset_state()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "compact.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, "
        "content TEXT, source_kind TEXT DEFAULT 'PASSIVE', "
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(compact, "DB_PATH", path)
    return path


def _insert(db, group_id, user_id, content, kind="PASSIVE"):
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind) VALUES (?, ?, ?, ?)",
        (str(group_id), str(user_id), content, kind),
    )
    conn.commit()
    conn.close()


def _evidence(content, *, message_id=1, author_id="1001", source_kind="PASSIVE",
              bot_id="", recipient_id="", conversation_key="test:group:1"):
    message = SummarySourceMessage(
        message_id=message_id,
        author_id=author_id,
        source_kind=source_kind,
        content=content,
        recipient_id=recipient_id,
    )
    return build_summary_evidence(conversation_key, bot_id, (message,))


def _packet(entry, *, low_id=0, watermark=1, source_count=1):
    return build_summary_packet(
        conversation_key=entry.conversation_key,
        bot_id=entry.bot_id,
        source_guard=(0, 0, low_id),
        source_low_id=low_id,
        source_high_id=watermark + 1,
        source_watermark=watermark,
        source_row_count=source_count,
        entries=(entry,),
    )


class _FakeBackend:
    """假 LLM 后端：记录收到的 prompt，返回预设结果或抛异常。"""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt, system_prompt=""):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        if self.result is not None:
            return self.result
        refs = [
            line.split(" ", 2)[1]
            for line in prompt.splitlines()
            if line.startswith("REF ref_")
        ]
        return json.dumps({"selected_refs": refs}, ensure_ascii=False)


# ── prompt 护栏 ────────────────────────────────────────


def test_prompt_contains_anti_fabrication_clauses():
    """防编造条款不得被删——压缩同样属于「宁可丢内容也不能编」的场景。"""
    prompt = compact.build_compact_prompt([_evidence("测试", message_id=1)])
    assert "不要输出摘要、事实、作者解释或新台词" in prompt
    assert "只表示 Bot 说过这些话" in prompt
    assert '"selected_refs"' in prompt


def test_prompt_preserves_own_speech_clause():
    """必须要求保留「我」的发言，否则 Bot 会忘记自己说过什么。

    归属修复计划 §6.4： wording 覆盖旧「我:」与新「作者=Bot(...)」两种
    渲染，且明确「回顾时写明对谁说的、不把自己的话归给用户」。
    """
    prompt = compact.build_compact_prompt([
        _evidence(
            "在吗",
            author_id="5000",
            source_kind="BOT_SELF",
            bot_id="5000",
            recipient_id="1001",
        )
    ])
    assert "author=Bot(5000)" in prompt
    assert '"recipient_id":"1001"' in prompt
    assert "不能拆分、改写或转交给" in prompt


def test_prompt_preserves_state_and_quoted_speech():
    """条件/否定/转述保持原样，不得升级成已发生事实（归属修复计划 §6.4）。"""
    prompt = compact.build_compact_prompt([
        _evidence("如果下次没有，只是听说角色扮演")
    ])
    assert "必须保留原文中的否定、条件、假设、玩笑、引用、疑问与角色扮演限定" in prompt
    for word in ("如果", "下次", "没有", "听说"):
        assert word in prompt
    assert "如果下次没有，只是听说角色扮演" in prompt


def test_prompt_offers_old_packet_refs_and_current_refs():
    """模型只从旧合法 packet 与当前来源行中选择 ID，不能写合并摘要。"""
    old = _evidence("旧来源行", message_id=1)
    current = _evidence("新来源行", message_id=2)
    prompt = compact.build_compact_prompt(
        [current], _packet(old, low_id=0, watermark=1)
    )
    assert old.ref_id in prompt and current.ref_id in prompt
    assert "旧来源行" in prompt and "新来源行" in prompt
    assert "不要输出摘要、事实" in prompt


def test_prompt_omits_block_without_existing():
    prompt = compact.build_compact_prompt([_evidence("当前来源", message_id=1)])
    assert "之前对更早内容的回顾" not in prompt
    assert "旧来源行" not in prompt


def test_prompt_has_no_leftover_placeholder():
    prompt = compact.build_compact_prompt([_evidence("内容", message_id=1)])
    assert "{existing}" not in prompt and "{messages}" not in prompt
    assert '{{"selected_refs"' not in prompt


# ── 待压缩区间 ────────────────────────────────────────


def test_fetch_excludes_both_ends(db):
    """区间左右开：不含已压缩的，也不含尾巴起点。"""
    for i in range(1, 6):
        _insert(db, 1, 1001, f"第{i}句")

    text, max_id, count = compact.fetch_pending_messages(1, 1, 5, limit=100)
    assert count == 3                        # id 2,3,4
    assert max_id == 4
    assert "第1句" not in text and "第5句" not in text
    assert "第2句" in text and "第4句" in text


def test_fetch_renders_bot_self_as_wo(db):
    _insert(db, 1, 1001, "用户的话")
    _insert(db, 9999, 9999, "占位", kind="PASSIVE")  # 别群，不应出现
    _insert(db, 1, 8888, "我的话", kind="BOT_SELF")

    text, _, _ = compact.fetch_pending_messages(1, 0, 999, limit=100)
    assert "用户(1001): 用户的话" in text
    assert "我: 我的话" in text
    assert "占位" not in text


def test_fetch_limit_advances_incrementally(db):
    """超过 limit 时只取最旧的一批，返回其末尾 id，余下留给下次。"""
    for i in range(1, 11):
        _insert(db, 1, 1001, f"第{i}句")

    text, max_id, count = compact.fetch_pending_messages(1, 0, 999, limit=4)
    assert count == 4 and max_id == 4
    assert "第5句" not in text


def test_fetch_skips_empty_content(db):
    _insert(db, 1, 1001, "有内容")
    _insert(db, 1, 1001, "   ")

    text, max_id, count = compact.fetch_pending_messages(1, 0, 999, limit=100)
    assert count == 1
    assert max_id == 2          # 位置仍推进到最后一条，避免空消息卡住区间
    assert text == "用户(1001): 有内容"


# ── G9/G10：v16 关系列同投影（归属修复计划 §6.4） ─────────────────────


def _insert_v16(db, user_id, content, kind="PASSIVE", *, msg_id=0, logical="",
                part=0, recipient="", origin=""):
    """往 v16 全列表插一行（带关系信封）。"""
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind,"
        " msg_id, conversation_key, bot_id, logical_message_id, part_index,"
        " origin_msg_id, reply_recipient_user_id, relation_version)"
        " VALUES ('1', ?, ?, ?, ?, 'qq:5000:group:1', '5000', ?, ?, ?, ?, 1)",
        (
            str(user_id), content, kind, msg_id or None, logical, part,
            origin, recipient,
        ),
    )
    conn.commit()
    conn.close()


def _make_v16_db(tmp_path):
    path = tmp_path / "compact_v16.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, "
        "content TEXT, source_kind TEXT DEFAULT 'PASSIVE', "
        "msg_id INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "conversation_key TEXT, bot_id TEXT, sender_display_name TEXT, "
        "reply_to_msg_id TEXT, reply_target_user_id TEXT, "
        "mentioned_user_ids_json TEXT DEFAULT '[]', "
        "logical_message_id TEXT, part_index INTEGER DEFAULT 0, "
        "origin_msg_id TEXT, reply_recipient_user_id TEXT, "
        "turn_id TEXT, relation_version INTEGER DEFAULT 0)"
    )
    conn.commit()
    conn.close()
    return path


def test_fetch_v16_groups_unit_with_recipient(tmp_path, monkeypatch):
    """带关系列：多气泡单元一行渲染，收件人显式；count 仍是原始行数。"""
    db = _make_v16_db(tmp_path)
    monkeypatch.setattr(compact, "DB_PATH", db)
    _insert_v16(db, 1001, "摸摸")
    _insert_v16(db, 5000, "诶？怎么啦", "BOT_SELF", msg_id=-558868042,
                logical="u1", part=0, recipient="1001", origin="-1337665775")
    _insert_v16(db, 5000, "不许摸我", "BOT_SELF", msg_id=-558868043,
                logical="u1", part=1, recipient="1001", origin="-1337665775")

    text, max_id, count = compact.fetch_pending_messages(1, 0, 999, limit=100)
    assert count == 3            # 原始非空行数，不因合组变 2
    assert max_id == 3
    unit = next(line for line in text.splitlines() if "作者=Bot(" in line)
    assert unit.startswith("[作者=Bot(5000); 回复给=用户(1001); 原输入=-1337665775]")
    assert "诶？怎么啦" in unit and "不许摸我" in unit  # 两气泡一行
    assert "[作者=用户(1001)] 说过: " in text


def test_fetch_v16_batch_split_keeps_each_segment_self_contained(tmp_path, monkeypatch):
    """批次切在逻辑单元中间：每段仍带完整作者/收件人，不越界推进。"""
    db = _make_v16_db(tmp_path)
    monkeypatch.setattr(compact, "DB_PATH", db)
    _insert_v16(db, 5000, "第一句", "BOT_SELF", msg_id=1,
                logical="u1", part=0, recipient="1001", origin="9")
    _insert_v16(db, 5000, "第二句", "BOT_SELF", msg_id=2,
                logical="u1", part=1, recipient="1001", origin="9")
    _insert_v16(db, 5000, "第三句", "BOT_SELF", msg_id=3,
                logical="u1", part=2, recipient="1001", origin="9")

    text1, max_id1, count1 = compact.fetch_pending_messages(1, 0, 999, limit=2)
    assert count1 == 2 and max_id1 == 2
    assert "第一句" in text1 and "第三句" not in text1
    # 切在前两泡：这一段仍是带收件人的自足行
    assert "回复给=用户(1001)" in text1

    text2, max_id2, count2 = compact.fetch_pending_messages(1, max_id1, 999, limit=2)
    assert count2 == 1 and max_id2 == 3
    assert "第三句" in text2
    assert "回复给=用户(1001)" in text2  # 收件人不靠上一批继承


def test_fetch_pending_records_seals_exact_author_target_and_full_text(tmp_path, monkeypatch):
    """新 packet ref 保留来源行、Bot 收件人和完整气泡原文。"""
    db = _make_v16_db(tmp_path)
    monkeypatch.setattr(compact, "DB_PATH", db)
    long_text = "条件与原文" * 500
    _insert_v16(db, 1001, "下次如果没有回应，只是引用", msg_id=11)
    _insert_v16(db, 5000, long_text, "BOT_SELF", msg_id=12,
                logical="bot-reply", part=0, recipient="1001", origin="-77")
    _insert_v16(db, 5000, "第二个气泡", "BOT_SELF", msg_id=13,
                logical="bot-reply", part=1, recipient="1001", origin="-77")

    batch = compact.fetch_pending_records(1, 0, 99, 100, (0, 0, 0))
    assert batch.conversation_key == "qq:5000:group:1"
    assert batch.bot_id == "5000"
    assert batch.source_row_count == 3
    assert batch.source_watermark == 3
    bot_entry = next(
        entry for entry in batch.entries if entry.messages[0].source_kind == "BOT_SELF"
    )
    assert len(bot_entry.messages) == 2
    assert bot_entry.messages[0].author_id == "5000"
    assert bot_entry.messages[0].recipient_id == "1001"
    assert bot_entry.messages[0].origin_msg_id == "-77"
    assert bot_entry.messages[0].content == long_text
    assert len(bot_entry.messages[0].content) == 2500
    rendered = compact.render_summary_evidence(bot_entry)
    assert long_text in rendered and "recipient_id" in rendered


def test_fetch_pending_records_extends_cut_to_complete_bot_unit(tmp_path, monkeypatch):
    """原始行 limit 落在多气泡 Bot 回复中间时，packet 仍取完整单元。"""
    db = _make_v16_db(tmp_path)
    monkeypatch.setattr(compact, "DB_PATH", db)
    for i in range(3):
        _insert_v16(db, 5000, f"第{i}个气泡", "BOT_SELF", msg_id=20 + i,
                    logical="complete-reply", part=i, recipient="1001", origin="-88")
    batch = compact.fetch_pending_records(1, 0, 99, 2, (0, 0, 0))
    assert batch.source_row_count == 3
    assert batch.source_watermark == 3
    assert len(batch.entries) == 1
    assert len(batch.entries[0].messages) == 3


def test_selection_parser_rejects_invalid_dual_or_repeated_refs():
    allowed = {"ref_good"}
    assert compact.parse_selected_refs('{"selected_refs":["ref_good"]}', allowed) == (
        "ref_good",
    )
    for invalid in (
        "无",
        '{"selected_refs":["ref_unknown"]}',
        '{"selected_refs":["ref_good","ref_good"]}',
        '{"selected_refs":[],"summary":"自由摘要"}',
        '{"selected_refs":[]} trailing prose',
        '{"selected_refs":["ref_good"],"selected_refs":[]}',
    ):
        with pytest.raises(ValueError):
            compact.parse_selected_refs(invalid, allowed)


def test_compact_invalid_ref_does_not_advance(db, monkeypatch):
    for i in range(1, 8):
        _insert(db, 1, 1001, f"原始发言{i}：如果下次没有确认")
    backend = _FakeBackend(result='{"selected_refs":["ref_unknown"]}')
    _setup_session(db, monkeypatch, backend)
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert sc.session_stats(1)["summarized_up_to_id"] == 1
    assert sc.session_stats(1)["compact_count"] == 0


def test_compact_second_protocol_failure_uses_complete_source_packet(db, monkeypatch):
    for i in range(1, 8):
        _insert(db, 1, 1001, f"完整来源行{i}：下次如果没有回应")
    backend = _FakeBackend(result='{"selected_refs":["ref_unknown"]}')
    _setup_session(db, monkeypatch, backend)

    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert sc.session_stats(1)["summarized_up_to_id"] == 1
    assert asyncio.run(compact.compact_once(1, 7)) is True
    summary = sc.get_summary(1)
    assert all(f"完整来源行{i}：下次如果没有回应" in summary for i in range(2, 7))
    assert sc.session_stats(1)["compact_count"] == 1
    assert sc.session_stats(1)["summarized_up_to_id"] == 6
    assert len(backend.prompts) == 2


def test_compact_pauses_when_minimum_packet_exceeds_budget(db, monkeypatch):
    for i in range(1, 8):
        _insert(db, 1, 1001, f"必须保留完整来源{i}")
    backend = _FakeBackend(result='{"selected_refs":["ref_unknown"]}')
    _setup_session(db, monkeypatch, backend)
    monkeypatch.setattr(compact, "SESSION_SUMMARY_MAX_TOKENS", 1)

    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert len(backend.prompts) == 2
    assert sc.session_stats(1)["summarized_up_to_id"] == 1
    assert sc.session_stats(1)["compact_count"] == 0


# ── compact_once 的四种结果 ───────────────────────────


def _setup_session(db, monkeypatch, backend, threshold=0):
    monkeypatch.setattr(sc, "SESSION_COMPACT_THRESHOLD_TOKENS", threshold)
    monkeypatch.setattr(compact, "_get_backend", lambda: backend)
    sc.ensure_initialized(1, 1)


def test_compact_applies_summary(db, monkeypatch):
    for i in range(1, 8):
        _insert(db, 1, 1001, f"这是第{i}句比较长的发言内容")
    backend = _FakeBackend()
    _setup_session(db, monkeypatch, backend)

    assert asyncio.run(compact.compact_once(1, 7)) is True
    summary = sc.get_summary(1)
    assert "这是第2句比较长的发言内容" in summary
    assert "这是第6句比较长的发言内容" in summary
    assert "大家在聊测试" not in summary
    assert sc.session_stats(1)["summarized_up_to_id"] == 6
    assert len(backend.prompts) == 1


def test_compact_skips_when_model_says_none(db, monkeypatch, summary_packet_factory):
    """模型判定无内容 → 推进位置、保留旧摘要（与失败区别对待）。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"哈哈哈哈哈{i}")
    backend = _FakeBackend(result='{"selected_refs":[]}')
    _setup_session(db, monkeypatch, backend)
    prior = summary_packet_factory(
        "先前的摘要",
        conversation_key="legacy:group:1",
        source_low_id=1,
        source_watermark=2,
    )
    sc.apply_summary(1, prior, up_to_id=2, message_count=1)
    previous_revision = sc.summary_revision(1)

    assert asyncio.run(compact.compact_once(1, 7)) is True
    assert "先前的摘要" in sc.get_summary(1)  # packet 未被覆盖
    assert sc.session_stats(1)["summarized_up_to_id"] == 6
    assert sc.summary_revision(1) == previous_revision
    assert sc.session_stats(1)["compact_count"] == 1


def test_compact_retries_after_llm_failure(db, monkeypatch):
    """调用失败 → 不推进位置，这批消息留待下次重试。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"这是第{i}句比较长的发言内容")
    backend = _FakeBackend(error=RuntimeError("服务不可用"))
    _setup_session(db, monkeypatch, backend)

    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert sc.session_stats(1)["summarized_up_to_id"] == 1
    assert sc.pending_bounds(1, 7) == (1, 7)


def test_compact_respects_token_threshold(db, monkeypatch):
    """未达阈值不调用 LLM。"""
    _insert(db, 1, 1001, "短")
    _insert(db, 1, 1001, "也短")
    _insert(db, 1, 1001, "还是短")
    backend = _FakeBackend()
    _setup_session(db, monkeypatch, backend, threshold=10000)

    assert asyncio.run(compact.compact_once(1, 3)) is False
    assert backend.prompts == []


def test_compact_noop_without_pending_range(db, monkeypatch):
    backend = _FakeBackend()
    monkeypatch.setattr(compact, "_get_backend", lambda: backend)
    # 未初始化会话 → 无待压缩区间
    assert asyncio.run(compact.compact_once(1, 100)) is False
    assert backend.prompts == []


def test_empty_result_variants():
    for text in ("", "  ", "无", "无。", "（无）", "None"):
        assert compact._is_empty_result(text), text
    # 正常回顾不得被误判为空
    for text in ("无法确定他的意思，大家在聊显卡", "大家在聊无人机"):
        assert not compact._is_empty_result(text), text


# ── T14：compact await 期间身份更正/重置 → CAS 拒绝提交（多人身份修复计划 §6.4） ──


class _GuardBumpBackend:
    """await 期间改变会话守卫状态的假后端（模拟并发身份更正/重置）。"""

    def __init__(self, result, mutate):
        self.result = result
        self.mutate = mutate

    async def generate(self, prompt, system_prompt=""):
        self.mutate()
        return self.result


def test_compact_discards_stale_result_on_identity_revision(db, monkeypatch):
    """await 期间 identity_revision 前进：旧摘要不提交、watermark 不推进。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"这是第{i}句比较长的发言内容")
    backend = _GuardBumpBackend(
        "还在用旧称呼的回顾", lambda: sc.observe_identity_revision(1, 5)
    )
    _setup_session(db, monkeypatch, backend)
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert sc.get_summary(1) == ""
    # watermark 停在初始化对齐点（1），绝未推进到压缩终点 6/7
    assert sc.session_stats(1)["summarized_up_to_id"] == 1


def test_compact_discards_stale_result_on_reset(db, monkeypatch):
    """await 期间会话重置（generation +1）：apply 与 skip 都被拒绝。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"这是第{i}句比较长的发言内容")
    backend = _GuardBumpBackend("无", lambda: sc.bump_reset_generation(1))
    _setup_session(db, monkeypatch, backend)
    assert asyncio.run(compact.compact_once(1, 7)) is False
    # 重置清空状态：摘要与位置都不存在旧值
    assert sc.get_summary(1) == ""
    assert sc.session_stats(1)["summarized_up_to_id"] == 0


def test_compact_skip_also_blocked_by_guard(db, monkeypatch):
    """skip_range 同样过 CAS：模型判「无」但守卫变化 → 位置不推进。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"哈哈哈哈哈{i}")
    backend = _GuardBumpBackend("无", lambda: sc.observe_identity_revision(1, 9))
    _setup_session(db, monkeypatch, backend)
    assert asyncio.run(compact.compact_once(1, 7)) is False
    assert sc.session_stats(1)["summarized_up_to_id"] == 1


def test_guard_recovers_next_round(db, monkeypatch):
    """守卫稳定后下一轮压缩正常提交（可重试语义）。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"这是第{i}句比较长的发言内容")
    state = {"round": 0}

    def mutate():
        state["round"] += 1
        if state["round"] == 1:
            sc.observe_identity_revision(1, 3)

    backend = _GuardBumpBackend("忽略的旧结果", mutate)
    _setup_session(db, monkeypatch, backend)
    assert asyncio.run(compact.compact_once(1, 7)) is False
    backend = _FakeBackend()
    monkeypatch.setattr(compact, "_get_backend", lambda: backend)
    assert asyncio.run(compact.compact_once(1, 7)) is True
    assert "这是第2句比较长的发言内容" in sc.get_summary(1)
