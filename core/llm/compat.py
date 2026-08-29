# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""OpenAI 兼容端点的参数差异自适应层。

**厂商中立是硬约束，不是「尽量」。** 本模块存在的理由只有一条：不同厂商对同一
份请求体的接受度不一样，而我们**不许用厂商白名单去分流**——白名单必然过时（新厂商
漏掉、旧厂商改版），最后表现为「换一家就跑不通」。

所以差异一律做成「**按错误体自适应 + 记住结果**」：

1. 默认发最小合规请求体（``model`` / ``messages`` / ``temperature`` /
   ``max_tokens``，流式加 ``stream``，工具链路加 ``tools`` / ``tool_choice``）；
2. 端点用 400 明确拒绝其中某个字段时，按**错误体关键词**判断该怎么改，重试一次；
3. 改法记在该端点槽上（进程内），之后的请求直接用对的形状，不再交学费。

只做关键词匹配，不解析固定结构：各家 ``error.message`` 的嵌套层级都不一样，
按结构解析等于又一份隐形白名单。

与既有「4xx 不重试」判据的关系：**4xx 原则上不重试，"已识别出可修正的参数差异"
是唯一例外，且同一请求最多自适应重试一次**——否则对着一个配置错误无限重试。
"""

from __future__ import annotations

from dataclasses import dataclass

# 自适应的两种改法
FIX_MAX_TOKENS_FIELD = "max_completion_tokens"
FIX_OMIT_TEMPERATURE = "omit_temperature"

# 「该用 max_completion_tokens」的判据：错误体里直接点了这个字段名。
# 这是各家在弃用 max_tokens 时都会给出的提示词，不需要知道是哪一家。
_MAX_TOKENS_HINT = "max_completion_tokens"

# 「不接受 temperature」的判据：错误体同时提到该字段与「不支持」类措辞。
# 单看 "temperature" 会把「取值超出范围」也算进来——那种情况省略该字段同样能过，
# 所以宁可命中，但仍要求有「不支持」类词，避免把无关 400 也当成参数差异。
_TEMPERATURE_UNSUPPORTED_HINTS = (
    "unsupported",
    "not supported",
    "does not support",
    "unsupported_value",
    "only the default",
    "不支持",
)


@dataclass
class EndpointCompat:
    """某个端点槽已学到的请求体形状。进程内状态，重启即重新学。"""

    slot: str
    # 生成长度用哪个字段名
    max_tokens_field: str = "max_tokens"
    # 是否省略 temperature
    omit_temperature: bool = False

    def describe(self) -> str:
        parts = []
        if self.max_tokens_field != "max_tokens":
            parts.append(f"长度字段={self.max_tokens_field}")
        if self.omit_temperature:
            parts.append("省略 temperature")
        return "、".join(parts) or "标准形状"


_compat: dict[str, EndpointCompat] = {}


def compat_for(slot: str) -> EndpointCompat:
    """取端点槽的兼容状态（懒建）。``slot`` 为空时用一个共享的匿名槽。"""
    key = slot or "-"
    state = _compat.get(key)
    if state is None:
        state = EndpointCompat(slot=key)
        _compat[key] = state
    return state


def snapshot() -> dict[str, str]:
    """已学到的形状（供 doctor / 启动日志）。"""
    return {slot: state.describe() for slot, state in _compat.items()}


def reset_state() -> None:
    """清空已学到的形状（测试用）。"""
    _compat.clear()


def shape_payload(payload: dict, compat: EndpointCompat) -> dict:
    """按已学到的形状调整请求体；返回**新字典**，不改原对象。

    调用方每次请求前都过一遍这里，于是「学到的改法」对后续请求自动生效。
    """
    out = dict(payload)
    if compat.max_tokens_field != "max_tokens" and "max_tokens" in out:
        out[compat.max_tokens_field] = out.pop("max_tokens")
    if compat.omit_temperature:
        out.pop("temperature", None)
    return out


def _searchable(body: str) -> str:
    r"""错误体的可搜索形式：原文，外加一份反转义副本（仅当出现 ``\uXXXX`` 时）。

    不少后端用 ``ensure_ascii=True`` 序列化 JSON，中文错误信息到了线上就成了
    一串 ``\uXXXX`` 转义，中文关键词一条都命中不了——而中文厂商恰恰是
    要支持的一类。这里**追加**而非替换：反转义可能失败，也可能动到原文里本就
    是字面反斜杠的部分，保留原文才能保证 ASCII 关键词照旧命中。
    """
    if "\\u" not in body:
        return body
    try:
        # 先把非 ASCII 也统一成转义形式再整体反转义：一次调用同时还原
        # 「本来就是转义」与「本来就是中文」两种写法，不必分头处理。
        decoded = body.encode("ascii", "backslashreplace").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return body
    return f"{body}\n{decoded}"


def learn_from_error(compat: EndpointCompat, status: int, body: str) -> str:
    """从 400 错误体里学一条改法；学到则改写 ``compat`` 并返回改法名，否则空串。

    参数:
        compat: 该端点槽的兼容状态，命中时**就地更新**；
        status: HTTP 状态码。只看 400——401/403/429/5xx 不是参数问题；
        body: 错误响应体文本（截断过也行，关键词通常在开头）。
            纯 ASCII 转义的中文由 :func:`_searchable` 还原后再匹配。
    返回:
        :data:`FIX_MAX_TOKENS_FIELD` / :data:`FIX_OMIT_TEMPERATURE` 之一，或空串。

    只在**尚未应用过**该改法时返回非空：同一改法学第二次说明这条不是真因，
    继续重试只会退化成对配置错误的死循环。
    """
    if status != 400 or not body:
        return ""
    low = _searchable(body).lower()
    if _MAX_TOKENS_HINT in low and compat.max_tokens_field == "max_tokens":
        compat.max_tokens_field = _MAX_TOKENS_HINT
        return FIX_MAX_TOKENS_FIELD
    if (
        "temperature" in low
        and not compat.omit_temperature
        and any(hint in low for hint in _TEMPERATURE_UNSUPPORTED_HINTS)
    ):
        compat.omit_temperature = True
        return FIX_OMIT_TEMPERATURE
    return ""


__all__ = [
    "FIX_MAX_TOKENS_FIELD",
    "FIX_OMIT_TEMPERATURE",
    "EndpointCompat",
    "compat_for",
    "learn_from_error",
    "reset_state",
    "shape_payload",
    "snapshot",
]
