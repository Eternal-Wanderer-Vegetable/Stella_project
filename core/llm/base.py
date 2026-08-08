# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 后端抽象基类。

定义所有 LLM 后端的统一接口 LLMBackend：任何实现只需提供 generate 异步方法，
即可接入 Pipeline。抽象层的价值在于让上层调用只依赖接口，而不关心具体是
本地 LM Studio 还是在线 FlexiWeb，方便在运行期按需切换/降级。
"""

from abc import ABC, abstractmethod


class LLMBackend(ABC):
    """所有 LLM 后端的抽象基类。

    子类需实现 generate()。backend_name 用于诊断日志标识实际后端来源。
    """
    # 后端标识，用于诊断日志
    backend_name: str = "unknown"

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成对给定 prompt 的一次回复。

        参数:
            prompt: 用户侧拼接后的输入（可能已包含 RAG 记忆上下文）；
            system_prompt: 可选系统提示词，不传则为空字符串。
        返回:
            模型生成的纯文本回复。
        """
        pass
