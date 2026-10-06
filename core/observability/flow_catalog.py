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
# 2026.10.04：私聊入口/固定节点补登记（修复计划 §6.5，R1）。
TOPOLOGY_VERSION = "2026.10.04"
CATALOG_SCHEMA_VERSION = 2

GENERATOR_VERSION = 3


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
    ("memory", "记忆整合与晋升"),
    ("proactive", "参与度与主动决策"),
    ("background", "后台派生"),
    ("cometa", "Cometa 任务"),
    ("ops", "后台运行与维护"),
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
    _N("ingress.private.receive", "收到私聊消息", "ingress", "entry",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_private_chat")),
    _N("flow.ingress", "流程观测 root 生命周期", "ingress", "hook",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_flow_ingress_root")),
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
    _N("chat.conversation_lock", "私聊会话锁", "gate", "lock",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_private_chat")),
    _N("chat.persist", "私聊消息落库", "gate", "persist",
       ("stella_project/plugins/bot_main/ai_gateway.py", "handle_private_chat")),
    _N("chat.runtime", "共享 runtime 轮次", "gate", "task",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),
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
    _N("turn.direct_silent", "直回/静默早退（无 finalize）", "prepare", "decision",
       ("core/runtime/facade.py", "RuntimeFacade.submit_turn")),

    # ── 固定语义节点（修复计划 §6.5，R1：已使用未登记的节点转正）──
    _N("command.reply", "命令回复检查点", "delivery", "derived", derived=True),
    _N("compact.commit", "压缩提交", "background", "persist",
       ("memory/session_compact.py", "compact_once")),
    _N("proactive.consolidate", "主动发言后整合", "proactive", "background",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_speak_for_group")),

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
    _N("post.attribution_guard", "归属守护", "finalize", "post",
       ("stella_project/plugins/bot_main/ai_gateway.py", "attribution_guard_hook")),
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

    # ── 记忆整合与晋升（计划 §6.3 表：独立 process，逐候选/逐记忆实例）──
    _N("memory.consolidate.entry", "整合入口（触发/预检/锁）", "memory", "entry",
       ("memory/consolidator.py", "MemoryConsolidator.consolidate_group")),
    _N("memory.consolidate.window", "消息窗口与检查点", "memory", "persist",
       ("memory/consolidator.py", "MemoryConsolidator._fetch_next_messages")),
    _N("memory.extract.stage1", "粗抽取（stage1 模型）", "memory", "task",
       ("memory/consolidator.py", "MemoryConsolidator._extract_candidates"), opaque=True),
    _N("memory.extract.gate2", "自我披露门控→精确抽取（stage2）", "memory", "gate",
       ("memory/consolidator.py", "MemoryConsolidator._has_self_disclosure")),
    _N("memory.candidate.write", "候选写入与归一化（Gate3）", "memory", "persist",
       ("memory/consolidator.py", "MemoryConsolidator._write_memory_candidates")),
    _N("memory.promotion.batch", "晋升批处理入口", "memory", "entry",
       ("memory/memory_manager.py", "MemoryManager.process_new_candidates")),
    _N("memory.promotion.backend", "后端解析（Python/Rust/auto 回退）", "memory", "state",
       ("memory/memory_manager.py", "MemoryManager.process_new_candidates")),
    _N("memory.promotion.gate", "晋升门槛判定（逐候选）", "memory", "gate",
       ("memory/memory_manager.py", "MemoryManager._decide_promotion")),
    _N("memory.promotion.conflict", "冲突扫描与处理", "memory", "state",
       ("memory/memory_manager.py", "MemoryManager._resolve_conflicts")),
    _N("memory.promotion.merge", "相似合并", "memory", "state",
       ("memory/memory_manager.py", "MemoryManager._merge_into_memory")),
    _N("memory.promotion.create", "新建长期记忆", "memory", "persist",
       ("memory/memory_manager.py", "MemoryManager._create_memory")),
    _N("memory.promotion.quota", "用户配额排序与归档", "memory", "gate",
       ("memory/memory_manager.py", "MemoryManager._enforce_user_quota")),
    _N("memory.promotion.commit", "事务提交确认", "memory", "state",
       ("memory/memory_manager.py", "MemoryManager._process_new_candidates_python")),
    _N("memory.maintenance.run", "记忆维护（压缩/去重/衰减）", "memory", "task",
       ("memory/compressor.py", "MemoryCompressor.run_weekly")),

    # ── 参与度与主动决策（计划 §6.4 表：全等级/前置 root/回执）──
    _N("participation.decision", "参与决策（全等级退出）", "proactive", "decision",
       ("memory/participation/__init__.py", "ParticipationManager.observe")),
    _N("participation.score_compute", "评分计算（embedding/keyword 回退）", "proactive", "task",
       ("memory/participation/__init__.py", "ParticipationManager._score_with_embedding")),
    _N("participation.mode", "决策 tracker（streak/backoff/strong hook）", "proactive", "decision",
       ("memory/participation/decision.py", "DecisionTracker.decide")),
    _N("proactive.timer.preflight", "定时主动预检（独立 root）", "proactive", "entry",
       ("stella_project/plugins/bot_main/ai_gateway.py", "proactive_speak_job")),
    _N("proactive.at.preflight", "主动@资格预检", "proactive", "gate",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_proactive_at_user")),
    _N("proactive.at.select", "验证候选选择与淘汰原因", "proactive", "decision",
       ("memory/proactive_target.py", "pick_target")),

    # ── 后台运行与维护（计划 §6.5：social/scheduling/knowledge 入口）──
    _N("social.worker.run_due", "社交 worker 到期租约处理", "ops", "entry",
       ("memory/social_worker.py", "run_due_jobs")),
    _N("ops.lifecycle", "生命周期钩子（启动/停止）", "ops", "entry",
       ("stella_project/plugins/bot_main/ai_gateway.py", "_start_scheduling")),
    _N("scheduled.runtime.tick", "预约调度 tick（租约/恢复/执行）", "ops", "entry",
       ("stella_project/plugins/bot_main/scheduling/runtime.py", "tick_once")),
    _N("scheduled.gate", "预约运行门控（静音/睡眠/冷却）", "ops", "gate",
       ("stella_project/plugins/bot_main/scheduling/runtime.py",
        "SchedulerRuntime._execute_locked")),
    _N("scheduled.agent", "预约 Agent 执行", "ops", "task",
       ("stella_project/plugins/bot_main/scheduling/runtime.py",
        "SchedulerRuntime._execute_agent")),
    _N("scheduled.deliver", "预约投递", "ops", "notify",
       ("stella_project/plugins/bot_main/scheduling/delivery.py",
        "DeliveryService.deliver")),
    _N("knowledge.ingest.entry", "知识导入入口", "ops", "entry",
       ("knowledge/ingest.py", "ingest_content")),
    _N("knowledge.parse", "知识解析", "ops", "task",
       ("knowledge/ingest.py", "_parse")),
    _N("knowledge.version", "版本构建与嵌入", "ops", "persist",
       ("knowledge/ingest.py", "_build_version")),
]}

# ---- 静态边（主链；条件边带 label，spawn/cause 是虚线）----
EDGES: list[EdgeSpec] = [
    # WebChat
    EdgeSpec("web.auth_input", "web.outer_deadline"),
    EdgeSpec("web.outer_deadline", "web.space_context"),
    EdgeSpec("web.space_context", "web.session_lock"),
    EdgeSpec("web.session_lock", "turn.identity"),
    EdgeSpec("web.output", "web.output", kind="cause", label="每段 BOT_SELF 落库"),
    # QQ 私聊入口（修复计划 §6.5 R1）
    EdgeSpec("ingress.private.receive", "chat.conversation_lock"),
    EdgeSpec("chat.conversation_lock", "chat.context"),
    EdgeSpec("chat.context", "chat.persist"),
    EdgeSpec("chat.persist", "chat.consolidate_trigger"),
    EdgeSpec("chat.persist", "turn.identity", kind="condition", label="无总结触发"),
    EdgeSpec("chat.daily_budget", "chat.runtime", kind="condition", label="私聊放行"),
    EdgeSpec("chat.runtime", "chat.runtime_result"),
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
    EdgeSpec("turn.prepare", "turn.direct_silent", kind="condition",
             label="DIRECT/SILENT"),
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
    EdgeSpec("post.parse", "post.attribution_guard"),
    EdgeSpec("post.attribution_guard", "post.badwords"),
    EdgeSpec("post.badwords", "post.split"),
    EdgeSpec("post.split", "post.thought"),
    EdgeSpec("post.thought", "post.done"),
    # 发送
    EdgeSpec("post.done", "send.prepare"),
    EdgeSpec("ingress.command.select", "command.reply", label="命令回复"),
    EdgeSpec("post.done", "command.reply", kind="condition", label="命令文本"),
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
    EdgeSpec("compact.generate", "compact.commit", label="推进压缩位置"),
    EdgeSpec("proactive.after", "proactive.consolidate", kind="spawn",
             label="发言后按需整合"),
    # Cometa
    EdgeSpec("delegation.submit", "cometa.accept", kind="cause"),
    EdgeSpec("delegation.submit", "delegation.ack"),
    EdgeSpec("cometa.accept", "cometa.claim", kind="cause"),
    EdgeSpec("cometa.claim", "cometa.preflight"),
    EdgeSpec("cometa.preflight", "cometa.launch"),
    EdgeSpec("cometa.launch", "cometa.stream"),
    EdgeSpec("cometa.stream", "cometa.notification", kind="cause", label="任务终态"),
    EdgeSpec("cometa.notification", "cometa.notification_result"),
    # 记忆整合与晋升（计划 §6.3：整合批次独立于晋升批，cause 相连）
    EdgeSpec("memory.consolidate.entry", "memory.consolidate.window"),
    EdgeSpec("memory.consolidate.window", "memory.extract.stage1", label="过阈值"),
    EdgeSpec("memory.extract.stage1", "memory.extract.gate2"),
    EdgeSpec("memory.extract.gate2", "memory.candidate.write", label="有候选"),
    EdgeSpec("memory.candidate.write", "memory.promotion.batch", kind="cause"),
    EdgeSpec("memory.promotion.batch", "memory.promotion.backend"),
    EdgeSpec("memory.promotion.backend", "memory.promotion.gate", label="逐候选"),
    EdgeSpec("memory.promotion.gate", "memory.promotion.conflict", kind="condition", label=" eligible"),
    EdgeSpec("memory.promotion.conflict", "memory.promotion.merge", kind="condition", label="相似命中"),
    EdgeSpec("memory.promotion.conflict", "memory.promotion.create", kind="condition", label="无冲突/新建"),
    EdgeSpec("memory.promotion.merge", "memory.promotion.quota"),
    EdgeSpec("memory.promotion.create", "memory.promotion.quota"),
    EdgeSpec("memory.promotion.quota", "memory.promotion.commit"),
    EdgeSpec("memory.promotion.commit", "memory.maintenance.run", kind="cause", label="晋升后压缩"),
    # 知识导入链（M5 孤岛收口）
    EdgeSpec("knowledge.ingest.entry", "knowledge.parse"),
    EdgeSpec("knowledge.parse", "knowledge.version"),
    # 预约调度链（M5 孤岛收口）
    EdgeSpec("scheduled.runtime.tick", "scheduled.gate"),
    EdgeSpec("scheduled.gate", "scheduled.agent", kind="condition", label="到期运行"),
    EdgeSpec("scheduled.agent", "scheduled.deliver"),
    # 社交 worker 到期处理驱动效果结算
    EdgeSpec("social.worker.run_due", "effect.resolve", kind="cause",
             label="到期结算作业"),
    # AstrBot 插件事件桥挂在能力并行之后
    EdgeSpec("capability.fanout", "astrbot.bridge", kind="order"),
    # 参与评分（background 活动面）挂在决策链之后
    EdgeSpec("participation.decision", "participation.score", kind="order",
             label="同一观察的活动面"),
    # 流程观测 root 生命周期先于消息入口（M5 孤岛收口）
    EdgeSpec("flow.ingress", "ingress.receive", label="群消息 root"),
    EdgeSpec("flow.ingress", "ingress.private.receive", label="私聊消息 root"),
    # 生命周期钩子（M5：真实启动/停止事实）
    EdgeSpec("ops.lifecycle", "scheduled.runtime.tick", kind="cause",
             label="启动调度器"),
    EdgeSpec("ops.lifecycle", "cometa.claim", kind="cause", label="启动 worker"),
    # 参与度与主动决策（计划 §6.4：timer/主动@/群插话三前置 root）
    EdgeSpec("participation.decision", "participation.score_compute", kind="order"),
    EdgeSpec("participation.score_compute", "participation.mode"),
    EdgeSpec("proactive.timer.preflight", "proactive.at.preflight", kind="condition", label="有验证候选"),
    EdgeSpec("proactive.timer.preflight", "proactive.preflight", label="参与度未启用"),
    EdgeSpec("proactive.at.preflight", "proactive.at.select"),
    EdgeSpec("proactive.at.select", "proactive.preflight", kind="condition", label="命中候选"),
]

# ---- 入口 root 种类（message_traces.root_kind 的合法值）----
ENTRY_ROOTS: dict[str, str] = {
    "qq_passive": "ingress.receive",       # 静默监听（每条群消息最早处理点）
    "qq_chat": "ingress.chat.rule",        # @ 对话（root 缺失时的兜底入口）
    "qq_command": "ingress.command.select",
    "qq_private": "ingress.private.receive",  # 私聊主链（修复计划 §6.5 R1）
    "webchat": "web.auth_input",
    "proactive": "proactive.preflight",    # 主动发言（独立 root）
    "consolidate": "consolidate.preflight",
    "compact": "compact.preflight",
    "cometa_task": "cometa.claim",
    "effect": "effect.resolve",
    # 计划 §6.3/§6.4：记忆与主动决策独立 process root
    "memory_consolidate": "memory.consolidate.entry",
    "memory_promotion": "memory.promotion.batch",
    "memory_maintenance": "memory.maintenance.run",
    "participation": "participation.decision",
    "proactive_timer": "proactive.timer.preflight",
    "proactive_at": "proactive.at.preflight",
    # 计划 §6.5：其余运行族入口（M4 探针接入）
    "social_worker": "social.worker.run_due",
    "scheduled_task": "scheduled.runtime.tick",
    "knowledge_ingest": "knowledge.ingest.entry",
    # 生命周期钩子（验收报告 M5：启动/停止真实运行事实）
    "lifecycle": "ops.lifecycle",
}

# ---- 显式埋点边（修复计划 §6.4）：这些 (src, dst) 已在真实控制边界发出
# transition 事实；其余边为 static_only（静态目录关系，运行未确认）----
EXPLICIT_EDGES: frozenset[tuple[str, str]] = frozenset({
    # 消息入口与被动记录链（修复计划 §6.4 第二批）
    ("ingress.receive", "ingress.passive.filter"),
    ("ingress.receive", "ingress.plugin"),
    ("ingress.receive", "ingress.chat.rule"),
    ("ingress.chat.rule", "chat.plugin_shortcut"),
    ("ingress.passive.filter", "ingress.passive.persist"),
    ("ingress.passive.persist", "ingress.passive.state"),
    ("ingress.passive.state", "ingress.passive.social"),
    ("ingress.passive.social", "ingress.passive.expression"),
    ("ingress.passive.expression", "ingress.passive.participation"),
    # 参与决策链
    ("participation.decision", "participation.score_compute"),
    ("participation.score_compute", "participation.mode"),
    # 对话/闸门/生成/发送/压缩（首批）
    ("chat.plugin_shortcut", "chat.group_lock"),
    ("chat.group_lock", "chat.context"),
    ("chat.daily_budget", "turn.identity"),
    ("turn.prepare", "turn.generate"),
    ("turn.generate", "turn.generated"),
    ("turn.generate", "turn.timeout"),
    ("turn.generate", "turn.cancel"),
    ("turn.generate", "turn.error"),
    ("send.prepare", "send.segment"),
    ("send.segment", "send.aggregate"),
    ("reply.bookkeeping", "reply.compact"),
    ("compact.spawn", "compact.preflight"),
})


# 运行时钩子名 → 语义节点（turn_service prepare/post hook 包装用）
HOOK_NODE_IDS: dict[str, str] = {
    "describe_images_hook": "hook.vision",
    "build_context": "context.session",
    "activate_capabilities": "capability.fanout",
}
POST_HOOK_NODE_IDS: dict[str, str] = {
    "parse_output": "post.parse",
    "attribution_guard_hook": "post.attribution_guard",
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
