# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""知识库能力的进程接线（方案 §7.8 启动顺序的 knowledge 环节）。

三件事，全部幂等、全部失败只告警（能力层是增量功能）：

1. 把 ``KnowledgeBackend``（kind=native）装进 Provider Runtime——装了它，
   ``comes.executor.resolve_tools`` 才能把 knowledge.search 的 provider
   解析成真的工具；
2. 把 ``knowledge.search`` 能力注册进 Capability Registry——显式声明
   （examples 是**用户会怎么问**的语料），参与 Router 语义路由；
3. 返回装配结果供启动诊断日志。

examples 的写法与 config/capabilities/entertainment.toml 同一纪律：
写给 Router Level 1 的原型语料，不是工具描述句。keywords 刻意不给——
「查一下」「资料库里」这类词没有专属性，L0 字面命中会把普通对话误伤成
强制检索（工具假阳是高代价错误，宁缺勿滥）。
"""

from __future__ import annotations

from typing import Any

from capability.providers.knowledge import (
    KNOWLEDGE_SEARCH_CAPABILITY,
    KNOWLEDGE_SEARCH_SCHEMA,
    KNOWLEDGE_SEARCH_TOOL,
    KnowledgeBackend,
)
from capability.registry import (
    KIND_NATIVE,
    SOURCE_CONFIG,
    Capability,
    CapabilityProvider,
    registry,
)

# examples：Level 1 语义路由的原型语料（用户视角的说法）。
# 「文档/资料/规定/手册/笔记」是知识库场景的高频词；刻意避开「搜索」
# 单独出现的形式——那会抢走普通网页检索类能力的流量。
_EXAMPLES = [
    "资料库里有没有关于部署的文档",
    "帮我查一下知识库里的服务器配置规范",
    "根据我们的文档，备份应该怎么做",
    "文档里怎么说的数据库连接",
    "团队资料库里有哪些入门教程",
    "查查规定文件里关于请假的部分",
]

_CAPABILITY_DESCRIPTION = (
    "在团队资料库/知识库中检索文档内容，返回带出处的权威摘录"
    "（区别于闲聊记忆：那是沉淀下来的正式资料）"
)


def install_knowledge_capability() -> dict[str, Any]:
    """装配知识库能力。返回诊断信息；未启用返回 ``{"enabled": False}``。"""
    from config import settings

    if not getattr(settings, "KNOWLEDGE_ENABLED", False):
        return {"enabled": False}

    from capability.providers import provider_runtime

    provider_runtime.register_backend(KnowledgeBackend())
    registry.register(
        Capability(
            id=KNOWLEDGE_SEARCH_CAPABILITY,
            domain="knowledge",
            description=_CAPABILITY_DESCRIPTION,
            examples=list(_EXAMPLES),
            input_schema=dict(KNOWLEDGE_SEARCH_SCHEMA),
            providers=[
                CapabilityProvider(
                    provider_id=f"{KNOWLEDGE_SEARCH_TOOL}_native",
                    capability_id=KNOWLEDGE_SEARCH_CAPABILITY,
                    kind=KIND_NATIVE,
                    tool_name=KNOWLEDGE_SEARCH_TOOL,
                    priority=10,
                    source=SOURCE_CONFIG,
                )
            ],
        )
    )
    return {
        "enabled": True,
        "capability": KNOWLEDGE_SEARCH_CAPABILITY,
        "tool": KNOWLEDGE_SEARCH_TOOL,
    }


__all__ = [
    "KNOWLEDGE_SEARCH_CAPABILITY",
    "install_knowledge_capability",
]
