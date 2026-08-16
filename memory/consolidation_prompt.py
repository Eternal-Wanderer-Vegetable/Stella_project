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

# ── 空输出许可的依据（2026-08-12 架构调整，勿删勿改宽）───────────────
# 过滤分两层：捕获层宽（允许错误，留待验证），晋升层严（Gate 1 三档 +
# 交叉验证 + 每用户配额）。prompt 里不再做置信度硬过滤与低价值排除——
# 那属于晋升层职责，且在 prompt 里过滤不可审计、不留数据、无法改进。
# 因此本模板不再包含置信度硬门槛与负例（它们挡的是低价值而非虚假）。
# 修改本模板前必须先跑 scripts/probe_consolidation.py --positive，
# 确保防编造条款与正例提取能力不回归。
# ──────────────────────────────────────────────────────────

CONSOLIDATION_PROMPT = """以下是一段群聊记录，请帮我分析一下，用 JSON 格式输出。

{current_summary}

群聊消息：
{messages}

先判断：这段记录里有没有「某个具体用户亲口说出的、关于他自己的」信息？
- 没有 → memory_candidates 填 []
- 有 → 输出这些，不要补充推断


判断依据是「这句话在描述谁」：描述发言者自身的属性（拥有什么设备、能不能吃什么、
住在哪、做什么工作、习惯如何）即为候选；描述第三方事物（新闻、别人的产品、他人）
才排除。不要因为句子里出现了产品名或地名就当作在讨论第三方——
「我的显卡是 X」描述的是发言者，不是 X。

【重要】memory_candidates 允许为空数组。
很多群聊窗口不包含任何关于发言者自身的信息。以下情况返回空数组：
- 窗口主要由图片、表情、单字回复、附和构成
- 讨论的完全是第三方事物（新闻、产品、他人），没有涉及发言者自身
- 需要推测才能得出结论（"他可能喜欢…"）——推断不是信息
返回空数组是正确行为，不是失败。没有就是没有，不要编造。

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
  "has_self_disclosure": false,
  "memory_candidates": []
}}

要求：
- short_term 必须输出
- short_term.recent_exchanges：列出最近 2~5 条对继续对话最关键、最能体现"谁说了什么"的发言；
  每条必须带上实际发送者的 user_id，尽量保留原话；严禁改换说话人、严禁把多人的话合并成一条
- recent_exchanges 里的 user_id 必须是纯数字 QQ 号；机器人自己发送的消息（标注为「不属于任何用户」）
  绝不能出现在 recent_exchanges 里，更不能把「我说」「机器人」等文字当作 user_id
- user_profiles 只写有变化的用户；**禁止保存人格判断、心理状态、价值判断**
- has_self_disclosure：这段记录里是否有「某个具体用户亲口说出的、关于他自己的」信息
  （拥有什么、能不能吃什么、住哪、职业、作息、身体状况等）。有填 true，没有填 false。
  只是图片/表情/单字附和/刷屏、或只在讨论第三方事物（新闻/产品/他人），填 false。
  这个判断只需二选一，不必自己提取内容——提取由后续步骤完成。
- memory_candidates 默认为空数组；只有「某个具体用户亲口说出的、关于他自己的、稳定的」信息才有候选；
  user_id 必须是该消息实际的发送者，严禁把 A 的发言归属给 B
- **memory_candidates 分类规则（极其重要）**：
  - 记忆类型必须且只能选一个：FACT=稳定事实 / PREFERENCE=明确喜欢或讨厌 / EVENT=重要事件 /
    PLAN=未来计划 / RELATION=人与人稳定互动 / STYLE=交流方式 / GROUP_CONTEXT=群体共同状态
  - 区分「当下状态」与「稳定属性」：只说一次"今天想吃炸鸡"应记为 EVENT 而非 PREFERENCE；
    但客观限制（过敏、忌口、身体条件）与客观事实（居住地、职业、设备型号）说一次即成立，
    记为 FACT。判断标准是这件事会不会明天就变，而不是它被说了几次
  - 一次性玩笑不要生成记忆
  - 涉及"不喜欢/讨厌/拒绝/边界/未经允许"等敏感内容时，usage_tags 必须是 BOUNDARY_PROTECTION
    或 CONFLICT_AVOID，visibility 必须是 RESTRICTED，绝不能当作聊天话题
  - usage_tags 填写这条记忆"将来应该被如何使用"（推荐/开场/回答背景…）
  - confidence 表示"这条信息有多确定"：>0.9 用户明确直接陈述、0.7-0.9 多次观察或强暗示、
    0.4-0.7 有依据但不完全确定。低置信候选照常输出并如实标注 confidence——
    后续由晋升闸门（交叉验证 / 复现次数 / 来源等级）决定它是否成为长期记忆，
    不要在这一步自行丢弃。confidence 低于 0.3 的猜测不要输出。
- source_message_ids 如果不知道可以填 []
- user_id 必须只写纯数字 QQ 号（例如 123456789），不要带"用户()"前缀，不要重复
- content 必须是可理解的自然语言，不要仅写关键词
- 群聊记录格式为「消息ID(id) 用户(QQ号): 内容」，所有输出里的 user_id 都必须沿用其中的 QQ 号归属，严禁张冠李戴
- 标注 `[这是机器人自己发送的消息，不属于任何用户]` 的是我（Bot）自己的发言，只用于理解上下文
  （比如用户回答「对」是在确认什么），严禁从其中提取任何关于用户的信息，也不要为我自己生成候选

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
