# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 后端包。

导出 LLM 后端抽象基类 LLMBackend（本地 LM Studio 为唯一实现），并在此集中
声明两个全局 asyncio 锁：chat_llm_lock 用于串行化聊天主链路对共享本地模型
的访问；consolidation_llm_lock 用于串行化记忆整合任务，避免多群并发打爆
同一整合服务。
"""

import asyncio

# 聊天主链路锁：防止并发调用 GPU 上的主聊天模型（LM Studio）
chat_llm_lock = asyncio.Lock()

# 记忆整合锁：整合使用独立的 LM Studio 配置（可指向不同模型/实例），与聊天互不阻塞；
# 但仍需串行，避免多群并发打爆同一整合服务
consolidation_llm_lock = asyncio.Lock()
