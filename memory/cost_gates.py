# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""成本闸门：整合前的本地免费预筛（Tier 1）。

在线端点按 token 计费，而记忆整合是高频后台任务。本模块回答一个问题：
**这一批消息值得花钱整合吗？** 判据全部跑在本地、零成本：

- :func:`should_skip_by_source_ratio`（T1-1）本批没人对 Bot 说话、其余全是
  图片/表情/单字附和 → 没有可提取的信息；
- :func:`at_mention_slice`（T1-2）阶段2 的任务定义是「用户亲口说的关于自己的
  信息」，被动刷屏对它无用却全额计费，因此只喂 AT_MENTION 行及其上下文；
- :func:`should_skip_by_novelty`（T1-3/T1-4）本批相对现有摘要毫无新意 → 话题
  没推进。优先用本地 embedding 的余弦相似度，拿不到向量就落到零依赖的词面判据
  ——``MEMORY_EMBEDDING_ENABLED`` **默认关闭**，不落这一步这道闸在默认配置下
  永远不触发。

两条纪律：

1. **跳过 = 攒批，不是丢弃。** 本模块只回答「该不该跳过」，绝不碰 checkpoint。
   调用方跳过时必须只 ``return``；推进了 checkpoint 这批消息就永久没人整合了
   （P0-4「消息永久丢失」的另一种形态）。配套的兜底是「连续跳过上限」
   （``CONSOLIDATION_MAX_SKIP_STREAK``），避免某个群永远攒不够而无限滞留。
2. **判据宁松勿紧。** 多花一次钱只是钱，漏掉一条「用户亲口说的信息」是记忆缺失。
   所以阈值都取得很保守，且任一条件不确定时都返回「不跳过」。

除 :func:`should_skip_by_novelty` 内部那次可选的 embedding 调用外，本模块全是
**无数据库、无 I/O 的纯函数**——``tests/test_cost_gates.py`` 因此不用搭库。
"""

from __future__ import annotations

import re

from memory.text_similarity import coverage_ratio, is_similar

# 整合 prompt 里的来源标记（由 memory/consolidator.py::_fetch_next_messages 写入）。
# 读写共用同一个常量：字面量各写一份的话，改了写入侧而漏改读取侧，
# 这道闸会静默失效——表现为「阶段2 还是收到整批消息」，没有任何报错。
AT_MENTION_MARKER = "[对Bot说]"
BOT_SELF_MARKER = "[这是机器人自己发送的消息，不属于任何用户]"

# 语义新颖度阈值。取得很高（= 很难触发）是故意的：这道闸的误判方向是
# 「把有新信息的一批当成重复跳掉」，代价是记忆缺失，比多花一次钱严重得多。
# 不给配置项——8 个新键已经是这一版的上限，阈值需要实测标定
# （design_docs/在线 LLM 接入方案 v1.0.md §5.6 把 T1-3 排在第 7 位并注明「阈值需标定」）。
NOVELTY_EMBEDDING_SIMILARITY = 0.95
NOVELTY_LEXICAL_COVERAGE = 0.90

# 单字/双字附和：命中即认为该行没有可提取的信息。只列高频且语义确定为空的，
# 拿不准的一律不列——漏判只是多花一次钱，误判会丢信息。
_TRIVIAL_REPLIES = frozenset(
    {
        "嗯", "嗯嗯", "哦", "噢", "啊", "呃", "唉", "哈", "哈哈", "哈哈哈", "嘿嘿",
        "嘻嘻", "呵呵", "对", "对对", "是", "是的", "好", "好的", "好吧", "行",
        "可以", "ok", "okk", "k", "牛", "牛逼", "强", "赞", "顶", "6", "66", "666",
        "www", "草", "awsl", "233", "2333", "在", "来了", "早", "晚安",
    }
)

# CQ 码（图片 / 表情 / 语音 / 骰子…）：整行只有 CQ 码时没有任何文字信息
_CQ_CODE = re.compile(r"\[CQ:[^\]]*\]")
# 非字母数字汉字一律剔掉：纯标点与纯 emoji 由此归一成空串
_NON_WORD = re.compile(r"[\W_]+")


def is_trivial_line(text: str | None) -> bool:
    """这一条消息是不是「图片 / 表情 / 单字附和」这类没有可提取信息的内容。

    判据顺序：空 → 纯 CQ 码 → 纯标点或纯 emoji → 附和词表 → 归一化后仅剩 1 个字符。
    """
    raw = (text or "").strip()
    if not raw:
        return True
    if not _CQ_CODE.sub("", raw).strip():
        return True
    body = _NON_WORD.sub("", _CQ_CODE.sub(" ", raw)).lower()
    if not body:
        return True
    if body in _TRIVIAL_REPLIES:
        return True
    return len(body) <= 1


def trivial_count(lines: list[str] | tuple[str, ...]) -> int:
    """``lines`` 里有多少条命中 :func:`is_trivial_line`（供日志与可观测性）。"""
    return sum(1 for line in lines if is_trivial_line(line))


def should_skip_by_source_ratio(
    at_senders: list[str] | tuple[str, ...] | None,
    lines: list[str] | tuple[str, ...] | None,
) -> str | None:
    """T1-1 来源占比门控；跳过时返回可直接写进日志的原因，否则 ``None``。

    两个条件是**与**关系：

    - 只要有人对 Bot 说过话（``at_senders`` 非空）就一定整合——AT_MENTION 是
      唯一稳定的信息源（``config/settings.py`` 的实测结论：群聊主体为角色扮演，
      被动摄入的可提取信息极少）；
    - 只要还剩一句实质发言就照样整合。

    ``lines`` 为空时**不跳过**：那不是「全是废话」，而是「没读到数据」，
    该由调用方的条数阈值去判断。
    """
    if at_senders:
        return None
    if not lines:
        return None
    trivial = trivial_count(lines)
    if trivial < len(lines):
        return None
    return f"本批 {len(lines)} 条消息无 AT_MENTION 来源且全为图片/表情/单字附和"


def at_mention_slice(messages_text: str, context_lines: int = 2) -> str:
    """T1-2：只保留含 AT_MENTION 标记的行及其前后 ``context_lines`` 行上下文。

    上下文是必要的：用户的「对，就是这个」只有配上上一句才有意义。

    没有任何 AT_MENTION 行时返回**原文**而不是空串——把阶段2 的输入掐成空的
    等于静默关掉提取，那种「候选莫名其妙变少」的故障极难排查。
    """
    lines = (messages_text or "").split("\n")
    hits = [i for i, line in enumerate(lines) if AT_MENTION_MARKER in line]
    if not hits:
        return messages_text
    span = max(0, context_lines)
    keep: set[int] = set()
    for i in hits:
        keep.update(range(max(0, i - span), min(len(lines), i + span + 1)))
    return "\n".join(lines[i] for i in sorted(keep))


async def _embedding_similarity(a: str, b: str) -> float | None:
    """本地 embedding 的余弦相似度；未启用 / 编码失败 / 任何异常一律返回 ``None``。

    lazy import 照 ``memory/retrieval_v2.py`` 的范式：模块级 import 会把
    ``memory.embeddings``（继而 ``core.llm``）拉进本模块的导入图，
    本模块就不再是「无 I/O 的纯逻辑」了，测试也得跟着搭环境。
    """
    try:
        from config import (
            MEMORY_EMBEDDING_BASE_URL,
            MEMORY_EMBEDDING_ENABLED,
            MEMORY_EMBEDDING_MODEL,
            MEMORY_EMBEDDING_TIMEOUT,
        )

        if not MEMORY_EMBEDDING_ENABLED:
            return None
        from memory.embeddings import EmbeddingService

        service = EmbeddingService(
            MEMORY_EMBEDDING_BASE_URL,
            MEMORY_EMBEDDING_MODEL,
            MEMORY_EMBEDDING_TIMEOUT,
        )
        return await service.similarity(a, b)
    except Exception:
        # 预筛失败就当「无从判断」→ 不跳过。闸门绝不能成为整合的失败点。
        return None


async def should_skip_by_novelty(messages_text: str, active_summary: str) -> str | None:
    """T1-3/T1-4 语义新颖度门控；跳过时返回可写进日志的原因，否则 ``None``。

    没有对照物（本批为空或还没有摘要）时一律放行：首批必须整合，
    否则一个新群永远等不到第一份摘要。

    向量可用时由它定论；拿不到向量（``MEMORY_EMBEDDING_ENABLED`` 默认关闭、
    服务没起、编码失败）才落到 T1-4 的词面判据。词面判据用两条：
    :func:`~memory.text_similarity.is_similar` 抓「互为子串」这类明显重复，
    :func:`~memory.text_similarity.coverage_ratio` 抓「这批话摘要里已经全说过」
    ——后者非对称，是中文长短文本对比唯一说得通的算法。
    """
    batch = (messages_text or "").strip()
    summary = (active_summary or "").strip()
    if not batch or not summary:
        return None

    sim = await _embedding_similarity(batch, summary)
    if sim is not None:
        if sim >= NOVELTY_EMBEDDING_SIMILARITY:
            return f"语义新颖度不足（与现有摘要余弦 {sim:.2f} ≥ {NOVELTY_EMBEDDING_SIMILARITY}）"
        return None

    if is_similar(batch, summary):
        return "词面判据判定与现有摘要重复（互为子串或词集合高度重叠）"
    coverage = coverage_ratio(batch, summary)
    if coverage >= NOVELTY_LEXICAL_COVERAGE:
        return f"词面重复率过高（{coverage:.2f} ≥ {NOVELTY_LEXICAL_COVERAGE}）"
    return None


__all__ = [
    "AT_MENTION_MARKER",
    "BOT_SELF_MARKER",
    "NOVELTY_EMBEDDING_SIMILARITY",
    "NOVELTY_LEXICAL_COVERAGE",
    "at_mention_slice",
    "is_trivial_line",
    "should_skip_by_novelty",
    "should_skip_by_source_ratio",
    "trivial_count",
]
