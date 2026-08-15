# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话压缩执行侧的行为基线（不触网，LLM 后端被替换为假实现）。

重点覆盖三件事：压缩 prompt 的防编造条款、待压缩区间的边界正确性、
以及「调用失败」与「模型判定无内容」两种空结果的区别处理。
"""
import asyncio
import sqlite3

import pytest

from memory import session_compact as compact
from memory import session_context as sc


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


class _FakeBackend:
    """假 LLM 后端：记录收到的 prompt，返回预设结果或抛异常。"""

    def __init__(self, result="这是一段回顾", error=None):
        self.result = result
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt, system_prompt=""):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.result


# ── prompt 护栏 ────────────────────────────────────────


def test_prompt_contains_anti_fabrication_clauses():
    """防编造条款不得被删——压缩同样属于「宁可丢内容也不能编」的场景。"""
    prompt = compact.build_compact_prompt("用户(1001): 测试")
    assert "严禁编造对话中没有出现过的内容" in prompt
    assert "只输出一个字：无" in prompt
    assert "不要推断任何人的动机或心理状态" in prompt


def test_prompt_preserves_own_speech_clause():
    """必须要求保留「我」的发言，否则 Bot 会忘记自己说过什么。"""
    assert "标注「我」的是你自己说过的话" in compact.build_compact_prompt("我: 在吗")


def test_prompt_merges_existing_summary():
    """存在旧摘要时要求合并成一段，避免摘要无限累积。"""
    prompt = compact.build_compact_prompt("用户(1001): 新内容", existing_summary="旧的回顾")
    assert "旧的回顾" in prompt
    assert "合并成一段" in prompt


def test_prompt_omits_block_without_existing():
    assert "之前对更早内容的回顾" not in compact.build_compact_prompt("用户(1001): 内容")


def test_prompt_has_no_leftover_placeholder():
    prompt = compact.build_compact_prompt("用户(1001): 内容", existing_summary="旧")
    assert "{" not in prompt and "}" not in prompt


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


# ── compact_once 的四种结果 ───────────────────────────


def _setup_session(db, monkeypatch, backend, threshold=0):
    monkeypatch.setattr(sc, "SESSION_COMPACT_THRESHOLD_TOKENS", threshold)
    monkeypatch.setattr(compact, "_get_backend", lambda: backend)
    sc.ensure_initialized(1, 1)


def test_compact_applies_summary(db, monkeypatch):
    for i in range(1, 8):
        _insert(db, 1, 1001, f"这是第{i}句比较长的发言内容")
    backend = _FakeBackend(result="大家在聊测试")
    _setup_session(db, monkeypatch, backend)

    assert asyncio.run(compact.compact_once(1, 7)) is True
    assert sc.get_summary(1) == "大家在聊测试"
    assert sc.session_stats(1)["summarized_up_to_id"] == 6
    assert len(backend.prompts) == 1


def test_compact_skips_when_model_says_none(db, monkeypatch):
    """模型判定无内容 → 推进位置、保留旧摘要（与失败区别对待）。"""
    for i in range(1, 8):
        _insert(db, 1, 1001, f"哈哈哈哈哈{i}")
    backend = _FakeBackend(result="无")
    _setup_session(db, monkeypatch, backend)
    sc.apply_summary(1, "先前的摘要", up_to_id=1)

    assert asyncio.run(compact.compact_once(1, 7)) is True
    assert sc.get_summary(1) == "先前的摘要"          # 摘要未被覆盖
    assert sc.session_stats(1)["summarized_up_to_id"] == 6   # 位置已推进


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
