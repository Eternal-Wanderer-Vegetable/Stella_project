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
from typing import Any


@dataclass
class ChatContext:
    """一次聊天处理会话的完整状态。

    属性分组：
    输入标识（user_id/group_id/msg_id/message/source_kind）来自 OneBot 事件；
    处理产物（raw_output/thought/action/reply/lines）由 pipeline 与解析钩子写入；
    诊断信息（trigger/intent/llm_* 系列）用于 thought 日志记录调试；
    结构化上下文（short_term/user_profile/memories_for_prompt）供 prompt 构建使用；
    任务调度（route/task_results/tool_summaries）由 Capability 层写入。
    """

    # ---- 输入标识 ----
    user_id: int
    group_id: int
    msg_id: int
    message: str
    # 消息来源：AT_MENTION=用户直接对 Bot 说 / PASSIVE=被动摄入的群聊
    source_kind: str = "PASSIVE"
    # 记忆与画像的归属空间。group_id 始终是真实 QQ 群号；group_shared_space 是
    # 「当下这场对话的状态」之外的长期认知归属（见 config/spaces.py 两层归属的
    # 分界线），二者不可混用。留空时按群号自动解析（隐式空间 = 群号字符串）。
    group_shared_space: str = ""

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

    # ---- 会话上下文压缩 ----
    # 尾巴起点消息 id：会话压缩用它计算不与尾巴重叠的待压缩区间。
    # 0 表示无尾巴（新群或全部消息都超出时间窗）。
    tail_start_id: int = 0

    # ---- Capability Router / Comes（任务调度层） ----
    # Router 的判定结论（capability.router.types.Route）。类型写 Any 是刻意的：
    # core 是「与业务无关的编排骨架」，不该 import capability——反向依赖会成环。
    route: Any = None
    # Comes 产出的 Result 列表。**data 字段不进 prompt**，只用于日志与调试。
    task_results: list = field(default_factory=list)
    # 压缩后的工具结果摘要，是唯一会被拼进 Stella prompt 的部分
    # （工具结果同样不该污染聊天上下文，见 core/pipeline.py 的 _tool_result_section）。
    tool_summaries: list[str] = field(default_factory=list)

    # ---- 平台原始句柄（opaque） ----
    # Comes 调 AstrBot 工具时，工具 handler 内部会用 event.send() /
    # event.bot.call_action()，必须是真实对象，构造不出等价替身。core 不解释它们的
    # 类型、也不碰它们的任何方法，只负责从接入层传递到 Capability 层。
    # repr=False：OneBot 事件的 repr 会把整条消息与 sender 全展开，
    # 日志里 ChatContext 一旦被 repr 就会刷屏。
    raw_event: Any = field(default=None, repr=False)
    bot: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """自动解析共享空间归属，不要求调用方逐个传参。

        ``resolve_space`` 延迟导入：避免 core 在 import 阶段依赖 config 子模块
        （与 settings.py 对 nonebot logger 的延迟导入同理）。
        """
        if not self.group_shared_space and self.group_id:
            from config.spaces import resolve_space

            self.group_shared_space = resolve_space(self.group_id)
