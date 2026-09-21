# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""导入管道：解析 → 切块 → （编码）→ 建版本索引 → 就绪。

导入是**异步于回复路径**的（plan §3：ingestion/indexing outside the
synchronous reply path）：调用方（管理入口/未来的 WebUI）把作业丢进来，
``ingest_content`` 在 worker 线程跑完整个管道；每一步的结果落
``kb_import_job``（观测面，plan §6.8），失败原因原样保留。

版本语义（plan §6.3）：

- 内容哈希（规范化全文的 SHA-256）同库唯一 → **重复导入幂等**（duplicate）；
- 同标题再导入且内容变化 → **替换**：新版本号、重建索引、旧版本待激活后
  自动 superseded（replacement）；
- 解析/切块失败 → 版本置 failed + job.failed，错误信息面向操作者
  （parse failure）。

本模块不写向量：``embedder`` 是注入的批量编码回调（``list[str] →
``list[bytes|None]``，BLOB 形态），由 retrieval 侧的 embedding 服务实现
（步骤 5）。注入而非内聚，让「切块入库」与「向量编码」可以独立测试、
独立失败——embedding 服务挂了不阻碍文本索引进 ready（BM25 仍可用，
检索层会标记 dense 降级）。
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from nonebot import logger

from knowledge import chunking
from knowledge.domain import (
    DOC_STATE_DRAFT,
    DOC_STATE_IN_REVIEW,
    IMPORTER_VERSION,
    VERSION_STATE_PENDING,
    VERSION_STATE_READY,
    KBDocument,
    KBDocumentVersion,
    KnowledgeBase,
    ParsedSource,
)
from knowledge.parsers import ParseError
from knowledge.store import KnowledgeStore

Embedder = Callable[[list[str]], list[bytes | None]]

# 内容哈希的规范化：行尾统一、去首尾空白。不同平台导出的同一份文档
# （CRLF/LF 差异）不该被当成两个版本。


def content_fingerprint(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class ImportOutcome:
    """一次导入的结果（service 层转成操作反馈）。"""

    state: str  # ready / duplicate / failed
    doc_id: str = ""
    version_no: int = 0
    chunk_count: int = 0
    vectorized: int = 0
    error: str = ""
    duplicate_of: str = ""  # duplicate 时指向已存在的 doc id

    @property
    def ok(self) -> bool:
        return self.state in ("ready", "duplicate")


def ingest_content(
    store: KnowledgeStore,
    kb: KnowledgeBase,
    source_type: str,
    data: bytes | str,
    *,
    title: str = "",
    uri: str = "",
    submitted_by: str = "",
    needs_review: bool = False,
    embedder: Embedder | None = None,
) -> ImportOutcome:
    """跑完整条导入管道。**不抛异常**——所有失败转成 ``state=failed`` 的结果。

    ``needs_review`` 由 service 层按 ACL/模式判定（见 acl.submit_needs_review）：
    True 时新文档/新版本进 in_review，False 时停在 draft 等待发布动作。
    导入本身**从不发布**——发布是显式的权限动作。
    """
    job_id = uuid.uuid4().hex[:12]
    store.create_job(job_id, kb.id, source_type, uri, submitted_by)
    try:
        parsed = _parse(source_type, data, title=title, uri=uri)
        outcome = _build_version(
            store,
            kb,
            parsed,
            submitted_by=submitted_by,
            needs_review=needs_review,
            embedder=embedder,
        )
    except ParseError as e:
        logger.warning(f"📥 [Knowledge] 导入解析失败（kb={kb.id}）: {e}")
        store.finish_job(job_id, error=str(e))
        return ImportOutcome(state="failed", error=str(e))
    except Exception as e:  # 兜底：任何意外都不炸调用方
        logger.warning(
            f"📥 [Knowledge] 导入失败（kb={kb.id}）: {type(e).__name__}: {e}"
        )
        store.finish_job(job_id, error=f"{type(e).__name__}: {e}")
        return ImportOutcome(state="failed", error=f"{type(e).__name__}: {e}")

    store.finish_job(job_id, doc_id=outcome.doc_id, version_no=outcome.version_no)
    return outcome


def _parse(
    source_type: str, data: bytes | str, *, title: str, uri: str
) -> ParsedSource:
    from knowledge.parsers import parse_content

    return parse_content(source_type, data, title=title, uri=uri)


def _build_version(
    store: KnowledgeStore,
    kb: KnowledgeBase,
    parsed: ParsedSource,
    *,
    submitted_by: str,
    needs_review: bool,
    embedder: Embedder | None,
) -> ImportOutcome:
    from knowledge.store import transaction

    full_text = "\n\n".join(s.text for s in parsed.sections)
    digest = content_fingerprint(full_text)

    # 幂等：同库同哈希已存在 → 直接拒绝（无论新旧版本）
    existing = store.find_document_by_hash(kb.id, digest)
    if existing is not None:
        return ImportOutcome(
            state="duplicate",
            doc_id=existing.id,
            duplicate_of=existing.id,
            error=f"内容与已有文档《{existing.title}》完全相同（重复导入已忽略）",
        )

    # 同标题 → 替换（新版本）；否则新建文档 v1
    doc = _find_by_title(store, kb.id, parsed.title)
    if doc is not None and doc.status != "archived":
        version_no = doc.latest_version + 1
        # 文档身份随内容演进：哈希与来源同步到最新版本，后续重复导入
        # 的新内容靠新哈希判重
        doc.content_hash = digest
        doc.source_uri = parsed.source_uri or doc.source_uri
        store.upsert_document(doc)
    else:
        version_no = 1
        doc = KBDocument(
            id=uuid.uuid4().hex[:12],
            kb_id=kb.id,
            title=parsed.title,
            source_type=parsed.source_type,
            source_uri=parsed.source_uri,
            content_hash=digest,
            status=DOC_STATE_IN_REVIEW if needs_review else DOC_STATE_DRAFT,
            created_by=submitted_by,
        )
        store.upsert_document(doc)

    chunks = chunking.chunk_sections(parsed.sections)
    if not chunks:
        raise ParseError("切块后没有任何可用内容")

    vectors: list[bytes | None] = [None] * len(chunks)
    vectorized = 0
    if embedder is not None:
        blobs = embedder([text for _, text, _ in chunks])
        for idx, blob in enumerate(blobs[: len(chunks)]):
            vectors[idx] = blob
            if blob is not None:
                vectorized += 1

    version = KBDocumentVersion(
        kb_id=kb.id,
        doc_id=doc.id,
        version_no=version_no,
        state=VERSION_STATE_PENDING,
        chunk_count=len(chunks),
        indexed_chunk_count=0,
        content_chars=len(full_text),
        importer_version=IMPORTER_VERSION,
        parser_meta=dict(parsed.meta),
        created_by=submitted_by,
    )
    store.create_version(version)

    with transaction(store.db_path) as conn:
        store.replace_version_chunks(
            conn,
            kb.id,
            doc.id,
            version_no,
            [
                (seq, text, loc, vectors[idx])
                for idx, (seq, text, loc) in enumerate(chunks)
            ],
        )
    version.indexed_chunk_count = len(chunks)
    version.state = VERSION_STATE_READY
    store.update_version(version)
    logger.info(
        f"📥 [Knowledge] 文档《{doc.title}》v{version_no} 索引就绪"
        f"（{len(chunks)} 块，{vectorized} 块已编码）"
    )
    return ImportOutcome(
        state="ready",
        doc_id=doc.id,
        version_no=version_no,
        chunk_count=len(chunks),
        vectorized=vectorized,
    )


def _find_by_title(store: KnowledgeStore, kb_id: str, title: str) -> KBDocument | None:
    for doc in store.list_documents(kb_id):
        if doc.title == title:
            return doc
    return None


__all__ = [
    "Embedder",
    "ImportOutcome",
    "content_fingerprint",
    "ingest_content",
]
