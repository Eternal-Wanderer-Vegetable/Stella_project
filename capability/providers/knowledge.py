# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""知识库 backend：把 ProviderBackend 协议接到 knowledge service（kind=native）。

native 是 registry 里留好的口子（KIND_NATIVE）：能力由 Stella 进程内直接实现，
不经插件也不经 MCP。与 McpBackend 的关键差异——**主体不是参数**：
``knowledge_search`` 工具的 query/kb_ids 由模型给，但 ACL 主体永远从聊天事件
推导（``_principal_of``），模型无从伪造身份（prompt injection 让模型带
``user_id=别人`` 也带不进来）。

依赖纪律：本模块**不许在模块顶层 import** ``knowledge`` 包（capability 层
不依赖具体领域子系统，与 astrbot_compat/mcp 的纪律相同），全部延迟导入；
``knowledge`` 侧也不 import 本模块。工具返回值是 **JSON 字符串**——
``capability.hooks`` 按能力 id 把其中的 evidence 摘出来送进
``ChatContext.knowledge_evidence``（三轨分离），剩余文本不进 tool_summaries。
"""

from __future__ import annotations

import json
from typing import Any

from astrbot_compat.llm.tool import FunctionTool
from capability.registry import KIND_NATIVE, CapabilityProvider

# 能力与工具的注册名（hooks 按能力 id 分流证据；改名字必须三处同步：
# adapters/knowledge.py 的注册、本文件的工具名、hooks 的分流判断）
KNOWLEDGE_SEARCH_CAPABILITY = "knowledge.search"
KNOWLEDGE_SEARCH_TOOL = "knowledge_search"

# OpenAI function 形态的参数 schema。query 必填；kb_ids 可选（显式选择库，
# 不给 = 该主体有权的全部库）。
KNOWLEDGE_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "检索查询语句，用与资料相关的关键词或自然语言描述",
        },
        "kb_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选。限定检索的资料库 id 列表；不给则在所有有权限的资料库中检索",
        },
    },
    "required": ["query"],
}

_TOOL_DESCRIPTION = (
    "在资料库（知识库）中检索文档内容，返回带出处的摘录。"
    "适用于查询团队资料、规范文档、教程笔记等沉淀知识。"
)


def _principal_of(event: Any) -> tuple[str, str, str, bool]:
    """从聊天事件推导 ACL 主体 ``(user_id, group_id, space, in_group)``。

    防御式取值：任何一层拿不到就降级（空 user_id = 无权限，检索自然为空），
    绝不抛异常——工具层的异常会被 execute_tool 转成 error 字符串回喂模型。
    """
    user_id = str(getattr(event, "get_sender_id", lambda: "")() or "")
    group_id = str(getattr(event, "get_group_id", lambda: "")() or "")
    space = ""
    if group_id:
        try:
            from config.spaces import resolve_space

            space = resolve_space(int(group_id))
        except Exception:
            space = ""
    return user_id, group_id, space, bool(group_id)


class KnowledgeSearchTool(FunctionTool):
    """``knowledge_search`` 工具：ACL 受限的资料库检索。

    ``call`` 的 ``context`` 是 ``ContextWrapper(context=event)``（与
    McpFunctionTool 同一契约）；ACL 主体从事件推导，不接受参数传入。
    """

    def __init__(self) -> None:
        super().__init__(
            name=KNOWLEDGE_SEARCH_TOOL,
            description=_TOOL_DESCRIPTION,
            parameters=KNOWLEDGE_SEARCH_SCHEMA,
        )

    async def call(self, context: Any, **kwargs: Any) -> str:
        event = getattr(context, "context", None)
        user_id, group_id, space, in_group = _principal_of(event)
        query = str(kwargs.get("query") or "").strip()
        kb_ids = kwargs.get("kb_ids") or None
        if isinstance(kb_ids, str):
            kb_ids = [part.strip() for part in kb_ids.split(",") if part.strip()]
        if not query:
            return json.dumps(
                {"evidence": [], "error": "缺少检索词 query"}, ensure_ascii=False
            )

        payload: dict[str, Any] = {"evidence": [], "degraded": ""}
        try:
            from knowledge.acl import Principal
            from knowledge.service import get_service

            result = await get_service().search(
                query,
                Principal(user_id=user_id, group_id=group_id, space=space),
                in_group=in_group,
                kb_ids=[str(k) for k in kb_ids] if kb_ids else None,
            )
            payload["evidence"] = [_evidence_dict(ev) for ev in result.evidence]
            payload["degraded"] = result.degraded
        except Exception as e:  # 兜底：检索失败回喂模型可读的错误，不炸执行链
            return json.dumps(
                {"evidence": [], "error": f"资料库检索失败: {e}"}, ensure_ascii=False
            )
        return json.dumps(payload, ensure_ascii=False)


def _evidence_dict(ev: Any) -> dict[str, Any]:
    """Evidence → JSON 安全 dict（hooks 落入 ctx.knowledge_evidence 的形态）。"""
    loc = ev.locator
    return {
        "kb_id": ev.kb_id,
        "kb_name": ev.kb_name,
        "doc_id": ev.doc_id,
        "doc_title": ev.doc_title,
        "version_no": ev.version_no,
        "chunk_seq": ev.chunk_seq,
        "text": ev.text,
        "section_path": loc.section_path,
        "page": loc.page,
        "paragraph": loc.paragraph,
        "source_uri": ev.source_uri,
        "citation": ev.citation(),
        "score": ev.score,
        "matched_by": ev.matched_by,
    }


class KnowledgeBackend:
    """``kind=native`` 的 ProviderBackend 实现（目前只有 knowledge.search）。"""

    kind = KIND_NATIVE

    def _enabled(self) -> bool:
        from config import settings

        return bool(getattr(settings, "KNOWLEDGE_ENABLED", False))

    def resolve(self, provider: CapabilityProvider) -> Any:
        if not self._enabled():
            return None
        return KnowledgeSearchTool()

    def schema(self, provider: CapabilityProvider) -> dict[str, Any]:
        return dict(KNOWLEDGE_SEARCH_SCHEMA)

    def is_live(self, provider: CapabilityProvider) -> bool:
        return self._enabled()

    def status(self, provider: CapabilityProvider) -> dict[str, Any]:
        return {
            "tool": KNOWLEDGE_SEARCH_TOOL,
            "state": "ok" if self._enabled() else "disabled",
        }


__all__ = [
    "KNOWLEDGE_SEARCH_CAPABILITY",
    "KNOWLEDGE_SEARCH_SCHEMA",
    "KNOWLEDGE_SEARCH_TOOL",
    "KnowledgeBackend",
    "KnowledgeSearchTool",
]
