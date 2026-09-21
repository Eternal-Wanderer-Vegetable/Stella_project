# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""知识库领域模型。

纯数据与不变式，不 import 任何存储 / 配置 / nonebot 模块——领域层必须是整个
子系统里最稳定、最可单测的部分。两层模型：

- **行记录**（``KnowledgeBase`` / ``KBDocument`` / ``KBDocumentVersion`` /
  ``KBGrant``）：与 ``knowledge.db`` 的行一一对应，store 层的读写单位；
- **值对象**（``ParsedSource`` / ``ParsedSection`` / ``ChunkLocator`` /
  ``Evidence``）：导入与检索管道的中间产物与最终输出。

归属主键（principal）刻意与记忆系统的两层归属对齐（见 config/spaces.py）：
``user:<qq号>``、``group:<QQ群号>``、``space:<群组共享空间名>`` 三种授权主体并存——
「授权给某个真实群」与「授权给整个共享空间」是两个不同的决定，混用一个字段
会把它们变成同一件事。知识库身份**绝不**复用 ``group_shared_space``（那是个人
记忆的归属，方案红线）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── 知识库模式（plan §6.5）──────────────────────────────
# managed：管理员统一维护。成员默认只读；上传与发布都收在维护者手里。
# shared ：成员共建。成员可投稿（默认需维护者审核）；库主可为低风险库开直发。
KB_MODE_MANAGED = "managed"
KB_MODE_SHARED = "shared"
KB_MODES = frozenset({KB_MODE_MANAGED, KB_MODE_SHARED})

# ── 知识库状态 ─────────────────────────────────────────
KB_STATUS_ACTIVE = "active"
KB_STATUS_ARCHIVED = "archived"
KB_STATUSES = frozenset({KB_STATUS_ACTIVE, KB_STATUS_ARCHIVED})

# ── 授权主体（plan §6.1：ACL subjects）──────────────────
PRINCIPAL_USER = "user"
PRINCIPAL_GROUP = "group"
PRINCIPAL_SPACE = "space"
PRINCIPAL_KINDS = frozenset({PRINCIPAL_USER, PRINCIPAL_GROUP, PRINCIPAL_SPACE})

# ── 角色（plan §6.5：upload 与 publish 权限分离）────────
# 越大越强；判定一律走 ROLE_RANKS 比较而不是字符串相等。
ROLE_VIEWER = "viewer"  # 可检索（仅 published 内容）
ROLE_CONTRIBUTOR = "contributor"  # 可投稿（shared 库；managed 库投稿=维护者）
ROLE_MAINTAINER = "maintainer"  # 可上传 / 审核 / 发布 / 管理 ACL（不含删库）
ROLE_OWNER = "owner"  # 库主：全部权限 + 归档 / 删除库 / 开关直发
ROLE_RANKS: dict[str, int] = {
    ROLE_VIEWER: 0,
    ROLE_CONTRIBUTOR: 1,
    ROLE_MAINTAINER: 2,
    ROLE_OWNER: 3,
}

# ── 文档生命周期（doc 的业务状态；plan §6.5 草稿/审核/发布）──
DOC_STATE_DRAFT = "draft"
DOC_STATE_IN_REVIEW = "in_review"
DOC_STATE_ACTIVE = "published"  # 值用 published：对外语义是「已发布」
DOC_STATE_ARCHIVED = "archived"
DOC_STATES = (
    DOC_STATE_DRAFT,
    DOC_STATE_IN_REVIEW,
    DOC_STATE_ACTIVE,
    DOC_STATE_ARCHIVED,
)

# ── 版本索引状态（版本的技术状态，与 doc 的业务状态正交）──
# pending：解析/切块/编码进行中；ready：索引完整可激活；active：当前生效；
# superseded：被更新版本取代；failed：导入失败（error 落库）。
VERSION_STATE_PENDING = "pending"
VERSION_STATE_READY = "ready"
VERSION_STATE_ACTIVE = "active"
VERSION_STATE_SUPERSEDED = "superseded"
VERSION_STATE_FAILED = "failed"
VERSION_STATES = frozenset(
    {
        VERSION_STATE_PENDING,
        VERSION_STATE_READY,
        VERSION_STATE_ACTIVE,
        VERSION_STATE_SUPERSEDED,
        VERSION_STATE_FAILED,
    }
)

# 导入器版本：解析规则变更（定位符语义、切块边界）时 +1，旧版本号的
# 定位符含义保持可解释。内容哈希不含它；它随版本记录落库。
IMPORTER_VERSION = 1

# 切块目标长度（字符）。中文场景 ~500 字是一段语义完整的讲述；切块只做
# 上限保护，硬边界见 chunking.py。
CHUNK_TARGET_CHARS = 500


def principal_key(kind: str, principal_id: str) -> str:
    """授权主体的规范键（``user:123``）；store 层用它做唯一约束。"""
    return f"{kind}:{principal_id}"


@dataclass
class KBGrant:
    """一条 ACL 授权：某主体在某库上的角色。

    owner 角色不通过本表授予——它就是 ``KnowledgeBase.owner_user_id``，
    授权表里写 owner 是建模错误（库主易主要走库级操作，不是加一行 ACL）。
    """

    kb_id: str
    principal_kind: str
    principal_id: str
    role: str = ROLE_VIEWER
    granted_by: str = ""
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.principal_kind not in PRINCIPAL_KINDS:
            raise ValueError(f"非法授权主体类型: {self.principal_kind}")
        if self.role not in ROLE_RANKS or self.role == ROLE_OWNER:
            raise ValueError(f"非法授权角色: {self.role}")

    @property
    def key(self) -> str:
        return principal_key(self.principal_kind, self.principal_id)


@dataclass
class KnowledgeBase:
    """一个知识库。

    embedding 指纹四元组（plan §6.4）：库创建/首次编码时锁定 model / dim /
    encoder / index_version；此后任何一项变化都要求重建（``fingerprint``
    不匹配的版本一律不得激活，检索侧降级为纯 BM25 并标记 needs_rebuild）。
    """

    id: str
    name: str
    mode: str = KB_MODE_MANAGED
    owner_user_id: str = ""
    direct_publish: bool = False  # 仅 shared 库可开：投稿免审核直接发布
    status: str = KB_STATUS_ACTIVE
    description: str = ""
    # embedding 指纹（空 = 尚未锁定，首次写入向量时锁定）
    embed_model: str = ""
    embed_dim: int = 0
    embed_encoder: str = ""  # 编码约定版本（裸文本/前缀/归一化规则）
    index_version: int = 0  # 索引结构版本（FTS 分词/向量存储格式）
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.mode not in KB_MODES:
            raise ValueError(f"非法知识库模式: {self.mode}")
        if self.status not in KB_STATUSES:
            raise ValueError(f"非法知识库状态: {self.status}")

    @property
    def is_archived(self) -> bool:
        return self.status == KB_STATUS_ARCHIVED

    def fingerprint(self) -> dict[str, Any]:
        """当前 embedding 指纹（供 ingest / retrieval 比对）。"""
        return {
            "model": self.embed_model,
            "dim": self.embed_dim,
            "encoder": self.embed_encoder,
            "index_version": self.index_version,
        }

    def fingerprint_locked(self) -> bool:
        """是否已锁定 embedding 指纹（四项齐全才算）。"""
        return bool(
            self.embed_model
            and self.embed_dim
            and self.embed_encoder
            and self.index_version
        )


@dataclass
class KBDocument:
    """一篇文档的「身份」：标题、来源、内容哈希与生命周期状态。

    ``content_hash`` 是**导入内容**的 SHA-256（不含定位符与切块边界），
    同库唯一——重复导入同一份内容直接命中幂等（plan 测试策略：duplicate hash）。
    ``active_version`` 指向当前对外可见的版本号（0 = 从未发布过）。
    """

    id: str
    kb_id: str
    title: str
    source_type: str = "markdown"
    source_uri: str = ""
    content_hash: str = ""
    status: str = DOC_STATE_DRAFT
    active_version: int = 0
    latest_version: int = 0
    created_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.status not in DOC_STATES:
            raise ValueError(f"非法文档状态: {self.status}")

    @property
    def is_published(self) -> bool:
        return self.status == DOC_STATE_ACTIVE


@dataclass
class KBDocumentVersion:
    """文档的一个不可变版本：内容 + 为它构建的整份索引。

    版本是原子激活的单位（plan §6.3）：ingest 把新版本的所有 chunk 与向量
    写完、校验数量一致后才把状态置 ready；激活（active）在单个事务里完成
    「旧版本 superseded + 新版本 active + doc.active_version 前移」。
    """

    kb_id: str
    doc_id: str
    version_no: int
    state: str = VERSION_STATE_PENDING
    chunk_count: int = 0
    indexed_chunk_count: int = 0  # 已完成编码+入索引的 chunk 数（进度观测）
    content_chars: int = 0
    importer_version: int = IMPORTER_VERSION
    parser_meta: dict[str, Any] = field(default_factory=dict)  # 页数/段落数等
    error: str = ""
    created_by: str = ""
    created_at: str = ""
    activated_at: str = ""

    def __post_init__(self) -> None:
        if self.state not in VERSION_STATES:
            raise ValueError(f"非法版本状态: {self.state}")

    @property
    def index_complete(self) -> bool:
        """索引是否完整（激活的必要条件：计数一致且无错误）。"""
        return (
            self.state in (VERSION_STATE_READY, VERSION_STATE_ACTIVE)
            and self.chunk_count > 0
            and self.indexed_chunk_count == self.chunk_count
            and not self.error
        )


@dataclass
class DocumentRecord:
    """文档 + 当前生效版本的组合视图（检索命中与状态接口用）。"""

    document: KBDocument
    version: KBDocumentVersion | None = None


@dataclass
class ChunkLocator:
    """来源定位符（plan 验收：每个摘录都有稳定引用与定位）。

    ``section_path`` 是「第一章 > 第二节」形态的标题路径（Markdown/DOCX）；
    PDF 用页码；纯文本用段落号。全部可空但至少一项非空，否则引用无从谈起。
    """

    section_path: str = ""
    page: int = 0  # 0 = 无页码概念
    paragraph: int = 0  # 0 = 无段落编号
    char_start: int = 0
    char_end: int = 0

    def display(self) -> str:
        """人读形态（引用渲染用）：至少能说出「哪一段」。"""
        parts: list[str] = []
        if self.section_path:
            parts.append(self.section_path)
        if self.page:
            parts.append(f"p{self.page}")
        if self.paragraph:
            parts.append(f"¶{self.paragraph}")
        return " > ".join(parts) if parts else "原文"


@dataclass
class ParsedSection:
    """解析器产出的一节内容：文本 + 它在原文中的定位。"""

    text: str
    locator: ChunkLocator = field(default_factory=ChunkLocator)


@dataclass
class ParsedSource:
    """一次成功解析的完整结果（导入管道的输入）。"""

    title: str
    source_type: str
    source_uri: str = ""
    sections: list[ParsedSection] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    """一条检索证据：摘录 + 稳定引用（进 prompt 的最终形态）。

    刻意只带展示所需的最小字段；``score`` / ``matched_by`` 是诊断信息，
    允许进状态接口、不进 prompt。
    """

    kb_id: str
    kb_name: str
    doc_id: str
    doc_title: str
    version_no: int
    chunk_seq: int
    text: str
    locator: ChunkLocator = field(default_factory=ChunkLocator)
    source_uri: str = ""
    score: float = 0.0
    matched_by: str = ""  # bm25 / dense / both（RRF 融合诊断）

    def citation(self) -> str:
        """规范引用串：``《标题》 §定位 (库:名)``。"""
        loc = self.locator.display()
        base = (
            f"《{self.doc_title}》 {loc}" if loc != "原文" else f"《{self.doc_title}》"
        )
        if self.kb_name:
            base += f"（资料库:{self.kb_name}）"
        return base
