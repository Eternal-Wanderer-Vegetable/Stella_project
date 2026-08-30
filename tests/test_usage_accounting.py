# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""LLM 用量记账与每日预算的行为基线（不触网，不起 NoneBot）。

四组约束在这里守住：

1. **聚合与幂等**：同一 ``(date, role, slot, model)`` 反复记账走 UPSERT 累加，
   落盘两次不会把数字翻倍；重启（= 清内存后重新读表）今日累计不清零。
2. **预算判据**：临界（用满即拦）、``pause_memory`` 只停记忆域、``pause_all``
   连对话一起停、``warn_only`` 从不拦。
3. **关掉记账就是真的什么都不做**：不挂钩子、不建表、不写库。
4. **记账绝不能成为聊天链路的失败点**：库不存在 / 目录不可写时，
   ``record`` 与 ``budget_blocked`` 都不许抛异常。
"""
import asyncio
import sqlite3
from datetime import date, timedelta

import pytest

import core.llm.usage_sink as usage_sink
import core.llm.usage_store as store
from core.llm.registry import (
    KIND_LOCAL,
    KIND_ONLINE,
    ROLE_CHAT,
    ROLE_COMPACT,
    ROLE_CONSOLIDATION,
    ROLE_EXTRACT,
    ROLE_PLUGIN,
    ROLE_ROUTER,
)


@pytest.fixture(autouse=True)
def _clean():
    store.reset_state()
    usage_sink.reset_state()
    yield
    store.reset_state()
    usage_sink.reset_state()


@pytest.fixture
def db(tmp_path, monkeypatch):
    """一个只有 llm_usage_daily 表的库——记账与记忆系统完全隔离，不需要别的表。"""
    path = tmp_path / "usage.db"
    from memory.schema import create_llm_usage_daily_table

    conn = sqlite3.connect(path)
    create_llm_usage_daily_table(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(store, "DB_PATH", path)
    return path


def _budget(monkeypatch, **kw):
    """把预算相关配置整组塞进一个假 settings（monkeypatch 的落点是 _settings）。"""
    values = {
        "LLM_USAGE_ACCOUNTING": True,
        "LLM_DAILY_TOKEN_BUDGET": 0,
        "LLM_BUDGET_SCOPE": store.SCOPE_ONLINE,
        "LLM_BUDGET_EXHAUSTED_ACTION": store.ACTION_PAUSE_MEMORY,
    }
    values.update(kw)
    fake = type("S", (), values)
    monkeypatch.setattr(store, "_settings", lambda: fake)
    return fake


def _record(role=ROLE_CONSOLIDATION, slot="ONLINE_MEMORY", model="m", kind=KIND_ONLINE,
            prompt=100, completion=20, cached=0, finish="stop", ok=True):
    return usage_sink.record(
        role=role,
        slot=slot,
        model=model,
        kind=kind,
        usage={
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "prompt_cache_hit_tokens": cached,
        },
        finish_reason=finish,
        ok=ok,
    )


def _rows(path):
    conn = sqlite3.connect(path)
    rows = conn.execute(
        "SELECT date, role, slot, model, kind, calls, failures, truncated, "
        "prompt_tokens, completion_tokens, cached_tokens FROM llm_usage_daily "
        "ORDER BY role, slot, model"
    ).fetchall()
    conn.close()
    return rows


# ── 聚合与落盘 ────────────────────────────────────────────


def test_records_aggregate_into_one_row(db, monkeypatch):
    """同一 (date, role, slot, model) 的多次调用聚成一行，计数逐项累加。"""
    _budget(monkeypatch)
    store.install()
    _record(prompt=100, completion=20, cached=60)
    _record(prompt=200, completion=30, cached=140)
    assert store.flush() == 1

    rows = _rows(db)
    assert len(rows) == 1
    _, role, slot, model, kind, calls, failures, truncated, pt, ct, cached = rows[0]
    assert (role, slot, model, kind) == (ROLE_CONSOLIDATION, "ONLINE_MEMORY", "m", KIND_ONLINE)
    assert (calls, failures, truncated) == (2, 0, 0)
    assert (pt, ct, cached) == (300, 50, 200)


def test_failures_and_truncation_counted_separately(db, monkeypatch):
    """失败与截断各自单独计数——截断是「配置太紧」的信号，不是调用失败。"""
    _budget(monkeypatch)
    store.install()
    _record(ok=False)
    _record(finish="length")
    _record()
    store.flush()

    _, _, _, _, _, calls, failures, truncated, _, _, _ = _rows(db)[0]
    assert (calls, failures, truncated) == (3, 1, 1)


def test_flush_is_idempotent(db, monkeypatch):
    """落盘两次不会把数字翻倍：写完即清 pending，第二次无事可做。"""
    _budget(monkeypatch)
    store.install()
    _record(prompt=100, completion=20)
    assert store.flush() == 1
    assert store.flush() == 0
    assert _rows(db)[0][8:] == (100, 20, 0)


def test_upsert_accumulates_across_flushes(db, monkeypatch):
    """跨两次落盘走 ON CONFLICT DO UPDATE 累加，而不是覆盖成第二批的值。"""
    _budget(monkeypatch)
    store.install()
    _record(prompt=100, completion=20)
    store.flush()
    _record(prompt=5, completion=1)
    store.flush()

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][5] == 2  # calls
    assert rows[0][8:] == (105, 21, 0)


def test_distinct_keys_stay_separate(db, monkeypatch):
    """角色 / 槽 / 模型任一不同就是不同的一行——成本要能按这三维拆开看。"""
    _budget(monkeypatch)
    store.install()
    _record(role=ROLE_CONSOLIDATION, slot="ONLINE_MEMORY", model="a")
    _record(role=ROLE_EXTRACT, slot="ONLINE_MEMORY", model="a")
    _record(role=ROLE_EXTRACT, slot="LOCAL", model="a", kind=KIND_LOCAL)
    _record(role=ROLE_EXTRACT, slot="LOCAL", model="b", kind=KIND_LOCAL)
    store.flush()
    assert len(_rows(db)) == 4


def test_empty_model_does_not_split_rows(db, monkeypatch):
    """回归：模型名为空必须落成 '-' 而不是 NULL。

    SQLite 允许非 INTEGER 主键列存 NULL，且 NULL 之间比较**不相等**——
    真存了 NULL，每次都会插出一行新记录，UPSERT 去重彻底失效。
    """
    _budget(monkeypatch)
    store.install()
    _record(model="")
    _record(model="")
    store.flush()

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][3] == "-"
    assert rows[0][5] == 2


def test_totals_survive_restart(db, monkeypatch):
    """重启不清零：清掉内存后今日累计从表里读回，预算因此不会被反复重置。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=1000)
    store.install()
    _record(prompt=400, completion=100)
    store.flush()
    assert store.today_tokens() == 500

    # 模拟进程重启：内存态清空，配置与库都还在
    store.reset_state()
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=1000)
    assert store.today_tokens() == 500


def test_yesterday_does_not_count_toward_today(db, monkeypatch):
    """日期键翻滚：昨天的用量留在表里可查，但不算进今天的预算。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=1000)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO llm_usage_daily (date, role, slot, model, kind, calls, "
        "prompt_tokens, completion_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (yesterday, ROLE_CONSOLIDATION, "ONLINE_MEMORY", "m", KIND_ONLINE, 1, 900, 90),
    )
    conn.commit()
    conn.close()

    store.install()
    assert store.today_tokens() == 0
    assert store.budget_blocked(ROLE_CONSOLIDATION) is None


def test_retention_prunes_old_days(db, monkeypatch):
    """超过保留天数的日账在读回时顺手清掉，库不会无限长。"""
    _budget(monkeypatch)
    old = (date.today() - timedelta(days=store.RETENTION_DAYS + 1)).isoformat()
    keep = (date.today() - timedelta(days=store.RETENTION_DAYS - 1)).isoformat()
    conn = sqlite3.connect(db)
    conn.executemany(
        "INSERT INTO llm_usage_daily (date, role, slot, model, kind) VALUES (?, ?, ?, ?, ?)",
        [(old, ROLE_CHAT, "LOCAL", "m", KIND_LOCAL), (keep, ROLE_CHAT, "LOCAL", "m", KIND_LOCAL)],
    )
    conn.commit()
    conn.close()

    store.install()
    remaining = {r[0] for r in _rows(db)}
    assert old not in remaining
    assert keep in remaining


# ── 预算判据 ──────────────────────────────────────────────


def _spend(tokens, kind=KIND_ONLINE):
    """记一笔指定 token 数的用量（只改内存，不需要库）。"""
    _record(prompt=tokens, completion=0, kind=kind)


def test_zero_budget_never_blocks(db, monkeypatch):
    """LLM_DAILY_TOKEN_BUDGET=0 是「不限」，用多少都不拦。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=0)
    store.install()
    _spend(10**9)
    for role in (ROLE_CHAT, ROLE_CONSOLIDATION, ROLE_COMPACT, ROLE_EXTRACT):
        assert store.budget_blocked(role) is None


def test_blocks_exactly_at_budget(db, monkeypatch):
    """临界语义：用满即拦（used >= budget），差一个 token 就放行。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100)
    store.install()
    _spend(99)
    assert store.budget_blocked(ROLE_CONSOLIDATION) is None
    _spend(1)
    assert store.budget_blocked(ROLE_CONSOLIDATION)


def test_pause_memory_spares_the_chat_path(db, monkeypatch):
    """默认动作只停记忆域三个角色——「超额之后群里照常能说话」是 P3 的验收标准。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100,
            LLM_BUDGET_EXHAUSTED_ACTION=store.ACTION_PAUSE_MEMORY)
    store.install()
    _spend(500)

    for role in (ROLE_CONSOLIDATION, ROLE_COMPACT, ROLE_EXTRACT):
        assert store.budget_blocked(role), f"{role} 应被拦下"
    for role in (ROLE_CHAT, ROLE_ROUTER, ROLE_PLUGIN):
        assert store.budget_blocked(role) is None, f"{role} 不该被拦"
    assert set(store.paused_roles()) == set(store.MEMORY_ROLES)


def test_pause_all_stops_every_role(db, monkeypatch):
    """pause_all 是用户显式选的硬停：一分钱都别再花，对话也停。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100,
            LLM_BUDGET_EXHAUSTED_ACTION=store.ACTION_PAUSE_ALL)
    store.install()
    _spend(500)
    for role in (ROLE_CHAT, ROLE_ROUTER, ROLE_PLUGIN, ROLE_CONSOLIDATION,
                 ROLE_COMPACT, ROLE_EXTRACT):
        assert store.budget_blocked(role), f"{role} 应被拦下"


def test_warn_only_never_blocks(db, monkeypatch):
    """warn_only 只告警：任何角色都放行，超额也一样。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100,
            LLM_BUDGET_EXHAUSTED_ACTION=store.ACTION_WARN_ONLY)
    store.install()
    _spend(500)
    for role in (ROLE_CHAT, ROLE_CONSOLIDATION, ROLE_COMPACT, ROLE_EXTRACT):
        assert store.budget_blocked(role) is None


def test_unknown_action_falls_back_to_pause_memory(db, monkeypatch):
    """认不出的动作值按最保守的 pause_memory 处理，而不是当成「不限」。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100,
            LLM_BUDGET_EXHAUSTED_ACTION="随便写点什么")
    store.install()
    _spend(500)
    assert store.exhausted_action() == store.ACTION_PAUSE_MEMORY
    assert store.budget_blocked(ROLE_CONSOLIDATION)
    assert store.budget_blocked(ROLE_CHAT) is None


def test_scope_online_ignores_local_usage(db, monkeypatch):
    """域=online 时本地端点的用量不进预算——本地模型不花钱。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100, LLM_BUDGET_SCOPE=store.SCOPE_ONLINE)
    store.install()
    _spend(500, kind=KIND_LOCAL)
    assert store.today_tokens() == 0
    assert store.budget_blocked(ROLE_CONSOLIDATION) is None


def test_scope_all_counts_local_usage(db, monkeypatch):
    """域=all 时本地也算——那时它是「算力预算」而不是账单预算。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=100, LLM_BUDGET_SCOPE=store.SCOPE_ALL)
    store.install()
    _spend(500, kind=KIND_LOCAL)
    assert store.today_tokens() == 500
    assert store.budget_blocked(ROLE_CONSOLIDATION)


def test_unknown_scope_falls_back_to_online(db, monkeypatch):
    _budget(monkeypatch, LLM_BUDGET_SCOPE="whatever")
    assert store.budget_scope() == store.SCOPE_ONLINE


# ── 关掉记账 = 真的什么都不做 ──────────────────────────────


def test_accounting_off_writes_nothing(tmp_path, monkeypatch):
    """关掉记账时连库文件都不该被创建，更不该建表。

    「关掉」必须是真的什么都不做，而不是照样写库只是不给看。
    """
    path = tmp_path / "never.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    _budget(monkeypatch, LLM_USAGE_ACCOUNTING=False)

    assert store.install() is False
    _record()
    assert store.flush() == 0
    assert not path.exists()


def test_accounting_off_disables_budget(db, monkeypatch):
    """没有用量数据，预算就无从判断——等于把预算一起关掉（配置注释里写明了）。"""
    _budget(monkeypatch, LLM_USAGE_ACCOUNTING=False, LLM_DAILY_TOKEN_BUDGET=1)
    assert store.budget_blocked(ROLE_CONSOLIDATION) is None
    assert store.usage_snapshot() == {"accounting": False}


def test_install_unhooks_when_turned_off(db, monkeypatch):
    """运行中把开关关掉再 install()，钩子要被摘掉，不能继续偷偷记。"""
    _budget(monkeypatch)
    assert store.install() is True
    assert usage_sink._sink is not None

    _budget(monkeypatch, LLM_USAGE_ACCOUNTING=False)
    assert store.install() is False
    assert usage_sink._sink is None


# ── 记账绝不能成为聊天链路的失败点 ──────────────────────────


def test_record_survives_missing_database(tmp_path, monkeypatch):
    """库路径完全不可用时，记账既不抛异常也不影响调用方拿到 UsageRecord。"""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "no" / "such" / "dir" / "x.db")
    _budget(monkeypatch)
    store.install()

    rec = _record(prompt=10, completion=2)
    assert rec.total_tokens == 12
    assert store.flush() == 0  # 写不进去，但不抛
    # 内存累计仍然对——预算判据即便没有库也能工作
    assert store.today_tokens() == 12


def test_budget_blocked_survives_broken_settings(db, monkeypatch):
    """配置值是垃圾（预算写成非数字）时按「不限」处理，不抛异常。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET="不是数字")
    store.install()
    assert store.daily_budget() == 0
    assert store.budget_blocked(ROLE_CONSOLIDATION) is None


def test_flush_retries_the_same_batch_after_failure(db, monkeypatch):
    """写库失败只丢这一次落盘机会，增量仍留在 pending 里等下次重试。"""
    _budget(monkeypatch)
    store.install()
    _record(prompt=100, completion=20)

    monkeypatch.setattr(store, "DB_PATH", db.parent / "gone" / "x.db")
    assert store.flush() == 0

    monkeypatch.setattr(store, "DB_PATH", db)
    assert store.flush() == 1
    assert _rows(db)[0][8:] == (100, 20, 0)


# ── 快照（status_api 会把它整块塞进响应体） ─────────────────


def test_snapshot_reports_cache_hit_rate_over_input_tokens(db, monkeypatch):
    """命中率的分母是输入 token 而不是调用次数。

    一次长请求命中一半、与两次短请求各命中全部，省下来的钱完全不同；
    按调用次数算会把这两种情况报成同一个数。缓存命中率是验证前缀缓存
    到底有没有生效的唯一手段，所以这个分母必须守住。
    """
    _budget(monkeypatch)
    store.install()
    _record(prompt=1000, completion=10, cached=250)

    snap = store.usage_snapshot()
    key = f"{ROLE_CONSOLIDATION}@ONLINE_MEMORY:m"
    assert snap["by_key"][key]["cache_hit_rate"] == 0.25
    assert snap["totals"]["cache_hit_rate"] == 0.25


def test_snapshot_has_no_credentials_or_chat_content(db, monkeypatch):
    """响应体只许有计数与比率：绝不含 prompt / 模型输出 / base_url / key。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=1000)
    store.install()
    _record(prompt=100, completion=20, cached=50)

    snap = store.usage_snapshot()
    assert snap["budget"] == 1000
    assert snap["used_tokens"] == 120
    assert snap["remaining_tokens"] == 880
    assert snap["over_budget"] is False

    flat = repr(snap)
    for banned in ("api_key", "base_url", "http://", "https://", "prompt_text", "Bearer"):
        assert banned not in flat
    allowed = {
        "role", "slot", "model", "kind", "calls", "failures", "truncated",
        "prompt_tokens", "completion_tokens", "cached_tokens", "cache_hit_rate",
    }
    for entry in snap["by_key"].values():
        assert set(entry) == allowed


def test_snapshot_remaining_is_none_when_unlimited(db, monkeypatch):
    """不限预算时余量是 None（而不是 0）——面板要能区分「不限」与「已用尽」。"""
    _budget(monkeypatch, LLM_DAILY_TOKEN_BUDGET=0)
    store.install()
    _record()
    snap = store.usage_snapshot()
    assert snap["remaining_tokens"] is None
    assert snap["over_budget"] is False
    assert snap["paused_roles"] == []


# ── 预算在各域入口真的生效（而且跳过 ≠ 丢弃） ───────────────


def _exhaust(monkeypatch, action=None):
    """把预算配成「已经撞破」的状态，并记一笔在线用量把它花掉。"""
    _budget(
        monkeypatch,
        LLM_DAILY_TOKEN_BUDGET=100,
        LLM_BUDGET_EXHAUSTED_ACTION=action or store.ACTION_PAUSE_MEMORY,
    )
    store.install()
    _spend(500)


def test_consolidation_skip_does_not_advance_checkpoint(tmp_path, monkeypatch):
    """整合被预算拦下时**只 return，绝不推进 checkpoint**。

    跳过 = 攒批，不是丢弃。推进了 checkpoint 这批消息就永远没人整合了
    （P0-4「消息永久丢失」的另一种形态）。
    """
    import memory.consolidator as consolidator
    from memory.consolidator import MemoryConsolidator

    usage_db = tmp_path / "usage.db"
    from memory.schema import create_llm_usage_daily_table

    conn = sqlite3.connect(usage_db)
    create_llm_usage_daily_table(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(store, "DB_PATH", usage_db)
    _exhaust(monkeypatch)

    db_path = tmp_path / "agent_memory.db"
    monkeypatch.setattr(consolidator, "DB_PATH", db_path)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    cons = MemoryConsolidator.__new__(MemoryConsolidator)
    conn = sqlite3.connect(db_path)
    cons._ensure_common_tables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT,"
        "timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.executemany(
        "INSERT INTO group_messages (group_id, user_id, content) VALUES (?, ?, ?)",
        [("2001", "111", f"m{i}") for i in range(200)],
    )
    conn.commit()
    conn.close()

    called = []
    monkeypatch.setattr(
        MemoryConsolidator, "_generate", lambda *a, **k: called.append(1)
    )

    asyncio.run(cons.consolidate_group(2001))

    assert called == [], "预算拦下之后不该再调 LLM"
    assert cons._get_last_processed_id(2001) == 0, "跳过路径推进了 checkpoint，消息会永久丢失"


def test_compact_skip_returns_false_without_calling_llm(tmp_path, monkeypatch):
    """会话压缩被预算拦下时返回 False（= 未推进压缩位置），且不调 LLM。"""
    from memory import session_compact as compact

    usage_db = tmp_path / "usage.db"
    from memory.schema import create_llm_usage_daily_table

    conn = sqlite3.connect(usage_db)
    create_llm_usage_daily_table(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(store, "DB_PATH", usage_db)
    _exhaust(monkeypatch)

    def _boom():
        raise AssertionError("预算拦下之后不该取用后端")

    monkeypatch.setattr(compact, "_get_backend", _boom)
    assert asyncio.run(compact.compact_once(3001, 0)) is False


def test_extract_skip_falls_back_to_stage_one_candidates(tmp_path, monkeypatch):
    """阶段2 被预算拦下时返回 None，即「回退阶段1 候选」而不是「确实没有候选」。"""
    import memory.consolidator as consolidator
    from memory.consolidator import MemoryConsolidator

    usage_db = tmp_path / "usage.db"
    from memory.schema import create_llm_usage_daily_table

    conn = sqlite3.connect(usage_db)
    create_llm_usage_daily_table(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(store, "DB_PATH", usage_db)
    monkeypatch.setattr(consolidator, "append_consolidation_log", lambda entry: None)
    _exhaust(monkeypatch)

    cons = MemoryConsolidator.__new__(MemoryConsolidator)
    # 后端故意留成「会炸的东西」：被预算拦下就根本不该走到取用后端那一步
    cons._extract_backend = ("boom", None)  # type: ignore[assignment]
    assert asyncio.run(cons._extract_candidates(4001, "用户(1): 我在北京工作")) is None
