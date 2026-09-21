# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""FTS5 索引文本处理（BM25 通道的写入侧与查询侧共用）。

中文没有词边界，SQLite 内建的 unicode61 分词器会把整段中文当成一个
token，BM25 由此完全失效。与 ``memory/retriever._segment_text`` 同一
技术（写入与查询两侧必须用同一套切法，索引才有意义）：

- 中文段：2/3 字滑窗切片段（长片段 3/2 双档，短片段整体保留）；
- 其余：按 ``\\w+`` 切词；
- 保序去重，空格连接成「词串」。

写入库 ``kb_chunk_fts.text`` 的是**分词后的词串**（原文始终在
``kb_chunk.text``，引用与展示不经过这里）；查询侧用
``build_match_query`` 把用户查询转成 FTS5 的 MATCH 表达式（OR 语义，
任一片段命中即召回，排序交给 bm25()）。
"""

from __future__ import annotations

import re

from memory.text_similarity import normalize_text

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,8}")
_WORD = re.compile(r"\w+")


def segment_text(text: str) -> str:
    """原文 → FTS5 词串（写入与查询共用，两侧不一致 = 索引报废）。"""
    normalized = normalize_text(text)
    tokens: list[str] = []
    for seg in _CJK_RUN.findall(normalized):
        if len(seg) <= 4:
            tokens.append(seg)
        else:
            for size in (3, 2):
                for i in range(len(seg) - size + 1):
                    tokens.append(seg[i : i + size])
    tokens.extend(_WORD.findall(normalized))
    return " ".join(dict.fromkeys(tokens))


def build_match_query(text: str, *, max_terms: int = 24) -> str:
    """查询 → MATCH 表达式。片段带引号防保留字，OR 连接保召回。

    空查询/无有效片段返回空串（调用方跳过 BM25 通道）。
    """
    segmented = segment_text(text)
    if not segmented:
        return ""
    terms = segmented.split()
    # 滑窗片段天然冗余，取前 max_terms 个足够；顺序保持原频次优先
    quoted = [f'"{term}"' for term in dict.fromkeys(terms)][:max_terms]
    return " OR ".join(quoted)


__all__ = [
    "build_match_query",
    "segment_text",
]
