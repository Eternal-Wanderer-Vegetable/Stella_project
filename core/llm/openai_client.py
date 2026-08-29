# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""完整的 OpenAI 兼容 chat-completions 客户端。

与 ``core.llm.lm_studio`` 的分工：

- ``LMStudioBackend.generate()`` 服务 Stella 主聊天链路，只收 (prompt, system_prompt)
  两个字符串，返回一段文本。它的行为（空回复重试、model_not_found 提示）是主链路
  多轮实测调出来的，本模块**不去动它**。
- 本模块服务 AstrBot 插件兼容层，需要透传完整的 messages 数组、tools（function
  calling）、图片内容块与流式输出——这些 ``generate()`` 表达不了。

两者共用同一个本地模型，因此**调用方必须自行经 ``core.llm.scheduler.acquire()``
排队**；本模块只负责发请求，不涉及闸门。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from nonebot import logger

from core.llm.compat import compat_for, learn_from_error, shape_payload
from core.llm.usage_sink import record as record_usage

# 4xx 是请求/配置问题，重试无意义；5xx（如瞬时 502）退避后重试
_MAX_ATTEMPTS = 3


class OpenAIClientError(RuntimeError):
    """chat-completions 调用失败。"""


def _build_payload(
    messages: list[dict],
    *,
    model: str,
    tools: list[dict] | None,
    tool_choice: str,
    temperature: float,
    max_tokens: int,
    api_key: str,
    kind: str,
    stream: bool,
    extra: dict[str, Any] | None,
) -> dict:
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if model:
        payload["model"] = model
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    if stream:
        payload["stream"] = True
    # 本地推理模型会把 token 全耗在思维链上导致 content 为空，禁用推理；
    # 在线厂商不认识该参数，多发就是一次 400，所以只在 local 端点上发。
    # kind 留空时沿用旧判据「有没有 key」，让未传 kind 的旧调用点行为不变。
    if (kind or ("online" if api_key else "local")).strip().lower() == "local":
        payload["reasoning_effort"] = "none"
    if extra:
        payload.update(extra)
    return payload


def _api_url(base_url: str) -> str:
    # 统一去掉末尾斜杠再拼路径，避免 base_url 带 / 导致 URL 出现双斜杠
    return f"{base_url.rstrip('/')}/v1/chat/completions"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _warn_if_truncated(data: dict) -> None:
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        return
    if (choice.get("finish_reason") or "") != "length":
        return
    usage = data.get("usage") or {}
    logger.warning(
        "[astrbot_llm] 输出被 max_tokens 截断"
        f"（finish_reason=length, completion_tokens={usage.get('completion_tokens')}）",
    )


def _explain_http_error(e: httpx.HTTPStatusError, model: str) -> None:
    status = e.response.status_code
    body = e.response.text[:800]
    logger.error(f"[astrbot_llm] HTTP {status}\n{body}")
    if status == 400 and "model_not_found" in body:
        # 与 lm_studio.py 同样的坑：模型 ID 写错最常见，但真因埋在返回的 JSON 里
        logger.error(
            f"[astrbot_llm] 模型 ID 配置错误：{model!r} 不存在。"
            "LM Studio 要求完整 ID（含 google/ 之类前缀）。"
            "运行 python -m deploy doctor 可列出当前已加载的模型。",
        )
    if status == 400 and ("context" in body.lower() or "token" in body.lower()):
        logger.error(
            "[astrbot_llm] 疑似超出模型上下文窗口。"
            "可下调 ASTRBOT_LLM_MAX_CONTEXT_TOKENS 或 ASTRBOT_LLM_MAX_TOOLS。",
        )


async def chat_completion(
    messages: list[dict],
    *,
    base_url: str,
    model: str = "",
    api_key: str = "",
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: float = 120.0,
    extra_body: dict[str, Any] | None = None,
    kind: str = "",
    slot: str = "",
    role: str = "",
) -> dict:
    """发一次 chat-completions 请求，返回原始响应 dict。

    参数:
        messages: 完整的 OpenAI 消息数组，原样透传（本函数不做裁剪，
            预算控制在调用方 ``StellaChatProvider`` 里做）；
        tools: OpenAI function-calling 的 tools 数组，为空则不发送；
        extra_body: 附加到请求体的字段，用于透传插件传入的 provider 私有参数；
        kind: ``local`` / ``online``，决定发不发本地专用参数；留空按有无 key 推断；
        slot: 端点槽名，用于参数兼容状态归集与用量记账；
        role: 角色名，同上。
    返回:
        服务端返回的完整 JSON。
    异常:
        OpenAIClientError: 重试耗尽后仍失败。
    """
    base_payload = _build_payload(
        messages,
        model=model,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        kind=kind,
        stream=False,
        extra=extra_body,
    )
    url = _api_url(base_url)
    headers = _headers(api_key)
    compat = compat_for(slot)
    last_error: Exception | None = None
    # 自适应重试上限 1：同一请求最多为参数形状差异重试一次，且不占用正常重试预算。
    adaptive_retries = 0
    attempt = 0

    while attempt < _MAX_ATTEMPTS:
        attempt += 1
        # 每次都按「该端点已学到的形状」重塑请求体，上一轮学到的改法自动生效
        payload = shape_payload(base_payload, compat)
        try:
            # trust_env=False 忽略系统代理，避免局域网地址被代理拦截
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                trust_env=False,
            ) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            _warn_if_truncated(data)
            if data.get("choices"):
                _record(data, role=role, slot=slot, model=model, kind=kind)
                return data
            last_error = OpenAIClientError("返回体没有 choices")
            logger.warning(f"[astrbot_llm] 第 {attempt} 次尝试返回空 choices，重试...")
        except httpx.HTTPStatusError as e:
            _explain_http_error(e, model)
            last_error = e
            status = e.response.status_code
            fix = learn_from_error(compat, status, e.response.text[:800])
            if fix and adaptive_retries < 1:
                adaptive_retries += 1
                attempt -= 1  # 自适应重试不占用正常重试预算
                logger.warning(
                    f"⚠️ [astrbot_llm] 端点不接受当前请求体（{fix}），"
                    f"已调整为「{compat.describe()}」并重试"
                )
                continue
            if 400 <= status < 500 or attempt >= _MAX_ATTEMPTS:
                break
            await asyncio.sleep(1.0 * attempt)
        except Exception as e:
            last_error = e
            logger.warning(f"[astrbot_llm] 第 {attempt} 次尝试异常: {e}")
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(1.0 * attempt)

    record_usage(role=role, slot=slot, model=model, kind=kind, ok=False)
    raise OpenAIClientError(f"chat-completions 请求失败: {last_error}") from last_error


def _record(data: dict, *, role: str, slot: str, model: str, kind: str) -> None:
    """把响应里的 usage / finish_reason 交给用量上报口。"""
    finish = ""
    # 上报是旁路：响应结构不符合预期时宁可少报一个字段，也不能让它把请求本身弄失败。
    with contextlib.suppress(KeyError, IndexError, TypeError):
        finish = data["choices"][0].get("finish_reason") or ""
    record_usage(
        role=role,
        slot=slot,
        model=model,
        kind=kind,
        usage=data.get("usage") or {},
        finish_reason=finish,
    )


async def chat_completion_stream(
    messages: list[dict],
    *,
    base_url: str,
    model: str = "",
    api_key: str = "",
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    timeout: float = 120.0,
    extra_body: dict[str, Any] | None = None,
    kind: str = "",
    slot: str = "",
    role: str = "",
) -> AsyncIterator[dict]:
    """流式请求，逐个 yield SSE 解出来的 chunk dict。

    与非流式不同，这里**不做重试**：流一旦开始产出，重试会让下游看到重复内容。
    参数差异的自适应也因此只「用」已学到的形状、不在这里学——非流式路径先撞上
    400 并学会，流式随后自动受益；反之若这里也学，就得为了学一次而重发整个流。
    """
    payload = shape_payload(
        _build_payload(
            messages,
            model=model,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            kind=kind,
            stream=True,
            extra=extra_body,
        ),
        compat_for(slot),
    )
    url = _api_url(base_url)
    headers = _headers(api_key)
    # 厂商通常把 usage 放在最后一个分片里，也有干脆不给的；边收边记最后见到的一份
    last_usage: dict = {}
    last_finish = ""

    try:
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(timeout), trust_env=False) as client,
            client.stream("POST", url, json=payload, headers=headers) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    data = json.loads(chunk)
                except ValueError:
                    logger.debug(f"[astrbot_llm] 跳过无法解析的流式分片: {chunk[:120]}")
                    continue
                usage = data.get("usage")
                if isinstance(usage, dict) and usage:
                    last_usage = usage
                finish = _chunk_finish_reason(data)
                if finish:
                    last_finish = finish
                yield data
            # 流正常结束后才记账：中途被下游放弃时 usage 本来也不完整，记了反而失真。
            # 拿不到 usage 就记 0——记 0 也比这条链路在用量表里完全不出现好。
            record_usage(
                role=role,
                slot=slot,
                model=model,
                kind=kind,
                usage=last_usage,
                finish_reason=last_finish,
            )
    except httpx.HTTPStatusError as e:
        _explain_http_error(e, model)
        record_usage(role=role, slot=slot, model=model, kind=kind, ok=False)
        raise OpenAIClientError(f"流式 chat-completions 请求失败: {e}") from e
    except OpenAIClientError:
        raise
    except Exception as e:
        raise OpenAIClientError(f"流式 chat-completions 请求失败: {e}") from e


def _chunk_finish_reason(chunk: dict) -> str:
    """取流式分片里的 finish_reason；取不到返回空串。"""
    try:
        return chunk["choices"][0].get("finish_reason") or ""
    except (AttributeError, KeyError, IndexError, TypeError):
        return ""
