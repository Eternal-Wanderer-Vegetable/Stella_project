# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""文档生命周期状态机。

发布语义（plan §6.5）：managed 库「维护者发布」，shared 库「成员投稿 + 维护者
审核」，直发是库主的库级开关（对维护者以上生效，见 acl.submit_needs_review）。

状态图（doc.status）：

```
draft ──submit──▶ in_review ──publish──▶ published ──archive──▶ archived
  ▲                   │                                            │
  └───── reject ──────┘        unpublish（撤回到草稿）▲             │
                                                            └── ◀──────┘
```

不变式（transition 负责强制，service/store 不许绕过它改状态）：

1. 只有合法边才能走；非法迁移抛 ``LifecycleError``；
2. ``publish`` 的语义是「把一个 ready 版本置为文档的 active 版本」——发布
   必须带 ``version_no``，且该版本必须已通过索引完整性校验（index_complete）；
   没有 ready 版本的发布是建模错误，不是运行时错误；
3. ``archive`` 终态：归档后的文档不再参与检索，也不允许复活（重新导入
   同一内容会生成新文档，而不是唤醒旧文档——哈希唯一约束保证这一点）。
"""

from __future__ import annotations

from knowledge.domain import (
    DOC_STATE_ACTIVE,
    DOC_STATE_ARCHIVED,
    DOC_STATE_DRAFT,
    DOC_STATE_IN_REVIEW,
    KBDocument,
    KBDocumentVersion,
)

# 合法迁移边：from → to（附带该边要求的动作名，报错时可读）
_TRANSITIONS: dict[tuple[str, str], str] = {
    (DOC_STATE_DRAFT, DOC_STATE_IN_REVIEW): "submit",
    (DOC_STATE_IN_REVIEW, DOC_STATE_ACTIVE): "publish",
    # 直发（免审）边：managed 库的上传、shared 开直发库的维护者投稿，
    # 不经过 in_review 直接发布（acl.submit_needs_review 决定走不走这条边）。
    (DOC_STATE_DRAFT, DOC_STATE_ACTIVE): "publish",
    (DOC_STATE_IN_REVIEW, DOC_STATE_DRAFT): "reject",
    (DOC_STATE_ACTIVE, DOC_STATE_DRAFT): "unpublish",
    (DOC_STATE_ACTIVE, DOC_STATE_ARCHIVED): "archive",
    (DOC_STATE_ARCHIVED, DOC_STATE_ARCHIVED): "archive",  # 幂等边：重复归档无害
}


class LifecycleError(ValueError):
    """非法生命周期迁移。service 层捕获后转成明确的操作错误。"""


def can_transition(doc: KBDocument, action: str) -> bool:
    """当前状态下能否执行该动作（纯查询，不改状态）。"""
    target = _target_of(doc.status, action)
    return target is not None


def transition(
    doc: KBDocument,
    action: str,
    *,
    version: KBDocumentVersion | None = None,
) -> str:
    """执行生命周期迁移，返回目标状态；非法迁移抛 ``LifecycleError``。

    ``publish`` 必须携带一个 ``index_complete`` 的版本——发布不是改一个字符串，
    是「把这份内容承诺给所有能检索这个库的人」，内容必须已经完整入索引。
    """
    target = _target_of(doc.status, action)
    if target is None:
        raise LifecycleError(
            f"文档处于 {doc.status} 状态，不允许执行 {action}"
            f"（合法动作见 knowledge.lifecycle._TRANSITIONS）"
        )
    if action == "publish":
        if version is None:
            raise LifecycleError("发布必须指定要激活的版本")
        if not version.index_complete:
            raise LifecycleError(
                f"版本 v{version.version_no} 索引不完整"
                f"（{version.indexed_chunk_count}/{version.chunk_count}），不能发布"
            )
    doc.status = target
    return target


def _target_of(status: str, action: str) -> str | None:
    for (src, dst), act in _TRANSITIONS.items():
        if src == status and act == action:
            return dst
    return None


__all__ = [
    "LifecycleError",
    "can_transition",
    "transition",
]
