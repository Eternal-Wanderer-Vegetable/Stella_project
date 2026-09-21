# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""切块：把解析出的节切成检索粒度的 chunk。

切块策略刻意保守（plan §6.3：preserve locator）：

- **段落在节内原子**：一个 chunk 由整段拼成，绝不把一句话劈成两半——
  语义检索的 query/chunk 相似度对截断句极敏感，劈开的句子两头都搜不到；
- **目标长度** ``CHUNK_TARGET_CHARS``（500 字符）：超过就先成块（贪心装箱），
  超长单段（硬上限 ``CHUNK_HARD_LIMIT_CHARS``）再按句切、按句装箱；
- **定位符继承**：chunk 的 ``section_path``/``page`` 沿用所在节的定位，
  ``paragraph`` 记录首段段号——引用粒度是「某节的这一段」，足够指回原文。

不追新模型（语义切块/late chunking）：本地部署的成本敏感场景下，
段落装箱 + 混合检索已经是质量/成本的最优点，先跑通再谈升级。
"""

from __future__ import annotations

import re

from knowledge.domain import CHUNK_TARGET_CHARS, ChunkLocator, ParsedSection

# 硬上限：超过它的单段必须二次切分（embedding 模型的有效输入长度有限）。
CHUNK_HARD_LIMIT_CHARS = 900
# 装箱余量：装箱时按目标长度贪心，最终块允许到 目标×1.4（避免“差一点点
# 就能并进上一块”的碎片块）。
_PACK_SLACK = 1.4

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")


def chunk_sections(
    sections: list[ParsedSection],
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
) -> list[tuple[int, str, ChunkLocator]]:
    """把解析节切成 ``[(seq, text, locator), ...]``（seq 从 0 连续递增）。"""
    chunks: list[tuple[int, str, ChunkLocator]] = []
    for section in sections:
        pieces = _pack_paragraphs(_paragraphs_of(section.text), target_chars)
        for piece in pieces:
            locator = ChunkLocator(
                section_path=section.locator.section_path,
                page=section.locator.page,
                paragraph=section.locator.paragraph,
                char_start=section.locator.char_start,
                char_end=section.locator.char_end,
            )
            chunks.append((len(chunks), piece, locator))
    return chunks


def _paragraphs_of(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}|\r\n{2,}", text) if p.strip()]


def _pack_paragraphs(paragraphs: list[str], target_chars: int) -> list[str]:
    """贪心装箱：段落依次并入当前块，超出目标长度就封块。"""
    limit = int(target_chars * _PACK_SLACK)
    packed: list[str] = []
    current: list[str] = []
    size = 0
    for para in paragraphs:
        for piece in _split_long_paragraph(para, target_chars):
            if current and size + len(piece) > limit:
                packed.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        packed.append("\n".join(current))
    return packed


def _split_long_paragraph(para: str, target_chars: int) -> list[str]:
    """超长段落按句切分再装箱；无句读的超长串按硬上限硬切。"""
    if len(para) <= target_chars * _PACK_SLACK:
        return [para]
    sentences = [s for s in _SENTENCE_SPLIT.split(para) if s.strip()]
    if len(sentences) <= 1:
        # 无句读（URL/代码行等）：按硬上限硬切，保住「能被检索」的下限
        return [
            para[i : i + CHUNK_HARD_LIMIT_CHARS]
            for i in range(0, len(para), CHUNK_HARD_LIMIT_CHARS)
        ]
    packed: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) > target_chars:
            packed.append(current)
            current = ""
        current += sentence
    if current:
        packed.append(current)
    return packed


__all__ = [
    "CHUNK_HARD_LIMIT_CHARS",
    "chunk_sections",
]
