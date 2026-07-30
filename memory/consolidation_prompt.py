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
  "long_term_memories": [
    {{
      "user_id": "用户 ID",
      "summary": "值得记住的事，10 字内",
      "importance": 5
    }}
  ]
}}

要求：
- short_term 必须输出
- user_profiles 只写有变化的用户
- long_term_memories 只写重要的事（importance >= 5），没有就空数组
- 没有相关内容填空数组或无
"""