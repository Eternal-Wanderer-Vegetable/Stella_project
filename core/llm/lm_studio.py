# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""OpenAI 兼容 chat-completions 后端（本地 LM Studio 与在线厂商共用）。

类名保留 ``LMStudioBackend`` 是为了不动几十处调用点与测试，但它早已不只服务
LM Studio：只要对方实现 ``/v1/chat/completions``，本类都能用。区别只在 ``kind``：

- ``kind="local"``：额外发 ``reasoning_effort="none"``。本地推理模型（如
  gemma-4-e4b）会把 token 全耗在思维链上导致 ``content`` 为空，必须关掉。
- ``kind="online"``：**只发最小合规请求体**。多发一个厂商不认识的字段就是一次
  400，而「换一家就跑不通」正是本次改造要消灭的东西。厂商间的参数差异交给
  ``core.llm.compat`` 按错误体自适应，绝不用厂商白名单分流。

带 3 次指数退避重试与空回复检测，5xx 等瞬时故障可自愈，4xx 配置类错误直接放弃
（唯一例外：``compat`` 从 400 里学到了可修正的参数差异，此时额外自适应重试一次）。
"""

import asyncio

import httpx
from nonebot import logger

from core.llm.base import LLMBackend
from core.llm.compat import EndpointCompat, compat_for, learn_from_error, shape_payload
from core.llm.usage_sink import record as record_usage

# 正常重试预算。自适应重试不占用它，见 generate_detailed。
_MAX_ATTEMPTS = 3


class LMStudioBackend(LLMBackend):
    """调用 OpenAI 兼容 chat-completions 接口的后端。"""
    backend_name = "lm_studio"
    is_local = True

    def __init__(
        self,
        base_url: str,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        api_key: str = "",
        *,
        kind: str = "",
        slot: str = "",
        role: str = "",
        timeout: float = 120.0,
    ):
        """初始化后端。

        参数:
            base_url: 服务地址，如本地 LM Studio http://127.0.0.1:1234，
                或远程 OpenAI 兼容 API；
            model: 模型 ID，留空则由服务端默认路由；部分路由要求完整 ID（含前缀）；
            max_tokens: 单次生成的最大 token 数；
            temperature: 采样温度，值越低输出越稳定；
            api_key: 远程 API 的 Bearer Token（本地 LM Studio 留空）；
            kind: ``local`` / ``online``，决定发不发本地专用参数。留空时按
                「有 key 即在线」推断——这是改造前的判据，保留它是为了让直接
                构造本类的旧调用点（含大量测试）行为逐字不变；
            slot: 端点槽名，只用于日志与用量归集；
            role: 角色名，同上；
            timeout: 单次 HTTP 请求超时（秒）。改造前这里写死 120，现在由端点配置给出。
        """
        # 统一去掉末尾斜杠再拼路径，避免 base_url 带/导致 URL 出现双斜杠
        self.api_url = f"{base_url.rstrip('/')}/v1/chat/completions"
        self.model = model or ""
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.api_key = api_key
        # 没显式给 kind 时沿用旧判据：有 key 即远程。不要改成「默认 local」——
        # 那会让旧调用点对着在线端点发 reasoning_effort，直接 400。
        self.kind = (kind or ("online" if api_key else "local")).strip().lower()
        self.slot = slot
        self.role = role
        self.timeout = timeout if timeout and timeout > 0 else 120.0
        # 覆盖类属性：is_local 现在由 kind 决定
        self.is_local = self.kind == "local"

    @property
    def _compat(self) -> EndpointCompat:
        """本端点槽已学到的请求体形状。按槽共享，一个槽只交一次学费。"""
        return compat_for(self.slot)

    def _log_tag(self) -> str:
        """日志前缀。带上角色/槽名，多端点部署下才分得清是谁在说话。"""
        if self.role or self.slot:
            return f"[LLM {self.role or '-'}@{self.slot or '-'}]"
        return "[LM Studio]"

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

    def _base_payload(self, prompt: str, system_prompt: str) -> dict:
        """最小合规请求体。**每加一个字段都要问一遍「换一家还认吗」。**"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict = {
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.model:
            payload["model"] = self.model
        if self.kind == "local":
            # 本地模型（如 gemma-4-e4b）推理时会把 token 全耗在思维链上导致
            # content 为空，禁用推理。判据是 kind 而不是「有没有 key」：
            # 本地 LM Studio 也可以设 key，那时旧判据会误判成在线、把推理放开。
            payload["reasoning_effort"] = "none"
        return payload

    async def generate_detailed(self, prompt: str, system_prompt: str = "") -> tuple[str, str]:
        """同 :meth:`generate`，但额外返回 ``finish_reason``。

        返回 ``(回复文本, finish_reason)``；``finish_reason`` 取自服务端响应，
        取不到时为空串。``"length"`` 表示输出被 ``max_tokens`` 截断。

        为什么不用「把 finish_reason 存到 self 上供调用方读」：后端实例是按角色
        共享的单例，闸门只在 generate 期间持有，调用方读取时可能已被另一个群的
        调用覆盖。用返回值传递才没有竞态。
        """
        base_payload = self._base_payload(prompt, system_prompt)
        tag = self._log_tag()
        logger.info(f"{tag} 发送请求（prompt {len(prompt)} 字符）")
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        last_error: Exception | None = None
        # 自适应重试次数。上限 1：同一请求最多为参数差异重试一次，否则一个配置
        # 错误会被无限重试成死循环（与「4xx 不重试」那条判据的唯一例外）。
        adaptive_retries = 0
        attempt = 0
        # trust_env=False 忽略系统代理，避免局域网地址被代理拦截
        while attempt < _MAX_ATTEMPTS:
            attempt += 1
            # 每次都按「已学到的形状」重塑请求体，于是上一轮学到的改法自动生效
            payload = shape_payload(base_payload, self._compat)
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.timeout), trust_env=False
                ) as client:
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
                            f"{tag} 输出被 max_tokens={self.max_tokens} 截断"
                            f"（finish_reason=length, completion_tokens={usage.get('completion_tokens')}）"
                        )
                    if reply:
                        record = record_usage(
                            role=self.role,
                            slot=self.slot,
                            model=self.model,
                            kind=self.kind,
                            usage=usage,
                            finish_reason=finish,
                        )
                        cached = (
                            f"，缓存命中 {record.cached_tokens}" if record.cached_tokens else ""
                        )
                        logger.info(
                            f"{tag} 收到回复（{len(reply)} 字符，finish={finish or '?'}，"
                            f"completion_tokens={usage.get('completion_tokens', '?')}{cached}）"
                        )
                        return reply, finish
                last_error = RuntimeError("LLM 返回空回复")
                logger.warning(f"{tag} 第 {attempt} 次尝试返回空回复，重试...")
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                body = e.response.text[:800]
                logger.error(f"{tag} HTTP {status}\n{body}")
                if status == 400 and "model_not_found" in body:
                    # 模型 ID 写错是最常见的配置错误，但表现为兜底回复「......？」，
                    # 真因埋在服务端返回的 JSON 里，普通用户不会去翻日志。
                    logger.error(
                        f"{tag} 模型 ID 配置错误：{self.model!r} 不存在。"
                        "LM Studio 要求完整 ID（含 google/ 之类前缀）；"
                        "在线厂商请照其文档填写。"
                        "运行 python -m deploy doctor 可列出当前已加载的模型。"
                    )
                last_error = e
                fix = learn_from_error(self._compat, status, body)
                if fix and adaptive_retries < 1:
                    # 识别出的是参数形状差异，不是配置错误：改完立刻重试，且**不占用**
                    # 正常重试预算——否则一次学习就吃掉三分之一的容错额度。
                    adaptive_retries += 1
                    attempt -= 1
                    logger.warning(
                        f"⚠️ {tag} 端点不接受当前请求体（{fix}），"
                        f"已调整为「{self._compat.describe()}」并重试"
                    )
                    continue
                # 4xx 是请求/配置问题，重试无意义；5xx（如瞬时 502）退避后重试
                if 400 <= status < 500 or attempt >= _MAX_ATTEMPTS:
                    break
                await asyncio.sleep(1.0 * attempt)
            except Exception as e:
                last_error = e
                logger.warning(f"{tag} 第 {attempt} 次尝试异常: {e}")
                if attempt < _MAX_ATTEMPTS:
                    # 网络类异常也按退避重试，把上次失败的有效错误保留到最后抛出
                    await asyncio.sleep(1.0 * attempt)
        # 失败也要记一笔：失败率是「该不该降级到本地」的判断依据
        record_usage(
            role=self.role, slot=self.slot, model=self.model, kind=self.kind, ok=False
        )
        raise last_error or RuntimeError("LLM 请求失败")
