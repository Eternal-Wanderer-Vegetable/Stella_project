# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""知识库管理（方案 §6.7）。全部经 ``knowledge.service.get_service()`` 门面。

WebUI 管理员身份：``Principal(user_id="webui-admin")``——knowledge 没有
特权绕过；本服务创建的库 owner 即该 id，因此自建自管。隔离红线不受影响：
知识库证据不进记忆（knowledge/isolation.py 与本层无关地继续生效）。
"""

from __future__ import annotations

from knowledge.acl import Principal
from knowledge.service import get_service

ADMIN = "webui-admin"


def _actor() -> Principal:
    return Principal(user_id=ADMIN)


def list_kbs() -> list[dict]:
    return get_service().list_accessible_kbs(_actor())


def create_kb(name: str, *, description: str = "") -> dict:
    kb = get_service().create_kb(
        name=name, mode="managed", owner_user_id=ADMIN, description=description
    )
    return {
        "kb_id": kb.kb_id,
        "name": kb.name,
        "description": getattr(kb, "description", description),
    }


def kb_detail(kb_id: str) -> dict:
    return get_service().kb_status(kb_id, _actor())


def archive(kb_id: str) -> dict:
    get_service().archive_kb(kb_id, _actor())
    return {"kb_id": kb_id, "archived": True}


async def submit_document(
    kb_id: str, *, data: bytes | str, title: str = "", uri: str = "", source_type: str = "file"
) -> dict:
    outcome = await get_service().submit(
        kb_id, source_type=source_type, data=data, title=title, uri=uri, actor=_actor()
    )
    return {
        "ok": outcome.ok,
        "state": outcome.state,
        "doc_id": outcome.doc_id,
        "version_no": outcome.version_no,
        "chunk_count": outcome.chunk_count,
        "vectorized": outcome.vectorized,
        "error": outcome.error,
    }


async def retrieve(kb_id: str, query: str) -> dict:
    result = await get_service().search(query, _actor(), kb_ids=[kb_id])
    evidence = getattr(result, "evidence", []) or []
    return {
        "evidence": [
            {
                "doc_id": getattr(e, "doc_id", None) or (e.get("doc_id") if isinstance(e, dict) else None),
                "chunk": getattr(e, "chunk", None) or (e.get("chunk") if isinstance(e, dict) else None),
                "text": getattr(e, "text", None) or (e.get("text") if isinstance(e, dict) else ""),
                "score": getattr(e, "score", None) if not isinstance(e, dict) else e.get("score"),
            }
            for e in evidence
        ],
        "degraded": getattr(result, "degraded", False),
    }


async def set_grant(kb_id: str, *, principal_kind: str, principal_id: str, role: str) -> dict:
    get_service().grant(kb_id, principal_kind=principal_kind, principal_id=principal_id,
                        role=role, actor=_actor())
    return {"granted": True}


async def set_revoke(kb_id: str, *, principal_kind: str, principal_id: str) -> dict:
    get_service().revoke(kb_id, principal_kind=principal_kind, principal_id=principal_id,
                         actor=_actor())
    return {"revoked": True}
