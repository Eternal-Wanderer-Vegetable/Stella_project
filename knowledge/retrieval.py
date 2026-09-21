# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""混合检索：BM25（FTS5）+ 语义（向量）双通道 → RRF 融合 → 有界证据。

职责边界（与 service 层的分界线是**授权**）：

- 本模块只回答「在这些**已授权**的库里，哪些 chunk 与查询最相关」。
  ``kb_ids`` 是 service 层按 ACL 圈定的授权集合——retrieval 不做权限判定，
  也因此**不可能**泄露未授权内容（过滤先于检索，plan §5 的硬约束）；
- 二次过滤在取回证据后仍然发生（``doc.status='published'`` 且
  ``version = doc.active_version`` 写死在两条通道的 SQL/扫描里）——
  草稿、审核中、归档、被新版本取代的 chunk 物理上进不了候选集。

融合（plan §6.4）：Reciprocal Rank Fusion，``score = Σ 1/(k + rank)``，
k 取 KNOWLEDGE_RRF_K（默认 60）。RRF 只用排名不用原始分，两路分数量纲
（bm25 的负对数与余弦）不可通约的问题由此消失。

降级链：FTS5 不可用 / 无命中 → 纯 dense；embedding 不可用 / 指纹不匹配 →
纯 BM25 + ``needs_rebuild`` 标记；两路都空 → 空结果。检索**永不抛异常**
由 service 层兜底，这里也尽量自带兜底。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from nonebot import logger

from knowledge.domain import Evidence
from knowledge.embedding import KBEmbedder, fingerprint_matches
from knowledge.fts import build_match_query
from knowledge.store import KnowledgeStore, unpack_vector

# 授权过滤写死在 SQL 里：published + active_version（二次过滤的第一次就在这）。
_ACTIVE_CHUNKS_SQL = """
SELECT c.id, c.kb_id, c.doc_id, c.version_no, c.seq, c.text,
       c.section_path, c.page, c.paragraph, c.char_start, c.char_end, c.vector,
       d.title AS doc_title, d.source_uri AS doc_uri
FROM kb_chunk c
JOIN kb_document d ON d.id = c.doc_id AND d.kb_id = c.kb_id
WHERE c.kb_id IN ({placeholders})
  AND d.status = 'published'
  AND c.version_no = d.active_version
"""


@dataclass
class RetrievalResult:
    """一次检索的完整产出（证据 + 诊断）。"""

    evidence: list[Evidence] = field(default_factory=list)
    dense_available: bool = False  # dense 通道是否真的参与了
    needs_rebuild: bool = False  # 指纹不匹配的库集合非空
    rebuild_kb_ids: list[str] = field(default_factory=list)
    degraded: str = ""  # 人读的降级原因（诊断/状态接口用）


def _settings() -> Any:
    from config import settings

    return settings


class HybridRetriever:
    """BM25 + dense 混合检索器。``search`` 是唯一入口，**永不抛异常**。"""

    def __init__(
        self,
        store: KnowledgeStore,
        embedder: KBEmbedder | None = None,
        reranker: Any | None = None,
    ):
        """``reranker``：可选的异步重排回调 ``async (query, evidence) -> evidence``。

        默认 None = 不重排（KNOWLEDGE_RERANK_ENABLED 也默认关）。本地栈目前
        没有 rerank 端点，这个口子是给外接重排服务预留的——注入即生效，
        不注入零成本。
        """
        self.store = store
        self.embedder = embedder or KBEmbedder()
        self.reranker = reranker

    async def search(
        self,
        query: str,
        kb_ids: list[str],
        *,
        top_k: int | None = None,
        rrf_k: int | None = None,
        max_items: int | None = None,
        max_chars: int | None = None,
    ) -> RetrievalResult:
        """在授权库集合内检索。空授权集 → 空结果（不碰任何数据）。"""
        s = _settings()
        top_k = top_k or int(s.KNOWLEDGE_SEARCH_TOP_K)
        rrf_k = rrf_k if rrf_k is not None else int(s.KNOWLEDGE_RRF_K)
        max_items = max_items or int(s.KNOWLEDGE_EVIDENCE_MAX_ITEMS)
        max_chars = max_chars or int(s.KNOWLEDGE_EVIDENCE_MAX_CHARS)

        result = RetrievalResult()
        if not query.strip() or not kb_ids:
            return result

        rebuild: list[str] = []
        dense_kbs: list[str] = []
        current = self.embedder.profile
        for kb_id in kb_ids:
            kb = self.store.get_kb(kb_id)
            if kb is None:
                continue
            if kb.fingerprint_locked() and not fingerprint_matches(
                kb.fingerprint(), current
            ):
                rebuild.append(kb_id)
            else:
                dense_kbs.append(kb_id)
        result.needs_rebuild = bool(rebuild)
        result.rebuild_kb_ids = rebuild

        try:
            bm25_hits = self._bm25_channel(query, dense_kbs + rebuild, top_k)
        except Exception as e:
            logger.warning(f"🔍 [Knowledge] BM25 通道失败（降级）: {e}")
            bm25_hits = []
        dense_hits: list[tuple[int, float]] = []
        if dense_kbs and self.embedder.available:
            query_vec = await self.embedder.embed_query(query)
            if query_vec is not None:
                dense_hits = self._dense_channel(query_vec, dense_kbs, top_k)
        result.dense_available = bool(dense_hits) or (
            self.embedder.available and bool(dense_kbs) and query_vec is not None
        )
        if not result.dense_available and self.embedder.available and rebuild:
            result.degraded = (
                "embedding 指纹与库锁定不一致，该库需重建索引（needs_rebuild）"
            )
        elif not result.dense_available and not self.embedder.available:
            result.degraded = "embedding 服务未配置，仅 BM25 通道生效"

        fused = _rrf_fuse(bm25_hits, dense_hits, rrf_k)
        if not fused:
            return result

        rows = self._hydrate([chunk_id for chunk_id, _ in fused[:max_items]])
        for chunk_id, score in fused[:max_items]:
            row = rows.get(chunk_id)
            if row is None:
                continue
            kb_name = row.get("kb_name", "")
            text = row["text"]
            if len(text) > max_chars:
                text = text[:max_chars]
            result.evidence.append(
                Evidence(
                    kb_id=row["kb_id"],
                    kb_name=kb_name,
                    doc_id=row["doc_id"],
                    doc_title=row["doc_title"],
                    version_no=row["version_no"],
                    chunk_seq=row["seq"],
                    text=text,
                    locator=_locator_of(row),
                    source_uri=row["doc_uri"] or "",
                    score=round(score, 6),
                    matched_by=_matched_by(chunk_id, bm25_hits, dense_hits),
                )
            )

        result.evidence = dedup_evidence(result.evidence)
        if (
            _settings().KNOWLEDGE_RERANK_ENABLED
            and self.reranker is not None
            and result.evidence
        ):
            try:
                result.evidence = await self.reranker(query, result.evidence)
            except Exception as e:
                logger.warning(f"🔍 [Knowledge] rerank 失败（保留融合序）: {e}")
        return result

    # ── 双通道 ───────────────────────────────────────────

    def _bm25_channel(
        self, query: str, kb_ids: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """FTS5 全文通道。返回 ``[(chunk_rowid, bm25分), ...]``（分越大越相关）。"""
        match = build_match_query(query)
        if not match or not kb_ids:
            return []
        conn = _connect(self.store)
        try:
            placeholders = ",".join("?" for _ in kb_ids)
            sql = (
                "SELECT f.rowid AS rowid, -bm25(kb_chunk_fts) AS score "
                "FROM kb_chunk_fts f "
                "JOIN kb_document d ON d.id = f.doc_id AND d.kb_id = f.kb_id "
                f"WHERE kb_chunk_fts MATCH ? AND f.kb_id IN ({placeholders}) "
                "AND d.status = 'published' AND f.version_no = d.active_version "
                "ORDER BY score DESC LIMIT ?"
            )
            rows = conn.execute(sql, (match, *kb_ids, top_k)).fetchall()
            return [(int(r["rowid"]), float(r["score"])) for r in rows]
        finally:
            conn.close()

    def _dense_channel(
        self, query_vec: list[float], kb_ids: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """语义通道：授权库的 active 向量全量载入（本地规模），余弦排序。

        规模边界：本通道的候选集是「授权库 × published × active」的向量行，
        单库资料库场景是几千行量级；外部向量数据库是明确的 deferred 项
        （plan §12），到量之前这里是诚实的成本。
        """
        from memory.embeddings import cosine_similarity

        conn = _connect(self.store)
        try:
            placeholders = ",".join("?" for _ in kb_ids)
            sql = (
                _ACTIVE_CHUNKS_SQL.format(placeholders=placeholders)
                + " AND c.vector IS NOT NULL"
            )
            rows = conn.execute(sql, kb_ids).fetchall()
        finally:
            conn.close()
        scored: list[tuple[int, float]] = []
        for row in rows:
            vec = unpack_vector(row["vector"])
            if not vec or len(vec) != len(query_vec):
                continue
            score = cosine_similarity(query_vec, vec)
            if score > 0.0:
                scored.append((int(row["id"]), score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    # ── 补水与装配 ────────────────────────────────────────

    def _hydrate(self, chunk_ids: list[int]) -> dict[int, dict[str, Any]]:
        """按 rowid 批量取 chunk 原文与文档信息（二次过滤在 SQL 里再跑一遍）。"""
        if not chunk_ids:
            return {}
        conn = _connect(self.store)
        try:
            placeholders = ",".join("?" for _ in chunk_ids)
            sql = (
                "SELECT c.id, c.kb_id, c.doc_id, c.version_no, c.seq, c.text, "
                "c.section_path, c.page, c.paragraph, c.char_start, c.char_end, "
                "d.title AS doc_title, d.source_uri AS doc_uri, d.status AS doc_status, "
                "d.active_version AS doc_active_version, k.name AS kb_name "
                "FROM kb_chunk c "
                "JOIN kb_document d ON d.id = c.doc_id AND d.kb_id = c.kb_id "
                "JOIN kb k ON k.id = c.kb_id "
                f"WHERE c.id IN ({placeholders}) "
                "AND d.status = 'published' AND c.version_no = d.active_version"
            )
            rows = conn.execute(sql, chunk_ids).fetchall()
            return {int(r["id"]): dict(r) for r in rows}
        finally:
            conn.close()


def _locator_of(row: dict[str, Any]):
    from knowledge.domain import ChunkLocator

    return ChunkLocator(
        section_path=row.get("section_path") or "",
        page=int(row.get("page") or 0),
        paragraph=int(row.get("paragraph") or 0),
        char_start=int(row.get("char_start") or 0),
        char_end=int(row.get("char_end") or 0),
    )


def _matched_by(
    chunk_id: int,
    bm25_hits: list[tuple[int, float]],
    dense_hits: list[tuple[int, float]],
) -> str:
    in_bm25 = any(cid == chunk_id for cid, _ in bm25_hits)
    in_dense = any(cid == chunk_id for cid, _ in dense_hits)
    if in_bm25 and in_dense:
        return "both"
    return "bm25" if in_bm25 else "dense"


def _rrf_fuse(
    bm25_hits: list[tuple[int, float]],
    dense_hits: list[tuple[int, float]],
    rrf_k: int,
) -> list[tuple[int, float]]:
    """RRF 融合：同一 chunk 双路命中时分数叠加，排名靠前胜出。"""
    scores: dict[int, float] = {}
    for ranking in (bm25_hits, dense_hits):
        for rank, (chunk_id, _) in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def dedup_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """近重复折叠：规范化文本相同（模板化文档常见）只保留最高分的一条。"""
    from memory.text_similarity import normalize_text

    seen: set[str] = set()
    result: list[Evidence] = []
    for ev in evidence:
        key = normalize_text(ev.text)[:200]
        if key in seen:
            continue
        seen.add(key)
        result.append(ev)
    return result


def _connect(store: KnowledgeStore) -> sqlite3.Connection:
    from knowledge.schema import connect

    conn = connect(store.db_path)
    conn.row_factory = sqlite3.Row
    return conn


__all__ = [
    "HybridRetriever",
    "RetrievalResult",
    "dedup_evidence",
]
