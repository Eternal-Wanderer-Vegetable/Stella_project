# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 用量落库与每日预算。

:mod:`core.llm.usage_sink` 只在内存里聚合，进程重启即清零；本模块把它接到
``llm_usage_daily`` 表上，并在此之上提供**每日 token 预算**的判据。

三条设计约束：

- **记账绝不能成为聊天链路的失败点。** sink 回调里不做同步写库：每次调用只改内存
  计数，攒到阈值或超过间隔才 UPSERT 落盘一次。整条路径吞异常（``usage_sink.record``
  已经兜了一层，这里再兜一层，写库失败只丢统计、不影响调用）。
- **预算重启不失效。** 今日累计在首次用到时从表里读回。用**本地时区的日期键**而不是
  计时器：计时器会因为重启而重新计时，「每日」就变成了「每次启动后 24 小时」。
- **超额默认只停记忆域，对话照常可用。** 判据是 :func:`budget_blocked`，由各域入口
  显式调用；不塞进 ``backend_for()``——那里有实例缓存，且被大量测试 monkeypatch。

为什么放在 ``core/llm/`` 而不是 ``memory/``：``memory/embeddings.py`` 已经反向
import ``core.llm``，模块级的 ``core.llm → memory`` 会成环。表的 DDL 仍然只有
``memory/schema.py`` 一份（单一真源），本模块在函数内部惰性 import 它。
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from config import DB_PATH
from core.llm import usage_sink
from core.llm.registry import (
    KIND_ONLINE,
    ROLE_COMPACT,
    ROLE_CONSOLIDATION,
    ROLE_EXTRACT,
)

# 记忆域的三个角色。``pause_memory`` 只停这三个——它们是「高频、低难度、可以等」的
# 后台任务；对话不在其中，所以超额之后群里照常能说话。
MEMORY_ROLES = frozenset({ROLE_CONSOLIDATION, ROLE_COMPACT, ROLE_EXTRACT})

# 超额动作
ACTION_PAUSE_MEMORY = "pause_memory"
ACTION_PAUSE_ALL = "pause_all"
ACTION_WARN_ONLY = "warn_only"
_ACTIONS = (ACTION_PAUSE_MEMORY, ACTION_PAUSE_ALL, ACTION_WARN_ONLY)

# 预算域
SCOPE_ONLINE = "online"
SCOPE_ALL = "all"

# 日账保留天数。写死不给配置项：这张表一天最多几十行，90 天不到三千行，
# 没有需要用户调的理由；真要长期留存应该导出，而不是让库无限长。
RETENTION_DAYS = 90

# 落盘节流：攒够这么多条待写记录，或距上次落盘超过这么久，才写一次。
_FLUSH_EVERY_ROWS = 16
_FLUSH_EVERY_SECONDS = 60.0


@dataclass
class _Row:
    """一天里「某角色打在某端点某模型上」的累计。"""

    kind: str = ""
    calls: int = 0
    failures: int = 0
    truncated: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, other: _Row) -> None:
        self.kind = other.kind or self.kind
        self.calls += other.calls
        self.failures += other.failures
        self.truncated += other.truncated
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cached_tokens += other.cached_tokens


# (date, role, slot, model) → 今日权威累计（含已落盘的部分，启动时从表里读回）
_totals: dict[tuple[str, str, str, str], _Row] = {}
# (date, role, slot, model) → 尚未落盘的增量。落盘走 UPSERT 累加，写完即清空。
_pending: dict[tuple[str, str, str, str], _Row] = {}

_loaded_date: str = ""
_last_flush: float = 0.0
_warned_date: str = ""
_installed = False


def _settings() -> Any:
    """读 ``config.settings`` 的属性而不是 ``from config import X``。

    与 ``registry._settings`` 同一个理由：``from config import X`` 在导入时把值
    绑死，测试 monkeypatch 配置就不生效了。
    """
    from config import settings

    return settings


def _date_key(when: date | None = None) -> str:
    """本地时区的 ``YYYY-MM-DD``。跨天靠日期变化自然翻滚，不用计时器。"""
    return (when or date.today()).isoformat()


# ---------- 配置读取 ----------


def accounting_enabled() -> bool:
    return bool(getattr(_settings(), "LLM_USAGE_ACCOUNTING", True))


def daily_budget() -> int:
    """每日 token 预算；``<= 0`` 表示不限。"""
    try:
        return max(0, int(getattr(_settings(), "LLM_DAILY_TOKEN_BUDGET", 0) or 0))
    except (TypeError, ValueError):
        return 0


def budget_scope() -> str:
    """预算算哪些端点：``online``（默认）只算在线，``all`` 全算。"""
    scope = str(getattr(_settings(), "LLM_BUDGET_SCOPE", SCOPE_ONLINE) or "").strip().lower()
    return scope if scope in (SCOPE_ONLINE, SCOPE_ALL) else SCOPE_ONLINE


def exhausted_action() -> str:
    """超额动作；认不出的值按最保守的 ``pause_memory`` 处理。"""
    action = (
        str(getattr(_settings(), "LLM_BUDGET_EXHAUSTED_ACTION", ACTION_PAUSE_MEMORY) or "")
        .strip()
        .lower()
    )
    return action if action in _ACTIONS else ACTION_PAUSE_MEMORY


# ---------- 落库 ----------


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    from memory.schema import create_llm_usage_daily_table

    create_llm_usage_daily_table(conn)
    return conn


def _load_today() -> None:
    """把今日已落盘的累计读回内存，并顺手清掉过期日账。

    重启不清零预算的关键一步：不读回的话，重启就等于把当天的花费忘掉，
    ``LLM_DAILY_TOKEN_BUDGET`` 会被反复重置。
    """
    global _loaded_date, _last_flush
    today = _date_key()
    # 只保留今天的键：昨天的累计对预算无意义，留着白占内存
    for key in [k for k in _totals if k[0] != today]:
        _totals.pop(key, None)
    _loaded_date = today
    # 节流窗口从「记账开始」起算。留在 0.0 的话 monotonic() - 0.0 恒大于间隔，
    # 于是**第一次**调用就会同步写一次库——正是热路径上不该发生的事。
    _last_flush = time.monotonic()
    try:
        conn = _connect()
    except Exception:
        return
    try:
        rows = conn.execute(
            "SELECT date, role, slot, model, kind, calls, failures, truncated, "
            "prompt_tokens, completion_tokens, cached_tokens "
            "FROM llm_usage_daily WHERE date = ?",
            (today,),
        ).fetchall()
        for d, role, slot, model, kind, calls, fails, trunc, pt, ct, cached in rows:
            _totals[(d, role, slot, model)] = _Row(
                kind=kind or "",
                calls=int(calls or 0),
                failures=int(fails or 0),
                truncated=int(trunc or 0),
                prompt_tokens=int(pt or 0),
                completion_tokens=int(ct or 0),
                cached_tokens=int(cached or 0),
            )
        cutoff = _date_key(date.today() - timedelta(days=RETENTION_DAYS))
        conn.execute("DELETE FROM llm_usage_daily WHERE date < ?", (cutoff,))
        conn.commit()
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def _ensure_loaded() -> None:
    """首次使用（或跨天之后）把今日累计对齐到库里的值。"""
    if _loaded_date != _date_key():
        _load_today()


def flush(*, force: bool = True) -> int:
    """把待写增量 UPSERT 落盘，返回写入的行数。**不抛异常。**

    参数:
        force: False 时受节流约束（攒够行数或超过间隔才真写），供热路径调用。
    """
    global _last_flush
    if not _pending:
        return 0
    if not force:
        stale = (time.monotonic() - _last_flush) >= _FLUSH_EVERY_SECONDS
        if len(_pending) < _FLUSH_EVERY_ROWS and not stale:
            return 0
    batch = list(_pending.items())
    try:
        conn = _connect()
    except Exception:
        return 0
    written = 0
    try:
        conn.executemany(
            """
            INSERT INTO llm_usage_daily
                (date, role, slot, model, kind, calls, failures, truncated,
                 prompt_tokens, completion_tokens, cached_tokens, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(date, role, slot, model) DO UPDATE SET
                kind = excluded.kind,
                calls = calls + excluded.calls,
                failures = failures + excluded.failures,
                truncated = truncated + excluded.truncated,
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens,
                cached_tokens = cached_tokens + excluded.cached_tokens,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    d,
                    role,
                    slot,
                    model,
                    row.kind,
                    row.calls,
                    row.failures,
                    row.truncated,
                    row.prompt_tokens,
                    row.completion_tokens,
                    row.cached_tokens,
                )
                for (d, role, slot, model), row in batch
            ],
        )
        conn.commit()
        written = len(batch)
        # 只清真正写出去的那批：落盘期间可能又有新记录进来
        for key, row in batch:
            staged = _pending.get(key)
            if staged is None:
                continue
            if staged is row:
                _pending.pop(key, None)
            else:  # 期间又累加过 → 减掉已写的部分
                staged.calls -= row.calls
                staged.failures -= row.failures
                staged.truncated -= row.truncated
                staged.prompt_tokens -= row.prompt_tokens
                staged.completion_tokens -= row.completion_tokens
                staged.cached_tokens -= row.cached_tokens
        _last_flush = time.monotonic()
    except Exception:
        # 写库失败只丢统计，绝不影响调用方。下次 flush 会带着同一批重试。
        pass
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    return written


def _on_record(rec: usage_sink.UsageRecord) -> None:
    """``usage_sink`` 的下游钩子。**只改内存 + 节流落盘，不做别的。**"""
    if not accounting_enabled():
        return
    _ensure_loaded()
    key = (_date_key(), rec.role or "-", rec.slot or "-", rec.model or "-")
    delta = _Row(
        kind=rec.kind or "",
        calls=1,
        failures=0 if rec.ok else 1,
        truncated=1 if rec.truncated else 0,
        prompt_tokens=rec.prompt_tokens,
        completion_tokens=rec.completion_tokens,
        cached_tokens=rec.cached_tokens,
    )
    _totals.setdefault(key, _Row(kind=delta.kind)).add(delta)
    _pending.setdefault(key, _Row(kind=delta.kind)).add(delta)
    flush(force=False)


def install() -> bool:
    """把本模块挂到 ``usage_sink`` 上。返回是否真的挂上了。

    ``LLM_USAGE_ACCOUNTING=false`` 时不挂钩子、一次也不碰数据库——
    「关掉记账」必须是真的什么都不做，而不是照样写库只是不给看。
    """
    global _installed
    if not accounting_enabled():
        if _installed:
            usage_sink.set_sink(None)
            _installed = False
        return False
    _ensure_loaded()
    usage_sink.set_sink(_on_record)
    _installed = True
    return True


# ---------- 预算 ----------


def today_tokens(scope: str | None = None) -> int:
    """今日预算域内的 token 总数（输入 + 输出）。"""
    _ensure_loaded()
    scope = scope or budget_scope()
    today = _date_key()
    return sum(
        row.total_tokens
        for key, row in _totals.items()
        if key[0] == today and (scope == SCOPE_ALL or row.kind == KIND_ONLINE)
    )


def budget_blocked(role: str) -> str | None:
    """该角色现在是否被预算拦住；拦住时返回可直接写进日志的原因。

    返回 None 表示放行。以下情形一律放行：

    - 关掉了记账（没有用量数据，预算无从判断——等于关掉预算）；
    - ``LLM_DAILY_TOKEN_BUDGET <= 0``（不限）；
    - 今日用量还没到预算；
    - 动作是 ``warn_only``（只告警，从不拦）；
    - 动作是 ``pause_memory`` 且该角色不属于记忆域（对话/路由/插件照常）。
    """
    global _warned_date
    if not accounting_enabled():
        return None
    budget = daily_budget()
    if budget <= 0:
        return None
    scope = budget_scope()
    used = today_tokens(scope)
    if used < budget:
        return None
    action = exhausted_action()
    detail = f"今日 token 用量 {used}/{budget}（域={scope}）"
    if action == ACTION_WARN_ONLY:
        today = _date_key()
        if _warned_date != today:
            _warned_date = today
            try:
                from nonebot import logger

                logger.warning(f"⚠️ [Budget] {detail}，已超预算（warn_only：不拦任何调用）")
            except Exception:
                pass
        return None
    if action == ACTION_PAUSE_MEMORY and role not in MEMORY_ROLES:
        return None
    return f"{detail}，动作={action}"


def paused_roles() -> list[str]:
    """当前被预算拦住的角色名，供 GUI / doctor 展示。"""
    from core.llm.registry import ROLES

    return [r for r in ROLES if budget_blocked(r)]


# ---------- 快照 ----------


def usage_snapshot() -> dict:
    """今日用量快照。**只含计数与比率，绝不含 prompt / 模型输出 / 凭据。**

    ``status_api`` 会把它整块塞进响应体，所以这里的每个字段都必须是能公开的数字。
    """
    if not accounting_enabled():
        return {"accounting": False}
    _ensure_loaded()
    today = _date_key()
    by_key: dict[str, dict] = {}
    agg = _Row()
    scope = budget_scope()
    for (d, role, slot, model), row in sorted(_totals.items()):
        if d != today:
            continue
        by_key[f"{role}@{slot}:{model}"] = {
            "role": role,
            "slot": slot,
            "model": model,
            "kind": row.kind,
            "calls": row.calls,
            "failures": row.failures,
            "truncated": row.truncated,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "cached_tokens": row.cached_tokens,
            # 分母是输入 token 而不是调用次数：一次长请求命中一半与两次短请求
            # 各命中全部，省下来的钱完全不同。
            "cache_hit_rate": (row.cached_tokens / row.prompt_tokens)
            if row.prompt_tokens
            else 0.0,
        }
        agg.add(row)
    budget = daily_budget()
    used = today_tokens(scope)
    return {
        "accounting": True,
        "date": today,
        "budget": budget,
        "scope": scope,
        "action": exhausted_action(),
        "used_tokens": used,
        "remaining_tokens": max(0, budget - used) if budget > 0 else None,
        "over_budget": budget > 0 and used >= budget,
        "paused_roles": paused_roles(),
        "totals": {
            "calls": agg.calls,
            "failures": agg.failures,
            "truncated": agg.truncated,
            "prompt_tokens": agg.prompt_tokens,
            "completion_tokens": agg.completion_tokens,
            "cached_tokens": agg.cached_tokens,
            "cache_hit_rate": (agg.cached_tokens / agg.prompt_tokens)
            if agg.prompt_tokens
            else 0.0,
        },
        "by_key": by_key,
    }


def reset_state() -> None:
    """清空内存态并卸载钩子（测试用）。不动库里的数据。"""
    global _loaded_date, _last_flush, _warned_date, _installed
    _totals.clear()
    _pending.clear()
    _loaded_date = ""
    _last_flush = 0.0
    _warned_date = ""
    if _installed:
        usage_sink.set_sink(None)
        _installed = False


__all__ = [
    "ACTION_PAUSE_ALL",
    "ACTION_PAUSE_MEMORY",
    "ACTION_WARN_ONLY",
    "MEMORY_ROLES",
    "RETENTION_DAYS",
    "SCOPE_ALL",
    "SCOPE_ONLINE",
    "accounting_enabled",
    "budget_blocked",
    "budget_scope",
    "daily_budget",
    "exhausted_action",
    "flush",
    "install",
    "paused_roles",
    "reset_state",
    "today_tokens",
    "usage_snapshot",
]
