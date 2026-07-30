from abc import ABC, abstractmethod


class LLMBackend(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        pass
