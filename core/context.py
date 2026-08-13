# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""聊天上下文数据模型。

定义 ChatContext：一次消息处理从进入 pipeline 到产出回复的“运行期载体”。
它同时携带输入信息（谁、在哪个群、什么消息）、处理产物（原始 LLM 输出、
thought/action/reply、多行回复）以及供日志与 prompt 构建用的诊断与结构化
上下文。全程由 Pipeline 各钩子和 LLM 后端共同读写，是各模块间传递数据的唯一通道。
"""

from dataclasses import dataclass, field


@dataclass
class ChatContext:
    """一次聊天处理会话的完整状态。

    属性分组：
    输入标识（user_id/group_id/msg_id/message/source_kind）来自 OneBot 事件；
    处理产物（raw_output/thought/action/reply/lines）由 pipeline 与解析钩子写入；
    诊断信息（trigger/intent/llm_* 系列）用于 thought 日志记录调试；
    结构化上下文（short_term/user_profile/memories_for_prompt）供 prompt 构建使用。
    """

    # ---- 输入标识 ----
    user_id: int
    group_id: int
    msg_id: int
    message: str
    # 消息来源：AT_MENTION=用户直接对 Bot 说 / PASSIVE=被动摄入的群聊
    source_kind: str = "PASSIVE"

    # ---- 处理产物 ----
    raw_output: str = ""
    thought: str = ""
    action: str = "NONE"
    reply: str = ""
    # 多行回复内容，供后续分条发送（受 MAX_REPLY_LINES 限制）
    lines: list[str] = field(default_factory=list)

    # ---- LLM 调用诊断信息（供 thought 日志记录） ----
    trigger: str = "reply"          # reply=@回复 / proactive=主动发言
    # 本次调用的意图（诊断 + prompt 组装用），不参与检索/模式判断：
    #   ""               普通对话
    #   "proactive_at"   主动 @ 某位用户（ctx.message 是任务指令，不是用户输入）
    #   "proactive_join" 主动插话
    # 不新增 trigger 取值：detect_mode / build_user_context / retrieval_v2
    # 三处都在判断 trigger == "proactive"，扩充它的取值集合容易漏改。
    intent: str = ""
    llm_backend: str = ""           # 实际调用的后端名（lm_studio）
    llm_model: str = ""             # 实际使用的模型名/站点
    system_prompt_len: int = 0      # 系统提示词字符数
    prompt_log: str = ""            # 发给 LLM 的完整 prompt（含上下文拼接）
    llm_elapsed: float = 0.0        # LLM 调用耗时（秒）
    # ---- 结构化上下文供 prompt_builder 使用 ----
    short_term: str = ""
    user_profile: str = ""
    memories_for_prompt: list[dict] = field(default_factory=list)
    # ---- 记忆系统 v2：模式 / 分区记忆 / 行为约束 / 决策轨迹 ----
    memory_mode: str = "CASUAL_REPLY"          # Stella 行为模式
    conversation_memories: list[dict] = field(default_factory=list)  # 聊天素材
    behavior_constraints: list[dict] = field(default_factory=list)   # 行为约束
    memory_trace: dict = field(default_factory=dict)                 # 决策轨迹
