from abc import ABC, abstractmethod


class LLMBackend(ABC):
    # 后端标识，用于诊断日志
    backend_name: str = "unknown"

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        pass
