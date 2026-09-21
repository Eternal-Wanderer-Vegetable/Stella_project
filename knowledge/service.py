# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""知识库服务层：角色 API、发布流程与 ACL 强制检索的唯一入口。

上层（capability provider、未来的管理面）只与本模块对话。三条铁律：

1. **所有写操作先过 ACL**（``acl.py`` 的判定谓词），store 层不做二次判定——
   但 store 也绝不提供绕过 service 的公开捷径（模块私有约定）；
2. **检索前圈定授权集，补水后再过滤**（plan §9 permission leakage 的
   两道闸）：``search`` 先解析 principal 能看到的库集合（空集合直接短路，
   不碰任何数据），retrieval 层的 SQL 再按 published+active 过滤一遍；
3. **导入永不隐式发布**：发布是显式的权限动作（``publish``），唯一例外是
   「无需审核」的投稿（managed 维护者上传 / shared 直发库）——那不是隐式，
   是策略（``acl.submit_needs_review``）判定该投稿无需第二个人点头。

导入是 CPU/IO 密集的解析+编码过程，``submit`` 把它丢进 worker 线程
（``asyncio.to_thread``），**绝不在回复路径上同步执行**（plan §3）。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nonebot import logger

from config import KNOWLEDGE_DB_PATH
from knowledge import lifecycle
from knowledge.acl import (
    Principal,
    can_manage_acl,
    can_manage_kb,
    can_publish,
    can_review,
    can_submit,
    resolve_role,
    submit_needs_review,
)
from knowledge.domain import (
    KB_MODE_MANAGED,
    KB_MODE_SHARED,
    ROLE_VIEWER,
    KBDocument,
    KnowledgeBase,
)
from knowledge.embedding import KBEmbedder, fingerprint_matches
from knowledge.ingest import ImportOutcome, ingest_content
from knowledge.retrieval import HybridRetriever, RetrievalResult, dedup_evidence
from knowledge.store import KnowledgeStore


class KnowledgePermissionError(PermissionError):
    """ACL 拒绝。message 面向操作者，不泄露库的存在与否之外的信息。"""


class KnowledgeStateError(ValueError):
    """生命周期/状态不允许该操作（如重复发布、激活未就绪版本）。"""


@dataclass
class SearchResult:
    """一次授权检索的产出（capability 层转成 evidence / 状态）。"""

    evidence: list = field(default_factory=list)
    authorized_kb_ids: list[str] = field(default_factory=list)
    denied_kb_ids: list[str] = field(default_factory=list)  # 显式请求但无权限的库
    dense_available: bool = False
    needs_rebuild: bool = False
    degraded: str = ""


class KnowledgeService:
    """知识库门面。一个进程一个实例（见模块级 ``get_service``）。"""

    def __init__(
        self,
        db_path: Path | str = KNOWLEDGE_DB_PATH,
        *,
        store: KnowledgeStore | None = None,
        embedder: KBEmbedder | None = None,
        retriever: HybridRetriever | None = None,
    ):
        self.store = store or KnowledgeStore(db_path)
        self.embedder = embedder or KBEmbedder()
        self.retriever = retriever or HybridRetriever(self.store, self.embedder)

    # ── 库管理（plan §6.1 / §6.5）─────────────────────────

    def create_kb(
        self,
        *,
        name: str,
        mode: str,
        owner_user_id: str,
        description: str = "",
        direct_publish: bool = False,
    ) -> KnowledgeBase:
        if mode not in (KB_MODE_MANAGED, KB_MODE_SHARED):
            raise KnowledgeStateError(f"非法模式: {mode}")
        kb = KnowledgeBase(
            id=uuid.uuid4().hex[:12],
            name=name,
            mode=mode,
            owner_user_id=owner_user_id,
            direct_publish=bool(direct_publish) and mode == KB_MODE_SHARED,
            description=description,
            created_by=owner_user_id,
        )
        self.store.create_kb(kb)
        logger.info(
            f"📚 [Knowledge] 知识库「{name}」已创建（{mode}, owner={owner_user_id}）"
        )
        return kb

    def archive_kb(self, kb_id: str, actor: Principal) -> None:
        kb, role = self._require_kb(kb_id, actor)
        if not can_manage_kb(kb, role):
            raise KnowledgePermissionError("只有库主可以归档知识库")
        kb.status = "archived"
        self.store.update_kb(kb)

    def set_direct_publish(self, kb_id: str, enabled: bool, actor: Principal) -> None:
        kb, role = self._require_kb(kb_id, actor)
        if not can_manage_kb(kb, role):
            raise KnowledgePermissionError("只有库主可以开关直发")
        if kb.mode != KB_MODE_SHARED and enabled:
            raise KnowledgeStateError("仅 shared 库支持直发")
        kb.direct_publish = enabled
        self.store.update_kb(kb)

    # ── ACL 管理 ─────────────────────────────────────────

    def grant(
        self,
        kb_id: str,
        *,
        principal_kind: str,
        principal_id: str,
        role: str,
        actor: Principal,
    ) -> None:
        from knowledge.domain import KBGrant

        kb, actor_role = self._require_kb(kb_id, actor)
        if not can_manage_acl(kb, actor_role):
            raise KnowledgePermissionError("需要维护者以上权限才能管理授权")
        if principal_kind == "user" and principal_id == kb.owner_user_id:
            raise KnowledgeStateError("库主无需授权")
        self.store.set_grant(
            KBGrant(
                kb_id=kb_id,
                principal_kind=principal_kind,
                principal_id=principal_id,
                role=role,
                granted_by=actor.user_id,
            )
        )

    def revoke(
        self, kb_id: str, *, principal_kind: str, principal_id: str, actor: Principal
    ) -> None:
        kb, actor_role = self._require_kb(kb_id, actor)
        if not can_manage_acl(kb, actor_role):
            raise KnowledgePermissionError("需要维护者以上权限才能管理授权")
        self.store.remove_grant(kb_id, principal_kind, principal_id)

    # ── 投稿 / 审核 / 发布（plan §6.5 生命周期）───────────

    async def submit(
        self,
        kb_id: str,
        *,
        source_type: str,
        data: bytes | str,
        title: str = "",
        uri: str = "",
        actor: Principal,
    ) -> ImportOutcome:
        """投稿。走 worker 线程，不阻塞事件循环；失败转成 failed 结果。"""
        kb, role = self._require_kb(kb_id, actor)
        if not can_submit(kb, role):
            raise KnowledgePermissionError(
                "没有向该资料库投稿的权限"
                if role is not None
                else "没有访问该资料库的权限"
            )
        needs_review = submit_needs_review(kb, role)
        outcome = await asyncio.to_thread(
            ingest_content,
            self.store,
            kb,
            source_type,
            data,
            title=title,
            uri=uri,
            submitted_by=actor.user_id,
            needs_review=needs_review,
            embedder=self.embedder.embed_batch_sync,
        )
        # 首次拿到向量即锁定库指纹（plan §6.4）；锁定后检索侧才能做一致性判定
        if outcome.ok and outcome.vectorized > 0 and not kb.fingerprint_locked():
            profile = self.embedder.profile
            kb.embed_model = profile["model"]
            kb.embed_dim = profile["dim"]
            kb.embed_encoder = profile["encoder"]
            kb.index_version = profile["index_version"]
            self.store.update_kb(kb)
        # 免审投稿（managed 上传 / shared 直发库）直接发布——见模块 docstring 第 3 条。
        # 走内部 _activate 而不是 publish()：自动发布是**策略**判定（needs_review=False
        # 由 ACL/模式推导），不是投稿人在行使发布权限（shared 直发库的贡献者
        # 并没有 publish 权限）。
        if outcome.ok and outcome.state == "ready" and not needs_review:
            await self._activate(kb_id, outcome.doc_id, outcome.version_no)
        return outcome

    async def publish(
        self,
        kb_id: str,
        doc_id: str,
        version_no: int | None = None,
        *,
        actor: Principal,
    ) -> None:
        """发布：把一个索引完整的版本置为文档的 active 版本（原子激活）。"""
        kb, role = self._require_kb(kb_id, actor)
        if not can_publish(kb, role):
            raise KnowledgePermissionError("没有发布权限")
        await self._activate(kb_id, doc_id, version_no)

    async def _activate(self, kb_id: str, doc_id: str, version_no: int | None) -> None:
        doc = self.store.get_document(doc_id)
        if doc is None or doc.kb_id != kb_id:
            raise KnowledgeStateError("文档不存在")
        version_no = version_no or doc.latest_version
        version = self.store.get_version(doc_id, version_no)
        if version is None:
            raise KnowledgeStateError(f"版本 v{version_no} 不存在")
        lifecycle.transition(doc, "publish", version=version)
        self.store.activate_version(doc_id, version_no)
        logger.info(f"📚 [Knowledge] 《{doc.title}》v{version_no} 已发布（kb={kb_id}）")

    async def reject(
        self, kb_id: str, doc_id: str, *, actor: Principal, reason: str = ""
    ) -> None:
        kb, role = self._require_kb(kb_id, actor)
        if not can_review(kb, role):
            raise KnowledgePermissionError("没有审核权限")
        doc = self._doc_of(kb_id, doc_id)
        lifecycle.transition(doc, "reject")
        self.store.upsert_document(doc)

    async def unpublish(self, kb_id: str, doc_id: str, *, actor: Principal) -> None:
        kb, role = self._require_kb(kb_id, actor)
        if not can_publish(kb, role):
            raise KnowledgePermissionError("没有发布权限")
        doc = self._doc_of(kb_id, doc_id)
        lifecycle.transition(doc, "unpublish")
        self.store.upsert_document(doc)

    async def archive_document(
        self, kb_id: str, doc_id: str, *, actor: Principal
    ) -> None:
        kb, role = self._require_kb(kb_id, actor)
        if not can_publish(kb, role):
            raise KnowledgePermissionError("没有下架权限")
        doc = self._doc_of(kb_id, doc_id)
        lifecycle.transition(doc, "archive")
        self.store.upsert_document(doc)

    # ── 检索（ACL 强制，plan §6.4 / §6.6）─────────────────

    async def search(
        self,
        query: str,
        actor: Principal,
        *,
        in_group: bool = False,
        kb_ids: list[str] | None = None,
    ) -> SearchResult:
        """授权域内检索。

        ``kb_ids`` 是显式指定（capability 的 KB 选择参数）；不给 = 全部
        有权库。显式指定了但无权限的库记入 ``denied_kb_ids``——**静默跳过**，
        不报错也不返回其任何元数据。
        """
        authorized: list[str] = []
        denied: list[str] = []
        for kb in self.store.list_kbs():
            role = resolve_role(
                kb, actor, self.store.acl_snapshot(kb.id), in_group=in_group
            )
            if role is not None and self._role_can_search(role):
                authorized.append(kb.id)
            elif kb_ids and kb.id in kb_ids:
                denied.append(kb.id)
        if kb_ids is not None:
            authorized = [kb_id for kb_id in authorized if kb_id in kb_ids]

        result = SearchResult(authorized_kb_ids=authorized, denied_kb_ids=denied)
        if not authorized:
            return result

        retrieval: RetrievalResult = await self.retriever.search(
            query, authorized, top_k=None
        )
        result.evidence = dedup_evidence(retrieval.evidence)
        result.dense_available = retrieval.dense_available
        result.needs_rebuild = retrieval.needs_rebuild
        result.degraded = retrieval.degraded
        return result

    # ── 观测面（plan §6.8）────────────────────────────────

    def kb_status(self, kb_id: str, actor: Principal) -> dict[str, Any]:
        """导入/索引状态、失败、active 版本与授权摘要（脱敏：需 viewer 以上）。"""
        kb, role = self._require_kb(kb_id, actor)
        if role is None or not self._role_can_search(role):
            raise KnowledgePermissionError("没有查看该资料库的权限")
        documents = self.store.list_documents(kb_id)
        current = self.embedder.profile
        status: dict[str, Any] = {
            "kb_id": kb.id,
            "name": kb.name,
            "mode": kb.mode,
            "status": kb.status,
            "direct_publish": kb.direct_publish,
            "fingerprint": kb.fingerprint(),
            "fingerprint_locked": kb.fingerprint_locked(),
            "fingerprint_matches_current": (
                fingerprint_matches(kb.fingerprint(), current)
                if kb.fingerprint_locked()
                else None
            ),
            "document_count": len(documents),
            "published_count": sum(1 for d in documents if d.is_published),
            "documents": [
                {
                    "doc_id": d.id,
                    "title": d.title,
                    "status": d.status,
                    "source_type": d.source_type,
                    "active_version": d.active_version,
                    "latest_version": d.latest_version,
                }
                for d in documents[:50]
            ],
            "recent_jobs": self.store.recent_jobs(kb_id, limit=10),
            "grants": [
                {
                    "principal": f"{g.principal_kind}:{g.principal_id}",
                    "role": g.role,
                }
                for g in self.store.list_grants(kb_id)
            ],
        }
        return status

    def list_accessible_kbs(
        self, actor: Principal, *, in_group: bool = False
    ) -> list[dict[str, Any]]:
        """主体可见的库列表（未授权的库不出现在列表里——元数据也不给）。"""
        visible: list[dict[str, Any]] = []
        for kb in self.store.list_kbs():
            role = resolve_role(
                kb, actor, self.store.acl_snapshot(kb.id), in_group=in_group
            )
            if role is not None and self._role_can_search(role):
                visible.append(
                    {"kb_id": kb.id, "name": kb.name, "mode": kb.mode, "role": role}
                )
        return visible

    # ── 内部 ─────────────────────────────────────────────

    def _require_kb(
        self, kb_id: str, actor: Principal
    ) -> tuple[KnowledgeBase, str | None]:
        kb = self.store.get_kb(kb_id)
        if kb is None:
            raise KnowledgeStateError("资料库不存在")
        role = resolve_role(kb, actor, self.store.acl_snapshot(kb_id))
        return kb, role

    def _doc_of(self, kb_id: str, doc_id: str) -> KBDocument:
        doc = self.store.get_document(doc_id)
        if doc is None or doc.kb_id != kb_id:
            raise KnowledgeStateError("文档不存在")
        return doc

    @staticmethod
    def _role_can_search(role: str | None) -> bool:
        from knowledge.acl import role_at_least

        return role_at_least(role, ROLE_VIEWER)


# ── 进程级单例（与 capability.registry 同理：必须模块级，否则不同 import
#    路径各拿一份，表现为「明明建了库却检索不到」）────────────────────

_service: KnowledgeService | None = None


def get_service() -> KnowledgeService:
    global _service
    if _service is None:
        _service = KnowledgeService()
    return _service


def reset_service() -> None:
    """测试与热重载用：下一个 ``get_service`` 重建实例。"""
    global _service
    _service = None


__all__ = [
    "KnowledgePermissionError",
    "KnowledgeService",
    "KnowledgeStateError",
    "SearchResult",
    "get_service",
    "reset_service",
]
