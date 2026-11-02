# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""回放隔离：临时 STELLA_HOME / 临时 DB + 生产模块 DB_PATH patch（可恢复）。

模式取自 ``scripts/eval_memory_replay.py``（M4 回放运行器）：
- 建表用 ``MemoryConsolidator.__new__(...)._ensure_common_tables`` +
  ``memory.pre_processors._GROUP_MESSAGES_V16_DDL``；
- 消息直接 INSERT（显式时间戳），``conversation_key`` 必须显式，否则快照与
  证据列不一致会在晋升期 verify 断链；
- ``capture=None`` 绕过 capture gate：本评测走真实整合/检索链路，capture gate
  只做可用性闸门（fail-closed 单例），绕过事实写入报告；
- 一个 session 恰好一批：patch 四个批次常量为 max(30, 最长会话消息数)，并
  ``consolidate_group(gid, force=True)``（对应生产「会话结束触发」路径）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_BATCH_SIZE = 30


def ensure_eval_home(workdir: Path) -> Path:
    """在任何 config/memory 导入**之前**调用：STELLA_HOME/DB_PATH 指向隔离目录。

    config.settings 在 import 时读环境变量（settings.py:354），因此本函数必须
    先于一切 ``import config``/``import memory`` 执行（``__main__`` 入口与测试
    conftest 均如此）。
    """
    home = workdir / "home"
    (home / "memory").mkdir(parents=True, exist_ok=True)
    import os

    os.environ["STELLA_HOME"] = str(home)
    os.environ["DB_PATH"] = str(home / "memory" / "agent_memory.db")
    return home


class _NoCompressor:
    def maybe_compress(self, reason: str = "") -> None:
        return None


class ReplayEnv:
    """单场景回放环境：隔离建库、消息插入、整合器装配、漏斗统计。"""

    def __init__(self, workdir: Path, scenario: dict[str, Any]):
        self.workdir = workdir
        self.scenario = scenario
        self.db_path = workdir / f"{scenario['scenario_id']}.db"
        self.thought_log_path = workdir / "thought_log.md"
        self.dia_to_row: dict[str, int] = {}
        self._patches: list[tuple[Any, str, Any]] = []
        self._setup_done = False

    # ── 生命周期 ──────────────────────────────────────────────
    def setup(self, *, batch_size: int | None = None) -> None:
        """建 schema、patch 隔离路径（可反复进入；恢复用 :meth:`close`）。"""
        import memory.consolidator as consolidator_mod
        import memory.memory_manager as memory_manager_mod
        import memory.post_processors as post_processors
        import memory.pre_processors as pre_processors
        import memory.retrieval_v2 as retrieval_v2
        import memory.retriever as retriever
        import memory.schema as schema_mod
        from memory.consolidator import MemoryConsolidator

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            MemoryConsolidator.__new__(MemoryConsolidator)._ensure_common_tables(conn)
            conn.execute(pre_processors._GROUP_MESSAGES_V16_DDL)
            conn.commit()
        finally:
            conn.close()

        sessions = self.scenario.get("sessions") or []
        effective_batch = batch_size or max(
            (len(s.get("messages") or []) for s in sessions), default=1
        )
        effective_batch = max(effective_batch, DEFAULT_BATCH_SIZE)
        for mod in (pre_processors, consolidator_mod, retriever, memory_manager_mod,
                    retrieval_v2, schema_mod):
            self._patch(mod, "DB_PATH", self.db_path)
        self._batch_attrs = (
            "CONSOLIDATION_LOCAL_BATCH_SIZE",
            "CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE",
            "CONSOLIDATION_ONLINE_BATCH_SIZE",
            "CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE",
        )
        self._batch_originals = {attr: getattr(consolidator_mod, attr)
                                 for attr in self._batch_attrs}
        self.set_batch_size(effective_batch)
        self._patch(post_processors, "THOUGHT_LOG_PATH", self.thought_log_path)
        self._patch(consolidator_mod, "append_consolidation_log", lambda entry: None)
        self._patch(memory_manager_mod, "get_compressor", lambda: _NoCompressor())
        self._setup_done = True

    def close(self) -> None:
        """恢复全部 patch（进程内多场景/测试复用时必须调用）。"""
        for mod, attr, old in reversed(self._patches):
            setattr(mod, attr, old)
        self._patches.clear()
        if getattr(self, "_batch_originals", None):
            import memory.consolidator as consolidator_mod

            for attr, old in self._batch_originals.items():
                setattr(consolidator_mod, attr, old)
            self._batch_originals = {}
        self._setup_done = False

    def set_batch_size(self, count: int) -> None:
        """把整合批次/阈值设为 ``count``。

        阈值检查对 force 同样生效（``new_count < _batch_size(force)`` 即跳过），
        逐会话回放必须让阈值恰好等于当前会话消息数，才能保证「一会话恰好一批」。
        """
        import memory.consolidator as consolidator_mod

        if not getattr(self, "_batch_originals", None):
            raise RuntimeError("ReplayEnv.setup() 未调用")
        for attr in self._batch_attrs:
            setattr(consolidator_mod, attr, max(1, int(count)))

    def _patch(self, module: Any, attr: str, value: Any) -> None:
        self._patches.append((module, attr, getattr(module, attr)))
        setattr(module, attr, value)

    @contextmanager
    def session(self, **setup_kwargs: Any) -> Iterator["ReplayEnv"]:
        self.setup(**setup_kwargs)
        try:
            yield self
        finally:
            self.close()

    # ── 数据写入 ──────────────────────────────────────────────
    def insert_sessions(self, sessions: list[dict[str, Any]]) -> int:
        """直接插入消息行（显式回填时间戳），记录 dia_id → row_id。"""
        from datetime import datetime, timedelta

        if not self._setup_done:
            raise RuntimeError("ReplayEnv.setup() 未调用")
        conversation_key = str(self.scenario["conversation_key"])
        bot_id = str(self.scenario.get("bot_id") or "stella-bench")
        gid = str(self.scenario["group_id"])
        inserted = 0
        conn = sqlite3.connect(self.db_path)
        try:
            for session in sessions:
                ts = datetime.strptime(str(session["ts"]), "%Y-%m-%d %H:%M:%S")
                for msg in session.get("messages") or []:
                    cur = conn.execute(
                        "INSERT INTO group_messages (group_id, user_id, content, source_kind, "
                        "timestamp, conversation_key, bot_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            gid,
                            str(msg["user_id"]),
                            str(msg.get("text") or ""),
                            "PASSIVE",
                            ts.strftime("%Y-%m-%d %H:%M:%S"),
                            conversation_key,
                            bot_id,
                        ),
                    )
                    row_id = int(cur.lastrowid or 0)
                    if msg.get("dia_id"):
                        self.dia_to_row[str(msg["dia_id"])] = row_id
                    ts += timedelta(seconds=1)
                    inserted += 1
            conn.commit()
        finally:
            conn.close()
        return inserted

    # ── 整合器装配 ────────────────────────────────────────────
    def build_consolidator(self, *, live: bool = False, fake_backend: Any = None) -> Any:
        """装配整合器：live 用生产 backend_for 角色；否则注入假后端（测试）。"""
        from memory.consolidator import MemoryConsolidator

        cons = MemoryConsolidator.__new__(MemoryConsolidator)
        if live:
            from core.llm.registry import ROLE_CONSOLIDATION, ROLE_EXTRACT, backend_for

            inner = backend_for(ROLE_CONSOLIDATION)
            if inner is None:
                raise RuntimeError("ROLE_CONSOLIDATION 无可用后端（检查 LLM_ENDPOINT_* 配置）")
            self.consolidation_backend = inner
            cons._backends = [("live", inner)]
            extract = backend_for(ROLE_EXTRACT)
            self.extract_backend = extract
            cons._extract_backend = (("live_extract", extract) if extract is not None else None)
        else:
            if fake_backend is None:
                raise ValueError("非 live 模式必须提供 fake_backend")
            self.consolidation_backend = fake_backend
            self.extract_backend = None
            cons._backends = [("fake", fake_backend)]
            cons._extract_backend = None
        return cons

    # ── 时间回填 ──────────────────────────────────────────────
    def backdate_new_rows(self, session_ts: str, wall_since: str) -> int:
        """把本会话整合新写入的记忆时间戳回填为会话时间。

        生产里记忆确认时间随真实时间自然展开；回放把数月压缩到小时级，
        若不回填，全部记忆的 last_confirmed_at 都挤在评测时刻，recency 权重
        与时间展示会系统性失真。只回填 wall_since 之后写入的行。

        注意只回填 ``memories``：``memory_candidates.first_seen_at`` 必须保持
        墙钟——晋升期 TTL 用 ``julianday('now')`` 与真实时间比较，回填会让
        全部候选被判「超期未获新证据」而 REJECTED（回放工件，非系统行为）。
        """
        if not self.db_path.exists():
            return 0
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE memories SET last_confirmed_at = ?, created_at = ?, updated_at = ? "
                "WHERE last_confirmed_at >= ?",
                (session_ts, session_ts, session_ts, wall_since),
            )
            touched = cur.rowcount
            conn.commit()
            return touched
        finally:
            conn.close()

    # ── 统计 ──────────────────────────────────────────────────
    def funnel(self) -> dict[str, Any]:
        """捕获漏斗：候选（按状态/按用户）与长期记忆（总数/active）。"""
        if not self.db_path.exists():
            return {"candidates_total": 0, "memories_total": 0}
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cand_by_status: dict[str, int] = {}
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM memory_candidates GROUP BY status"
            ):
                cand_by_status[str(row["status"] or "")] = int(row["n"])
            cand_by_user: dict[str, int] = {}
            for row in conn.execute(
                "SELECT user_id, COUNT(*) AS n FROM memory_candidates GROUP BY user_id"
            ):
                cand_by_user[str(row["user_id"] or "")] = int(row["n"])
            mem_total = int(
                (conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone() or {"n": 0})["n"]
            )
            mem_active = int(
                (
                    conn.execute(
                        "SELECT COUNT(*) AS n FROM memories WHERE status = 'active'"
                    ).fetchone()
                    or {"n": 0}
                )["n"]
            )
            return {
                "candidates_total": sum(cand_by_status.values()),
                "candidates_by_status": cand_by_status,
                "candidates_by_user": cand_by_user,
                "memories_total": mem_total,
                "memories_active": mem_active,
            }
        finally:
            conn.close()

    def table_contents(self) -> dict[str, list[str]]:
        """memories / memory_candidates 的 content 列表（写侧覆盖评估用）。"""
        out: dict[str, list[str]] = {"memories": [], "candidates": []}
        if not self.db_path.exists():
            return out
        conn = sqlite3.connect(self.db_path)
        try:
            out["memories"] = [
                str(r[0] or "")
                for r in conn.execute("SELECT content FROM memories WHERE status = 'active'")
            ]
            out["candidates"] = [
                str(r[0] or "") for r in conn.execute("SELECT content FROM memory_candidates")
            ]
        finally:
            conn.close()
        return out
