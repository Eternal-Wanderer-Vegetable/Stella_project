# Stella Dashboard 消息工作流完整性修复计划

日期：2026-10-04；深度：deep；形式：full；类别：共享 API/数据迁移 + 并发与事务。**交付状态：仅计划，尚未实施。**

证据基线：分支 `feat/multi-user-identity-repair`；HEAD `6d73b9f70bd3797cb97af88a999bc59d9582cdcf`。承接 `docs/reports/2026-10-04-dashboard-message-flow-completeness-review.md` 的 R1–R9。本轮没有修改业务代码、测试、配置或生成 manifest，也没有提交。

图分析：Docker `stella-gitnexus`，挂载 `/repo`，别名 `Stella_project`；GitNexus 1.6.11 / Node 22.23.2；本轮严格刷新 `analyze --index-only --pdg` 成功，99.1 秒，索引时间 `2026-10-04T05:07:53.075Z`，85,007 节点、205,534 关系、914 社区、845 抽样流程。分析器 artifact/build/dependency 摘要分别为 `c7d271007a9858c4a966a249474aa193a055ec35a7126dc91eea5c806f414f19` / `9faaea7491d7a9f1955c300305fb7a21a14f44196981c249bf1c9a905083c4bc` / `24135c34df802e81623989801a7b4efd3502c5f296389c328ba309f7c370f158`。第 11 节保留官方 helper 生成的 schema-2 工作树证据，不把未跟踪文件当作已提交源码。

标注约定：`[verified]` 为当前源码或同 HEAD 隔离探针确认；`[graph]` 为图返回；`[inferred]` 为由证据提出的修复设计；`[assumed]` 为执行前需要检查的前提。除明确说明的现状外，所有“应/新增/改为”均属于拟实施合同。

## 1. Objective

[inferred] 完整展示所有已发生的消息事实、真实分支、派生处理与消息 IO；同时让用户看清静态目录、未观测部分、数据丢失和尚未加载的数据。修复 R1–R9，复用现有 RuntimeFacade、SQLite 业务库、观测 writer、FlowStore 和 Vue 页面，不建立第二套聊天/记忆引擎。

| 发现 | 目标行为 | 工作包 |
| --- | --- | --- |
| R1 私聊/固定节点/标签缺失 | 规范身份贯通，私聊输入及确认发送片段可查，入口与固定节点全部登记 | M1、M2、M4、M5 |
| R2 root 键碰撞 | Bot/会话类型/peer/消息 ID 联合隔离；同一事件共享同一 root | M1 |
| R3 推断实际连线 | 只有明确 transition 事实才能激活边；旧轨迹不虚构路径 | M3 |
| R4 源码闭包与入口门禁不足 | 本地跨文件闭包、辅助函数变化、真实入口新增均可检测；未闭合边界可见 | M4 |
| R5 spec 归档/绑定不足 | 新 root 精确绑定不可变 digest；同版本不同 spec 可共存；旧轨迹明确降级 | M1 |
| R6 实时 IO 过期 | 片段确认/结束/手动刷新更新 IO、detail、关系、对象事实；请求代际隔离 | M5 |
| R7 内部孤岛/背景关系不可导航 | 真实内部入口有运行事实；相关轨迹和对象历史可导航且有因果证据 | M4、M5 |
| R8 浏览器截断被误解为完整 | 分页、稳定水位、加载状态、无 spec 回退与全文展开均可用 | M5 |
| R9 checkpoint 被当作完成 | 检查点只更新事实；只有同一次 span 的 terminal event 才结束运行状态 | M3 |

## 2. Current Behaviour

[verified] 当前路径为 QQ preprocessor 创建 root → 群/私聊 matcher → 会话锁、持久化、共享 runtime → `deliver_lines` → `_record_bot_lines` → postprocessor 结束；WebChat 经自己的入口进入共享 runtime。观测通过有界队列异步落库，API 只读查 detail/events/spec/IO，浏览器按静态 manifest 加运行事件绘图。定位：`ai_gateway.py:232,388,1267,2643`、`message_flow.py:888,1016`、`webui/services/flow.py:369`、`dashboard/src/stores/flow.ts:35`。

[verified] 原始复核在同一 HEAD 下确认：manifest 有 130 个语义节点、124 条静态边、14 条泳道；129 个解析锚点对应 81 个不同源码位置，6,725 个结构位点含复用锚点，1,808 个未解析调用，4 个同文件可达闭包被截断。声明入口 20、root 接入 16，不能据此宣称覆盖率 80%。`internal_flow_catalog.py` 的手工清单校验不能发现清单外的新入口。

[verified] 隔离探针已经重现：不同 Bot/peer 的私聊消息 7 都返回 `(0,7)`；私聊业务历史存在但 IO 返回 `input=null`；两个无 transition 的兄弟 span 可被判为经过 A→B；辅助 `_flow_key` 的非锚点实现变化未改变 manifest hash；同 topology version 的不同 spec 只留第一份且 root digest 为空；checkpoint 提前投影为成功。真实 QQ 并发串线尚未现场触发，不能将条件性后果写成线上事故。

[verified] 前轮现有基线：观测 + API 104 tests、私聊入口 11 tests、Dashboard 6 files/60 tests 全部通过，typecheck 和 manifest `--check` 通过。它们验证已有合同，没有覆盖新增验收；本轮未重复跑这些测试，也未 build/sync/真实 adapter 验收。

## 3. Relevant Architecture

| 层 | 现有扩展位置与证据 | 本计划约束 |
| --- | --- | --- |
| 会话身份 | `core/conversation.py:42,63`；注册表 `memory/conversation_registry.py:95,199` | 复用 ConversationRef；私聊真实存储 ID 为注册表负整数，不由 scope 或 peer 推算 |
| root/span/event | `core/observability/message_flow.py:786,888,1016` | 新参数提供默认值，保留旧 kind；诊断失败不得改变业务回复、重发或持有会话锁等待 flush |
| writer | `message_flow.py:366,483,551,702,715` | root/spec 必须是有归属的同一提交单元，批事务失败后的 per-trace 重试仍保留依赖 |
| 业务回执 | `core/social/contracts.py:135`、`delivery.py:223`、`memory/social_store.py:62` | 完整正文留在已有业务回执表，事件只存脱敏摘要/引用；中立回执不授权群学习 |
| 组件迁移 | `memory/social_schema.py:529` 与 `memory/schema.py:64` | social 组件独立 v1→v2；保持主记忆 schema v16；仅在实际改动主记忆合同后才另立 Python/Rust 迁移 |
| 目录/闭包 | `flow_catalog.py:508`、`internal_flow_catalog.py`、`generate_message_flow.py:182,292,354,485` | 静态源码关系和 runtime transition 分开；生成器标准库可跑，沿用确定性 AST 归一化 |
| API/页面 | `webui/routers/trace.py:85`、`webui/services/flow.py:283,369`；FlowStore/reducer/layout/FlowPage | 保留旧 API；新字段 optional；原始事实可浏览，即使没有精确 spec |

## 4. GitNexus Findings

[graph] 五个 primary symbols 均做了 upstream/maxDepth=3/includeTests=true/limit=300 分析。`_flow_key`：CRITICAL，12 个受影响符号，d1/d2/d3=4/5/3，5 个流程；`begin_trace`：CRITICAL，161，71/59/31，11 个流程；`_emit_event`：CRITICAL，207，6/87/114，15 个流程；`edgeTraversed`：LOW，10，1/2/7；`build_manifest`：LOW，6，3/1/2。以保存的完整 impact 结果为准，第 9 节列出全部 d1 依赖。

[graph] 入口 query 实际找到了 `handle_private_chat → send` 和 `→ _get_message_table`；`get_or_register_private` context 找到 gateway 私聊注册调用；`record_delivery` context 指向 `_append_and_persist`、WebChat 和测试；`deliver_lines` 的实际 gateway 调用包含群聊、私聊、主动群聊和主动 @。所以私聊 IO 修复必须覆盖真实共享入口，而不能依据旧记忆说私聊入口不存在。

[verified] 本轮 LocalBackend 使用官方已安装 `callTool` 及 resource reader 访问图；不是自行生成 grep 调用图。`resolve_private` 无此符号，改用源码存在的 `get_or_register_private`；`conversation_key` 因同名 property 有歧义，工厂合同以 `core/conversation.py:42` 的定点源码为准。

[graph] 排名丢弃 2,439/2,639 候选入口，24 条深度截断；675 个候选 callee 被排名丢弃，46 次 walk 被切断。大于 512KB 的 manifest 未被索引，已直接核验 JSON。因此“无流程/无调用者/UNKNOWN”不能解释为未使用。五次 primary impact 未报告 partial/truncated 标记，但并不消除动态注册和跨语言盲点。

## 5. Statement-Level PDG Findings

[graph] 有界 PDG：`begin_trace controls` 7 条；`_flow_ingress_root controls` 23 条；`_flow_key flows` 1 条。只保留与设计相关的 statement slice；PDG 是函数内控制/数据依赖，不能证明跨线程落库顺序。

| slice | 真实控制/数据关系 | 设计约束 |
| --- | --- | --- |
| `_flow_key` 232→234 | 参数 `event` 到返回表达式 `(getattr(group_id,0) or 0,message_id)` | 加完整事件身份，四个所有者操作必须同时改键；只改 scope 无效 |
| `_flow_ingress_root` 394、400→401/402 | 类型过滤、键存在则 return，否则创建并缓存 root | 保留非 QQ 消息过滤、同事件幂等；新的完整键进入所有 get/pop 分支 |
| `_flow_ingress_root` 411→412 | 缓存超过 256 时淘汰旧项 | 淘汰要显式结束/标 unknown 或记录丢失，不能使活跃 root 静默失踪；不得借缓存扩容掩盖碰撞 |
| `begin_trace` 914、916→917/918 | trace_id 对应活跃 root 时 return found，否则进入创建块 | 旧调用保持幂等；身份/spec 不匹配时告警并降级，不重绑已存在 root |
| `begin_trace` 918 创建块 | PDG 将构造/register/trace submit/spec submit/root-start 合并在一个块 | 源码 935–948 明确是 trace 先排队、无归属 spec 后排队；需有归属 envelope，而非仅交换两次 submit |

[verified] writer 批失败后按 `_row_trace_id` 分组，spec 目前归入 `""` 组（`message_flow.py:702–735`）；单纯“先存 spec 后存 root”仍可能在分组重试/队列满时断开。新 envelope、丢失归账和存储 finality 必须一起测试。

## 6. Proposed Changes

### 6.1 会话与事件身份合同（R1、R2）

[inferred] `_flow_key` 使用 `(platform, bot_id, conversation_kind, peer_id, message_id)`，或等价的 `(conversation_key,message_id)`；gateway 优先复用 `_event_key:200`/ConversationRef 的规范构造。所有 `_flow_ingress_root/_end`、`_flow_root_for/_or_create` 共同使用，禁止保留旧 tuple 索引构造 source key。新 `source_message_key` 为 `<conversation_key>:msg:<message_id>`，message ID 原样字符串化，不把私聊 peer 当成群号。

[inferred] FlowContext 和 message_traces 追加 `conversation_key,bot_id,conversation_kind,peer_id,storage_session_id,source_message_id`。QQ preprocessor 可不查业务库，先记录身份及 source ID；matcher 拿到已注册 ref 后，通过新幂等补充接口设置 storage ID，写同 trace 的 metadata update，不重建 root。补充只允许空→可信值，冲突标记 `identity_state=conflict`；DB lookup/query 只读，不在 Dashboard API 注册新会话。

[inferred] `scope` 保留旧显示/筛选合同，不作为新轨迹的数据查询主键。历史缺字段仅做可证明解析：旧群 scope 能给群号但不能推断 Bot；旧私聊 source key 缺 peer 时禁止靠相近时间补全身份。API 提供 `identity_state=exact|legacy_partial|conflict|missing`，空字段不强制填 0。

[inferred] 同事件重入共享 root，结束时以缓存 key + 取得的 ctx 身份做 compare-and-pop；另一个 event/ctx 的迟到 postprocessor 不得关闭替换后的 root。缓存淘汰对活跃 ctx 显式 unknown/partial，记可观测原因。保留 gateway matcher 生命周期，不新增业务事件并发调度器。

### 6.2 spec 不可变归档与迁移（R5）

[inferred] FLOW_SCHEMA_VERSION 从 2→3，按现有可重复 ALTER/建表方式追加 identity 列和 `flow_spec_blobs`。保留 `flow_specs(topology_version PK)`，不重建或删除旧表。新表建议合同：`spec_digest TEXT PRIMARY KEY, topology_version TEXT NOT NULL, manifest_schema INTEGER NOT NULL, canonicalization TEXT NOT NULL, spec_json TEXT NOT NULL, archived_at_utc TEXT NOT NULL`，加 `(topology_version,spec_digest)` 索引。

[inferred] 新 spec digest 复用生成器 `content_hash:485` 的**完整 64 位 SHA-256**：排除 source_revision，排序键，紧凑 UTF-8 JSON；canonicalization 标识 `stella-flow-content-v1`。归档保存该 canonical payload，source_revision 作为独立 provenance 元数据，避免同 digest 对应不同 payload。12 位文件名只用于资源定位。校验 bundled 内容与 digest；失配/丢失不归档 `{}`。

[inferred] 启动或组件初始化时加载/校验 packaged spec 并缓存；消息热路径只取缓存结果。`begin_trace` 提交带 trace_id 的 owned root bundle，其中包含 spec prerequisite、trace 行和 root-start；同一事务落档。队列满或 spec/trace 写入失败计入此 run loss；per-trace fallback 必须重放整个 bundle。允许同 digest 幂等 INSERT，但拒绝内容不同的覆盖；存储不可用时业务继续，观测为 partial/unknown。

[inferred] 两种完整性分别表达：`spec_binding=exact|legacy_unverified|missing|invalid` 与现有 runtime integrity。bundled spec 尚未就绪的 root 不能指向别的 spec；可以保持 binding missing，异步恢复时仅给有明确期望 digest 的新 root 补归档。不能事后把旧空摘要绑定到当前版本。

[inferred] 历史 flow_specs 可归档其真实 JSON 生成 blob，但历史 roots 的空 spec_digest 保持空；它们仍按原 semantic version 尝试读取旧档，显示 legacy_unverified。新 API 保留 `/flow/specs/{version}`，增加 `digest` query；传了 digest 必须 exact match，否则 404，无 current/latest fallback。缓存按 digest；仅 legacy 缓存按 version+binding 状态，并明确不保证精确匹配。同 version 不同 digest 并存。

[inferred] 迁移在停写/启动阶段执行，先按现有数据库备份机制备份，单事务完成，失败保持旧组件版本、旧数据可读；测试 v1→v3、v2→v3、空库和重复执行。旧客户端忽略新增字段，新客户端读取旧 DB 时提供默认值。回退代码可读旧列/旧档；需要恢复数据库时使用迁移前备份并明确会丢弃迁移后新增事实，不能自动抹掉新数据。

### 6.3 会话中立 IO 与回执合同（R1）

[inferred] message_io 先读精确 trace identity；输入按 `conversation_key + source_message_id` 或 ref 的 `storage_session_id + msg_id` 查业务 group_messages，并核对 Bot/kind/peer。新私聊身份缺失时返回 missing/legacy_partial；禁止把负 storage ID 展示为真实群号，禁止跨 Bot/peer 的时间窗口兜底。群旧数据兜底只标注 `provenance=legacy_time_window`，不标 exact。

[inferred] **复用现有 social_deliveries 的投递事实存储**，不复制正文进 flow_events，也不新增聊天表。DeliveryReceipt 追加 optional canonical conversation 字段（或 ConversationRef 输入再序列化），`deliver_lines` 增加 optional `receipt_conversation`。scope 非空沿用现有存档；scope=None 且有明确合法 ref 时，仅存中立回执；scope=None 且没有 ref 的旧调用仍跳过持久化。因此保留原 `test_no_scope_skips_persistence`，新增“显式私聊 ref 存回执但不学习”的用例，不能直接删除旧断言。

[inferred] social 组件 v1→v2：social_deliveries 追加 `conversation_key,conversation_kind,peer_id,storage_session_id,learning_eligible`，保留现有 bot_id/platform/trace_id/turn_id/part_index。新中立私聊行 `group_id=''`、`learning_eligible=0`；群 scope 行才可为 1。旧行以可信 QQ 群字段迁移 eligibility，不为缺 Bot 的行捏造 canonical key。DDL 需在 CREATE 后、建新增列索引前执行；现有 ensure_social_schema 的 CREATE IF NOT EXISTS 不能替代 ALTER。主 memory schema v16 不变，Rust 当前没有 social_deliveries SQL 消费，执行时再核验这一边界。

[inferred] `_append_and_persist` 传 ref 并按上述条件存档，维持 acknowledged/failed/unknown 状态和现有 `(turn_id,part_index)` 幂等。落库失败只记录 receipt persistence unknown，不能取消已确认发送、反向重发或伪造完整正文。私聊仍不调用 open_effect、社会事件采集或群表达学习；中立回执遵循现有聊天历史访问与保留策略，SOCIAL 总开关继续控制学习。

[inferred] 收紧共享表查询边界：open_effect 只接纳匹配当前群身份且 learning_eligible 的确认回执；find_delivery_by_platform_id 新增 scope/conversation 限定，旧仅 ID 调用只能查学习可用群行；无 scope 的歧义匹配返回 None。引用归因调用方传现有 effect 的 platform/Bot/group；expression usage 查询排除中立行。不能因加入私聊行让它被群引用归因或群统计消费。

[inferred] IO output 按 exact trace_id + canonical identity 查回执，按原 part_index 排序，不改写为压缩后的序号；分别返回 acknowledged 输出与 failed/unknown 片段事实及存档完整性。BOT_SELF 作为标明来源的历史兼容路径：已有 `_record_bot_lines:2643` v16 含 trace/turn/logical ID/part_index/platform ID/ref 字段，但会跳过短文本和纯标点，因此不能仅靠它覆盖所有发送。命令回复也应进入同一可查询回执路径；500 字摘要不是完整正文。

### 6.4 显式 transition 与正确状态（R3、R9）

[inferred] 新增观测 `transition` helper，通过现有 `_emit_event` 写 `kind='decision',fact_kind='transition'`，不扩展旧 kind 枚举。在 metrics 的版本化字段记录 `transition_v=1, edge_id, from_node,to_node,from_span_id,to_span_id,from_instance,to_instance,attempt,relation_kind`；字段走现有脱敏，不含正文。静态 edge_id 确定性构造并区分 guard/loop/fork/join。

[inferred] 事实由实际控制边界发出：确定分支且真正调用下一阶段、重试启动、派生 worker 成功创建时记录；不能由两端状态或任意先后序推导。span 端点有句柄时记录真实 span；无 span 的 decision/checkpoint 用明确 occurrence ID，不能臆造 parent span。异步派生同时用既有 trace_relation，关系类型不混写成同步调用。transition 发出失败按本 run loss 归账。

[inferred] 第一批覆盖 QQ 群/私聊入口→锁/持久化→runtime、runtime 早退/生成/后处理、发送 gate/每片段/abort，以及压缩/整合实际派生。目录中其他边逐条标 `runtime_evidence=explicit|static_only`，必须查真实调用边界再接埋点；同语义实例并不足以证明经过一条边。新轨迹中尚未接入的边保持 static_only，页面不得标运行路径完整。

[inferred] edgeTraversed 只匹配 trace、edge_id、端点 occurrence/span、attempt 和有效 transition；越 trace、跨 attempt、两个兄弟 span、只看到 A/B 节点均不激活边。旧无 transition 的运行视图保留已观测节点与时间线，静态关系显示未确认样式/提示。起点依据 root-start，终点依据真实 root finish + producer/writer finality，移除基于静态 source/sink 的运行结束推断。布局连通性测试需改成事实准确性断言。

[inferred] reducer 的实例键优先真实 span_id，再结合 attempt；instance_key 是业务聚合维度，不能把不同 span 合成一个生命周期。checkpoint 更新摘要/metrics/last_seen，已有 running 不转 succeeded；只有对应 span 的 finish/cancel/error 才 terminal。无 span 的 decision 保留“判断事实”状态，不据此结束另一个活跃 span。terminal 后 checkpoint 不重开或覆盖终态，乱序事件按 seq/row watermark 去重投影；保留未知/丢失标识。

### 6.5 真实源码闭包与入口发现（R4、R7）

[inferred] 生成器先建立 repo-local Python 模块/导入/别名索引，对相对导入、直接函数、类方法和可证明的 receiver 做跨文件解析；第三方才归 external。循环/重复符号用 `(path,qualname)` visited；复用确定性 AST 归一化，hash 每个可达 helper 的实际体，不只存名字或大入口体。canonical closure 含 caller/callsite/callee、语言、解析状态与边界分类；不把 GitNexus 排名流程当完整枚举。

[inferred] 把 dynamic registration、插件、Rust FFI、外部 provider 单列 explicit boundary registry，锚定真实注册点/contract/源码或配置 hash。Rust 体可用确定性内容 hash + 已有合同 registry，不引入另一个 AST 平台；动态不可解析标 `dynamic_unresolved`，不伪装 third_party。closure 上限有确定性配置与 `truncated` 原因，4 个已知核心截断须解除或细分锚点；任何预算截断使闭包完整性 partial。

[inferred] 在生产模块范围独立扫描 matcher、startup/shutdown decorators、scheduled jobs、worker/queue 注册、模块顶层注册语句；排除 tests/scripts/deploy tooling 的规则写清并入 hash。发现集合与 inventory 双向差集：新增未登记入口失败，删除/失效登记失败；豁免必须给真实 external/intentional boundary 理由。用私聊处理器与新装饰器 fixture 证明“扫描能发现清单以外入口”。

[inferred] 补 qq_private ENTRY_ROOTS、私聊流程节点、chat.runtime、turn.direct_silent、compact.commit、command.reply、proactive.consolidate；补全已声明但无运行事实的参与度、scheduled gate/agent/deliver/runtime tick、social worker、知识 ingest/parse/version、AstrBot bridge。只在真实调用/有任务时建立 root；idle tick 不制造业务运行。某入口尚未观测须显示内部未接入，不能称 opaque external。

[inferred] 生命周期 inventory 改锚真实 `_start_scheduling:2487`、`_start_cometa:2532`、`_start_stop_watcher:3731`、`_graceful_shutdown:3854` 等 hooks，加入初始化/停止 root 与错误/取消事实，保留现有停止顺序：watchers → Cometa → scheduler → facade drain/stop → consolidation/compact wait → usage flush；最后 finish/flush 观测必须有界且不再触发新任务。不可为埋点重排资源收尾或替换停止策略。

[inferred] manifest schema→3、topology_version 一次升级到本次发布日期版本；新增 entry metadata、closure 与边界分类、真实 source_ref/hash、coverage denominators。API FlowSpec 和 UI 消费这些字段，给完整视图增加源码/闭包详情入口。分别展示语义目录覆盖、源码闭合状态、运行观测完整性、浏览器加载进度；130 节点/6,725 位点不构成全系统完成率。完整图不等同于逐语句运行回放，不逐行产生事件或改变 8K 模型上下文。

### 6.6 页面取数、导航和信息展开（R6、R7、R8）

[inferred] 新 `refreshTraceBundle(trace_id,generation,streamSession)` action 一次刷新 detail、IO、relations、trace entities；receipt 事实可节流触发，trace_end 和手动刷新必须触发。选中 trace 变化/隐藏页/注销时取消或失效旧请求，每个异步回包均检查身份，不只检查 getEvents。不能给每一条 SSE 事件做全量 IO 查询。

[inferred] 结束刷新采用有界补读：ended_utc 是 producer 信号；只有 writer finality 确认且冻结水位已读到，才为最终加载完成。API detail/events 增加 optional `event_high_watermark, storage_finalized, pending_writes`（名字可统一，但意义固定）；依据已提交 rows/现有 producer_ended 与 integrity 生成，不能从业务成功推断 finality。达到重试上限显示 pending/partial，并可手动重试；不得提前终止 SSE 丢尾部事实。

[inferred] list 保留 limit/offset 兼容，新增 keyset cursor `(started_utc,trace_id)` 与首屏查询快照上界，filter change 重置；旧分页和 live 新增分别合并去重，不用 offset 在不断插入列表中保证无遗漏。UI 可加载更多/列表窗口化，区分 authoritative total、当前已载、过滤后可见。默认 100 条不是总量上限。

[inferred] events 保留 after 参数，新增 until 水位；首读固定已提交上界，读满后再追 SSE 或新的稳定水位。最多页数/100k 安全阈值仍可保留，但必须显示截断与“继续加载/导出”，不可等同 complete；检测短页/缺口/去重/丢失计数，不用 row_id 连号判断单 trace 缺口（row_id 跨轨迹是全局）。大数组 cursor 用循环累计，避免 Math.max(...events)。

[inferred] 无精确 spec 时从事件创建 fallback 节点和时间线，边仍只来自合法 transition；无节点事件也显示 root/错误和缺失原因，不出现 graphLayout=null 的空白误导。标签/筛选由 manifest entry metadata 与运行 root union 生成，未知 root 原样可选。仅有输入为空时区分未提供、未持久化、identity 缺失、权限拒绝和加载失败。

[inferred] trace relation chips 支持跳转子/父 trace；使用既有 getTraceEntities/getEntityHistory 显示对象变更列表并导航相关 trace。只在业务真实使用消息/实体、提交更改或派生工作时写关联；知识/调度/Cometa 时间相近不构成因果边。中立回执、群数据与对象履历沿用既有 API 鉴权，不跨用户或会话展示正文。

[inferred] metrics 全量折叠/分页、output 所有片段可展开、完整业务正文按引用获取；诊断 summary 的脱敏/长度限额保持。提供截断、不可用、存档失败说明，不把 last 8 metrics/first 4 output 当全部；“未经过”改为“未观测/未加载/静态未确认”的对应状态。

## 7. Implementation Sequence

[inferred] 下列 M0–M6 按依赖执行。中间可做隔离测试和临时 manifest fixture；**所有 instrumentation/catalog/source 变更完成后，仅在 M6 一次正式重生成/同步 manifest**。中间漂移记录为 WIP，不合并、不假称 --check 通过；最后提交必须含生成物并通过门禁。

| 阶段 | 前提 | 实施内容 | 完成条件 |
| --- | --- | --- | --- |
| M0 锁定回归（P1） | 第 11 节 provenance 无漂移，图 freshness 确认 | 把已有 6 类隔离探针转为稳定失败用例；添加私聊/multi-Bot/旧 DB/spec 同版本 fixture | 明确当前失败是 R1–R9 的真实缺口；新 fixture 不调用真实 provider/账号 |
| M1 身份与 spec（P1） | M0 | 完整 root 键、可信 metadata 补充、schema3/spec blob/owned bundle/exact API | collision/结束竞争、队列满、批事务失败/分组重试、同版本 A/B、旧 DB 重复迁移均通过；旧调用默认兼容 |
| M2 私聊 IO（P1） | M1 身份合同 | receipt_conversation、social v2、群学习查询 guard、exact 输入/输出与 command receipt | 同 Bot 两 peer/两 Bot 同 ID 隔离；部分发送/短文本/纯标点/无 ID/存档失败准确；私聊零群学习作业；旧 scope=None 跳过行为仍通过 |
| M3 运行事实与状态（P1） | M1；发送埋点依赖 M2 | transition helper/关键链埋点、edge_id、attempt/occurrence、reducer/布局 | 无 transition 兄弟节点不激活边；重试/并发/派生不串边；start→checkpoint 保持 running；旧事件可读 |
| M4 目录与闭包（P1/P2） | M1–M3 合同稳定 | AST 跨文件闭包、辅助体 hash、入口发现/边界 registry、固定节点与内部族/lifecycle 埋点 | 新增入口/helper/import/dynamic registry 的 drift fixture 失败；已知四个核心截断收口；所有已知内部入口有测试或诚实 partial 标记 |
| M5 页面与后台导航（P1/P2） | M1–M4 API/manifest schema 可用 | bundle 刷新、水位/keyset/更多分页、缺 spec 回退、标签/源码详情/对象关联/全文 | 用户停留页可见最终输出；快切/旧 promise/SSE 重连不串；>100 traces、>100k 事件显示加载状态；对象/相关轨迹可导航 |
| M6 集成与交付（P1） | 全部源改动完成 | 一次正式生成、所有门禁、build/sync、真实 QQ/浏览器/桌面验收、graph diff | 第 13 节全部关闭；未完成真实账号或发行包验收必须列剩余项，不声明发布完成 |

[inferred] 每阶段改任何函数/类/方法之前对目标做新 impact（upstream；共享入口 depth3）；HIGH/CRITICAL 告知用户但不重复索要已授权实施权限。UNKNOWN 用源码/注册点补证；提交前 detect_changes scope all，不接受 partial/truncated。合并回归再用 compare/base_ref=main。本计划只交付文件，不替用户执行阶段。

## 8. Test Strategy

| 层与既有/新文件 | 输入 → 动作 → 期望 |
| --- | --- |
| `tests/observability/test_message_flow_runtime.py` + 新 `test_flow_identity_binding.py` | 两 Bot 同 msg_id；同 Bot 两私聊 peer；群/私聊相同 ID；重复事件、迟到结束、缓存淘汰 → root create/end → 相互隔离且同事件幂等 |
| `tests/observability/test_message_flow_integrity.py` | v1/v2 DB、同 version 两 payload、root bundle 队列满、spec INSERT 故障、batch rollback/per-trace retry → archive/read → digest 精确或明确 missing，per-run loss 正确，其他运行不受污损 |
| `tests/test_social_migrations.py`、`test_social_delivery.py`、`test_reply_effect_service.py` | scope=None 无 ref vs 有私聊 ref；社会组件 v1→v2 重复/故障迁移；群/私聊同平台 ID → 存回执/归因 → 旧跳过行为不变，中立行不参与群学习 |
| `tests/webui/test_message_flow_api.py`、`tests/test_private_chat_ingress.py` | 带注册表私聊 input、纯标点/多段 output、第二段失败、无平台 ID、command、receipt 存档失败 → IO → 保留真实 part_index、exact 身份、不补推 unknown 发送成功 |
| 新 `tests/observability/test_flow_source_closure.py`；合同/inventory tests | 临时 fixture 改辅助 return；跨文件 import/alias/relative import；新增 matcher/startup/worker；登记 Rust/dynamic 边界；递归与预算截断 → build/check → hash/drift/发现差集稳定，第三方与内部未解析区分 |
| background/memory/proactive lifecycle tests | idle、实际任务、失败/取消、startup 与 graceful shutdown → root/relation → 无闲置空业务 root；停止顺序不变、flush 有界；父子关系来自真实传递 |
| `dashboard/tests/flow-reducer.spec.ts` | start→checkpoint→finish、terminal→checkpoint、不同 span 同 instance、重复 attempt、乱序/重复、unknown/loss → projection → running 不提前结束，独立 span 不合并生命周期 |
| `dashboard/tests/flow-layout-executed.spec.ts`、layered tests | 仅 Astart/Bfinish；正确 transition；跨 attempt/trace/fork/loop/legacy → layout → 只激活合法事实边，终点不由静态 sink 猜测 |
| `dashboard/tests/flow-store.spec.ts` | IO 首读空→receipt→terminal，writer 晚提交、请求失败、trace 快切、旧 spec promise、可见性变更、连续 cursor、重复 SSE、分页上限 → refresh/load → 不串线、不漏尾部、不显示假完整 |
| 新 `dashboard/tests/flow-page.spec.ts` 或等价现有工具可运行页面验收 | 未知 root、spec404、点击关系/对象、展开全部输出/metrics、加载更多 → 页面交互 → 原始事实仍可见，导航可用；若引入 DOM runner 必须作为明确依赖改动而非假设已安装 |
| `dashboard/tests/perf-10k-layout.spec.ts` 扩展 | 实际规模 manifest + 10k events，多实例/loops；100k 事件增量分页 → reducer/layout → 记录 p50/p95/峰值；沿用 10k <5s 的宽门槛，避免逐事件重复全量布局 |

[verified] 已有 npm scripts、pytest 入口、标准库 generator 与 CI 门禁均存在。执行命令（PowerShell 中分别执行，不用命令分隔符拼接）：

```powershell
python -m pytest tests/observability tests/webui/test_message_flow_api.py tests/test_private_chat_ingress.py tests/test_conversation_registry.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_reply_effect_service.py -q
npm --prefix dashboard test
npm --prefix dashboard run typecheck
```

[inferred] M6 源改动结束后，使用生成器现有默认生成命令一次正式生成，然后检查（路径来自已核验 generator/CI/package scripts）：

```powershell
python scripts/generate_message_flow.py
python scripts/generate_message_flow.py --check
npm --prefix dashboard run build
npm --prefix dashboard run sync:webui
docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs analyze --index-only --pdg
docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo .
```

[inferred] CI 保留全依赖 Python test matrix 和纯标准库 flow-manifest；flow-closure job 把独立 discovered entry reconciliation 的失败作为门禁，不能只证明 GitNexus 可建库。Dashboard CI path filter 覆盖新增 identity/receipt/catalog/业务埋点来源（例如 core/social、memory、gateway、knowledge、scheduler 等），源码 helper 变化也要触发前端合同/生成物检查。CI 不借 regenerate 自动掩盖 --check 失败。

[inferred] 现场验收：在已授权测试账号发群/私聊/图片/命令；模拟 gate 拒绝、取消、第二段失败；停留页面观察发送完成；另两会话同时同消息 ID 的情况用 adapter fixture 确定性构造；执行一次真实后台派生/对象修改。对浏览器托管 webui/dist 与桌面 desktop/dashboard-dist 核验构建 marker/对应 JS hash 并实际打开页面。build/sync 不是最终安装包验证，必要的 clean Windows 发布验收仍独立进行。

## 9. Risk and Impact Analysis

[graph] **CRITICAL：_flow_key、begin_trace、_emit_event。** 本计划已明确警告；riskSharedAxes 不用于降级。参数默认兼容不能替代实际运行验证；身份、spec prerequisite、事件语义变更会影响 QQ/WebChat/主动/记忆/Cometa/调度及大量测试。

以下是五次 upstream 结果的**全部 d1 依赖**，按文件聚合；不是全部间接影响。测试依赖同样计入。每个名字对应保存图结果中的符号（同名测试在不同类时以表中的全限定名区分）。

| Primary / risk | d1 文件 | 全部直接依赖符号 |
| --- | --- | --- |
| `_flow_key` / CRITICAL | `stella_project/plugins/bot_main/ai_gateway.py` | `_flow_ingress_end`；`_flow_ingress_root`；`_flow_root_for`；`_flow_root_or_create` |
| `begin_trace` / CRITICAL | `capability/delegation.py` | `_flow_on_submit` |
| `begin_trace` / CRITICAL | `knowledge/ingest.py` | `_ingest_flow_root` |
| `begin_trace` / CRITICAL | `memory/consolidator.py` | `_consolidate_with_flow`；`MemoryConsolidator._consolidate_with_root#6` |
| `begin_trace` / CRITICAL | `memory/session_compact.py` | `schedule_compact._run@288:4` |
| `begin_trace` / CRITICAL | `memory/social_worker.py` | `run_due_jobs` |
| `begin_trace` / CRITICAL | `scripts/benchmark_capacity.py` | `bench_long_run_drain`；`bench_prune` |
| `begin_trace` / CRITICAL | `scripts/benchmark_flow_overhead.py` | `_run` |
| `begin_trace` / CRITICAL | `scripts/soak_longrun.py` | `main` |
| `begin_trace` / CRITICAL | `scripts/validate_rust_fullchain.py` | `_run_promotion` |
| `begin_trace` / CRITICAL | `stella_project/plugins/bot_main/ai_gateway.py` | `_flow_ingress_root`；`_flow_root_or_create`；`_proactive_at_user`；`_proactive_speak_for_group`；`proactive_speak_job` |
| `begin_trace` / CRITICAL | `tests/test_ai_gateway_deterministic_reply.py` | `test_flow_watch_finish_captures_reply_text` |
| `begin_trace` / CRITICAL | `tests/webui/test_message_flow_api.py` | `_seed_trace`；`TestCommandReplyVisible.test_command_reply_merged_into_output#3`；`TestFlowMessageContext.test_output_prefers_acknowledged_receipts#5` |
| `begin_trace` / CRITICAL | `webui/chat_ingress.py` | `run_turn` |
| `begin_trace` / CRITICAL | `webui/routers/chat.py` | `chat` |
| `begin_trace` / CRITICAL | `cometa/executor.py` | `AttemptExecutor.run_attempt#2` |
| `begin_trace` / CRITICAL | `memory/compressor.py` | `MemoryCompressor.run_weekly#0` |
| `begin_trace` / CRITICAL | `memory/memory_manager.py` | `MemoryManager.process_new_candidates#1` |
| `begin_trace` / CRITICAL | `stella_project/plugins/bot_main/scheduling/runtime.py` | `SchedulerRuntime._flow_root#2` |
| `begin_trace` / CRITICAL | `tests/observability/test_background_flow_roots.py` | `TestSocialWorkerRoot.test_no_jobs_creates_no_root#1` |
| `begin_trace` / CRITICAL | `tests/observability/test_memory_flow_lifecycle.py` | `TestConsolidateRootLifecycle.test_parent_link_when_flow_ctx_passed#2` |
| `begin_trace` / CRITICAL | `tests/observability/test_message_flow_integrity.py` | `TestEntityHistory.test_record_and_history_roundtrip#1`；`TestHeartbeat.test_heartbeat_skips_ended_runs#1`；`TestHeartbeat.test_heartbeat_tick_touches_running_runs#1`；`TestPerRunIntegrity.test_late_writer_failure_corrects_only_its_run#2`；`TestPerRunIntegrity.test_leaked_spans_produce_partial_integrity#1`；`TestPerRunIntegrity.test_normal_end_finalizes_producer_ended_and_integrity#1`；`TestPerRunIntegrity.test_storage_unavailable_records_loss_not_raise#2`；`TestSanitization.test_bearer_and_token_shapes_redacted#1`；`TestSanitization.test_exception_records_stable_error_code_not_secrets#1`；`TestSchemaMigration.test_v1_database_migrates_additively#1`；`TestSpecArchive.test_spec_archived_on_first_root_reference#1`；`TestSpecArchive.test_trace_row_carries_process_identity#1` |
| `begin_trace` / CRITICAL | `tests/observability/test_message_flow_runtime.py` | `TestAsyncLoopLinks.test_by_source_key_lookup#1`；`TestAsyncLoopLinks.test_compact_root_linked_to_parent#2`；`TestDeliverySegmentFacts.test_abort_marks_unattempted_segments#1`；`TestDeliverySegmentFacts.test_delivery_without_root_is_silent#1`；`TestDeliverySegmentFacts.test_partial_send_second_segment_fails_stop#1`；`TestFacadeTurnFacts.test_cancelled_turn_facts#2`；`TestFacadeTurnFacts.test_direct_early_exit_skips_generation_and_finalize#1`；`TestFacadeTurnFacts.test_generate_turn_full_facts#2`；`TestFacadeTurnFacts.test_no_backend_fallback#1`；`TestFacadeTurnFacts.test_provider_error_marks_turn_error#1`；`TestRootLifecycle.test_attach_and_flow_of#1`；`TestRootLifecycle.test_begin_is_idempotent_for_active_trace#1`；`TestRootLifecycle.test_end_trace_sets_outcome_and_complete#1` |
| `begin_trace` / CRITICAL | `tests/observability/test_message_flow_store.py` | `TestDecisionsAndLinks.test_decision_and_checkpoint#1`；`TestDecisionsAndLinks.test_relation_links_both_traces#1`；`TestDecisionsAndLinks.test_self_link_ignored#1`；`TestSpanLifecycle.test_cancelled_span_status#1`；`TestSpanLifecycle.test_end_trace_is_idempotent#1`；`TestSpanLifecycle.test_exception_marks_failed_and_reraises#1`；`TestSpanLifecycle.test_leaked_span_marked_unknown_and_partial#1`；`TestSpanLifecycle.test_span_start_finish_pairs_and_projection#1`；`TestWriterDiscipline.test_flush_drains_queue#1`；`TestWriterDiscipline.test_sensitive_keys_scrubbed#1`；`TestWriterDiscipline.test_unknown_root_kind_recorded#1` |
| `begin_trace` / CRITICAL | `tests/observability/test_proactive_flow_lifecycle.py` | `TestDecisionTrackerObservability.test_decide_slot_metrics_visible_in_mode_decision#2`；`TestParticipationAllLevels.test_observe_disabled_tables_records_blocked#2`；`TestParticipationAllLevels.test_observe_records_all_levels_and_warmup_exit#2`；`TestProactiveAtSelection.test_no_candidate_records_select_reason#2`；`TestProactiveAtSelection.test_quota_rejection_reason_lands_on_at_preflight#3`；`TestProactiveAtSelection.test_selection_records_chosen_candidate#2`；`TestProbeBypass.test_probe_exceptions_never_break_observe#3` |
| `_emit_event` / CRITICAL | `core/observability/message_flow.py` | `_emit_span_start`；`checkpoint`；`decision`；`end_trace`；`link`；`FlowSpan.finish#5` |
| `edgeTraversed` / LOW | `dashboard/src/views/data/flowLayout.ts` | `layered` |
| `build_manifest` / LOW | `scripts/generate_message_flow.py` | `main` |
| `build_manifest` / LOW | `tests/observability/test_message_flow_contract.py` | `manifest` |
| `build_manifest` / LOW | `tests/observability/test_internal_flow_inventory.py` | `TestManifestIntegration.manifest#0` |

[inferred] 主要风险及退出方式：

- spec 队列/事务错序：owned bundle + 故障注入；仅交换 submit 不合格。
- 中立私聊回执进入群归因：scope/eligibility 查询 guard + 同平台 ID 跨 Bot/peer 测试；SOCIAL 学习关闭仍关闭。
- 旧数据伪绑定或错误身份：历史空 digest 不回填 exact；无证据禁止时间窗跨会话取正文。
- transition 增加热路径开销：只记录语义/分支/派生事实，保持有界队列与脱敏，不能逐语句发事件或 sync flush。
- closure 扫描爆炸/误判第三方：visited、显式边界、确定性预算和 partial 标记；不能用 whitelist 消除真实内部入口缺口。
- 实时/API 竞态：请求代际、水位与 storage finality 分离；端点 ended 不等于浏览器已完整。
- 前端大数据卡顿：增量 cursor/去重/窗口化、宽性能门槛，实际 manifest fixture 验证；前轮 12 节点基准不能证明新规模。
- 用户已有未跟踪 Laya 计划：不改、不 stage；generated_plan_path 只排除本计划，其他 dirty 都由 provenance 纳入。

## 10. Files Expected to Change

[inferred] 下表是实现修改范围；core/conversation 与 registry 优先复用，不为本任务重写身份、负 ID 分配或私人记忆授权。

| 文件/范围 | 修改目的 |
| --- | --- |
| `stella_project/plugins/bot_main/ai_gateway.py` | root key/metadata/ref、私聊/command receipt、关键 transition、lifecycle root；不重排业务/关闭路径 |
| `core/observability/message_flow.py` | schema3、identity update、spec archive bundle、transition helper、finality/loss |
| `core/observability/flow_catalog.py`、`internal_flow_catalog.py` | 私聊与固定节点、explicit edge IDs、真实 inventory/边界、发现差集 |
| `scripts/generate_message_flow.py`；必要时新同目录 closure helper | 跨文件闭包/辅助 hash/discovery/确定性资源输出；标准库运行 |
| `core/observability/flows/message-flow.<digest12>.json` | M6 生成的新 schema3 manifest；保留历史资源的归档/兼容读取，不手改 JSON |
| `core/social/contracts.py`、`core/social/delivery.py` | receipt_conversation 中立合同、显式发送事实、持久化失败状态 |
| `memory/social_schema.py`、`memory/social_store.py` | social v2 migration、canonical receipt 存档与 scoped lookup |
| `memory/reply_effect_service.py`；必要时 `expression_selector.py/expression_learning.py` | 群学习过滤与引用归因传 scope；改前 impact/源码核实实际消费者 |
| `webui/chat_ingress.py` | 现有 WebChat record_delivery 调用补规范身份，避免新回执合同漏入口 |
| `core/runtime/facade.py`、`memory/session_compact.py` 等目录已锚定关键边界 | transition/固定节点补齐，保留共享引擎；具体符号改前再 impact |
| knowledge、scheduler、social worker、AstrBot/Cometa 等 inventory 对应实际入口文件 | M4 仅补真实运行与派生事实；由登记锚点定点实施，不扫描重构全模块 |
| `webui/services/flow.py`、`webui/routers/trace.py` | exact spec/IO、cursor/watermark/finality；旧接口兼容 |
| `dashboard/src/api/flow.ts`、`stores/flow.ts`、`stores/flowReducer.ts` | additive API types、分页/刷新/实例状态与完整性状态 |
| `dashboard/src/views/data/flowLayout.ts`、`FlowPage.vue` | 事实连线、无 spec 回退、动态标签、闭包/关联/全文/分页界面 |
| 第 8 节既有测试及明确标为新的测试文件 | 回归矩阵；页面 DOM 依赖如需要单列变更 |
| `.github/workflows/ci.yml`、`dashboard_ci.yml` | source/discovery/drift/路径触发门禁 |
| `dashboard/dist`、`webui/dist`、`desktop/dashboard-dist` | 本地构建快照（当前忽略路径）；由已有 sync:webui 同步，实际发布按现有流程 |

## 11. Reusable Implementation Context

以下 JSON 是执行上下文；不需要重新全仓调查。evidence_provenance 为官方 serializer 的原始 schema-2 值。执行前用技能 helper 的 read-plan 读取本文件，再按 manifest 路径重算 snapshot；HEAD/dirty/cited bytes 若变化，只重查变动证据和受影响工作包。

```json
{
  "implementation_context": {
    "task_summary": "只实施复核报告 R1-R9：规范身份/exact spec/中立IO/明确运行事实/真实源码闭包/实时分页与导航；当前交付仅计划",
    "acceptance_criteria": [
      "完整 key 与 ref 保证 QQ 私聊/群聊/多 Bot 隔离",
      "spec full64 digest、owned archive+root、旧轨迹 legacy_unverified",
      "中立回执可查询且不进入群学习；scope=None 无 ref 仍 skip",
      "仅 transition 激活边；checkpoint 不结束 span",
      "跨文件 helper hash 与独立入口 discovery 门禁",
      "IO bundle 实时更新、稳定加载水位和分页、无 spec 事实可读",
      "相关 trace/对象/源码导航与全文展开",
      "M6 一次正式 manifest regeneration、测试/build/sync/现场验收分开报告"
    ],
    "evidence_provenance": {
  "schema_version": 2,
  "head_commit": "6d73b9f70bd3797cb97af88a999bc59d9582cdcf",
  "generated_plan_path": "docs/plans/2026-10-04-gitnexus-plan-dashboard-flow-completeness-repair.md",
  "global_dirty_digest": {
    "algorithm": "sha256",
    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
    "value": "07b89fd3d3e8238418d86dd0319700e0ea7fc6f3981ad01355fcd9085bc289f9"
  },
  "cited_path_manifest": [
    {
      "path": ".github/workflows/ci.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:fdd5a82926831dc902d6d5986fc862275c49dcb8ae986af5948ca2e18eac0ea5",
      "index_digest": "sha256:fdd5a82926831dc902d6d5986fc862275c49dcb8ae986af5948ca2e18eac0ea5",
      "worktree_digest": "sha256:63de89a47ac1b55e5a0fd35b20c8724d8a8082ddf212f26f2726e9b78f624e81",
      "untracked_digest": "absent"
    },
    {
      "path": ".github/workflows/dashboard_ci.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e81d33b95b477e9ce5411158674462667c4be34612d1da3f65d4b0275443d469",
      "index_digest": "sha256:e81d33b95b477e9ce5411158674462667c4be34612d1da3f65d4b0275443d469",
      "worktree_digest": "sha256:e81d33b95b477e9ce5411158674462667c4be34612d1da3f65d4b0275443d469",
      "untracked_digest": "absent"
    },
    {
      "path": "AGENTS.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
      "index_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
      "worktree_digest": "sha256:d2a89022b9fa5087cad8d80549aade7104a50ee4768db4979c243ab6b16f4db2",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/delegation.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:330d97327e38d9440f766ce17863f5ae6636da68e9b1c1bf2c2c290db26596b8",
      "index_digest": "sha256:330d97327e38d9440f766ce17863f5ae6636da68e9b1c1bf2c2c290db26596b8",
      "worktree_digest": "sha256:330d97327e38d9440f766ce17863f5ae6636da68e9b1c1bf2c2c290db26596b8",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/executor.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:23de78138d6edcefe7368d473f60423df413fc50c792a34713ef8bf5538c49d2",
      "index_digest": "sha256:23de78138d6edcefe7368d473f60423df413fc50c792a34713ef8bf5538c49d2",
      "worktree_digest": "sha256:23de78138d6edcefe7368d473f60423df413fc50c792a34713ef8bf5538c49d2",
      "untracked_digest": "absent"
    },
    {
      "path": "core/conversation.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2cf946658f0c45a379378ca4c84ca6ad516768e5f5ec7c5a87c00d1fc62a65e3",
      "index_digest": "sha256:2cf946658f0c45a379378ca4c84ca6ad516768e5f5ec7c5a87c00d1fc62a65e3",
      "worktree_digest": "sha256:2cf946658f0c45a379378ca4c84ca6ad516768e5f5ec7c5a87c00d1fc62a65e3",
      "untracked_digest": "absent"
    },
    {
      "path": "core/observability/flow_catalog.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:aec48e99326106ccbea8dbcbb380ad4c06b031bbab389ab47bd528d3f7b621b3",
      "index_digest": "sha256:aec48e99326106ccbea8dbcbb380ad4c06b031bbab389ab47bd528d3f7b621b3",
      "worktree_digest": "sha256:eed473642aefff6905a0ff890dec9fd98bc4dfa0ed3d082e2a3cf0a9e5321b6f",
      "untracked_digest": "absent"
    },
    {
      "path": "core/observability/flows/message-flow.da26f49a7853.json",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:27f3ec38cb654f4e94db0758d17d9f2ebae1ccac1aaed77b1825e254d1683088",
      "index_digest": "sha256:27f3ec38cb654f4e94db0758d17d9f2ebae1ccac1aaed77b1825e254d1683088",
      "worktree_digest": "sha256:43396d6978847991696b7d69cf1723676e4502203b7bc0c161f40fd580f87b47",
      "untracked_digest": "absent"
    },
    {
      "path": "core/observability/internal_flow_catalog.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:53ec82fcda7207ce65ceb2c748203257f957e4e74010d67ee8c0332846c97b21",
      "index_digest": "sha256:53ec82fcda7207ce65ceb2c748203257f957e4e74010d67ee8c0332846c97b21",
      "worktree_digest": "sha256:96b48adbaecb1b935eb06f3fdf4883376733b74be95403812bcb61d5753b4cd4",
      "untracked_digest": "absent"
    },
    {
      "path": "core/observability/message_flow.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:891898e1e73a18ef386faf2c856c4ba8b9582e94dd313280b5bdf9d9e37a8e66",
      "index_digest": "sha256:891898e1e73a18ef386faf2c856c4ba8b9582e94dd313280b5bdf9d9e37a8e66",
      "worktree_digest": "sha256:7c61d7c9b3ca0e65c250741627d78fd6ed47edd1d1568fb64ad0d240fcc30a6d",
      "untracked_digest": "absent"
    },
    {
      "path": "core/runtime/facade.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:cb6f072ffc6749a176995b7947c666da4711ca3c6cd0e27478f0acad18073f2c",
      "index_digest": "sha256:cb6f072ffc6749a176995b7947c666da4711ca3c6cd0e27478f0acad18073f2c",
      "worktree_digest": "sha256:ae1b4544ba93aab006b29cc9e6013d792c135bcd71893725adb3034eb7dc7443",
      "untracked_digest": "absent"
    },
    {
      "path": "core/social/contracts.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:d16cceffc0e9035d008fea6555b02416a1e96ee834a70511988c47ad7f761eb9",
      "index_digest": "sha256:d16cceffc0e9035d008fea6555b02416a1e96ee834a70511988c47ad7f761eb9",
      "worktree_digest": "sha256:2a560e46fa00fb1ae4ce7a4040c106d3291e1ae15948cbff6ce47da25df754e9",
      "untracked_digest": "absent"
    },
    {
      "path": "core/social/delivery.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ff023f32956b9400e2a92bfb84c506105a2f299a8a7337827bfda4e8e29373f5",
      "index_digest": "sha256:ff023f32956b9400e2a92bfb84c506105a2f299a8a7337827bfda4e8e29373f5",
      "worktree_digest": "sha256:ff023f32956b9400e2a92bfb84c506105a2f299a8a7337827bfda4e8e29373f5",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/package.json",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:0f32f08322bd32a9c14657cf9e1e8d91a05ca986f9cb3f487d3cfedffc758493",
      "index_digest": "sha256:0f32f08322bd32a9c14657cf9e1e8d91a05ca986f9cb3f487d3cfedffc758493",
      "worktree_digest": "sha256:912e7945191a26f7fa78790febe92516a62bc4b9b149bc2c24a457145e47e076",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/api/flow.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a2cce239ef1a28ca2fb0719254921f499d35c159baf54c49071188dd2390560d",
      "index_digest": "sha256:a2cce239ef1a28ca2fb0719254921f499d35c159baf54c49071188dd2390560d",
      "worktree_digest": "sha256:a2cce239ef1a28ca2fb0719254921f499d35c159baf54c49071188dd2390560d",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/stores/flow.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:9e4358ab5a9e7b5746c2da9d208b6f6217d9c87fb8e07a82652a39395f211e57",
      "index_digest": "sha256:9e4358ab5a9e7b5746c2da9d208b6f6217d9c87fb8e07a82652a39395f211e57",
      "worktree_digest": "sha256:9e4358ab5a9e7b5746c2da9d208b6f6217d9c87fb8e07a82652a39395f211e57",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/stores/flowReducer.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2fa923d2a83f64a1dc7d3811157e9352b4182218d7a53ef3514495a0402db15b",
      "index_digest": "sha256:2fa923d2a83f64a1dc7d3811157e9352b4182218d7a53ef3514495a0402db15b",
      "worktree_digest": "sha256:2fa923d2a83f64a1dc7d3811157e9352b4182218d7a53ef3514495a0402db15b",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/views/data/FlowPage.vue",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:cef0bd3fe34729d2292030a4afda41704832afe04497907db2678e51ea9457fd",
      "index_digest": "sha256:cef0bd3fe34729d2292030a4afda41704832afe04497907db2678e51ea9457fd",
      "worktree_digest": "sha256:cef0bd3fe34729d2292030a4afda41704832afe04497907db2678e51ea9457fd",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/views/data/flowLayout.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:760fc9eaaada981fc23bcbeb68b3bca1bac01b131d2e219b4ecb4ea2cb7e3101",
      "index_digest": "sha256:760fc9eaaada981fc23bcbeb68b3bca1bac01b131d2e219b4ecb4ea2cb7e3101",
      "worktree_digest": "sha256:760fc9eaaada981fc23bcbeb68b3bca1bac01b131d2e219b4ecb4ea2cb7e3101",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/sync-dist.mjs",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:aa7f0932164b3159c5e1814b9f26961d1e2d6894e3298b07392d1f5c4226018f",
      "index_digest": "sha256:aa7f0932164b3159c5e1814b9f26961d1e2d6894e3298b07392d1f5c4226018f",
      "worktree_digest": "sha256:aa7f0932164b3159c5e1814b9f26961d1e2d6894e3298b07392d1f5c4226018f",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/tests/flow-layout-executed.spec.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a067197ea3e2c6a6a78d9d0d5e3a2541a7aa2c0e6ddd1fd22d47c425d28e001f",
      "index_digest": "sha256:a067197ea3e2c6a6a78d9d0d5e3a2541a7aa2c0e6ddd1fd22d47c425d28e001f",
      "worktree_digest": "sha256:a067197ea3e2c6a6a78d9d0d5e3a2541a7aa2c0e6ddd1fd22d47c425d28e001f",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/tests/flow-layout-layered.spec.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6e231a553e26e2b5dfdb32fa5cd7023abd6e46e8ae87cfaa2cbe61e0ab1c2b3b",
      "index_digest": "sha256:6e231a553e26e2b5dfdb32fa5cd7023abd6e46e8ae87cfaa2cbe61e0ab1c2b3b",
      "worktree_digest": "sha256:6e231a553e26e2b5dfdb32fa5cd7023abd6e46e8ae87cfaa2cbe61e0ab1c2b3b",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/tests/flow-reducer.spec.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:98d301d4f5c05be7111ce12d6d3f5f7ed2dfc2150d277325d9a145b6a1d124b7",
      "index_digest": "sha256:98d301d4f5c05be7111ce12d6d3f5f7ed2dfc2150d277325d9a145b6a1d124b7",
      "worktree_digest": "sha256:98d301d4f5c05be7111ce12d6d3f5f7ed2dfc2150d277325d9a145b6a1d124b7",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/tests/flow-store.spec.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:186e3e65c9e8678aaafee0868516178f689d0b22d45b5198b97b162c30c15c79",
      "index_digest": "sha256:186e3e65c9e8678aaafee0868516178f689d0b22d45b5198b97b162c30c15c79",
      "worktree_digest": "sha256:186e3e65c9e8678aaafee0868516178f689d0b22d45b5198b97b162c30c15c79",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/tests/perf-10k-layout.spec.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a3efd75f81ccd4afc72cb991820a62a53e482d1d0f693c552b6a47abee4dd16f",
      "index_digest": "sha256:a3efd75f81ccd4afc72cb991820a62a53e482d1d0f693c552b6a47abee4dd16f",
      "worktree_digest": "sha256:74a02bc7c90b18cef07d96fe1b8441c3b712a4478183d460edf022467c08d415",
      "untracked_digest": "absent"
    },
    {
      "path": "docs/reports/2026-10-04-dashboard-message-flow-completeness-review.md",
      "object_kind": {
        "head": "absent",
        "index": "absent",
        "worktree": "absent",
        "untracked": "regular"
      },
      "state": "untracked",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "absent",
      "index_digest": "absent",
      "worktree_digest": "absent",
      "untracked_digest": "sha256:c4179881ec330402cfce6ca20e45de1ed8b6c76f4a5c9c01f175a91b24c592d4"
    },
    {
      "path": "knowledge/ingest.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2157e1f49cb6142204c34daf844e4e039b833ab15aefabf8ad83d29e8c6a7326",
      "index_digest": "sha256:2157e1f49cb6142204c34daf844e4e039b833ab15aefabf8ad83d29e8c6a7326",
      "worktree_digest": "sha256:15f53cacfc58b0e1310ce7803bd10926b4bd4265be237f3435c6298a31036c69",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/compressor.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:9653f435986c3a98fb5a8584b37b31df903882a982ab7fc9b486fe149b5ae0d4",
      "index_digest": "sha256:9653f435986c3a98fb5a8584b37b31df903882a982ab7fc9b486fe149b5ae0d4",
      "worktree_digest": "sha256:4927f4617d6918641f7864a910c72bace90b6a2907dc88bebb1fb4f43c7f1c43",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/consolidator.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e4b64c416beb9b7fd1b385cc81ed6b347f6454495f87b2eec91dd675697cf0cb",
      "index_digest": "sha256:e4b64c416beb9b7fd1b385cc81ed6b347f6454495f87b2eec91dd675697cf0cb",
      "worktree_digest": "sha256:aa004732273ae5abca12c9f2393cd4d0637eb4c50750da67ff7c0eac222bb90c",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/conversation_registry.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c1c5ae67f7e36ddad84f5e1835caa985af1259110285c19ef59a53ea45d4f688",
      "index_digest": "sha256:c1c5ae67f7e36ddad84f5e1835caa985af1259110285c19ef59a53ea45d4f688",
      "worktree_digest": "sha256:c1c5ae67f7e36ddad84f5e1835caa985af1259110285c19ef59a53ea45d4f688",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/expression_learning.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6a57f9854c149d23f609cd6ef05c797a27512ef6ab4d1e1d7128dce14cfda623",
      "index_digest": "sha256:6a57f9854c149d23f609cd6ef05c797a27512ef6ab4d1e1d7128dce14cfda623",
      "worktree_digest": "sha256:dfdf19ae13defa15ccbfae752e24fe312014e651717f458d7788c413308e314f",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/expression_selector.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:9718b83c82b7ee2dba9ce0f2d2612ea3ce747f62e2dbed91d444094fbdae89a0",
      "index_digest": "sha256:9718b83c82b7ee2dba9ce0f2d2612ea3ce747f62e2dbed91d444094fbdae89a0",
      "worktree_digest": "sha256:854c9f7c9acddf6becdac9a1498d5d391e5183aafac69894eb8e20d10a432f02",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/memory_manager.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:709fc1dc1c3285d8eb606b260f68318e7f511ad3d986e38b650418624d1d0cd4",
      "index_digest": "sha256:709fc1dc1c3285d8eb606b260f68318e7f511ad3d986e38b650418624d1d0cd4",
      "worktree_digest": "sha256:9c7beb8222ffb8361b9f7786d6ab46069ae7e75cbfd7d9d2a175ccbc9d6e685e",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/pre_processors.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:97f1a5baf4e4479e746ab565a4a0ff0e641bcca0b940453ddaaf357155c27652",
      "index_digest": "sha256:97f1a5baf4e4479e746ab565a4a0ff0e641bcca0b940453ddaaf357155c27652",
      "worktree_digest": "sha256:97f1a5baf4e4479e746ab565a4a0ff0e641bcca0b940453ddaaf357155c27652",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/reply_effect_service.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:48b2250c1767a3c06b7148fbcd09dc844a1b6fa107d7d4b6f335049a5eafa5d0",
      "index_digest": "sha256:48b2250c1767a3c06b7148fbcd09dc844a1b6fa107d7d4b6f335049a5eafa5d0",
      "worktree_digest": "sha256:4dda103a7195cdff7066a867a40a148003b6926b8cdd2c65dfaaf29b9495e781",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/schema.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c149c7844d7fbe2fbfdbb032a69432300db36021d9cfec78be3f8ba4d1c8eecc",
      "index_digest": "sha256:c149c7844d7fbe2fbfdbb032a69432300db36021d9cfec78be3f8ba4d1c8eecc",
      "worktree_digest": "sha256:c53b1e2a7f1d21816303a8858266bfaea6190279bc5e3bb6bf152670920b76f0",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/session_compact.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:41bbce50b3ef86a5872795f367ae8647b734004c7b9f013a5527e90cf6e3de02",
      "index_digest": "sha256:41bbce50b3ef86a5872795f367ae8647b734004c7b9f013a5527e90cf6e3de02",
      "worktree_digest": "sha256:41bbce50b3ef86a5872795f367ae8647b734004c7b9f013a5527e90cf6e3de02",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/social_schema.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:921fa21c83feace43153c2ebdb90578d22544a6b107deb54aa63265387dbfca9",
      "index_digest": "sha256:921fa21c83feace43153c2ebdb90578d22544a6b107deb54aa63265387dbfca9",
      "worktree_digest": "sha256:dbadd9cae8d0af5ddd07ca3401555f8bd7807f71c0ecab76936e3b694fb8db92",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/social_store.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:84a188163580df84853415bb35c8097606dd7cd7b2529f0658fe4a82f88c6a0f",
      "index_digest": "sha256:84a188163580df84853415bb35c8097606dd7cd7b2529f0658fe4a82f88c6a0f",
      "worktree_digest": "sha256:fa080967c9f06aeaf122f9e54929df5088c3fa6a50e62e2ca83a62a46c2d8180",
      "untracked_digest": "absent"
    },
    {
      "path": "memory/social_worker.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:318bb9933be5533c554a12d2b47897a68fd1c7948ab62941be48bb8be5732685",
      "index_digest": "sha256:318bb9933be5533c554a12d2b47897a68fd1c7948ab62941be48bb8be5732685",
      "worktree_digest": "sha256:5d250353cbd548958e5aa8401d1f2b1bd409355eeab624e9d4059e7f146d16c4",
      "untracked_digest": "absent"
    },
    {
      "path": "scripts/benchmark_capacity.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:4cea940d43b2195f648f171810477a5388273bf88ae72583cf450af0881a29fd",
      "index_digest": "sha256:4cea940d43b2195f648f171810477a5388273bf88ae72583cf450af0881a29fd",
      "worktree_digest": "sha256:b22cb1a62367b05a1f8a841567e0d0bf82c7067710c47838e04f0f85ec63ca96",
      "untracked_digest": "absent"
    },
    {
      "path": "scripts/benchmark_flow_overhead.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:07b85cf409528d93d8e5ad4d40218ffa53b5bbd2953ebaa5289f0891b452959f",
      "index_digest": "sha256:07b85cf409528d93d8e5ad4d40218ffa53b5bbd2953ebaa5289f0891b452959f",
      "worktree_digest": "sha256:0991bdbb1b6c1adfcd625278d96d542525141ca6603742ca225343800d53a28c",
      "untracked_digest": "absent"
    },
    {
      "path": "scripts/generate_message_flow.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a8f8cbc7d887a3901a1fbc59d0fcc0fd2807686e248bb291cad2791151d08989",
      "index_digest": "sha256:a8f8cbc7d887a3901a1fbc59d0fcc0fd2807686e248bb291cad2791151d08989",
      "worktree_digest": "sha256:bdb42487df8808c3d17ff0932b3335c1313d5dd05def49457fce61a584c2e013",
      "untracked_digest": "absent"
    },
    {
      "path": "scripts/soak_longrun.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:b75dfdf9093045668e090f52e1dc9a101303004a69ad79736001906b015aa50f",
      "index_digest": "sha256:b75dfdf9093045668e090f52e1dc9a101303004a69ad79736001906b015aa50f",
      "worktree_digest": "sha256:3b20a48098daaff9b738abe4f47051a8c9b96b00fcfac249d5ab2a7c5ccf77c9",
      "untracked_digest": "absent"
    },
    {
      "path": "scripts/validate_rust_fullchain.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:f7f1fd6717667e51004aa17e1813ba3dd88d854d420fbb2ea5394d4861ed823c",
      "index_digest": "sha256:f7f1fd6717667e51004aa17e1813ba3dd88d854d420fbb2ea5394d4861ed823c",
      "worktree_digest": "sha256:0f5ed437c493b922166effb088af5a0cd6e15ba2a321f6d3fb3f8a8c0b2c72e8",
      "untracked_digest": "absent"
    },
    {
      "path": "stella_project/plugins/bot_main/ai_gateway.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ac2da29b079eafb5c2569adaefdff215f9528041e0b6e8318138d3e03a955b44",
      "index_digest": "sha256:ac2da29b079eafb5c2569adaefdff215f9528041e0b6e8318138d3e03a955b44",
      "worktree_digest": "sha256:ac2da29b079eafb5c2569adaefdff215f9528041e0b6e8318138d3e03a955b44",
      "untracked_digest": "absent"
    },
    {
      "path": "stella_project/plugins/bot_main/scheduling/runtime.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2d075c4b5fa8f51be20806baffbb0d5b1b98ee3b12f66f1d3a9b93cfa68a1be9",
      "index_digest": "sha256:2d075c4b5fa8f51be20806baffbb0d5b1b98ee3b12f66f1d3a9b93cfa68a1be9",
      "worktree_digest": "sha256:bca2f2592d6551192cbe20c2754b8da9763330eb3e679d36a4e61c9e37babf1f",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_background_flow_roots.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:35d6af11c1a3efdc2ecfd5d4e59a0191bacaa5110c2fc3a6e6fb8d4cb3dfedbc",
      "index_digest": "sha256:35d6af11c1a3efdc2ecfd5d4e59a0191bacaa5110c2fc3a6e6fb8d4cb3dfedbc",
      "worktree_digest": "sha256:6337da5c93c17cec45b54878879132acaa08da1fc680ad1f3c0795e026d14fd4",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_internal_flow_inventory.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:708c10f1bbe8c20b623bc9004d24bfd81462d448f66bf61d35f8a93be03137e4",
      "index_digest": "sha256:708c10f1bbe8c20b623bc9004d24bfd81462d448f66bf61d35f8a93be03137e4",
      "worktree_digest": "sha256:708c10f1bbe8c20b623bc9004d24bfd81462d448f66bf61d35f8a93be03137e4",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_memory_flow_lifecycle.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:4b781834ab8b63167970426d228c7010a5a71f5471450f8c26f77f8ce7f2dc4c",
      "index_digest": "sha256:4b781834ab8b63167970426d228c7010a5a71f5471450f8c26f77f8ce7f2dc4c",
      "worktree_digest": "sha256:4b781834ab8b63167970426d228c7010a5a71f5471450f8c26f77f8ce7f2dc4c",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_message_flow_contract.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:81de269cb7f5448452d9befa462f3b74b4ad1a9d076984f6790b44db1a8acd88",
      "index_digest": "sha256:81de269cb7f5448452d9befa462f3b74b4ad1a9d076984f6790b44db1a8acd88",
      "worktree_digest": "sha256:f45a1bc662a6f3dbd6dd5fc44c17fb0bff781feaac105b2a301d95d86158d3ac",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_message_flow_integrity.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e345d972a58cf20b11cfcf5ae6d9f37f59fa5394268151e001aedca4069d663c",
      "index_digest": "sha256:e345d972a58cf20b11cfcf5ae6d9f37f59fa5394268151e001aedca4069d663c",
      "worktree_digest": "sha256:6741f0b370e527310c6f5499b2f1b491a765fff4e7ddb0faf7657b3f7c8477c2",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_message_flow_runtime.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:1ddd4eaceb124c9d0f19c70f8aedb1d587cea8e222c400ec1b14fd2942ac1832",
      "index_digest": "sha256:1ddd4eaceb124c9d0f19c70f8aedb1d587cea8e222c400ec1b14fd2942ac1832",
      "worktree_digest": "sha256:38761024843306e26811974c8adbb1561130cf38646b85e02fda4402eb624f11",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_message_flow_store.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:00236b9fb3a548bd67dc386b7ef74923b6f2344d4249d11cdf0b7a01a410cb85",
      "index_digest": "sha256:00236b9fb3a548bd67dc386b7ef74923b6f2344d4249d11cdf0b7a01a410cb85",
      "worktree_digest": "sha256:00236b9fb3a548bd67dc386b7ef74923b6f2344d4249d11cdf0b7a01a410cb85",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/observability/test_proactive_flow_lifecycle.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a2a2a2aebe4314c6d498d7c0c67d493b79957f3203c489c2515f3cd7287d9b5d",
      "index_digest": "sha256:a2a2a2aebe4314c6d498d7c0c67d493b79957f3203c489c2515f3cd7287d9b5d",
      "worktree_digest": "sha256:a2a2a2aebe4314c6d498d7c0c67d493b79957f3203c489c2515f3cd7287d9b5d",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_ai_gateway_deterministic_reply.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6a30e507f3c847fc94344ac555445ed9c064c13b373e38d9eb7cbc6110750980",
      "index_digest": "sha256:6a30e507f3c847fc94344ac555445ed9c064c13b373e38d9eb7cbc6110750980",
      "worktree_digest": "sha256:6a30e507f3c847fc94344ac555445ed9c064c13b373e38d9eb7cbc6110750980",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_conversation_registry.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:fcf2fa7b6b7fadecf921595f4f751a5af03bf2cdac2b8ccf2020edbb09242e42",
      "index_digest": "sha256:fcf2fa7b6b7fadecf921595f4f751a5af03bf2cdac2b8ccf2020edbb09242e42",
      "worktree_digest": "sha256:fcf2fa7b6b7fadecf921595f4f751a5af03bf2cdac2b8ccf2020edbb09242e42",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_private_chat_ingress.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:8f3efaadbc989194ff11c787ac5bef47f20ffa443e5a021e75006808d9bf2894",
      "index_digest": "sha256:8f3efaadbc989194ff11c787ac5bef47f20ffa443e5a021e75006808d9bf2894",
      "worktree_digest": "sha256:8f3efaadbc989194ff11c787ac5bef47f20ffa443e5a021e75006808d9bf2894",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_social_delivery.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:f41fa0f7a2992e1a95c85a2c3606b796f01c4600481056cfb14326cfb1dfd361",
      "index_digest": "sha256:f41fa0f7a2992e1a95c85a2c3606b796f01c4600481056cfb14326cfb1dfd361",
      "worktree_digest": "sha256:fef1a172d35ae8e6dfdf31141228289972190171db458055f2279a478a7e61d3",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/test_social_migrations.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:928f84a7ace1198385fe6c4e13e01b20101231a1d56ee76b871e6f976f82017e",
      "index_digest": "sha256:928f84a7ace1198385fe6c4e13e01b20101231a1d56ee76b871e6f976f82017e",
      "worktree_digest": "sha256:803bdc1ee37df3ebcb5615b4b6029d7aecea191fb6c9c136eef196bd0ccc3e59",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/webui/test_message_flow_api.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:62d02a6038640d589c39f76e7af4c2d0fc414589e03998ffe37932ac71fc49e3",
      "index_digest": "sha256:62d02a6038640d589c39f76e7af4c2d0fc414589e03998ffe37932ac71fc49e3",
      "worktree_digest": "sha256:62d02a6038640d589c39f76e7af4c2d0fc414589e03998ffe37932ac71fc49e3",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/chat_ingress.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e10f66b88f98232f363abdc94c200cd7fedec6f5ad51c19f246e1650cd62ea2f",
      "index_digest": "sha256:e10f66b88f98232f363abdc94c200cd7fedec6f5ad51c19f246e1650cd62ea2f",
      "worktree_digest": "sha256:084fd839db79b0e5c1cfbeb83acdc8027aad0adb7fa7c890bdd6b196bfa7368d",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/routers/chat.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ad7d4d6de3f2a52a56747d2139f1a0b06396f196e1317e6b95b02e0e82354d1f",
      "index_digest": "sha256:ad7d4d6de3f2a52a56747d2139f1a0b06396f196e1317e6b95b02e0e82354d1f",
      "worktree_digest": "sha256:7d8e975619c56f08188d9eda43d109fc65bce8d893348faef4a14326202ee6ec",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/routers/trace.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6141a817eb35d964b2a8bd068d85b7512ffd96e1335f9f565b4c11e6336683a1",
      "index_digest": "sha256:6141a817eb35d964b2a8bd068d85b7512ffd96e1335f9f565b4c11e6336683a1",
      "worktree_digest": "sha256:6141a817eb35d964b2a8bd068d85b7512ffd96e1335f9f565b4c11e6336683a1",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/services/flow.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c80573b9f3e208b101059f6af9cf13bc145bcea7eee745ef8e6d32cf948160e9",
      "index_digest": "sha256:c80573b9f3e208b101059f6af9cf13bc145bcea7eee745ef8e6d32cf948160e9",
      "worktree_digest": "sha256:8db0c3b2a4dbb914bb6b6a88c6b872949ac9615ecb510fdd48f703f2b34031ee",
      "untracked_digest": "absent"
    }
  ]
},
    "primary_symbols": [
      {
        "symbol": "_flow_key",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "232-234",
        "role": "规范事件身份与 root 缓存键"
      },
      {
        "symbol": "begin_trace",
        "file": "core/observability/message_flow.py",
        "lines": "888-950",
        "role": "共享 root 创建、身份、spec 精确绑定"
      },
      {
        "symbol": "_emit_event",
        "file": "core/observability/message_flow.py",
        "lines": "1016",
        "role": "事件事实、transition 与 per-run loss"
      },
      {
        "symbol": "edgeTraversed",
        "file": "dashboard/src/views/data/flowLayout.ts",
        "lines": "373",
        "role": "实际连线事实判定"
      },
      {
        "symbol": "build_manifest",
        "file": "scripts/generate_message_flow.py",
        "lines": "354-482",
        "role": "目录、源码闭包与覆盖证据生成"
      }
    ],
    "related_symbols": [
      {
        "symbol": "_flow_ingress_root",
        "relationship": "CALLS _flow_key / begin_trace",
        "relevance": "类型过滤、同事件幂等、缓存上限"
      },
      {
        "symbol": "_flow_ingress_end",
        "relationship": "CALLS _flow_key",
        "relevance": "迟到结束 compare-and-pop"
      },
      {
        "symbol": "_flow_root_for",
        "relationship": "CALLS _flow_key",
        "relevance": "四个键消费者同步改动"
      },
      {
        "symbol": "_flow_root_or_create",
        "relationship": "CALLS _flow_key / begin_trace",
        "relevance": "fallback 保持规范身份"
      },
      {
        "symbol": "ConversationRef",
        "relationship": "identity contract",
        "relevance": "core/conversation.py:63 复用，不改变私人记忆授权"
      },
      {
        "symbol": "get_or_register_private",
        "relationship": "CALLS conversation_key / lookup",
        "relevance": "memory/conversation_registry.py:199 复用真实 storage ID"
      },
      {
        "symbol": "FlowContext",
        "relationship": "root state",
        "relevance": "message_flow.py:786 additive identity/spec fields"
      },
      {
        "symbol": "_Writer",
        "relationship": "persistence",
        "relevance": "有界队列、owned bundle、finality"
      },
      {
        "symbol": "_group_by_trace",
        "relationship": "retry grouping",
        "relevance": "message_flow.py:702 spec prerequisite 保持 trace 归属"
      },
      {
        "symbol": "_row_trace_id",
        "relationship": "loss ownership",
        "relevance": "message_flow.py:715 队列满归账"
      },
      {
        "symbol": "DeliveryReceipt",
        "relationship": "business fact",
        "relevance": "contracts.py:135 canonical fields 默认兼容"
      },
      {
        "symbol": "deliver_lines",
        "relationship": "gateway calls",
        "relevance": "群/私聊/主动 @/主动群聊共用"
      },
      {
        "symbol": "_append_and_persist",
        "relationship": "CALLS record_delivery",
        "relevance": "scope=None 有明确 ref 才 opt-in"
      },
      {
        "symbol": "record_delivery",
        "relationship": "business persistence",
        "relevance": "social_store.py:62 不覆盖既有 turn/part 事实"
      },
      {
        "symbol": "ensure_social_schema",
        "relationship": "component migration",
        "relevance": "social_schema.py:529 ALTER + 索引 + version 同事务"
      },
      {
        "symbol": "message_io",
        "relationship": "read-only API",
        "relevance": "flow.py:369 精确会话与回执"
      },
      {
        "symbol": "spec",
        "relationship": "read-only API",
        "relevance": "flow.py:283 digest exact / legacy version fallback"
      },
      {
        "symbol": "projectInstance",
        "relationship": "event projection",
        "relevance": "flowReducer.ts line56；checkpoint 不 terminal"
      },
      {
        "symbol": "useFlowStore",
        "relationship": "UI lifecycle",
        "relevance": "stores/flow.ts:35 generation+streamSession 隔离"
      },
      {
        "symbol": "validate_inventory",
        "relationship": "entry reconciliation",
        "relevance": "独立生产入口扫描，不只检查声明项"
      }
    ],
    "execution_path": [
      "preprocessor 按完整 event identity 创建/复用 root",
      "matcher 使用已注册 ConversationRef 补可信存储 metadata",
      "持久化输入 -> shared RuntimeFacade，实际分支产生 explicit transition",
      "deliver_lines 产生 acknowledged/failed/unknown segment receipts；明确 ref 的中立行存现有业务表",
      "BOT_SELF 仅历史兼容；scope/eligibility 限定群学习",
      "owned bundle/writer 异步落 spec+root+facts；producer end 与 committed finality 分离",
      "API 精确 digest/identity + cursor/until 查询，无证据禁止猜测",
      "store bundle refresh 每个回包校验 generation/streamSession；页面分别显示 spec/closure/runtime/loading 状态"
    ],
    "pdg_constraints": [
      {
        "description": "event 参数到旧 tuple return 缺 Bot/kind/peer [graph]",
        "affected_statements": [
          "stella_project/plugins/bot_main/ai_gateway.py:232",
          "stella_project/plugins/bot_main/ai_gateway.py:234"
        ],
        "implementation_consequence": "四个 key 消费者同步改，禁止仅改 scope"
      },
      {
        "description": "ingress 类型 guard、key 存在 return、容量淘汰 [graph]",
        "affected_statements": [
          "stella_project/plugins/bot_main/ai_gateway.py:394",
          "stella_project/plugins/bot_main/ai_gateway.py:400",
          "stella_project/plugins/bot_main/ai_gateway.py:401",
          "stella_project/plugins/bot_main/ai_gateway.py:402",
          "stella_project/plugins/bot_main/ai_gateway.py:411",
          "stella_project/plugins/bot_main/ai_gateway.py:412"
        ],
        "implementation_consequence": "同事件幂等；淘汰活跃 root 需明确 partial；非 QQ 不创建"
      },
      {
        "description": "active trace_id 命中时直接返回 [graph]",
        "affected_statements": [
          "core/observability/message_flow.py:914",
          "core/observability/message_flow.py:916",
          "core/observability/message_flow.py:917"
        ],
        "implementation_consequence": "保留旧接口幂等，不重绑已存在 root 的 spec/identity"
      },
      {
        "description": "PDG 创建块合并 submit；source 明确 trace 与无归属 spec 分提交 [graph+verified]",
        "affected_statements": [
          "core/observability/message_flow.py:918",
          "core/observability/message_flow.py:935",
          "core/observability/message_flow.py:945",
          "core/observability/message_flow.py:702",
          "core/observability/message_flow.py:715"
        ],
        "implementation_consequence": "owned envelope 在普通和分组重试事务中保留 archive prerequisite，不能仅交换 submit"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "ConversationRef 规范身份、registry 可信 storage ID",
        "example_location": "core/conversation.py:42,63; memory/conversation_registry.py:199",
        "usage_guidance": "复用，不推算私聊群号/负 ID，不改私人记忆权限"
      },
      {
        "pattern": "有界异步观测旁路、per-run loss",
        "example_location": "core/observability/message_flow.py:_Writer",
        "usage_guidance": "故障不能阻塞业务/重发；root bundle 保持 trace ownership"
      },
      {
        "pattern": "已有业务回执与独立 social 组件迁移",
        "example_location": "memory/social_store.py:62; memory/social_schema.py:529",
        "usage_guidance": "正文不入诊断事件，中立行 eligibility=0，scope=None 无 ref 仍 skip"
      },
      {
        "pattern": "只读 API + generation/streamSession",
        "example_location": "webui/services/flow.py; dashboard/src/stores/flow.ts",
        "usage_guidance": "不在 API 注册会话，不扩大鉴权；每类请求回包检查"
      },
      {
        "pattern": "确定性标准库 generator 与 drift gate",
        "example_location": "scripts/generate_message_flow.py:485; .github/workflows/ci.yml:191",
        "usage_guidance": "helper bodies/discovered entries 纳入；不在 CI 自动重生掩盖 drift"
      }
    ],
    "files_to_modify": [
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "_flow_key",
          "_flow_ingress_root",
          "_flow_ingress_end",
          "_flow_root_for",
          "_flow_root_or_create",
          "handle_private_chat",
          "_record_bot_lines"
        ],
        "intended_change": "身份/receipt ref/关键 transition/lifecycle，保持业务顺序"
      },
      {
        "file": "core/observability/message_flow.py",
        "symbols": [
          "FlowContext",
          "begin_trace",
          "_emit_event",
          "_Writer",
          "_group_by_trace",
          "_row_trace_id"
        ],
        "intended_change": "schema3/exact archive/owned root bundle/metadata update/transition/finality"
      },
      {
        "file": "core/observability/flow_catalog.py",
        "symbols": [
          "ENTRY_ROOTS"
        ],
        "intended_change": "私聊/固定节点、edge IDs、entry metadata"
      },
      {
        "file": "core/observability/internal_flow_catalog.py",
        "symbols": [
          "validate_inventory"
        ],
        "intended_change": "真实 hooks/边界 registry/独立 discovered 差集"
      },
      {
        "file": "scripts/generate_message_flow.py",
        "symbols": [
          "build_manifest",
          "content_hash",
          "reachable_symbols"
        ],
        "intended_change": "本地跨文件闭包/辅助体 hash/入口发现/确定性预算"
      },
      {
        "file": "core/observability/flows/message-flow.<digest12>.json",
        "symbols": [],
        "intended_change": "M6 一次正式生成 schema3 资源，禁止手改"
      },
      {
        "file": "core/social/contracts.py",
        "symbols": [
          "DeliveryReceipt"
        ],
        "intended_change": "追加规范身份与中立 receipt 合同"
      },
      {
        "file": "core/social/delivery.py",
        "symbols": [
          "deliver_lines",
          "_append_and_persist"
        ],
        "intended_change": "explicit receipt_conversation 与发送 transition"
      },
      {
        "file": "memory/social_schema.py",
        "symbols": [
          "ensure_social_schema"
        ],
        "intended_change": "social v1->v2 单事务增量列/索引，main memory v16 不变"
      },
      {
        "file": "memory/social_store.py",
        "symbols": [
          "record_delivery",
          "deliveries_for_turn",
          "find_delivery_by_platform_id"
        ],
        "intended_change": "canonical receipt/eligibility/scoped lookup"
      },
      {
        "file": "memory/reply_effect_service.py",
        "symbols": [
          "open_effect",
          "resolve_effect"
        ],
        "intended_change": "只接納匹配当前群身份/eligibility 的证据并传 scope"
      },
      {
        "file": "memory/expression_selector.py",
        "symbols": [],
        "intended_change": "群使用统计过滤中立行；执行前 impact 具体符号"
      },
      {
        "file": "memory/expression_learning.py",
        "symbols": [],
        "intended_change": "引用归因 scope 传递如实际调用需要；执行前 impact"
      },
      {
        "file": "webui/chat_ingress.py",
        "symbols": [
          "run_turn"
        ],
        "intended_change": "现有 record_delivery 补规范身份"
      },
      {
        "file": "core/runtime/facade.py",
        "symbols": [],
        "intended_change": "关键 runtime 分支 transition 与固定节点；不重建引擎"
      },
      {
        "file": "memory/session_compact.py",
        "symbols": [],
        "intended_change": "compact.commit 登记/真实派生关系"
      },
      {
        "file": "webui/services/flow.py",
        "symbols": [
          "spec",
          "message_io"
        ],
        "intended_change": "精确 digest/IO、keyset/watermark/finality，旧字段默认"
      },
      {
        "file": "webui/routers/trace.py",
        "symbols": [],
        "intended_change": "additive digest/cursor/until 参数与旧 API 兼容"
      },
      {
        "file": "dashboard/src/api/flow.ts",
        "symbols": [
          "FlowSpec",
          "FlowEvent",
          "FlowMessageIo",
          "MessageQuery"
        ],
        "intended_change": "additive schema3 types 与 API methods"
      },
      {
        "file": "dashboard/src/stores/flow.ts",
        "symbols": [
          "useFlowStore"
        ],
        "intended_change": "bundle refresh/分页/水位/代际/关联/加载状态"
      },
      {
        "file": "dashboard/src/stores/flowReducer.ts",
        "symbols": [
          "projectInstance",
          "projectNode"
        ],
        "intended_change": "span+attempt 生命周期、checkpoint semantics"
      },
      {
        "file": "dashboard/src/views/data/flowLayout.ts",
        "symbols": [
          "edgeTraversed",
          "layoutExecuted",
          "layoutLayered"
        ],
        "intended_change": "transition-only 高亮，无 spec fallback，真实终点"
      },
      {
        "file": "dashboard/src/views/data/FlowPage.vue",
        "symbols": [],
        "intended_change": "动态 root 标签/展开/源码闭包/关系对象导航/完整性提示"
      },
      {
        "file": ".github/workflows/ci.yml",
        "symbols": [],
        "intended_change": "closure discovered diff 和 manifest drift gate"
      },
      {
        "file": ".github/workflows/dashboard_ci.yml",
        "symbols": [],
        "intended_change": "完整 source path 触发与前端合同"
      },
      {
        "file": "inventory 对应 knowledge/scheduler/social worker/AstrBot/Cometa/lifecycle 源文件",
        "symbols": [],
        "intended_change": "依据真实入口锚点定点埋点；UNKNOWN 必须 source/registration 验证，不开展全模块重构"
      }
    ],
    "tests": [
      {
        "file": "tests/observability/test_flow_identity_binding.py",
        "status": "new",
        "scenarios": [
          "不同 Bot/peer/kind 同消息 ID -> roots/结束处理隔离",
          "同事件重复与缓存淘汰 -> 幂等或明确 partial"
        ]
      },
      {
        "file": "tests/observability/test_message_flow_integrity.py",
        "status": "existing",
        "scenarios": [
          "v1/v2->v3/重复迁移/故障回滚",
          "同 version A/B -> exact digest",
          "队列满/batch failure/per-trace retry -> owned prerequisite 与 per-run loss"
        ]
      },
      {
        "file": "tests/test_social_delivery.py",
        "status": "existing",
        "scenarios": [
          "保留 scope=None 无 ref 的 skip fixture",
          "显式 private ref -> 中立回执，纯标点/短文本/无 ID/部分发送事实准确"
        ]
      },
      {
        "file": "tests/test_social_migrations.py",
        "status": "existing",
        "scenarios": [
          "social v1->v2/重复/故障迁移/旧行 eligibility"
        ]
      },
      {
        "file": "tests/test_reply_effect_service.py",
        "status": "existing",
        "scenarios": [
          "私聊与群同 platform ID -> 不跨归因，不开群学习任务"
        ]
      },
      {
        "file": "tests/webui/test_message_flow_api.py",
        "status": "existing",
        "scenarios": [
          "私聊 exact input/output与command",
          "missing/legacy spec 不取 current，no content 列原因",
          "cursor/until/finality 跨页稳定"
        ]
      },
      {
        "file": "tests/test_private_chat_ingress.py",
        "status": "existing",
        "scenarios": [
          "shared runtime/插件接管/图片/预算拒绝/取消/partial send 原合同保留"
        ]
      },
      {
        "file": "tests/test_conversation_registry.py",
        "status": "existing",
        "scenarios": [
          "跨 Bot/peer 负 ID 注册隔离原合同保持"
        ]
      },
      {
        "file": "tests/observability/test_flow_source_closure.py",
        "status": "new",
        "scenarios": [
          "helper return/import/relative alias 变化 -> hash drift",
          "新增未声明 matcher/hook/worker -> inventory mismatch",
          "dynamic/Rust boundary/cycle/budget -> 诚实闭包状态"
        ]
      },
      {
        "file": "tests/observability/test_internal_flow_inventory.py",
        "status": "existing",
        "scenarios": [
          "真实 lifecycle anchors/固定节点/私聊入口发现差集"
        ]
      },
      {
        "file": "tests/observability/test_background_flow_roots.py",
        "status": "existing",
        "scenarios": [
          "idle 无 root，有任务/取消/错误/真实父子 relation"
        ]
      },
      {
        "file": "dashboard/tests/flow-reducer.spec.ts",
        "status": "existing",
        "scenarios": [
          "start->checkpoint 不 terminal",
          "不同 span 同 instance/attempt/乱序/terminal后checkpoint不覆盖"
        ]
      },
      {
        "file": "dashboard/tests/flow-layout-executed.spec.ts",
        "status": "existing",
        "scenarios": [
          "无 transition 兄弟节点不激活边",
          "跨 trace/attempt/fork/loop/legacy only -> 正确事实"
        ]
      },
      {
        "file": "dashboard/tests/flow-layout-layered.spec.ts",
        "status": "existing",
        "scenarios": [
          "静态未确认边样式、真实 root end"
        ]
      },
      {
        "file": "dashboard/tests/flow-store.spec.ts",
        "status": "existing",
        "scenarios": [
          "实时 IO empty->receipt->writer finality",
          "quick switch/旧 promise/SSE reconnect 不串",
          "list>100/events>100k/页上限 -> partial+continue"
        ]
      },
      {
        "file": "dashboard/tests/flow-page.spec.ts",
        "status": "new",
        "scenarios": [
          "no spec/unknown root/展开全部/对象与关系导航；DOM runner 如需要须单列依赖"
        ]
      },
      {
        "file": "dashboard/tests/perf-10k-layout.spec.ts",
        "status": "existing",
        "scenarios": [
          "实际 manifest +10k events <5s 宽门槛，报告p50/p95",
          "100k事件增量水位/窗口化规模验证"
        ]
      }
    ],
    "verification_commands": [
      "python -m pytest tests/observability tests/webui/test_message_flow_api.py tests/test_private_chat_ingress.py tests/test_conversation_registry.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_reply_effect_service.py -q",
      "npm --prefix dashboard test",
      "npm --prefix dashboard run typecheck",
      "python scripts/generate_message_flow.py",
      "python scripts/generate_message_flow.py --check",
      "npm --prefix dashboard run build",
      "npm --prefix dashboard run sync:webui",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs analyze --index-only --pdg",
      "docker exec -w /repo stella-gitnexus node .gitnexus/run.cjs detect-changes --scope all --repo ."
    ],
    "verification_command_notes": "pytest/npm/generator/build/sync 是已核验存在的入口；新用例实施后再运行。正式 generator 默认生成仅 M6 一次。真实账号/安装包结果不由这些命令替代。每次符号改前另外调用 impact；提交前 graph check 非 partial/truncated。",
    "risks": [
      "CRITICAL _flow_key/begin_trace/_emit_event; full upstream d1 见第9节",
      "archive prerequisite 与 root 分组重试错序",
      "中立私聊 receipt 经共享表泄漏到群学习/引用归因",
      "历史 empty digest/identity 被伪补 exact",
      "诊断热路径与跨文件 closure 扫描开销",
      "producer end/late writer/SSE/browser loading 竞态",
      "缺 spec/分页阈值让页面假完整",
      "用户既有 Laya untracked 计划不可 stage/修改"
    ],
    "assumptions": [
      "以官方 schema2 snapshot 比较 HEAD/global dirty/cited bytes；变动则只重验相关工作包",
      "读取真实数据库 flow/social/main memory 的列/版本确认迁移起点，故障测试用复制库",
      "执行前 graph+rg 检查 memory_rust 无 social_deliveries 消费；main memory 合同如变须补 Python/Rust 对称迁移",
      "复核现有 Dashboard 鉴权/历史正文保留边界，并做私聊越权测试",
      "核验 Python/npm 依赖；新页面 DOM runner 不是既有依赖，需明确锁文件变更"
    ],
    "open_questions": [
      "真实 QQ 测试账号/adapter、桌面与最终发行环境是否可用；不可用则明确现场待验收",
      "非核心 dynamic boundary 尚未解析的逐项清单在 M4 输出；不能因此标全系统闭合"
    ],
    "avoid": [
      "Do not repeat full repository discovery",
      "Do not replace established patterns without evidence",
      "不实施第二套聊天/记忆引擎，不改8K模型上下文或部署配置",
      "不改变 private/group memory audience 授权，不把 private storage ID 当群号",
      "不伪回填旧 root spec_digest，不 fallback current spec 冒充 exact",
      "不从节点时间顺序或同 instance_key 推断实际边",
      "不删除 scope=None 无 ref skip 测试，不让中立 receipt 学习/归因",
      "不将 acknowledged 与 receipt persistence 合并，不因丢档重发",
      "不在热路径 synchronous flush/全文件 hash/逐语句埋点",
      "不在所有源码改变前重复正式 manifest regeneration；中间 WIP 不合并",
      "不手改生成 JSON、不将页数阈值标 complete、不取消旧 loss/unknown/脱敏能力",
      "不修改或 stage 用户既有 Laya 计划，不自称已真实 QQ 或安装最终EXE验证"
    ],
    "impact_summary": [
      {
        "symbol": "_flow_key",
        "risk": "CRITICAL",
        "impacted_count": 12,
        "direct_count": 4,
        "depth_counts": {
          "1": 4,
          "2": 5,
          "3": 3
        },
        "processes_affected": 5,
        "epistemic": "exact"
      },
      {
        "symbol": "begin_trace",
        "risk": "CRITICAL",
        "impacted_count": 161,
        "direct_count": 71,
        "depth_counts": {
          "1": 71,
          "2": 59,
          "3": 31
        },
        "processes_affected": 11,
        "epistemic": "exact"
      },
      {
        "symbol": "_emit_event",
        "risk": "CRITICAL",
        "impacted_count": 207,
        "direct_count": 6,
        "depth_counts": {
          "1": 6,
          "2": 87,
          "3": 114
        },
        "processes_affected": 15,
        "epistemic": "exact"
      },
      {
        "symbol": "edgeTraversed",
        "risk": "LOW",
        "impacted_count": 10,
        "direct_count": 1,
        "depth_counts": {
          "1": 1,
          "2": 2,
          "3": 7
        },
        "processes_affected": 0,
        "epistemic": "exact"
      },
      {
        "symbol": "build_manifest",
        "risk": "LOW",
        "impacted_count": 6,
        "direct_count": 3,
        "depth_counts": {
          "1": 3,
          "2": 1,
          "3": 2
        },
        "processes_affected": 0,
        "epistemic": "exact"
      }
    ],
    "implementation_sequence": [
      "M0 锁定失败回归",
      "M1 完整 identity + schema3/spec owned binding",
      "M2 social v2 + explicit 中立 receipts + exact IO + learning guards",
      "M3 transition/attempt/span + reducer/layout",
      "M4 closure/discovery/catalog/background lifecycle",
      "M5 bundle refresh/pagination/watermark/fallback/navigation",
      "M6 一次生成/check/tests/build/sync/real acceptance/graph check"
    ]
  }
}
```

## 12. Assumptions and Open Questions

- [assumed] 执行起点仍为以上 HEAD/工作树；用第 11 节 provenance 比较确认。当前另有未跟踪 Laya 计划与本复核报告，均纳入 dirty 摘要。
- [assumed] 当前 receipt social 组件 v1、主 memory v16、flow schema2；执行前读取实际库版本/列，不能用源码常量代替用户库状态。不得直接在真实库试验故障迁移，先复制库。
- [assumed] Rust 无 social_deliveries 消费，本任务只变 social 组件与 flow 旁表；执行前 graph + `rg social_deliveries memory_rust -g '*.rs'` 复核，若产生主 memory 合同变化，暂停该工作包、补 Python/Rust 迁移而非单边修改。
- [assumed] 生产 retained message/receipt 原文可由现有 Dashboard 鉴权访问；执行时以现有 token/用户边界做私聊 API 越权测试，不扩大读取权限。
- [assumed] npm/项目 Python 依赖与本轮复核环境保持可运行；新 DOM runner 尚未存在，必要时明确安装/锁文件变更及理由。
- [inferred] 本计划已作实施选择：digest 精确归档、历史不伪回填；私聊显式 ref 启用中立回执，scope=None 无 ref 保留跳过；关键边 transition 逐步补齐；未解析/预算截断如实 partial。无需再次请用户选择架构方向。
- [inferred] 唯一外部验收条件是可用的测试 QQ 账号、adapter 与桌面/发行环境。若没有这些条件，仍完成隔离测试/构建，但交付标为“代码验证完成，现场验收待执行”，列未完成 case；不能假称已发真实消息或安装最终 EXE。
- [inferred] closure scanner 的非核心动态边界可能持续 unresolved。M4 需输出逐项清单与真实 registry 锚点；关键消息闭包不得留未解释内部节点。全系统指标只能标部分闭合，直到声明范围的所有入口差集/内部缺档关闭。

## 13. Definition of Done

1. R1–R9 均有通过的新增回归或明确现场证据，未完成项逐条列出。
2. 私聊/群聊/多 Bot 的 root、input、output、结束处理不串线；storage session 来自可信 ref；旧身份不伪造。
3. 新 root 的 spec_digest 为 full64、归档不可变、同 version A/B 可精确回放；旧空 digest 显示 legacy_unverified；spec missing 时事实仍可见。
4. root/spec/start 同一 owned transaction 单元，队列满/写失败/per-trace fallback 不产生假完整；业务发送不被诊断故障改变。
5. 仅合法 transition 激活实际边，attempt/span/fork/loop 不串；所有 static_only 边明确未确认；root 结束依据真实终态与 finality。
6. checkpoint 不结束 active span，独立 span/attempt 不合并生命周期，原 unknown/loss/cancel 能力保留。
7. 私聊确认发送、部分失败、无平台 ID、短文本/纯标点、命令回执可查；没有正文时准确标不可用；中立回执不参与群学习/引用归因。
8. 辅助函数与本地跨文件调用变化可使 closure hash/drift 改变；独立扫描发现清单外入口；核心四个截断收口；未闭合区域不显示完整。
9. 固定语义节点已登记、真实内部族与 lifecycle 有事实/测试；静态目录与实际因果关系分开。
10. IO/detail/关系/对象在 receipt/终态/手动刷新后更新；迟到回包与 SSE 不跨 trace 污染；writer 晚提交尾部仍可加载。
11. 列表 >100 条、事件 >100k/页数上限、无 spec、全文/metrics 展开均诚实表达 loaded/pending/partial；不得把浏览器已载数量解释为存储总量。
12. 相关轨迹/对象导航工作；鉴权/会话边界保持，原诊断脱敏不退化。
13. 标准库生成器、Python 合同/迁移测试、Dashboard tests/typecheck/build 与必要 CI 全通过；正式 manifest 仅在全部源变更完成后生成一次并 --check 通过。
14. WebUI/桌面快照同步且实际页面加载新 JS；QQ 测试账号验收与最终发行包验收的完成状态分别给证据。
15. 每个符号编辑前有 impact；提交前 detect_changes 非 partial/truncated；保留 HIGH/CRITICAL 风险与动态/跨语言限制说明，不把零调用者当安全结论。
16. 最终变更/测试报告明确改了什么、验证范围、剩余风险；不改用户已有 Laya 计划、私人记忆权限或模型部署配置。