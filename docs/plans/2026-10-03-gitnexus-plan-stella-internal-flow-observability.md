# GitNexus Engineering Plan：Stella 内部流程观测与数据集验证

> Task：复核消息流程展示旧计划的完成度；进一步设计基于源代码的内部流程 Dashboard，覆盖记忆晋升、主动发言及后台生命周期，支持调试和真实聊天数据集稳定性验证。
> 状态：**工程计划，尚未实施**。本轮仅刷新索引、读取代码、运行现有测试和隔离探针、编写本文件；未修改业务代码、配置或生产数据库。
> Evidence verified at HEAD `4b089b5106f3b1945200058cad4047e7ca1cc221`，分支 `feat/cometa-agent-task-layer`；旧计划证据基线 `e7cf4f3166d898310279de43cfa89a0c1d0b0aaf`。
> Docker GitNexus：本轮首先成功执行 `docker exec stella-gitnexus sh -lc 'node .gitnexus/run.cjs analyze --index-only --force --pdg'`；刷新完成 UTC `2026-10-03T00:59:24.916Z`，耗时约 151 秒。
> Evidence provenance schema 2：global dirty digest `ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf`；59 个排序的引用路径均 clean；只排除本文件精确路径。完整快照见 §11。
> 证据标签：`[verified]` 当前源码/测试/探针；`[graph]` GitNexus/PDG；`[inferred]` 从证据推导的设计；`[assumed]` 待实施前确认。文中“建议/新增/拟”均表示拟实施合同。

## 1. Objective

[inferred] 将 Dashboard 的数据页面演进为内部流程控制台。用户能够回答：某条消息为何被忽略/触发回复；某候选为何观察、晋升、冲突或过期；Stella 为何主动说话或保持沉默；发送是否确认；后续学习/记忆/任务发生了什么；在同一数据集上升级前后哪里发生行为变化。

[inferred] 完整度的定义是“已声明运行入口的源码可达业务闭包，每个调用、条件、异常、返回、事务、异步分叉和状态变化都有目录归属或明确边界说明”。静态目录完整度、运行观测完整度、数据集覆盖度必须分别报告，任何一个不能冒充其他两个。

[inferred] 本计划范围包含消息/Turn、整合与记忆、主动决策与发言、回复效果与社交学习、后台维护、预约任务、知识导入/索引相关运行、Cometa 已有任务运行，以及这些流程使用的模型/工具/队列/门控。安装升级流程不混入聊天运行图；发行打包是否包含流程清单仍是验收项。运行入口发现器发现的新入口必须归类，不得因没有人工列举而静默遗漏。

[inferred] 保留现有 `/data/flow`、trace API、同库观测表、custom SVG 展示和旧 Turn API，在其上增量扩展。VueFlow/ELK 可作为后续性能或布局替代评估，不是本次工程成立的前置依赖。

## 2. Current Behaviour：旧计划完成度复核

### 2.1 结论与判定依据

[verified] 旧计划 `docs/plans/2026-10-02-gitnexus-plan-message-processing-flow.md` 已有实现落地，但**只能判为部分完成，不能关闭其全部 DoD**。相对证据基线到当前 HEAD 有 15 个提交、49 个变化文件。以下按交付要求判定，不用提交数或通过率估算完成百分比。

| 旧要求 | 结论 | 当前证据/限制 |
|---|---|---|
| 数据页消息流程入口、目录、trace/span/event/relation | 已实现基础 | `DataPage.vue:14`、`router/index.ts:103`；`message_flow.py:109`；相关测试通过 |
| 入口早于 matcher、共享消息 root | 部分完成 | gateway `346–379` 有 pre/postprocessor；真实 NoneBot 调度未做现场验收；root 分类会影响输出查询 |
| 输入输出、暂停/单步/拖动回放 | 已实现基础 | `FlowPage.vue:434`、`264`；QQ 分类缺陷会使实际回复缺失；固定 300ms，没有速度控件 |
| 源码业务/符号/语句三级完整展开 | 未完成 | 102 个手工目录节点、57 个不同 source refs、0 个 AST 细节节点；生成器没有递归可达闭包 |
| 实际分支、并行、重试实例 | 部分完成且有缺陷 | 节点聚合覆盖实例状态；静态边由端点出现推断为经过；unknown 节点消失 |
| 异步 root 与跨任务关联 | 部分完成 | compact 关联测试通过；consolidate 未记录真实消费消息集合；页面关联 ID 不可跳转 |
| 历史 trace 绑定原拓扑 | 部分完成且有缺陷 | store 沿用第一张 spec；固定 version 与内容 digest 脱节；归档表无实际写入 |
| live SSE、补读、断线/隐藏/认证生命周期 | 未完成闭环 | 活跃 root 被误判 interrupted；前端无自动恢复，列表轮询没有挂接，历史事件只读第一页 |
| complete/loss/interrupted 诚实呈现 | 部分完成且有缺陷 | writer 延迟失败可保留 complete=1；缺事件仍显示“未走到” |
| 有界非阻塞观测、隐私、保留与性能 | 部分完成 | 有界队列存在；异常 summary 未脱敏；prune 无生产调用、无硬容量验收、无压力基准 |
| 清单漂移检查与 CI | 已实现基础 | AST manifest `--check` 与 contract tests；未做 Docker GitNexus 闭包对账 |
| 最终发行包和真实入口端到端验收 | 未验证 | 本轮未 build、sync-dist 或验证发行实物，不视为完成 |

[verified] 旧方案提到了 consolidate/proactive 等高层节点；这些高层节点及粗 span 不等于记忆晋升和主动决策的完整生命周期。当前 `consolidator.py:705–737` 将精确抽取、候选写入、晋升和 checkpoint 包在粗粒度 `consolidate.write` 内；MemoryManager 内部无完整节点级记录。

### 2.2 会误导调试结果的优先收口项

| ID / 优先级 | 问题及已验证结果 | 定位 | 必须达到的修复合同 |
|---|---|---|---|
| O01 P1 | 活跃数据库 running root 被 list/detail 返回 interrupted；SSE root start 后立即 trace_end | `webui/services/flow.py:93,163`；`webui/routers/trace.py:247` | process incarnation + heartbeat + 已知终态；不能因暂时没有事件结束流 |
| O02 P1 | 当前 QQ 共享 root 一律 qq_passive；实际 delivered 且存在 BOT_SELF 时 IO 仍为空 | gateway `355`；`webui/services/flow.py:249,369` | origin/trigger/route/outcome 分离；通过业务输入/发送 ID 关联 IO |
| O03 P1 | checkpoint 写入失败后 root 仍 complete=1、loss=0，health dropped=1 | `message_flow.py:303–323,535–548` | per-trace sequence/loss + writer 提交确认；异步失败纠正完整性 |
| O04 P1 | trace old→new 实测仍绑定 old spec，只请求 old 版本 | `dashboard/src/stores/flow.ts:140,184` | 按 digest 缓存、切换校验、异步 generation 防护 |
| O05 P1 | 两个端点出现被当作条件边已经执行；真实 unknown hook 节点不进入画布 | `flowLayout.ts:85,263` | 实例事实边与静态可能边分离；unknown 节点和事件始终可查 |
| O06 P2 | start1→success1→start2 后节点仍 succeeded、instances=2 | `flowReducer.ts:45–56` | 按 span/attempt 投影，单独聚合 running/latest/partial failure |
| O07 P2 | 异常中的 Authorization/Bearer 形状字符串原样进入 summary | `message_flow.py:665–668,582` | 稳定 error_code + 统一脱敏；summary/detail/metrics 一并覆盖 |
| O08 P2 | flow_specs 表创建/insert 分支存在但没有 submit spec；轨迹创建后归档计数 0 | `flow_catalog.py:25`；`message_flow.py:468`；`flow.py:198` | 首次运行前持久化不可变 content digest spec；历史可用 |
| O09 P2 | SSE 无恢复闭环，401 处理不同于 Axios；>1000 事件只读一页；列表新轨迹不自动出现 | `flow.ts:109,166,194`；`sse.ts:25` | 分页到高水位、可见性生命周期、cursor/backoff、统一认证 |
| O10 P2 | 没事件显示“未走到”，丢失观测也作同样解释 | `FlowPage.vue:587,618` | 未观测 ≠ 未执行；只有明确 skip/decision 才说跳过 |

[verified] 上述 O01–O08 有当前源码隔离探针或直接查询支持；O09–O10 为当前源码生命周期核验。探针只使用临时库/内存 API mock，没有修改生产数据。

### 2.3 本轮验证的实际边界

[verified] 后端 51 项测试通过，manifest check 通过；Dashboard 5 个测试文件、45 项测试通过，vue-tsc exit 0。命令见 §8。全局 pnpm shim 不可用，实际使用本地 Node 工具入口，没有声称 pnpm 命令通过。

[verified] 现有 API 测试 `tests/webui/test_message_flow_api.py:87` 明确断言了 running→interrupted 的错误行为；`dashboard/tests/flow-store.spec.ts:7` 不覆盖 openTrace/fetch/SSE；布局测试接受端点推断边的实现。`tests/conftest.py:34` 默认关闭 V2。因此现有全绿只证明当前测试合同满足，不能证明旧计划完整、真实聊天稳定或观测事实可信。

## 3. Relevant Architecture

### 3.1 复用边界与三个信息层

[verified] 当前 `core/observability/message_flow.py` 已有独立 root、span、event、relation、异步 writer；`flow_catalog.py` 提供目录；`generate_message_flow.py` 解析登记符号并生成清单；WebUI service/router 与 Dashboard store/reducer/SVG 消费这些数据。延续它们，避免第二套无关联日志系统。

[inferred] 拟采用三个相互独立的层：

1. **静态流程目录**：当前构建中有哪些可能入口、节点、条件和调用。节点有稳定 ID、源码锚点、内容版本、边界归类。
2. **执行实例**：run/root → span/attempt → event/transition；保存实际选中的 guard、输入引用、结果、异常、并行/因果关系。
3. **对象履历**：候选、长期记忆、topic、decision、effect、job、scheduled run、knowledge version、Cometa task 的状态变化与证据引用。对象经历多个流程；一个批次处理多个对象。

[inferred] 三层通过多对多 relation/entity refs 联接。一个消息可能触发多个后台任务，一个整合批次消费多条消息，一个记忆可能经历多批 reinforcement；不要用单一 parent_trace_id 代替实际消费关系。完整视角支持 latest-state 查询，但历史视角必须读当时的状态事件，不从今天的业务表反推当时状态。

```mermaid
flowchart LR
    I[消息或定时/任务入口] --> R[多个独立运行实例]
    R --> T[Turn / 模型 / 工具 / 发送]
    R --> C[消息整合与候选抽取]
    C --> P[候选门槛 / 冲突 / 晋升事务]
    P --> M[长期记忆 / FTS / 缓存 / 压缩]
    I --> D[话题 / 参与度评分 / 主动决策]
    D --> A[群插话或候选验证主动@]
    A --> T
    T --> E[回执 / 回复窗口 / 效果学习]
    E --> C
    M --> T
    M --> A
    B[社交worker / 维护 / 预约 / 知识 / Cometa] --> R
    R --> F[执行事件与对象履历]
    S[源代码 + Docker GitNexus + AST闭包] --> G[不可变版本流程目录]
    G --> U[Dashboard 流程/实例/对象/实验视图]
    F --> U
    X[隔离数据集执行器] --> R
    X --> V[稳定性与版本差异报告]
    V --> U
```

[inferred] 此图是导航架构，不宣称替代完整节点目录。完整性应由 §6.2 的源代码闭包产物和 §6.3–6.6 的节点合同验证。

### 3.2 源码已经确定的业务边界

[verified] 整合的 checkpoint/短期上下文按 QQ 群，画像/候选/记忆按共享空间（`consolidator.py:586–603`）。展示、导出与评测必须保留 group 和 group_shared_space 两个键，不能将群隔离等同记忆空间隔离。

[verified] 当前 participation.observe 已有话题、embedding/keyword fallback、评分、streak/backoff 和候选/允许门槛；持久化只覆盖 CANDIDATE/ALLOW（`participation/__init__.py:194–298`）。新观测需要记录 IGNORE/OBSERVE/禁用/预热等退出原因，不能只展示触发说话的样本。

[verified] 周期主动任务优先尝试获取/验证记忆的主动 @；评分层启用时，定时任务不会再走掷骰群插话（gateway `2930–2940`）。`proactive_target.py:178–265` 无 eligible 验证候选时返回 None；不存在可直接假设的“无候选则随便找人聊天”流程。

[verified] MemoryManager 默认 Python，可选择 auto/rust/严格模式；auto 可回退，严格模式错误不可吞。Python 与 Rust 晋升的事务边界和冲突行为不完全相同（§5），图必须显示实际 backend 与 fallback，不统一画成假想原子事务。

## 4. GitNexus Findings

### 4.1 刷新与完整性限制

[graph] 本轮 Docker GitNexus 1.6.11 / Node 22.23.2；refresh 输出：`872 files, 78030 nodes, 187748 edges, 931 clusters, 829 flows`。节点数包含 PDG statement，不等于业务流程节点数。索引 artifact/build/dependency identity 已比对：artifact `c7d271007a9858c4a966a249474aa193a055ec35a7126dc91eea5c806f414f19`，build `9faaea7491d7a9f1955c300305fb7a21a14f44196981c249bf1c9a905083c4bc`，dependencies `24135c34df802e81623989801a7b4efd3502c5f296389c328ba309f7c370f158`。

[graph] analyze 报告 830 个跨语言 property site 未联接、callable 候选 33 超过 cap32；execution flow 抽样丢弃 2270/2470 entry candidates、24 个 depth cap、659 个 dropped callees、43 个 budget-cut walks。**829 条抽样流程不是内部流程全集**。后续生成器必须用入口/动态注册清单 + AST 补闭包；Rust/动态 hook/定时注册等手工边界需要对账。

### 4.2 本轮查询与实施影响

| 调用与关键参数 | 一行结果 | 对计划的作用 |
|---|---|---|
| `query(search_query=消息流程/flow generator/manifest)`；`context(name=build_manifest)` | 当前生成器可定位到登记目录与 AST 特征生成 | [graph][verified] hash 登记函数不等于可达闭包 |
| `query(search_query=memory candidate promotion decay)`；`context(name=process_new_candidates,file_path=memory/memory_manager.py)` | 晋升入口、Python/Rust gate、整合 caller | [graph][verified] 将晋升作为独立运行、逐候选实例；不复用粗 write span 冒充 |
| `query(search_query=participation proactive scheduling benchmark)`；`context(name=observe)` | participation 与 gateway/benchmark 同时相关 | [graph][verified] 线上观测与隔离评测必须调用同一决策函数 |
| `context(name=promote, file_path=memory_rust/native/src/promotion.rs)` | Rust 调用面有 receiver unresolved，属于 lower-bound | [graph] 使用 Python request 与 Rust transaction 源码补证，不声称跨语言完全解析 |
| `impact(target=build_manifest,direction=upstream,maxDepth=3)` | `LOW, direct=2, impacted=4` | [graph] generator main 与 manifest fixture 合同回归 |
| `impact(target=process_new_candidates,file_path=memory/memory_manager.py,direction=upstream,maxDepth=3)` | `HIGH, direct=15, impacted=21` | [graph] **高风险**：整合与多组记忆测试；观测不能改变晋升行为/锁范围 |
| `impact(target=observe,file_path=memory/participation/__init__.py,direction=upstream,maxDepth=3)` | `HIGH, direct=6, impacted=23` | [graph] **高风险**：线上 gateway 与 benchmark 同受影响；禁用模式必须零业务差异 |
| `context/impact(target=_emit_event,file_path=core/observability/message_flow.py,direction=upstream,maxDepth=3)` | `CRITICAL, direct=6, impacted=65, processes_affected=12` | [graph] **关键风险**：writer/event 合同影响消息、后台、WebUI 与 Cometa；必须先测试兼容迁移 |
| `detect_changes(scope=compare,base_ref=e7cf4f3166d898310279de43cfa89a0c1d0b0aaf)` | `changed_count=811, affected_count=87, changed_files=49, risk_level=critical` | [graph] 用于旧交付边界定位；不是已完成/无回归证明 |

[graph] 上述 impact/detect_changes 的完整保存结果无 `partial:true`/`truncated:true` 标志；终端大输出被展示截断时，本轮再从保存结果提取所有 depth1 依赖核验。不能把工具无完整性标志扩展成索引无盲区。

[verified] 首次以 `emit` 查找返回 UNKNOWN/no symbol；当前真实函数是 `_emit_event:560`，已用正确名称重新 context/impact 并源码核验。该 UNKNOWN 没被当成低风险结论。

## 5. Statement-Level PDG Findings

[graph] `pdg_query(target=memory/memory_manager.py,mode=controls,limit=200)` 返回142条控制关系；`pdg_query(target=memory/participation/decision.py,mode=controls,limit=200)` 返回27条；审计还查询了 `end_trace` controls。下表只保留与埋点顺序/评测正确性有关的切片；PDG 给的是控制依赖，数据与事务语义由源码确认，不伪称完整 REACHING_DEF 或跨语言数据流证明。

| 切片 | 源码/控制约束 | 实施要求 |
|---|---|---|
| backend 分派 | [graph][verified] manager `111,116,122` 控制 Rust/auto fallback/Python 返回；`102–142` | backend.selected、fallback.reason、实际异常及耗时分开；strict failure 仍抛出 |
| candidate gate | [verified] `354–394` 依次 importance→高 confidence→低 confidence 与 @/occurrence→观察 | 每条 gate 保存具体阈值版本、输入数值和 selected reason；不要只画成功节点 |
| merge/create | [graph][verified] `303` 的 T→merge304，F→create306+quota308 | 使用实际分支 transition；quota 在新建分支，不虚构为每次 merge 都执行 |
| Python commit/cache/compress | [verified] `314–333` candidate确认、commit、close 后才 bump/compress | committed 状态事件在业务 commit 后确认；缓存/压缩失败不把已提交记忆显示为回滚 |
| Rust transaction | [verified] `promotion.rs:623–646` IMMEDIATE事务；冲突/merge/create/FTS/quota/确认在事务内 | 区分 attempted/committed/rolled_back；Rust桥接语义节点与真实 backend request/result绑定 |
| 冲突业务差异 | [verified] Python `_resolve_conflicts:728–758` 将弱候选置 OBSERVING 但上层 `299–316` 继续晋升；Rust `398–413` 立即返回 observing_conflict | 新增强旧记忆/弱新候选 parity case；这是现存业务疑点，独立决定修复，不能靠观测统一成同一逻辑 |
| TTL 与时钟 | [verified] manager `411–470` 按 first_seen_at 与 SQL julianday('now') 过期；reinforcement 保留首次时间 | 逻辑时钟必须覆盖 SQL、Python/Rust时间写入；重现不能只给 observe(now) |
| streak/backoff | [graph][verified] decision `118,119,139,145–158` 控制累积/强钩子/降级；`122` 使用 time.time而不是now | 保存决策前后slot、topicrevision、强钩子、streak、backoff；统一可注入业务时钟 |
| 评分持久化盲区 | [verified] observe `297–298` 只落候选/允许 | 观测流须独立覆盖全部决策等级及 warmup/no tables；不能更改原业务存储语义 |
| 主动发送前过滤 | [verified] gateway `2804–2868` 顺序为空→topic失效→自然性→合并行数→重复→送达 | 保存每次退出；生成成功和发送确认分离；已发送部分与未发送部分可查 |
| 发送后副作用 | [verified] `2870–2905` after span当前为空，实际记账/学习/记录/压缩发生其后 | span 包住真实动作；只对 acknowledged segments 记账/学习，因果关联异步压缩 |
| writer 完整性 | [graph][verified] end_trace `536` 控制 complete默认计算；真正异步失败在 `303–323` | 不能以 producer结束时全局drop差值作为最终完整性；按trace提交事实纠正 |

## 6. Proposed Changes

以下都是拟实施方案。每项先明确现有锚点与职责，再定义新合同；新增文件/接口/数据结构没有被当作现有实现。

### 6.1 先修复观测事实，再增量扩展数据合同

[inferred] 修改 `message_flow.py` 的 `begin_trace/end_trace/_emit_event/FlowSpan.finish/__exit__/_Writer._write_batch`，以及 `webui/services/flow.py` 的 message_detail/message_io 等已读服务逻辑，完成 O01–O03/O07/O08。建议保留现有表名和 trace_id 主键，增加字段与辅助表；前端把 message trace 抽象为内部 process run，不要求一次性改名迁移所有消费者。

| 合同对象 | 建议增加的数据 | 责任/约束 |
|---|---|---|
| root/run | process_kind、origin、trigger、route、process_incarnation、business_ts、started/last_heartbeat/ended、spec_digest、experiment/case IDs | QQ root身份稳定，route可追加；业务时间与观测时间独立；已有root_kind作为legacy映射 |
| span/instance | span_id、parent_span_id、attempt、instance_key、entity refs、source node id | 同node多个实例独立；跨线程/worker显式传递run上下文，拒绝仅靠ambient context猜关联 |
| event/transition | event_id、run内sequence、fact_kind、selected_edge/guard_id、reason_code、before/after refs、transaction_id/commit状态 | sequence在run内保证；跨run只提供因果偏序，不伪造全局先后；不存任意参数/locals |
| relation | caused_by、consumed_message、produced_candidate、promoted_to、verified_by、spawned、scheduled、notified、same_task/attempt 等typed edges | 多对多；batch真实消费集合；来源粒度不足必须标 legacy/inferred |
| entity_change（拟新增） | entity_type/id、scope、run/span、from/to_state、version/revision、changed_fields摘要、content digest | 历史append-only事实；允许表示创建/删除/tombstone；业务内容通过受控只读查询读取 |
| integrity | producer-ended、writer-ack高水位、observed/lost/unmapped、gap ranges、reason、storage/loaded completeness | producer结束不等于persisted complete；已知loss持久归trace；观察者自身失败明确unknown |
| spec archive | 不可变digest、schema、code commit/dirty provenance、nodes/edges/coverage、签出源码anchor | 首次root引用前归档；同digest字节相同；历史无源文件仍可看当时拓扑 |

[inferred] Writer保持有界、非阻塞、业务 fail-open。run结束先标 producer_ended/pending_flush，writer确认本run已接受sequence的持久高水位后落最终integrity；队列拒绝时记录 per-run loss/gap，账本不可用则 integrity=unknown。等待 flush 只用于测试/关机的有限窗口，不放到聊天热点路径。崩溃恢复用 incarnation/heartbeat和持久账本，不仅凭status=running判中断。

[inferred] 状态事件在业务成功 commit 后确认；失败可发 attempted/rolled_back。观测暂不可用时业务事务继续，不能把flow insert加入业务锁或事务来影响晋升；需要强审计的状态变更使用同业务事务内的最小outbox记录并由writer消费，此选项须有锁/写放大基准后启用。明确哪种模式提供commit事实保证，哪种只有best-effort观察。

[inferred] 摘要采用 allowlist 数据类型和error_code，所有字符串渠道统一脱敏。对象ID/pseudonym保持跨实验可联接；原始聊天内容独立权限、可配置保留及导出策略。跨scope查询继续遵守现有管理员认证/业务可见性，不能以Dashboard调试模式扩大知识或私有记忆权限。

### 6.2 基于源代码生成全量目录，并随版本同步

[verified] 当前生成器 `build_manifest:130–183` 只遍历人工 NODES，`structural_features:76–101` 数调用/branch/await，不生成对应节点或边。[inferred] 保留它的注册/校验入口，升级为“人工语义根 + 自动源码闭包 + 动态边界清单”的编译流程。

1. **入口发现**：从matcher/preprocessor、FastAPI route、scheduler decorator、worker main/handler registry、on-startup/shutdown、RuntimeFacade、Rust桥接导出以及当前目录roots建立inventory。将发现入口归到下表流程族，测试入口另列，配置禁用根仍保留静态目录。
2. **GitNexus图优先**：使用已刷新的query/context/关系查询做跨模块closure和impact。不能使用processes抽样作为全集。CI运行固定版本Docker分析；PDG用于验证guard/return/状态变更顺序。
3. **AST展开**：每个可达源码符号自动列出call/await、if/match/loop、early return、raise/except/finally、with/async with、task spawn、事务及存储/网络副作用；去重递归和循环，保留调用位置。不是只计数或body hash。
4. **边界对账**：标准库/第三方叶子列external边界；NoneBot动态dispatch、plain-object hooks、Python/Rust property绑定列explicit mapping与证据；UNKNOWN不得自动豁免。每个boundary有owner、reason、source、期望输入输出和未观测说明。
5. **三层目录**：业务语义节点→真实符号/调用图→条件/语句节点。稳定ID采用显式业务ID和module-qualified symbol + 结构anchor；行号仅导航，内容/语义变化产生新digest。改名迁移用alias映射，禁止把旧事件强改成新节点。
6. **运行探针映射**：日常profile记录业务/状态/关键guard；详细debug profile按选定run/模块开启statement探针，AST探针在构建/开发阶段生成，只输出分支ID与安全摘要。静态语句有目录但没probe时显示“未观测/静态”，绝不根据parent成功推定全执行。
7. **生成变更**：产出 entry_inventory、source_closure、nodes/edges、unresolved/excluded、coverage、source_map、semantic_diff。CI检查新调用/分支/任务/状态未覆盖就失败；body变化即使拓扑未变也刷新源版本，避免旧源码anchor绑定新内容。
8. **版本发布**：code digest+spec digest+schema版本绑定；运行库归档；release资源清单包含所需manifest；旧版保留与trace保留关联。性能数据阈值只调整布局/采样，不从目录删除节点。

[inferred] 核心coverage分母：registered_runtime_roots、reachable_symbols、branch/exception/return_sites、spawn_sites、business_state_mutations、explicit_boundaries。每类分别报告 mapped/probed/unresolved/excluded；“所有核心源码节点已表示”要求 unresolved=0，合法boundary仍显式显示。运行complete只说明该次已启用profile没有已知gap，不等于所有静态路径都经过。

### 6.3 记忆整合、晋升与后续生命周期节点合同

[verified] 以下节点库存以当前 `consolidator.py:586–755,1102–1289`、manager、compressor及Rust晋升源码为依据。[inferred] ID为建议语义ID前缀；每个业务步骤继续自动展开符号和语句层。**循环按候选/记忆ID生成实例，不逐条手写不同静态节点**。

| 流程/节点组 | 必须展示的逐步节点与分支 | 关键事实/关联 |
|---|---|---|
| `memory.consolidate` 入口 | 触发原因/force；DB可用；群lock wait/acquire；共享空间解析；checkpoint；积压计数；批次阈值/skip streak；source窗口与backend | group与space分开；consumed消息集合及起止ID；锁等待与模型等待分开 |
| `memory.extract` | stage1 prompt/context→模型gate/queue→调用→截断缩批重试/下限失败→JSON解析；self_disclosure gate→stage2精确抽取→成功空数组覆盖/失败None回退 | stage1/2真正prompt/model版本、批次、token预算；解析失败推进checkpoint与截断停checkpoint必须不同 |
| `memory.candidate.write` | 短期上下文/画像分别写入；candidate user/source/importance normalization；缺user/未知sender/空内容skip；Gate3 validation；pending匹配；reinforce或insert；legacy long-term分支 | candidate/evidence/source IDs；confidence/occurrence前后；reinforce保留first_seen；Gate3错误码 |
| `memory.promotion.batch` | backend resolve→Rust/Python/auto fallback；TTL拒绝；读取NEW/OBSERVING排序；逐candidate gate | batch可能处理当前群以外的既存候选，不能把全部结果归到触发消息；保留actual scope |
| `memory.promotion.gate` | importance阈值；confidence高/中/低；AT来源认可；occurrence阈值；OBSERVING/noop/eligible分支 | 每个门槛输入与当时config；NEW→OBSERVING→CONFIRMED或REJECTED履历 |
| `memory.promotion.apply` | scoped conflict扫描→contradiction→旧记忆conflict或候选观察；相似记忆查找→merge/create；新建quota排序/dryrun/archive；FTS upsert/delete；candidate确认；commit/rollback | Python/Rust各自子图；memoryID与变更；FTS和quota一致性；不能统一虚构停止条件 |
| `memory.promotion.after` | commit后history版本bump→压缩hook；处理摘要；整合checkpoint推进；root关闭 | 业务成功/后台失败分开；因果多对多；checkpoint不是candidate状态 |
| `memory.maintenance` | promote后压缩；周度active加载/空集；去重merge→atomize→低价值archive→decay→commit→stats→historybump | `compressor.py:89–129`；archive/merge/原子化对象履历；多commit分别记录 |
| `memory.retrieve` | 作用域/可见性；各检索通道/候选/排序/注入预算；访问/确认副作用；缓存命中/版本；FTS rebuild条件→active重建→commit | 当前retriever细节继续由M0源码闭包展开；FTS rebuild是检索触发，不假设定时任务 |
| `memory.verify` | 主动@资格/候选选择→生成/发送确认→待回复窗口→新消息归因/超时→后续候选证据/整合/再晋升 | 不把任何回复自动等同验证成功；显示当前实现实际改了什么；无回应不能判负面证据 |

[inferred] 建议新增 `core/observability/internal_flow_catalog.py` 注册独立 memory process specs；在 `_write_memory_candidates/process_new_candidates/_decide_promotion/_resolve_conflicts/_merge_into_memory/_create_memory/_enforce_user_quota/run_weekly` 已读真实边界添加轻量语义probe。Rust源码目录来自AST/显式桥接；运行事实优先从 bounded request/PromotionOutput形成事件，只有需要事务内细节时扩展Rust返回trace摘要，不把真实SQLite句柄/任意内容传给观测层。

[inferred] weak-conflict Python/Rust差异作为独立业务回归缺陷登记：先用隔离fixture确认预期策略及现状；可比较一致性但不能在本轮文档内标已修复。M2若修正，必须独立测试/行为变更记录，不能通过调整图让缺陷消失。

### 6.4 主动决策、群插话、主动 @ 的完整节点合同

[verified] 以 `ParticipationManager.observe/_score_with_embedding/note_stella_spoke/tick`、decision/scorer、`proactive_target`、gateway `_proactive_at_user/_proactive_speak_for_group/_proactive_speak_impl/proactive_speak_job` 为实现锚点。[inferred] 建议process种类为 `participation.evaluate`、`proactive.group`、`proactive.verify_user`、`proactive.timer`，明确主动发言和直接请求回复的关系。

| 流程 | 必须展示的节点/退出 | 关键调试数据 |
|---|---|---|
| 消息驱动 participation | 配置/表/预热检查→人类活动记录→buffer→topic生命周期/embedding失败fallback→signals→velocity/share/novelty→统一score | 全部IGNORE/OBSERVE/CANDIDATE/ALLOW；score正负分项、阈值version、topic/revision；不能只存ALLOW |
| 决策tracker | mode；nominal level；topic变更reset；candidate streak；strong hook；low-novelty backoff解除/进入；二次确认；最终level/should_speak | slot before/after、need次数、backoff_until、source message；硬@/direct gate不混成主动概率命中 |
| 周期检查 | feature开关/无Bot→群循环→睡眠/苏醒播报→主动@尝试→成功跳过群插话→参与度启用跳过骰子→legacy群插话 | root在前置return之前创建；群/候选无资格也有可查询原因；独立播报root与门控边界 |
| 主动@选择 | can_speak→per-user24h配额/base+bonus/cap→未回应/冷却→OBSERVING可验证类型/confidence区间/询问冷却→目标选择→昵称与候选context | 谁为何被选、哪些候选因何淘汰；无候选=noop；避免只在生成开始后创建trace |
| 群插话前置 | can_speak/静音/睡眠/冷却→概率路径（仅适用模式）→群lock→replygate/start→触发异步整合→context→topicrevision snapshot | 门控来源/锁等待/同群抢占；触发整合只建立spawn因果，不伪画等待后台完成 |
| 通用turn子图 | RuntimeFacade/runtime→retrieval/prompt/budget→planner/model/tool/provider/gates→cancel/error/wait→output | 使用现有Turn/工具事件关联；不复制一套生成engine；区分墙钟/queue/模型耗时 |
| 发送前过滤 | empty→topic过期/撤销→自然性skip→行合并→重复→每段发送/abort | filter输入digest、理由；多次revision检查；无发送时不记账 |
| 发送与确认 | 每段attempt→ack/failed/unknown→partial aggregation；主动@单段亦同 | 对真实messageID/receipt绑定；unknown不自动retry，模拟发送用simulated_ack |
| 发送后 | confirmed-only频率/重复记录→note_stella_spoke→effect learning→BOT_SELF记录→异步compact→主动@配额/问询记录→回复窗口task | 不用当前空的proactive.after span代替这些动作；已确认与剩余片段区分 |
| 效果闭环 | 新消息response attribution→接话/拒绝/无观测响应→窗口close→social job/effect更新→后续记忆证据 | 无回应是no_observed_response；窗口异步因果，前台root关闭不表示窗口完成 |

[inferred] Dashboard可从某次“保持沉默”直接看gate和当时slot，也可从某条已晋升记忆反查主动@验证及来源消息。不要依赖timestamp窗口猜哪条BOT_SELF对应哪次turn。

### 6.5 其余内部流程族与边界

| 流程族 | 当前源码锚点 | 建议观测节点/对象 |
|---|---|---|
| 消息/Turn/工具 | [verified] 旧flow与gateway已有入口/运行数据 | [inferred] 保留完整消息链，修route/IO；静态展开动态hooks/provider/tool边界，关联turn而非凭同名节点合并 |
| 回复效果/社交worker | [verified] `memory/social_worker.py:193–228` | [inferred] sweep→due→lease/claim→handler→done/retry/dead；effect/job/delivery/evidence履历与重试attempt |
| idle/backlog/清理 | [verified] gateway `2962–3067` | [inferred] expression sweep、session idle/end、consolidation drain、message/trace/learning prune；处理范围、游标、删除计数、保留策略和noop原因 |
| 预约调度 | [verified] `plugins/bot_main/scheduling/runtime.py:146–184,262–338` | [inferred] worker lease/recover→due/missed/merge/cursor→claim→markrunning→mute/sleep/cooldown→reminder或agent→limits/fence/cancel/timeout→delivery；复用task/run/lease状态 |
| 知识导入/索引 | [verified] `knowledge/ingest.py:78–120,131–229` | [inferred] job→parse→fingerprint/dedup→doc/version→chunks/embedding/pending→ready/failed；ready≠published；审核/发布/索引重建入口由M0继续闭包核验 |
| Cometa | [verified] `cometa/worker.py:131–195` 已有flow source_key/task linkage | [inferred] 延续task/attempt/backend/event/result/approval/artifact协议；显示lease/执行/结果/通知各自状态，不新增同义任务协议 |
| 启动/关闭与观测健康 | [inferred] 从M0入口inventory实际发现 | [inferred] 注册成功/失败、worker启动/恢复/关闭、flush/队列压力/loss；external进程/模型内部为有合同的边界 |

[inferred] M0为每族形成source-verified入口清单；本表中的详细新节点不是“当前已经观测到”的声明。知识publish、工具动态注册等未在本轮完整精读的子图留作M0定点闭包任务，禁止实施代理凭名称猜函数然后编辑。

### 6.6 Dashboard：流程目录、运行实例、对象履历、验证实验

[inferred] 修改现有 `FlowPage.vue/flowLayout.ts/flow.ts/flowReducer.ts/api/flow.ts`，保留现有导航入口，增加四个同级视角：

- **流程目录**：按process族筛选；三层展开；静态可能路径、条件说明、source anchor、unresolved/opaque清单；显示版本/coverage与当前代码差异。
- **运行实例**：root/span/attempt列表；全量/实际视图；时间轴泳道、并行与spawn；真实transition高亮；锁/队列/模型/事务/发送分时；loss/gap明确；span可点选、关联run可跳转。
- **对象履历**：按candidate/memory/topic/job等ID查，展示状态前后、证据集合、发生run与scope；关联输入、输出和effect；最新状态与历史事件分栏，保留来源精度标签。
- **验证实验**：dataset/snapshot/config/model版本→case列表→稳定性指标/覆盖→差异→失败run→节点/对象。实验有进度、取消、资源/模型调用预算；查看报告和播放不能启动业务。

[inferred] reducer先按instance算状态，再计算节点的running_count/succeeded_count/failed_count/latest；跨并行不把latest颜色当唯一事实。未知节点以占位节点+事件表显示；“未观测”与“明确跳过”分开。缺spec仍能查看原始受控事实表。

[inferred] 加入spec digest缓存与快速切trace的request generation检查；历史事件先分页到snapshot高水位，再订阅其后的SSE；断线重连cursor补读、去重、backoff。隐藏页面停止连接，恢复补读；401统一处理。列表轮询或列表stream真正挂接。数据库完整性、API返回截断、前端已加载完整性分别显示。

[inferred] 回放支持播放速率、单步、按真实时间/按事件、跳到decision/error/commit；只是读取事实，不重跑模型。跨run根据因果可同步选择，独立时钟/不同worker不得画成确定的全局序列。大图默认折叠业务层，节点/事件列表虚拟化，服务端分页；详细AST仅对选中子图按需加载。

### 6.7 真实聊天数据集稳定性验证

#### 6.7.1 现有工具可复用部分与不足

[verified] `tests/benchmark/participation/runner.py:43–85,120–151` 未select原始message ID；历史时间 naive parse受主机时区影响；历史BOT_SELF调用note_stella_spoke未传now；is_tome固定false。decision tracker还有time.time；manager使用SQL now。只注入observe时间无法复现完整业务状态。

[verified] benchmark B/E/F 等指标在没有对应样本时ratio=0→PASS；A的is_tome=false不能验证真实@场景（`metrics.py:65–86,121–149`）。现有工具不执行完整生成/发送/学习/晋升链路。`memory/benchmark.py:270–399` 有临时DB检索回放但关闭FTS/RAG并全局monkeypatch，不能直接放进并发Web服务；Rust benchmark以检索parity为主。

[verified] `probe_consolidation.py` 可跑窗口prompt/模型/parse/Gate3但不落库/推进checkpoint；embedding fixture脚本会真正调用endpoint；sample_windows的高密度采样不等于自然聊天分布，而且窗口字段丢失原始scope/ID/source。`webui/services/trace.py:244–275` 的冻结预算replay也不是全链路重执行。

#### 6.7.2 四种明确隔离的实验模式

| 模式 | 执行内容 | 副作用/结果合同 |
|---|---|---|
| `trace_playback` | 历史观测事件回放 | 只读；0模型、0写业务、0发送；用于调试事实 |
| `decision_recompute` | 冻结snapshot/config/clock，调用真实纯决策与gate | 隔离状态；已有fixture/keyword与指定embedding fixture；用于策略/时序对照 |
| `isolated_pipeline` | 同生产业务函数，临时DB/缓存/job状态，fixture LLM和dry sender | 实际执行记忆/学习/调度事务；simulated_ack明确；0生产DB、0真实QQ/外部工具 |
| `model_validation` | 同隔离pipeline，显式模型endpoint与预算 | 真实模型生成；仍隔离发送与工具；费用/次数/timeout可控；不把随机seed当LLM确定性保证 |

[inferred] 新增 `core/evaluation/` 独立包与CLI（拟），由独立child process运行，每个实验一个工作目录/SQLite/缓存/日志/工件/job store，不能在FastAPI线程里monkeypatch生产模块全局DB_PATH。先引入被业务使用的Dependencies/Clock/Random/Model/Embedder/Sender边界；测试和生产使用相同规则函数。路径解析后必须处于实验root，配置加载禁止落回生产默认路径；不能沿用默认productionDB的benchmark启动方式。

[inferred] Dashboard实验API只调用固定CLI/参数schema；不接受任意Python模块、pickle或shell命令。生成器/插件/工具在评测中通过允许的fake adapter；生产QQ sender不可导入执行。subprocess失败/cancel要关闭worker、保存partial与错误，不把未完成样本纳入稳定率。

#### 6.7.3 Dataset、snapshot、时钟与版本合同

[inferred] dataset采用manifest+JSONL/SQLite，只读源快照导出，保存stable event_id、原message ID映射、source_kind、group/shared_space、pseudonym user、UTC timestamp+明确原时区、sequence/order tie、is_tome/@/reply target、附件引用与已授权content。按UTC+源顺序稳定排序，不用CAST(timestamp AS INTEGER)排序ISO日期；重复ID与乱序处理政策显式记录。保留全体自然分布测试集，信号密集/故障集单独报告，不混加权。

[inferred] snapshot在时间cutoff冻结：消息水位、summary/checkpoint、candidate/evidence与first_seen、active/conflict/archive memory、profile、topic/slot、quota/unanswered/effect窗口、job/lease、knowledge/index version、scheduled/Cometa状态、scope映射与配置。导出用一致性只读事务/SQLite backup，禁止复制打开中的裸db文件遗漏WAL。missing模块标partial snapshot，不能宣称完整复现。

[inferred] 逻辑业务时钟注入所有TTL/冷却/backoff/配额/任务lease/回复窗口及SQL时间写入；性能时长继续monotonic真实计时。scheduler在虚拟时间tick；后台运行的可控调度顺序与random draws一并记录。避免替换全局time模块，使用Clock依赖和显式SQL now参数；Python/Rust相同clock合同。

[inferred] 明确两类数据使用：**历史观察**保留历史BOT_SELF用于恢复原状态；**反事实模拟**由新模型生成模拟BOT_SELF，不能同时再将历史bot输出作为本轮bot行为累加。历史人类响应只可按原语境标注，不能自动当作对新生成内容的真实反馈；warmup/测量分段，snapshot不能包含cutoff后的记忆/标签。

[inferred] 每次experiment记录 code HEAD/dirty digest、spec digest、数据/初始snapshot hash、脱敏config hash、prompt/model/embedding版本与实际响应fixture、logical timezone/seed/random draws、policy suite/labels版本、backend、资源与调用预算。相同fixtures可比semantic digest（忽略UUID/实际耗时等非语义字段）；真实模型多轮重复报告分布和置信区间，不能用一次随机结果证明稳定。

#### 6.7.4 稳定性、覆盖与故障验证

[inferred] 先检查完整性/样本门槛，再计算业务指标。每项结果为 PASS/FAIL/INSUFFICIENT_SAMPLES/SKIPPED/INCOMPLETE；样本数0不允许PASS。报告总数、有效数、丢弃原因、root/guard/exception/branch/backend覆盖，使用已声明expected cases作分母；不拿“跑完”替代稳定。

| 维度 | 必须验证的不变量/指标 |
|---|---|
| 观测真实性 | live不中断误报；per-run loss不串线；无事实transition不高亮；unknown可见；旧spec绑定；完整加载与存储完整独立 |
| 记忆 | scope/证据不串群；Gate3失败不晋升；TTL按first_seen；重复源不虚增证据；transaction fail不确认；冲突/FTS/quota/backend parity；checkpoint停/进策略可复现 |
| 主动 | gate拒绝无发送；score可解释；streak/退避/配额/冷却跨天时序；过期topic/cancel丢弃输出；只ack记账；未知发送不自动重发；无回应不记负反馈 |
| worker/任务 | lease恢复、fence、重复claim幂等、retry/dead有界；task执行成功与通知失败分开；knowledge ready≠published |
| 隔离 | 实验所有状态路径在sandbox；生产DB前后hash/连接审计不变；sender/tool只fake；并发实验互不污染；观测开关不改变同fixture业务结果 |
| 资源/长期稳定 | 队列watermark/drop、DB锁/体积、RSS、p50/p95耗时、任务backlog与最终排空、长期运行事件保留/容量；模型预算/取消可控 |

[inferred] sandbox可控fault profiles：JSON解析/输出截断/模型timeout、embedding离线/维度不符、SQLite锁/commit失败/磁盘写失败、writer队列溢出/批量失败、进程重启/lease过期、clock午夜/时区/跃迁、topic revision与取消、重复/并发输入、部分/未知发送回执。每次故障注明注入节点/attempt，能从报告直达flow实例与状态变化；不对生产bot注入故障。

[assumed] 初始性能预算建议：日常语义profile p95额外延迟不超过5ms且固定fixture吞吐下降≤5%；实验上限1并发，trace事件硬容量/TTL可配置；图先以单run10k事件、数据集100k消息、日常语义run低采样loss为验收规模。M0用实际硬件基线确认数值后锁定，未测量前不称已达标；详细statement profile另报告开销，不能强制日常全开。

## 7. Implementation Sequence

[inferred] 按依赖拆成可独立审查的里程碑。M0/M1是可相信调试结果的前置条件；M2/M3是用户当前重点；M4完成全系统范围；M5/M6满足真实数据集验证目标。只做M2/M3不能关闭整项计划。各阶段业务仍可运行、旧API可用，新增功能有feature flag和迁移回滚策略。

| 阶段/优先级 | 可执行工作 | 依赖 | 退出条件 |
|---|---|---|---|
| M0 / P0 源码与旧交付收口 | 将O01–O10探针变成正确合同的回归测试；inventory所有运行根；补动态/Rust/knowledge publish等边界的context+源码；确定性能/容量基线；旧DoD逐项登记 | 当前HEAD重新核验、每个symbol改前impact | 有root/closure清单与覆盖分母；业务风险清单不含未解释UNKNOWN；旧缺陷可稳定复现 |
| M1 / P0 可信观测模型 | 实现live/IO/loss/sanitization/spec归档；增量schema；instance/transition/entity contract；修前端版本/unknown/retry/分页/SSE/未观测文案；迁移与legacy兼容 | M0 | 所有O01–O10验收通过；loss/commit/heartbeat可信；旧trace可看、spec不串；观测关闭业务等价 |
| M2 / P1 记忆生命周期 | candidate extraction/write/reinforce→batch promotion→Python/Rust gate/conflict/apply/commit→quota/FTS→cache/compress/retrieve对象履历；补强弱冲突parity实验，若修业务独立提交 | M1 + memory source closure | 逐候选可解释，事务状态不虚报，真实evidence/consumption多对多可查；TTL/backend/冲突用fixtures验证 |
| M3 / P1 主动发言闭环 | participation全等级记录；topic/score/streak/backoff；timer preflight/verify_user/group roots；发送前过滤、逐段回执、记账/效果窗口/记忆关联 | M1；验证闭环依赖M2 | 可解释“为什么没有说”；主动@无目标也有原因；确认发送才记账；窗口与根关联且互不冒充完成 |
| M4 / P1 其余运行与目录展开 | worker/social/effect、maintenance、scheduled、knowledge、Cometa、startup/shutdown；三层目录、跨root泳道/跳转/对象查询；保留/容量/性能 | M1；相关M2/M3合同 | 所有inventory入口已归类；所有核心静态节点映射，无unknown静默豁免；进程恢复/历史数据可靠 |
| M5 / P1 隔离验证执行器 | dataset/snapshot schema与只读导出；Clock/Random/Model/Sender adapter；四种模式；child process隔离；fixture/virtual-time/fault profiles；CLI先行 | M1；M2/M3；全范围依赖M4 | 可运行固定小集重现及故障；所有状态路径隔离；0真实发送；同fixture语义结果可重复 |
| M6 / P1 报告、比较与最终门禁 | Dashboard实验/失败case导航；sample/coverage/invariant报告；版本差异；大集/长跑性能；Docker闭包CI、manifest/资源打包与真实入口smoke | M4+M5 | §13全部满足；当前发布包包含对应digest spec；自然分布数据集报告可审查 |

[inferred] 目录生成器实现可在M1建立接口，后续阶段持续添加roots/mapping；受body fingerprint/golden保护的正式生成manifest/baseline **在最终整合阶段统一刷新一次**，避免每个中间阶段反复改同一基线。期间使用临时候选产物和针对编译器的测试，不谎称发布manifest已最终对齐。每次准备commit仍执行AGENTS要求的detect_changes，不能以文档阶段顺序豁免。

## 8. Test Strategy

### 8.1 已运行的验证命令

[verified] 当前环境实际运行成功，均使用临时库/现有依赖，没有模型调用或真实发送：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/observability/test_message_flow_store.py tests/observability/test_message_flow_runtime.py tests/observability/test_message_flow_contract.py tests/webui/test_message_flow_api.py -q -p no:cacheprovider --basetemp "$env:TEMP\stella-flow-review-pytest"
python scripts/generate_message_flow.py --check
node dashboard/node_modules/vitest/vitest.mjs run --root dashboard
node dashboard/node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p dashboard/tsconfig.json
python -m pytest tests/test_memory_manager_v2.py tests/test_candidate_reinforcement.py tests/test_memory_rust_promotion.py -q -p no:cacheprovider --basetemp "$env:TEMP\stella-internal-flow-memory-review"
```

[verified] 结果分别：51 passed（3条依赖弃用警告）、manifest matched、5 files/45 tests passed、typecheck exit0、29 passed（1条依赖弃用警告）。Rust相关测试包含mock/backend合同，不能据此宣称真实native扩展和全数据集parity通过。未build/未sync-dist/未做真实NoneBot/最终发行包验收。

### 8.2 现有测试应更新的场景

| 文件 | 输入 → 操作 → 期望 |
|---|---|
| `tests/webui/test_message_flow_api.py` | running+活进程 → list/detail/SSE → running且不trace_end；过期incarnation才interrupted；QQ delivered通过业务ID返回真实output；>1000分页高水位 |
| `tests/observability/test_message_flow_runtime.py` | producer end后writer batch失败 → flush/recovery →该trace partial/loss；并发另trace不受污染；脱敏summary；heartbeat/restart；实例attempt |
| `tests/observability/test_message_flow_store.py` | 老schema/老root→migration/read→兼容；同spec digest重复存幂等，版本碰撞拒绝；归档与保留联动 |
| `tests/observability/test_message_flow_contract.py` | 新入口/call/branch/spawn/return加入 → compile/check → 未映射核心失败；external/Rust显式boundary可查；hash与语义diff不混 |
| `dashboard/tests/flow-store.spec.ts` | old→new spec、快速A/B切换、乱序响应 →digest正确；分页/断线/隐藏恢复/401；列表实际刷新；missing spec事实表 |
| `dashboard/tests/flow-reducer.spec.ts` | success→新attempt start、并行成功失败、乱序事件 → instance状态正确，不继承旧reason |
| `dashboard/tests/flow-layout-executed.spec.ts` / `flow-layout-layered.spec.ts` | endpoint出现无transition →无traversed；unknown/opaque可见；循环/异步/重试；层级展开保留source anchors |
| `tests/test_memory_manager_v2.py` | 弱新候选矛盾强旧记忆 → Python/Rust →现状复现/约定策略一致；不能只测强新候选 |
| `tests/test_candidate_reinforcement.py` | 同源/重复源/TTL边界/再出现 → reinforcement/gate →证据计数与first_seen策略一致；scope隔离 |
| `tests/test_memory_rust_promotion.py` | python/auto/rust/strict、事务失败/fallback → bounded request/result/hook →实际backend和提交状态正确 |

[inferred] M0定位参与度、调度、社交、知识与Cometa各自现有测试后补入交付清单；其具体symbol必须context/source/impact确认。新增测试可采用下列明确路径，避免用一组镜像实现的单元测试替代业务验收。

### 8.3 新增测试与场景矩阵

| 拟新增测试 | 必须包含的独立行为场景 |
|---|---|
| `tests/observability/test_internal_flow_inventory.py` | root发现、动态注册/跨语言explicit mappings、核心缺节点硬失败、第三方边界原因、稳定ID/改名alias、源代码变更semantic diff |
| `tests/observability/test_memory_flow_lifecycle.py` | stage1/2空覆盖与fallback、Gate3拒绝、reinforce、TTL、merge/create/conflict/quota/FTS、commit失败、after-hook失败、batch真实消费集合、多群共享space |
| `tests/observability/test_proactive_flow_lifecycle.py` | IGNORE/OBSERVE/ALLOW/预热；stronghook/二次确认/backoff；noBot/noeligible；timer评分启用分支；主动@与群插话；stale/cancel/empty/duplicate；partial/unknown send与ack-only学习 |
| `tests/evaluation/test_isolation.py` | production路径默认回退、scope映射、插件/真实sender导入、DB/WAL、并发run/cancel → 拒绝或完全隔离；生产状态不变 |
| `tests/evaluation/test_virtual_clock.py` | UTC+8/UTC、午夜、TTL/冷却、SQL/Python/Rust、历史BOT_SELF、scheduler lease/backoff →一致逻辑时间；性能monotonic独立 |
| `tests/evaluation/test_pipeline_replay.py` | frozen snapshot+dataset+fixtures →两次pipeline→同semantic digest；warmup/cutoff防泄漏；历史与反事实模式不双算；来源ID与顺序保持 |
| `tests/evaluation/test_stability_report.py` | 0样本/partial/loss/skipped/label缺失 →不PASS；故障case→报告→root/节点/entity定位；branch/root分母准确；LLM重复分布 |
| `dashboard/tests/internal-flow-navigation.spec.ts` | process目录→run→span→对象→关联run→experiment失败case；有DOM交互、旧schema、缺spec、加载进度和unknown可见 |

[inferred] 另外需要browser端到端smoke、真实native Rust集成、受控NoneBot入口smoke、长跑/10k事件布局/100k消息数据集性能、最终打包spec资源校验。它们不属于本轮已经运行的检查。新CLI/新测试命令在其实现后补入CI，不将不存在的命令列成已验证命令。

## 9. Risk and Impact Analysis

### 9.1 已有graph直接依赖的完整处置

[graph] `_emit_event` risk **CRITICAL**：depth1六项 `_emit_span_start`、`checkpoint`、`decision`、`end_trace`、`link`、`FlowSpan.finish` 均位于 `message_flow.py`。它们全部必须保持字段/序列/幂等/脱敏合同，并覆盖WebUI、runtime、gateway后台和Cometa消费者；不能用riskSharedAxes=MEDIUM降低CRITICAL警告。

[graph] `process_new_candidates` risk **HIGH**：depth1十五项为生产 `MemoryConsolidator.consolidate_group` 与下列14测试。全部纳入晋升回归，不能只跑新observability测试：

- `tests/test_candidate_reinforcement.py`：test_reoccurrence_eventually_promotes_end_to_end、test_stale_observing_candidate_rejected。
- `tests/test_memory_manager.py`：test_high_value_candidate_becomes_confirmed_memory、test_low_value_candidate_goes_to_observing。
- `tests/test_memory_manager_fts_sync.py`：test_fts_disabled_means_no_index_and_query_falls_back、test_fts_index_stays_in_sync_after_promotion、test_fts_index_sync_after_merge_updates_content。
- `tests/test_memory_manager_v2.py`：test_candidate_meta_fields_persisted、test_conflict_marks_old_memory。
- `tests/test_memory_promotion_deadlock.py`：test_zero_importance_candidate_now_promotes。
- `tests/test_memory_rust_promotion.py`：test_auto_falls_back_to_python_after_rust_runtime_failure、test_rust_promotion_keeps_observing_gate_in_python、test_rust_promotion_receives_bounded_request_and_runs_hooks_once、test_strict_rust_runtime_failure_is_not_swallowed。

[graph] `observe` risk **HIGH**：六个depth1分别为 gateway record_group_chat；benchmark runner.run；`tests/test_participation.py` 的feed、observe；`tests/test_participation_timing.py` 的feed、test_share_and_novelty_off_by_default。真实消息与benchmark规则共享，逐项验证timing/disable/default配置不变。

[graph] `build_manifest` risk LOW：depth1 main 与 `tests/observability/test_message_flow_contract.py` 的manifest fixture，升级目录生成合同必须更新这两个调用面及发行读取合同。

[inferred] 以上impact只代表当前查询边界，执行代理对任何新触及符号仍须重新impact，不准用此表覆盖新增符号。无caller/UNKNOWN需文本/运行补证，提交前detect_changes；partial/truncated必须重跑。

### 9.2 主要工程风险与控制

| 风险 | 控制与可审查证据 |
|---|---|
| 观测改变锁/事务/模型排队 | 业务fail-open；不在热路径flush；语义profile开关等价测试；lock wait与模型gate分别记录；p95/throughput测量 |
| 全量statement导致事件爆炸 | 静态全目录与运行profile分开；详细profile按模块/run；bounded队列/硬容量/TTL；采样率、gap显式记录，不伪完整 |
| SQLite migration与WAL/多worker | additive migration、schema版本、幂等、可回滚reader；run/incarnation标识；writer/fault/restart测试；experiment独立进程/库 |
| 事务未提交却显示已晋升 | attempted/committed分离；commit后事实或事务outbox；Python/Rust各自实际边界；after-hook失败不回滚显示 |
| 隐私与实验误触生产 | summary全渠道脱敏；dataset伪名与权限；只读一致性export；sandbox绝对路径校验；fake sender/tool；无网络默认配置 |
| 图覆盖分母虚假 | source closure、动态registry、boundary、PDG与AST对账；抽样processes不能当全集；unknown不自动排除 |
| 历史拓扑漂移 | content digest不可变；archive先于引用；alias不改旧事实；保留/打包/旧schema验收 |
| 数据集误判稳定 | 0样本不足、覆盖门槛、观测完整性门槛；自然分布与重点集分开；snapshot cutoff与反事实反馈限制；真实模型重复试验 |
| 迁移过程中双写/事件重复 | event_id与run sequence幂等；legacy adapter；断线补读去重；对象履历不重复应用业务副作用 |

## 10. Files Expected to Change

[inferred] 下表是实施范围，不是本轮已修改文件。现有锚点均经源代码核验；其他流程细节在M0补闭包后再明确改动symbol。新文件路径为建议，尚不存在。

| 文件 | 当前锚点/拟新增对象 | 责任与依赖 |
|---|---|---|
| `core/observability/message_flow.py` | begin_trace/end_trace/_emit_event/FlowSpan/_Writer | M1可靠性、实例/状态/完整性增量schema；CRITICAL |
| `core/observability/flow_catalog.py` | NODES/TOPOLOGY_VERSION现有目录 | 兼容legacy；不可变digest与多process目录 |
| `scripts/generate_message_flow.py` | build_manifest/structural_features/main | AST/GitNexus闭包、source map/coverage/diff；正式生成基线最后刷新 |
| `core/observability/internal_flow_catalog.py`（新） | process root/semantic mapping registry（拟） | memory/proactive/后台语义根，动态boundary合同 |
| `core/observability/entity_history.py`（新） | committed entity event/query（拟） | 复用同库writer/认证，历史对象履历 |
| `memory/consolidator.py` | consolidate_group/_write_memory_candidates | 抽取/写入/批次消息来源/晋升与checkpoint边界；M2 |
| `memory/memory_manager.py` | process_new_candidates及已读gate/conflict/create/merge/quota | 逐候选、backend、事务/状态probe；HIGH |
| `memory_rust/native/src/promotion.rs` | promote与transaction/PromotionOutput | source目录与桥接返回摘要/clock；仅必要时增加native观测数据 |
| `memory/compressor.py` | run_weekly | 压缩各状态变更、统计与缓存失效；M2/M4 |
| `memory/retriever.py` | 已读FTS rebuild触发区域 | M0先补检索closure，M2记录检索/注入/访问状态与缓存 |
| `memory/participation/__init__.py` | observe/_score_with_embedding/note_stella_spoke/tick | 全等级决策/话题/score观测与clock；HIGH |
| `memory/participation/decision.py` | decide/模式及slot控制逻辑 | guard/slot before-after；移除业务逻辑的实时时钟漏洞 |
| `memory/participation/scorer.py` | 已读统一score与keyword/relevance计算 | 分项可解释、安全摘要，不复制评分规则 |
| `memory/proactive_target.py` | at_quota/can_at_user/_fetch_observing_candidate/pick_target | 候选淘汰原因、配额/冷却/选择事实 |
| `memory/timeutil.py` | utc_now/db_timestamp_str/seconds_since | 保持UTC合同，新增可注入Clock适配；SQL时钟同步 |
| `stella_project/plugins/bot_main/ai_gateway.py` | ingress、proactive相关函数及已读维护jobs | route/IO、timer前置root、主动发送/后处理、后台根；M1/M3/M4 |
| `memory/social_worker.py` | 已读lease/handler运行段 | job/effect/retry/dead roots；M0先锚定具体方法 |
| `stella_project/plugins/bot_main/scheduling/runtime.py` | tick_once/_execute_locked/_execute_agent | 租约/状态/取消/模型/发送运行关联，复用已有clock |
| `knowledge/ingest.py` | ingest_content/_build_version | 导入/embedding/version/ready；publish/index细节M0定位 |
| `cometa/worker.py` | 已读task-flow运行关联 | 复用task/attempt协议；其他executor/delivery编辑先M0补源码impact |
| `webui/services/flow.py`、`webui/routers/trace.py` | message_detail/message_io/events与SSE | live/IO/spec/分页/对象/跨run查询兼容 |
| `webui/routers/evaluation.py`、`webui/services/evaluation.py`（新） | 固定CLI job adapter/report（拟） | 认证、隔离实验创建/取消/查询；不执行任意代码 |
| `core/evaluation/{dataset,snapshot,clock,adapters,runner,report}.py`（新） | 隔离实验合同（拟） | 四模式、child process、虚拟时间、fixtures、故障/报告 |
| `scripts/run_flow_evaluation.py`（新） | 固定入口CLI（拟） | Dashboard/CI共用、无生产默认DB路径 |
| `dashboard/src/views/data/FlowPage.vue`、`flowLayout.ts` | 现有组件/实际布局 | M1事实修复，三层图、实例/对象/关联导航/回放/大图 |
| `dashboard/src/stores/flow.ts`、`flowReducer.ts` | openTrace/loadSpec/fetchEvents/startStream/projectNode | digest绑定、实例状态、分页/订阅生命周期 |
| `dashboard/src/api/{flow,sse,http}.ts` | 现有client与认证 | typed process/entity/experiment接口；401一致 |
| `dashboard/src/views/data/InternalFlowExperiments.vue`（新） | dataset/report UI（拟） | 实验摘要→case→run→实体；M6 |
| `dashboard/src/views/data/DataPage.vue`、`dashboard/src/router/index.ts` | 数据页tab/路由 | 复用旧flow入口，扩实验路由 |
| §8所列现有/新测试 | 行为场景 | 修旧错误断言；新全链路/隔离/完整度合同 |
| `.github/workflows/ci.yml`、`dashboard_ci.yml` | 当前manifest/test gate | Docker闭包对账，相关Python/Rust/目录变化触发前端合同；资源打包门禁 |
| `core/observability/flows/` | 最终生成manifest | M6统一刷新与历史digest保留，禁止手改伪造coverage |

## 11. Reusable Implementation Context

以下JSON是可供后续实施直接读取的context pack；evidence_provenance来自官方schema2 helper，未手工重算。符号未完整核验的后台子图明确留在M0，不要求重新全仓调查。

```json
{
  "implementation_context": {
    "task_summary": "Read-only audit verdict: previous message-flow plan PARTIAL. Implement trustworthy source-grounded internal flow console and isolated dataset stability evaluation; prioritize memory promotion and proactive speaking. This plan has not been implemented.",
    "acceptance_criteria": [
      "All O01-O10 observer/UI defects have correct-contract regression coverage and fixes.",
      "Versioned runtime entry inventory and GitNexus+AST reachable closure with every core call/guard/return/exception/spawn/state mutation represented; core unresolved=0; external/dynamic boundaries explicit.",
      "Memory candidate/promotion/maintenance/retrieval/verification lifecycle and actual backend/transaction facts navigable per entity.",
      "Participation all decisions, preflight proactive roots, sender receipts, acknowledged-only side effects and response/effect relations visible.",
      "Other runtime roots incl social/maintenance/scheduling/knowledge/Cometa and startup/shutdown mapped.",
      "Immutable spec digest archive; per-attempt states; factual transitions; unknown/loss/loading gaps visible; pagination/SSE lifecycle correct.",
      "Four experiment modes share production business rules via isolated process and injected dependencies; no production writes, real QQ sends, arbitrary tools.",
      "Frozen dataset/snapshot/clock/model/config provenance; no future leakage or historic/counterfactual double counting.",
      "No zero-sample PASS; coverage/integrity gates; reproducible fixture semantic results; repeat real-model distributions; failure report navigates to run/node/entity.",
      "Fault/native/browser/real-entry/performance/packaged-resource validation and CI source-drift gate satisfy section13."
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "4b089b5106f3b1945200058cad4047e7ca1cc221",
      "generated_plan_path": "docs/plans/2026-10-03-gitnexus-plan-stella-internal-flow-observability.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf"
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
          "head_digest": "sha256:f5b572c5faeccce6b1841229f53506d95ce88531ec9eb36a46c6529a95adab6b",
          "index_digest": "sha256:f5b572c5faeccce6b1841229f53506d95ce88531ec9eb36a46c6529a95adab6b",
          "worktree_digest": "sha256:6819a55a8acba2d2e9d62c7fdcbdae153854a57629f30fe3cf7cec0e38f397ac",
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
          "head_digest": "sha256:67491a0bc3d8a6af13b516eab9d8c3ede306ef2f6ae89f43812a6dc9e72cd780",
          "index_digest": "sha256:67491a0bc3d8a6af13b516eab9d8c3ede306ef2f6ae89f43812a6dc9e72cd780",
          "worktree_digest": "sha256:67491a0bc3d8a6af13b516eab9d8c3ede306ef2f6ae89f43812a6dc9e72cd780",
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
          "path": "cometa/worker.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:46dadc14283c1b415d739556e5eb52b1ec9bb645d7f7f6d186631cecbaa45f9f",
          "index_digest": "sha256:46dadc14283c1b415d739556e5eb52b1ec9bb645d7f7f6d186631cecbaa45f9f",
          "worktree_digest": "sha256:46dadc14283c1b415d739556e5eb52b1ec9bb645d7f7f6d186631cecbaa45f9f",
          "untracked_digest": "absent"
        },
        {
          "path": "config/settings.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1175723ed26c7174b5ce3f4b15f85443bc7dc636d2d61c8d001b5f6725b04aa7",
          "index_digest": "sha256:1175723ed26c7174b5ce3f4b15f85443bc7dc636d2d61c8d001b5f6725b04aa7",
          "worktree_digest": "sha256:8a805cd14a7705c1db143020f0e22d543b8100b35def6526d4dd2e0ce27084ea",
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
          "head_digest": "sha256:fa973e0c02a0e7b3ec62cead3976a5fcf9fe9834361216411b7449c95fb0e140",
          "index_digest": "sha256:fa973e0c02a0e7b3ec62cead3976a5fcf9fe9834361216411b7449c95fb0e140",
          "worktree_digest": "sha256:fa973e0c02a0e7b3ec62cead3976a5fcf9fe9834361216411b7449c95fb0e140",
          "untracked_digest": "absent"
        },
        {
          "path": "core/observability/flows/message-flow.651a7719add8.json",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:92dda5f1f765aa37b516d0097955a0f1b4c563d5ed617ffa0ac381d687d5eb00",
          "index_digest": "sha256:92dda5f1f765aa37b516d0097955a0f1b4c563d5ed617ffa0ac381d687d5eb00",
          "worktree_digest": "sha256:3d0fe75b3393b337c11c9d046826d1433c5e79e887219a59bf3b57a854a27e3b",
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
          "head_digest": "sha256:ad5f263d2c219ddcd06c7a2364ffdfbf461487ed04a09ca67fa924461b343838",
          "index_digest": "sha256:ad5f263d2c219ddcd06c7a2364ffdfbf461487ed04a09ca67fa924461b343838",
          "worktree_digest": "sha256:ad5f263d2c219ddcd06c7a2364ffdfbf461487ed04a09ca67fa924461b343838",
          "untracked_digest": "absent"
        },
        {
          "path": "core/observability/turn_trace.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:909a2261c315b4bf6199bee78361c00df7cde7a8d5b3f4f0ff28b7cceb73f5cd",
          "index_digest": "sha256:909a2261c315b4bf6199bee78361c00df7cde7a8d5b3f4f0ff28b7cceb73f5cd",
          "worktree_digest": "sha256:6c30ac556bfcc599480da02b38dde8ccb2be551b245686c6f50ee574bd203fe8",
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
          "head_digest": "sha256:605c557bd888e890903c9056f88f1e16b5ff2c305b1834eac0319ad74c4f6c29",
          "index_digest": "sha256:605c557bd888e890903c9056f88f1e16b5ff2c305b1834eac0319ad74c4f6c29",
          "worktree_digest": "sha256:605c557bd888e890903c9056f88f1e16b5ff2c305b1834eac0319ad74c4f6c29",
          "untracked_digest": "absent"
        },
        {
          "path": "dashboard/src/api/http.ts",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a8bc916e12c71ccfd17fab63508e3b8bfff0fa0e123e999a73e67b0b86545e8e",
          "index_digest": "sha256:a8bc916e12c71ccfd17fab63508e3b8bfff0fa0e123e999a73e67b0b86545e8e",
          "worktree_digest": "sha256:1c0cc17957d50384ff450244144c6ebf326b49b1431aa2b1a03222834baaa9ad",
          "untracked_digest": "absent"
        },
        {
          "path": "dashboard/src/api/sse.ts",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4338d79305111c00d0279aa98c1200cf829e56aa6f44aa2faa3505605b431ed1",
          "index_digest": "sha256:4338d79305111c00d0279aa98c1200cf829e56aa6f44aa2faa3505605b431ed1",
          "worktree_digest": "sha256:27c3705ad6821faba1c1e7ba6318a264e6b7b99d1b505e99ab4d1a704920999e",
          "untracked_digest": "absent"
        },
        {
          "path": "dashboard/src/router/index.ts",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:455de26c8a2c8f921c05ba57031c4106b7a7403e06bcf7c564f868789acad666",
          "index_digest": "sha256:455de26c8a2c8f921c05ba57031c4106b7a7403e06bcf7c564f868789acad666",
          "worktree_digest": "sha256:455de26c8a2c8f921c05ba57031c4106b7a7403e06bcf7c564f868789acad666",
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
          "head_digest": "sha256:1612918b447e329af3875dc85b555e1a224b7af9a3a51385333b985125dbd9b9",
          "index_digest": "sha256:1612918b447e329af3875dc85b555e1a224b7af9a3a51385333b985125dbd9b9",
          "worktree_digest": "sha256:1612918b447e329af3875dc85b555e1a224b7af9a3a51385333b985125dbd9b9",
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
          "head_digest": "sha256:76e0650793445e21941b00a00f17726d4cde9f6f635e46923f0e321daa99efa8",
          "index_digest": "sha256:76e0650793445e21941b00a00f17726d4cde9f6f635e46923f0e321daa99efa8",
          "worktree_digest": "sha256:76e0650793445e21941b00a00f17726d4cde9f6f635e46923f0e321daa99efa8",
          "untracked_digest": "absent"
        },
        {
          "path": "dashboard/src/views/data/DataPage.vue",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b10fe86afca4a7e3d91dbaa51545b7fad3269bd23e6bf15415116715077be209",
          "index_digest": "sha256:b10fe86afca4a7e3d91dbaa51545b7fad3269bd23e6bf15415116715077be209",
          "worktree_digest": "sha256:b10fe86afca4a7e3d91dbaa51545b7fad3269bd23e6bf15415116715077be209",
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
          "head_digest": "sha256:076452cd1ee33132c5fcd9c5d9b37fc907985065d56b26517175ba6b8023d4ba",
          "index_digest": "sha256:076452cd1ee33132c5fcd9c5d9b37fc907985065d56b26517175ba6b8023d4ba",
          "worktree_digest": "sha256:076452cd1ee33132c5fcd9c5d9b37fc907985065d56b26517175ba6b8023d4ba",
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
          "head_digest": "sha256:3a3433d4513338ba571a28b67c014017370c6c8324cdc753af0930b689da3c0d",
          "index_digest": "sha256:3a3433d4513338ba571a28b67c014017370c6c8324cdc753af0930b689da3c0d",
          "worktree_digest": "sha256:3a3433d4513338ba571a28b67c014017370c6c8324cdc753af0930b689da3c0d",
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
          "head_digest": "sha256:9bd50464c74ac5afdf798d7f8f5523ffd2ab88e3cc84b3a50a64da5a04b04505",
          "index_digest": "sha256:9bd50464c74ac5afdf798d7f8f5523ffd2ab88e3cc84b3a50a64da5a04b04505",
          "worktree_digest": "sha256:9bd50464c74ac5afdf798d7f8f5523ffd2ab88e3cc84b3a50a64da5a04b04505",
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
          "head_digest": "sha256:102dc5e8d13b3642ce3f52514942e5ad0f679ad1cab41c817db828c31498138b",
          "index_digest": "sha256:102dc5e8d13b3642ce3f52514942e5ad0f679ad1cab41c817db828c31498138b",
          "worktree_digest": "sha256:102dc5e8d13b3642ce3f52514942e5ad0f679ad1cab41c817db828c31498138b",
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
          "head_digest": "sha256:7695697b8c6f898e84940202d8a1320268b5ef747ce552ad8fbc99d164338911",
          "index_digest": "sha256:7695697b8c6f898e84940202d8a1320268b5ef747ce552ad8fbc99d164338911",
          "worktree_digest": "sha256:7695697b8c6f898e84940202d8a1320268b5ef747ce552ad8fbc99d164338911",
          "untracked_digest": "absent"
        },
        {
          "path": "dashboard/vitest.config.ts",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:90dd1e4911d5be9fc776e0d78f1a8101d97dc428e800cc2ff95d59b0a5dedf20",
          "index_digest": "sha256:90dd1e4911d5be9fc776e0d78f1a8101d97dc428e800cc2ff95d59b0a5dedf20",
          "worktree_digest": "sha256:90dd1e4911d5be9fc776e0d78f1a8101d97dc428e800cc2ff95d59b0a5dedf20",
          "untracked_digest": "absent"
        },
        {
          "path": "docs/plans/2026-10-02-gitnexus-plan-message-processing-flow.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:da91d0a78391ed8c351a188b593948c09b7e821ca4c1d35653d933aa3971b310",
          "index_digest": "sha256:da91d0a78391ed8c351a188b593948c09b7e821ca4c1d35653d933aa3971b310",
          "worktree_digest": "sha256:da91d0a78391ed8c351a188b593948c09b7e821ca4c1d35653d933aa3971b310",
          "untracked_digest": "absent"
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
          "head_digest": "sha256:d07ffb69890d7145f83802362c47d5d823ec0d7befc97a593fcc81e44894ddce",
          "index_digest": "sha256:d07ffb69890d7145f83802362c47d5d823ec0d7befc97a593fcc81e44894ddce",
          "worktree_digest": "sha256:a873b9e9f872b06ed0fdfc2146da73604d06ab02c3a645b0987aa314d9f40196",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/benchmark.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f55edfd8484eb60e3ba3373609f75bd9c8192c4f3d9276aced27f6fb68535c20",
          "index_digest": "sha256:f55edfd8484eb60e3ba3373609f75bd9c8192c4f3d9276aced27f6fb68535c20",
          "worktree_digest": "sha256:ade1a6917bbb73f38d3a62bda73a08556ed8fdeb92522236fb5c2b874aba272a",
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
          "head_digest": "sha256:e715131c52b6da24b3d08e75d8df7b3e989029b74be8ebc2d85622d3e742ea20",
          "index_digest": "sha256:e715131c52b6da24b3d08e75d8df7b3e989029b74be8ebc2d85622d3e742ea20",
          "worktree_digest": "sha256:ffb546997d6b698042c1dab95b7fa466fe765a1908a4adc7ba46d451cb8c078f",
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
          "head_digest": "sha256:a5187c795131bb86aedd5e00e8584dbbdd2b6aec8fd809b6b0b3b2672dd8e1ab",
          "index_digest": "sha256:a5187c795131bb86aedd5e00e8584dbbdd2b6aec8fd809b6b0b3b2672dd8e1ab",
          "worktree_digest": "sha256:a5187c795131bb86aedd5e00e8584dbbdd2b6aec8fd809b6b0b3b2672dd8e1ab",
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
          "head_digest": "sha256:e78e5c0e30d73a7c9acc38f0406af05e85bee5ce6e01dc32a3917a11e38b57cd",
          "index_digest": "sha256:e78e5c0e30d73a7c9acc38f0406af05e85bee5ce6e01dc32a3917a11e38b57cd",
          "worktree_digest": "sha256:a4e833cae1098845df9e5651720bea5976a01250822ec10a625c4b681b0f9490",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/participation/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3ab5b8f3594f1fac65fda45f8803c74d3055614585906301d984a78a6fb75ff6",
          "index_digest": "sha256:3ab5b8f3594f1fac65fda45f8803c74d3055614585906301d984a78a6fb75ff6",
          "worktree_digest": "sha256:b07db83d86c3297b5da886132ac9671b1db95ecade2f0138cb487c94e7371561",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/participation/decision.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3987f3bb8aaec46cfe3b9104e5c814a891300adf004771135015a53bf2d01308",
          "index_digest": "sha256:3987f3bb8aaec46cfe3b9104e5c814a891300adf004771135015a53bf2d01308",
          "worktree_digest": "sha256:2fe56ff06e3aec668ca93da7921300c323d8615d52c7806c68ebc5d1215803d2",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/participation/scorer.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:56ff65f8f79c2f512dfa736ca40cadc9066aad1552571f9259e36c8b399e96ed",
          "index_digest": "sha256:56ff65f8f79c2f512dfa736ca40cadc9066aad1552571f9259e36c8b399e96ed",
          "worktree_digest": "sha256:73be30345323c8d5cc7c566879ca87c26479945b4f3608e1a7cf52084e8d0a8b",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive_target.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:80badcbdb304dbe2c1ea8117aec9993cb4ceff0de738b3e740e79e76f044ce94",
          "index_digest": "sha256:80badcbdb304dbe2c1ea8117aec9993cb4ceff0de738b3e740e79e76f044ce94",
          "worktree_digest": "sha256:a4cbf02b07d3af0f745d30c2e426ab90898d85c97ce5eff8a36ee1caf965b09f",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/retriever.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8ed809ea232638e45b84e9a87c3d4bb1ab1b147cc695da3369c0085d09ef21a5",
          "index_digest": "sha256:8ed809ea232638e45b84e9a87c3d4bb1ab1b147cc695da3369c0085d09ef21a5",
          "worktree_digest": "sha256:7b8319e05efb04a936aaccfd7936766272c04245ccfd8ec09f7e9c08ed1cf3e0",
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
          "head_digest": "sha256:447b2e99feb56b5fe14682d3739917c9fbb8d79f5095095faf38cdf887a2c56d",
          "index_digest": "sha256:447b2e99feb56b5fe14682d3739917c9fbb8d79f5095095faf38cdf887a2c56d",
          "worktree_digest": "sha256:16f02cfde3588dee21be127398c59b6fc8226f8e134c6b47a93ab4d03cacdf1b",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/timeutil.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9a52089068112c21ac0fe00de29973aab15b060c71fa82804bd1cc33fc303776",
          "index_digest": "sha256:9a52089068112c21ac0fe00de29973aab15b060c71fa82804bd1cc33fc303776",
          "worktree_digest": "sha256:9a52089068112c21ac0fe00de29973aab15b060c71fa82804bd1cc33fc303776",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/benchmark.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:96868fd2e07051b50ab88e8794d36ee7f42ed0c84b4cc3bb524e5461029d4a46",
          "index_digest": "sha256:96868fd2e07051b50ab88e8794d36ee7f42ed0c84b4cc3bb524e5461029d4a46",
          "worktree_digest": "sha256:58c04433bbf7522178403c400cf43813c3ddb0fd62d6d154a6c41986352a90ee",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/native/src/promotion.rs",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:493599face26ef26ec46cb491cca21084e5e036bbca55f564c41d34516f7f4de",
          "index_digest": "sha256:493599face26ef26ec46cb491cca21084e5e036bbca55f564c41d34516f7f4de",
          "worktree_digest": "sha256:a0b8eb11f325a79127b3f86c091bb7c2076602adf308da3ffb3b13460d166d93",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/build_embedding_fixture.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2155be99ac08e0d039e72419c9ce066ba75b984f56ec95a01154262fb5583778",
          "index_digest": "sha256:2155be99ac08e0d039e72419c9ce066ba75b984f56ec95a01154262fb5583778",
          "worktree_digest": "sha256:2155be99ac08e0d039e72419c9ce066ba75b984f56ec95a01154262fb5583778",
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
          "head_digest": "sha256:76eaf5042114edc827e23c86749ad4fc3f759c8245b0edfbb43f3b33a1442974",
          "index_digest": "sha256:76eaf5042114edc827e23c86749ad4fc3f759c8245b0edfbb43f3b33a1442974",
          "worktree_digest": "sha256:76eaf5042114edc827e23c86749ad4fc3f759c8245b0edfbb43f3b33a1442974",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/probe_consolidation.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a0db3936a26a7017cb04e6f9046315475b8e40e1ef12d74ead38f21528e25cef",
          "index_digest": "sha256:a0db3936a26a7017cb04e6f9046315475b8e40e1ef12d74ead38f21528e25cef",
          "worktree_digest": "sha256:9e78d3f359e9af40473bf9f732b2a8c17d51320bd5b2f773a5c97e8265b8d4bd",
          "untracked_digest": "absent"
        },
        {
          "path": "scripts/sample_windows.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4c1ae780247713a524c856aaa314b295130eca57460e4ca23fa74629f23449b0",
          "index_digest": "sha256:4c1ae780247713a524c856aaa314b295130eca57460e4ca23fa74629f23449b0",
          "worktree_digest": "sha256:4c1ae780247713a524c856aaa314b295130eca57460e4ca23fa74629f23449b0",
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
          "head_digest": "sha256:0427caac14b95a93e5a414680547a27d910d3c050a70acdcf29480bd4ddd73dd",
          "index_digest": "sha256:0427caac14b95a93e5a414680547a27d910d3c050a70acdcf29480bd4ddd73dd",
          "worktree_digest": "sha256:0427caac14b95a93e5a414680547a27d910d3c050a70acdcf29480bd4ddd73dd",
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
          "head_digest": "sha256:4151e88bb1974a83851b6062ae539aa0e3338840b4607183c46af6cba369f501",
          "index_digest": "sha256:4151e88bb1974a83851b6062ae539aa0e3338840b4607183c46af6cba369f501",
          "worktree_digest": "sha256:f8847f43b172a1bc8ca4e768bf0b313114ea5a01d945a48fec3a0eaceb68dbe0",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/benchmark/participation/metrics.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:57221d0aff8b69ed6143a974e284cdcec045026a4972d7a81851d4691f0d96e3",
          "index_digest": "sha256:57221d0aff8b69ed6143a974e284cdcec045026a4972d7a81851d4691f0d96e3",
          "worktree_digest": "sha256:57221d0aff8b69ed6143a974e284cdcec045026a4972d7a81851d4691f0d96e3",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/benchmark/participation/runner.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:37ab739b3537048c6c9b4d645a8ba7098644ea6e8696bd49eec7fe4d94447577",
          "index_digest": "sha256:37ab739b3537048c6c9b4d645a8ba7098644ea6e8696bd49eec7fe4d94447577",
          "worktree_digest": "sha256:37ab739b3537048c6c9b4d645a8ba7098644ea6e8696bd49eec7fe4d94447577",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/conftest.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e20d97e3ef0051d0165b00f4b683616527b35ac992549e7c672f61a8e14323eb",
          "index_digest": "sha256:e20d97e3ef0051d0165b00f4b683616527b35ac992549e7c672f61a8e14323eb",
          "worktree_digest": "sha256:2c95f7957354c00456481799de8e030782187d424bfa308ce96bc79b0be975d2",
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
          "head_digest": "sha256:e455f9609d091c1115971aa9cb9fc130213d788fb5a7003ec245ead6630bd0ab",
          "index_digest": "sha256:e455f9609d091c1115971aa9cb9fc130213d788fb5a7003ec245ead6630bd0ab",
          "worktree_digest": "sha256:e455f9609d091c1115971aa9cb9fc130213d788fb5a7003ec245ead6630bd0ab",
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
          "head_digest": "sha256:3507fd72ea7e147adeae55d152ff4f8f1118d0eddab2ce465309e6d87b5f49af",
          "index_digest": "sha256:3507fd72ea7e147adeae55d152ff4f8f1118d0eddab2ce465309e6d87b5f49af",
          "worktree_digest": "sha256:3507fd72ea7e147adeae55d152ff4f8f1118d0eddab2ce465309e6d87b5f49af",
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
          "path": "tests/test_candidate_reinforcement.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:fd790edd308310d58b3857f2e509e79a335cdc7668d0dacf714a8130f8ca7fd5",
          "index_digest": "sha256:fd790edd308310d58b3857f2e509e79a335cdc7668d0dacf714a8130f8ca7fd5",
          "worktree_digest": "sha256:fd790edd308310d58b3857f2e509e79a335cdc7668d0dacf714a8130f8ca7fd5",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_memory_manager_v2.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e4ae5c2fdf19db0ac033b72a8a8164cf8b55e61ef351f735f757eefc1bdbadb0",
          "index_digest": "sha256:e4ae5c2fdf19db0ac033b72a8a8164cf8b55e61ef351f735f757eefc1bdbadb0",
          "worktree_digest": "sha256:e4ae5c2fdf19db0ac033b72a8a8164cf8b55e61ef351f735f757eefc1bdbadb0",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_memory_rust_promotion.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
          "index_digest": "sha256:9d4202785baeebcb029856bc541110eea8fd71490d00b9615f39784b172de4ff",
          "worktree_digest": "sha256:38b041bc5f48b796dc5791d3c32994a4e2682c7a4afffa47159851f803d55c76",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/webui/conftest.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6189087305aa91eddce0fa190370a01c82253b918e6d58ec21fa431e06eb7604",
          "index_digest": "sha256:6189087305aa91eddce0fa190370a01c82253b918e6d58ec21fa431e06eb7604",
          "worktree_digest": "sha256:c0ebe583232b78cead95cf141dd3e502a7c1af7e89d172dc1acbedff3e2207e3",
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
          "head_digest": "sha256:61d606fe6d81787173edf5d0c79abe5ace13089228bc7d5d77a51f65b3118517",
          "index_digest": "sha256:61d606fe6d81787173edf5d0c79abe5ace13089228bc7d5d77a51f65b3118517",
          "worktree_digest": "sha256:61d606fe6d81787173edf5d0c79abe5ace13089228bc7d5d77a51f65b3118517",
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
          "head_digest": "sha256:2e966ff96325978a2d7300f37da26ffdbc5e414b7839decc2c974d503921b94f",
          "index_digest": "sha256:2e966ff96325978a2d7300f37da26ffdbc5e414b7839decc2c974d503921b94f",
          "worktree_digest": "sha256:2e966ff96325978a2d7300f37da26ffdbc5e414b7839decc2c974d503921b94f",
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
          "head_digest": "sha256:575ff80338d17ad016a909a23a04b45270690d9b26a754e8415cac44ce403159",
          "index_digest": "sha256:575ff80338d17ad016a909a23a04b45270690d9b26a754e8415cac44ce403159",
          "worktree_digest": "sha256:575ff80338d17ad016a909a23a04b45270690d9b26a754e8415cac44ce403159",
          "untracked_digest": "absent"
        },
        {
          "path": "webui/services/trace.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1f28f669a2151d2f3aea001a6eeb2059d1e0dfece1696c47c2974d36f496abea",
          "index_digest": "sha256:1f28f669a2151d2f3aea001a6eeb2059d1e0dfece1696c47c2974d36f496abea",
          "worktree_digest": "sha256:0545272fbedfdfb8b418bf2cdadfffd70b22b57baa4d01283b973dc0464fe1c9",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "_emit_event",
        "file": "core/observability/message_flow.py",
        "lines": "560-583",
        "role": "CRITICAL shared event writer; safe summary, sequence, integrity schema"
      },
      {
        "symbol": "end_trace",
        "file": "core/observability/message_flow.py",
        "lines": "500-548",
        "role": "Producer close currently calculates completeness before async persistence failure"
      },
      {
        "symbol": "build_manifest",
        "file": "scripts/generate_message_flow.py",
        "lines": "130-183",
        "role": "Current manual catalog hashing; planned source closure compiler"
      },
      {
        "symbol": "process_new_candidates",
        "file": "memory/memory_manager.py",
        "lines": "102-142",
        "role": "HIGH backend selection and candidate batch root"
      },
      {
        "symbol": "_process_new_candidates_python",
        "file": "memory/memory_manager.py",
        "lines": "237-335",
        "role": "Gate/conflict/merge/create/confirmation/commit/post-commit boundary"
      },
      {
        "symbol": "_decide_promotion",
        "file": "memory/memory_manager.py",
        "lines": "354-394",
        "role": "Importance/confidence/source/occurrence guard facts"
      },
      {
        "symbol": "consolidate_group",
        "file": "memory/consolidator.py",
        "lines": "586-755",
        "role": "Consumed-message window, extraction stages, writes, promotion and checkpoint"
      },
      {
        "symbol": "_write_memory_candidates",
        "file": "memory/consolidator.py",
        "lines": "1102-1289",
        "role": "Gate3, normalization, reinforcement and source evidence"
      },
      {
        "symbol": "promote",
        "file": "memory_rust/native/src/promotion.rs",
        "lines": "623-646",
        "role": "Native immediate transaction; explicit cross-language boundary"
      },
      {
        "symbol": "observe",
        "file": "memory/participation/__init__.py",
        "lines": "194-298",
        "role": "HIGH full participation/topic/score decision observability"
      },
      {
        "symbol": "decide",
        "file": "memory/participation/decision.py",
        "lines": "90-181",
        "role": "Threshold/streak/backoff; time.time at122 must use business clock"
      },
      {
        "symbol": "_proactive_at_user",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "2289-2432",
        "role": "Candidate verification preflight through confirmed delivery/response window"
      },
      {
        "symbol": "_proactive_speak_impl",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "2681-2905",
        "role": "Group proactive gates, generation, stale/naturalness/duplicate filters, receipts and after effects"
      },
      {
        "symbol": "proactive_speak_job",
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "lines": "2912-2942",
        "role": "Timer prioritizes memory verification; participation enabled skips dice path"
      },
      {
        "symbol": "openTrace/loadSpec",
        "file": "dashboard/src/stores/flow.ts",
        "lines": "140-190",
        "role": "Immutable digest binding and fast switch lifecycle"
      },
      {
        "symbol": "projectNode",
        "file": "dashboard/src/stores/flowReducer.ts",
        "lines": "45-84",
        "role": "Instance first projection; running after prior success"
      },
      {
        "symbol": "layoutExecuted",
        "file": "dashboard/src/views/data/flowLayout.ts",
        "lines": "80-127",
        "role": "Unknown node visibility and real instance edges"
      }
    ],
    "related_symbols": [
      {
        "symbol": "_emit_span_start,checkpoint,decision,end_trace,link,FlowSpan.finish",
        "relationship": "CALLS _emit_event (6 depth1)",
        "relevance": "Full direct-call compatibility; critical observer changes"
      },
      {
        "symbol": "consolidate_group +14 tests listed in section9",
        "relationship": "CALLS process_new_candidates (15 depth1)",
        "relevance": "High-risk memory behavior, backend, FTS, TTL, reinforcement and deadlock regression"
      },
      {
        "symbol": "record_group_chat, participation benchmark run, 4 test helpers/cases listed in section9",
        "relationship": "CALLS observe (6 depth1)",
        "relevance": "Same production rules and virtual-time benchmark; disable/default modes"
      },
      {
        "symbol": "main, manifest test fixture",
        "relationship": "CALLS build_manifest (2 depth1)",
        "relevance": "Source closure generation and contract checks"
      },
      {
        "symbol": "MemoryCompressor.run_weekly",
        "relationship": "post-promotion/scheduled maintenance",
        "relevance": "Merge/atomize/archive/decay/commit/cache lifecycle"
      },
      {
        "symbol": "tick_once/_execute_locked/_execute_agent",
        "relationship": "scheduled runtime established pattern",
        "relevance": "Reuse lease/claim/recovery/clock/fence contracts"
      },
      {
        "symbol": "ingest_content/_build_version",
        "relationship": "knowledge import lifecycle",
        "relevance": "ready is not published; publication/index closure pending M0"
      },
      {
        "symbol": "CometaWorker task flow linkage",
        "relationship": "existing run/task source_key correlation",
        "relevance": "Reuse task/attempt and result/notification separation"
      }
    ],
    "execution_path": [
      "M0 pin source + fresh graph + runtime entry inventory + correct-contract repros for O01-O10.",
      "M1 observer integrity/spec/IO migration and factual instances/transitions; fix frontend lifecycle.",
      "M2 memory consolidation -> candidates -> per-candidate backend/gates -> mutation/transaction -> post-commit -> object history.",
      "M3 participation all decisions -> timer/verify-user/group preflight -> shared turn -> actual delivery -> confirmed-only accounting -> effects/verification.",
      "M4 remaining roots and source/symbol/statement layers, navigation, retention and performance.",
      "M5 isolated child-process experiments with frozen inputs, clock and adapters; four explicit modes.",
      "M6 stability/diff reports, browser/real-entry/native/long-run tests, final manifests and package/CI gate."
    ],
    "pdg_constraints": [
      {
        "description": "Controls 142 manager results; backend choice and fallback guards remain business-equivalent.",
        "affected_statements": [
          "memory/memory_manager.py:111",
          "memory/memory_manager.py:116",
          "memory/memory_manager.py:122"
        ],
        "implementation_consequence": "Record actual backend/fallback, strict errors must propagate; no observer lock changes."
      },
      {
        "description": "similarity guard controls merge versus create+quota.",
        "affected_statements": [
          "memory/memory_manager.py:303",
          "memory/memory_manager.py:304",
          "memory/memory_manager.py:306"
        ],
        "implementation_consequence": "Factual branch transition; quota only actual branch, not endpoint inference."
      },
      {
        "description": "Source-verified confirmation/commit then cache/compress; native transaction differs.",
        "affected_statements": [
          "memory/memory_manager.py:314",
          "memory/memory_manager.py:320",
          "memory/memory_manager.py:327",
          "memory/memory_manager.py:333",
          "memory_rust/native/src/promotion.rs:623"
        ],
        "implementation_consequence": "attempted/committed/rollback facts; post-hook errors do not falsify committed business state."
      },
      {
        "description": "Controls 27 participation decision results; streak, topic reset, strong-hook and backoff.",
        "affected_statements": [
          "memory/participation/decision.py:118",
          "memory/participation/decision.py:122",
          "memory/participation/decision.py:139",
          "memory/participation/decision.py:145"
        ],
        "implementation_consequence": "Record slot before/after and inject all business clocks incl direct time.time and SQL time."
      },
      {
        "description": "end_trace completeness default guard occurs before actual writer persistence outcome.",
        "affected_statements": [
          "core/observability/message_flow.py:536",
          "core/observability/message_flow.py:303"
        ],
        "implementation_consequence": "Writer per-trace acknowledgements/loss correction; producer close is not persisted complete."
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "Bounded non-blocking observer and fail-open business paths",
        "example_location": "core/observability/message_flow.py _Writer",
        "usage_guidance": "Preserve bounded submit, add per-run integrity and sanitization; avoid sync flush in chat hot path."
      },
      {
        "pattern": "Independent roots and many-to-many relations",
        "example_location": "core/observability/message_flow.py link",
        "usage_guidance": "Correlate actual consumed message/entity IDs; root closure independent of async child completion."
      },
      {
        "pattern": "Existing model/turn runtime",
        "example_location": "stella_project/plugins/bot_main/ai_gateway.py _run_turn_via_engine callers",
        "usage_guidance": "Reuse current runtime with adapters, do not duplicate business pipeline in evaluator."
      },
      {
        "pattern": "Explicit UTC parse and monotonic timing",
        "example_location": "memory/timeutil.py and message_flow.py",
        "usage_guidance": "Virtual business clock incl SQL/Rust; real monotonic observer duration remains separate."
      },
      {
        "pattern": "SQLite worker leases, claim, recovery and fences",
        "example_location": "stella_project/plugins/bot_main/scheduling/runtime.py tick_once",
        "usage_guidance": "Reuse existing job/task state protocols and expose lifecycle facts; evaluation gets isolated store."
      }
    ],
    "files_to_modify": [
      {
        "file": "core/observability/message_flow.py",
        "symbols": [
          "begin_trace",
          "end_trace",
          "_emit_event",
          "FlowSpan",
          "_Writer"
        ],
        "intended_change": "M1 reliable integrity, additive schema, instances, relations and safe strings"
      },
      {
        "file": "core/observability/flow_catalog.py",
        "symbols": [
          "NODES",
          "TOPOLOGY_VERSION"
        ],
        "intended_change": "Legacy mapping and immutable multiple process catalogs"
      },
      {
        "file": "scripts/generate_message_flow.py",
        "symbols": [
          "build_manifest",
          "structural_features",
          "main"
        ],
        "intended_change": "Entry inventory, GitNexus+AST closure, coverage/source map/semantic diff"
      },
      {
        "file": "core/observability/internal_flow_catalog.py",
        "symbols": [],
        "intended_change": "NEW semantic process/boundary registry"
      },
      {
        "file": "core/observability/entity_history.py",
        "symbols": [],
        "intended_change": "NEW append-only committed entity history using current writer"
      },
      {
        "file": "memory/consolidator.py",
        "symbols": [
          "consolidate_group",
          "_write_memory_candidates"
        ],
        "intended_change": "M2 extraction, evidence, batch consumption and checkpoint facts"
      },
      {
        "file": "memory/memory_manager.py",
        "symbols": [
          "process_new_candidates",
          "_decide_promotion",
          "_resolve_conflicts",
          "_create_memory",
          "_merge_into_memory",
          "_enforce_user_quota"
        ],
        "intended_change": "M2 per-candidate gates/actual transaction/backend and object history"
      },
      {
        "file": "memory_rust/native/src/promotion.rs",
        "symbols": [
          "promote"
        ],
        "intended_change": "Explicit native transaction mappings and only necessary bounded result trace"
      },
      {
        "file": "memory/compressor.py",
        "symbols": [
          "run_weekly"
        ],
        "intended_change": "Memory maintenance state history"
      },
      {
        "file": "memory/retriever.py",
        "symbols": [],
        "intended_change": "M0 complete exact source/impact first; M2 retrieval/FTS/cache/injection facts"
      },
      {
        "file": "memory/participation/__init__.py",
        "symbols": [
          "observe",
          "_score_with_embedding",
          "note_stella_spoke",
          "tick"
        ],
        "intended_change": "M3 all levels/topic/score and clock"
      },
      {
        "file": "memory/participation/decision.py",
        "symbols": [
          "decide"
        ],
        "intended_change": "Slot/guard facts, business clock"
      },
      {
        "file": "memory/participation/scorer.py",
        "symbols": [],
        "intended_change": "Source-verified score regions; M0 exact edit symbol re-anchor first"
      },
      {
        "file": "memory/proactive_target.py",
        "symbols": [
          "at_quota",
          "can_at_user",
          "_fetch_observing_candidate",
          "pick_target"
        ],
        "intended_change": "Selection, quota, cooldown and noop reasons"
      },
      {
        "file": "memory/timeutil.py",
        "symbols": [
          "utc_now",
          "db_timestamp_str",
          "seconds_since"
        ],
        "intended_change": "UTC-compatible clock adapter"
      },
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "_proactive_at_user",
          "_proactive_speak_for_group",
          "_proactive_speak_impl",
          "proactive_speak_job"
        ],
        "intended_change": "Ingress route/IO, preflight, receipts/after effects and background roots"
      },
      {
        "file": "memory/social_worker.py",
        "symbols": [],
        "intended_change": "M0 exact handler source re-anchor before edit; M4 job lease/retry/dead roots"
      },
      {
        "file": "stella_project/plugins/bot_main/scheduling/runtime.py",
        "symbols": [
          "tick_once",
          "_execute_locked",
          "_execute_agent"
        ],
        "intended_change": "Scheduled task lifecycle using existing protocols"
      },
      {
        "file": "knowledge/ingest.py",
        "symbols": [
          "ingest_content",
          "_build_version"
        ],
        "intended_change": "Import/version ready facts; M0 locate publish/index exact symbols"
      },
      {
        "file": "cometa/worker.py",
        "symbols": [],
        "intended_change": "Reuse current task/attempt linkage; M0 exact edit symbol + executor/delivery source checks"
      },
      {
        "file": "webui/services/flow.py",
        "symbols": [
          "message_detail",
          "message_io",
          "events_after",
          "spec"
        ],
        "intended_change": "Live/IO/spec/pagination/entity/run queries"
      },
      {
        "file": "webui/routers/trace.py",
        "symbols": [],
        "intended_change": "Source-verified message API and SSE compatibility; exact route impacts before edit"
      },
      {
        "file": "webui/routers/evaluation.py",
        "symbols": [],
        "intended_change": "NEW fixed-schema experiment CLI adapter"
      },
      {
        "file": "webui/services/evaluation.py",
        "symbols": [],
        "intended_change": "NEW child-process run/cancel/query isolated experiment service"
      },
      {
        "file": "core/evaluation/",
        "symbols": [],
        "intended_change": "NEW dataset/snapshot/clock/adapters/runner/report modules"
      },
      {
        "file": "scripts/run_flow_evaluation.py",
        "symbols": [],
        "intended_change": "NEW fixed CLI without default production DB"
      },
      {
        "file": "dashboard/src/views/data/FlowPage.vue",
        "symbols": [],
        "intended_change": "Current component: factual instance/source/entity/related navigation and replay lifecycle"
      },
      {
        "file": "dashboard/src/views/data/flowLayout.ts",
        "symbols": [
          "layoutExecuted"
        ],
        "intended_change": "Unknown visibility, true transition instance edges and layers"
      },
      {
        "file": "dashboard/src/stores/flow.ts",
        "symbols": [
          "openTrace",
          "loadSpec",
          "fetchEvents",
          "startStream"
        ],
        "intended_change": "Digest caching, switching guards, paging and subscription lifecycle"
      },
      {
        "file": "dashboard/src/stores/flowReducer.ts",
        "symbols": [
          "projectNode"
        ],
        "intended_change": "Instance first projection and correct aggregation"
      },
      {
        "file": "dashboard/src/api/flow.ts",
        "symbols": [],
        "intended_change": "Typed process/entity/report API compatibility"
      },
      {
        "file": "dashboard/src/api/sse.ts",
        "symbols": [],
        "intended_change": "Cursor/reconnect/auth lifecycle"
      },
      {
        "file": "dashboard/src/api/http.ts",
        "symbols": [],
        "intended_change": "Shared authentication failure behavior"
      },
      {
        "file": "dashboard/src/views/data/InternalFlowExperiments.vue",
        "symbols": [],
        "intended_change": "NEW dataset/report UI"
      },
      {
        "file": "dashboard/src/views/data/DataPage.vue",
        "symbols": [],
        "intended_change": "Existing data tabs"
      },
      {
        "file": "dashboard/src/router/index.ts",
        "symbols": [],
        "intended_change": "Existing flow route + experiment routes"
      },
      {
        "file": ".github/workflows/ci.yml",
        "symbols": [],
        "intended_change": "Docker source closure and final generated artifact gate"
      },
      {
        "file": ".github/workflows/dashboard_ci.yml",
        "symbols": [],
        "intended_change": "Cross-language flow change triggers and UI contract gate"
      },
      {
        "file": "core/observability/flows/",
        "symbols": [],
        "intended_change": "Final versioned generated artifacts once at M6"
      }
    ],
    "tests": [
      {
        "file": "tests/webui/test_message_flow_api.py",
        "scenarios": [
          "Alive running remains running/SSE open; dead incarnation interrupted",
          "Delivered QQ IO by IDs",
          "History paging/high watermark/spec archive"
        ]
      },
      {
        "file": "tests/observability/test_message_flow_runtime.py",
        "scenarios": [
          "Late writer failure corrects affected run loss/complete",
          "Concurrent run losses do not cross-attribute",
          "Safe summary and restart heartbeat",
          "Repeated/parallel attempts"
        ]
      },
      {
        "file": "tests/observability/test_message_flow_store.py",
        "scenarios": [
          "Additive legacy migration",
          "Spec immutable digest archive and pruning linkage"
        ]
      },
      {
        "file": "tests/observability/test_message_flow_contract.py",
        "scenarios": [
          "New root/call/guard/exception/spawn unregistered fails",
          "Explicit boundary/source changes with digest/semantic diff"
        ]
      },
      {
        "file": "dashboard/tests/flow-store.spec.ts",
        "scenarios": [
          "old/new switch and stale response guard",
          "Paging, reconnect, hidden recovery,401 and list updates"
        ]
      },
      {
        "file": "dashboard/tests/flow-reducer.spec.ts",
        "scenarios": [
          "success then new attempt running",
          "Parallel partial outcomes and no inherited reason"
        ]
      },
      {
        "file": "dashboard/tests/flow-layout-executed.spec.ts",
        "scenarios": [
          "No transition means no traversed edge",
          "Unknown hook displayed",
          "Loop/async/attempt distinction"
        ]
      },
      {
        "file": "dashboard/tests/flow-layout-layered.spec.ts",
        "scenarios": [
          "Source/symbol/business layers and stable navigation"
        ]
      },
      {
        "file": "tests/test_memory_manager_v2.py",
        "scenarios": [
          "Weak candidate contradicting strong existing memory: current Python/Rust difference and chosen policy"
        ]
      },
      {
        "file": "tests/test_candidate_reinforcement.py",
        "scenarios": [
          "Same evidence duplicates, first_seen TTL, scopes and promotion threshold"
        ]
      },
      {
        "file": "tests/test_memory_rust_promotion.py",
        "scenarios": [
          "Actual backend/fallback/strict error and hooks once",
          "Committed vs rolledback state facts"
        ]
      },
      {
        "file": "tests/observability/test_internal_flow_inventory.py",
        "scenarios": [
          "NEW root/source closure boundary and IDs coverage"
        ]
      },
      {
        "file": "tests/observability/test_memory_flow_lifecycle.py",
        "scenarios": [
          "NEW extraction/candidate/transaction/FTS/quota/after hook lifecycle and many-to-many evidence"
        ]
      },
      {
        "file": "tests/observability/test_proactive_flow_lifecycle.py",
        "scenarios": [
          "NEW all levels/preflight/clock/filters/receipts/ack-only effects and verify loop"
        ]
      },
      {
        "file": "tests/evaluation/test_isolation.py",
        "scenarios": [
          "NEW sandbox DB/WAL/cache/jobs/plugins/sender/process/cancel isolation"
        ]
      },
      {
        "file": "tests/evaluation/test_virtual_clock.py",
        "scenarios": [
          "NEW UTC/SQL/Rust/TTL/midnight/backoff/leases and independent monotonic"
        ]
      },
      {
        "file": "tests/evaluation/test_pipeline_replay.py",
        "scenarios": [
          "NEW repeat fixtures digest/cutoff/no future leakage and historic/counterfactual separation"
        ]
      },
      {
        "file": "tests/evaluation/test_stability_report.py",
        "scenarios": [
          "NEW zero/partial sample never PASS, proper coverage denominator and fault navigation"
        ]
      },
      {
        "file": "dashboard/tests/internal-flow-navigation.spec.ts",
        "scenarios": [
          "NEW DOM process/span/entity/experiment navigation, missing spec and integrity display"
        ]
      }
    ],
    "verification_commands": [
      "docker exec stella-gitnexus sh -lc 'node .gitnexus/run.cjs analyze --index-only --force --pdg'",
      "python -m pytest tests/observability/test_message_flow_store.py tests/observability/test_message_flow_runtime.py tests/observability/test_message_flow_contract.py tests/webui/test_message_flow_api.py -q -p no:cacheprovider --basetemp \"$env:TEMP\\stella-flow-review-pytest\"",
      "python scripts/generate_message_flow.py --check",
      "node dashboard/node_modules/vitest/vitest.mjs run --root dashboard",
      "node dashboard/node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p dashboard/tsconfig.json",
      "python -m pytest tests/test_memory_manager_v2.py tests/test_candidate_reinforcement.py tests/test_memory_rust_promotion.py -q -p no:cacheprovider --basetemp \"$env:TEMP\\stella-internal-flow-memory-review\""
    ],
    "risks": [
      "CRITICAL _emit_event; HIGH promotion and observe; complete depth1 dependents listed in section9 must regress.",
      "Graph flow sampling/dynamic/cross-language gaps; source closure denominator cannot be 829 sampled flows.",
      "Async writer loss, SQLite migration/locking, historical spec drift, statement event amplification.",
      "Evaluation global monkeypatch/default production paths, virtual-clock gaps and historic feedback leakage.",
      "Existing Python weak-conflict behavior differs from native Rust; independent business decision required.",
      "Privacy, partial delivery unknown, empty sample false PASS, fixture/native/UI contracts not end-to-end evidence."
    ],
    "assumptions": [
      "Plan only; current user has not requested actual model runs/sends or business implementation. Start fixture+fake sender; choose dataset/budget at experiment execution.",
      "Suggested 5ms/5% overhead,1 experiment concurrency,10k events/100k messages need M0 actual-hardware measurements and locked gates.",
      "Minimal/pseudonym export suitable initially; check actual private content authorization/retention and current ACL before implementing export.",
      "Existing SVG/flow API reusable; validate large graph performance before considering library rewrite.",
      "M0 exact sources/impacts required for not fully verified knowledge publish/index/dynamic tools/startup/remaining callbacks; no speculative symbol edits."
    ],
    "open_questions": [
      "M0 choose hardware-backed overhead/capacity thresholds and detailed-profile scope.",
      "Select export privacy/retention settings and dataset/model budgets for future actual experiments.",
      "Confirm intended weak-conflict policy and Python/Rust quota/FTS parity before behavior fix.",
      "Complete native/real-NoneBot/long-run/package validation at M6; current tests do not establish them."
    ],
    "avoid": [
      "Do not repeat full repository discovery; use this evidence and targeted M0 gaps.",
      "Do not replace current flow/Turn/task protocols or business rules without evidence.",
      "Do not mark previous plan complete, this plan implemented or new CLI/tests already passed.",
      "Do not treat graph UNKNOWN/zero callers/sampled processes as completeness proof.",
      "Do not edit existing symbols before fresh impact or commit before detect_changes; partial/truncated requires rerun.",
      "Do not derive real traversed edges from endpoints, execution from absent events, or current state as historical fact.",
      "Do not classify reply output using root_kind/time-window guesses or equate generation to acknowledged delivery.",
      "Do not flush observer synchronously in hot paths or move business locks/transactions for telemetry.",
      "Do not run experiments in FastAPI via global DB_PATH/time monkeypatch or production default paths.",
      "Do not send real QQ, run arbitrary tools, upload dataset or invoke model during read-only planning.",
      "Do not return PASS for no samples/unknown/partial; do not count historical human reactions as genuine feedback to counterfactual generated text.",
      "Do not overwrite the prior plan; final manifest/golden regeneration once in integration stage."
    ],
    "investigation_ledger": {
      "plan_mode": "deep/full/strict",
      "head": "4b089b5106f3b1945200058cad4047e7ca1cc221",
      "base": "e7cf4f3166d898310279de43cfa89a0c1d0b0aaf",
      "refresh": {
        "container": "stella-gitnexus",
        "repo": "/repo",
        "utc": "2026-10-03T00:59:24.916Z",
        "status": "success",
        "files": 872,
        "nodes": 78030,
        "edges": 187748,
        "clusters": 931,
        "sampled_flows": 829
      },
      "graph_calls": [
        "resources context/clusters/processes",
        "query flow/memory/proactive/maintenance",
        "context generator/promotion/gate/observe/proactive/target/Python/Rust",
        "impact build_manifest/process_new_candidates/observe/_emit_event",
        "pdg controls manager142/decision27/end_trace",
        "detect_changes compare explicit base:811symbols/87affected/49files/critical"
      ],
      "source_verification": "Cited manifest pins read source regions and located/executed tests; broad mutation boundaries partially inspected by parallel review lenses. Not a claim all lines of every cited file were read.",
      "verification": {
        "backend_tests": 51,
        "dashboard_tests": 45,
        "dashboard_files": 5,
        "typecheck_exit": 0,
        "manifest_check": "matched",
        "memory_tests": 29,
        "probes": "temporary SQLite + in-memory transpiled current UI sources; O01-O08 evidence"
      },
      "decisions": [
        "Previous DoD partial, not complete",
        "Reuse observer/catalog/SVG/task boundaries",
        "Static topology/actual instances/entity history separate",
        "Memory and proactive multi-root processes",
        "Child-process isolated evaluation",
        "No business/config/production data changes"
      ]
    }
  }
}
```

## 12. Assumptions and Open Questions

| 分类 | 内容 | 实施前验证/处理 |
|---|---|---|
| [assumed] 数据用途 | 用户目标是本地调试和真实聊天稳定性验证，允许设计只读导出与隔离runner；未授权本轮实际调用模型/发送 | 实施时使用指定dataset/模型预算；默认fixture+fake sender，不把计划当运行授权 |
| [assumed] 性能与容量 | §6.7建议5ms/5%、1实验并发、10k事件/100k消息基准，尚无硬件实测 | M0基准后确定配置/门槛与profile；报告实际测量，不自行保证 |
| [assumed] 私有内容 | export可用伪名ID与必要content，原文权限/保留需求未确定 | 默认最小内容、管理员权限；snapshot/dataset导出界面显式选择字段，遵守当前业务可见性 |
| [verified] 未知入口细节 | 本轮没有全精读knowledge发布、所有动态工具、startup/shutdown/全部scheduler callback | M0从fresh graph+AST registry逐项补source；未锚定前不编辑符号；不将它们从完整范围删掉 |
| [verified] 业务疑点 | Python弱候选冲突继续晋升、Python/Rust quota/FTS处理差异；本轮没有业务修复 | 隔离case与当前策略核验；图忠实呈现；修正行为独立审查/回归 |
| [inferred] 初期产品边界 | 沿用custom SVG与现有flow API可实现；是否替换图库尚非前提 | M4压力/可维护性证据后决定，避免先重写UI再验证事实模型 |
| [inferred] 详细观测范围 | 常规profile不逐语句记录locals；详细debug选择run/模块 | 所有节点静态可查；未probe标未观测；不能承诺低开销且全量运行细节同时成立 |
| [verified] 尚未完成验证 | 真实NoneBot入口、native Rust全链路、长期大集、最终发行包 | M6交付证据后才可关闭计划；本轮现有测试不能填这些结果 |

[inferred] 相邻但非本次默认工作：云托管观测服务、自动上传聊天数据、分布式OTel平台、换全部前端图库、全面修业务算法。现有业务缺陷若妨碍验证应定点修正，不扩大成没有验收范围的重构。

## 13. Definition of Done

[inferred] 本计划只有以下条件全部满足才可标完成；旧计划关闭还要求其旧DoD未满足项逐项提供证据。不能用“测试全绿”“图能动”“文档列了节点”代替验收。

1. O01–O10均有当前正确合同的回归测试与修复；live root不会立即interrupted；QQ真实回复可按业务ID关联；writer晚失败能纠正per-trace integrity。
2. registered runtime roots有版本化inventory；所有新发现入口归类；GitNexus+AST闭包包含调用/guard/return/except/finally/spawn/状态/事务；每个节点可展开source anchor，核心unresolved=0，external/dynamic/Rust边界显式可查。
3. 目录完整度、runtime观测完整度、dataset覆盖度分别显示分母与状态；UNKNOWN、loss、no probe、insufficient samples不可作绿色通过或“未走到”。
4. 历史trace绑定不可变spec digest并归档；old/new快速切换不串spec；无spec/unknown事件仍可读；发布资源携带对应manifest。
5. root/span/attempt与真实transition分离；循环/并行/重试实例独立；静态端点出现不高亮假执行边；关联run支持点击导航。
6. 记忆全链路覆盖抽取/候选/reinforce/TTL/backend/gate/conflict/merge/create/quota/FTS/commit/cache/compress/retrieve与验证闭环；逐candidate/memory可查前后状态和真实证据来源，多群/共享space不混。
7. participation全部等级及early return可解释；主动timer/主动@/群插话各有前置root；禁用/无Bot/无目标/门控/退避/冷却/配额也可查询；score/slot/topicrevision可核验。
8. 生成、逐段发送、部分/未知回执、确认记账、回复窗口、效果学习与后续记忆因果贯通；模拟ack与真实ack不混；无回应不判负反馈。
9. social/maintenance/scheduling/knowledge/Cometa/startup-shutdown等inventory根覆盖；task执行/通知、knowledge ready/published、business commit/后台hook分开。
10. SSE cursor补读/去重/恢复/隐藏/401完成；历史分页到高水位；列表更新生效；loaded完整与storage完整区别展示；暂停/单步/速度/跳错只读无副作用。
11. 四种实验模式合同明确，隔离child process使用同业务函数和adapter；所有DB/缓存/job/log/artifact路径在sandbox，0生产写入、0真实发送/工具；取消/失败保留partial且不算完成样本。
12. dataset保留原source/ID/order/scope/@/UTC信息；snapshot一致性cutoff无未来泄漏；虚拟时间覆盖SQL/Python/Rust/任务窗口；历史与反事实不双算BOT_SELF/反馈。
13. 同fixtures重复semantic digest一致；真实模型报告多次分布；样本/coverage/完整性门槛先行，零样本为INSUFFICIENT_SAMPLES或SKIPPED；报告能定位失败case→run→node/entity。
14. §8故障矩阵、实际入口smoke、native Rust集成、自然分布与重点数据集均出报告；长期运行backlog最终可排空；p95/吞吐/容量/大图达到M0确认门槛。
15. 观测summary等全渠道脱敏，权限/保留/硬容量与prune有实际生产调用和验收；常规与debug profile overhead各自测量；观测关闭/异常不改变业务合同。
16. CI能因Python/Rust/动态注册/guard变化而发现目录漂移；提交前impact/detect_changes完整核验；最终代码、manifest、Dashboard资源、版本报告一致；最终发行实物验收留证。



