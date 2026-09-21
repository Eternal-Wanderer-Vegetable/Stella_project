# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""knowledge.domain / acl / lifecycle 的单元测试（纯领域层，无 IO）。"""

from __future__ import annotations

import pytest

from knowledge.acl import (
    ACLSnapshot,
    Principal,
    can_manage_kb,
    can_publish,
    can_review,
    can_search,
    can_submit,
    resolve_role,
    role_at_least,
    submit_needs_review,
)
from knowledge.domain import (
    DOC_STATE_ACTIVE,
    DOC_STATE_ARCHIVED,
    DOC_STATE_DRAFT,
    DOC_STATE_IN_REVIEW,
    KB_MODE_MANAGED,
    KB_MODE_SHARED,
    ROLE_CONTRIBUTOR,
    ROLE_MAINTAINER,
    ROLE_VIEWER,
    VERSION_STATE_PENDING,
    VERSION_STATE_READY,
    KBDocument,
    KBDocumentVersion,
    KBGrant,
    KnowledgeBase,
    principal_key,
)
from knowledge.lifecycle import LifecycleError, can_transition, transition


def _kb(**kw) -> KnowledgeBase:
    base: dict = {
        "id": "kb1",
        "name": "测试库",
        "mode": KB_MODE_MANAGED,
        "owner_user_id": "100",
    }
    base.update(kw)
    return KnowledgeBase(**base)


def _snapshot(*grants: KBGrant) -> ACLSnapshot:
    return ACLSnapshot(roles={g.key: g.role for g in grants})


def _grant(kind: str, pid: str, role: str, kb_id: str = "kb1") -> KBGrant:
    return KBGrant(kb_id=kb_id, principal_kind=kind, principal_id=pid, role=role)


# ── domain 基本不变式 ─────────────────────────────────────


def test_principal_key_format() -> None:
    assert principal_key("user", "123") == "user:123"


def test_kb_rejects_bad_mode() -> None:
    with pytest.raises(ValueError):
        _kb(mode="wiki")


def test_grant_rejects_owner_role() -> None:
    # owner 不进授权表：它就是 kb.owner_user_id
    with pytest.raises(ValueError):
        _grant("user", "123", "owner")


def test_version_index_complete_requires_matching_counts() -> None:
    v = KBDocumentVersion(
        kb_id="kb1",
        doc_id="d1",
        version_no=1,
        state=VERSION_STATE_READY,
        chunk_count=3,
        indexed_chunk_count=3,
    )
    assert v.index_complete
    partial = KBDocumentVersion(
        kb_id="kb1",
        doc_id="d1",
        version_no=1,
        state=VERSION_STATE_READY,
        chunk_count=3,
        indexed_chunk_count=2,
    )
    assert not partial.index_complete
    pending = KBDocumentVersion(
        kb_id="kb1",
        doc_id="d1",
        version_no=1,
        state=VERSION_STATE_PENDING,
        chunk_count=3,
        indexed_chunk_count=3,
    )
    assert not pending.index_complete


def test_kb_fingerprint_lock_requires_all_fields() -> None:
    kb = _kb(
        embed_model="bge-m3", embed_dim=1024, embed_encoder="raw-v1", index_version=1
    )
    assert kb.fingerprint_locked()
    half = _kb(embed_model="bge-m3", embed_dim=1024)
    assert not half.fingerprint_locked()


# ── ACL ───────────────────────────────────────────────────


def test_owner_is_owner_everywhere() -> None:
    kb = _kb()
    role = resolve_role(
        kb, Principal(user_id="100", group_id="7", space="s"), _snapshot()
    )
    assert role == "owner"
    assert can_search(kb, role) and can_submit(kb, role)
    assert can_review(kb, role) and can_publish(kb, role)
    assert can_manage_kb(kb, role)


def test_group_and_space_grants_take_max() -> None:
    kb = _kb()
    snap = _snapshot(
        _grant("group", "7", ROLE_VIEWER),
        _grant("space", "s", ROLE_MAINTAINER),
    )
    role = resolve_role(kb, Principal(user_id="1", group_id="7", space="s"), snap)
    assert role == ROLE_MAINTAINER


def test_unrelated_principal_gets_nothing() -> None:
    kb = _kb()
    snap = _snapshot(_grant("user", "555", ROLE_MAINTAINER))
    role = resolve_role(kb, Principal(user_id="1", group_id="7", space="s"), snap)
    assert role is None
    assert not can_search(kb, role)


def test_private_kb_hidden_in_group_chat() -> None:
    """仅 user 授权的库，在群聊里连库主以外的授权人也不可见。"""
    kb = _kb()
    snap = _snapshot(_grant("user", "555", ROLE_MAINTAINER))
    # 私聊：user 授权生效
    assert (
        resolve_role(kb, Principal(user_id="555"), snap, in_group=False)
        == ROLE_MAINTAINER
    )
    # 群聊：同一授权不生效（private 库在群聊不可见）
    assert (
        resolve_role(kb, Principal(user_id="555", group_id="7"), snap, in_group=True)
        is None
    )


def test_group_granted_kb_visible_in_group_chat() -> None:
    kb = _kb()
    snap = _snapshot(_grant("group", "7", ROLE_VIEWER))
    role = resolve_role(kb, Principal(user_id="555", group_id="7"), snap, in_group=True)
    assert role == ROLE_VIEWER
    assert can_search(kb, role)
    assert not can_submit(kb, role)


def test_archived_kb_denies_everyone() -> None:
    kb = _kb(status="archived")
    assert (
        resolve_role(kb, Principal(user_id="100"), _snapshot(), in_group=False) is None
    )


def test_managed_requires_maintainer_to_submit() -> None:
    kb = _kb()
    assert can_submit(kb, ROLE_MAINTAINER)
    assert not can_submit(kb, ROLE_CONTRIBUTOR)


def test_shared_allows_contributor_submit_but_not_publish() -> None:
    kb = _kb(mode=KB_MODE_SHARED)
    assert can_submit(kb, ROLE_CONTRIBUTOR)
    assert not can_publish(kb, ROLE_CONTRIBUTOR)
    assert can_publish(kb, ROLE_MAINTAINER)


def test_direct_publish_review_rules() -> None:
    managed = _kb()
    assert not submit_needs_review(managed, ROLE_MAINTAINER)  # managed：无审核概念
    shared = _kb(mode=KB_MODE_SHARED)
    assert submit_needs_review(shared, ROLE_CONTRIBUTOR)  # 默认要审
    assert not submit_needs_review(shared, ROLE_MAINTAINER)  # 维护者本就有发布权，免审
    shared.direct_publish = True
    assert not submit_needs_review(shared, ROLE_MAINTAINER)
    assert not submit_needs_review(shared, ROLE_CONTRIBUTOR)  # 直发库贡献者免审
    assert not role_at_least(None, ROLE_VIEWER)  # 无授权永为 False


# ── lifecycle ─────────────────────────────────────────────


def _doc(status: str = DOC_STATE_DRAFT) -> KBDocument:
    return KBDocument(id="d1", kb_id="kb1", title="t", status=status)


def _version(complete: bool = True) -> KBDocumentVersion:
    return KBDocumentVersion(
        kb_id="kb1",
        doc_id="d1",
        version_no=1,
        state=VERSION_STATE_READY if complete else VERSION_STATE_PENDING,
        chunk_count=2,
        indexed_chunk_count=2 if complete else 0,
    )


def test_full_review_flow() -> None:
    doc = _doc()
    assert transition(doc, "submit") == DOC_STATE_IN_REVIEW
    assert transition(doc, "publish", version=_version()) == DOC_STATE_ACTIVE
    assert transition(doc, "unpublish") == DOC_STATE_DRAFT


def test_direct_publish_edge() -> None:
    doc = _doc()
    assert transition(doc, "publish", version=_version()) == DOC_STATE_ACTIVE


def test_publish_requires_complete_version() -> None:
    doc = _doc()
    doc.status = DOC_STATE_IN_REVIEW
    with pytest.raises(LifecycleError):
        transition(doc, "publish", version=_version(complete=False))
    with pytest.raises(LifecycleError):
        transition(doc, "publish")  # 不带版本也是错的


def test_illegal_transitions_rejected() -> None:
    doc = _doc(DOC_STATE_ACTIVE)
    assert not can_transition(doc, "submit")
    with pytest.raises(LifecycleError):
        transition(doc, "submit")
    archived = _doc(DOC_STATE_ARCHIVED)
    with pytest.raises(LifecycleError):
        transition(archived, "publish", version=_version())
