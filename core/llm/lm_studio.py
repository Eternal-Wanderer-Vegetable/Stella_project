# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""本地 LLM 后端（LM Studio）。

通过 LM Studio 的 OpenAI 兼容 /v1/chat/completions 接口调用本机模型
（如 gemma-4-e4b）。默认关闭 reasoning_effort，避免推理模型把全部 token
耗在思维链上导致 content 为空；并带 3 次指数退避重试与空回复检测，
5xx 等瞬时故障可自愈，4xx 配置类错误则直接放弃。用于聊天主链路与本地记忆整合。
"""

import asyncio

import httpx
from nonebot import logger

from core.llm.base import LLMBackend


class LMStudioBackend(LLMBackend):
    """调用 LM Studio 本地模型的 OpenAI 兼容后端。"""
    backend_name = "lm_studio"
    is_local = True

    def __init__(self, base_url: str, model: str | None = None, max_tokens: int = 2000, temperature: float = 0.7, api_key: str = ""):
        """初始化后端。

        参数:
            base_url: LLM 服务地址，如本地 LM Studio http://127.0.0.1:1234，
                或远程 OpenAI 兼容 API；
            model: 模型 ID，留空则由服务端默认路由；部分路由要求完整 ID（含前缀）；
            max_tokens: 单次生成的最大 token 数；
            temperature: 采样温度，值越低输出越稳定；
            api_key: 远程 API 的 Bearer Token（本地 LM Studio 留空）。
        """
        # 统一去掉末尾斜杠再拼路径，避免 base_url 带/导致 URL 出现双斜杠
        self.api_url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self.model = model or ""
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.api_key = api_key

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """生成回复；对瞬时故障最多重试 3 次，最终仍失败则抛异常。

        参数:
            prompt: 用户/上下文拼接后的输入；
            system_prompt: 系统提示词，非空时才加入 messages。
        返回:
            模型回复的纯文本；空回复按失败处理并重试。

        需要区分「输出被截断」与「模型确实这么答」的调用方请用
        :meth:`generate_detailed`——本方法的 ``-> str`` 签名是 LLMBackend
        的统一接口，插件兼容层等多处依赖，不做改动。
        """
        reply, _ = await self.generate_detailed(prompt, system_prompt)
        return reply

    async def generate_detailed(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        """同 :meth:`generate`，但额外返回 ``finish_reason``。

        返回 ``(回复文本, finish_reason)``；``finish_reason`` 取自服务端响应，
        取不到时为空串。``"length"`` 表示输出被 ``max_tokens`` 截断。

        为什么不用「把 finish_reason 存到 self 上供调用方读」：后端实例是按角色
        共享的单例，闸门只在 generate 期间持有，调用方读取时可能已被另一个群的
        调用覆盖。用返回值传递才没有竞态。
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.model:
            payload["model"] = self.model
        # 本地模型（如 gemma-4-e4b）推理时会把 token 全耗在思维链上导致 content 为空，禁用推理；
        # 远程 OpenAI 兼容 API 不认识该参数，不发送
        if not self.api_key:
            payload["reasoning_effort"] = "none"

        logger.info(f"[LM Studio] 发送请求（prompt {len(prompt)} 字符）")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        last_error: Exception | None = None
        # 最多 3 次尝试；trust_env=False 忽略系统代理，避免局域网地址被代理拦截
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), trust_env=False) as client:
                    resp = await client.post(self.api_url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    reply = choice["message"]["content"]
                    finish = choice.get("finish_reason") or ""
                    usage = data.get("usage") or {}
                    if finish == "length":
                        # 输出被 max_tokens 截断：JSON 类任务会因此解析失败。
                        # 调用方若用 generate_detailed 就能据此不推进 checkpoint；
                        # 只用 generate 的调用方看不到，仍靠这条日志排查。
                        logger.warning(
                            f"[LM Studio] 输出被 max_tokens={self.max_tokens} 截断"
                            f"（finish_reason=length, completion_tokens={usage.get('completion_tokens')}）"
                        )
                    if reply:
                        logger.info(
                            f"[LM Studio] 收到回复（{len(reply)} 字符，finish={finish or '?'}，"
                            f"completion_tokens={usage.get('completion_tokens', '?')}）"
                        )
                        return reply, finish
                last_error = RuntimeError("LM Studio 返回空回复")
                logger.warning(f"[LM Studio] 第 {attempt + 1} 次尝试返回空回复，重试...")
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:800]
                logger.error(f"[LM Studio] HTTP {status}\n{body}")
                if status == 400 and "model_not_found" in body:
                    # 模型 ID 写错是最常见的配置错误，但表现为兜底回复「......？」，
                    # 真因埋在 LM Studio 返回的 JSON 里，普通用户不会去翻日志。
                    logger.error(
                        f"[LM Studio] 模型 ID 配置错误：{self.model!r} 不存在。"
                        "LM Studio 要求完整 ID（含 google/ 之类前缀）。"
                        "运行 python -m deploy doctor 可列出当前已加载的模型。"
                    )
                last_error = e
                # 4xx 是请求/配置问题，重试无意义；5xx（如瞬时 502）服务端暂不可用，退避后重试
                if 400 <= status < 500 or attempt >= 2:
                    break
                await asyncio.sleep(1.0 * (attempt + 1))
            except Exception as e:
                last_error = e
                logger.warning(f"[LM Studio] 第 {attempt + 1} 次尝试异常: {e}")
                if attempt < 2:
                    # 网络类异常也按退避重试，把上次失败的有效错误保留到最后抛出
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise last_error or RuntimeError("LM Studio 请求失败")
