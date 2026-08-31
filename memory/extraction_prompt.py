# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆候选提取（两阶段整合的第二阶段）Prompt 模板。


与 consolidation_prompt.py 的分工：
- consolidation_prompt：阶段1，E4B，出 short_term + user_profiles + has_self_disclosure；
- 本模板：阶段2，27B，只做一件事——精确提取 memory_candidates。


为什么单独拆：E4B（4B）能总结主题，却系统性把候选提取判空
（log_2026_8_16_1717：7 批全空，明确「读到信息但主动弃掉」）。
候选提取是高精度抽取任务，需要 27B。


与整合 prompt 的语气差异（关键）：
本模板只在「阶段1 已判定这批含用户自我披露」时才被调用，因此基调是
「请把这些信息找出来并正确归类」，而非「没有就返回空」。空输出话术被
大幅削弱——把「是否值得记」的判断交给下游晋升闸门（Gate 1 三档 + 交叉
验证 + 配额），本步只负责「不漏」。但防编造/防张冠李戴的红线保持不变。


format 转义规则同 consolidation_prompt：字面花括号写 {{ }}，
{messages} / {types} / {usages} / {visibilities} 为占位符。


前缀缓存约束（2026-08-28 起）：``{messages}`` 必须留在模板最末尾，
理由与守卫同 consolidation_prompt.py，不再重复。
"""


_TYPES = "FACT / PREFERENCE / EVENT / PLAN / RELATION / STYLE / GROUP_CONTEXT"
_USAGES = (
    "TOPIC_START / TOPIC_CONTINUE / ANSWER_CONTEXT / RECOMMEND / PERSONALIZE / "
    "RELATION_CONTEXT / GROUP_CONTEXT / HUMOR / EMOTIONAL_SUPPORT / BOUNDARY_PROTECTION / CONFLICT_AVOID"
)
_VISIBILITIES = "OPEN / CONTEXTUAL / RESTRICTED / INTERNAL"


EXTRACTION_PROMPT = """你将读到一段群聊记录。已经有初步判断认为：这段记录里包含「某个具体用户亲口说出的、关于他自己的」信息。你的任务是把这些信息准确地提取成记忆候选，用 JSON 输出。


你的目标是「不漏」：把每一条用户亲口说出的、关于自己的稳定信息都提取出来。
是否值得长期保存，由后续的独立流程判断，不需要你在这一步顾虑——你只管如实提取。


判断依据是「这句话在描述谁」：
- 描述发言者自身（拥有什么设备、能不能吃什么、住在哪、做什么工作、作息习惯、
  身体状况、家庭情况…）→ 提取
- 描述第三方事物（新闻、别人的产品、他人）→ 不提取
不要因为句子里出现了产品名或地名就当作第三方——「我的显卡是 X」描述的是发言者。


区分「当下状态」与「稳定属性」：
- 只说一次「今天想吃炸鸡」→ EVENT（会变）
- 客观限制/客观事实（过敏、忌口、身体条件、居住地、职业、设备型号、作息规律）
  说一次即成立 → FACT（明天不会变）
判断标准是「这件事明天会不会变」，不是「被说了几次」。


正例（务必学会这类提取）：
消息「我时不时会失眠，所以醒得很早」
→ {{"user_id": "该发言者QQ号", "type": "FACT", "content": "有失眠情况，常常醒得很早",
    "usage_tags": ["ANSWER_CONTEXT"], "visibility": "OPEN",
    "importance": 0.6, "confidence": 0.9, "evidence": "用户直接陈述自己的作息与身体状况",
    "source_message_ids": []}}
消息「早餐一般只是一个馒头，自己家做的」
→ {{"user_id": "该发言者QQ号", "type": "FACT", "content": "早餐一般只吃一个自家做的馒头",
    "usage_tags": ["ANSWER_CONTEXT", "PERSONALIZE"], "visibility": "OPEN",
    "importance": 0.5, "confidence": 0.9, "evidence": "用户直接陈述自己的饮食习惯",
    "source_message_ids": []}}


请用以下 JSON 格式回复（不要代码块，直接输出 JSON）：
{{
  "memory_candidates": []
}}


规则：
- user_id 必须是该消息实际发送者的纯数字 QQ 号（例如 123456789），不带「用户()」前缀，
  严禁把 A 的发言归属给 B
- 标注「[这是机器人自己发送的消息，不属于任何用户]」的是机器人自己的发言，只用于理解上下文，
  严禁从中提取任何关于用户的信息
- 记忆类型必须且只能选一个：FACT=稳定事实 / PREFERENCE=明确喜欢或讨厌 / EVENT=重要事件 /
  PLAN=未来计划 / RELATION=人与人稳定互动 / STYLE=交流方式 / GROUP_CONTEXT=群体共同状态
- 涉及「不喜欢/讨厌/拒绝/边界/未经允许」等敏感内容时，usage_tags 必须是 BOUNDARY_PROTECTION
  或 CONFLICT_AVOID，visibility 必须是 RESTRICTED，绝不能当作聊天话题
- usage_tags 填这条记忆「将来应该被如何使用」，从这些里选：{usages}
- visibility 从这些里选：{visibilities}
- confidence 表示「这条信息有多确定」：>0.9 用户明确直接陈述、0.7-0.9 强暗示、
  0.4-0.7 有依据但不完全确定。如实标注即可，不要因为不确定就丢弃——低置信候选照常输出，
  由下游闸门决定去留。低于 0.3 的纯猜测才不要输出。
- importance 表示「这条信息对以后理解这个人有多大价值」，与 confidence 无关——
  一件事可以既非常确定又无关紧要：0.7-1.0 长期稳定且影响该怎么跟他相处（过敏忌口、
  职业、居住地、身体状况、明确说出的边界）；0.4-0.7 一般偏好与习惯；
  0.1-0.4 当下状态或琐事（今天想吃什么、临时情绪、一次性的事件）。
  **必须逐条自行判断后填写，不要照抄下面结构示例里的 0.0**——填 0 等于宣告
  这条信息毫无价值，它会被直接丢弃，再高的 confidence 也救不回来。
- content 必须是可理解的自然语言，不要只写关键词
- 绝对不要编造记录里没有的信息。刷屏、复读、表情、单字附和不包含任何可提取信息，跳过它们
- 一次性玩笑不要提取


每条候选的完整结构：
{{
  "user_id": "纯数字QQ号",
  "type": "{types}",
  "content": "可长期记忆的事实或偏好描述",
  "usage_tags": ["{usages}"],
  "visibility": "{visibilities}",
  "behavior_rule": "涉及边界/行为约束时写明；否则省略",
  "importance": 0.0,
  "confidence": 0.0,
  "evidence": "这条信息的依据",
  "source_message_ids": []
}}

===== 以上为固定规则；以下是本次待分析的数据 =====

群聊消息：
{messages}
"""


def format_extraction_prompt(messages: str) -> str:
    """填充提取 prompt：注入消息批次与 v2 分类枚举。"""
    return EXTRACTION_PROMPT.format(
        messages=messages,
        types=_TYPES,
        usages=_USAGES,
        visibilities=_VISIBILITIES,
    )
