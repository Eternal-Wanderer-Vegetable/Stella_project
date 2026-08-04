import asyncio

# 全局 LLM 调用锁：防止 Pipeline 回复与 Consolidator 整合并发打同一个本地模型
llm_lock = asyncio.Lock()
