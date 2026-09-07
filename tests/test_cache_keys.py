# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""memory.cache_keys 的测试：话题归一化与记忆历史版本。

归一化是文本级的（小写 + 去标点/表情/空白），两个方向都要钉住：
- 同一文本的书写差异（标点/大小写/空格/表情）→ 相同签名；
- 换措辞即换话题 → 必然不同（宁可本地重查，也不复用旧话题的检索结果）。
"""

from memory.cache_keys import (
    POLICY_VERSION,
    bump_memory_history,
    memory_history_version,
    normalize_topic,
    topic_hash,
)


def test_writing_differences_do_not_change_signature():
    """标点/表情/空白/大小写是书写差异，不是话题差异。"""
    assert normalize_topic("显卡好贵啊！！") == normalize_topic("显卡好贵啊")
    assert normalize_topic("Helldivers2 好玩") == normalize_topic("helldivers2好玩")
    assert normalize_topic("你 好 呀") == normalize_topic("你好呀")
    assert normalize_topic("显卡，多少钱？😄") == normalize_topic("显卡多少钱")


def test_different_phrasing_is_different_topic():
    """换措辞 = 换桶：这是「话题变化后不复用旧检索结果」的直接实现。

    文本级归一化刻意不做语义粗化——中文滑窗 n-gram 对措辞变化给不出
    稳定签名，而错误共享桶会让 Bot 拿旧话题的记忆接新话题的话。
    """
    assert normalize_topic("最近显卡是不是涨价了") != normalize_topic("你们说的4090好贵是怎么回事")


def test_empty_and_punctuation_only_normalize_to_empty():
    """空文本/纯标点表情 → 空签名（这类查询本就走新鲜度检索，共桶无害）。"""
    assert normalize_topic("") == ""
    assert normalize_topic("！！！😄～") == ""


def test_topic_hash_stable_and_discriminating():
    """哈希跨调用稳定；同文本同哈希、异文本异哈希。"""
    assert topic_hash("显卡多少钱？") == topic_hash("显卡多少钱")
    assert topic_hash("显卡多少钱") != topic_hash("我明天要出差")
    # 空签名也有确定哈希，不抛异常
    assert isinstance(topic_hash(""), str) and topic_hash("")


def test_policy_version_is_pinned():
    """POLICY_VERSION 必须是非空字符串：所有缓存 key 都编入它。"""
    assert isinstance(POLICY_VERSION, str) and POLICY_VERSION


def test_memory_history_version_bumps_monotonically():
    before = memory_history_version()
    bump_memory_history()
    bump_memory_history()
    assert memory_history_version() == before + 2
