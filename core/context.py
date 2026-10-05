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

# 消息身份信封的边界值（多人身份修复计划 §6.2 字段规格）
_ENVELOPE_DISPLAY_NAME_MAX = 64
_ENVELOPE_MENTIONS_MAX = 32


def normalize_display_name(raw: str | None) -> str:
    """展示用昵称规范化：去控制字符/提示标记、截到 64 字符。

    display name 只是展示数据，**永远不能作稳定身份键**；清理它是因为群名片
    是用户可控文本，可能携带 【现在 】等 prompt 结构标记或换行注入。
    """
    text = str(raw or "")
    cleaned = "".join(
        ch for ch in text if ch not in "\r\n\t" and _not_prompt_marker_char(ch)
    )
    return cleaned.strip()[:_ENVELOPE_DISPLAY_NAME_MAX]


def _not_prompt_marker_char(ch: str) -> bool:
    import unicodedata

    return unicodedata.category(ch) != "Cc" and ch not in "【】"


def normalize_mentions(raw) -> tuple[str, ...]:
    """@ 目标规范化：字符串化、去重、剔除空值，上限 32 个。"""
    out: list[str] = []
    for item in raw or ():
        uid = str(item or "").strip()
        if not uid or uid.lower() == "all" or uid in out:
            continue
        out.append(uid)
        if len(out) >= _ENVELOPE_MENTIONS_MAX:
            break
    return tuple(out)


@dataclass(frozen=True)
class MessageIdentityEnvelope:
    """一条平台消息的身份信封（多人身份修复计划 §6.2）。

    全部字段来自**平台事件/可信 ctx/已入库行**，绝不从正文、昵称或话题连续性
    推导。uid 一律是项目现有的稳定 uid 字符串；平台 message ID 在持久化边界
    统一成字符串。``apply`` 把值落到 ChatContext 的扁平字段上（投影只传有界
    JSON primitive，见 ChatContext._PROJECTION_FIELDS v4）。
    """

    sender_display_name: str = ""
    reply_to_msg_id: str = ""
    reply_target_user_id: str = ""
    mentioned_user_ids: tuple[str, ...] = ()
    logical_message_id: str = ""
    part_index: int = 0
    origin_msg_id: str = ""
    reply_recipient_user_id: str = ""
    turn_id: str = ""
    recorded_row_id: int = 0
    relation_version: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sender_display_name", normalize_display_name(self.sender_display_name)
        )
        object.__setattr__(self, "mentioned_user_ids", normalize_mentions(self.mentioned_user_ids))
        object.__setattr__(self, "part_index", max(0, int(self.part_index or 0)))
        object.__setattr__(self, "reply_to_msg_id", str(self.reply_to_msg_id or ""))
        object.__setattr__(self, "reply_target_user_id", str(self.reply_target_user_id or ""))
        object.__setattr__(self, "origin_msg_id", str(self.origin_msg_id or ""))
        object.__setattr__(
            self, "reply_recipient_user_id", str(self.reply_recipient_user_id or "")
        )

    def apply(self, ctx: "ChatContext") -> "ChatContext":
        """把信封写入 ChatContext 的扁平字段（返回同一 ctx，链式友好）。"""
        ctx.sender_display_name = self.sender_display_name
        ctx.reply_to_msg_id = self.reply_to_msg_id
        ctx.reply_target_user_id = self.reply_target_user_id
        ctx.mentioned_user_ids = self.mentioned_user_ids
        ctx.logical_message_id = self.logical_message_id
        ctx.part_index = self.part_index
        ctx.origin_msg_id = self.origin_msg_id
        ctx.reply_recipient_user_id = self.reply_recipient_user_id
        if self.turn_id:
            ctx.turn_id = self.turn_id
        ctx.recorded_row_id = self.recorded_row_id
        ctx.relation_version = self.relation_version
        return ctx

    @classmethod
    def from_context(cls, ctx: "ChatContext") -> "MessageIdentityEnvelope":
        """从已带信封字段的 ctx 取回（round-trip 用）。"""
        return cls(
            sender_display_name=ctx.sender_display_name,
            reply_to_msg_id=ctx.reply_to_msg_id,
            reply_target_user_id=ctx.reply_target_user_id,
            mentioned_user_ids=tuple(ctx.mentioned_user_ids),
            logical_message_id=ctx.logical_message_id,
            part_index=ctx.part_index,
            origin_msg_id=ctx.origin_msg_id,
            reply_recipient_user_id=ctx.reply_recipient_user_id,
            turn_id=ctx.turn_id,
            recorded_row_id=ctx.recorded_row_id,
            relation_version=ctx.relation_version,
        )


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
    # 消息来源：AT_MENTION=用户直接对 Bot 说 / PASSIVE=被动摄入的群聊 /
    # PRIVATE_DIRECT=用户在私聊里直接对 Bot 说 / BOT_SELF=Bot 自己的发言
    source_kind: str = "PASSIVE"
    # 记忆与画像的归属空间。group_id 始终是真实 QQ 群号（私聊为 0，见下）；
    # group_shared_space 是「当下这场对话的状态」之外的长期认知归属
    # （见 config/spaces.py 两层归属的分界线），二者不可混用。留空时按群号
    # 自动解析（隐式空间 = 群号字符串）。
    group_shared_space: str = ""

    # ---- 会话身份（计划 §6.1：ConversationRef 投影到运行期载体） ----
    # group_id 在私聊轮次里恒为 0（兼容占位，**不是**公共会话号）；真实身份
    # 在下面四个字段里。storage_session_id 是注册表分配的存储键：群=正整数
    # 群号、WebChat=-1、私聊=负整数；存储/摘要/checkpoint 一律用它
    # （storage_key()），绝不能用负号反推种类。
    conversation_kind: str = ""  # group / private / webchat；空 = 旧入口未升级
    conversation_key: str = ""  # 规范键 qq:<bot>:group:<gid> 等；空 = 旧入口
    bot_id: str = ""  # 接入 Bot 的 self_id（个人 owner 键 person:qq:<bot>:<uid> 用）
    peer_id: str = ""  # 群=群号；私聊=sender QQ 号；WebChat=主体
    storage_session_id: int = 0  # 0 = 未升级入口，按 group_id 兼容

    # ---- 消息身份信封（多人身份修复计划 §6.2，v4 投影） ----
    # 全部来自平台事件/可信 ctx/已入库行；缺省空值 = 「关系未知」，消费方
    # （tail 渲染/纠正解析）按 unknown 处理，绝不按相邻文本或最近发言人补。
    # sender_display_name 是展示数据，不作稳定身份键。
    sender_display_name: str = ""
    reply_to_msg_id: str = ""  # 平台 message ID（字符串）
    reply_target_user_id: str = ""  # 被回复消息作者（同 canonical conversation+bot 解析）
    mentioned_user_ids: tuple[str, ...] = ()
    logical_message_id: str = ""  # 一次多气泡回复共享的逻辑单元 ID
    part_index: int = 0  # 逻辑单元内的气泡序号（非负）
    origin_msg_id: str = ""  # BOT_SELF 逻辑单元对应的源消息（被回复/被触发那条）
    reply_recipient_user_id: str = ""  # BOT_SELF 逻辑单元的收件人（不是作者）
    recorded_row_id: int = 0  # record_message 写入后的行 id（0=未入库）
    relation_version: int = 0  # 信封写入时的关系 schema 版本（0=无关系）
    identity_revision: int = 0  # 会话身份版本快照（M3 写入；缓存/CAS 用）
    # 每轮重新生成的当前用户身份 capsule（多人身份修复计划 §6.3，M3）：
    # 从平台 ID/已验证 alias/reply target/冲突状态构造，进 prompt 稳定区。
    identity_capsule: str = ""

    def storage_key(self) -> int:
        """历史消息/摘要/checkpoint 的物理会话键。

        已升级入口返回注册表分配的 storage_session_id；旧入口（未设置身份
        字段）按 group_id 兼容。**只有**存储语义允许用本键；需要真实群号的
        消费者必须先判 conversation_kind == "group"。
        """
        return self.storage_session_id or self.group_id

    @property
    def trace_scope(self) -> str:
        """观测/详细日志的 scope 标签：规范会话键优先，旧入口回退 ``qq:<群号>``。

        私聊轮次的 group_id 是 0，任何 ``qq:{ctx.group_id}`` 拼接都必须改用
        本属性，否则全部私聊共享同一个 trace scope（计划 §6.2）。
        """
        return self.conversation_key or f"qq:{self.group_id}"

    # ---- 处理产物 ----
    raw_output: str = ""
    thought: str = ""
    action: str = "NONE"
    reply: str = ""
    # 多行回复内容，供后续分条发送（受 MAX_REPLY_LINES 限制）
    lines: list[str] = field(default_factory=list)

    # ---- LLM 调用诊断信息（供 thought 日志记录） ----
    trigger: str = "reply"  # reply=@回复 / proactive=主动发言
    # 本次调用的意图（诊断 + prompt 组装用），不参与检索/模式判断：
    #   ""               普通对话
    #   "proactive_at"   主动 @ 某位用户（ctx.message 是任务指令，不是用户输入）
    #   "proactive_join" 主动插话
    # 不新增 trigger 取值：detect_mode / build_user_context / retrieval_v2
    # 三处都在判断 trigger == "proactive"，扩充它的取值集合容易漏改。
    intent: str = ""
    llm_backend: str = ""  # 实际调用的后端名（lm_studio）
    llm_model: str = ""  # 实际使用的模型名/站点
    system_prompt_len: int = 0  # 系统提示词字符数
    prompt_log: str = ""  # 发给 LLM 的完整 prompt（含上下文拼接）
    llm_elapsed: float = 0.0  # LLM 调用耗时（秒）
    llm_call_count: int = 0  # 本次上下文触发的 LLM 调用次数
    gate_path: str = ""  # hard_trigger / proactive / silent
    gate_score: float = 0.0
    gate_reasons: tuple[str, ...] = field(default_factory=tuple)
    context_window_tokens: int = 0
    prompt_budget_tokens: int = 0
    prompt_estimated_tokens: int = 0
    prompt_truncated: bool = False
    # ---- 结构化上下文供 prompt_builder 使用 ----
    short_term: str = ""
    user_profile: str = ""
    # 明确目标用户的关系性称呼；不替代平台昵称，也不用于群级主动发言。
    preferred_address: str | None = None
    memories_for_prompt: list[dict] = field(default_factory=list)
    # ---- 记忆系统 v2：模式 / 分区记忆 / 行为约束 / 决策轨迹 ----
    memory_mode: str = "CASUAL_REPLY"  # Stella 行为模式
    conversation_memories: list[dict] = field(default_factory=list)  # 聊天素材
    behavior_constraints: list[dict] = field(default_factory=list)  # 行为约束
    memory_trace: dict = field(default_factory=dict)  # 决策轨迹

    # ---- 受限 Planner（设计阶段五：深度回复路径） ----
    # 三者均默认空/False = 走快速路径（本地 Gate → 检索 → 单次 LLM）。
    planner_trigger: str = (
        ""  # 本地触发原因：history_reference / ambiguity / proactive_unclear
    )
    planner_action: str = ""  # Planner 决策：REPLY / QUERY_MEMORY / WAIT
    planner_wait: bool = False  # WAIT：本轮不回复，等更多消息（仅主动路径；不轮询 LLM）
    deep_tool_calls: int = (
        0  # 本轮深度记忆查询次数（上限 PLANNER_MAX_TOOL_CALLS_PER_TURN）
    )

    # ---- 会话上下文压缩 ----
    # 尾巴起点消息 id：会话压缩用它计算不与尾巴重叠的待压缩区间。
    # 0 表示无尾巴（新群或全部消息都超出时间窗）。
    tail_start_id: int = 0

    # ---- 归属整改（复核 F1，v5 投影）：typed 检索 / 合同 / 证据 / 决策 / 处置 ----
    # typed 检索查询：主动验证等场景由服务端生成（候选主题+目标近期对话），
    # 非空时检索消费它而不是任务指令模板；空 = 沿用旧推导（行为不变）。
    retrieval_query: str = ""
    # 主动验证合同（memory/proactive_contract.VerificationContract 的 JSON 投影；
    # 空 dict = 无合同）。合同只由服务端在 pick_target 后构造。
    verification_contract: dict = field(default_factory=dict)
    # 证据表投影（core/dialogue_attribution.SourceEvidence 的 JSON；guard 模式
    # 非.off 时由 prepare 侧构建，empty = 关闭或无证据）。
    attribution_evidence: dict = field(default_factory=dict)
    # guard 决策（AttributionDecision 的 JSON；finalize 侧写入）。
    attribution_decision: dict = field(default_factory=dict)
    # 最终回复处置：deliver=按 lines 交付 / fallback=交付受限兜底 /
    # suppressed=本轮不交付（guard 拒绝且无合格段）。split_lines 等后置钩子
    # 必须尊重 suppressed——不得用「......？」默认值顶替。
    reply_disposition: str = ""

    # ---- Capability Router / Comes（任务调度层） ----
    # Router 的判定结论（capability.router.types.Route）。类型写 Any 是刻意的：
    # core 是「与业务无关的编排骨架」，不该 import capability——反向依赖会成环。
    route: Any = None
    # Comes 产出的 Result 列表。**data 字段不进 prompt**，只用于日志与调试。
    task_results: list = field(default_factory=list)
    # 压缩后的工具结果摘要，是唯一会被拼进 Stella prompt 的部分
    # （工具结果同样不该污染聊天上下文，见 core/pipeline.py 的 _tool_result_section）。
    tool_summaries: list[str] = field(default_factory=list)
    # 知识库证据（knowledge.search 的检索结果）：结构化摘录 + 引用，与
    # tool_summaries / memories_for_prompt 三轨分离（见 docs/knowledge-base.md）。
    # dict 形态见 capability/providers/knowledge.py 的 _evidence_dict；
    # 由 capability.hooks 从 knowledge.search 的结果里分流写入，pipeline 在
    # prompt 组装时套用知识证据预算（KNOWLEDGE_EVIDENCE_*）后渲染成引用段。
    # **绝不**进入记忆整合：knowledge.isolation 保证它不是记忆候选来源。
    knowledge_evidence: list[dict] = field(default_factory=list)

    # ---- Skills（Anthropic 风格技能，skills/ 子系统） ----
    # 与 route/task_results 同一治理模式：core 只承载，不解释 skills 的类型
    # （反向 import 会成环）。四个字段全部默认空，旧调用方零改动。
    # 候选（skills.model.SkillCandidate 对象，metadata-only，无正文无路径），
    # 由 capability.hooks 的 skills 分支填充：
    skill_candidates: list = field(default_factory=list)
    # 本次调用的 SkillResult 对象（原始结果；进 prompt 的只有 skill_summaries）
    skill_results: list = field(default_factory=list)
    # 有界摘要（同 tool_summaries 地位，是唯一进 Stella prompt 的技能文本）
    skill_summaries: list[str] = field(default_factory=list)
    # 产物引用（skills.model.ArtifactRef），pipeline 渲染为 workspace 相对路径
    skill_artifacts: list = field(default_factory=list)

    # ---- 图片识别（视觉转述，见 design_docs/Stella_图片识别（视觉转述）实施计划 v1.0） ----
    # 接入层从 OneBot 事件提取的图片来源（URL / base64:// / data: / 本地路径）。
    image_sources: list[str] = field(default_factory=list)
    # describe_images 产出的每张图的客观描述（与 image_sources 同序、可短于它）。
    image_captions: list[str] = field(default_factory=list)

    # ---- 平台原始句柄（opaque） ----
    # Comes 调 AstrBot 工具时，工具 handler 内部会用 event.send() /
    # event.bot.call_action()，必须是真实对象，构造不出等价替身。core 不解释它们的
    # 类型、也不碰它们的任何方法，只负责从接入层传递到 Capability 层。
    # repr=False：OneBot 事件的 repr 会把整条消息与 sender 全展开，
    # 日志里 ChatContext 一旦被 repr 就会刷屏。
    raw_event: Any = field(default=None, repr=False)
    bot: Any = field(default=None, repr=False)

    # ---- 社交闭环身份（计划 §6.1） ----
    # trace_id：接入入口在硬门禁前创建，未进入 Facade 的静默决策也持有它；
    # turn_id：RuntimeFacade 分配并写入（跨进程桥两侧一致），未进入 Facade 的
    # 上下文为空串。两者都是安全标量，可进投影；raw_event/bot 仍然永不过桥。
    trace_id: str = ""
    turn_id: str = ""
    # 本轮 social 插槽的预算快照（选中/注入/裁剪明细，计划 §6.5）：
    # JSON 字符串，由 core.social.context_builder 写入，供追踪与审计。
    social_context_snapshot: str = ""

    # ---- Cometa 外部委派（design_docs/Cometa 外部 Agent 任务运行层实施方案 v1.0） ----
    # 类型刻意是 Any：core 是编排骨架，import cometa 会反向成环（与 route 同理）。
    # cometa_origin：可信入口（ai_gateway / chat_ingress）构造的 Origin dict；
    #   被动群聊/主动发言路径保持 None——委派只由用户显式请求触发（方案 §6.4.1）。
    # cometa_submission：委派受理成功后由 capability.delegation 写入的 dict
    #   （task_id / accepted_at / ack_notification_id / ack_text），供接入层
    #   认领 ack 通知（§6.5：入口与后台泵用同一 CAS，只有一个发送者）。
    # 两个字段**均不进** _PROJECTION_FIELDS：身份与授权信息不过跨进程桥。
    cometa_origin: Any = field(default=None, repr=False)
    cometa_submission: Any = field(default=None, repr=False)

    # ---- Cortico 迁移：跨进程 JSON 投影（计划 §6.2/§6.4） ----
    # 投影 schema 版本：字段集变更时 +1；旧 runtime store 按版本向后读取。
    # v2：新增 trace_id / turn_id（社交闭环身份贯通，计划 §6.1）。
    # v3：新增会话身份四字段（conversation_kind/key/peer/storage_session_id，
    # 计划 §6.1）。旧 v2 投影缺这些字段 → 按旧 QQ 群/WebChat 格式恢复
    # （group_id 即存储键），不猜测新格式缺失字段的会话种类。
    # v4：消息身份信封扁平字段（多人身份修复计划 §6.2）。旧 v3 输入缺这些
    # 字段 → 关系一律 unknown；任何来源不明的投影不得仅凭传入 uid 获得权限
    # ——权限主体仍由既有可信入口（scope_for_chat_context 等）确定。
    # v5：归属整改五字段（复核 F1）：retrieval_query / verification_contract /
    # attribution_evidence / attribution_decision / reply_disposition。旧 v4
    # 输入缺这些字段 → typed 查询为空（沿用旧推导）、合同/证据为空（guard
    # 按 feature-off 处理）、处置为空（按 deliver 兼容）——不放宽任何权限。
    PROJECTION_SCHEMA_VERSION = 5
    # 显式白名单（never blacklist）：raw_event/bot 是平台句柄，**永不过桥**；
    # route/task_results/skill_results 承载任意 Python 对象，桥只传可 JSON 的
    # 摘要字段（tool_summaries / knowledge_evidence / skill_summaries 等）。
    _PROJECTION_FIELDS = (
        # 输入标识
        "user_id", "group_id", "msg_id", "message", "source_kind",
        "group_shared_space", "trigger", "intent", "image_sources",
        "trace_id", "turn_id",
        # 会话身份（v3）
        "conversation_kind", "conversation_key", "bot_id", "peer_id", "storage_session_id",
        # 消息身份信封（v4）
        "sender_display_name", "reply_to_msg_id", "reply_target_user_id",
        "mentioned_user_ids", "logical_message_id", "part_index", "origin_msg_id",
        "reply_recipient_user_id", "recorded_row_id", "relation_version",
        "identity_revision", "identity_capsule",
        # pre/prepare 侧
        "short_term", "user_profile", "preferred_address", "memories_for_prompt",
        "memory_mode", "conversation_memories", "behavior_constraints", "tail_start_id",
        "tool_summaries", "knowledge_evidence", "skill_summaries", "skill_artifacts",
        "image_captions",
        # 归属整改（v5，复核 F1）
        "retrieval_query", "verification_contract", "attribution_evidence",
        "attribution_decision", "reply_disposition",
        # 诊断
        "llm_backend", "llm_model", "llm_call_count", "context_window_tokens",
        "prompt_budget_tokens", "prompt_estimated_tokens", "prompt_truncated",
        "system_prompt_len",
        # 输出
        "raw_output", "thought", "action", "reply", "lines",
        # 门禁与 Planner
        "gate_path", "gate_score", "gate_reasons",
        "planner_trigger", "planner_action", "planner_wait", "deep_tool_calls",
    )

    def to_json_projection(self) -> dict:
        """跨进程桥的 JSON 投影：白名单字段 + schema 版本。

        - ``raw_event``/``bot``/``route``/``task_results``/``skill_results``/
          ``memory_trace`` 不进投影（平台句柄与任意对象；桥以进程内短期
          handle 语义另行管理，重启失效——计划 §6.4）。
        - 语义字段名一律不改（group/shared_space/user/trigger 等照旧）。
        """
        out: dict = {
            "projection_schema_version": self.PROJECTION_SCHEMA_VERSION,
        }
        for name in self._PROJECTION_FIELDS:
            value = getattr(self, name)
            if name == "skill_artifacts":
                # ArtifactRef 是对象；只取桥需要的原始字段
                value = [
                    {"path": getattr(a, "path", ""), "size_bytes": getattr(a, "size_bytes", 0)}
                    for a in (value or [])
                ]
            elif name == "gate_reasons":
                # tuple → list：投影必须 JSON 安全
                value = list(value or [])
            elif name == "mentioned_user_ids":
                # tuple → list：投影必须 JSON 安全（v4 信封）
                value = list(value or [])
            out[name] = value
        return out

    def __post_init__(self) -> None:
        """自动解析共享空间归属，不要求调用方逐个传参。

        ``resolve_space`` 延迟导入：避免 core 在 import 阶段依赖 config 子模块
        （与 settings.py 对 nonebot logger 的延迟导入同理）。
        """
        if not self.group_shared_space and self.group_id:
            from config.spaces import resolve_space

            self.group_shared_space = resolve_space(self.group_id)
        # v4 信封字段的统一入口规范化（多人身份修复计划 §6.2）：无论哪个
        # 入口构造 ctx，展示昵称都不携带控制字符/提示标记，mentions 有界去重。
        if self.sender_display_name:
            self.sender_display_name = normalize_display_name(self.sender_display_name)
        if self.mentioned_user_ids:
            self.mentioned_user_ids = normalize_mentions(self.mentioned_user_ids)
