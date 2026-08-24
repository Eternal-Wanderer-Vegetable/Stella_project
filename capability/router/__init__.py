# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Router：判断本次请求需要哪些能力（方案第 6~8 节）。

Router **只**回答「需要哪些能力」。它不负责：

- 记忆写入（记忆形成属于 Memory System 自己的判断，方案第 15 节）；
- 工具选择（Provider 的选择是 Comes 的活）；
- 工具执行；
- 人格回复。

三级级联，任一级给出高置信结论即短路：

```
Level 0  规则快速判断     零延迟，不调模型
   ↓ 给不出结论
Level 1  Embedding 语义   一次编码（有缓存）
   ↓ 落在不确定带
Level 2  更强模型兜底     默认关闭，只处理极少量请求
   ↓ 不可用
降级     chat + memory，不调工具
```

**降级是唯一的失败归宿**：embedding 不可用、注册表为空、超时、任何异常，
都返回 ``default_route()``（照常聊天、照常读记忆、不调工具）。与
``memory/embeddings.py`` 的既有约定一致——路由绝不能成为主链路的硬依赖。

保守方向是刻意的：漏调一次工具，用户最多再问一遍；凭空调一次工具，则可能真的
发出一条消息或改变外部状态。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from capability.registry import CapabilityRegistry
from capability.router.types import (
    LEVEL_DISABLED,
    LEVEL_RULE,
    CapabilityHit,
    Route,
    default_route,
)

# 主动发言类 intent：ctx.message 是给 Stella 的任务指令，不是用户的请求。
# 对它做能力路由是错的——「生成一句搭话」里出现「查」字不代表用户想查什么。
_INSTRUCTION_INTENTS = frozenset({"proactive_at", "proactive_join"})


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``（见 semantic.py 的注释）。"""
    from config import settings

    return settings


def _logger():
    from nonebot import logger

    return logger


async def route(
    message: str,
    *,
    intent: str = "",
    trigger: str = "reply",
    target: CapabilityRegistry | None = None,
    embedding_service=None,
    fallback_backend=None,
) -> Route:
    """判定一次请求需要哪些能力。**任何情况下都返回 Route，绝不抛异常。**

    参数:
        message: 用户消息（指令型 intent 下是任务指令，见 _INSTRUCTION_INTENTS）；
        intent: ChatContext.intent，用于识别指令型调用；
        trigger: ChatContext.trigger，仅用于日志归因；
        target: 能力注册表，缺省用模块级单例；
        embedding_service / fallback_backend: 测试注入点。
    """
    s = _settings()
    started = time.monotonic()

    if not s.CAPABILITY_ROUTER_ENABLED:
        result = default_route("能力路由未启用", level=LEVEL_DISABLED)
        result.elapsed = time.monotonic() - started
        return result

    # 指令型 intent 不做能力路由：message 是给 Stella 的指令而非用户请求。
    # 与 core/pipeline.py 的 _INSTRUCTION_INTENTS 同源考量。
    if intent in _INSTRUCTION_INTENTS:
        result = default_route(f"指令型 intent（{intent}）不做能力路由")
        result.elapsed = time.monotonic() - started
        return result

    try:
        result = await asyncio.wait_for(
            _cascade(
                message,
                target=target,
                embedding_service=embedding_service,
                fallback_backend=fallback_backend,
            ),
            timeout=s.ROUTER_TIMEOUT,
        )
    # 必须写 asyncio.TimeoutError：Python 3.10 下它与内置 TimeoutError 是两个
    # 不相干的类（3.11 起才合并），写内置的会在 3.10 上漏接。
    except asyncio.TimeoutError:
        _logger().warning(f"⚠️ [Router] 判定超时（{s.ROUTER_TIMEOUT}s），降级为 chat+memory")
        result = default_route(f"判定超时（{s.ROUTER_TIMEOUT}s）")
    except Exception as e:
        _logger().warning(f"⚠️ [Router] 判定异常，降级为 chat+memory: {e}")
        result = default_route(f"判定异常: {e}")

    result.elapsed = time.monotonic() - started
    _logger().info(
        f"🧭 [Router] {result!r} trigger={trigger} "
        f"({result.elapsed * 1000:.0f}ms) — {result.reason}",
    )
    return result


async def _cascade(
    message: str,
    *,
    target: CapabilityRegistry | None,
    embedding_service,
    fallback_backend,
) -> Route:
    """三级级联本体。异常向上抛给 ``route()`` 统一降级。"""
    s = _settings()

    # 记忆判定保持保守默认 True。只有 Level 0 有能力把它降为 False（纯寒暄），
    # 而那种情形已经在 apply_rules 里直接短路返回了；语义相似度衡量的是
    # 「像不像某个工具能力」，对「要不要回忆」没有区分力，故 Level 1/2 不改它。
    memory = True

    # ---- Level 0：规则 ----
    if s.ROUTER_RULE_ENABLED:
        from capability.router.rules import apply_rules

        ruled = apply_rules(message, target)
        if ruled is not None:
            return ruled

    # ---- Level 1：语义 ----
    if not s.ROUTER_SEMANTIC_ENABLED:
        return default_route("语义路由未启用，规则未命中")

    from capability.router.semantic import route_semantic

    semantic = await route_semantic(
        message,
        target=target,
        service=embedding_service,
        memory=memory,
    )
    if semantic is None:
        return default_route("语义层不可用（编码失败或无可路由能力）")

    # 语义已确定需要工具 → 完成
    if semantic.tool:
        return semantic

    # ---- Level 2：仅不确定带才兜底 ----
    top = semantic.top_score
    if not s.ROUTER_FALLBACK_ENABLED or not (
        s.ROUTER_UNCERTAIN_FLOOR < top < s.ROUTER_TOOL_THRESHOLD
    ):
        return semantic

    from capability.router.fallback import route_fallback

    fallback = await route_fallback(
        message,
        target=target,
        memory=memory,
        backend=fallback_backend,
    )
    if fallback is None:
        # 兜底不可用：语义层的结论仍然有效（「不需要工具」），直接用它
        return semantic
    return fallback


__all__ = ["LEVEL_RULE", "CapabilityHit", "Route", "default_route", "route"]
