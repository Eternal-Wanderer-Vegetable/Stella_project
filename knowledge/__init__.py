# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""独立知识库子系统（knowledge）。

与个人记忆（memory/）平行的有界子系统：管理员统一维护的资料库（managed）与
成员共建的共享资料库（shared），支持 Markdown/TXT/文本型 PDF/DOCX/显式选择的
URL 导入，ACL 隔离、草稿/审核/发布生命周期、版本化索引、混合检索（BM25 + 语义）
与有边界的引用式证据注入。

**隔离纪律**（设计约束，见 docs/knowledge-base.md）：

1. 存储隔离：知识库使用独立的 ``knowledge.db``，**绝不**复用 ``agent_memory.db``
   的任何表——记忆的清理、晋升、保留策略不得触碰外部文档；
2. 上下文隔离：检索证据落在 ``ChatContext.knowledge_evidence``，与
   ``tool_summaries`` / ``memories_for_prompt`` 三轨分离，各自有独立的预算；
3. 晋升隔离：知识证据**永远不是**个人记忆的候选来源（见 ``isolation.py``）。

模块导出遵循「领域类型优先」：上层只 import 本包的领域对象与服务入口，
不直接触碰存储细节（``store.py`` / ``schema.py`` 是 knowledge 包的内部实现）。
"""

from knowledge.domain import (
    CHUNK_TARGET_CHARS,
    DOC_STATE_ACTIVE,
    DOC_STATE_ARCHIVED,
    DOC_STATE_DRAFT,
    DOC_STATE_IN_REVIEW,
    DOC_STATES,
    IMPORTER_VERSION,
    KB_MODE_MANAGED,
    KB_MODE_SHARED,
    KB_MODES,
    KB_STATUS_ACTIVE,
    KB_STATUS_ARCHIVED,
    KB_STATUSES,
    PRINCIPAL_GROUP,
    PRINCIPAL_KINDS,
    PRINCIPAL_SPACE,
    PRINCIPAL_USER,
    ROLE_CONTRIBUTOR,
    ROLE_MAINTAINER,
    ROLE_OWNER,
    ROLE_RANKS,
    ROLE_VIEWER,
    VERSION_STATE_ACTIVE,
    VERSION_STATE_FAILED,
    VERSION_STATE_PENDING,
    VERSION_STATE_READY,
    VERSION_STATE_SUPERSEDED,
    VERSION_STATES,
    ChunkLocator,
    DocumentRecord,
    Evidence,
    KBDocument,
    KBDocumentVersion,
    KBGrant,
    KnowledgeBase,
    ParsedSection,
    ParsedSource,
    principal_key,
)
from knowledge.lifecycle import (
    can_transition,
    transition,
)

__all__ = [
    "CHUNK_TARGET_CHARS",
    "DOC_STATES",
    "DOC_STATE_ACTIVE",
    "DOC_STATE_ARCHIVED",
    "DOC_STATE_DRAFT",
    "DOC_STATE_IN_REVIEW",
    "IMPORTER_VERSION",
    "KB_MODES",
    "KB_MODE_MANAGED",
    "KB_MODE_SHARED",
    "KB_STATUSES",
    "KB_STATUS_ACTIVE",
    "KB_STATUS_ARCHIVED",
    "PRINCIPAL_GROUP",
    "PRINCIPAL_KINDS",
    "PRINCIPAL_SPACE",
    "PRINCIPAL_USER",
    "ROLE_CONTRIBUTOR",
    "ROLE_MAINTAINER",
    "ROLE_OWNER",
    "ROLE_RANKS",
    "ROLE_VIEWER",
    "VERSION_STATES",
    "VERSION_STATE_ACTIVE",
    "VERSION_STATE_FAILED",
    "VERSION_STATE_PENDING",
    "VERSION_STATE_READY",
    "VERSION_STATE_SUPERSEDED",
    "ChunkLocator",
    "DocumentRecord",
    "Evidence",
    "KBDocument",
    "KBDocumentVersion",
    "KBGrant",
    "KnowledgeBase",
    "ParsedSection",
    "ParsedSource",
    "can_transition",
    "principal_key",
    "transition",
]
