# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""text_similarity 的行为基线。


这套逻辑原先在 memory_manager / compressor / retrieval_v2 各有一份副本，
收敛为单一模块后由本文件锁定行为：三个调用方都依赖它，改动会同时影响
候选晋升、周度压缩与 v2 检索合并。
"""
from memory.text_similarity import (
    SIMILARITY_THRESHOLD,
    is_similar,
    jaccard_similarity,
    merge_content,
    normalize_text,
)


def test_normalize_text_strips_punctuation_and_case():
    assert normalize_text("  RTX-5080，跑27B模型  ") == "rtx 5080 跑27b模型"
    assert normalize_text("") == ""
    assert normalize_text(None) == ""


def test_jaccard_edges():
    assert jaccard_similarity(set(), {"a"}) == 0.0
    assert jaccard_similarity({"a"}, {"a"}) == 1.0
    assert jaccard_similarity({"a", "b"}, {"b", "c"}) == 1 / 3


def test_is_similar_identical_and_substring():
    assert is_similar("喜欢玩合作游戏", "喜欢玩合作游戏")
    # 一方是另一方的更完整表述
    assert is_similar("不吃香菜", "不吃香菜，点外卖要备注")


def test_is_similar_rejects_unrelated():
    assert not is_similar("喜欢玩合作游戏", "在杭州做后端开发")


def test_is_similar_empty_is_never_similar():
    assert not is_similar("", "任意内容")
    assert not is_similar("任意内容", "")
    assert not is_similar(None, None)


def test_is_similar_threshold_is_configurable():
    a, b = "喜欢 玩 合作 游戏", "喜欢 玩 单机 游戏"
    # 2/6 交集 → 0.333：默认阈值下不相似，放宽阈值后相似
    assert not is_similar(a, b)
    assert is_similar(a, b, threshold=0.3)
    assert SIMILARITY_THRESHOLD == 0.65


def test_merge_content_prefers_more_complete():
    assert merge_content("不吃香菜", "不吃香菜，点外卖要备注") == "不吃香菜，点外卖要备注"
    assert merge_content("不吃香菜，点外卖要备注", "不吃香菜") == "不吃香菜，点外卖要备注"


def test_merge_content_joins_distinct():
    assert merge_content("在杭州工作", "主要写Go") == "在杭州工作；主要写Go"


def test_merge_content_handles_empty():
    assert merge_content("", "只有新内容") == "只有新内容"
    assert merge_content("只有旧内容", "") == "只有旧内容"
    assert merge_content("", "") == ""
