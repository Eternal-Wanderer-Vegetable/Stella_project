# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 用量上报口。

后端在成功分支把 ``usage`` 与 ``finish_reason`` 交到这里，一处改动供给三处：

- **截断可见**：``finish_reason=length`` 是「输出被截断 → JSON 解析失败 → 消息丢失」
  那条故障链的唯一信号；
- **成本可见**：按（日期, 角色, 端点, 模型）聚合输入/输出 token；
- **缓存命中率可见**：这是「对话域与记忆域各用一把 key」到底有没有生效的**唯一**
  验收手段。厂商在 ``usage`` 里给了缓存字段就直读，没给就只能靠输入 token 相对
  基线的下降间接观测——所以两种字段名都尝试识别。

本模块只做「收集 + 内存聚合 + 转交下游」。落库（SQLite 表、日预算、超额动作）
由成本控制那一期接进 :func:`set_sink`，这里刻意不引入任何数据库依赖：
记账绝不能成为聊天链路的失败点，所以整条路径全程吞异常。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# 厂商给缓存命中 token 的字段名各不相同，全都试一遍。
# 只做字段名匹配，不猜结构——猜结构等于又一份厂商白名单。
_CACHED_TOKEN_KEYS = (
    "prompt_cache_hit_tokens",
    "cached_tokens",
    "cache_read_input_tokens",
)
_CACHED_NESTED_KEYS = ("prompt_tokens_details", "input_tokens_details")


@dataclass(frozen=True)
class UsageRecord:
    """一次调用的用量。token 数取不到时为 0——**不是** None，避免下游到处判空。"""

    role: str
    slot: str
    model: str
    kind: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    finish_reason: str = ""
    ok: bool = True

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


@dataclass
class _Aggregate:
    """内存聚合桶。进程重启即清零——持久化是落库那一层的事。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    truncated: int = 0
    failed: int = 0


# (role, slot, model) → 聚合
_totals: dict[tuple[str, str, str], _Aggregate] = {}

# 下游落库钩子。默认 None = 只在内存里聚合。
_sink: Callable[[UsageRecord], None] | None = None


def set_sink(sink: Callable[[UsageRecord], None] | None) -> None:
    """安装下游落库钩子（成本控制那一期用）。传 None 卸载。"""
    global _sink
    _sink = sink


def extract_cached_tokens(usage: dict | None) -> int:
    """从 ``usage`` 里尽力取出「缓存命中的输入 token 数」；取不到返回 0。

    平铺字段与 ``prompt_tokens_details.cached_tokens`` 这类嵌套写法都认。
    """
    if not isinstance(usage, dict):
        return 0
    for key in _CACHED_TOKEN_KEYS:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    for outer in _CACHED_NESTED_KEYS:
        nested = usage.get(outer)
        if isinstance(nested, dict):
            for key in _CACHED_TOKEN_KEYS:
                value = nested.get(key)
                if isinstance(value, (int, float)):
                    return int(value)
    return 0


def record(
    *,
    role: str = "",
    slot: str = "",
    model: str = "",
    kind: str = "",
    usage: dict | None = None,
    finish_reason: str = "",
    ok: bool = True,
) -> UsageRecord:
    """记一次调用的用量。**全程不抛异常**——记账不该让聊天链路失败。

    参数:
        role: 角色名（chat / consolidation / ...）；
        slot: 端点槽名，即闸门资源名；
        model: 实际请求的模型 ID；
        kind: local | online。预算只算在线端点，所以要带上；
        usage: 服务端返回的 usage 字典，缺失按全 0 处理；
        finish_reason: 服务端返回的 finish_reason，``length`` 表示被截断；
        ok: 本次调用是否成功。失败也记——失败率是降级判断的依据。
    返回:
        本次的 :class:`UsageRecord`（调用方通常不需要，便于测试断言）。
    """
    usage = usage if isinstance(usage, dict) else {}

    def _int(key: str) -> int:
        value = usage.get(key)
        return int(value) if isinstance(value, (int, float)) else 0

    rec = UsageRecord(
        role=role,
        slot=slot,
        model=model,
        kind=kind,
        prompt_tokens=_int("prompt_tokens"),
        completion_tokens=_int("completion_tokens"),
        cached_tokens=extract_cached_tokens(usage),
        finish_reason=finish_reason or "",
        ok=ok,
    )

    bucket = _totals.setdefault((rec.role, rec.slot, rec.model), _Aggregate())
    bucket.calls += 1
    bucket.prompt_tokens += rec.prompt_tokens
    bucket.completion_tokens += rec.completion_tokens
    bucket.cached_tokens += rec.cached_tokens
    if rec.truncated:
        bucket.truncated += 1
    if not rec.ok:
        bucket.failed += 1

    if _sink is not None:
        try:
            _sink(rec)
        except Exception:
            # 落库失败不能影响调用方。这里连日志都走 try——
            # 记账路径上的任何异常都必须止步于此。
            try:
                from nonebot import logger

                logger.debug(f"[Usage] 下游记账钩子异常，已忽略（role={rec.role}）")
            except Exception:
                pass
    return rec


def snapshot() -> dict:
    """按 ``角色/端点/模型`` 导出进程内累计用量与缓存命中率。"""
    out = {}
    for (role, slot, model), agg in _totals.items():
        prompt = agg.prompt_tokens
        out[f"{role}@{slot}:{model or '-'}"] = {
            "role": role,
            "slot": slot,
            "model": model,
            "calls": agg.calls,
            "prompt_tokens": prompt,
            "completion_tokens": agg.completion_tokens,
            "cached_tokens": agg.cached_tokens,
            # 缓存命中率的分母是输入 token，不是调用次数：一次长请求命中一半
            # 与两次短请求各命中全部，省下来的钱完全不同。
            "cache_hit_rate": (agg.cached_tokens / prompt) if prompt else 0.0,
            "truncated": agg.truncated,
            "failed": agg.failed,
        }
    return out


def reset_state() -> None:
    """清空内存聚合（测试用）。不动已安装的 sink。"""
    _totals.clear()


__all__ = [
    "UsageRecord",
    "extract_cached_tokens",
    "record",
    "reset_state",
    "set_sink",
    "snapshot",
]
