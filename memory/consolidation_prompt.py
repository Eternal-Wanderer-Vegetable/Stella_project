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