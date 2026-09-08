# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""本地模型的提示词前缀复用估算。

本地 OpenAI 兼容端点通常不会返回 ``cached_tokens``。这里根据同一端点/模型
近期见过的提示词公共前缀，估算本次可能复用的输入 token。

这不是 LM Studio 或模型引擎报告的真实 KV-cache 命中：估算只看文本前缀，
不掌握引擎的显存容量、逐层淘汰策略、量化实现和 TTL。模块只保存前缀哈希，
不保存提示词正文；进程重启后，前缀观测窗口自然清空。
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass

from core.context_budget import estimate_tokens

# 以字符为步长建立前缀指纹，避免保存提示词正文，也避免逐字符建立巨量索引。
_PREFIX_STEP_CHARS = 64
_MAX_PREFIXES = 8192

_seen_prefixes: OrderedDict[tuple[str, int, str], None] = OrderedDict()
_lock = threading.Lock()


@dataclass(frozen=True)
class PrefixEstimate:
    """一次本地请求的理论缓存估算。"""

    prompt_tokens: int = 0
    cached_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        return self.cached_tokens / self.prompt_tokens if self.prompt_tokens else 0.0


def _canonical_prompt(messages: list[dict], tools: list[dict] | None = None) -> str:
    """把会影响输入前缀的请求内容编码成稳定字符串。"""
    return json.dumps(
        {
            "messages": messages,
            "tools": tools or [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _prefix_keys(scope: str, text: str) -> list[tuple[tuple[str, int, str], int]]:
    keys: list[tuple[tuple[str, int, str], int]] = []
    for end in range(_PREFIX_STEP_CHARS, len(text) + 1, _PREFIX_STEP_CHARS):
        digest = hashlib.sha256(text[:end].encode("utf-8")).hexdigest()
        keys.append(((scope, end, digest), end))
    if text and (not keys or keys[-1][1] != len(text)):
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        keys.append(((scope, len(text), digest), len(text)))
    return keys


def estimate_local_prefix(
    messages: list[dict],
    *,
    slot: str = "",
    model: str = "",
    tools: list[dict] | None = None,
) -> PrefixEstimate:
    """估算本地端点可能复用的提示词前缀 token。

    只有此前在同一 ``slot/model`` 看到过的公共前缀才计入估算。
    返回值不包含原文，可直接交给用量记账层。
    """
    try:
        text = _canonical_prompt(messages, tools)
        total_tokens = estimate_tokens(text)
        if total_tokens <= 0:
            return PrefixEstimate()

        scope = f"{slot or '-'}:{model or '-'}"
        keys = _prefix_keys(scope, text)
        with _lock:
            cached_chars = 0
            for key, end in keys:
                if key in _seen_prefixes:
                    cached_chars = end
            for key, _ in keys:
                _seen_prefixes[key] = None
                _seen_prefixes.move_to_end(key)
            while len(_seen_prefixes) > _MAX_PREFIXES:
                _seen_prefixes.popitem(last=False)

        cached_tokens = min(total_tokens, estimate_tokens(text[:cached_chars]))
        return PrefixEstimate(
            prompt_tokens=total_tokens,
            cached_tokens=cached_tokens,
        )
    except Exception:
        # 估算只是观测旁路，任何异常都不能影响模型调用。
        return PrefixEstimate()


def reset_state() -> None:
    """清空进程内前缀观测窗口（测试与热重载使用）。"""
    with _lock:
        _seen_prefixes.clear()


__all__ = ["PrefixEstimate", "estimate_local_prefix", "reset_state"]
