# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Level 2：高级 fallback（方案第 8 节）。

只处理**极少量**不确定请求：Level 1 的最高分落在「不确定带」
（``ROUTER_UNCERTAIN_FLOOR`` < top < ``ROUTER_TOOL_THRESHOLD``）时才调用。

方案明确要求「避免浪费 27B SLM 推理资源」，所以：

- 默认 ``ROUTER_FALLBACK_ENABLED=false``；
- 即便打开，也只在不确定带内触发，确定不需要工具的请求不会走到这里；
- 只问一个封闭问题（在给定能力清单里选，或答「无」），不做开放生成——
  输出空间越小，本地小模型越不容易跑偏，也越容易解析。

它经 ``ROUTER`` 角色绑定的端点闸门（``gate_of(ROLE_ROUTER)``）排队：纯本地默认
与主聊天绑同一个槽、共用那块显存，因此必须串行；绑到独立端点后同一行代码自动
变成并行（见 docs/architecture.md「调用方绝不能同时持有两把闸门」）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from capability.registry import CapabilityRegistry
from capability.registry import registry as _default_registry
from capability.router.types import LEVEL_FALLBACK, CapabilityHit, Route

# 兜底判定的置信分。模型只回答「是/否 + 选哪个」，没有连续置信度，
# 给一个固定值表示「由模型拍板」，不与语义相似度同尺度比较。
FALLBACK_SCORE = 0.8

_PROMPT = """判断用户这句话是否需要调用外部工具，如果需要，从清单里选出最合适的。

可用能力清单：
{catalog}

用户这句话：{message}

只输出 JSON，不要解释：
{{"tool": true 或 false, "capability": "能力 id 或空字符串"}}

规则：
- 只有确实需要查询外部信息或执行外部操作时 tool 才为 true；
- 单纯闲聊、表达情绪、询问你自己的看法，tool 一律为 false；
- capability 必须是清单里的 id 之一，选不出就填空字符串并把 tool 设为 false。"""


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``（见 semantic.py 的注释）。"""
    from config import settings

    return settings


def _logger():
    from nonebot import logger

    return logger


def build_catalog(target: CapabilityRegistry | None = None) -> str:
    """把可路由能力渲染成清单文本。

    只给 id + description，**不给 examples**：examples 是给 embedding 用的语料，
    几十条塞进 prompt 会把本地模型的窗口吃掉，且对选择帮助有限。
    """
    reg = target if target is not None else _default_registry
    lines = []
    for capability in reg.routable():
        desc = capability.description or capability.id
        lines.append(f"- {capability.id}: {desc}")
    return "\n".join(lines)


def parse_verdict(raw: str) -> tuple[bool, str] | None:
    """从模型输出里解析 ``(tool, capability_id)``；解析不出返回 None。

    本地模型常在 JSON 外面裹一层解释文字或 markdown 代码块，所以先抓第一个
    ``{...}`` 再解析，而不是直接 ``json.loads(raw)``。
    """
    text = (raw or "").strip()
    if not text:
        return None
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    tool_raw = data.get("tool")
    if isinstance(tool_raw, str):
        tool = tool_raw.strip().lower() in ("true", "1", "yes", "是")
    else:
        tool = bool(tool_raw)
    capability = str(data.get("capability") or "").strip()
    return tool, capability


async def route_fallback(
    message: str,
    *,
    target: CapabilityRegistry | None = None,
    memory: bool = True,
    backend=None,
) -> Route | None:
    """Level 2 判定。返回 None 表示兜底不可用/未启用，调用方应降级。

    参数:
        backend: 可注入的 LLM 后端（需有 ``generate(prompt, system_prompt)``）。
            缺省时用主聊天后端——兜底判定与聊天共用同一个 27B。
    """
    if not _settings().ROUTER_FALLBACK_ENABLED:
        return None

    reg = target if target is not None else _default_registry
    catalog = build_catalog(reg)
    if not catalog:
        return None

    text = (message or "").strip()
    if not text:
        return None

    if backend is None:
        backend = _default_backend()
        if backend is None:
            return None

    prompt = _PROMPT.format(catalog=catalog, message=text)
    try:
        from core.llm import PRIORITY_INTERACTIVE, ROLE_ROUTER, acquire, gate_of

        # 与绑同一端点的角色（默认即主聊天 27B）共用闸门，必须排队；
        # 不可与其它闸门嵌套持有
        async with acquire(
            gate_of(ROLE_ROUTER), tag="router-fallback", priority=PRIORITY_INTERACTIVE
        ):
            raw = await backend.generate(prompt, "")
    except Exception as e:
        _logger().warning(f"⚠️ [Router] Level 2 兜底调用失败，降级: {e}")
        return None

    verdict = parse_verdict(raw)
    if verdict is None:
        _logger().warning(f"⚠️ [Router] Level 2 输出无法解析，降级: {raw[:120]!r}")
        return None

    tool, capability_id = verdict
    # 模型可能编出清单外的 id——那等于没选出来，按不需要工具处理
    if tool and reg.get(capability_id) is None:
        _logger().info(f"🧭 [Router] Level 2 给出了清单外的能力 {capability_id!r}，按无工具处理")
        tool = False
        capability_id = ""

    hits = [CapabilityHit(capability_id=capability_id, score=FALLBACK_SCORE)] if tool else []
    return Route(
        chat=True,
        memory=memory,
        tool=tool,
        capabilities=hits,
        top_score=FALLBACK_SCORE if tool else 0.0,
        level=LEVEL_FALLBACK,
        reason=f"模型兜底判定 tool={tool} capability={capability_id or '无'}",
    )


def _default_backend():
    """ROUTER 角色的后端。取不到返回 None（兜底不可用即降级，不影响回复）。"""
    try:
        from core.llm import ROLE_ROUTER, backend_for

        return backend_for(ROLE_ROUTER)
    except Exception as e:
        _logger().warning(f"⚠️ [Router] Level 2 后端构造失败: {e}")
        return None


__all__ = ["FALLBACK_SCORE", "build_catalog", "parse_verdict", "route_fallback"]
