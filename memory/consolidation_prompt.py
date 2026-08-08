# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆整合任务的系统 Prompt 模板。

把一段新消息批次 + 当前短期摘要，要求本地/在线 LLM 一次性输出三样东西：
短期摘要（short_term）、有变化的用户画像（user_profiles）以及值得长期
记忆的候选（memory_candidates），全部以严格 JSON 结构返回。
"""
CONSOLIDATION_PROMPT = """以下是一段群聊记录，请帮我分析一下，用 JSON 格式输出。

{current_summary}

群聊消息：
{messages}

请用以下 JSON 格式回复（不需要代码块，直接输出 JSON）：
{{
  "short_term": {{
    "active_summary": "最多 15 字概括当前群聊主题",
    "pending_topic": "进行中的话题（没有则填无）"
  }},
  "user_profiles": [
    {{
      "user_id": "用户 ID",
      "personality_traits": "推测的性格，10 字内",
      "agent_attitude": "对机器人态度（友好/中立/冷淡/敌对）"
    }}
  ],
  "memory_candidates": [
    {{
      "user_id": "用户 ID",
      "type": "FACT/PREFERENCE/EVENT/PLAN/RELATION",
      "content": "可长期记忆的事实或偏好描述",
      "importance": 0.0,
      "confidence": 0.0,
      "evidence": "为何认为这条信息有价值",
      "source_message_ids": []
    }}
  ]
}}

要求：
- short_term 必须输出
- user_profiles 只写有变化的用户
- memory_candidates 只写当前批次中值得长期记忆的候选，没有就空数组
- source_message_ids 如果不知道可以填 []
- user_id 必须只写纯数字 QQ 号（例如 123456789），不要带"用户()"前缀，不要重复
- content 必须是可理解的自然语言，不要仅写关键词
"""