# Review: Dashboard 消息工作流第二轮验收

日期：2026-10-05。结论：**NOT READY；上一轮多项主要缺陷已关闭，但仍未全部完成。**

验收依据：[上一轮报告](E:/stella/stella_project/docs/reports/2026-10-05-dashboard-flow-plan-acceptance-review.md)、[修复响应](E:/stella/stella_project/docs/reports/2026-10-05-acceptance-fixes-response.md)、[原计划](E:/stella/stella_project/docs/plans/2026-10-04-gitnexus-plan-dashboard-flow-completeness-repair.md)。原计划正文未在本轮比较范围内变更；沿用此前正式解码的计划合同。以下区分原反例已关闭、新修复仍漏掉的边界，以及尚未执行的现场验收。

## Findings

### A1 [HIGH / P1] writer 确认后仍漏最终补读；detail 短暂失败还阻断独立 IO

[flow.ts:368](E:/stella/stella_project/dashboard/src/stores/flow.ts:368) 在重试发现 producer_ended 与 integrity 已确认后直接 return，绕过最终事件补读；IO/entities 也只在等待前查询一次。隔离探针初次 detail 为 pending、水位 1，读取事件 1/IO part1；1.5 秒后 detail 确认结束、水位与 count 都为 2，实际结果仍是：

```json
{"high":2,"count":2,"loaded":1,"io":["part1"],"detailCalls":2,"eventCalls":1,"ioCalls":1,"truncated":false}
```

这不是纯假设：[trace.py:227](E:/stella/stella_project/webui/routers/trace.py:227) 的 SSE 仍按 ended_utc 发 trace_end，不等 writer producer_ended 落账，客户端因此会走 pending→final 路径。新手动刷新在水位已确认时确实会补读，**原 H5 的手动刷新反例已修复**，但原 R6/R8 收尾合同未关闭。

另 [flow.ts:345](E:/stella/stella_project/dashboard/src/stores/flow.ts:345) 对首次或重试 detail 异常直接 return。首次 getMessage transient error 的探针在推进 60 秒后仍只有 1 次 detail 请求、0 次 events、0 次 IO；这还把原本独立的 IO/entities 刷新变成了依赖 detail 成功的新回归。现有新增用例只验证手动刷新正常成功，没有 pending→final 或 detail transient error。

修复要求：finality 确认后按新水位补齐 events、IO、relations/entities，再确认完整或显式 pending/partial；短暂失败进入有界重试，独立来源的刷新不能被 detail 错误统一取消。

### A2 [MEDIUM / P2] 页面隐藏不使 bundle 失效，继续加载也未保持冻结快照

[flow.ts:335](E:/stella/stella_project/dashboard/src/stores/flow.ts:335) 的 alive 检查有请求 seq 和 trace generation，但没有 streamSession。隔离探针挂起 bundle 后隐藏页面、session 增加，再返回旧响应，旧 detail 仍落地，并发出事件请求：`session=1, high=1, ended='', eventCalls=1`。新同 trace 两个 bundle 的迟到覆盖反例已通过，但原页面隐藏合同仍漏。

[flow.ts:444](E:/stella/stella_project/dashboard/src/stores/flow.ts:444) 的 loadMoreEvents 未传 until。探针冻结水位 1500、已有 row 1–1000，继续加载请求仅为 `['t',1000,1000]`，返回并合并到 row 2000，超过冻结快照。初始 fetchEvents 的每一页现在都传冻结水位，**这部分已经修好**；续页须使用同一快照边界，不能因为跨过水位把快照误判为已完整。

修复要求：所有 bundle/事件回包绑定 session 与请求上下文；fetch 和 continue 共用快照水位，主动刷新再开启新快照。补页面隐藏与继续页边界反例。

### A3 [MEDIUM / P2] 闭包和入口门禁仍有三种确定漏检，native 合同/配置摘要也不完整

- **普通模块别名**：[generate_message_flow.py:187](E:/stella/stella_project/scripts/generate_message_flow.py:187) 对 `import pkg.helper as h` 保存 original 为空，455 的还原仅覆盖 from-import。临时 fixture 调用 h.normalize，实际记录不存在的 helper.py#h.normalize 为 unresolved，修改 normalize 函数体 `+1→+2` 后 closure hash 不变。from-import 别名、生产 extract_signals/sc.get_summary 本轮已修好，不能混为仍未修。
- **删除注册但保留函数**：[generate_message_flow.py:776](E:/stella/stella_project/scripts/generate_message_flow.py:776) 的 missing 仍按符号存在性。移除 scheduled_job decorator、保留已登记 tick 函数，discovered/undeclared/missing 全空。新增入口发现已能抓带参数装饰器，但反向注销检测仍未满足原 §6.5。
- **worker handler 改绑**：[generate_message_flow.py:743](E:/stella/stella_project/scripts/generate_message_flow.py:743) 只保留 register_handler 首个字符串键，丢掉第二个 handler。完整 manifest 内存 AST 探针将真实 resolve_effect 的 handler 从 _handle_resolve_effect 换成现存 _connect，未改正式文件，结果 problems=[]、完整 hash 仍为 `84f89c091e2405f78d5b7ef18660e80511e197a11ec612454fddf57d6b757985`。真实 [social_worker.py:223](E:/stella/stella_project/memory/social_worker.py:223) 会调用这个 handler；注册键相同并不代表生产行为相同。

修复要求：分别解析模块别名与符号别名；注册 inventory 保留注册证据和 handler 绑定，校验删除注册的反向差集，把绑定与 handler 体/边界纳入 hash。

另外 [generate_message_flow.py:919](E:/stella/stella_project/scripts/generate_message_flow.py:919) 现在确实给 promotion.rs 加了源码 digest，但 memory_rust.backend/selector 的合同、配置边界仍只有 native 名称；修改临时 backend 合同和 mode 配置的探针不会改变 closure/hash。需要补真实 contract/config 依赖摘要。这是原 M4 剩余合同，不能宣称 Rust 源文件 digest 毫无改善。

### A4 [MEDIUM / P2] 生命周期成功路径已接入，失败/取消仍悬空或误报成功

[ai_gateway.py:2740](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:2740) 的 scheduler runtime.start 在 init try/except 之外。安全 AST 抽取生产函数，假 start 分别抛 RuntimeError、CancelledError，均产生 begin/start/raised，end_calls=0，新 lifecycle root 悬空。

[shutdown:4125](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:4125) 和 4130 suppress Cometa/scheduler 停止错误，4159 仍总标 stopped、complete=True。假两个 stop 均失败，探针仍得到 `ends=[['stopped',{'complete':true}]]`。没有 finally 覆盖整体取消/异常，也没有有界 message_flow flush 来确认末尾观测提交。

真实库已有三个正常启动 root，证明成功路径改善；它们不能证明失败、取消和关闭路径完整。修复要求：保留原异常/取消语义，用明确终态或 finally 收口，记录真实失败/超时，并完成有界观测 flush。现有测试矩阵没有这些 lifecycle 反例。

### A5 [MEDIUM / P2] token 只挂在 root，旧事件仍能结束新的 occurrence

[ai_gateway.py:509](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:509) 的 token 属性赋值成功；不是 slots 问题。但是 event/处理上下文没有 expected token。[529](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:529) 先按 canonical key pop 当前 root，再比较该 root 自己是否消费过 token。

AST 探针让旧 root 结束，同身份同消息号的新 occurrence 建立 replacement，再让旧事件迟到重复结束，结果 `replacement_distinct=true, replacement_ended_by_old_end=true, event_has_token=false`。原“缓存淘汰→活跃事件重入→连续结束”已复用同 root 并通过；新增用例没有在两个结束之间加入 replacement。

修复要求：把 occurrence/token 绑定事件或处理上下文，结束时核 expected ctx/token，再 compare-and-pop；旧 occurrence 的结束不得 pop 掉新 root。

### A6 [MEDIUM / P2] 新输出模板显示矛盾的“无”，私聊入口仍依赖先打开其他轨迹

[FlowPage.vue:966](E:/stella/stella_project/dashboard/src/views/data/FlowPage.vue:966) 的 v-else 现在与“存在非 acknowledged segments”的新 v-if 配对。全部 ACK、已显示正文时也会显示“（无）”。真实 Vue SSR 探针 hasOutput=true/hasNoOutput=true；浏览器查看 10:13:07 的已送达私聊，输出 3 行且输出区域包含“（无）”，已实际确认。修复要求：无输出占位仅判断是否没有输出/片段事实，不应依附非 ACK 条件；补 DOM 渲染回归。

[FlowPage.vue:700](E:/stella/stella_project/dashboard/src/views/data/FlowPage.vue:700) 的动态入口 union 依赖 store.spec，而 spec 只在选择轨迹后加载；静态标签表漏 qq_private。浏览器初始下拉 19 项没有私聊，先打开 lifecycle 轨迹加载 spec 后才出现第 20 项 qq_private。修复要求：初始可用的标签/入口目录包含私聊，或独立加载过滤目录；过滤选项不能依赖已选择轨迹的历史 spec。

列表累积页本轮确实保留，但 [flow.ts:230](E:/stella/stella_project/dashboard/src/stores/flow.ts:230) 用空 cursor 同时表达“尚未加载”和“已取尽”。浏览器私聊列表从 100 续读到 122 后，轮询又恢复首屏 cursor，按钮仍显示“已载 122 / 共 122”。需保留独立的 exhausted 状态。这是分页状态的剩余问题，不等于旧 H3 的方向错误仍存在。

### A7 [MEDIUM / P2，恢复合同] 备份失败后仍提交迁移

[message_flow.py:418](E:/stella/stella_project/core/observability/message_flow.py:418) 只把 backup 返回值转成 bool，不阻止失败后继续迁移。临时旧库 patch backup helper 返回空串，实际迁移成功、新 identity 列存在，但无备份。

显式事务与晚期迁移失败回滚已经有效，原半迁移残留反例已关闭；这里是原 §6.2 的迁移前恢复保障仍未兑现。已有数据需迁移时备份失败应保留原库并降级诊断存储，或落实明确的等效恢复保障。补备份失败的反例。

### A8 [MEDIUM / P2] 片段超过 20 段时无提示截断，命令完整正文合同仍未完成

[flow.py:542](E:/stella/stella_project/webui/services/flow.py:542) 读取上限+1 个回执，[680](E:/stella/stella_project/webui/services/flow.py:680) 返回前 20 个 segments，截断说明却只按 ACK 文本数量判断。21 个 failed 回执即可被无提示截断；201 段探针返回 20 段、最大 part_index=19，没有 total/truncated/cursor 或截断 note。count 只表示 ACK 正文数，不能代表所有片段已加载。

原 0 ACK/1 failed/2 ACK 小矩阵现在确实保留原序号与 status；全部失败也有逐段事实。需要在全部 segments 维度报告总数、截断和继续读取，并保持完整正文可访问。修复响应明确仍让命令走 command.reply checkpoint，原计划的命令完整回执正文合同未完成；应继续列为剩余项，不标整项 M6 已完成。

## Change and blast-radius summary

- Repo：E:/stella/stella_project；当前分支 `feat/dialogue-attribution-role-repair`；remote 默认分支 origin/main。修复响应中另写的分支名属于其历史描述，不作为本轮 checkout 事实。
- 精确两点范围：`33a34f326ac87f1d66271a13945a061610830399..4fe05ec2c866908233ca18fd8668dd7ec3bfdb62`。Git diff stat 为 24 个文件（含生成文件 rename/delete）；graph compare 识别 23 个文件、151 个 changed symbols、18 个 affected processes，risk critical，无 partial/truncated 标记。原始图结果位于 Docker `/tmp/stella-flow-reacceptance/`。
- Docker stella-gitnexus 在 /repo 执行 analyze --index-only --pdg 成功，314 秒；lastCommit 与上述 HEAD 对齐，indexedAt=`2026-10-05T02:35:59.429Z`，87,686 nodes、212,765 edges、946 clusters、831 sampled flows。
- 父审阅独立完成 context、upstream impact、detect_changes、explain、PDG，再分域进行只读源码与临时探针。record_delivery 为 CRITICAL/direct9，_connect 为 HIGH/direct10，_flow_root_or_create 为 HIGH/direct5；这些是覆盖范围信号，不是缺陷严重性依据。对象 store 方法及动态 startup hooks 的 UNKNOWN 用源码/探针补证，不按零 caller 判 unused。
- 五个数据边界 explain 均无 finding，工具明确不覆盖 closure/property/implicit flows，不能据此推断身份和异步合同安全。PDG 已定位 exact 输入守卫、delivery 守卫、discovery 注册分支及 finality 的提前 return；均有实际层，不是 skipped。
- 检查了 diff 外直接依赖：WebChat 回执构造、social 归因/学习消费者、trace router、entity history、manifest 合同及相关测试；没有发现新增必填参数破坏这些调用。新增 Receipt 字段有默认值，现有构造使用关键字参数。
- 图的过程入口排名、深度/预算及 callable 候选存在截断，manifest 大 JSON 不在普通符号索引；另直接解析生成目录，并用 AST/临时执行补齐关键合同。未编辑业务符号或提交；本轮图检查不追溯证明历史每个编辑都执行了 impact。

## Coverage and residual risk

### 本轮重新执行的门禁

| 检查 | 当前结果 |
| --- | --- |
| 上轮指定 Python 矩阵 | **217 passed，58 warnings** |
| Dashboard Vitest | **6 files / 94 tests passed** |
| Dashboard typecheck | 通过 |
| Dashboard production build | 通过，写入系统 Temp 外部目录；有既有 chunk/dynamic-import 提示 |
| manifest --check | 通过：message-flow.84f89c091e24.json |
| fresh build 对三处部署目录 | 各 **50 个文件逐文件 SHA-256 完全一致** |
| git diff --check | 通过 |
| 补充隔离反例 | 上述 finality/session/快照/模板/入口、AST lifecycle/cache、SQLite migration/片段、闭包/注册绑定反例成立 |

Python 命令：`python -m pytest tests/observability tests/webui/test_message_flow_api.py tests/test_private_chat_ingress.py tests/test_conversation_registry.py tests/test_social_delivery.py tests/test_social_migrations.py tests/test_reply_effect_service.py -q`。前端 test/typecheck 与 manifest check 均用原命令；build 使用 `--outDir C:/Users/Vegetable/AppData/Local/Temp/stella-flow-reacceptance-build`。没有覆盖或重新同步运行中的静态目录。没有重复执行本轮已通过的相同门禁。

临时反例测试“通过”是确认失败形状成立，不能计入产品验收通过数。前端新 H4 正向探针使用自洽单位：全局 row_id=100001…200001、trace seq=1…100001、persisted_events=MAX(seq)=100001、event_count=100001；100 页后 partial=true，继续补末条后 partial=false。旧探针 fixture 的 seq 与 row_id 同值问题已纠正，本报告不把旧 JSON 当真实 writer 单位证据。

当前 manifest 为 **140 nodes / 148 edges / 20 roots / 49 declared / 33 discovered**，22 explicit、126 static_only；孤岛为 0，两种预算截断清单均为空。源码位置、体 hash、helper 数和边界分类已有页面消费。零孤岛、空差集只证明当前限定扫描/目录状态；A3 的反例表明还不能宣称真实源码闭包完整。

### 真实数据库与浏览器

沿用用户授权，以 URI mode=ro、query_only=ON 和读事务查询 turn_trace.db 与 agent_memory.db。没有向真实 QQ 发送测试消息，没有对真实库运行迁移、回填或修复。

最近 10 条私聊中有 **7 条修复后的新轨迹**，开始时间 **2026-10-05 09:48:19–10:13:07（UTC+8）**。它们绑定运行时归档 a859… digest，每条均 delivered/complete，3 个 send.segment 成功事件、3 个 acknowledged 回执、3 行输出、3 个 segments，learning_eligible=0，Bot 字段非空。老 619c… 轨迹仍无回执；历史缺档没有当作新代码再次失败。

当前 HEAD 的生成文件是 84f89c…，运行时新样本归档 a859… 是后续换行 digest 修正之前的版本。两者按各自 digest 归档；本轮没有把这个版本差异判为错误绑定或用 latest 图解释旧轨迹。

真实库还存在 _start_scheduling、_start_cometa、_start_stop_watcher 三个生命周期 started/complete root。浏览器正常显示这些轨迹。打开最新修复后私聊，确认输出 3 行、“已载 71 / 存储 71”；同时确认 A6 的矛盾占位与动态私聊入口延迟出现。真实历史列表成功从 100 续读到 122，验证 H3 的主要方向修复；取尽状态被轮询重置的问题另列 A6。

正文、账号和私聊会话 ID 不写入本报告。浏览器只进行过滤、查看和加载，没有业务写入。用户明确回答 **“尚未完成现场验收”**；最终安装包、桌面实际加载及完整导航、真实 QQ 图片/命令/部分失败/拒绝/并发矩阵均未验收。这些缺口不能由 7 条普通成功私聊代替。

### 上一轮缺陷关闭矩阵

| 上轮项 | 本轮判断 | 依据及剩余边界 |
| --- | --- | --- |
| H1 真实 ref 不落回执 | **已关闭** | 生产工厂链路临时落库 + 7 条真实新轨迹有效；中立身份和 learn0 保留 |
| H2 exact 输入跨 Bot | **原反例已关闭** | 同 storage/msg 的两 Bot 正确返回各自正文，mismatch=None，legacy 保守标注 |
| H3 keyset/offset/total | **原反例已关闭** | 三页 5→1 正确、offset 正确、total 同过滤范围；真实历史续读有效 |
| H4 row/seq 单位及计数 | **原反例已关闭** | 自洽 100001 事件探针；页面真实 71/71；继续页快照仍见 A2 |
| H5 手动事件补读 | **正常手动路径已关闭，收尾未完成** | 手动水位推进会补事件；pending→final、异常仍见 A1 |
| M1 transition span/edge_id | **原反例已关闭** | 错 span/平行 kind 被拒绝，匹配事实可激活 |
| M2 bundle/list 竞态 | **主要反例已关闭，部分完成** | 同 trace 并发序列、切过滤旧页、轮询保留历史通过；页面隐藏和 exhausted 仍见 A2/A6 |
| M3 真实发现形状 | **新增形状已关闭，反向合同未完成** | 带参数装饰器与 worker 表达式可发现；删除注册仍漏报 |
| M4 alias/local/native | **主要案例已关闭，部分完成** | from-import、sc/extract、AstrBot、缺 local 可见、Rust 本体 digest 改善；普通 import 与 handler/config 合同见 A3 |
| M5 lifecycle/孤岛/UI | **部分完成** | 正常启动、0 孤岛、闭包视图、动态 union 已实现；异常取消、关闭事实及初始私聊筛选仍缺 |
| M6 segments/cache/migration | **原小矩阵已关闭，部分完成** | 原 part/status、全部失败片段、活跃重入、迁移回滚有效；长片段、replacement occurrence、备份失败、命令正文见 A5/A7/A8 |

H2 查询仍只查最近 8 个候选后在 Python 核身份，目标在第 9 个会返回 None；它已不会返回别的 Bot 正文。本轮不将保守漏显误报为原跨 Bot P1。回执输出仅按全局 trace ID 查询，没有实现额外 canonical 防御核对；未构造线上证据将它提升为 P1。

### 原计划完成度

| DoD | 当前验收 |
| --- | --- |
| 1 全部 R1–R9 与现场证据 | 未完成，仍有 A1–A8 和现场待验 |
| 2 身份/root/输入输出/终态隔离 | 主要修复通过；replacement occurrence 未完成 |
| 3 精确 spec/A-B/legacy/missing | 保留前轮核心通过；真实 loader 多文件/缓存选择合同尚未补独立反例 |
| 4 owned transaction/per-run fail-open | 保留已有实现支持；完整故障矩阵仍非本轮全验 |
| 5 transition/occurrence/finality | span/edge 原反例通过；finality A1 未完成 |
| 6 checkpoint/span 状态 | 本轮现有测试通过，无新增阻断 |
| 7 完整回执/片段/命令及不学习 | 私聊与小片段、不学习通过；长片段/命令仍未完成 |
| 8 入口/helper/边界漂移可见 | 部分完成，A3 阻断 |
| 9 生命周期/内部事实 | 正常启动通过；失败/取消/停止 A4 未完成 |
| 10 IO/detail/关系刷新无竞态 | 部分完成，A1/A2 阻断 |
| 11 分页/加载状态/完整正文 | 主要分页修复通过；续页快照、取尽、片段截断未完成 |
| 12 导航/auth/脱敏 | 代码与部分浏览器检查有证据；完整浏览器/桌面矩阵待验 |
| 13 测试/type/build/CI/gen | 指定命令通过；DOM、finality/取消等反例及真实 manifest 100k p50/p95 未完整覆盖 |
| 14 资产/QQ/安装包 | 三处资产通过、7 条成功私聊有证据；完整现场矩阵及最终包未完成 |
| 15 GitNexus gates | 本轮 graph compare/PDG 对齐通过；不追溯证明历史逐编辑流程 |
| 16 交付状态与范围 | 修复响应应把 A1–A8 剩余合同补回清单，不能继续写所有 M 项已完成 |

不把新增 static_only 边当作真实 transition，也不把其他归因/Laya/记忆/安装器计划的测试当作本计划验收。仍缺实际 manifest 的 100k 增量性能 p50/p95 和完整页面 DOM 交互回归。

## Verdict

**NOT READY。** H1–H4 的主要故障、M1、M2 的几个竞态、入口发现形状、from-import/AstrBot、正常生命周期、迁移原子回滚等均有实际改善与通过证据。剩余失败已经收敛到收尾补读、session/快照、闭包登记合同、生命周期错误与 occurrence、输出显示/完整性和恢复边界，尚不能验收“探测到的缺陷全部完成”。

建议先关闭 A1，再修 A2/A4/A5，补 A3 漂移反例以及 A6–A8；重跑受影响门禁后完成用户确认尚未执行的现场与安装包验收。每项应留下当前 trace/digest/水位/片段证据，并更新修复响应。

本轮只新增这份复验报告；正式业务源码、测试、配置、manifest 未修改，未提交或真实发送。既有未跟踪 .bot-restart.log、.fix_digest.py、Laya 计划和上一轮验收报告保留；没有执行 .fix_digest.py。
