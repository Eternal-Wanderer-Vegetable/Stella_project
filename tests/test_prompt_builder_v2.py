# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""memory.prompt_builder v2 分区注入 与 memory.trace 决策追踪的测试。"""

import sqlite3

import memory.prompt_builder as prompt_builder
import memory.trace as trace


def test_build_v2_prompt_context_partitions_sections():
    """v2 分区注入：聊天素材与行为约束必须分开，绝不混合。"""
    conversation = [
        {"content": "用户喜欢合作类游戏，例如 Helldivers2"},
        {"content": "用户最近在研究本地AI部署"},
    ]
    behavior = [
        {"content": "用户不喜欢未经允许摸头", "behavior_rule": "避免对该用户进行摸头互动"},
    ]
    prompt = prompt_builder.build_v2_prompt_context(
        "最近在聊游戏",
        "关于用户的可观察特征: 经常聊游戏",
        conversation,
        behavior,
        current_user_id=100,
        mode="CASUAL_REPLY",
    )

    assert "可参考的聊天背景" in prompt
    assert "Helldivers2" in prompt
    assert "交流注意" in prompt
    assert "避免对该用户进行摸头互动" in prompt
    # 行为约束没有混进聊天素材区
    chat_section = prompt.split("交流注意")[0]
    assert "摸头" not in chat_section


def test_build_v2_prompt_context_omits_empty_sections():
    """没有行为约束时，不输出空的“交流注意”标题。"""
    prompt = prompt_builder.build_v2_prompt_context(
        "摘要", "", [{"content": "用户喜欢游戏"}], [], current_user_id=None
    )
    assert "交流注意" not in prompt
    assert "可参考的聊天背景" in prompt


def test_tech_mode_has_larger_conversation_budget():
    """技术模式放宽聊天素材 token 预算。"""
    conv = [{"content": f"测试内容第{i}条" * 4} for i in range(50)]
    casual = prompt_builder.build_conversation_section(conv, max_tokens=500)
    tech = prompt_builder.build_conversation_section(conv, max_tokens=1000)
    assert prompt_builder.estimate_tokens(tech) > prompt_builder.estimate_tokens(casual)


def test_time_section_present_and_first():
    """当前时间必须出现且位于最前——它是环境事实，应先于任何对话内容。"""
    out = prompt_builder.build_v2_prompt_context("摘要", "画像", [], [], current_user_id=1001)
    assert out.startswith("现在是 ")
    assert "星期" in out


def test_trace_records_and_statistics(tmp_path, monkeypatch):
    """决策追踪：写入 memory_traces 表并产出统计。"""
    db_path = tmp_path / "agent_memory.db"
    conn = sqlite3.connect(db_path)
    conn.close()
    monkeypatch.setattr(trace, "DB_PATH", db_path)
    monkeypatch.setattr(trace, "MEMORY_TRACE_ENABLED", True)

    trace.record_trace(
        group_id=1,
        user_id=100,
        message="推荐游戏",
        mode="RECOMMEND",
        trigger="reply",
        candidates=[{"id": "c1"}, {"id": "c2"}],
        final=[{"id": "c1", "_score": 0.9}],
        rejected=[{"id": "c2"}],
        behavior=[],
        prompt_snapshot="prompt...",
        output="回复",
    )

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT mode, final_ids, rejected_ids FROM memory_traces").fetchone()
    conn.close()
    assert row[0] == "RECOMMEND"
    assert '"c1"' in row[1]
    assert '"c2"' in row[2]

    stats = trace.memory_statistics(days=7)
    assert stats["total_traces"] >= 1
    assert stats["avg_memories_per_reply"] >= 0
