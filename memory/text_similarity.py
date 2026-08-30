# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆内容的文本相似度与合并（单一真相源）。


背景：判断「两条记忆是不是同一件事」与「怎么把它们合成一条」这两件事，
历史上在 memory_manager / compressor / retrieval_v2 里各有一份近乎相同的
副本。副本漂移已经造成过实际缺陷——跨用户合并 bug 需要在三个文件里分别修，
其中两处被漏掉。本模块把这套逻辑收敛为模块级纯函数，三处统一 import。


纯逻辑、无数据库依赖，便于单测。


注意：本模块只回答「内容是否相似」。**归属（group_id / user_id）与类型
是否相同必须由调用方先行判定**——内容相似不等于可以合并，用户 A 与
用户 B 说了同一句话是两条独立记忆。
"""
from __future__ import annotations

import re

# 内容相似判定阈值（Jaccard）。0.65 沿用原三处实现的既有取值：
# 过高会漏合并导致重复记忆堆积，过低会误合并造成信息串味。
SIMILARITY_THRESHOLD = 0.65


def normalize_text(text: str | None) -> str:
    """文本归一化：小写、非字母数字字符替换为空格、压缩空白。空值按空串处理。"""
    text = (text or "").strip().lower()
    text = re.sub(r"[\W_]+", " ", text)
    return " ".join(text.split())


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """两词集合的 Jaccard 相似度 = 交集 / 并集（任一方为空返回 0）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def char_ngrams(text: str | None, n: int = 2) -> set[str]:
    """归一化后的字符级 n-gram 集合（去掉分隔空白）。

    中文没有空格分词，:func:`jaccard_similarity` 的词集合会退化成「整段算一个词」——
    两段不同的中文对话相似度恒为 0。字符 n-gram 是零依赖的替代品，不引入分词器。
    """
    norm = normalize_text(text).replace(" ", "")
    if not norm:
        return set()
    if len(norm) <= n:
        return {norm}
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def coverage_ratio(new: str | None, existing: str | None, n: int = 2) -> float:
    """``new`` 有多大比例的字符 n-gram 已经出现在 ``existing`` 里（0~1）。

    与 :func:`jaccard_similarity` 的关键区别是**非对称**：分母只有 ``new`` 一侧。
    判「这批新消息是否已被旧摘要说完」时必须用它——摘要总比原文短得多，
    Jaccard 会被这个长度差压到很低，永远判不出重复。
    """
    a = char_ngrams(new, n)
    b = char_ngrams(existing, n)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def is_similar(a: str | None, b: str | None, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """判断两段内容是否指同一件事：归一化后互为子串，或词集合 Jaccard ≥ 阈值。空值视为不相似。"""
    if not a or not b:
        return False
    a_norm = normalize_text(a)
    b_norm = normalize_text(b)
    if not a_norm or not b_norm:
        return False
    # 归一化后互相包含，视为同一条（一方是另一方的更完整表述）
    if a_norm in b_norm or b_norm in a_norm:
        return True
    return jaccard_similarity(set(a_norm.split()), set(b_norm.split())) >= threshold


def merge_content(old: str, new: str) -> str:
    """合并两段内容：一方包含另一方时取更完整者，否则以「；」连接。


    任一方为空时返回另一方，保证合并结果非空。
    """
    old = (old or "").strip()
    new = (new or "").strip()
    if not old:
        return new
    if not new:
        return old
    if new in old:
        return old
    if old in new:
        return new
    return old + "；" + new
