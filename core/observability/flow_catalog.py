# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""消息流程语义目录（计划 §6.1/§6.3）：稳定节点身份的唯一登记处。

- **语义层**：这里登记的是计划 §6.3 验收清单里的语义节点（稳定
  ``node_id``、业务名、泳道、来源符号），不是运行事实——「有没有发生」
  只看 :mod:`core.observability.message_flow` 写出的真实事件。
- **手工维护边界**：只有业务标签 / 稳定身份 / 外部边界需要人标注（计划
  §6.1 第 8 点）；结构漂移由 ``scripts/generate_message_flow.py`` 对着
  源码 AST 生成 manifest 并在 CI 里做 ``--check`` 捕获。
- **ID 稳定性**：``node_id`` 是 UI、事件表与 manifest 的共同主键。重命名
  符号不改 ID；只有语义本身变化才允许增删 ID 并升 ``TOPOLOGY_VERSION``。
- ``source`` 给出该节点的核查锚点（文件, 符号），生成器据此计算 body
  hash 并展开源码细节子节点；无 source 的节点（如 post.done 这种由多
  事件推导的汇聚点）标记 ``derived``。
"""

from __future__ import annotations

from dataclasses import dataclass

# 语义拓扑版本：节点/边/条件的**语义**变化时手工递增（内容 hash 由生成器
# 另算，二者独立——见计划 §6.1 manifest 字段说明）。
TOPOLOGY_VERSION = "2026.10.02"
CATALOG_SCHEMA_VERSION = 1

GENERATOR_VERSION = 1


@dataclass(frozen=True)
class NodeSpec:
    """一个语义节点：ID、业务名、泳道、种类与来源锚点。"""

    id: str
    label: str
    lane: str
    kind: str  # entry|filter|persist|state|gate|lock|hook|planner|prompt|parallel|generate|post|delivery|bookkeeping|background|task|notify|aggregate|derived
    source: tuple[str, str] | None = None  # (file, qualified symbol)
    derived: bool = False  # 无单一源码锚点（由多个事件推导）
    opaque: bool = False  # 外部系统边界（SDK/平台/第三方），不展开内部


@dataclass(frozen=True)
class EdgeSpec:
    """一条静态边：``kind`` 决定渲染语义（order 实线 / spawn·cause·data 虚线）。"""

    src: str
    dst: str
    kind: str = "order"  # order|condition|spawn|cause|data
    label: str = ""


# ---- 泳道（subgraph）：渲染顺序即列表顺序 ----
LANES: list[tuple[str, str]] = [
    ("web", "WebChat 入口"),
    ("ingress", "收到消息与分流"),
    ("command", "控制命令"),
    ("gate", "闸门与预算"),
    ("prepare", "预处理与规划"),
    ("capability", "并行能力"),
    ("generate", "生成"),
    ("finalize", "后处理"),
    ("delivery", "发送与记账"),
    ("background", "后台派生"),
    ("cometa", "Cometa 任务"),
]

_N = NodeSpec

# ---- 节点登记（计划 §6.3 表 A–G 的语义行）----
NODES: dict[str, NodeSpec] = {n.id: n for n in [
    # ── WebChat（表 B）──
    _N("web.auth_input", "鉴权与输入检查", "web", "gate",
       ("webui/routers/chat.py", "chat")),
    _N("web.outer_deadline", "整轮外层超时", "web", "gate",
       ("webui/routers/chat.py", "chat")),
    _N("web.space_context", "虚拟空间与记录消息", "web", "persist",
       ("webui/chat_ingress.py", "run_turn")),
    _N("web.session_lock", "WebChat 串行锁", "web", "lock",
       ("webui/chat_ingress.py", "run_turn")),
    _N("web.output", "回复落库与 server_emitted", "web", "delivery",
       ("webui/chat_ingress.py", "run_turn")),

    # ── 收到消息与分流（表 A）──
    _N("ingress.receive", "收到群消息", "ingress", "entry",
       ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat")),
    _N("ingress.passive.filter", "群过滤/自我/slash/空文本", "ingress", "filter",
       ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat")),
    _N("ingress.passive.persist", "消息落库", "ingress", "persist",
       ("memory/pre_processors.py", "record_message")),
    _N("ingress.passive.state", "主动状态观察", "ingress", "state",
       ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat")),
    _N("ingress.passive.social", "社交证据标准化", "ingress", "state",
       ("stella_project/plugins/bot_main/ai_gateway.py", "record_group_chat")),
    _N("ingress.passive.expression", "被动表达观察", "ingress", "state",
       ("memory/expression_learning.py", "note_passive_message")),
    _N("ingress.passive.participation", "参与评分", "ingress", "decision",
       ("memory/participation/__init__.py", "ParticipationManager.observe")),
    _N("ingress.chat.rule", "聊天触发判定", "ingress", "filter",
       ("stella_project/plugins/bot_main/ai_gateway.py", "is_chat_trigger")),
    _N("ingress.plugin", "插件分发", "ingress", "task",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_plugin")),
    _N("ingress.command.select", "命令候选选择", "ingress", "decision",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat"), derived=True),

    # ── 控制命令（表 A command.*；每类一个终态节点，分支在源码层展开）──
    _N("command.addressing", "个性化称呼命令", "command", "task",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_addressing")),
    _N("command.toggle", "开关命令", "command", "task",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_toggle")),
    _N("command.capabilities", "能力查询命令", "command", "task",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_capability_query")),
    _N("command.reload", "重载命令", "command", "task",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_reload")),
    _N("command.scheduling", "定时任务命令", "command", "task",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_scheduling")),

    # ── 闸门与预算（表 A chat.*）──
    _N("chat.plugin_shortcut", "插件已接管短路", "gate", "filter",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("chat.group_lock", "群锁排队", "gate", "lock",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("chat.context", "话题版本与 Cometa Origin", "gate", "state",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("chat.reply_gate", "回复闸门评估", "gate", "gate",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("chat.consolidate_trigger", "按需整合触发", "gate", "decision",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("chat.daily_budget", "日预算阻断", "gate", "gate",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("chat.runtime_result", "运行时结果分派", "gate", "decision",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),

    # ── 预处理与规划（表 B turn.* / 表 D prepare/planner/prompt）──
    _N("turn.identity", "轮次身份", "prepare", "state",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("turn.prepare", "prepare 阶段", "prepare", "aggregate",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("prepare.hooks", "前置钩子链", "prepare", "hook",
       ("core/runtime/turn_service.py", "TurnService.prepare_turn")),
    _N("hook.vision", "图片转述钩子", "prepare", "hook",
       ("stella_project/plugins/bot_main/ai_gateway.py", "describe_images_hook")),
    _N("context.session", "短期上下文组装", "prepare", "hook",
       ("memory/pre_processors.py", "build_context")),
    _N("planner.preflight", "Planner 触发判定", "prepare", "planner",
       ("core/planner.py", "RestrictedPlanner.maybe_plan")),
    _N("planner.ask", "Planner LLM 决策", "prepare", "planner",
       ("core/planner.py", "RestrictedPlanner._ask")),
    _N("planner.parse", "Planner 结果解析", "prepare", "planner",
       ("core/planner.py", "RestrictedPlanner.maybe_plan")),
    _N("prepare.direct", "直回短路 (DIRECT)", "prepare", "decision",
       ("core/runtime/turn_service.py", "TurnService.prepare_turn")),
    _N("prepare.silent", "等待更多消息 (SILENT)", "prepare", "decision",
       ("core/runtime/turn_service.py", "TurnService.prepare_turn")),
    _N("prepare.backend_budget", "无后端/调用预算", "prepare", "decision",
       ("core/runtime/turn_service.py", "TurnService.prepare_turn")),
    _N("prompt.memory", "记忆分区注入", "prepare", "prompt",
       ("core/runtime/turn_service.py", "TurnService.prepare_turn")),
    _N("prompt.parts", "提示词分段组装", "prepare", "prompt",
       ("core/runtime/turn_service.py", "_compose_prompt")),
    _N("prompt.fit", "窗口预算裁剪", "prepare", "prompt",
       ("core/context_budget.py", "fit_prompt_to_window")),
    _N("turn.generate", "生成调用（wait_for 围 provider）", "prepare", "generate",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("turn.timeout", "生成超时兜底", "prepare", "decision",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("turn.cancel", "轮次取消", "prepare", "decision",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("turn.error", "Provider 异常兜底", "prepare", "decision",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("turn.generated", "生成完成", "prepare", "decision",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
    _N("turn.fallback", "本地兜底 (budget/no_backend)", "prepare", "decision",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),

    # ── 并行能力（表 C）──
    _N("capability.route", "Router 路由判定", "capability", "decision",
       ("capability/hooks.py", "activate_capabilities")),
    _N("capability.cometa", "Cometa 委派判定", "capability", "decision",
       ("capability/delegation.py", "handle_delegation_turn")),
    _N("capability.fanout", "Memory/Comes/Skills 并行", "capability", "parallel",
       ("capability/hooks.py", "activate_capabilities")),
    _N("capability.isolation", "分支异常隔离", "capability", "aggregate",
       ("capability/hooks.py", "activate_capabilities")),
    _N("memory.retrieve", "记忆检索", "capability", "task",
       ("memory/retrieval_v2.py", "retrieve_memories"), opaque=True),
    _N("comes.task_build", "工具任务构建", "capability", "task",
       ("capability/hooks.py", "_run_comes")),
    _N("comes.execute_all", "工具执行", "capability", "task",
       ("capability/comes/__init__.py", "execute_all"), opaque=True),
    _N("comes.dispatch", "工具结果分发", "capability", "task",
       ("capability/hooks.py", "_run_comes")),
    _N("skills.preflight", "技能预检", "capability", "task",
       ("capability/hooks.py", "_run_skills")),
    _N("skills.invoke", "技能执行", "capability", "task",
       ("capability/hooks.py", "_run_skills"), opaque=True),
    _N("astrbot.bridge", "插件事件桥", "capability", "task",
       ("capability/hooks.py", "_build_astr_event")),

    # ── 生成（表 D llm.*）──
    _N("llm.provider", "Provider 直连生成", "generate", "generate",
       ("core/runtime/facade.py", "_pipeline_provider")),
    _N("llm.request", "HTTP 请求", "generate", "generate",
       ("core/llm/lm_studio.py", "OpenAICompatibleBackend.generate_detailed"), opaque=True),
    _N("llm.response", "响应解析", "generate", "aggregate",
       ("core/llm/lm_studio.py", "OpenAICompatibleBackend.generate_detailed"), opaque=True),
    _N("llm.retry", "重试与退避", "generate", "decision",
       ("core/llm/lm_studio.py", "OpenAICompatibleBackend.generate_detailed"), opaque=True),

    # ── 后处理（表 D finalize/post）──
    _N("finalize.trace", "记忆决策轨迹", "finalize", "bookkeeping",
       ("core/runtime/turn_service.py", "TurnService.finalize_turn")),
    _N("post.parse", "输出解析", "finalize", "post",
       ("memory/post_processors.py", "parse_output")),
    _N("post.badwords", "违禁语过滤", "finalize", "post",
       ("memory/post_processors.py", "bad_phrase_filter")),
    _N("post.split", "分行", "finalize", "post",
       ("memory/post_processors.py", "split_lines")),
    _N("post.thought", "思维链日志", "finalize", "post",
       ("memory/post_processors.py", "log_thought")),
    _N("post.done", "后处理完成（可发送）", "finalize", "derived", derived=True),

    # ── 发送与记账（表 E）──
    _N("send.prepare", "发送准备", "delivery", "delivery",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("send.cometa_ack", "Cometa 受理确认", "delivery", "delivery",
       ("stella_project/plugins/bot_main/cometa_bridge.py", "deliver_ack")),
    _N("send.segment", "逐段发送", "delivery", "delivery",
       ("core/social/delivery.py", "deliver_lines")),
    _N("send.receipt", "回执落库", "delivery", "persist",
       ("core/social/delivery.py", "_append_and_persist")),
    _N("send.aggregate", "回执聚合", "delivery", "aggregate",
       ("core/social/delivery.py", "_trace_delivery")),
    _N("reply.bookkeeping", "确认段记账与学习", "delivery", "bookkeeping",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("reply.no_delivery", "全部未送达（不记账）", "delivery", "decision",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_chat")),
    _N("reply.compact", "回复后压缩派生", "delivery", "background",
       ("memory/session_compact.py", "schedule_compact")),
    _N("learning.open", "表达学习开启", "delivery", "background",
       ("memory/expression_learning.py", "on_reply_sent")),
    _N("effect.observe", "效果窗口观察", "delivery", "background",
       ("memory/reply_effect_service.py", "open_effect")),
    _N("effect.resolve", "效果结算", "delivery", "background",
       ("memory/reply_effect_service.py", "resolve_effect")),

    # ── 后台派生（表 F）──
    _N("participation.score", "参与评分决策", "background", "decision",
       ("memory/participation/__init__.py", "ParticipationManager.observe")),
    _N("participation.spawn", "主动发言派生", "background", "background",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_spawn_participation_speak")),
    _N("proactive.preflight", "主动发言预检", "background", "gate",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group")),
    _N("proactive.turn", "主动发言轮次", "background", "generate",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group")),
    _N("proactive.filter", "主动输出过滤", "background", "filter",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group")),
    _N("proactive.send", "主动逐段发送", "background", "delivery",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group")),
    _N("proactive.after", "主动发言记账", "background", "bookkeeping",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group")),
    _N("consolidate.spawn", "整合派生", "background", "background",
       ("memory/consolidator.py", "maybe_consolidate")),
    _N("consolidate.preflight", "整合预检", "background", "gate",
       ("memory/consolidator.py", "MemoryConsolidator.consolidate_group")),
    _N("consolidate.extract", "整合提取", "background", "task",
       ("memory/consolidator.py", "MemoryConsolidator.consolidate_group"), opaque=True),
    _N("consolidate.write", "整合写入", "background", "persist",
       ("memory/consolidator.py", "MemoryConsolidator.consolidate_group")),
    _N("compact.spawn", "压缩派生", "background", "background",
       ("memory/session_compact.py", "schedule_compact")),
    _N("compact.preflight", "压缩预检", "background", "gate",
       ("memory/session_compact.py", "compact_once")),
    _N("compact.generate", "压缩生成", "background", "task",
       ("memory/session_compact.py", "compact_once"), opaque=True),

    # ── Cometa 任务（表 G）──
    _N("delegation.submit", "任务受理", "cometa", "task",
       ("capability/delegation.py", "_submit_delegate")),
    _N("delegation.ack", "受理确认回复", "cometa", "delivery",
       ("capability/delegation.py", "_set_ack")),
    _N("cometa.accept", "任务入库与去重", "cometa", "persist",
       ("cometa/service.py", "CometaService.submit")),
    _N("cometa.claim", "worker 认领", "cometa", "task",
       ("cometa/worker.py", "CometaWorker._tick")),
    _N("cometa.preflight", "执行预检", "cometa", "gate",
       ("cometa/executor.py", "AttemptExecutor.run_attempt")),
    _N("cometa.launch", "会话启动", "cometa", "task",
       ("cometa/executor.py", "AttemptExecutor.run_attempt"), opaque=True),
    _N("cometa.stream", "Agent 流消费", "cometa", "task",
       ("cometa/executor.py", "AttemptExecutor.run_attempt"), opaque=True),
    _N("cometa.notification", "结果通知发送", "cometa", "notify",
       ("cometa/delivery.py", "deliver_one")),
    _N("cometa.notification_result", "通知投递终态", "cometa", "decision",
       ("cometa/delivery.py", "NotificationPump.pump_once")),
]}

# ---- 静态边（主链；条件边带 label，spawn/cause 是虚线）----
EDGES: list[EdgeSpec] = [
    # WebChat
    EdgeSpec("web.auth_input", "web.outer_deadline"),
    EdgeSpec("web.outer_deadline", "web.space_context"),
    EdgeSpec("web.space_context", "web.session_lock"),
    EdgeSpec("web.session_lock", "turn.identity"),
    EdgeSpec("web.output", "web.output", kind="cause", label="每段 BOT_SELF 落库"),
    # QQ 入口
    EdgeSpec("ingress.receive", "ingress.passive.filter"),
    EdgeSpec("ingress.passive.filter", "ingress.passive.persist", label="通过过滤"),
    EdgeSpec("ingress.passive.persist", "ingress.passive.state"),
    EdgeSpec("ingress.passive.state", "ingress.passive.social"),
    EdgeSpec("ingress.passive.social", "ingress.passive.expression"),
    EdgeSpec("ingress.passive.expression", "ingress.passive.participation"),
    EdgeSpec("ingress.receive", "ingress.chat.rule", label="@ 命中"),
    EdgeSpec("ingress.receive", "ingress.plugin", label="插件规则命中"),
    EdgeSpec("ingress.receive", "ingress.command.select", label="命令候选"),
    EdgeSpec("ingress.command.select", "command.addressing", kind="condition"),
    EdgeSpec("ingress.command.select", "command.toggle", kind="condition"),
    EdgeSpec("ingress.command.select", "command.capabilities", kind="condition"),
    EdgeSpec("ingress.command.select", "command.reload", kind="condition"),
    EdgeSpec("ingress.command.select", "command.scheduling", kind="condition"),
    # 闸门链
    EdgeSpec("ingress.chat.rule", "chat.plugin_shortcut"),
    EdgeSpec("chat.plugin_shortcut", "chat.group_lock", label="未接管"),
    EdgeSpec("chat.group_lock", "chat.context"),
    EdgeSpec("chat.context", "chat.reply_gate"),
    EdgeSpec("chat.reply_gate", "chat.consolidate_trigger"),
    EdgeSpec("chat.consolidate_trigger", "chat.daily_budget"),
    EdgeSpec("chat.daily_budget", "turn.identity", label="放行"),
    EdgeSpec("chat.daily_budget", "chat.runtime_result", kind="condition", label="blocked"),
    # prepare 链
    EdgeSpec("turn.identity", "turn.prepare"),
    EdgeSpec("turn.prepare", "prepare.hooks"),
    EdgeSpec("prepare.hooks", "hook.vision", kind="order"),
    EdgeSpec("prepare.hooks", "context.session", kind="order"),
    EdgeSpec("prepare.hooks", "capability.route", kind="order"),
    EdgeSpec("prepare.hooks", "prepare.direct", kind="condition", label="钩子已回复"),
    EdgeSpec("prepare.hooks", "planner.preflight"),
    EdgeSpec("planner.preflight", "planner.ask", kind="condition", label="触发深度路径"),
    EdgeSpec("planner.ask", "planner.parse"),
    EdgeSpec("planner.parse", "prepare.silent", kind="condition", label="WAIT"),
    EdgeSpec("prepare.hooks", "prepare.backend_budget", kind="condition", label="no_backend/预算尽"),
    EdgeSpec("planner.preflight", "prompt.memory", label="REPLY/未触发"),
    EdgeSpec("prompt.memory", "prompt.parts"),
    EdgeSpec("prompt.parts", "prompt.fit"),
    EdgeSpec("prompt.fit", "turn.generate"),
    EdgeSpec("turn.generate", "turn.timeout", kind="condition", label="timeout"),
    EdgeSpec("turn.generate", "turn.cancel", kind="condition", label="cancel"),
    EdgeSpec("turn.generate", "turn.error", kind="condition", label="provider error"),
    EdgeSpec("turn.generate", "turn.generated", label="完成"),
    # 能力并行
    EdgeSpec("capability.route", "capability.cometa", kind="condition", label="Cometa 启用"),
    EdgeSpec("capability.cometa", "delegation.submit", kind="condition", label="受理"),
    EdgeSpec("capability.route", "capability.fanout"),
    EdgeSpec("capability.fanout", "memory.retrieve", kind="order"),
    EdgeSpec("capability.fanout", "comes.task_build", kind="order"),
    EdgeSpec("capability.fanout", "skills.preflight", kind="order"),
    EdgeSpec("comes.task_build", "comes.execute_all"),
    EdgeSpec("comes.execute_all", "comes.dispatch"),
    EdgeSpec("skills.preflight", "skills.invoke", kind="condition"),
    EdgeSpec("capability.fanout", "capability.isolation"),
    EdgeSpec("capability.isolation", "prompt.memory"),
    # 生成
    EdgeSpec("turn.generate", "llm.provider"),
    EdgeSpec("llm.provider", "llm.request"),
    EdgeSpec("llm.request", "llm.response"),
    EdgeSpec("llm.response", "llm.retry", kind="condition", label="可重试失败"),
    EdgeSpec("llm.retry", "llm.request", label="退避重试"),
    EdgeSpec("llm.response", "turn.generated"),
    # finalize
    EdgeSpec("turn.generated", "finalize.trace"),
    EdgeSpec("turn.fallback", "finalize.trace"),
    EdgeSpec("turn.timeout", "finalize.trace"),
    EdgeSpec("turn.error", "finalize.trace"),
    EdgeSpec("finalize.trace", "post.parse"),
    EdgeSpec("post.parse", "post.badwords"),
    EdgeSpec("post.badwords", "post.split"),
    EdgeSpec("post.split", "post.thought"),
    EdgeSpec("post.thought", "post.done"),
    # 发送
    EdgeSpec("post.done", "send.prepare"),
    EdgeSpec("send.prepare", "send.cometa_ack", kind="condition", label="委派受理"),
    EdgeSpec("send.prepare", "send.segment", label="普通回复"),
    EdgeSpec("send.segment", "send.receipt", kind="order"),
    EdgeSpec("send.segment", "send.aggregate"),
    EdgeSpec("send.aggregate", "reply.bookkeeping", kind="condition", label="有送达"),
    EdgeSpec("send.aggregate", "reply.no_delivery", kind="condition", label="全部未送达"),
    EdgeSpec("reply.bookkeeping", "reply.compact", kind="spawn"),
    EdgeSpec("reply.bookkeeping", "learning.open", kind="spawn"),
    EdgeSpec("learning.open", "effect.observe", kind="cause"),
    EdgeSpec("effect.observe", "effect.resolve", kind="cause"),
    # 后台派生
    EdgeSpec("chat.consolidate_trigger", "consolidate.spawn", kind="spawn"),
    EdgeSpec("ingress.passive.participation", "participation.spawn", kind="spawn", label="ALLOW"),
    EdgeSpec("participation.spawn", "proactive.preflight", kind="cause"),
    EdgeSpec("proactive.preflight", "proactive.turn"),
    EdgeSpec("proactive.turn", "proactive.filter"),
    EdgeSpec("proactive.filter", "proactive.send"),
    EdgeSpec("proactive.send", "proactive.after"),
    EdgeSpec("consolidate.spawn", "consolidate.preflight", kind="cause"),
    EdgeSpec("consolidate.preflight", "consolidate.extract", kind="condition", label="过阈值"),
    EdgeSpec("consolidate.extract", "consolidate.write"),
    EdgeSpec("reply.compact", "compact.spawn", kind="spawn"),
    EdgeSpec("compact.spawn", "compact.preflight", kind="cause"),
    EdgeSpec("compact.preflight", "compact.generate", kind="condition"),
    # Cometa
    EdgeSpec("delegation.submit", "cometa.accept", kind="cause"),
    EdgeSpec("delegation.submit", "delegation.ack"),
    EdgeSpec("cometa.accept", "cometa.claim", kind="cause"),
    EdgeSpec("cometa.claim", "cometa.preflight"),
    EdgeSpec("cometa.preflight", "cometa.launch"),
    EdgeSpec("cometa.launch", "cometa.stream"),
    EdgeSpec("cometa.stream", "cometa.notification", kind="cause", label="任务终态"),
    EdgeSpec("cometa.notification", "cometa.notification_result"),
]

# ---- 入口 root 种类（message_traces.root_kind 的合法值）----
ENTRY_ROOTS: dict[str, str] = {
    "qq_passive": "ingress.receive",       # 静默监听（每条群消息最早处理点）
    "qq_chat": "ingress.chat.rule",        # @ 对话（root 缺失时的兜底入口）
    "qq_command": "ingress.command.select",
    "webchat": "web.auth_input",
    "proactive": "proactive.preflight",    # 主动发言（独立 root）
    "consolidate": "consolidate.preflight",
    "compact": "compact.preflight",
    "cometa_task": "cometa.claim",
    "effect": "effect.resolve",
}

# 运行时钩子名 → 语义节点（turn_service prepare/post hook 包装用）
HOOK_NODE_IDS: dict[str, str] = {
    "describe_images_hook": "hook.vision",
    "build_context": "context.session",
    "activate_capabilities": "capability.fanout",
}
POST_HOOK_NODE_IDS: dict[str, str] = {
    "parse_output": "post.parse",
    "bad_phrase_filter": "post.badwords",
    "split_lines": "post.split",
    "log_thought": "post.thought",
}


def validate() -> list[str]:
    """目录自检：边引用存在、lane/kind 合法、入口 root 有节点。供合同测试调用。"""
    problems: list[str] = []
    lanes = {lid for lid, _ in LANES}
    for nid, node in NODES.items():
        if node.lane not in lanes:
            problems.append(f"node {nid}: unknown lane {node.lane}")
    for edge in EDGES:
        if edge.src not in NODES:
            problems.append(f"edge {edge.src}->{edge.dst}: missing src node")
        if edge.dst not in NODES:
            problems.append(f"edge {edge.dst}: missing dst node")
    for root_kind, nid in ENTRY_ROOTS.items():
        if nid not in NODES:
            problems.append(f"entry root {root_kind}: missing node {nid}")
    seen = {(e.src, e.dst, e.kind) for e in EDGES}
    if len(seen) != len(EDGES):
        problems.append("duplicate edges")
    return problems


def node_label(node_id: str) -> str:
    """UI 兜底标签：目录里没有的动态 ID（如 hook.custom:*）原样可读。"""
    node = NODES.get(node_id)
    if node is not None:
        return node.label
    if node_id.startswith("hook.custom:"):
        return f"扩展钩子 {node_id.split(':', 1)[1]}"
    return node_id
