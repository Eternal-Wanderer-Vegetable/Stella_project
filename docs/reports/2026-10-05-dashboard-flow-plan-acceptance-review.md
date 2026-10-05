# Review: Dashboard 消息工作流修复计划验收

日期：2026-10-05。结论：**NOT READY，原计划尚未全部完成。**

验收对象：[2026-10-04 修复计划](E:/stella/stella_project/docs/plans/2026-10-04-gitnexus-plan-dashboard-flow-completeness-repair.md)。计划经原 evidence helper 解码复读，正文 SHA-256 为 `3d17519f3c8d25fc7c15ca8e4be765df8cc7a77b7e9e6033b128771b88fee96c`，113741 字节、13 节。以下把本次变更中的缺陷、原计划仍未兑现的合同、现场证据不足分别说明。没有实施修复。

## Findings

### H1 [HIGH / P1] 真实私聊 ConversationRef 无法进入中立回执持久化

[delivery.py:270](E:/stella/stella_project/core/social/delivery.py:270) 读取 `receipt_conversation.conversation_kind`，而 [ConversationRef:68](E:/stella/stella_project/core/conversation.py:68) 的实际字段是 `kind`。[私聊发送入口:1627](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:1627) 传入真实 ref；字段缺失使 277–280 清空规范身份，`scope=None` 时 `neutral=False`，不执行 `record_delivery`。

隔离探针使用真实 `qq_private_ref` 和假发送器，发送得到 acknowledged，但 `receipt_key=''、receipt_kind=''、persistence_calls=0`。当前中立回执测试用 `SimpleNamespace(conversation_kind='private')`，因此未覆盖生产数据类型。真实库最近 20 条已结束私聊也全部出现“成功发送、无回执、output=0”，详见数据库证据。阻断 R1、DoD 2/7。

修复要求：显式使用真实 ConversationRef 的序列化合同，保留平台/Bot/会话身份；增加真实工厂对象经过 `deliver_lines → record_delivery → message_io` 的集成用例。修复时应一并补全 [social_store.py:87](E:/stella/stella_project/memory/social_store.py:87) 中立行目前从空 scope 取出的空 platform/bot_id。已经发送的消息不得重发；历史无可信正文关联时应明确缺档。

### H2 [HIGH / P1] exact 输入查询仍可跨 Bot 取正文

[flow.py:665](E:/stella/stella_project/webui/services/flow.py:665) 只用 `group_id、msg_id` 取最新非 BOT_SELF 行，没有 trace 的 `conversation_key/bot_id` 谓词，`conversation_kind` 参数也未使用。[群入口:1160](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:1160) 的 storage_session_id 仍直接等于群号。

临时数据库同时放两个 Bot 的同群同号消息，针对第一台 Bot 的 trace 调用 `message_io`，返回第二台 Bot 的正文及用户，并标成 `identity_state='exact'`。这是确定的隔离探针结果；本轮没有把它称为真实多 Bot 线上事故。阻断 R2 和 DoD 2。

修复要求：向输入查询传完整 trace identity，并验证业务行的 canonical conversation/Bot；旧行身份不足时返回保守状态。增加同 storage、同 msg_id、不同 canonical conversation 的反例。

### H3 [HIGH / P1] “加载更早”向较新方向查，offset 兼容也失效

[flow.py:123](E:/stella/stella_project/webui/services/flow.py:123) 的 cursor 谓词是 `started_utc > cursor`，查询却按时间及 trace_id 降序排列。因此下一页回到首屏较新记录；SQL 也未使用仍被 API 接受的 offset。total 又把 cursor 条件计入，失去同一过滤查询的总数含义。

五条临时轨迹 t1–t5：首屏 limit=2 为 `[t5,t4]`，下一页实际 `[t5]`，应为 `[t3,t2]`；offset=2 仍是 `[t5,t4]`；两页 total 为 `[5,1]`。浏览器的“加载更早”也没有展示更早记录，但稳定结论以临时库探针为准。阻断 R8。

修复要求：降序 keyset 使用严格小于，保存查询快照上界；明确 total 的查询范围；保留 offset 兼容，并加入并发插入、同时间不同 ID、取尽的回归。

### H4 [HIGH / P1] 全局 row_id 与 trace 的 seq 水位混比，超过软上限后继续加载被隐藏

[flow.ts:361](E:/stella/stella_project/dashboard/src/stores/flow.ts:361) 和 381–385 用 `maxRowId(events) < persisted_events` 判断剩余数据。[writer:599](E:/stella/stella_project/core/observability/message_flow.py:599) 实际将该 trace 的 `MAX(seq)` 写入 persisted_events；row_id 是整张 flow_events 的全局自增 ID，二者单位不同。persisted_events **也不是 COUNT(*)**。

前端隔离探针放 100001 条事件、trace seq 水位 100001、全局 row_id 从 100001 开始。100 页后已载 100000 条、max row=200000，但 `eventsTruncated=false`，再调用 loadMoreEvents 不发请求。[页面:1271](E:/stella/stella_project/dashboard/src/views/data/FlowPage.vue:1271) 因此不显示继续按钮。interrupted 历史轨迹不会开启 SSE，无法自动补齐。现有 fixture 的 seq/count/row_id 数值相同，掩盖了单位错误。阻断 R8、DoD 11。

真实最新私聊实际有 71 条 flow_events、MAX(seq)=123、persisted_events=123；当前“已载 71 / 存储 123”也不能解释成缺失 52 条事件。修复要求：API 明确区分事件数量、全局分页游标、trace seq 和快照水位；分页返回是否还有数据，UI 不再跨单位比较。

### H5 [HIGH / P1] 手动刷新不再补读事件，晚提交尾部无法恢复

[FlowPage.vue:803](E:/stella/stella_project/dashboard/src/views/data/FlowPage.vue:803) 把原先 fetchEvents 改成 refreshTraceBundle；[flow.ts:290](E:/stella/stella_project/dashboard/src/stores/flow.ts:290) 的 bundle 只查 detail、IO、entities，不查询 events。

前端隔离探针先载 1 条事件，随后 detail 提升水位至 2；点击对应 action 后仍 loaded=1，eventCalls=0。停止直播、断线后的已结束轨迹、writer 晚提交均不能靠刷新补齐；truncated 也不重新计算。阻断 R6/R8。

修复要求：手动刷新包含冻结水位后的事件补读，收尾刷新应等待可确认的 writer finality 或显示 pending/unknown。终帧单次刷新后停止在基线已存在；本计划承诺的有界 finality 重试仍未实现，不能把全部终帧问题都称为新引入回归。

### M1 [MEDIUM / P2] transition 未匹配端点 occurrence/span

[flowLayout.ts:532](E:/stella/stella_project/dashboard/src/views/data/flowLayout.ts:532) 只核节点及 attempt，没有核 edge_id、from/to span、instance。隔离探针给实际端点 a-real/b-real，但 transition 指向 a-other/b-other，全部 attempt=0，结果仍 `wrongOccurrenceAccepted=true`。同节点重复执行时会借别的 occurrence 事实点亮边。当前真实 manifest 没有平行同端点边，本结论不依赖平行边事故。阻断 R3、DoD 5；需按实际端点身份匹配，并补同 attempt 不同 span 反例。

### M2 [MEDIUM / P2] 同 trace 旧 bundle 可覆盖终态，列表异步请求也没有查询代际

[flow.ts:297](E:/stella/stella_project/dashboard/src/stores/flow.ts:297) 的 bundle 仅检查 traceGeneration 和 trace_id。同 trace 第一次请求挂起，隐藏页面增加 streamSession、第二次请求得到终态，随后旧响应返回，会把 ended 清空并将 persisted 水位降回 1。需要 session 及请求代际或单调水位约束。

[flow.ts:196](E:/stella/stella_project/dashboard/src/stores/flow.ts:196) 首屏轮询直接替换累积列表，已加载的历史页在下一次 5 秒轮询消失；219 的 loadMore 还可在过滤已切成 WebChat 后追加旧 QQ 页并覆盖 cursor/total。隔离探针均已重现。需对每个过滤查询使用代际，并合并新首屏、保留历史累积页。阻断 R6/R8。

### M3 [MEDIUM / P2] 新入口发现门禁漏掉带参数装饰器和 worker 注册

[generate_message_flow.py:687](E:/stella/stella_project/scripts/generate_message_flow.py:687) 不展开 `ast.Call.func`，所以 `@scheduler.scheduled_job(...)`、`@matcher.handle()` 不被识别；696–704 只查赋值，不查表达式注册。临时源码加 scheduled_job 和 queue.register_handler 后，discovered/undeclared/missing 均为空，门禁仍可通过。

实际 gateway 有多处 scheduled_job；[social_worker.py:324](E:/stella/stella_project/memory/social_worker.py:324) 有 register_handler。需覆盖真实入口形状及删除注册、保留函数的反向测试。阻断 R4、DoD 8。

### M4 [MEDIUM / P2] 导入别名的 helper 被漏算，内部 AstrBot 与 native 边界也未进入有效漂移合同

[generate_message_flow.py:191](E:/stella/stella_project/scripts/generate_message_flow.py:191) 丢失导入原名；548–550 对不存在的 local helper 静默跳过。临时 fixture `normalize as transform` 在 helper 函数体 `v+1 → v+2` 后，symbols/boundaries 仍空、truncated=false、closure_hash 不变。实际 participation 的 `extract as extract_signals` 被写成不存在的 `signals.py#extract_signals`，真实 `extract` 不在闭包内。

[PackageIndex:390](E:/stella/stella_project/scripts/generate_message_flow.py:390) 漏掉仓库内 astrbot_compat，实际 handle_plugin 的 dispatch 被列成 external，manifest 的该目录 helper/source 数量为 0。557 的跨语言记录和 856 的 inventory 边界只有名称/路径，没有计划要求的源码/配置/合同 hash；临时 Rust 返回值 `1 → 2` 后 closure 整体不变。

需保留 import 原名、解析模块别名、不存在的 local callee 显示 unresolved；仓库内模块不能归 third-party external；native/config/contract 锚点进入确定性摘要并加入 drift 测试。阻断 R4、DoD 8。这些是具体失败形状，不以“图中零 callers”论证遗漏。

### M5 [MEDIUM / P2，未完成合同] 生命周期只有静态锚点，页面也未展示源码闭包

[internal_flow_catalog.py:161](E:/stella/stella_project/core/observability/internal_flow_catalog.py:161) 的五个 startup/shutdown entry root_kind 为空。实际 [启动函数:2672](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:2672) 和 [关闭函数:4042](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:4042) 无 flow/trace 调用；安全 AST 抽取启动函数执行只观察到 runtime.start，没有 begin_trace。原十个孤岛仍度为零，新增 flow.ingress 后共十一孤岛。不能用真实函数锚点代替运行事实。阻断 R7、DoD 9。

manifest 已有 source_ref/source_closure/coverage，但 API 前端类型与页面没有消费这些字段，节点卡无法查看源码闭包及未解析边界。[FlowPage.vue:661](E:/stella/stella_project/dashboard/src/views/data/FlowPage.vue:661) 入口过滤仍固定 9 项，manifest entry_roots 有 19 项。需完成生命周期成功/失败/取消/停止事实、动态入口选项及闭包视图。这些标为原计划剩余合同，不作为本次新引入故障。

### M6 [MEDIUM / P2，未完成合同] 输出片段事实、缓存重入与 Flow 迁移恢复仍不满足计划

- [flow.py:529](E:/stella/stella_project/webui/services/flow.py:529) 只返回 acknowledged 正文，没有原 part_index/status 事实；0 ack A / 1 failed B / 2 ack C 返回 `[A,C]`。全部失败时 627–630 又丢掉具体失败说明。命令输出仍走 command.reply checkpoint 的摘要路径。需保留原片段序号、failed/unknown 及持久化状态，并提供完整正文合同。对应 DoD 7。
- [ai_gateway.py:452](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:452) root 缓存淘汰后同事件重入，不复用 active source root；487 的结束只比较 conversation key。领域探针“创建→淘汰→重入→迟到结束”产生第二 root，旧 root 未结束，替换 root 被迟到结束关闭。需 occurrence token 的 compare-and-pop。对应 DoD 2。
- [message_flow.py:388](E:/stella/stella_project/core/observability/message_flow.py:388) schema CREATE/ALTER/index 迁移无显式单事务/迁移前备份。临时 v2 库注入晚期 index 错误，连接返回 None，但新 identity 列及 blob 表已保留且无 backup。Social 迁移已有事务，不能代替 Flow 迁移恢复。对应 §6.2。这一无事务模式基线已存在，属于本计划未兑现合同。

## Change and blast-radius summary

精确比较 `6d73b9f70bd3797cb97af88a999bc59d9582cdcf..33a34f326ac87f1d66271a13945a061610830399`；当前分支 `feat/dialogue-attribution-role-repair`。比较中包含后续归因修复，只将与 Dashboard 计划合同相关的内容纳入本报告。全范围 93 个文件，616 个 changed symbols、95 个 affected processes；detect_changes 没有 partial/truncated 标记。remote 默认分支 origin/main；本验收使用原计划基线的两点比较，而非用 main 范围替换目标。

Docker stella-gitnexus 在 /repo 刷新 `analyze --index-only --pdg` 成功，lastCommit 对齐上述 HEAD，indexedAt=`2026-10-05T00:00:57.006Z`，87,239 nodes、211,475 edges、945 communities、831 sampled flows。GitNexus 1.6.11 / Node 22.23.2。官方 LocalBackend 完成 context、impact、detect_changes、explain、PDG；原始结果在容器 `/tmp/stella-flow-acceptance/`。

共享入口影响风险较高：begin_trace 176 个上游影响、_emit_event 211、transition 48、record_delivery 46；这些数字说明验证范围，不作为缺陷证据。fetchEvents、refreshTraceBundle 因对象属性调度返回 UNKNOWN，使用当前源代码及隔离探针补证，未按“零 callers”判安全。explain 四个数据边界没有返回 taint finding，但不证明跨 Bot 的业务身份隔离正确。

分析器流程抽样存在入口排名/深度/预算截断；大生成 JSON 不进入普通符号索引，另直接解析 manifest。PDG 确认 delivery 的身份守卫与 discovery 的扫描分支；messages 的 PDG 名称歧义没有当作成功切片。没有源码编辑，故本次不涉及 pre-edit 或 commit gate；本次图验证不能追溯证明每个历史实施步骤都执行过 impact。

## Coverage and residual risk

### 本轮实际重跑的检查

| 检查 | 结果 | 能证明的范围 |
| --- | --- | --- |
| Python 观测/API/私聊注册表/发送/social migration/effect 相关组合 | 203 passed，58 warnings | 现有用例通过，不覆盖上述全部反例 |
| Dashboard Vitest | 6 files、85 tests passed | 现有 reducer/store/layout 合同 |
| Dashboard typecheck | 通过 | 类型检查 |
| Dashboard build | 通过，写入系统 Temp 外部目录 | 当前 HEAD 可生产构建；存在既有 chunk/dynamic-import 提示 |
| generate_message_flow.py --check | 通过 | 当前生成内容一致，文件 message-flow.619c34f1f487.json |
| 重新构建 vs dashboard/dist、webui/dist、desktop/dashboard-dist | 三处各 50 文件，逐文件 SHA-256 完全相同 | 当前已同步目录与本次构建一致；不是安装包验收 |
| 后端隔离探针 | 真实 ref 无回执、跨 Bot exact 输入、片段事实丢失复现 | 假 adapter/临时 SQLite，没有真实发送 |
| 列表隔离探针 | 更早 cursor 与 offset 失败复现 | 临时 SQLite |
| 前端补充探针 | 7 个错误形状复现，1 个 R9 正向成立 | 临时 Vitest；8/8 指探针断言成立，不是产品八项通过 |
| 闭包/入口隔离 fixture | 装饰器、worker、别名、native 漂移漏报复现 | 临时源码目录 |

Python 命令：`python -m pytest tests/observability tests/webui/test_message_flow_api.py tests/test_private_chat_ingress.py tests/test_conversation_registry.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_reply_effect_service.py -q`。前端命令为 `npm --prefix dashboard test`、`npm --prefix dashboard run typecheck`、`npm --prefix dashboard run build -- --outDir C:/Users/Vegetable/AppData/Local/Temp/stella-flow-acceptance-build`。没有重新同步或覆盖运行中的静态目录。

主 JS `assets/index-XixPgrei.js` SHA-256 为 `878a14da11c7e4c2219f60f4fe8aab31543797c1fca42a3f70b0f861050fcd2c`。当前 manifest 为 139 nodes、136 edges，其中 22 explicit、114 static_only；36 declared entries、16 discovered entries。四个原预算截断核心节点各有 142 helpers，两种截断标记均 false。这部分确实改善，但 explicit/static 数量不能换算成系统覆盖率。

### 真实数据库与浏览器证据

经用户授权，只读 `StellaData/turn_trace.db` 与 `StellaData/memory/agent_memory.db`，连接使用 URI mode=ro、PRAGMA query_only=ON 和读事务。没有运行迁移或写入真实库。查询时根轨迹共 40,274 条，qq_private 101 条；后台运行会继续增加数量。业务库主 schema=16，social 组件=2。

抽样规则：message_traces 中 root_kind='qq_private' 且 producer_ended=1，按 started_utc DESC 取最近 20 条。时间范围为 **2026-10-05 02:41:13–07:24:37（UTC+8）**，源时间为 2026-10-04T18:41:13.430+00:00 至 23:24:37.151+00:00。

20/20 均带规范 conversation_key、绑定当前 619c… digest、outcome=delivered、integrity=complete；每条有 3 个 send.segment finish/succeeded。social_deliveries 按 trace_id 的行数全部为 0，message_io 的 input 均存在但 output.count 全部为 0。正文、账号和会话 ID 不写入本报告。

最新样本 trace 前缀 `138344040bb0`：71 条 flow_events，row_id 范围 488096–488301，MAX(seq)=123，persisted_events=123。数据库“complete”只表达观测 writer 当前完整性合同，不能证明回执存档或业务输出完整。浏览器现有 `http://127.0.0.1:8080/#/data/flow` 中查看这条轨迹，确实显示已送达但 output 无；输入、轨迹及关联 compact 可见。

未向真实 QQ 发送测试消息。真实库验证了私聊的一种实际失败路径，**没有覆盖**命令、全部拒绝/异常、跨 Bot 冲突、完整并发/finality 场景，也没有证明桌面壳实际加载及导航全部正确。用户明确说明安装包尚未验收，因此安装包验收直接记为未完成。

补充操作边界：一个领域探针直接 import gateway 时触发模块初始化，日志有消息统计读取及用量记账初始化；随后观测 writer 使用临时库，没有调用模型或实际发送。该导入未完全隔离，不能笼统称本轮所有探针都无初始化副作用；已停止重复导入。正式源码、配置、测试、manifest 和真实消息库未被本轮修复或迁移。

### R1–R9 验收矩阵

| 原项 | 结论 | 已实现 | 未关闭 |
| --- | --- | --- | --- |
| R1 私聊/固定节点/标签 | 部分完成，阻断 | 私聊 root/身份、固定节点与标签已接入 | H1 私聊确认输出无法存档，片段/命令全文合同不足 |
| R2 root 键碰撞 | 部分完成，阻断 | 常规 Bot/kind/peer/message 键隔离 | H2 exact 输入跨 Bot；缓存淘汰重入 occurrence 未隔离 |
| R3 实际连线 | 部分完成 | 无 transition 不亮边、跨 attempt 已限制 | M1 同 attempt 不同 span 被串接；finality 未满足 |
| R4 闭包/入口门禁 | 部分完成，阻断 | 跨文件 helper hash、核心预算截断已解除 | M3/M4 真实入口、别名、内部包、native/config 合同漏检；页面不可见 |
| R5 spec 归档/绑定 | 核心合同通过，剩余项未验收 | full64 digest、不可变 blob、owned bundle、旧/缺失明确降级 | Flow 迁移回滚；实际 loader 同版本多文件挑选与缓存合同缺有效反例 |
| R6 实时 IO | 部分完成，阻断 | receipt 节流、detail/IO/entities bundle、跨 trace 代际 | H5 事件补读丢失、M2 同 trace 旧响应覆盖、终态重试缺失 |
| R7 内部/背景导航 | 部分完成 | 关系和对象履历接口/入口已接入 | M5 生命周期事实和原孤岛未收口；实际页面导航矩阵未完整验收 |
| R8 截断/分页/全文 | 部分完成，阻断 | 更多按钮、缺 spec 节点回退、metrics/输出展开 | H3/H4/H5、列表代际、快照后续页、命令完整正文和实规模性能 |
| R9 checkpoint 终态 | 本轮核心合同通过 | 按独立 span 投影，checkpoint 不结束，乱序/同 instance 不同 span 处理成立 | 无本轮阻断发现；仍受整体验收范围限制 |

R5 当前 loader 实际挑中 619c…，生成器 check 也通过；不会据此报告“当前绑定了错误 spec”。但它仍按 filename 排序选第一份并按 version 缓存，现有 A/B 测试替换整个 loader，未证明真实多文件/缓存更新合同。

### 工作包与 DoD

| 工作包 | 验收结论 |
| --- | --- |
| M0 回归夹具 | 部分完成；现有用例增加，但真实 ref、同 canonical 冲突、同 attempt span、全局 row 偏移、入口/别名/native 反例缺失 |
| M1 身份/spec | 主要结构落地；缓存重入和 Flow 迁移恢复仍阻断 |
| M2 中立回执/IO | 未通过；真实发送→存档断点已被真实库证实 |
| M3 transition/reducer | reducer checkpoint 合同通过，transition 端点身份未通过 |
| M4 闭包/入口/生命周期 | 未完成；门禁漏报与运行事实缺失 |
| M5 store/分页/UI | 未通过；分页、补读、异步代际、水位及闭包展示仍缺 |
| M6 CI/部署/现场验收 | 当前自动门禁和目录资产一致性通过；QQ 全矩阵、桌面实际加载、最终安装包未完成 |

| DoD | 状态 | 判断依据 |
| --- | --- | --- |
| 1 R1–R9 与现场证据 | 未完成 | 上述阻断及现场缺口 |
| 2 身份隔离/输入输出/终态 | 未完成 | H1/H2、缓存重入 |
| 3 full64 spec/A-B/legacy/missing | 核心通过、loader 剩余合同待补证 | 精确 digest API 有效，真实文件挑选未充分验证 |
| 4 owned transaction/per-run fail-open | 主要实现有支持，完整失败矩阵待补证 | owned bundle 落地；不可把成功测试当全部故障注入验收 |
| 5 明确 transition/occurrence/finality | 未完成 | M1、终态补读 |
| 6 checkpoint/span 状态 | 通过本轮复核 | R9 正向及现有测试 |
| 7 私聊/片段/命令回执与不学习 | 未完成 | H1、中立身份字段、片段/全文合同 |
| 8 helper/入口/边界漂移可见 | 未完成 | M3/M4，页面无闭包视图 |
| 9 固定内部节点/生命周期事实 | 未完成 | 静态锚点已换，运行事实缺失 |
| 10 收尾/手动/IO/关系更新与无竞态 | 未完成 | H5/M2 |
| 11 分页/超长轨迹/加载状态 | 未完成 | H3/H4、冻结水位只用于首个请求 |
| 12 导航/auth/脱敏 | 部分验证 | 源码入口及既有 API 用例；未完成真实浏览器/桌面交互矩阵 |
| 13 tests/type/build/CI/gen | 当前指定命令通过，计划验证范围仍不全 | 失败形状、页面 DOM、真实 manifest 100k/p50/p95 未覆盖 |
| 14 资产/真实 QQ/发行包 | 资产通过、整项未完成 | 三目录与 fresh build 完全一致；QQ/桌面/安装包缺口 |
| 15 GitNexus gates | 本轮图验证通过；历史逐编辑执行未追溯确认 | 不替历史实施流程背书 |
| 16 诚实交付/范围边界 | 状态需更新 | 旧实施报告正确保留现场待验，但未列本轮查出的源码缺口；其他功能不在本次验收范围 |

当前页面没有 DOM 交互回归文件；10k 性能用例是 12 节点合成目录，不包含真实 manifest 的 100k 增量、p50/p95。冻结水位目前只在第一页传 until，后续传 0；隔离输入快照水位 1500、第二页读到 2000，违反稳定快照合同。终帧 detail 请求 transient failure 后，60 秒内没有 finality 重试。

## Verdict

**NOT READY。** 可以验收“主要结构已经落地，指定自动测试和资产同步通过”，不能验收“原计划全部完成”或“Dashboard 完整呈现真实代码行为”。安装包未完成只是其中一项；目前还存在真实数据可证实的私聊输出缺档及多个代码合同失败。

建议执行顺序：先关闭 H1/H2/H3，再处理 H4/H5 与 M1/M2；补齐 M3/M4 门禁及 M5/M6 剩余合同后，重跑指定门禁和失败反例，进行真实 QQ 全场景、浏览器/桌面导航、最终安装包验收。每项完成需留下 trace/digest/水位/输出片段证据，并更新实施报告；不要通过删掉原验收项把范围改成已完成。

本轮新增本报告；未改业务源码、正式测试、配置、生成 manifest，未提交。既有未跟踪 `.bot-restart.log` 和 Laya 计划保留。
