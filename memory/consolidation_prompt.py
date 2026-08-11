# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆整合任务的系统 Prompt 模板。

把一段新消息批次 + 当前短期摘要，要求本地 LLM 一次性输出三样东西：
短期摘要（short_term）、有变化的用户画像（user_profiles）以及值得长期
记忆的候选（memory_candidates），全部以严格 JSON 结构返回。

v2：memory_candidates 必须附带 type / usage_tags / visibility / confidence /
behavior_rule（见 Memory Schema Specification）。候选不是最终记忆，后续还
会经过 Policy Validator 审核与 MemoryManager 晋升。

模板使用普通字符串 + ``str.format()`` 填充：JSON 示例里的字面花括号必须写成
``{{`` / ``}}``（format 的转义），``{current_summary}`` / ``{messages}`` /
``{types}`` / ``{usages}`` / ``{visibilities}`` 为运行时占位符。
"""

# 允许的 Memory Type（枚举）
_TYPES = "FACT / PREFERENCE / EVENT / PLAN / RELATION / STYLE / GROUP_CONTEXT"
# 允许的 Usage 标签（枚举）
_USAGES = (
    "TOPIC_START / TOPIC_CONTINUE / ANSWER_CONTEXT / RECOMMEND / PERSONALIZE / "
    "RELATION_CONTEXT / GROUP_CONTEXT / HUMOR / EMOTIONAL_SUPPORT / BOUNDARY_PROTECTION / CONFLICT_AVOID"
)
# 允许的 Visibility（枚举）
_VISIBILITIES = "OPEN / CONTEXTUAL / RESTRICTED / INTERNAL"

CONSOLIDATION_PROMPT = """以下是一段群聊记录，请帮我分析一下，用 JSON 格式输出。

{current_summary}

群聊消息：
{messages}

先判断：这段记录里有没有「某个具体用户亲口说出的、关于他自己的、稳定的」信息？
- 没有 → memory_candidates 填 []
- 有 → 只输出这些，不要补充推断

【重要】memory_candidates 允许为空数组。
绝大多数群聊窗口不包含值得长期记住的信息。以下情况必须返回空数组：
- 窗口主要由图片、表情、单字回复、附和构成
- 只有话题讨论，没有关于某个具体用户的稳定信息
- 讨论的是第三方事物（新闻、产品、他人），不是发言者自身的属性
- 需要推测才能得出结论（"他可能喜欢…"）

宁可返回空数组，也不要输出不确定的候选。返回空数组是正确行为，不是失败。

请用以下 JSON 格式回复（不需要代码块，直接输出 JSON）：
{{
  "short_term": {{
    "active_summary": "最多 15 字概括当前群聊主题",
    "pending_topic": "进行中的话题（没有则填无）",
    "recent_exchanges": [
      {{"user_id": "用户QQ号", "content": "最近关键的发言原话或要点"}}
    ]
  }},
  "user_profiles": [],
  "memory_candidates": []
}}

负例一（刷屏，应返回空）：
消息ID(1) 用户(1001): [图片]
消息ID(2) 用户(1002): 哈哈哈
消息ID(3) 用户(1001): 确实
消息ID(4) 用户(1003): [图片]
→ {{"short_term": {{"active_summary": "群里刷图闲聊", "pending_topic": "无", "recent_exchanges": [{{"user_id": "1002", "content": "哈哈哈"}}]}}, "user_profiles": [], "memory_candidates": []}}

负例二（讨论第三方，应返回空）：
消息ID(1) 用户(1001): 某品牌新笔记本才798g
消息ID(2) 用户(1002): 这么轻
消息ID(3) 用户(1001): 官方拆机视频里说的
→ {{"short_term": {{"active_summary": "讨论某品牌笔记本重量", "pending_topic": "无", "recent_exchanges": [{{"user_id": "1001", "content": "某品牌新笔记本才798g"}}]}}, "user_profiles": [], "memory_candidates": []}}

负例三（技术问答，有话题无稳定属性，应返回空）：
消息ID(1) 用户(1001): 这个报错怎么解决
消息ID(2) 用户(1002): 你试试重装依赖
消息ID(3) 用户(1001): 好了谢谢
→ {{"short_term": {{"active_summary": "排查报错并解决", "pending_topic": "无", "recent_exchanges": [{{"user_id": "1002", "content": "你试试重装依赖"}}]}}, "user_profiles": [], "memory_candidates": []}}

要求：
- short_term 必须输出
- short_term.recent_exchanges：列出最近 2~5 条对继续对话最关键、最能体现"谁说了什么"的发言；
  每条必须带上实际发送者的 user_id，尽量保留原话；严禁改换说话人、严禁把多人的话合并成一条
- user_profiles 只写有变化的用户；**禁止保存人格判断、心理状态、价值判断**
- memory_candidates 默认为空数组；只有「某个具体用户亲口说出的、关于他自己的、稳定的」信息才有候选；
  user_id 必须是该消息实际的发送者，严禁把 A 的发言归属给 B
- **memory_candidates 分类规则（极其重要）**：
  - 记忆类型必须且只能选一个：FACT=稳定事实 / PREFERENCE=明确喜欢或讨厌 / EVENT=重要事件 /
    PLAN=未来计划 / RELATION=人与人稳定互动 / STYLE=交流方式 / GROUP_CONTEXT=群体共同状态
  - 单次表达不等于长期事实：只说一次"今天想吃炸鸡"不要写成 PREFERENCE，最多是 EVENT 或直接不保存
  - 一次性玩笑不要生成记忆
  - 涉及"不喜欢/讨厌/拒绝/边界/未经允许"等敏感内容时，usage_tags 必须是 BOUNDARY_PROTECTION
    或 CONFLICT_AVOID，visibility 必须是 RESTRICTED，绝不能当作聊天话题
  - usage_tags 填写这条记忆"将来应该被如何使用"（推荐/开场/回答背景…）
  - confidence 表示"这条信息有多确定"：>0.9 用户明确直接陈述、0.7-0.9 多次观察或强暗示、
    <0.7 不要输出这条候选（低置信就弃掉，不要进入 memory_candidates）
- source_message_ids 如果不知道可以填 []
- user_id 必须只写纯数字 QQ 号（例如 123456789），不要带"用户()"前缀，不要重复
- content 必须是可理解的自然语言，不要仅写关键词
- 群聊记录格式为「消息ID(id) 用户(QQ号): 内容」，所有输出里的 user_id 都必须沿用其中的 QQ 号归属，严禁张冠李戴

若确实需要输出候选（少数情况），每条结构如下：
{{
  "user_id": "纯数字QQ号",
  "type": "{types}",
  "content": "可长期记忆的事实或偏好描述",
  "usage_tags": ["{usages}"],
  "visibility": "{visibilities}",
  "behavior_rule": "涉及边界/行为约束时写明；否则省略",
  "importance": 0.0,
  "confidence": 0.0,
  "evidence": "为何认为这条信息有价值",
  "source_message_ids": []
}}
"""


def format_consolidation_prompt(current_summary: str, messages: str) -> str:
    """填充整合 prompt：注入当前摘要、消息批次与 v2 分类枚举。"""
    return CONSOLIDATION_PROMPT.format(
        current_summary=current_summary,
        messages=messages,
        types=_TYPES,
        usages=_USAGES,
        visibilities=_VISIBILITIES,
    )
