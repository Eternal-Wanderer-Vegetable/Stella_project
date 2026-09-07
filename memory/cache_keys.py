# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""缓存 key 的统一来源（《Stella 拟人化插话与低成本运行改进方案 v1.0》阶段四）。

两类缓存共用本模块的版本与话题归一化，保证 key 语义只有一处定义：

    会话上下文缓存：session_id + history_version + mode + policy_version
    语义检索缓存：  shared_space + user + normalized_topic_hash + mode + 历史版本

本模块**不做任何 IO**：不碰数据库、不调 LLM，纯函数 + 进程内计数器，
可被任意记忆模块安全引用（不会引入循环依赖）。
"""

from __future__ import annotations

import hashlib
import re

# 记忆策略版本：改动 rank_memories / mode_limit / usage_allowed 等策略语义，
# 或改动上下文组装的分区规则时**必须递增**——所有缓存 key 都包含它，
# 递增即全部失效，避免「策略变了、缓存还在按旧策略吐结果」。
POLICY_VERSION = "2026-09-08.0"

# ── 记忆库历史版本（进程内单调递增） ──
# 语义检索缓存把该值编进 key：整合器晋升/合并/归档任何记忆后版本变化，
# 旧缓存条目自然不可达（等容量上限逐出），实现「历史版本变化时失效缓存」。
# 只覆盖进程内写入（NoneBot 单进程部署）；库被外部工具改动时由 TTL 兜底。
_memory_history_version = 0


def memory_history_version() -> int:
    """当前记忆库历史版本（写入路径每次落库后调用 bump 递增）。"""
    return _memory_history_version


def bump_memory_history() -> None:
    """宣告「记忆库内容变了」。所有记忆写入路径提交后都必须调用。

    只递增不清理：失效靠 key 变化完成，旧条目由各缓存的容量上限逐出，
    这样 bump 是 O(1) 且不会与正在进行的检索读产生竞争。
    """
    global _memory_history_version
    _memory_history_version += 1


# ── 话题归一化 ──
# 文本级归一化：小写、只保留中文/字母/数字、去空白与标点表情。
# 设计取舍（刻意保守）：
# - 「同一句话」的重复查询（主动发言的罐头指令、重试、同一消息的
#   多路径检索）→ 归一化后逐字相同 → 命中；
# - 「换措辞」→ 视为换话题 → 换桶。不做关键词/语义级别的粗化：
#   中文无分词的滑窗 n-gram 对措辞变化给不出稳定签名，而错误共享桶的
#   代价（复用旧话题的检索结果 → 接错话题）远大于 miss 的代价
#   （重跑几条本地 SQLite 查询，零 LLM 调用）。
_KEEP_RUN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


def normalize_topic(text: str) -> str:
    """把一条查询归一化为话题签名：小写 + 只留中文/字母/数字 + 去空白标点。

    确定性纯函数：同文本必同签名；标点/表情/大小写/空白差异不影响。
    无有效字符时返回空串（该类查询本就走新鲜度检索，共享空桶无害）。
    """
    if not text:
        return ""
    return "".join(_KEEP_RUN.findall(text)).lower()


def topic_hash(text: str) -> str:
    """话题签名的短哈希（md5 前 8 位，跨进程稳定，可直接进缓存 key 元组）。"""
    return hashlib.md5(normalize_topic(text).encode("utf-8")).hexdigest()[:8]
