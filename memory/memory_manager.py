# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
记忆经理（MemoryManager）模块。

本模块位于记忆工作流的“晋升侧”：消费整合器写入的 memory_candidates 候选，
按置信度/重要度打分决定进入「观察(OBSERVING)」等待进一步证据，还是立即晋升为长期记忆
（memories 表 + FTS 同步索引），并与已有相似记忆合并。

典型调用链（示例）：
    Consolidator 写出记忆候选 → process_new_candidates()
    → 低分候选标记为 OBSERVING（等待后续更多证据）
    → 高分候选：相似合并（_merge_into_memory）或新建（_create_memory）
    → 晋升批次提交后异步触发轻量压缩（避免 SQLite 写事务锁冲突）
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import uuid

from nonebot import logger
from typing_extensions import Self

from config import (
    DB_PATH,
    MEMORY_CANDIDATE_MAX_OBSERVING_DAYS,
    MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE,
    MEMORY_CONFIRM_HIGH_CONFIDENCE,
    MEMORY_OBSERVE_LOW_CONFIDENCE,
    MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT,
    MEMORY_PROMOTE_MIN_IMPORTANCE,
    MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE,
    MEMORY_QUOTA_CONFIRMATION_CAP,
    MEMORY_QUOTA_ENFORCE,
    MEMORY_QUOTA_W_CONFIRMATION,
    MEMORY_QUOTA_W_IMPORTANCE,
    MEMORY_QUOTA_W_RECENCY,
    MEMORY_USER_QUOTA,
    RAG_ENABLED,
    RAG_SQLITE_FTS_ENABLED,
)
from memory.cache_keys import bump_memory_history
from memory.compressor import get_compressor
from memory.retriever import _upsert_fts_record
from memory.schema import (
    create_atomic_facts_table,
    create_memories_table,
    create_memory_candidates_table,
    ensure_v2_schema,
)
from memory.text_similarity import is_similar, merge_content, same_normalized_text

# ── 晋升流程观测探针（计划 §6.3 memory.promotion.*；M2）────────────────
# 旁路纪律（最高优先级）：ctx 为 None（观测未接入）或任何观测异常都不影响
# 晋升业务；探针绝不进入业务事务/锁——flow 事件与 entity_history 都走
# message_flow 有界 writer 队列（put_nowait），与业务连接无关。
# metrics 只记 id / 计数 / 阈值 / 数值，不记候选正文（计划 §6.1 隐私）。


class _NoopSpan:
    """空转 span：观测通道故障时保证 with 与显式 finish() 都安全。"""

    def finish(self, **kw) -> None:
        pass

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _probe_span(ctx, node_id: str, **kw):
    """开观测 span；ctx=None 时 message_flow.span 自带空转实现，异常降级 _NoopSpan。"""
    if ctx is None:
        return _NoopSpan()
    try:
        from core.observability import message_flow

        return message_flow.span(ctx, node_id, **kw)
    except Exception:
        return _NoopSpan()


def _probe_decision(ctx, node_id: str, **kw) -> None:
    """决策点探针：全量 fail-open，绝不抛。"""
    if ctx is None:
        return
    try:
        from core.observability import message_flow

        message_flow.decision(ctx, node_id, **kw)
    except Exception:
        pass


def _probe_checkpoint(ctx, node_id: str, **kw) -> None:
    """过程事实探针：全量 fail-open，绝不抛。"""
    if ctx is None:
        return
    try:
        from core.observability import message_flow

        message_flow.checkpoint(ctx, node_id, **kw)
    except Exception:
        pass


def _gate_reason_code(reason: str) -> str:
    """Gate 1 原因文案 → 稳定 reason_code（决策事实可按码聚合，计划 §6.3）。"""
    if "重要度不足" in reason:
        return "importance_below_min"
    if "高置信" in reason:
        return "high_confidence"
    if "AT_MENTION" in reason:
        return "at_mention_single_shot"
    if "交叉验证" in reason:
        return "occurrence_threshold"
    if "证据不足" in reason:
        return "insufficient_evidence"
    if "置信度不足" in reason:
        return "low_confidence"
    return "other"


class MemoryManager:
    """记忆候选晋升为长期记忆的管理器。

    职责：
    - 读取 memory_candidates 中 NEW / OBSERVING 状态的候选；
    - 依据 Gate 1 三档（置信度 × 证据充分度）决定候选取向（观察 / 晋升 / 超期淘汰）；
    - 晋升时与已有相似记忆合并，避免重复记忆堆积；
    - 维护 memories 表与 FTS 全文索引的同步（_upsert_fts_record）。
    - 维护每用户记忆配额（MEMORY_USER_QUOTA）：超额时竞争性淘汰最弱记忆。
    """

    def __init__(self):
        # 对象履历缓冲：本批次业务事务内的状态写入先攒在这里，等
        # conn.commit() 成功后再统一落账（_flush_history，计划 §6.1）；
        # 提交失败即随事务丢弃——回滚了的写入不能留下「已发生」的履历。
        self._history_buffer: list[tuple[str, str, str, str, str, dict]] = []
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        """打开默认 SQLite 连接（DB_PATH）。"""
        return sqlite3.connect(DB_PATH)

    def _ensure_tables(self) -> None:
        """确保记忆相关表存在：memory_candidates（候选）、memories（长期记忆）、
        atomic_facts（原子事实，备用），并创建常用检索索引。

        v8 起统一复用 schema 规范 DDL（group_shared_space 归属），
        不再手抄一份建表语句。
        """
        conn = self._connect()
        cursor = conn.cursor()
        create_memory_candidates_table(conn)
        create_memories_table(conn)
        create_atomic_facts_table(conn)
        # 常用检索索引（memories 按空间维度）
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_space_user_status
            ON memories (group_shared_space, user_id, status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_space_status_accessed
            ON memories (group_shared_space, status, last_accessed_at)
        """)
        conn.commit()
        conn.close()
        # v2 记忆系统：基础表建好后，增量迁移补新字段/索引（幂等）
        with contextlib.suppress(Exception):
            ensure_v2_schema(DB_PATH)

    def process_new_candidates(self, *, flow_ctx=None) -> None:
        """Process candidates with the configured backend.

        Python remains the default. Rust is only asked to handle the bounded
        database transaction; the Python gate and post-commit hooks stay here.

        ``flow_ctx``（计划 §6.3 memory.promotion.batch，M2）：调用方已有父 trace
        （consolidate_group 整合批次）时显式传入——复用调用方 ctx 开子 span，
        不自建 root 也不 end_trace；None 时自建独立 ``memory_promotion`` root
        （origin=spawn，scope=共享空间键）。晋升批可能处理当前群以外的既存候选，
        与触发消息只有 cause 关联（actual scope 落在 memory.promotion.batch
        checkpoint 的 spaces metrics 里），不冒充触发消息的子步骤。
        """
        from memory_rust.selector import configured_mode, resolve_backend

        # root 生命周期：只在无人传父 trace 时自建（旁路：创建失败按 None 空转）。
        own_root = None
        if flow_ctx is None:
            try:
                from core.observability import message_flow

                own_root = message_flow.begin_trace(
                    root_kind="memory_promotion", origin="spawn",
                    scope="memory_shared",
                )
            except Exception:
                own_root = None
        # ctx 经实例属性下传给内部方法：既有测试用零参替身替换
        # _process_new_candidates_python，内部签名必须保持零参兼容。
        # process_new_candidates 全程同步（无 await），事件循环内不会重入。
        self._flow_ctx = flow_ctx if flow_ctx is not None else own_root
        self._batch_span = (
            _NoopSpan() if own_root is not None
            else _probe_span(self._flow_ctx, "memory.promotion.batch")
        )
        outcome = "done"
        try:
            mode = configured_mode()
            if mode in {"auto", "rust", "strict"}:
                decision, backend = resolve_backend(mode)
                logger.info(
                    f"[MemoryBackend] promotion backend selected: {backend.name} (requested={decision.requested})"
                )
                # 后端解析事实（计划 §6.3 memory.promotion.backend）：实际
                # backend / 请求模式 / fallback 原因分开记录，不统一画成假想事务。
                _probe_decision(self._flow_ctx, "memory.promotion.backend",
                                status="succeeded", reason_code=backend.name,
                                metrics={"mode": mode, "requested": decision.requested,
                                         "backend": backend.name,
                                         "fallback_reason": decision.fallback_reason or ""})
                if backend.name == "rust":
                    started = time.perf_counter()
                    try:
                        self._process_new_candidates_rust(decision, backend)
                    except Exception as exc:
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        _probe_decision(self._flow_ctx, "memory.promotion.backend",
                                        status="failed", reason_code="rust_error",
                                        error_code=type(exc).__name__,
                                        metrics={"mode": mode,
                                                 "elapsed_ms": round(elapsed_ms, 1)})
                        if decision.requested != "auto":
                            logger.error(
                                f"[MemoryBackend] Rust promotion failed in non-fallback mode "
                                f"(elapsed_ms={elapsed_ms:.1f}): {type(exc).__name__}: {exc}"
                            )
                            outcome = "rust_failed"
                            # strict 模式失败原样上抛：观测不吞（计划 §6.3）
                            raise
                        logger.warning(
                            f"[MemoryBackend] Rust promotion fallback to Python "
                            f"(elapsed_ms={elapsed_ms:.1f}): {type(exc).__name__}: {exc}"
                        )
                        outcome = "fallback_python"
                        _probe_decision(self._flow_ctx, "memory.promotion.backend",
                                        status="skipped", reason_code="auto_fallback_python",
                                        metrics={"mode": mode,
                                                 "error_code": type(exc).__name__})
                        try:
                            return self._process_new_candidates_python()
                        except BaseException:
                            outcome = "error"
                            raise
                    logger.info(
                        f"[MemoryBackend] Rust promotion committed "
                        f"(elapsed_ms={(time.perf_counter() - started) * 1000:.1f})"
                    )
                    return None
                if decision.fallback_reason:
                    logger.warning(
                        f"[MemoryBackend] Rust promotion unavailable; using Python: {decision.fallback_reason}"
                    )
            else:
                _probe_decision(self._flow_ctx, "memory.promotion.backend",
                                status="succeeded", reason_code="python",
                                metrics={"mode": mode, "backend": "python"})
            return self._process_new_candidates_python()
        except BaseException:
            if outcome == "done":
                outcome = "error"
            raise
        finally:
            if self._batch_span is not None:
                with contextlib.suppress(Exception):
                    self._batch_span.finish(
                        status="failed" if outcome in ("error", "rust_failed") else "succeeded",
                        reason_code="" if outcome == "done" else outcome)
            self._flow_ctx = None
            self._batch_span = None
            if own_root is not None:
                try:
                    from core.observability import message_flow

                    if not own_root.ended:
                        message_flow.end_trace(own_root, outcome=outcome)
                except Exception:
                    pass

    @staticmethod
    def _candidate_from_row(row) -> dict:
        return {
            "id": row[0],
            "group_shared_space": row[1],
            "user_id": row[2],
            "type": row[3] or "FACT",
            "content": row[4] or "",
            "importance": float(row[5] or 0.0),
            "confidence": float(row[6] or 0.0),
            "evidence": row[7] or "",
            "status": row[8] or "NEW",
            "source_message_ids": row[9] or "[]",
            "usage_tags": row[10] or "[]",
            "visibility": row[11] or "OPEN",
            "behavior_rule": row[12] or "",
            "occurrence_count": int(row[13] or 1),
            "source_kinds": row[14] or '["PASSIVE"]',
            "source_kind": row[15] or "PASSIVE",
        }

    # ── 观测辅助（计划 §6.1 对象履历；旁路纪律见模块头注释）──────────

    def _history_buffer_append(self, event: tuple[str, str, str, str, str, dict]) -> None:
        """把一条状态变化写入本批履历缓冲（业务 commit 成功后由 _flush_history 落账）。

        缓冲不存在（未走 process_new_candidates 的直接方法调用，如单测）时静默丢弃。
        """
        buf = getattr(self, "_history_buffer", None)
        if buf is not None:
            buf.append(event)

    def _flush_history(self) -> None:
        """把履历缓冲落账（只在业务 conn.commit() 成功之后调用，计划 §6.1）。

        entity_history.record 走 message_flow 有界 writer 队列（put_nowait），
        不在业务事务/锁内；单条失败返回 "" 不抛（旁路绝不影响业务）。
        trace_id 只在显式传入 flow_ctx 时可关联，否则为空（不猜）。
        """
        events = getattr(self, "_history_buffer", None)
        self._history_buffer = []
        if not events:
            return
        ctx = getattr(self, "_flow_ctx", None)
        trace_id = str(getattr(ctx, "trace_id", "") or "") if ctx is not None else ""
        try:
            from core.observability import entity_history

            for etype, eid, scope, from_state, to_state, changed in events:
                entity_history.record(
                    etype, eid, scope=scope, trace_id=trace_id,
                    from_state=from_state, to_state=to_state,
                    changed_fields=changed,
                )
        except Exception:
            pass

    @staticmethod
    def _gate_metrics(candidate: dict) -> dict:
        """Gate 1 门槛事实：阈值与实际值同落（计划 §6.3 memory.promotion.gate）。"""
        return {
            "importance": candidate["importance"],
            "confidence": candidate["confidence"],
            "occurrence": candidate["occurrence_count"],
            "at_mention_evidence": MemoryManager._has_at_mention(candidate["source_kinds"]),
            "threshold_min_importance": MEMORY_PROMOTE_MIN_IMPORTANCE,
            "threshold_high_confidence": MEMORY_CONFIRM_HIGH_CONFIDENCE,
            "threshold_low_confidence": MEMORY_OBSERVE_LOW_CONFIDENCE,
            "threshold_min_occurrence": MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE,
            "at_mention_single_shot": MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT,
        }

    def _process_new_candidates_rust(self, decision, backend) -> None:
        """Run one native transaction per candidate and keep Python side effects."""
        from memory_rust.backend import PromotionRequest

        if not DB_PATH.exists():
            return
        ctx = getattr(self, "_flow_ctx", None)
        conn = self._connect()
        cursor = conn.cursor()
        self._ensure_tables()
        self._reject_stale_candidates(cursor)
        rows = cursor.execute(
            "SELECT id, group_shared_space, user_id, type, content, importance, confidence, evidence, status, "
            "source_message_ids, usage_tags, visibility, behavior_rule, "
            "occurrence_count, source_kinds, source_kind, origin_group_id"
            " FROM memory_candidates WHERE status IN ('NEW', 'OBSERVING') ORDER BY created_at ASC"
        ).fetchall()
        conn.commit()
        conn.close()
        logger.info(
            f"[MemoryBackend] Rust promotion candidates={len(rows)}"
        )
        # 批次事实（计划 §6.3 memory.promotion.batch）：actual scope（候选可能
        # 来自当前群以外的空间）与条数，不把全部结果归到触发消息。
        _probe_checkpoint(ctx, "memory.promotion.batch",
                          metrics={"candidates": len(rows), "backend": "rust",
                                   "spaces": sorted({str(r[1]) for r in rows})[:8]})

        promoted = False
        for row in rows:
            candidate = self._candidate_from_row(row)
            instance_key = f"cand:{candidate['id']}"
            with _probe_span(ctx, "memory.promotion.gate",
                             instance_key=instance_key) as gate_span:
                should_promote, reason = self._decide_promotion(candidate)
                # 逐候选门槛事实（计划 §6.3 memory.promotion.gate）：阈值与
                # 实际值（importance/confidence/occurrence/来源认可）同落。
                _probe_decision(ctx, "memory.promotion.gate",
                                status="succeeded" if should_promote else "skipped",
                                reason_code=_gate_reason_code(reason), summary=reason,
                                instance_key=instance_key,
                                metrics=self._gate_metrics(candidate))
                if not should_promote:
                    status_conn = self._connect()
                    status_conn.execute(
                        "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        ("OBSERVING", candidate["id"]),
                    )
                    status_conn.commit()
                    status_conn.close()
                    # Rust 侧 OBSERVING 是独立小事务：提交成功后再落履历（计划 §5）
                    self._history_buffer_append((
                        "memory_candidate", str(candidate["id"]),
                        str(candidate["group_shared_space"]),
                        candidate["status"], "OBSERVING",
                        {"action": "gate_hold", "backend": "rust",
                         "reason_code": _gate_reason_code(reason)},
                    ))
                    self._flush_history()
                    gate_span.finish(status="skipped",
                                     reason_code=_gate_reason_code(reason))
                    logger.debug(
                        f"[MemoryManager] candidate {candidate['id']} -> OBSERVING: {reason}"
                    )
                    continue

                request = PromotionRequest(
                    db_path=DB_PATH,
                    candidate_id=str(candidate["id"]),
                    group_shared_space=str(candidate["group_shared_space"]),
                    user_id=str(candidate["user_id"]),
                    memory_type=str(candidate["type"]),
                    quota_limit=MEMORY_USER_QUOTA,
                    quota_enforce=MEMORY_QUOTA_ENFORCE,
                    quota_confirmation_cap=MEMORY_QUOTA_CONFIRMATION_CAP,
                    quota_weight_importance=MEMORY_QUOTA_W_IMPORTANCE,
                    quota_weight_confirmation=MEMORY_QUOTA_W_CONFIRMATION,
                    quota_weight_recency=MEMORY_QUOTA_W_RECENCY,
                    fts_enabled=RAG_ENABLED and RAG_SQLITE_FTS_ENABLED,
                )
                try:
                    result = backend.promote(request)
                except Exception as exc:
                    # Rust 事务失败：attempted/rolled_back 事实（计划 §5/§6.1）。
                    # 异常继续上抛，由 strict/auto 策略决定后续（观测不吞）。
                    _probe_decision(ctx, "memory.promotion.commit",
                                    status="failed", reason_code="rolled_back",
                                    fact_kind="commit", instance_key=instance_key,
                                    error_code=type(exc).__name__,
                                    metrics={"backend": "rust"})
                    raise
                result_promoted = (
                    result.get("promoted", False)
                    if isinstance(result, dict)
                    else bool(getattr(result, "promoted", False))
                )
                if result_promoted:
                    promoted = True
                    action = (
                        str(result.get("action", "") or "")
                        if isinstance(result, dict)
                        else str(getattr(result, "action", "") or "")
                    )
                    # Rust 的 IMMEDIATE 事务在 promote 返回前已提交
                    # （promotion.rs）：返回即提交确认，commit 事实在此之后。
                    _probe_decision(ctx, "memory.promotion.commit",
                                    status="succeeded", fact_kind="commit",
                                    instance_key=instance_key,
                                    metrics={"backend": "rust", "action": action})
                    self._history_buffer_append((
                        "memory_candidate", str(candidate["id"]),
                        str(candidate["group_shared_space"]),
                        candidate["status"], "CONFIRMED",
                        {"action": action or "promoted", "backend": "rust"},
                    ))
                    self._flush_history()
                    logger.info(
                        f"[MemoryManager] Rust promoted candidate {candidate['id']}: {reason}"
                    )

        if promoted:
            bump_memory_history()
            try:
                get_compressor().maybe_compress(reason="candidate_processed")
            except Exception as e:
                logger.warning(f"🧹 [MemoryManager] 触发轻量压缩失败: {e}")

    def _process_new_candidates_python(self) -> None:
        """处理全部待晋升的记忆候选（status ∈ {NEW, OBSERVING}），并把结果提交。

        关键逻辑：
        1. Gate 1 三档判定：先淘汰超期 OBSERVING 候选，再按置信度 × 证据充分度
           （来源等级 / 复现次数）决定观察或晋升；
        2. 相似度合并：命中已有相似记忆则合并进入该记忆，否则新建记忆；
        3. 新旧都同步 FTS 索引；
        4. 提交后驱动轻量压缩（见注释）。
        副作用：修改 memory_candidates / memories / FTS 等表。

        观测（计划 §6.3，M2）：逐候选 gate/conflict/merge/create/quota 节点；
        memory.promotion.commit 事实节点在业务 ``conn.commit()`` 成功**之后**
        发 succeeded（fact_kind=commit），失败发 failed(rolled_back)——事务
        诚实：未提交的晋升绝不显示为已提交。对象履历在提交成功后统一落账。
        """
        if not DB_PATH.exists():
            return
        ctx = getattr(self, "_flow_ctx", None)
        conn = self._connect()
        cursor = conn.cursor()
        self._ensure_tables()

        # 先淘汰超期候选，避免它们参与本轮评估
        stale_rejected = self._reject_stale_candidates(cursor)
        _probe_checkpoint(ctx, "memory.promotion.batch",
                          metrics={"stale_rejected": stale_rejected, "backend": "python"})

        # 按创建时间先后处理，避免同批候选间的顺序抖动
        candidates = cursor.execute(
            "SELECT id, group_shared_space, user_id, type, content, importance, confidence, evidence, status, "
            "source_message_ids, usage_tags, visibility, behavior_rule, "
            "occurrence_count, source_kinds, source_kind, origin_group_id"
            " FROM memory_candidates WHERE status IN ('NEW', 'OBSERVING') ORDER BY created_at ASC"
        ).fetchall()
        # 批次事实：actual scope（候选可能来自当前群以外的空间）与条数
        _probe_checkpoint(ctx, "memory.promotion.batch",
                          metrics={"candidates": len(candidates), "backend": "python",
                                   "spaces": sorted({str(r[1]) for r in candidates})[:8]})

        # 本批状态写入都在同一个业务事务里：履历先入缓冲，提交成功后落账
        self._history_buffer = []
        promoted = False
        for row in candidates:
            candidate = {
                "id": row[0],
                "group_shared_space": row[1],
                "user_id": row[2],
                "type": row[3] or "FACT",
                "content": row[4] or "",
                "importance": float(row[5] or 0.0),
                "confidence": float(row[6] or 0.0),
                "evidence": row[7] or "",
                "status": row[8] or "NEW",
                "source_message_ids": row[9] or "[]",
                "usage_tags": row[10] or "[]",
                "visibility": row[11] or "OPEN",
                "behavior_rule": row[12] or "",
                "occurrence_count": int(row[13] or 1),
                "source_kinds": row[14] or '["PASSIVE"]',
                "source_kind": row[15] or "PASSIVE",
            }
            instance_key = f"cand:{candidate['id']}"

            # ── 逐候选实例 span（计划 §6.1 instance 合同）：同节点的多个候选
            # 各自独立成实例，聚合状态不会互相覆盖 ──
            with _probe_span(ctx, "memory.promotion.gate",
                             instance_key=instance_key) as gate_span:
                # ── Gate 1 三档判定：置信度 + 证据充分度（来源等级 / 复现次数） ──
                should_promote, reason = self._decide_promotion(candidate)
                _probe_decision(ctx, "memory.promotion.gate",
                                status="succeeded" if should_promote else "skipped",
                                reason_code=_gate_reason_code(reason), summary=reason,
                                instance_key=instance_key,
                                metrics=self._gate_metrics(candidate))
                if not should_promote:
                    cursor.execute(
                        "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        ("OBSERVING", candidate["id"]),
                    )
                    self._history_buffer_append((
                        "memory_candidate", str(candidate["id"]),
                        str(candidate["group_shared_space"]),
                        candidate["status"], "OBSERVING",
                        {"action": "gate_hold",
                         "reason_code": _gate_reason_code(reason)},
                    ))
                    gate_span.finish(status="skipped",
                                     reason_code=_gate_reason_code(reason))
                    logger.debug(
                        f"👀 [MemoryManager] 候选转 OBSERVING {candidate['id']}：{reason}"
                    )
                    continue

                # 冲突解决（Conflict Resolution）：新候选与旧记忆矛盾时，标记旧记忆为 CONFLICT
                with _probe_span(ctx, "memory.promotion.conflict",
                                 instance_key=instance_key):
                    weak_demoted = self._resolve_conflicts(cursor, candidate)

                # 相似度合并：与已有的活跃同类型记忆比对，相似则合并而非重复新建
                existing_id = self._find_similar_memory(cursor, candidate)
                if existing_id:
                    with _probe_span(ctx, "memory.promotion.merge",
                                     instance_key=instance_key):
                        self._merge_into_memory(cursor, existing_id, candidate)
                else:
                    with _probe_span(ctx, "memory.promotion.create",
                                     instance_key=instance_key):
                        self._create_memory(cursor, candidate)
                    # 新建才可能突破配额；合并不增加条数（计划 §5：quota 在
                    # create 分支，不虚构为每次 merge 都执行）
                    with _probe_span(ctx, "memory.promotion.quota",
                                     instance_key=instance_key) as quota_span:
                        archived = self._enforce_user_quota(
                            cursor, candidate["group_shared_space"], candidate["user_id"]
                        )
                        quota_span.finish(
                            status="succeeded",
                            metrics={"archived": archived,
                                     "quota_limit": MEMORY_USER_QUOTA,
                                     "enforce": bool(MEMORY_QUOTA_ENFORCE)})

                logger.info(f"⬆️ [MemoryManager] 候选晋升 {candidate['id']}：{reason}")

                cursor.execute(
                    "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("CONFIRMED", candidate["id"]),
                )
                # 弱候选冲突场景（计划 §5 登记的 Python/Rust parity 案例）：
                # _resolve_conflicts 已把候选写成 OBSERVING，这里又改写为
                # CONFIRMED——履历如实记录这两次业务写入，不替业务圆场。
                self._history_buffer_append((
                    "memory_candidate", str(candidate["id"]),
                    str(candidate["group_shared_space"]),
                    "OBSERVING" if weak_demoted else candidate["status"], "CONFIRMED",
                    {"action": "promoted",
                     "reason_code": _gate_reason_code(reason)},
                ))
                # 只记录有晋升（CONFIRMED）的批次，用于提交后统一触发压缩
                promoted = True

        # ── 事务提交（memory.promotion.commit 事实节点，计划 §6.1 事务诚实）──
        try:
            conn.commit()
        except Exception as exc:
            _probe_decision(ctx, "memory.promotion.commit",
                            status="failed", reason_code="rolled_back",
                            fact_kind="commit", error_code=type(exc).__name__,
                            metrics={"backend": "python", "promoted": promoted})
            raise
        finally:
            conn.close()
        # 提交确认（conn.commit() 成功之后，计划 §5：attempted/committed 分离）
        _probe_decision(ctx, "memory.promotion.commit",
                        status="succeeded", fact_kind="commit",
                        metrics={"backend": "python", "promoted": promoted,
                                 "history_events": len(self._history_buffer)})
        self._flush_history()

        # 记忆库内容变了（新建/合并/冲突标记都发生在 promoted 批次内）：
        # 递增历史版本，让语义检索缓存立即换桶，@ 对话前刚整合出的新记忆
        # 不被 5 分钟 TTL 挡在门外（设计阶段四「历史版本变化时失效缓存」）。
        if promoted:
            bump_memory_history()

        # 提交并关闭连接后再触发压缩，避免对仍在写事务的连接产生 SQLite 锁冲突
        if promoted:
            try:
                # 轻量触发压缩（节流），避免每次都执行重度压缩
                get_compressor().maybe_compress(reason="candidate_processed")
            except Exception as e:
                logger.warning(f"🧹 [MemoryManager] 触发轻量压缩失败: {e}")

    @staticmethod
    def _has_at_mention(source_kinds: str | None) -> bool:
        """历次证据中是否包含 AT_MENTION（用户直接对 Bot 说过）。

        看的是 source_kinds（历次来源集合）而非 source_kind（最近一次）：
        一条事实先在群聊被动提到、后来用户又直接确认过，那次直接确认
        不应因为后续又有被动观察而失效。
        """
        try:
            kinds = json.loads(source_kinds or "[]")
        except (ValueError, TypeError):
            return False
        return isinstance(kinds, list) and any(
            str(k).strip().upper() == "AT_MENTION" for k in kinds
        )

    @staticmethod
    def _decide_promotion(candidate: dict) -> tuple[bool, str]:
        """Gate 1 三档判定：返回 (是否晋升, 原因说明)。

        档位（依据 Memory Consolidation Spec 的 Gate 1）：
          conf >= HIGH(0.85)  → 晋升。用户明确直接陈述，无需额外佐证。
          conf >= LOW(0.6)    → 看证据充分度：
                                  历次来源含 AT_MENTION 且开关开 → 晋升（高密度证据）
                                  occurrence_count >= MIN_OCCURRENCE_PASSIVE → 晋升（交叉验证通过）
                                  否则 → OBSERVING，等复现
          conf <  LOW(0.6)    → OBSERVING。置信度不足，无论来源都要等更多证据。

        另设 importance 下限：低于 MEMORY_PROMOTE_MIN_IMPORTANCE 的候选一律
        不晋升（过于琐碎），但仍保留在 OBSERVING 中等待——它可能后续被证明重要。

        与旧逻辑的区别：旧判定为 `conf < 0.5 AND imp < 0.5` 才观察，即
        importance 单独达标就能晋升。importance 是 LLM 自评、最不可靠的一项，
        不应单独构成晋升依据。
        """
        conf = candidate["confidence"]
        imp = candidate["importance"]
        occurrence = candidate["occurrence_count"]

        if imp < MEMORY_PROMOTE_MIN_IMPORTANCE:
            return False, f"重要度不足（imp={imp:.2f} < {MEMORY_PROMOTE_MIN_IMPORTANCE}）"

        if conf >= MEMORY_CONFIRM_HIGH_CONFIDENCE:
            return True, f"高置信直接晋升（conf={conf:.2f}）"

        if conf >= MEMORY_OBSERVE_LOW_CONFIDENCE:
            if MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT and MemoryManager._has_at_mention(
                candidate["source_kinds"]
            ):
                return True, f"AT_MENTION 高密度证据单次晋升（conf={conf:.2f}）"
            if occurrence >= MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE:
                return True, f"交叉验证通过（conf={conf:.2f}，观察 {occurrence} 次）"
            return False, (
                f"置信度中等但证据不足（conf={conf:.2f}，观察 {occurrence} 次 < "
                f"{MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE}，无 AT_MENTION）"
            )

        return False, f"置信度不足（conf={conf:.2f} < {MEMORY_OBSERVE_LOW_CONFIDENCE}）"

    @staticmethod
    def _observing_ttl_days(mem_type: str | None) -> float:
        """该类型候选在 OBSERVING 的最长停留天数：有类型档就用，否则走全局值。

        单独抽出来是为了让「时效型信息不该等满 30 天」这条判断有个能直接断言的
        入口——它藏在 SQL 里的话，测试只能靠构造时间戳去反推。
        脏 type（空串、大小写不一）一律按全局值处理：宁可多留几天，也不要因为
        一个拼错的类型名把候选提前丢掉。
        """
        key = (mem_type or "").strip().upper()
        try:
            return float(MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE[key])
        except (KeyError, TypeError, ValueError):
            return float(MEMORY_CANDIDATE_MAX_OBSERVING_DAYS)

    def _reject_stale_candidates(self, cursor: sqlite3.Cursor) -> int:
        """把超期未获新证据的 OBSERVING 候选标记为 REJECTED（不删除，保留供审计）。

        没有这一步，OBSERVING 会变成只进不出的死胡同：一条永远等不到复现的
        候选会被无限次重新评估、反复失败，把候选表堆大并拖慢每轮晋升。
        以 first_seen_at 为锚点（不是 updated_at，后者每次复现都会刷新）。

        TTL 按类型分档（``MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE``）：EVENT 这类
        时效信息几天内没有复现就不再值得等下去。统一 30 天的后果是它一直占着候选池，
        且始终落在主动验证的取数范围内被反复挑中（见 design_docs/bug_report/
        bug_report_2026_8_31#1.md 现象 2）。

        分类型逐条执行而不是写成一条 CASE：超期淘汰是完全不可见的后台动作，
        按类型分行记日志才能事后看出「淘汰的是哪一类」，可审计性优先于少一次 UPDATE。
        """
        typed = {
            str(t).strip().upper(): float(d)
            for t, d in MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE.items()
            if str(t).strip()
        }
        total = 0
        for mem_type, days in sorted(typed.items()):
            total += self._reject_stale_batch(
                cursor, "AND UPPER(COALESCE(type, 'FACT')) = ?", (mem_type,), days, mem_type
            )

        # 剩下的类型走全局 TTL。type 为空或脏值经 COALESCE 归到 FACT，
        # 因此不会有候选因为类型缺失而永久豁免淘汰。
        rest_clause, rest_params = "", ()
        if typed:
            holes = ",".join("?" * len(typed))
            rest_clause = f"AND UPPER(COALESCE(type, 'FACT')) NOT IN ({holes})"
            rest_params = tuple(sorted(typed))
        total += self._reject_stale_batch(
            cursor,
            rest_clause,
            rest_params,
            float(MEMORY_CANDIDATE_MAX_OBSERVING_DAYS),
            "其他类型",
        )
        return total

    @staticmethod
    def _reject_stale_batch(
        cursor: sqlite3.Cursor,
        type_clause: str,
        type_params: tuple[str, ...],
        days: float,
        label: str,
    ) -> int:
        """按一个类型过滤条件淘汰超期候选，返回被标记的行数。

        ``type_clause`` 只由本模块的常量拼出（占位符个数），类型名一律走参数绑定。
        """
        cursor.execute(
            "UPDATE memory_candidates SET status = 'REJECTED', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'OBSERVING' AND first_seen_at IS NOT NULL "
            f"{type_clause} "
            "AND julianday('now') - julianday(first_seen_at) > ?",
            (*type_params, days),
        )
        rejected = cursor.rowcount or 0
        if rejected > 0:
            logger.info(
                f"🗑️ [MemoryManager] {rejected} 条 {label} 候选超过 "
                f"{days:g} 天未获新证据，标记 REJECTED"
            )
        return rejected

    def _find_similar_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> str | None:
        """在同空间、同用户的 active 记忆中查找与候选内容相似的记忆 id；找不到返回 None。

        **必须按 group_shared_space + user_id 过滤**：只比 type 会把用户 A 的候选合并进
        用户 B 的记忆（_merge_content 用「；」把两人的内容拼在一起），造成
        不可恢复的归属污染。与 _resolve_conflicts 的过滤条件保持一致。

        类型条件分两档：同类型相似即命中；跨类型只在归一化后逐字相同时命中——
        类型词表对「希望被称呼为X」这类内容两可，LLM 两次抽取可能给出 RELATION
        与 PREFERENCE，纯同类型比对会让跨类型重复各立一条（2026-09-27 缺陷）。
        """
        rows = cursor.execute(
            "SELECT id, type, content FROM memories WHERE status = 'active' "
            "AND group_shared_space = ? AND user_id = ? "
            # 证据新鲜度倒序：同类相似记忆有多条时并入最近被确认过的那条。
            # 不用 last_accessed_at——它现在由检索命中刷新，会让「最近被引用过的」
            # 而不是「最近被证实过的」持续吸收新证据。
            "ORDER BY COALESCE(last_confirmed_at, last_accessed_at) DESC",
            (str(candidate["group_shared_space"]), str(candidate["user_id"])),
        ).fetchall()
        for mem_id, mem_type, content in rows:
            content = content or ""
            if is_similar(candidate["content"], content) and (
                mem_type == candidate["type"]
                or same_normalized_text(candidate["content"], content)
            ):
                return mem_id
        return None

    def _create_memory(self, cursor: sqlite3.Cursor, candidate: dict) -> None:
        """新建长期记忆并同步写入 FTS 索引。内存记忆内容与原样都取 candidate.content。
        同时写入 v2 元字段（usage_tags / visibility / behavior_rule）。"""
        memory_id = uuid.uuid4().hex
        cursor.execute(
            "INSERT OR IGNORE INTO memories ("
            "id, group_shared_space, user_id, type, content, content_raw, importance, confidence, status, "
            # last_accessed_at 在建库时也写当前时间：它的语义是「最后一次被用到」，
            # 新记忆还没被检索过，但置 NULL 会让 _archive_low_value_memories 的
            # 「从未访问」分支立刻把低重要度的新记忆归档，等于不给宽限期。
            "confirmation_count, last_confirmed_at, last_accessed_at, compressed_at, compression_version, is_atomized, "
            "usage_tags, visibility, behavior_rule, source_kind)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, NULL, 0, 0, ?, ?, ?, ?)",
            (
                memory_id,
                candidate["group_shared_space"],
                candidate["user_id"],
                candidate["type"],
                candidate["content"],
                candidate["content"],
                candidate["importance"],
                candidate["confidence"],
                "active",
                1,
                candidate.get("usage_tags") or "[]",
                candidate.get("visibility") or "OPEN",
                candidate.get("behavior_rule") or "",
                candidate.get("source_kind") or "PASSIVE",
            ),
        )
        _upsert_fts_record(
            cursor,
            memory_id,
            str(candidate["group_shared_space"]),
            str(candidate["user_id"]),
            candidate["content"],
        )
        # 新建履历（from 空 = 创建，计划 §6.1 entity_change 允许表示创建）；
        # 业务提交成功后由 _flush_history 统一落账。
        self._history_buffer_append((
            "long_term_memory", memory_id,
            str(candidate["group_shared_space"]),
            "NEW", "active",
            {"action": "create", "type": candidate["type"],
             "candidate": candidate["id"]},
        ))
        logger.info(f"🧠 [MemoryManager] 新增长期记忆 {memory_id} ({candidate['type']})")

    @staticmethod
    def _quota_score(importance, confirmation_count, last_accessed_at) -> float:
        """配额竞争分：越低越先被淘汰。

        三维加权：importance（信息本身的重要度）、confirmation_count（被独立确认
        的次数，最硬的证据，按 MEMORY_QUOTA_CONFIRMATION_CAP 归一化）、
        recency（最近是否仍被触达，指数衰减 τ=30 天，与 policy._recency_factor 一致）。

        用 last_accessed_at 而非 created_at：一条老但仍被频繁调用的记忆比一条新
        却从未被用过的更有价值。这条意图直到 2026-08-31 才真正成立——此前
        last_accessed_at 只跟着「确认」写，检索从不刷新它，于是本项实际算的是
        「最后一次被确认」，与 confirmation 项重复计分（bug_report_2026_8_31#1 §4.e）。
        现在它由 retrieval_v2._touch_accessed 刷新，两项才各自独立。
        """
        import math

        from memory.timeutil import seconds_since

        imp = 0.0
        try:
            imp = max(0.0, min(1.0, float(importance or 0.0)))
        except (TypeError, ValueError):
            imp = 0.0

        conf_count = 0
        try:
            conf_count = int(confirmation_count or 0)
        except (TypeError, ValueError):
            conf_count = 0
        confirmation = min(1.0, conf_count / max(1, MEMORY_QUOTA_CONFIRMATION_CAP))

        # recency：解析失败或从未访问按「最旧」处理（recency=0），优先淘汰
        recency = 0.0
        elapsed = seconds_since(last_accessed_at) if last_accessed_at else None
        if elapsed is not None:
            age_days = max(0.0, elapsed / 86400.0)
            recency = math.exp(-age_days / 30.0)

        return (
            MEMORY_QUOTA_W_IMPORTANCE * imp
            + MEMORY_QUOTA_W_CONFIRMATION * confirmation
            + MEMORY_QUOTA_W_RECENCY * recency
        )

    def _enforce_user_quota(self, cursor: sqlite3.Cursor, group_shared_space, user_id) -> int:
        """把该空间该用户的 active 记忆压回 MEMORY_USER_QUOTA 条以内（竞争性淘汰）。

        超额时按 _quota_score 升序把最弱的若干条置 archived（不删除，仅退出
        active 检索，可人工恢复）。返回被淘汰的条数。

        ⚠️ 语义变化（v8）：MEMORY_USER_QUOTA 现在是「每空间每用户」的上限，
        不再是「每 QQ 群」。多个群组成一个空间时配额实际收紧了——这符合设计
        （同一个人在同一空间就是一份认知），但调参时要知道。

        MEMORY_QUOTA_ENFORCE=False 时只记录「本来会淘汰谁」的日志、不实际执行，
        用于上线前观察配额在真实库上的行为——25 条这个数在具体库上会淘汰什么，
        必须先看过再打开。

        注意：只统计 status='active'。archived / conflict 不占配额。
        """
        rows = cursor.execute(
            "SELECT id, content, importance, confirmation_count, last_accessed_at "
            "FROM memories WHERE status = 'active' AND group_shared_space = ? AND user_id = ?",
            (str(group_shared_space), str(user_id)),
        ).fetchall()
        if len(rows) <= MEMORY_USER_QUOTA:
            return 0

        scored = sorted(
            (
                (self._quota_score(r[2], r[3], r[4]), r[0], r[1] or "")
                for r in rows
            ),
            key=lambda item: item[0],
        )
        overflow = len(rows) - MEMORY_USER_QUOTA
        victims = scored[:overflow]

        if not MEMORY_QUOTA_ENFORCE:
            for score, mem_id, content in victims:
                logger.info(
                    f"📊 [Quota dry-run] 用户 {user_id} 超额（{len(rows)}/{MEMORY_USER_QUOTA}），"
                    f"本来会淘汰 {mem_id}（分 {score:.3f}）「{content[:40]}」"
                )
            return 0

        for score, mem_id, content in victims:
            cursor.execute(
                "UPDATE memories SET status = 'archived', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (mem_id,),
            )
            # 配额淘汰履历（active → archived；dry-run 不改业务，不落履历）
            self._history_buffer_append((
                "long_term_memory", str(mem_id),
                str(group_shared_space),
                "active", "archived",
                {"action": "quota_archive", "score": round(score, 3)},
            ))
            logger.info(
                f"📦 [Quota] 用户 {user_id} 超额（{len(rows)}/{MEMORY_USER_QUOTA}），"
                f"归档最弱记忆 {mem_id}（分 {score:.3f}）「{content[:40]}」"
            )
        return len(victims)

    def _merge_into_memory(self, cursor: sqlite3.Cursor, memory_id: str, candidate: dict) -> None:
        """把候选合并进已有记忆：合并内容块、重要度/置信度取最大值、累计确认次数，并同步 FTS。
        合并时同步吸收 v2 元字段（usage_tags 并集、behavior_rule 优先取候选值）。"""
        row = cursor.execute(
            "SELECT content, content_raw, importance, confidence, confirmation_count, usage_tags, visibility, behavior_rule FROM memories WHERE id = ?",
            (memory_id,),
        ).fetchone()
        if not row:
            return
        content, content_raw, importance, confidence, count = row[0], row[1], row[2], row[3], row[4]
        # 相似度合并：内容去重拼接（正文与原样都合并）
        merged_content = merge_content(content, candidate["content"])
        merged_content_raw = merge_content(content_raw or content, candidate["content"])
        # 合并时重要度/置信度取双方较大值，保留更强证据
        merged_importance = max(importance or 0.0, candidate["importance"])
        merged_confidence = max(confidence or 0.0, candidate["confidence"])
        # v2 元字段：usage_tags 取并集；behavior_rule 优先取候选值（候选更可能是边界规则）
        merged_usage = self._merge_usage_tags(row[5], candidate.get("usage_tags"))
        merged_visibility = self._merge_visibility(row[6], candidate.get("visibility"))
        merged_behavior = (candidate.get("behavior_rule") or "").strip() or (row[7] or "")
        cursor.execute(
            "UPDATE memories SET content = ?, content_raw = ?, importance = ?, confidence = ?, "
            # 只刷 last_confirmed_at：候选强化是新证据，不是「这条记忆被用到了」。
            # 一并刷 last_accessed_at 会让配额竞争里的 recency 项与 confirmation 项
            # 重复计同一个信号，也会让「长期未访问」的归档判定永远不成立。
            "confirmation_count = ?, last_confirmed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP, "
            "usage_tags = ?, visibility = ?, behavior_rule = ? "
            "WHERE id = ?",
            (
                merged_content,
                merged_content_raw,
                merged_importance,
                merged_confidence,
                (count or 0) + 1,
                merged_usage,
                merged_visibility,
                merged_behavior,
                memory_id,
            ),
        )
        # 合并后更新 FTS 索引，保证内容同步
        _upsert_fts_record(
            cursor,
            memory_id,
            str(candidate["group_shared_space"]),
            str(candidate["user_id"]),
            merged_content,
        )
        # 合并履历：记忆保持 active（业务状态词），动作与证据增量记入
        # changed_fields；业务提交成功后由 _flush_history 统一落账。
        self._history_buffer_append((
            "long_term_memory", str(memory_id),
            str(candidate["group_shared_space"]),
            "active", "active",
            {"action": "merge", "candidate": candidate.get("id", ""),
             "confirmation_count": (count or 0) + 1,
             "confidence": round(merged_confidence, 3)},
        ))
        logger.info(f"🧠 [MemoryManager] 合并入已有记忆 {memory_id}")

    @staticmethod
    def _merge_usage_tags(old: str, new) -> str:
        """合并两批 usage_tags（JSON 数组），取并集、去重、保序。"""

        def _parse(value) -> list[str]:
            if isinstance(value, list):
                return [str(x).strip().upper() for x in value if str(x).strip()]
            try:
                parsed = json.loads(value or "[]")
                return [str(x).strip().upper() for x in parsed if str(x).strip()]
            except (ValueError, TypeError):
                return []

        merged: list[str] = []
        for tag in _parse(old) + _parse(new):
            if tag not in merged:
                merged.append(tag)
        return json.dumps(merged, ensure_ascii=False)

    @staticmethod
    def _merge_visibility(old, new) -> str:
        """合并可见性：候选若为更严格的 RESTRICTED/INTERNAL 则升级，否则保留旧值。"""
        from memory.policy import (
            VISIBILITY_INTERNAL,
            VISIBILITY_RESTRICTED,
            parse_visibility,
        )

        old_vis = parse_visibility(old)
        new_vis = parse_visibility(new)
        order = {VISIBILITY_INTERNAL: 0, VISIBILITY_RESTRICTED: 1, "CONTEXTUAL": 2, "OPEN": 3}
        return new_vis if order.get(new_vis, 3) <= order.get(old_vis, 3) else old_vis

    def _resolve_conflicts(self, cursor: sqlite3.Cursor, candidate: dict) -> bool:
        """冲突解决（Conflict Resolution）：检测候选是否与已有活跃记忆矛盾。

        矛盾判定：同用户、同类型，两者共享关键对象词，但情感极性相反
        （旧=肯定、新=否定，反之亦然）。若新候选置信度更高，旧记忆标记为
        CONFLICT（不再参与检索），新候选晋升；否则新候选压入 OBSERVING 等更多证据。

        返回是否走了「弱候选置 OBSERVING」分支。**这是计划 §5 登记的
        Python/Rust parity 案例**：Python 把弱候选写成 OBSERVING，但上层晋升
        循环会继续合并/新建并把最终状态改写为 CONFIRMED（Rust 则立即返回
        observing_conflict）。现存业务疑点本轮不修——观测只如实记录这两次
        业务写入（NEW→OBSERVING→CONFIRMED），不替业务圆场。
        """
        ctx = getattr(self, "_flow_ctx", None)
        instance_key = f"cand:{candidate['id']}"
        if not candidate["content"]:
            return False
        rows = cursor.execute(
            "SELECT id, content, confidence FROM memories WHERE status = 'active' AND group_shared_space = ? AND user_id = ? AND type = ?",
            (str(candidate["group_shared_space"]), str(candidate["user_id"]), candidate["type"]),
        ).fetchall()
        for mem_id, old_content, old_confidence in rows:
            if not old_content or old_content == candidate["content"]:
                continue
            if self._detect_contradiction(old_content, candidate["content"]):
                old_conf = float(old_confidence or 0.0)
                if candidate["confidence"] >= old_conf:
                    cursor.execute(
                        "UPDATE memories SET status = 'conflict', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (mem_id,),
                    )
                    self._history_buffer_append((
                        "long_term_memory", str(mem_id),
                        str(candidate["group_shared_space"]),
                        "active", "conflict",
                        {"action": "conflict", "candidate": candidate["id"]},
                    ))
                    _probe_decision(ctx, "memory.promotion.conflict",
                                    status="succeeded",
                                    reason_code="old_memory_conflict",
                                    instance_key=instance_key,
                                    metrics={"old_memory_id": mem_id,
                                             "candidate_confidence": candidate["confidence"],
                                             "old_confidence": old_conf})
                    logger.info(f"⚔️ [MemoryManager] 候选与旧记忆冲突，旧记忆标记 CONFLICT: {mem_id}")
                    return False
                cursor.execute(
                    "UPDATE memory_candidates SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    ("OBSERVING", candidate["id"]),
                )
                self._history_buffer_append((
                    "memory_candidate", str(candidate["id"]),
                    str(candidate["group_shared_space"]),
                    candidate["status"], "OBSERVING",
                    {"action": "conflict_weak", "old_memory_id": mem_id},
                ))
                _probe_decision(ctx, "memory.promotion.conflict",
                                status="skipped",
                                reason_code="weak_candidate_observing",
                                instance_key=instance_key,
                                metrics={"old_memory_id": mem_id,
                                         "candidate_confidence": candidate["confidence"],
                                         "old_confidence": old_conf})
                logger.info("⚔️ [MemoryManager] 候选与旧记忆冲突但置信度更低，转为 OBSERVING")
                return True
        return False

    @staticmethod
    def _detect_contradiction(a: str, b: str) -> bool:
        """启发式矛盾检测：两段内容共享关键词对象，但情感极性相反。"""
        negation = (
            "不喜欢", "不爱", "不想", "不常", "不愿意", "讨厌", "反感",
            "拒绝", "不再", "停止", "禁止", "没兴趣",
        )
        affirmation = ("喜欢", "爱玩", "常玩", "经常", "愿意", "想玩", "感兴趣", "好")

        def _polarity(text: str) -> int:
            if any(w in text for w in negation):
                return -1
            if any(w in text for w in affirmation):
                return 1
            return 0

        pa, pb = _polarity(a), _polarity(b)
        if pa == 0 or pb == 0 or pa == pb:
            return False
        # 共享对象词：两段内容中都出现过的 2~4 字片段
        common = MemoryManager._common_terms(a, b)
        return bool(common)

    @staticmethod
    def _common_terms(a: str, b: str, min_len: int = 2) -> set[str]:
        """提取两段文本共同的 2~4 字中文片段或英数词（用于判断是否谈论同一对象）。"""
        import re as _re

        def _segments(text: str) -> set[str]:
            segs = _re.findall(r"[\u4e00-\u9fff]{2,8}", text or "")
            out: set[str] = set()
            for seg in segs:
                if len(seg) <= 4:
                    out.add(seg)
                else:
                    for size in (2, 3, 4):
                        for i in range(len(seg) - size + 1):
                            out.add(seg[i : i + size])
            # 英数词（游戏名/型号等），如 Helldivers2 / RTX5080
            out.update(_re.findall(r"[a-zA-Z0-9]+", text or ""))
            return out

        return _segments(a) & _segments(b)


_memory_manager_instance: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """返回进程级单例 MemoryManager（懒初始化）。"""
    global _memory_manager_instance
    if _memory_manager_instance is None:
        _memory_manager_instance = MemoryManager()
    return _memory_manager_instance
