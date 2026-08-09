# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""memory.policy 记忆策略引擎的测试。

覆盖三层过滤（Usage / Visibility）与排序、Mode 检测、Policy Validator 审核。
"""

import memory.policy as policy
from memory.policy import (
    MODE_ACTIVE_JOIN,
    MODE_CASUAL_REPLY,
    MODE_CONFLICT_AVOID,
    MODE_HUMOR,
    MODE_RECOMMEND,
    MODE_TECH_HELP,
    USAGE_ANSWER_CONTEXT,
    USAGE_BOUNDARY_PROTECTION,
    USAGE_GROUP_CONTEXT,
    USAGE_HUMOR,
    USAGE_RECOMMEND,
    VISIBILITY_OPEN,
    VISIBILITY_RESTRICTED,
)


def _mem(**kwargs):
    data = {
        "type": "PREFERENCE",
        "content": "测试记忆",
        "usage_tags": [USAGE_RECOMMEND],
        "visibility": VISIBILITY_OPEN,
        "confidence": 0.9,
        "importance": 0.7,
    }
    data.update(kwargs)
    return data


def test_usage_blocked_when_not_in_mode():
    """TECH_HELP 模式下，RECOMMEND 用途的记忆不应被放行（Policy 优先于相似度）。"""
    allowed, score = policy.usage_allowed(MODE_TECH_HELP, _mem())
    assert not allowed
    assert score == 0


def test_usage_allowed_when_in_mode():
    """TECH_HELP 模式下，ANSWER_CONTEXT 用途的记忆应被放行并加分。"""
    allowed, score = policy.usage_allowed(
        MODE_TECH_HELP, _mem(usage_tags=[USAGE_ANSWER_CONTEXT], type="FACT")
    )
    assert allowed
    assert score > 0


def test_boundary_never_chat_material_in_casual():
    """普通聊天模式下，BOUNDARY_PROTECTION 记忆禁止进入聊天素材。"""
    allowed, _ = policy.usage_allowed(
        MODE_CASUAL_REPLY, _mem(usage_tags=[USAGE_BOUNDARY_PROTECTION], visibility=VISIBILITY_RESTRICTED)
    )
    assert not allowed


def test_visibility_restricted_denied_in_casual():
    """RESTRICTED 可见性在 CASUAL_REPLY 模式禁止访问。"""
    assert policy.visibility_allowed(MODE_CASUAL_REPLY, _mem(visibility=VISIBILITY_RESTRICTED)) is False


def test_visibility_restricted_allowed_in_conflict():
    """CONFLICT_AVOID 是 Behavior Guard 入口：允许 RESTRICTED 记忆。"""
    assert policy.visibility_allowed(MODE_CONFLICT_AVOID, _mem(visibility=VISIBILITY_RESTRICTED)) is True


def test_detect_mode_tech_and_recommend():
    """Mode 检测：技术关键词→TECH_HELP，推荐关键词→RECOMMEND。"""
    assert policy.detect_mode("我的 CUDA 运行不了，报错显存不足") == MODE_TECH_HELP
    assert policy.detect_mode("推荐一个好玩的游戏") == MODE_RECOMMEND


def test_detect_mode_proactive():
    """主动插话默认 ACTIVE_JOIN；话题带玩梗意味时进入 HUMOR。"""
    assert policy.detect_mode("（没人@你）", trigger="proactive") == MODE_ACTIVE_JOIN
    assert policy.detect_mode("（没人@你）", trigger="proactive", recent_topic="大家玩摸头梗") == MODE_HUMOR


def test_rank_places_mode_matched_higher():
    """排序：与模式匹配的记忆应排在不匹配记忆之前。"""
    matched = _mem(id="m1", usage_tags=[USAGE_ANSWER_CONTEXT], type="FACT", content="用户有RTX5080显卡")
    mismatched = _mem(id="m2", usage_tags=[USAGE_HUMOR], type="RELATION", content="用户喜欢开玩笑")
    ranked = policy.rank_memories([mismatched, matched], MODE_TECH_HELP, query="显卡")
    assert ranked[0]["id"] == "m1"


def test_split_behavior_constraints():
    """行为约束与聊天素材分离：RESTRICTED/BOUNDARY 记忆只进行为约束。"""
    open_mem = _mem(id="a", usage_tags=[USAGE_GROUP_CONTEXT], visibility=VISIBILITY_OPEN)
    restricted_mem = _mem(id="b", usage_tags=[USAGE_BOUNDARY_PROTECTION], visibility=VISIBILITY_RESTRICTED)
    behavior = policy.split_behavior_constraints([open_mem, restricted_mem])
    assert [m["id"] for m in behavior] == ["b"]


def test_validate_candidate_corrects_boundary_mislabel():
    """Policy Validator：敏感内容被误标为 TOPIC_START → 强制改为 BOUNDARY_PROTECTION + RESTRICTED。"""
    cand = policy.validate_candidate(
        {"content": "用户不喜欢未经允许摸头", "usage_tags": ["TOPIC_START"], "visibility": "OPEN"}
    )
    assert cand["usage_tags"] == [USAGE_BOUNDARY_PROTECTION]
    assert cand["visibility"] == VISIBILITY_RESTRICTED
    assert cand["behavior_rule"]


def test_stable_profile_facts_filters_persona():
    """User Profile 治理：人格判断被过滤，可观察行为保留。"""
    kept = policy.stable_profile_facts("温柔，乐观，经常聊游戏，在研究本地AI模型")
    assert "温柔" not in kept
    assert "乐观" not in kept
    assert any("聊游戏" in k or "AI" in k or "模型" in k for k in kept)
