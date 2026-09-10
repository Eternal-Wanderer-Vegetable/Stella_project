# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""自然语言个性化称呼意图识别。

本模块是一个安全的「路由 + 提取」层：规则负责廉价预筛，LM Studio embedding
负责判断语义是否接近称呼配置意图，最后只返回结构化请求。它不读取或写入称呼
偏好，也不把模型输出当作可执行命令。
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from typing import Any

from memory.embeddings import cosine_similarity

SET_SELF_ADDRESS = "SET_SELF_ADDRESS"
SET_OTHER_ADDRESS = "SET_OTHER_ADDRESS"
CLEAR_ADDRESS = "CLEAR_ADDRESS"
QUERY_ADDRESS = "QUERY_ADDRESS"
NOT_ADDRESS_REQUEST = "NOT_ADDRESS_REQUEST"

_PROTOTYPES: dict[str, tuple[str, ...]] = {
    SET_SELF_ADDRESS: (
        "以后叫我哥哥",
        "请称呼我为队长",
        "你可以喊我小林",
        "我希望你叫我老师",
    ),
    SET_OTHER_ADDRESS: (
        "把那位用户的称呼改成队长",
        "帮我给这个人设置一个称呼",
        "以后叫他学长",
        "把指定用户称呼为管理员",
    ),
    CLEAR_ADDRESS: (
        "别再这样称呼我",
        "取消我的个性化称呼",
        "不要再叫我哥哥了",
        "清除这个用户的称呼",
    ),
    QUERY_ADDRESS: (
        "你现在怎么称呼我",
        "我的个性化称呼是什么",
        "你记得我让你怎么叫我吗",
        "查看这个用户的称呼",
    ),
}

_SET_PATTERNS = (
    re.compile(r"(?:以后|请|今后)?(?:叫|称呼|喊)\s*我\s*(?:为|叫)?\s*(?P<term>.+)$"),
    re.compile(r"(?:以后|请|今后)?(?:称我为|叫我做|喊我做)\s*(?P<term>.+)$"),
    re.compile(r"(?:称呼|叫法)\s*(?:改成|改为|设为|设置为)\s*(?P<term>.+)$"),
)
_OTHER_SET_PATTERNS = (
    re.compile(
        r"(?:以后|请|今后)?(?:叫|称呼|喊)\s*"
        r"(?:他|她|TA|ta|用户)\s*(?:为|叫|做)?\s*(?P<term>.+)$"
    ),
)
_CLEAR_RE = re.compile(
    r"(?:别再|不要再|别|不要|取消|清除|删除|忘掉|忘记).{0,8}"
    r"(?:称呼|叫我|喊我|叫法)"
)
_QUERY_RE = re.compile(r"(?:怎么称呼|称呼我什么|叫我什么|我的称呼|称呼记录)")
_ADDRESS_CUE_RE = re.compile(
    r"(?:称呼|叫法|叫我|喊我|称我|叫他|叫她|叫TA|叫ta|喊他|喊她|喊TA|喊ta|"
    r"称呼他|称呼她|称呼TA|称呼ta|叫成|设为|改成|不要再叫|别再叫|怎么称呼)"
)
_TERM_TRAILING_RE = re.compile(r"^[\s:：，,。.!！?？；;、\"“”'‘’「」『』]+|[\s，,。.!！?？；;、\"“”'‘’「」『』]+$")


@dataclass(frozen=True)
class AddressingRequest:
    """意图层给消息 handler 的结构化结果。"""

    operation: str
    target_user_id: str | None = None
    address_term: str = ""
    confidence: float = 0.0
    needs_clarification: bool = False
    reason: str = ""


def _settings() -> Any:
    from config import settings

    return settings


def _normalize_term(value: str) -> str:
    return _TERM_TRAILING_RE.sub("", (value or "").strip())


def _normalize_user_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def is_likely_addressing_request(text: str) -> bool:
    """廉价预筛：普通「我哥哥来了」不会进入 embedding。"""
    return bool(_ADDRESS_CUE_RE.search((text or "").strip()))


def _rule_operation(text: str) -> str | None:
    value = (text or "").strip()
    if not value:
        return None
    if _CLEAR_RE.search(value):
        return CLEAR_ADDRESS
    if _QUERY_RE.search(value):
        return QUERY_ADDRESS
    if any(pattern.search(value) for pattern in _OTHER_SET_PATTERNS):
        return SET_OTHER_ADDRESS
    if any(pattern.search(value) for pattern in _SET_PATTERNS):
        if re.search(r"(?:把|给|替|帮).{0,24}(?:用户|他|她|TA|称呼|叫法)", value):
            return SET_OTHER_ADDRESS
        return SET_SELF_ADDRESS
    return None


def extract_address_term(text: str) -> str:
    """从确定性短语中提取短称呼；提取失败返回空串。"""
    value = (text or "").strip()
    for pattern in (*_OTHER_SET_PATTERNS, *_SET_PATTERNS):
        match = pattern.search(value)
        if match:
            return _normalize_term(match.group("term"))
    return ""


def _mean_vector(vectors: list[list[float]]) -> list[float] | None:
    usable = [v for v in vectors if v]
    if not usable:
        return None
    dim = len(usable[0])
    usable = [v for v in usable if len(v) == dim]
    if not usable:
        return None
    mean = [
        sum(vector[index] for vector in usable) / len(usable)
        for index in range(dim)
    ]
    norm = math.sqrt(sum(value * value for value in mean))
    return [value / norm for value in mean] if norm else None


_prototype_cache: dict[str, list[float]] = {}
_cached_model = ""


def reset_prototype_cache() -> None:
    """清空意图原型缓存（测试与模型切换时使用）。"""
    global _cached_model
    _prototype_cache.clear()
    _cached_model = ""


def _get_service():
    from memory.embeddings import EmbeddingService

    settings = _settings()
    return EmbeddingService(
        base_url=settings.MEMORY_EMBEDDING_BASE_URL,
        model=settings.MEMORY_EMBEDDING_MODEL,
        timeout=settings.MEMORY_EMBEDDING_TIMEOUT,
    )


async def build_prototypes(service=None) -> dict[str, list[float]]:
    """按 embedding 模型缓存称呼意图原型均值。"""
    global _cached_model
    service = service or _get_service()
    model = str(getattr(service, "model", "") or "")
    if model != _cached_model:
        reset_prototype_cache()
        _cached_model = model
    for operation, examples in _PROTOTYPES.items():
        if operation in _prototype_cache:
            continue
        vectors = []
        for example in examples:
            vector = await service.embed(example)
            if vector:
                vectors.append(vector)
        prototype = _mean_vector(vectors)
        if prototype is not None:
            _prototype_cache[operation] = prototype
    return dict(_prototype_cache)


async def _semantic_match(text: str, service=None) -> tuple[str | None, float, bool]:
    settings = _settings()
    service = service or _get_service()
    prototypes = await build_prototypes(service)
    query = await service.embed(text)
    if not query or not prototypes:
        return None, 0.0, False
    scores = sorted(
        (
            (operation, cosine_similarity(query, prototype))
            for operation, prototype in prototypes.items()
        ),
        key=lambda item: (-item[1], item[0]),
    )
    top_operation, top_score = scores[0]
    if top_score < settings.ADDRESSING_INTENT_THRESHOLD:
        return None, top_score, False
    second_score = scores[1][1] if len(scores) > 1 else 0.0
    ambiguous = len(scores) > 1 and top_score - second_score < settings.ADDRESSING_INTENT_MARGIN
    return top_operation, top_score, ambiguous


async def classify_addressing(
    text: str,
    *,
    target_user_id: Any = None,
    service=None,
) -> AddressingRequest:
    """识别称呼请求；不确定时返回 ``needs_clarification=True``。"""
    value = (text or "").strip()
    if not _settings().ADDRESSING_ENABLED or not is_likely_addressing_request(value):
        return AddressingRequest(NOT_ADDRESS_REQUEST, reason="prefilter_miss")

    rule_operation = _rule_operation(value)
    operation = rule_operation
    confidence = 0.92 if rule_operation else 0.0
    reason = "rule_match" if rule_operation else ""

    if _settings().ADDRESSING_SEMANTIC_ENABLED:
        try:
            semantic_operation, semantic_score, ambiguous = await asyncio.wait_for(
                _semantic_match(value, service),
                timeout=_settings().ADDRESSING_INTENT_TIMEOUT,
            )
        except Exception as error:
            semantic_operation, semantic_score, ambiguous = None, 0.0, False
            reason = f"embedding_fallback:{type(error).__name__}"
        else:
            if ambiguous and rule_operation is None:
                return AddressingRequest(
                    operation or semantic_operation or NOT_ADDRESS_REQUEST,
                    target_user_id=_normalize_user_id(target_user_id),
                    address_term=extract_address_term(value),
                    confidence=semantic_score,
                    needs_clarification=True,
                    reason="semantic_margin_too_small",
                )
            if semantic_operation is not None:
                operation = rule_operation or semantic_operation
                confidence = max(confidence, semantic_score)
                reason = reason or "semantic_match"

    if operation is None:
        return AddressingRequest(NOT_ADDRESS_REQUEST, reason=reason or "no_intent")

    target = _normalize_user_id(target_user_id)
    if target and target != "0" and operation == SET_SELF_ADDRESS:
        operation = SET_OTHER_ADDRESS

    term = extract_address_term(value) if operation in (
        SET_SELF_ADDRESS,
        SET_OTHER_ADDRESS,
    ) else ""
    if operation in (SET_SELF_ADDRESS, SET_OTHER_ADDRESS) and not term:
        return AddressingRequest(
            operation,
            target_user_id=target,
            confidence=confidence,
            needs_clarification=True,
            reason="missing_address_term",
        )
    return AddressingRequest(
        operation,
        target_user_id=target,
        address_term=term,
        confidence=confidence,
        reason=reason,
    )
