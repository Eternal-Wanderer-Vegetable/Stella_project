import asyncio

# 聊天主链路锁：防止并发调用 GPU 上的主聊天模型（LM Studio）
chat_llm_lock = asyncio.Lock()

# 记忆整合锁：整合使用独立的 LM Studio 配置（可指向不同模型/实例），与聊天互不阻塞；
# 但仍需串行，避免多群并发打爆同一整合服务
consolidation_llm_lock = asyncio.Lock()
