# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""`last_accessed_at` / `last_confirmed_at` 两个时间戳的语义护栏。

守的是 design_docs/bug_report/bug_report_2026_8_31#1.md §4.e：`last_accessed_at`
的名字说「最后一次被用到」，但检索路径从不刷新它——只有候选强化与压缩合并会写。
于是它实际是「最后一次被确认」，与 `last_confirmed_at` 恒等，两件事被同一个列
表达，「老但仍被频繁调用的记忆更有价值」这条排序意图落空。

2026-08-31 的修法是把两个语义拆开：

- `last_accessed_at` = 真正进了 Prompt（`retrieval_v2._touch_accessed`）；
- `last_confirmed_at` = 有新证据（候选强化 / 压缩合并）。

拆开之后所有「新鲜度」读取方都必须改看 `last_confirmed_at`，否则会出现反向
效应：取用一次就把衰减时钟重置，越被反复引用的记忆越不会过期。本文件的每组
用例都成对断言——既钉住「该刷的刷了」，也钉住「不该被刷影响的没被影响」。
"""

import sqlite3
from pathlib import Path

import pytest

import memory.compressor as compressor
import memory.retrieval_v2 as retrieval_v2

# 用例里区分「很久以前」与「刚刚」的两个锚点。取足够大的间隔，避免与
# MEMORY_ARCHIVE_INACTIVE_DAYS / MEMORY_DECAY_DAYS 的具体取值贴太近。
_LONG_AGO = "2020-01-01 00:00:00"


def _v2_db(db_path: Path) -> None:
    """建一张规范 memories 表（直接用生产 DDL，避免与 schema 漂移）。"""
    conn = sqlite3.connect(db_path)
    from memory import schema

    schema.create_memories_table(conn)
    conn.commit()
    conn.close()


def _insert(
    db_path: Path,
    mid: str,
    content: str,
    *,
    usage: str = '["TOPIC_CONTINUE"]',
    visibility: str = "OPEN",
    owner: str = "100",
    mem_type: str = "PREFERENCE",
    importance: float = 0.8,
    confirmed_at: str | None = _LONG_AGO,
    accessed_at: str | None = _LONG_AGO,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content, importance, "
        "confidence, status, confirmation_count, usage_tags, visibility, "
        "last_confirmed_at, last_accessed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 0.9, 'active', 1, ?, ?, ?, ?)",
        # 空间标识刻意用非纯数字：schema 迁移会把看起来像 QQ 群号的
        # group_shared_space 当成旧的 group_id 重写成 legacy_<gid>，
        # 用 "1" 的话凡是构造过 MemoryManager 的用例都会查不到自己刚插的行。
        (mid, "space_1", owner, mem_type, content, importance, usage, visibility,
         confirmed_at, accessed_at),
    )
    conn.commit()
    conn.close()


def _timestamps(db_path: Path, mid: str) -> tuple[str | None, str | None]:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT last_accessed_at, last_confirmed_at FROM memories WHERE id = ?", (mid,)
    ).fetchone()
    conn.close()
    return (row[0], row[1]) if row else (None, None)


@pytest.fixture
def v2_env(tmp_path, monkeypatch):
    """一个可跑 retrieve_memories 的临时库；每个用例都清掉检索缓存。

    _CACHE 是模块级 dict，key 里虽然带了 DB_PATH，但用例之间共享同一个对象，
    不清的话「第二次检索命中缓存」这类断言会被上一个用例的残留干扰。
    """
    db_path = tmp_path / "agent_memory.db"
    _v2_db(db_path)
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db_path)
    monkeypatch.setattr(retrieval_v2, "MEMORY_V2_ENABLED", True)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    retrieval_v2._CACHE.clear()
    yield db_path
    retrieval_v2._CACHE.clear()


# ── 1. 检索侧：进了 Prompt 才算「被访问」 ──────────────────────


def test_retrieval_touches_accessed_at_for_returned_memories(v2_env):
    """真正进了 Prompt 的记忆，last_accessed_at 必须被刷新。

    这是本次修改的正向目标：在此之前检索路径一次也不写这个列。
    """
    _insert(v2_env, "m_hit", "用户喜欢玩合作类游戏")

    result = retrieval_v2.retrieve_memories("space_1", 100, "一起玩游戏吧", trigger="reply")
    assert "m_hit" in [m["id"] for m in result.conversation_memories], "前置条件不成立"

    accessed, confirmed = _timestamps(v2_env, "m_hit")
    assert accessed != _LONG_AGO, "进了 Prompt 却没记账"
    assert confirmed == _LONG_AGO, "检索不是新证据，不许动 last_confirmed_at"


def test_retrieval_does_not_touch_filtered_out_memories(v2_env):
    """被 Visibility / Usage 挡在 Prompt 外的记忆不得记账。

    反向断言：不加这条，把 _touch_accessed 写成「刷新整个候选池」也能过上一个
    用例——而那样一来「有没有人用得上它」就退化成「有没有被查出来过」，
    _archive_low_value_memories 会永远归档不掉任何东西。
    """
    _insert(v2_env, "m_hit", "用户喜欢玩合作类游戏")
    _insert(
        v2_env,
        "m_boundary",
        "用户不喜欢未经允许摸头",
        usage='["BOUNDARY_PROTECTION"]',
        visibility="RESTRICTED",
    )

    result = retrieval_v2.retrieve_memories("space_1", 100, "一起玩游戏吧", trigger="reply")
    returned = {m["id"] for m in result.conversation_memories} | {
        m["id"] for m in result.behavior_constraints
    }
    assert "m_boundary" not in returned, "前置条件不成立：CASUAL_REPLY 应挡掉它"

    assert _timestamps(v2_env, "m_hit")[0] != _LONG_AGO
    assert _timestamps(v2_env, "m_boundary")[0] == _LONG_AGO


def test_behavior_constraints_also_count_as_accessed(v2_env):
    """行为约束分区同样算「被用到」——两个分区都进了 Prompt。"""
    _insert(
        v2_env,
        "m_boundary",
        "用户不喜欢未经允许摸头",
        usage='["BOUNDARY_PROTECTION"]',
        visibility="RESTRICTED",
        owner="235",
    )

    result = retrieval_v2.retrieve_memories(
        "space_1", 235, "你别开这种玩笑，我不喜欢别人这样碰我", trigger="reply"
    )
    assert "m_boundary" in [m["id"] for m in result.behavior_constraints], "前置条件不成立"
    assert _timestamps(v2_env, "m_boundary")[0] != _LONG_AGO


def test_cache_hit_does_not_re_touch(v2_env, monkeypatch):
    """命中 5 分钟缓存的那次 return 不重复记账。

    不是省一次写库那么简单：缓存命中期内每句话都刷一次的话，一次对话就能把
    访问时间钉在「现在」，而归档判定是天粒度的，这个精度毫无意义。
    """
    _insert(v2_env, "m_hit", "用户喜欢玩合作类游戏")

    retrieval_v2.retrieve_memories("space_1", 100, "一起玩游戏吧", trigger="reply")
    first = _timestamps(v2_env, "m_hit")[0]

    calls: list[list[str]] = []
    monkeypatch.setattr(retrieval_v2, "_touch_accessed", lambda ids: calls.append(ids))
    retrieval_v2.retrieve_memories("space_1", 100, "一起玩游戏吧", trigger="reply")

    assert calls == [], "缓存命中不该再记账"
    assert _timestamps(v2_env, "m_hit")[0] == first


def test_touch_accessed_ignores_empty_and_survives_missing_ids(v2_env):
    """空列表直接返回；不存在的 id 不得抛异常（记账失败不能拖垮检索）。"""
    retrieval_v2._touch_accessed([])
    retrieval_v2._touch_accessed(["no_such_memory"])


# ── 2. 排序侧：新鲜度看证据，不看引用 ────────────────────────


def test_ranking_freshness_prefers_confirmed_over_accessed():
    """排序读 last_confirmed_at；被刷新的 last_accessed_at 不得把旧事实顶上来。

    这是「富者愈富」的反例：m_stale 刚被取用过（last_accessed_at 是现在），但它
    最后一次被证实是 2020 年；m_fresh 上周才被确认过。新鲜度维度必须判 m_fresh 更新。
    """
    from memory.policy import _mem_timestamp

    stale = {"last_confirmed_at": _LONG_AGO, "last_accessed_at": "2026-08-31 12:00:00"}
    fresh = {"last_confirmed_at": "2026-08-24 12:00:00", "last_accessed_at": _LONG_AGO}

    assert _mem_timestamp(fresh) > _mem_timestamp(stale)


def test_ranking_falls_back_to_accessed_for_legacy_rows():
    """反向断言：只有 last_accessed_at 的旧库/夹具行仍要拿到一个可用的时间戳。

    只测「优先 last_confirmed_at」的话，把回退链砍成单键也能通过——而那样一来
    未回填 last_confirmed_at 的存量行会全部落到 time.time()，一律被当成「刚刚」。
    """
    from memory.policy import _mem_timestamp

    legacy = {"last_accessed_at": _LONG_AGO, "created_at": "2026-08-30 12:00:00"}
    assert _mem_timestamp(legacy) == pytest.approx(
        _mem_timestamp({"last_confirmed_at": _LONG_AGO})
    )


def test_quota_score_recency_is_driven_by_access():
    """配额竞争的 recency 项**刻意**读 last_accessed_at——它问的是「还有人用吗」。

    与排序侧相反：淘汰谁的时候，「老但仍被频繁调用」确实比「新却从未被用过」
    更该留下。这条意图在检索开始记账后才真正成立。
    """
    from memory.memory_manager import MemoryManager

    used = MemoryManager._quota_score(0.5, 1, "2026-08-31 12:00:00")
    never_used = MemoryManager._quota_score(0.5, 1, None)
    long_unused = MemoryManager._quota_score(0.5, 1, _LONG_AGO)

    assert used > long_unused >= never_used


# ── 3. 压缩侧：衰减看证据，归档看引用 ────────────────────────


def _now_shifted(days_ago: float) -> str:
    """生成一个「距今 days_ago 天」的 SQLite 时间串（UTC，与 CURRENT_TIMESTAMP 同基准）。"""
    from datetime import datetime, timedelta, timezone

    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def compressor_env(tmp_path, monkeypatch):
    """一个只含 memories 表的临时库 + 不写日志的压缩器。"""
    db_path = tmp_path / "compress.db"
    _v2_db(db_path)
    monkeypatch.setattr(compressor, "DB_PATH", db_path)
    monkeypatch.setattr(compressor, "MEMORY_COMPRESS_LOG_PATH", tmp_path / "log.md")
    monkeypatch.setattr(compressor.MemoryCompressor, "_append_log", lambda self, text: None)
    return db_path


def _status(db_path: Path, mid: str) -> str:
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT status FROM memories WHERE id = ?", (mid,)).fetchone()
    conn.close()
    return str(row[0]) if row else ""


def test_decay_archives_expired_memory_even_if_just_retrieved(compressor_env):
    """过了类型生命周期的记忆，即使刚被检索取用过也照样归档。

    反向就是这次修改要堵的漏洞：拿 last_accessed_at 当衰减时钟的话，一条 EVENT
    只要每周被取用一次就能无限续命，类型生命周期形同虚设。
    """
    from config import MEMORY_DECAY_DAYS

    over_ttl = _now_shifted(MEMORY_DECAY_DAYS["EVENT"] + 5)
    _insert(
        compressor_env,
        "m_expired",
        "上周听到地震预警",
        mem_type="EVENT",
        confirmed_at=over_ttl,
        accessed_at=_now_shifted(0),  # 刚刚才进过 Prompt
    )

    conn = sqlite3.connect(compressor_env)
    archived = compressor.MemoryCompressor()._apply_decay(conn.cursor())
    conn.commit()
    conn.close()

    assert archived == 1
    assert _status(compressor_env, "m_expired") == "archived"


def test_decay_spares_recently_confirmed_memory(compressor_env):
    """反向断言：类型生命周期内、近期有新证据的记忆不得被衰减掉。

    只测「该归档的归档了」的话，把判据写成永真（或直接归档全表）也能通过。
    """
    from config import MEMORY_DECAY_DAYS

    _insert(
        compressor_env,
        "m_alive",
        "本周又提到听到地震预警",
        mem_type="EVENT",
        confirmed_at=_now_shifted(MEMORY_DECAY_DAYS["EVENT"] / 2),
        accessed_at=_LONG_AGO,  # 从没被取用过，但证据是新的
    )

    conn = sqlite3.connect(compressor_env)
    archived = compressor.MemoryCompressor()._apply_decay(conn.cursor())
    conn.commit()
    conn.close()

    assert archived == 0
    assert _status(compressor_env, "m_alive") == "active"


def test_low_value_archive_spares_recently_accessed(compressor_env):
    """低价值归档问的是「还有人用得上吗」，所以刚被取用过的要留下。

    这条与上面的衰减刚好相反，是两个时间戳各管一件事的直接体现：证据早就不新了，
    但只要还在被引用，就说明它对当下的对话有用。
    """
    from config import MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD, MEMORY_ARCHIVE_INACTIVE_DAYS

    low = max(0.0, MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD - 0.1)
    _insert(
        compressor_env,
        "m_used",
        "用户偶尔提到爱喝冰美式",
        mem_type="FACT",
        importance=low,
        confirmed_at=_LONG_AGO,
        accessed_at=_now_shifted(0),
    )
    _insert(
        compressor_env,
        "m_unused",
        "用户偶尔提到爱喝热可可",
        mem_type="FACT",
        importance=low,
        confirmed_at=_LONG_AGO,
        accessed_at=_now_shifted(MEMORY_ARCHIVE_INACTIVE_DAYS + 5),
    )

    conn = sqlite3.connect(compressor_env)
    archived = compressor.MemoryCompressor()._archive_low_value_memories(conn.cursor())
    conn.commit()
    conn.close()

    assert archived == 1
    assert _status(compressor_env, "m_used") == "active"
    assert _status(compressor_env, "m_unused") == "archived"


# ── 4. 写入侧：确认不等于访问 ────────────────────────────────


def test_candidate_reinforcement_bumps_confirmed_only(compressor_env, monkeypatch):
    """候选强化并入已有记忆：刷 last_confirmed_at，不动 last_accessed_at。

    这是新证据，不是「这条记忆被用到了」。一并刷 last_accessed_at 会让配额竞争的
    recency 项与 confirmation 项重复计同一个信号，并让低价值归档永远不成立。
    """
    from memory.memory_manager import MemoryManager

    monkeypatch.setattr("memory.memory_manager.DB_PATH", compressor_env)
    _insert(compressor_env, "m_old", "住在南方", mem_type="FACT")

    conn = sqlite3.connect(compressor_env)
    MemoryManager()._merge_into_memory(
        conn.cursor(),
        "m_old",
        {
            "group_shared_space": "space_1",
            "user_id": "100",
            "type": "FACT",
            "content": "住在南方，家里种甘蔗",
            "importance": 0.6,
            "confidence": 0.9,
            "usage_tags": '["ANSWER_CONTEXT"]',
            "visibility": "OPEN",
        },
    )
    conn.commit()
    conn.close()

    accessed, confirmed = _timestamps(compressor_env, "m_old")
    assert confirmed != _LONG_AGO, "合并是新证据，必须刷确认时间"
    assert accessed == _LONG_AGO, "合并不是访问，不许刷 last_accessed_at"


def test_compressor_merge_bumps_confirmed_only(compressor_env):
    """去重合并同理：存活方的确认时间前移，访问时间保持原样。"""
    # id 命名让 ORDER BY id 下 m_1_keep 排在前面 → 它是存活方，m_2_dup 被归档
    _insert(compressor_env, "m_1_keep", "居住地附近主要种植甘蔗", mem_type="FACT")
    _insert(compressor_env, "m_2_dup", "居住地附近主要种植甘蔗树", mem_type="FACT")

    conn = sqlite3.connect(compressor_env)
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT id, group_shared_space, user_id, type, content, importance, confidence, "
        "confirmation_count, compressed_at, is_atomized FROM memories "
        "WHERE status = 'active' ORDER BY id"
    ).fetchall()
    archived = compressor.MemoryCompressor()._merge_duplicate_memories(cursor, rows)
    conn.commit()
    conn.close()

    assert archived == 1, "前置条件不成立：这两条应被判为相似"
    assert _status(compressor_env, "m_2_dup") == "archived"
    accessed, confirmed = _timestamps(compressor_env, "m_1_keep")
    assert confirmed != _LONG_AGO
    assert accessed == _LONG_AGO


def test_similar_memory_lookup_orders_by_confirmed(compressor_env, monkeypatch):
    """新证据并入哪一条：按证据新鲜度选，而不是按「最近被引用过」。

    否则最近被取用过的那条会持续吸收所有新证据，另一条永远停在旧内容上。
    """
    from memory.memory_manager import MemoryManager

    monkeypatch.setattr("memory.memory_manager.DB_PATH", compressor_env)
    # m_referenced 刚被检索取用过但证据很旧；m_confirmed 反之
    _insert(
        compressor_env, "m_referenced", "居住地附近主要种植甘蔗", mem_type="FACT",
        confirmed_at=_LONG_AGO, accessed_at=_now_shifted(0),
    )
    _insert(
        compressor_env, "m_confirmed", "居住地附近主要种植甘蔗树", mem_type="FACT",
        confirmed_at=_now_shifted(1), accessed_at=_LONG_AGO,
    )

    conn = sqlite3.connect(compressor_env)
    found = MemoryManager()._find_similar_memory(
        conn.cursor(),
        {
            "group_shared_space": "space_1",
            "user_id": "100",
            "type": "FACT",
            "content": "居住地附近主要种植甘蔗",
        },
    )
    conn.close()

    assert found == "m_confirmed"


def test_freshness_ordering_tolerates_null_confirmed(compressor_env):
    """存量行 last_confirmed_at 为 NULL 时，COALESCE 必须回退到 last_accessed_at。

    反向断言：把排序表达式写成裸 last_confirmed_at 的话，未回填的旧行会全部
    排到 NULL 组里（SQLite 的 NULL 在 DESC 下垫底），在轻量压缩的 LIMIT 截断中
    被系统性地漏掉——不报错，只是永远不被处理。
    """
    _insert(compressor_env, "m_legacy", "旧库行", confirmed_at=None,
            accessed_at=_now_shifted(0))
    _insert(compressor_env, "m_new", "新行", confirmed_at=_now_shifted(10),
            accessed_at=_LONG_AGO)

    conn = sqlite3.connect(compressor_env)
    ordered = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM memories WHERE status = 'active' "
            f"ORDER BY {compressor._FRESHNESS} DESC"
        ).fetchall()
    ]
    conn.close()

    assert ordered == ["m_legacy", "m_new"]
