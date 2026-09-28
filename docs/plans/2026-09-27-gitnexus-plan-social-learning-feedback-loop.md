# Stella 社交学习与反馈闭环实施计划

日期：2026-09-27｜深度：Deep / Full｜状态：待实施，已完成源码与图谱调查  
本地基线：`c1a1e843b70de301c6ee5bfe164f23d5c48944a7`，分支 `feat/cortico-runtime-migration`；调查时工作区干净。  
MaiBot 参考基线：`95c027cae7a9dcf611575451fa2920b2307e6a2d`。本文引用固定提交，不依赖未来 main 的变化。

证据标记：**[verified]** 已读源码或实际工具输出；**[graph]** GitNexus 图结果；**[inferred]** 从证据推导的设计判断；**[assumed]** 待实测的参数、投入估计。第 6—8 节中注明“拟新增”的接口、结构、测试均为本计划的设计，尚未实现。

## 1. Objective — 目标与边界

把现有“采集了但很少使用”的表达和黑话数据，接入一个可解释、可回退的闭环：

**真实消息证据 → 发送确认与追踪 → 反馈归因 → 表达/词义资产 → 有预算的上下文选择 → 回复 → 再观察。**

五项交付：

1. **表达学习**：学“什么场合怎样说”，能选入回复；保留 Stella 人格，不复读某个人。
2. **回复效果评估**：区分被接话、被纠正、造成打扰与证据不足；可查具体证据。
3. **群黑话理解**：保存群内词义、适用语境、歧义与来源，先帮助理解，再考虑使用。
4. **请求追踪与回放**：能解释本次为什么说/没说、用了哪些材料、实际发出哪些消息；重现冻结的决策输入。
5. **发言时机**：补全信号、发言占比和等待退避，防止生成中的过期主动回复突然插入。

约束：沿用现有 RuntimeFacade / TurnService、SQLite、参与评分和 WebUI；在线路径不增加学习/评估专用 LLM 请求，不扩张现有轮次调用上限和 8K 预算边界。后台模型默认关闭，允许人工确认资产和规则评估完成基础闭环。插件运行隔离不在本期范围。不引入向量数据库、独立队列服务或第二套聊天执行器。

## 2. Current Behaviour — 已验证现状

| 方向 | Stella 已有能力 | 必须补的缺口 |
|---|---|---|
| 表达学习 | [verified] `on_reply_sent`、被动消息采集、expression_examples / behavior_patterns | 候选列表和模式读取主要由测试使用，没有完整的回复选择与注入链；应将采集、选择、应用、效果关联连起来。 |
| 回复效果 | [verified] 延时结算和 sweep；关键词/emoji/复用分类 | 按同群同用户查发送之后的消息，缺截止上界与准确引用归因；空结果被当 ignored；持久化 monotonic 时间不能跨重启比较；状态结算和模式累加分开，存在重复统计窗口。 |
| 群黑话 | [verified] 词频、候选/确认状态，正则提取 | 缺 definition / sense / context / source evidence；用户多样性仅在内存；高频不等于理解。 |
| 请求追踪 | [verified] runtime turns.jsonl、memory trace、participation trace、WebUI 展示 | turn ID 未贯通，内存轨迹会截断提示词/输出且详情依赖当前记忆；不能重建当时完整决策与投递。 |
| 发言时机 | [verified] 九因子评分、话题与候选确认、可选 embedding、真实日志回放 | 网关没有传齐 observe 支持的 reply/@ 元数据；发言占比、统一退避、可重现时钟与发送前过期检查需要补充。 |

源码锚点：

- [表达学习](E:/stella/stella_project/memory/expression_learning.py:90)、[效果结算](E:/stella/stella_project/memory/expression_learning.py:188)、[存储与旧时间字段](E:/stella/stella_project/memory/expression_store.py:311)。
- [轮次入口](E:/stella/stella_project/core/runtime/facade.py:170)、[准备与预算](E:/stella/stella_project/core/runtime/turn_service.py:268)、[上下文投影](E:/stella/stella_project/core/context.py)。
- [参与观察](E:/stella/stella_project/memory/participation/__init__.py:183)、[评分](E:/stella/stella_project/memory/participation/scorer.py)、[决策](E:/stella/stella_project/memory/participation/decision.py)。
- [现有追踪服务](E:/stella/stella_project/webui/services/trace.py:1)、[记忆轨迹截断](E:/stella/stella_project/memory/trace.py:69)。

**优先修复的基础语义：**

- [verified] 普通回复在实际 send/finish 前调用学习、记录 BOT_SELF 和发言状态。主动 @ 与主动群聊也存在类似顺序；发送失败可能已被记成“说过”。见 [普通发送链](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:618)、[主动 @](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:1810)、[主动群聊](E:/stella/stella_project/stella_project/plugins/bot_main/ai_gateway.py:2155)。
- [verified] 主动群聊使用 user_id=0，现有效果查询仍过滤同一 user_id。[inferred] 该路径通常无法收集真实群成员的反馈。
- [verified] Facade 的 completed 在 finalize 前记录，含义不是平台已投递；DIRECT/SILENT 不执行 finalize。不能只在 finalize 里收集完整追踪。
- [verified] Facade 的默认 provider 直接调用后端，未走 TurnService.generate_reply 内的 scheduler acquire；[verified] scheduler 的 priority 参数目前仍是 FIFO。后台使用同模型前必须补齐共同资源闸门，不能声称已有交互优先调度。
- [verified] record_message 已存 msg_id，却未保存 reply_to / mentioned_users 等关系，见 [消息存储](E:/stella/stella_project/memory/pre_processors.py:55)。新关系宜放旁表，避免扩大核心消息 schema 改动。

## 3. Relevant Architecture — 接入边界与借鉴取舍

### 3.1 保持主链路边界

[verified] QQ 入口经 `_run_turn_via_engine` 调 Facade；WebChat 也直接调 Facade。Facade 按会话加锁，并维护 owner_epoch / inflight；TurnService 负责 prepare / generate / finalize。[verified] WebChat 返回的是服务端生成结果，没有浏览器已读或平台投递确认。

拟实施路径：

```text
QQ / WebChat ingress
  → event_id + trace_id，标准化消息关系与时间
  → 现有硬门禁 / Participation 决策（未生成也记录原因）
  → RuntimeFacade 分配 turn_id，绑定不可变身份
  → TurnService.prepare_turn
      → 现有检索 / Router / Planner
      → 本地选择已确认词义和适用表达
      → 最终预算与请求快照
  → provider → finalize → 待发送输出
  → QQ 回执 / WebChat server_emitted
  → 投递事实与已发片段
  → 后台效果观察 → 归因 / 可选评估 → 可审计统计
```

新学习资产按 `(platform, bot_id, real_group_id)` 隔离；用户表达偏好再加 user_id。保留 `group_shared_space` 作为现有空间映射快照，但默认不跨真实群检索黑话/表达。群组共享记忆不自动意味着共享社交习惯。旧数据来源无法确定时保留 legacy_unscoped，不能猜测回填。

### 3.2 MaiBot 值得迁移的机制

| 方向 | 参考证据（固定提交） | Stella 的取舍 |
|---|---|---|
| 表达 | [learner](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/learners/expression_learner.py)、[selector](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/chat/replyer/maisaka_expression_selector.py) | [verified] 场景/表达结构和选择链可参考；[inferred] 首版本地标签、检索和排序，暂不增加每轮模型 selector。 |
| 效果 | [tracker](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/reply_effect/tracker.py)、[scoring](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/reply_effect/scoring.py)、[judge](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/reply_effect/judge.py) | [verified] 真实发送 ID、引用归因、分维度评估、版本化结果；迁移这些契约，先规则后可选后台 judge。 |
| 黑话 | [miner](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/learners/jargon_miner.py)、[matcher](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/jargon_context_matcher.py) | [verified] 带来源上下文挖掘、按语境匹配；[inferred] 不照搬逐词多轮模型判断，批次提取并允许未知/多义。 |
| 追踪 | [request_snapshot](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/llm_models/request_snapshot.py) | [verified] 请求快照、配置与敏感字段清理值得借鉴；补 Stella 的 turn、工具摘要、预算和投递关系。 |
| 时机 | [necessity](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/reply_necessity.py)、[scheduler](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/turn_scheduler.py)、[backoff](https://github.com/Mai-with-u/MaiBot/blob/95c027cae7a9dcf611575451fa2920b2307e6a2d/src/maisaka/idle_backoff.py) | [verified] 必要性、在场压力、强触发、空闲退避、有限打断；[inferred] 融入已有评分器，避免另起完整 scheduler。 |

借鉴设计，代码实现按 Stella 现有接口重写。模型候选不是可信事实，聊天里的“把某词定义成……”也不是管理指令。

## 4. GitNexus Findings — 图谱结果与调查边界

[verified] GitNexus 1.6.11、Node 22.23.2，索引位于当前 HEAD，PDG 已启用。当前计划复用本会话已有调查，不重复重建索引。环境中 Windows runner 不可用，已验证可用命令：

```powershell
docker exec -w /repo stella-gitnexus gitnexus status --repo Stella_project
docker exec -w /repo stella-gitnexus gitnexus context prepare_turn --file core/runtime/turn_service.py --repo Stella_project
docker exec -w /repo stella-gitnexus gitnexus impact _resolve_effect --direction upstream --depth 3 --limit 100 --repo Stella_project
```

[graph] resources context / clusters / processes 已用于导航；query 先查消息记录、迁移、LLM 角色与预算、prompt composition，再读精确源码。进程枚举有限，动态分派也有漏边，不能把零命中视为不存在。

五个主符号 impact，direction=upstream、depth=3、limit=100；同名方法按文件限定。结果未出现 partial/truncated：

| 主符号 | 风险 / 总影响节点 | 全部 d=1 依赖 | 处理 |
|---|---|---|---|
| on_reply_sent | LOW / 6 | handle_chat、_proactive_at_user、_proactive_speak_for_group | 三入口统一改为发送确认后事件。 |
| _resolve_effect | **HIGH / 7** | _resolve_effect_later、sweep_pending_effects | 保留高风险告警；定时和补偿必须共用幂等结算事务。 |
| prepare_turn | LOW / 2 | RuntimeFacade.submit_turn、TurnService.run | native 和兼容入口都验证 prompt / 静默 / 调用数。 |
| submit_turn | **UNKNOWN / 0** | 图未解析 | [verified] 文本和源码补查确认 QQ `_run_turn_via_engine` 与 WebChat `run_turn` 调用；视为核心路径风险，绝非无调用。 |
| ParticipationManager.observe | LOW / 1 | record_group_chat | 所有消息关系参数补齐；图中涉及 10 条 record_group_chat 执行流程。 |

相关流程：handle_chat、proactive_speak_job、record_group_chat。_resolve_effect 的间接依赖包括 on_reply_sent、expression_sweep_job 与三个发送入口。prepare_turn 没有被枚举进 process 不影响其已验证的真实主链地位。

实施时每次编辑既有符号前重跑该符号 impact，不能用本计划五次 impact 覆盖未来所有改动。每次提交前运行 detect-changes；partial/truncated/UNKNOWN 均需补证。

## 5. Statement-Level PDG Findings — 控制约束

通过 LocalBackend.callTool(`pdg_query`, {mode:"controls", target:文件, repo:"Stella_project", limit:200}) 查询。类名限定 target 曾无法命中，改文件锚后按 functionLine 过滤；不将失败结果当无依赖。Facade functionLine=170，文件共返回 54 条。

| 锚点 | [graph] 控制结果与 [verified] 源码核对 | 实施约束 |
|---|---|---|
| expression_learning.py:188–196 | resolved guard 控制早退；之后查询、分类、更新、merge | 不能只靠读取时 resolved 防并发重复；结算、aggregate 去重须同事务。 |
| turn_service.py:281–305 | DIRECT、Planner WAIT→SILENT、NO_BACKEND、调用上限分支先于生成 | 学习注入不得让这些路径额外请求模型，WAIT 不得补兜底回复。 |
| turn_service.py:309–358 | v2/legacy 组 prompt 后执行最终 budget，再 GENERATE | 两种组合模式都留插槽；可选学习先裁，不能靠通用截断碰运气。 |
| facade.py:191–197 | prepare 后 epoch 不一致会抛取消 | 新记录、重放和后台回调必须保持 turn/epoch，不能让已废弃轮次发出。 |
| facade.py:203–257 | GENERATE 才建 task；超时和 provider 错误走 finalize；取消路径抛错；finally 清 inflight | 不把取消统一变成“……？”；追踪不干扰 finally，不漏终态。 |
| facade.py:259–277 | DIRECT/SILENT 直接 return plan.ctx；预算/无后端仍 finalize | trace 必须覆盖外层生命周期；仅包 finalize 不完整。 |

PDG 的异常/finally 边部分显示一般 F 标签，源码才是具体异常语义的最终依据。这里只用于控制依赖，不声称获得了完整跨 await 数据流证明。

## 6. Proposed Changes — 详细设计

以下接口和表名均为**拟新增**；复用旧模块作为入口，复杂逻辑移入有边界的小模块。

### 6.1 先定义身份、消息证据和投递事实

拟新增 `core/social/contracts.py`：

- `ConversationScope(platform, bot_id, group_id)`；禁止拿 user_id=0 代表“全群反馈对象”。
- `MessageEvidence(event_id, scope, platform_message_id, received_at_utc, event_at_utc, source_kind, user_id, reply_to_id, mentioned_user_ids, text_excerpt, content_hash)`。平台时间用于展示，服务接收时间与序号用于稳定排序；所有时间保存 UTC。唯一键包含 platform/bot/group/message ID，不能只以 QQ message ID 全局去重。无平台 ID 的事件使用独立 UUID，绝不把 0 当全局唯一键。
- `DeliveryReceipt(trace_id, turn_id, epoch, part_index, status, platform_message_id, acknowledged_at_utc, text_hash)`。状态为 pending / acknowledged / failed / unknown；逻辑回复另聚合 complete / partial / failed / unknown。
- `trace_id` 在已接纳入口、硬门禁前创建；`turn_id` 由 Facade 创建，进入 ChatContext。未进入 Facade 的静默决策只有 trace_id / decision_id。原始事件由两个 matcher 处理时用稳定 event_id 关联和幂等入库。
- 将安全标量加入 ChatContext 投影 whitelist，投影 schema 升级并兼容读 v1；不加入 raw_event/bot/凭据。前处理器若返回替代 ctx，外层绑定对象恢复并校验身份，不能产生第二个 turn。

**发送改造**：普通回复、主动 @、主动群聊统一“准备片段→逐段 send→收集回执→写 acknowledged 事实”。普通 matcher 若 finish(message) 无法拿回执，改为 send 每段、最后 finish() 仅结束流程；先以适配器测试核实框架行为。只有确认的片段写 BOT_SELF、启动效果观察；首个成功片段更新一次 note_stella_spoke / 发言占用，不因多段重复计数。后续失败标 partial，评估仅使用已发部分。配额和实际发送统计区分 attempt 与 acknowledged。

发送成功但落库失败、网络超时但平台实际收到：均可能出现 unknown。**不承诺跨网络 exactly-once，不自动重发未知消息**。记录诊断并由 sweep 补偿本地未处理事件；如果没有可恢复 ACK，只能保留 unknown、排除学习。收到 ACK 的本地提交可以幂等重试，不能再次调用网络 send。

WebChat 记录 server_emitted，与 QQ acknowledged 分开；默认不进入群社交效果学习。用户看见/读到不能由服务端返回成功推断。

### 6.2 数据与迁移

**[inferred] 采用组件独立迁移**：social 表留在当前 DB_PATH 的 SQLite；新 `memory/social_schema.py` 管理 `social_schema_meta`，启动时一次初始化与升级，事务成功才提升组件版本。原 expression_store.ensure_tables 改为兼容入口。理由：现有表达表已有独立建表方式，新旁表不改变核心 memory 的结构契约；核心 schema v14 与 Rust 的版本兼容保持现状。若实现期间不得不改核心表，则转用现有 migrate_vN+旧库夹具流程，并同步核查 Rust 契约，不能静默加核心版本。

| 拟新增表 | 最小字段 / 索引 / 约束 |
|---|---|
| social_events | event_id PK、scope、平台 ID、reply_to/@、接收 UTC、来源、摘要；平台 ID 有效时复合唯一；scope+time 索引。 |
| social_deliveries | turn_id+part_index UNIQUE、trace_id、epoch、ACK 状态/ID/UTC、已发文本快照；ACK ID 反查索引。 |
| social_effects | effect_id PK、turn_id UNIQUE、scope、target_user_id nullable、trigger/intent、首末 ACK 时间、window_end、状态、规则/模型评估版本、可评估性。 |
| social_effect_evidence | effect_id+event_id UNIQUE、attribution、confidence、分类、多义原因；一条消息可留下候选关联，但只有明确归因进入统计。 |
| social_assets | asset_id PK、kind(expression/jargon)、scope、owner_user nullable、situation/term/sense、style/definition、confidence、status、revision、UTC；scope+kind+status 索引。 |
| social_asset_evidence | asset_id+event_id+evidence_kind UNIQUE、来源摘要/哈希、作者、时间；用于去重与跨重启用户数。 |
| social_asset_usage | turn_id+asset_id+revision UNIQUE、selected/injected/applied、反馈关联；选择不等于已使用。 |
| social_aggregate_events | effect_id+evaluation_version+metric UNIQUE；用于一次结算只计一次、重评可撤回旧贡献。 |
| social_jobs | job_id、type、dedupe_key UNIQUE、payload_refs、status、attempts、lease_until_utc、not_before_utc；持久化有界工作队列。 |

评估版本结果保留审计历史；新版本取代旧版本时在同事务撤回旧 aggregate contribution，再写新贡献，不跨版本叠加。一条明确群反馈不能因多个 effect 重复计正向人数。所有数据库网络/模型调用都在事务之外；短写事务、busy_timeout、有界重试，失败不阻塞回复。

迁移步骤：

1. 使用 SQLite backup API 生成一致备份，不能在 WAL 写入中直接复制单个 .db；输出旧/新行数与组件版本。
2. 单事务创建旁表、索引和迁移映射，导入旧表达/黑话作为 legacy 候选。用旧行 ID 稳定映射，重复运行不复制。
3. 能可靠确定真实群的源记录才赋 scope；只有共享空间的旧资产保留隔离的 legacy_unscoped，需管理确认后才激活。
4. 旧未结算 effect 缺可靠回执和跨重启时间，标记 legacy_unverifiable，不补造评价、不驱动阈值。旧统计只供历史显示，不混入新分母。
5. 新 worker 替代旧 sleep+sweep 的效果结算；灰度时不同时运行两套正向学习写入。保留兼容读取，禁止对新表旧逻辑双写。
6. 核查导入数量、唯一约束、孤儿 evidence；失败整级回滚。回退代码可忽略新旁表，不要求删数据或恢复整库；恢复备份会丢升级后数据，只作为故障恢复手段。
7. 每条资产携带 origin group；空间映射变化不自动复制/合并真实群资产。删除群数据覆盖新表、trace 与队列；清理后不得由旧任务复活。

trace 使用 STELLA_HOME 下独立诊断 SQLite（拟名 turn_trace.db），避免大快照拖累记忆库。效果事实不依赖该库可用性。两库不作跨库事务，trace 可以丢失并明确标记；社交事实用自身持久化队列补偿。

### 6.3 表达学习：从候选到实际使用

借鉴 MaiBot 的 situation/style 结构，首版规则提取＋人工确认；可选后台模型仅批量处理候选。

1. 从人类原始消息提取短表达；拒绝 BOT_SELF、命令、转发文本、超长复述、纯事实或个人敏感片段。证据持久化后才更新频率/独立作者/不同日期计数。
2. 表达资产包含场景标签（调侃/认同/安慰/拒绝等）、句式/语气、适用条件、反例、禁用范围、来源。自动提取不直接升 active；拟默认至少 3 条独立证据、2 位作者、跨 2 个日期，加人工确认或满足后续评估门槛。[assumed] 小群单人偏好另存个人 scope，不能用同一门槛误推广到全群。
3. 本地 selector 先 scope/status 过滤，再按场景匹配、证据强度、最近适用性排序；重复使用惩罚和负反馈降权；每轮最多 2 条。无合适材料直接返回空。
4. 记录 selected → 实际注入 injected → 输出匹配 applied；只有可确认 applied 的表达才关联其使用结果。未匹配是 unknown，不把整条回复成功归给所有候选。
5. 最近 10 次本群回复已使用的同表达默认不再注入，允许配置。人格规则优先；表达是可选参考，不是“必须使用”的指令。
6. 状态 candidate / active / quarantined / disabled；人工关闭立刻使缓存失效，版本回退可恢复。自动负反馈先 quarantine、保留证据，不永久删除。
7. 后续评分用平滑后的置信下界、样本量和时效，不用“正向比例高的两条样本”压过长期稳定资产；效果数据不足时排序仅依赖适用性，绝不自称效果已提升。

### 6.4 群黑话：先解释，再决定是否使用

1. 候选来自现有正则、引用文本、重复 n-gram 和人工添加；词形归一、停用词过滤、近似合并按群进行。重复转发/同一消息不增加独立证据。
2. 把“词形出现次数”和“词义确认”分开。每个 sense 保存 definition、适用主题、正反例、来源 event_id、时间、置信度、冲突标记。
3. 首版人工确认词义；可选后台每批最多 8 个候选、每词最多 3 个窗口，要求输出定义＋引用证据 ID＋无法确定标记，严格校验 ID 属于本批。一次批处理完成，不为每词固定串联多个 LLM。
4. 语义冲突新增 sense，不覆盖旧义。同一词不同群分别维护；多义语境无法消歧时不注入确定定义，必要时给“本群有两种可能含义”或完全省略。
5. 本地 matcher 在当前用户消息及短尾巴中匹配，最多 3 条定义，注明群内语境和可信度；不因今天常见就宣称通用知识。
6. “可理解”与“可模仿使用”两个开关：默认只解释给模型，主动使用需独立确认，避免刚学会就满屏套黑话。
7. 定义纠正提升为版本变更；旧 evidence 和旧 turn 的快照仍可重现。过期/低置信度资产降为待复核。

### 6.5 Prompt 接入与预算

拟新增 `core/social/context_builder.py` 输出结构化 SocialContext，TurnService.prepare_turn 的两种上下文模式在最终 budget 前接入。保持现有普通回复“当前输入在尾部”和 proactive_at“任务指令在前”的约束，不改成统一机械拼接。

[assumed] 初始配额：表达最多 160 个估算 token，黑话最多 240，共最多 400；不额外增加上下文窗口。先构建无学习基线并计算系统提示词、当前输入、工具/知识必要证据、输出预留，再用剩余额度放可选片段。超限顺序：删除低分表达→剩余表达→低分词义→全部 social context。预算记录实际删掉的资产和原因。

沿用当前估算器不意味着精确 tokenizer 保证；快照记录 estimated/actual 区别，有 tokenizer 时用实际值验收，并保留输出余量。新片段完全空时必须保持既有 prompt 字节不变。规则说明留在固定系统/模板层，群原话和词义作为带来源的低权限数据块，不能提升为系统指令。

### 6.6 回复效果：归因、评估、学习分离

**观察窗口**：[assumed] 首版从首个 ACK 开始，末个 ACK 后 120 秒关闭，另设首个 ACK 后 180 秒硬上限，最多 50 条后续人类事件；达到 cap 标 capped，不能当观察完整。低活跃群可在 60–300 秒范围配置。使用 UTC 持久化 deadline、注入 Clock 作回放；monotonic 只用于进程内耗时。

**归因优先级**：

1. 引用已发平台 message ID：direct，强证据。
2. @bot 且主题/时序一致：probable，保留理由。
3. 同一目标用户且紧邻、无其他竞争回复、主题一致：weak。
4. 普通群消息或多个候选同样接近：ambiguous，保存但不直接计效果。

主动群聊 target_user_id=null，收集全群的后续人类事件；主动 @ 仍保留目标，但群内其他成员的明确引用可作为旁观回应。每条 follow-up 枚举候选 effect，优先明确 ID，再判断冲突；不把“发送后的下一句话”自动归属本轮。排除 BOT_SELF、重放和其他机器人。

**结果分维度存储**：

- engagement：明确关联回应人数/条数、是否推动后续对话；只描述参与。
- reception：支持 / 中性 / 纠正 / 拒绝打扰 / 不确定。
- usefulness：有帮助 / 无帮助 / 不可评估；不能由字数或 emoji 自动判有帮助。
- expression_fit：具体已用表达是否自然/被模仿/被嫌弃；无证据则 unknown。
- observation：complete / capped / insufficient / disconnected / evaluation_failed。
- confidence、evidence_ids、rule_version、judge/model/prompt version。

无回应记录 no_observed_response，**不是负反馈**；缺数据记录 insufficient。规则层识别明确引用、纠正和停止请求；可选 judge 仅处理有归因但语义不确定的批次，严格 JSON、允许弃权，不强行填全数值。停止/静音指令继续由现有硬策略优先处理，不能等后台模型判定。

结算采用 job lease＋事务 CAS；状态改为 resolved、evaluation 写入、aggregate event 插入同事务。定时任务和重启 sweep 共用同一函数。重评不重复累加，版本切换撤回旧贡献。默认先只展示，不自动改 prompt 权重或发言阈值。积累至少 30 个可归因样本、跨 7 天且人工抽检通过后，才允许表达权重小幅调整；每周最多 ±10%，置信不足回到基线。[assumed] 此门槛不是统计显著性保证。

### 6.7 后台预算与任务生命周期

拟新增 `memory/social_worker.py`，复用现有定时任务/启动关闭生命周期，不引入常驻外部队列。队列上限拟 1000；优先效果落账，其次词义，最后表达；满载时丢弃低价值重复提取并计数，不能丢已投递事实。过期 lease 可重领，任务引用已删除数据即终止；最多 2 次重试并退避，最终失败可见。

模型使用现有 ROLE_EXTRACT 配置和 usage 计量，增加 task_kind 标签；新社交子预算不能绕过全局预算。默认 background_llm=false；显式开启后 [assumed] 初始全实例每日最多 20 请求、40k 输入 token、8k 输出 token，三者任一耗尽即停，按部署时区日界结算但保存 UTC。每次发送前原子预留最大额度，完成结算实际值，超时也计入请求；供应商无 usage 时按保守估算，不记作免费。预算限额可配，失败不能自动切换到新云服务。

同端点部署先补齐 native 主生成与 worker 的共同 acquire，避免同资源绕行、重复 acquire 死锁；已有 priority 仅 FIFO，**第一版不承诺抢占**。后台只在空闲窗口尝试短期获锁、拿不到就延期；模型请求超时最多 15 秒，在线 p95 恶化则自动暂停后台。新前台请求仍可能等待一个正在运行的后台请求，因此共享本地模型初始保持后台模型关闭，优先人工确认；需要开启时先通过负载验收或配置现有独立端点。

### 6.8 请求追踪与两类回放

拟新增 `core/observability/turn_trace.py`、`core/observability/replay.py`。

追踪事件包含 trace/turn/event/decision/parent ID、scope、UTC、相对耗时、stage、status、reason_code、版本、输入/输出引用和摘要。阶段至少：ingress、gate、participation、prepare、router/tool摘要、planner、retrieval、social selection、budget、model attempt、finalize、delivery、effect。每次 provider attempt 单独记录序号，取消/超时/本地兜底/DIRECT/WAIT 都有终态。completed 表示生成生命周期完成，delivery 为独立维度，保留旧日志兼容。

两档保存：

- metadata 默认：ID、分数、配置/提示模板版本、token/耗时、hash、错误码、已注入资产 ID/revision；不保存认证信息。
- detailed 按群和时段显式开启：最终 system+messages、工具/检索/资产当时采用的内容快照、模型参数、输出和投递片段；按键白名单生成，不序列化原始 backend 对象、Authorization、环境变量和密钥。用户消息本身也是敏感正文，限鉴权管理接口读取。

[assumed] metadata 保留 30 天、detailed 7 天、单条最大 256 KiB、总库上限 256 MiB；达到容量优先删最旧 detailed。清理包含 SQLite/WAL 与 checkpoint 的实际文件大小监控，不能只 COUNT 行数声称限额达标。截断必须写完整性标记，缺内容就拒绝“完整回放”。

**A. 离线决策回放（默认）**：载入冻结的输入、策略版本、时钟、随机种子、资产 revision、历史返回值，在临时存储中重放评分/选择/预算；provider、工具、发送器全部换只读桩。比较原分数、决定、片段和请求 hash，产 replay_id/parent_trace_id 报告。旧 trace 只有摘要时显示“仅可浏览”，不补查今天的 memory 来伪造当时输入。

**B. 显式模型重生成**：用户在鉴权页面选已完整保存的请求，确认目标模型与额度；复用冻结的工具结果，禁止执行工具/消息发送/记忆写入/学习。消费实际模型预算，结果单独存 replay 命名空间。模型非确定性、模型版本变化意味着输出不保证逐字相同；UI 必须展示差异与不一致配置。第一版不支持任意重跑 agent 或恢复历史副作用。

WebUI 在现有 trace router/service 上新增 turns 列表、单轮时间线、关联效果和 replay 操作，保持原 memory/participation API；所有接口沿用 require_auth、分页/内容大小限制。新增资产管理页提供证据、修订、启停、群筛选和导出/删除。不要新增一套鉴权。

### 6.9 发言时机：分三层推进

**层 1，修复信号和时钟**：record_group_chat 将 reply_to、mentioned_users、is_tome、图像/emoji 标记传入 observe；针对 bot 的硬触发仍按现有直接回复策略，不通过普通参与评分重复发一遍。真实 ACK 才更新“刚说过”。decide、note_stella_spoke、benchmark 全部使用同一注入 Clock，离线不能偷用当前 time.time。

**层 2，补可解释抑制项**：

- 发言占比：滑动窗口内 bot 的逻辑发言数 / 人与 bot 的逻辑发言总数；多段输出算一次。按消息数与时间双窗口计算，避免一段回复被切成多条后惩罚膨胀。
- 新信息量：与最近主动发言的本地 n-gram/已有 embedding 相似度；没有新话题时降权，不为此额外请求模型。
- 空闲退避：连续无新信息而主动探测失败时 30→60→120→240 秒、上限 300 秒；新相关人类消息/明确提及重置，不把后台效果的“无回应”直接当拒绝。
- 保留强相关/明确引用 bypass，但不能越过静音、权限、预算、睡眠等硬门禁。解释日志输出每项贡献、阈值和最终原因。
- scorer 与 _score_with_embedding 目前有重复汇总路径，拟把最终合成收口为一个函数，只改这一处共享公式；分别回归 embedding 开/关。

[assumed] 初始主动发言目标占比 15%，20% 起明显抑制，仅作 shadow 初值，不作为所有群统一人格。已存在策略保持基线，直到离线和试点通过。第一期不自动用效果分数训练权重。

**层 3，处理过期主动回复**：先实现发送前 generation token / topic revision 检查；主动生成期间出现明确转题、撤销、静音或新的直接请求，则在发送前丢弃旧输出并记录 stale，不发“……？”兜底。再按需要接入 Facade.cancel_turn(key, exact_turn_id)，不能取消新一轮或所有会话；同群最多合并 1 次重规划，其他新消息走正常入口，防止热群无限重启生成。

锁顺序固定为既有 group lock → facade lock；收到新消息的观察路径只能更新版本/发出取消信号，不能反向等待 group lock 后再取消。发送每个片段前检查 epoch/版本；已经 ACK 的片段不可撤销，若中途失效停止后续片段并标 partial。cancel 的 RuntimeTurnError(E_CANCELLED) 在网关单独处理成无发送，禁止落入通用异常兜底。

## 7. Implementation Sequence — 分阶段交付

[assumed] 一名熟悉项目的开发者约 **24–32 个开发日**，另留 1–2 周观察窗口；包含下列功能与测试，不含大规模 UI 重设计。按依赖顺序合并小 PR，每个阶段都可独立关停。

| 阶段 | 工作与交付 | 依赖 / 估算 | 出口条件 |
|---|---|---|---|
| P0 契约与迁移 | scope/ID/Clock/receipt 契约，组件迁移、旧库夹具，录制基线评测集 | 3–4 日 | 迁移重复执行不增量复制；旧库可读；无生产行为变化。 |
| P1 真实投递与追踪底座 | 三发送入口 ACK 后落账、partial/unknown；ID 贯通，所有早退事件，trace 列表/详情 | P0；5–6 日 | 发送失败不增加发言与效果；取消无消息；三入口与 WebChat 全覆盖。 |
| P2 效果观察 | 群/用户目标拆分、窗口、证据关联、持久队列、事务结算、评估展示 | P1；4–5 日 | quote 归因测试全过；并发和重启不重复统计；未知不计负面；shadow 数据可审计。 |
| P3 黑话理解 | 证据化候选、词义版本、多义、管理确认、本地 matcher、预算插槽 | P0/P1；3–4 日 | 同词异群不串义；关闭/歧义时无错误注入；预算溢出先丢 optional。 |
| P4 表达闭环 | situation/style、selector、usage/applied、启停/反馈降权、可选后台提取预算 | P2/P3；3–4 日 | 无额外在线调用；不会复读/污染人格；实际用到的资产可关联效果。 |
| P5 回放与时机 | 冻结输入回放/显式重生成、signal/Clock、share/backoff、发送前过期保护 | P1/P2；4–6 日 | 离线回放零副作用；既有场景不退化；取消并发与锁测试通过。 |
| P6 灰度验收 | 管理视图收尾、性能/容量/故障演练、文档、试点参数与回退演练 | 所有；2–3 日 | 达到第 8/13 节门槛，保留观察结果及各群配置。 |

预算有限时，P0→P1→P2 是先交付的最小可信基础；P3 先于自动表达模仿，优先减少“听不懂”。P5 的信号/Clock 修复可随 P1 提前，新增评分和取消策略仍单独灰度。

功能开关（拟新增并走现有配置加载/校验机制）：social.enabled、social.mode=off/shadow/active、expression.inject、jargon.inject、background_llm.enabled、effects.adapt_weights、timing.mode、trace.detail_scopes。各项可独立关闭；shadow 只记录候选决策，不修改实际 prompt/发送。

上线顺序：测试→一群 shadow 至少 7 天→同群先启用黑话理解→表达→新时机；每步至少有 30 次有效覆盖机会，否则延长而不宣布通过。效果自适应默认仍关闭。跨群推广按群独立，不共享反馈；发生串群/重复发送/取消后误发立即关闭相应开关并回退该阶段，保留诊断证据。

## 8. Test Strategy — 自动化、离线与灰度验收

### 8.1 必须覆盖的行为矩阵

| 测试区域 | 输入 → 行为 → 预期 |
|---|---|
| 投递 | 第 1 段成功、第 2 段失败 → partial；只记录第 1 段 BOT_SELF/证据，逻辑发言只计一次；全失败不产生可评估 effect。 |
| 不确定投递 | send 超时/ACK 后数据库暂不可写 → unknown 或本地补偿；不重发；无伪造成功。 |
| 三入口 | 普通、主动 @、主动群聊分别成功/失败 → 同一回执契约；null target 全群归因，user_id=0 不再过滤真实回应。 |
| 图谱高风险结算 | sleep/job/sweep 两路并发、lease 到期、结算中崩溃后重启 → effect 与 aggregate 一次生效；重评撤旧贡献。 |
| 时间与窗口 | 重启、更换 monotonic 起点、边界前后消息、50 条 cap、事件乱序 → 按冻结 UTC 与序号重现，超窗不混入，capped 不装作完整。 |
| 归因 | 两次 bot 回复交错后用户引用第一条 → 只给第一条 direct；无引用竞争 → ambiguous；没人说话 → unknown/no_observed_response。 |
| 资产隔离 | 同词在 A/B 群相反含义、同共享空间 → 分别匹配；legacy 无来源 → 不注入；禁用立即失效。 |
| Prompt | 空 social→字节相同；普通/主动 @/工具/知识场景→顺序保持；近满预算→只裁 optional，调用次数不增加。 |
| 取消 | prepare reset、生成中转题、直接请求插队、取消撞完成、部分发送后取消 → epoch 正确、无误取消后续 turn、不发兜底、不死锁。 |
| 回放 | 修改当前记忆后回放旧 trace → 用旧快照；联网/工具/发送/学习桩一旦被调用即失败；不完整 trace 拒绝完整回放。 |
| 后台 | 全局预算封锁、子预算竞争、超时无 usage、队列满、共享端点 → 原子额度正确、任务有终态、前台不无限等。 |
| 追踪/安全 | DIRECT/WAIT/预算/超时/拒绝/发送失败都有理由；未授权 API 不能读正文；密钥样例不出现在快照/异常文本；容量上限可回收。 |
| 迁移 | 原版四表、空库、部分建表、重复启动、失败中断 → 正确恢复且旧记录守恒；不开新功能时旧流程可运行。 |

复用 [表达学习测试](E:/stella/stella_project/tests/test_expression_learning.py)、[存储测试](E:/stella/stella_project/tests/test_expression_store.py)、[Facade 回归](E:/stella/stella_project/tests/runtime/test_facade_turns.py)、[prompt 顺序测试](E:/stella/stella_project/tests/test_pipeline_compose.py)。拟新增 social schema/delivery/effect/replay 测试使用临时库、假 Clock 和假平台，禁止连接生产机器人。

### 8.2 评测集与指标

[assumed] 建一套脱敏本地黄金集：至少 120 个上下文窗口，覆盖 3 种群活跃度、明确/模糊引用、纠正/调侃、无人回应、同词异义、主动插话、长 prompt；保留群/日期分组，开发集 80、锁定验收集 40，不把同一窗口拆到两边。来源不足时用标记清楚的合成样例补边界，真实效果结论仍等真实试点。

两位标注者独立判断归因、词义、表达自然度和插话是否合适；争议仲裁并保留“不确定”。模型 judge 不是自己的唯一裁判。

拟门槛（阈值为目标，不是现有成绩）：

- 明确引用归因 precision=100%（本地确定 ID 用例）；人工抽样的非直接归因 precision ≥90%，同时报告 coverage / unknown 比例，不能靠全弃权达标。
- 锁定集词义精度 ≥90%，跨群错误为 0；自动模糊匹配未达标就只启用人工确认与精确匹配。
- 表达盲评“自然且不偏离人格”≥基线；明显不合适率 ≤5%。报告样本量和区间，小样本只支持继续试点。
- 保持既有 participation scenarios：高流速触发≤0.05、无机会沉默≥0.8、刚发言得分比≤0.7、过期话题不触发、@ bypass；social candidate≥0.1 等原断言也不删。见 [场景表](E:/stella/stella_project/tests/benchmark/participation/scenarios.toml)。
- 新时机比较按同一冻结输入 A/B：不合时宜主动插话降低，同时明确被点名漏答率不升高；不以回复数量增加为收益。
- 在线新增 LLM 请求数=0；新增本地选取 p95 目标≤30ms，关闭后台模型时端到端 p95 增幅≤5%。共享端点开启后台后 p95 增幅≤10% 否则自动停后台；必须报告机器/模型/负载和基线。
- crash/timeout/trace 库不可写故障下，回复与核心取消语义不受辅助功能拖垮；社交持久化故障以可见降级和 unknown 收敛。

### 8.3 验证命令与实际验证状态

[verified] 当前主机有 Python/Node/npm，pytest 9.1.1；项目 pytest 和 CI 配置、dashboard 的 typecheck/build 脚本已核对。下面是实施后命令，本轮**没有运行功能测试，也没有声称新增功能已通过**。

```powershell
python -m pytest tests/test_expression_store.py tests/test_expression_learning.py tests/test_pipeline_compose.py tests/test_participation.py tests/runtime/ tests/webui/test_webui_conversations_trace.py -q
python -m ruff check .
npm --prefix dashboard run typecheck
npm --prefix dashboard run build
```

CI 全量按现有 [.github/workflows/ci.yml](E:/stella/stella_project/.github/workflows/ci.yml) 跑，依赖先使用项目约定安装。新增测试文件在对应阶段加入同一 pytest invocation。benchmark 使用脱敏副本显式指定 --db、--no-embedding，不能默认读取生产库；[runner](E:/stella/stella_project/tests/benchmark/participation/runner.py) 支持这些参数。

提交前：
```powershell
docker exec -w /repo stella-gitnexus gitnexus detect-changes --scope all --repo Stella_project
```
若源码 HEAD 改动或索引陈旧，先按 AGENTS.md 刷新索引并保留 PDG；检测 partial/truncated 必须重跑至完整。计划文档交付本身不提交代码。

## 9. Risk and Impact Analysis — 风险与全部直接依赖

| 风险 | 影响 | 控制 |
|---|---|---|
| HIGH：_resolve_effect | _resolve_effect_later、sweep_pending_effects 两条直接入口可能同时结算 | 一个持久作业模型、同事务 CAS 与 aggregate 唯一键；并发/崩溃测试是 P2 合并门槛。 |
| UNKNOWN：submit_turn 图漏边 | 已确认 QQ _run_turn_via_engine、WebChat run_turn；核心锁、取消、兜底均受影响 | 源码补证已完成；实施前新 impact 与文本核对；保留 exact turn/epoch 和两入口回归。 |
| on_reply_sent 三直接调用者 | handle_chat、_proactive_at_user、_proactive_speak_for_group | 不遗漏主动路径；投递契约一次改齐；平台 receipt 先用假适配器和已装版本核实。 |
| prepare_turn 两直接调用者 | RuntimeFacade.submit_turn、TurnService.run | native/兼容两路 no-op 字节一致和预算测试。 |
| observe 唯一图直调者 | record_group_chat，另有测试/benchmark 使用 | 元数据不全时允许明确 unknown；Clock 贯通；embedding 双路径保持同公式。 |
| 自我强化和错误归因 | 不合适表达被高频、情绪噪声强化 | 不学 BOT_SELF；分离 attribution/evaluation/adaptation；shadow、人工抽样和小步权重。 |
| 数据隔离/迁移 | 共享空间混群、旧时间错误、新表遗忘清理 | 真实群 scope、legacy_unverifiable、组件迁移、删除覆盖旁表和队列。 |
| 延迟与资源 | 后台 LLM 抢占本地模型；SQLite 阻塞事件循环 | 默认关闭后台模型、共享 gate、事务短写及异步封装/有界工作线程；性能不达标关停。 |
| 回放副作用 | 重跑工具或发送导致重复操作 | 默认离线依赖注入，模型重生成不接工具与发送器；replay 排除学习和正式统计。 |
| 诊断不完整 | trace 丢失却被解释成没有动作 | trace_complete / dropped_events / redacted / truncated 可见，不伪造可重放性。 |

实现阶段需要扩展 impact 到实际改动的 scheduler、消息存储、投影和 WebUI 接口；上表不替代这些编辑前检查。现有 source-level 风险比图的 LOW 更重要，不能用节点数压低并发风险。

## 10. Files Expected to Change — 文件边界

以下是预计文件集合，不是本次已修改列表。新增目录保持小模块，禁止借机重写整个 memory 或 gateway。

| 文件 / 区域 | 变更 |
|---|---|
| core/context.py | trace/turn/scope 安全字段、投影兼容。 |
| core/runtime/facade.py | 身份贯通、生命周期追踪、共同生成 gate、取消/epoch 记录。 |
| core/runtime/turn_service.py；core/context_budget.py | social 插槽、optional 配额、快照；保持现有顺序与分支。 |
| core/social/contracts.py；context_builder.py（新增） | 平台无关契约与本地选择结果。 |
| core/observability/turn_trace.py；replay.py（新增） | 有界快照存储、只读离线回放与受控重生成。 |
| memory/expression_learning.py；expression_store.py | 兼容入口、候选采集、替换旧效果结算和读写路径。 |
| memory/social_schema.py；social_store.py；social_worker.py（新增） | 组件迁移、证据/作业/结算事务与清理。 |
| memory/expression_selector.py；jargon_service.py；reply_effect_service.py（新增） | 表达选择、词义与归因评估。 |
| memory/pre_processors.py | 记录标准化事件关联；核心 group_messages 结构不扩张。 |
| memory/participation/__init__.py；scorer.py；decision.py | Clock、元数据、share/backoff、统一汇总和版本信号。 |
| stella_project/plugins/bot_main/ai_gateway.py | 三发送入口、ACK 后落账、取消区别处理、启动/补偿/关闭 worker。 |
| webui/chat_ingress.py | ID、server_emitted、禁止自动社会效果学习。 |
| webui/services/trace.py；webui/routers/trace.py | 扩展现有 API、完整性与鉴权；保留旧 API。 |
| webui 社交资产 service/router（新增）；dashboard 现有追踪视图及新资产视图 | 证据管理、修订、启停、回放、观测面板；具体 UI 文件实施时用 graph 定位。 |
| core/llm/scheduler.py；usage_store.py | 必要的共享资源检查/任务标签/子预算；本期不实现复杂抢占队列。 |
| 现有 config 配置声明与示例 | 功能开关、预算、保留期，具体配置所有者实施前用 query 定位，禁止散落 getenv。 |
| tests/test_expression_*、test_pipeline_compose、test_participation、runtime、webui、benchmark | 原测试扩展；新增投递、迁移、归因、回放、预算和故障夹具。 |

memory/schema.py / migrations.py / memory_rust/selector.py 是兼容性参考，按当前旁表设计**不计划修改**；一旦实现改了核心 schema，必须显式扩大此计划和验证矩阵。

## 11. Reusable Implementation Context — 执行上下文包

下方 JSON 是可直接复用的实现输入。相对路径用于机器处理；证据摘要由官方 schema-2 helper 生成。计划是唯一仓库写入物，列出的拟新增实现仍不存在。

```json
{
  "implementation_context": {
    "task_summary": "为 Stella 整合表达学习、回复效果评估、群黑话、请求追踪回放和发言时机；只产出计划，本期排除插件隔离。",
    "acceptance_criteria": [
      "五方向实现且按群独立可关停",
      "在线学习专用 LLM 调用增量为零，现有调用上限/8K预算不扩大",
      "投递后学习、归因有证据、结算幂等、unknown不当负反馈",
      "冻结输入回放无发送/工具/记忆/学习副作用",
      "迁移/重启/取消/多段发送/预算/隔离回归通过",
      "shadow与试点数据通过验收后逐项启用"
    ],
    "evidence_provenance": {
      "schema_version": 2,
      "head_commit": "c1a1e843b70de301c6ee5bfe164f23d5c48944a7",
      "generated_plan_path": "docs/plans/2026-09-27-gitnexus-plan-social-learning-feedback-loop.md",
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
          "head_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "index_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "worktree_digest": "sha256:34d982e2622d379623fa8dcb96e87e6b2b352afadb1ae1be27de86e1ef7ec957",
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
          "path": "core/context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6f8b6bf6a1f154336e6b9933d3357aaffda2efa298a09668760940792870d206",
          "index_digest": "sha256:6f8b6bf6a1f154336e6b9933d3357aaffda2efa298a09668760940792870d206",
          "worktree_digest": "sha256:6f8b6bf6a1f154336e6b9933d3357aaffda2efa298a09668760940792870d206",
          "untracked_digest": "absent"
        },
        {
          "path": "core/context_budget.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "index_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "worktree_digest": "sha256:c251a2d207c10db899aff227938fa98ff09a8f9aeb9edc3c6be97dedb364b849",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/scheduler.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:489effc441f08f837240c5f354e7e2e98ed32fe6e4ecc262f5f1b7b4fa712da5",
          "index_digest": "sha256:489effc441f08f837240c5f354e7e2e98ed32fe6e4ecc262f5f1b7b4fa712da5",
          "worktree_digest": "sha256:c5d8bbab4e57cb3433956f18e5760f82ea26b16e3e893f2f18818b3c02a98950",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/usage_store.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b2cc11ebbd4658def4f0db67271b6f9f3acb08f406eeb8db484db5f4e785c4e6",
          "index_digest": "sha256:b2cc11ebbd4658def4f0db67271b6f9f3acb08f406eeb8db484db5f4e785c4e6",
          "worktree_digest": "sha256:b2cc11ebbd4658def4f0db67271b6f9f3acb08f406eeb8db484db5f4e785c4e6",
          "untracked_digest": "absent"
        },
        {
          "path": "core/planner.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b16e935370700c14d75e832968634a95bc77337b947212ed5c488851b39c4873",
          "index_digest": "sha256:b16e935370700c14d75e832968634a95bc77337b947212ed5c488851b39c4873",
          "worktree_digest": "sha256:b16e935370700c14d75e832968634a95bc77337b947212ed5c488851b39c4873",
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
          "head_digest": "sha256:b250ab12d37fda7e447189a1044e4b16c264802500fe71bbef5ec27ff974c88d",
          "index_digest": "sha256:b250ab12d37fda7e447189a1044e4b16c264802500fe71bbef5ec27ff974c88d",
          "worktree_digest": "sha256:b250ab12d37fda7e447189a1044e4b16c264802500fe71bbef5ec27ff974c88d",
          "untracked_digest": "absent"
        },
        {
          "path": "core/runtime/turn_service.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d644d3e33a2925d0cfa346aa7d1859dff9ee7042611f775973a151e05115534d",
          "index_digest": "sha256:d644d3e33a2925d0cfa346aa7d1859dff9ee7042611f775973a151e05115534d",
          "worktree_digest": "sha256:d644d3e33a2925d0cfa346aa7d1859dff9ee7042611f775973a151e05115534d",
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
          "head_digest": "sha256:516f1c81cd0ed984fab054796095ffd2aac2637c1668043bf83629655e5d903e",
          "index_digest": "sha256:516f1c81cd0ed984fab054796095ffd2aac2637c1668043bf83629655e5d903e",
          "worktree_digest": "sha256:516f1c81cd0ed984fab054796095ffd2aac2637c1668043bf83629655e5d903e",
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
          "head_digest": "sha256:b2810a9d0cfcf0b9789a651ad332d39f1d6e6fffc3059c9919da956a66b31df6",
          "index_digest": "sha256:b2810a9d0cfcf0b9789a651ad332d39f1d6e6fffc3059c9919da956a66b31df6",
          "worktree_digest": "sha256:b2810a9d0cfcf0b9789a651ad332d39f1d6e6fffc3059c9919da956a66b31df6",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/expression_store.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1c009f3a35a5c3c26940e13839c37f7feaec0cc8137b973f6e994f5490f426f1",
          "index_digest": "sha256:1c009f3a35a5c3c26940e13839c37f7feaec0cc8137b973f6e994f5490f426f1",
          "worktree_digest": "sha256:1c009f3a35a5c3c26940e13839c37f7feaec0cc8137b973f6e994f5490f426f1",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/migrations.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:eca87c32ce8e51ba7595d8b3be047f581b12437e62b5d59b60116fb73adee222",
          "index_digest": "sha256:eca87c32ce8e51ba7595d8b3be047f581b12437e62b5d59b60116fb73adee222",
          "worktree_digest": "sha256:cb9012580ad85a2095529306af67659873e352287fe6293d37e8048bff487390",
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
          "head_digest": "sha256:ebea33851d84b864eeb1472da99d92df6d1bc1bfc1effb39e951adb722ac6c73",
          "index_digest": "sha256:ebea33851d84b864eeb1472da99d92df6d1bc1bfc1effb39e951adb722ac6c73",
          "worktree_digest": "sha256:ebea33851d84b864eeb1472da99d92df6d1bc1bfc1effb39e951adb722ac6c73",
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
          "head_digest": "sha256:faf972c40a499325e46455116b88e13f60fb84fe1d908cf268d56222b10ecfbf",
          "index_digest": "sha256:faf972c40a499325e46455116b88e13f60fb84fe1d908cf268d56222b10ecfbf",
          "worktree_digest": "sha256:faf972c40a499325e46455116b88e13f60fb84fe1d908cf268d56222b10ecfbf",
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
          "head_digest": "sha256:b7925a88b82e208e5ffa8c5e7a86694d3081742a20284852e4f0afd016bbfa2a",
          "index_digest": "sha256:b7925a88b82e208e5ffa8c5e7a86694d3081742a20284852e4f0afd016bbfa2a",
          "worktree_digest": "sha256:2910cab948d1991750c8e15925e95cddb1bf224d5472239cd804a01aad244448",
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
          "head_digest": "sha256:c9ed86b5e52ca9c0d12c121039be66e6c4b955e3a4d2fd5935882c6d628c9940",
          "index_digest": "sha256:c9ed86b5e52ca9c0d12c121039be66e6c4b955e3a4d2fd5935882c6d628c9940",
          "worktree_digest": "sha256:cf5a22c54e5c799efec1bd2572e2cb237def5a35f15c8a2e10939701f519ff34",
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
          "head_digest": "sha256:ece6d5a6847e5d57f192c3dc702617fb1eb9b698adcc81786b1fb19eabc2be03",
          "index_digest": "sha256:ece6d5a6847e5d57f192c3dc702617fb1eb9b698adcc81786b1fb19eabc2be03",
          "worktree_digest": "sha256:826893be333bb56a99b316794356e9c075f36e62201408d2e406b34e0d65d086",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/trace.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1f42dc70e517404a2600d5688d7f7816dbaed3274935a54e18397f2a24b195fe",
          "index_digest": "sha256:1f42dc70e517404a2600d5688d7f7816dbaed3274935a54e18397f2a24b195fe",
          "worktree_digest": "sha256:1f42dc70e517404a2600d5688d7f7816dbaed3274935a54e18397f2a24b195fe",
          "untracked_digest": "absent"
        },
        {
          "path": "memory_rust/selector.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d21f3f8625fb20fa8d047c348e28244db64077b40d1f468321f00daaf518ead8",
          "index_digest": "sha256:d21f3f8625fb20fa8d047c348e28244db64077b40d1f468321f00daaf518ead8",
          "worktree_digest": "sha256:d21f3f8625fb20fa8d047c348e28244db64077b40d1f468321f00daaf518ead8",
          "untracked_digest": "absent"
        },
        {
          "path": "pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:ff81c6a9b85768d6a729701562eb38bf12a8cae24d355c4a7ee86f9b84887655",
          "index_digest": "sha256:ff81c6a9b85768d6a729701562eb38bf12a8cae24d355c4a7ee86f9b84887655",
          "worktree_digest": "sha256:352e4951a876897d481af7b84c5cc244dea0f03673dbabab0bfb88e1e2cf500f",
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
          "head_digest": "sha256:0826a2feef3ef68824b3d9a38d91fb6a1b30901cd6dd0da29eec4beb922f7d22",
          "index_digest": "sha256:0826a2feef3ef68824b3d9a38d91fb6a1b30901cd6dd0da29eec4beb922f7d22",
          "worktree_digest": "sha256:0826a2feef3ef68824b3d9a38d91fb6a1b30901cd6dd0da29eec4beb922f7d22",
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
          "path": "tests/benchmark/participation/scenarios.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bee6138e32c7d4e50cbc475e430afe9bce4bf086f48d83454863c1539a3ea9ce",
          "index_digest": "sha256:bee6138e32c7d4e50cbc475e430afe9bce4bf086f48d83454863c1539a3ea9ce",
          "worktree_digest": "sha256:bee6138e32c7d4e50cbc475e430afe9bce4bf086f48d83454863c1539a3ea9ce",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/runtime/test_facade_turns.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c86622a9e008ef0464cdbebc365e20bc86da7307be4bf4f22d91286f611b9858",
          "index_digest": "sha256:c86622a9e008ef0464cdbebc365e20bc86da7307be4bf4f22d91286f611b9858",
          "worktree_digest": "sha256:c86622a9e008ef0464cdbebc365e20bc86da7307be4bf4f22d91286f611b9858",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_expression_learning.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a37c37fc17bc86c349082324f744ccf795056df73d55242afa6d06fdd331dff3",
          "index_digest": "sha256:a37c37fc17bc86c349082324f744ccf795056df73d55242afa6d06fdd331dff3",
          "worktree_digest": "sha256:eb31bf787b0b72a92941095e82fc5929225cf9f63bc6fac767f3d34b88775dc0",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_expression_store.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3d0486b766948fdcd2150a609a502381ea0ae2b32056668022e2351a2104f8b8",
          "index_digest": "sha256:3d0486b766948fdcd2150a609a502381ea0ae2b32056668022e2351a2104f8b8",
          "worktree_digest": "sha256:3d0486b766948fdcd2150a609a502381ea0ae2b32056668022e2351a2104f8b8",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_pipeline_compose.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cc9d6f54871db100107067f60833e3682dc8ae30daf64281949cd82faceb36a2",
          "index_digest": "sha256:cc9d6f54871db100107067f60833e3682dc8ae30daf64281949cd82faceb36a2",
          "worktree_digest": "sha256:5714b0bf23cb8d02942230ac3991dcec8e9a080fcc74cf213a824366cdf79658",
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
          "head_digest": "sha256:86d8a39f07aea6bc31477019aee93b2ff3bcc968df37e24bbf0968188488e129",
          "index_digest": "sha256:86d8a39f07aea6bc31477019aee93b2ff3bcc968df37e24bbf0968188488e129",
          "worktree_digest": "sha256:86d8a39f07aea6bc31477019aee93b2ff3bcc968df37e24bbf0968188488e129",
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
          "head_digest": "sha256:020147ca59f5a7732491203c2032caee3bf04a34d32e942439e9bdcf40dcf743",
          "index_digest": "sha256:020147ca59f5a7732491203c2032caee3bf04a34d32e942439e9bdcf40dcf743",
          "worktree_digest": "sha256:020147ca59f5a7732491203c2032caee3bf04a34d32e942439e9bdcf40dcf743",
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
          "head_digest": "sha256:c9bfdcc2011a85c3732375cfac8efb6dbaa2729375b205af9401664be0ed2973",
          "index_digest": "sha256:c9bfdcc2011a85c3732375cfac8efb6dbaa2729375b205af9401664be0ed2973",
          "worktree_digest": "sha256:81d78fc65f9341a54f7e6269e87f22d09a6c2d3dbb97be7381bc8dc779e9ccde",
          "untracked_digest": "absent"
        }
      ]
    },
    "primary_symbols": [
      {
        "symbol": "on_reply_sent",
        "file": "memory/expression_learning.py",
        "lines": "90-124",
        "role": "既有三发送入口学习触发点，迁移到 ACK 后"
      },
      {
        "symbol": "_resolve_effect",
        "file": "memory/expression_learning.py",
        "lines": "188-196",
        "role": "HIGH 风险结算，替换为事务幂等"
      },
      {
        "symbol": "TurnService.prepare_turn",
        "file": "core/runtime/turn_service.py",
        "lines": "268-358",
        "role": "social 选择和预算边界"
      },
      {
        "symbol": "RuntimeFacade.submit_turn",
        "file": "core/runtime/facade.py",
        "lines": "170-277",
        "role": "turn 身份、锁、取消、完整追踪"
      },
      {
        "symbol": "ParticipationManager.observe",
        "file": "memory/participation/__init__.py",
        "lines": "183-272",
        "role": "信号入口与解释决策"
      }
    ],
    "related_symbols": [
      {
        "symbol": "handle_chat",
        "relationship": "CALLS on_reply_sent",
        "relevance": "普通回复 ACK 后写入"
      },
      {
        "symbol": "_proactive_at_user",
        "relationship": "CALLS on_reply_sent",
        "relevance": "定向主动回复"
      },
      {
        "symbol": "_proactive_speak_for_group",
        "relationship": "CALLS on_reply_sent",
        "relevance": "群目标不能用 user_id=0 过滤反馈"
      },
      {
        "symbol": "_resolve_effect_later",
        "relationship": "CALLS _resolve_effect",
        "relevance": "旧定时路径退役或转持久队列"
      },
      {
        "symbol": "sweep_pending_effects",
        "relationship": "CALLS _resolve_effect",
        "relevance": "重启补偿与实时任务共用幂等逻辑"
      },
      {
        "symbol": "expression_sweep_job",
        "relationship": "indirect CALLS _resolve_effect",
        "relevance": "网关补偿入口"
      },
      {
        "symbol": "TurnService.run",
        "relationship": "CALLS prepare_turn",
        "relevance": "兼容路径回归"
      },
      {
        "symbol": "record_group_chat",
        "relationship": "CALLS observe",
        "relevance": "传齐 reply/@/media 元数据"
      },
      {
        "symbol": "_run_turn_via_engine",
        "relationship": "source-verified CALLS submit_turn",
        "relevance": "补证 UNKNOWN 图结果"
      },
      {
        "symbol": "webui.chat_ingress.run_turn",
        "relationship": "source-verified CALLS submit_turn",
        "relevance": "WebChat server_emitted"
      },
      {
        "symbol": "record_message",
        "relationship": "message evidence producer",
        "relevance": "group_messages 已保存 msg_id，关系旁表接入"
      },
      {
        "symbol": "_compose_prompt",
        "relationship": "prompt builder",
        "relevance": "普通输入在尾、proactive_at 指令在首"
      },
      {
        "symbol": "note_stella_spoke",
        "relationship": "participation state update",
        "relevance": "只在 ACK 后更新且注入 Clock"
      },
      {
        "symbol": "_score_with_embedding",
        "relationship": "score aggregation path",
        "relevance": "与 scorer 汇总收口避免两套规则"
      },
      {
        "symbol": "RuntimeFacade.cancel_turn",
        "relationship": "cancellation",
        "relevance": "exact turn_id 防止误杀下一轮"
      },
      {
        "symbol": "acquire",
        "relationship": "scheduler gate",
        "relevance": "当前 FIFO，不承诺背景抢占"
      },
      {
        "symbol": "resolve_reply_effect",
        "relationship": "legacy CAS store",
        "relevance": "单独 CAS 不足以原子累加模式"
      },
      {
        "symbol": "run_migrations",
        "relationship": "migration reference",
        "relevance": "事务成功才提升版本原则"
      }
    ],
    "execution_path": [
      "ingress 标准化 event/scope/trace",
      "门禁/参与决策；未进入生成也有原因",
      "Facade 分配 turn 并保留 epoch",
      "prepare 原检索/planner/router 后选择可选 social",
      "预算、完整性标记、provider attempt",
      "finalize 或早退；cancel 保持静默",
      "逐片段发送并接收 ACK；unknown不重发",
      "投递事实驱动持久效果作业",
      "冻结窗口归因和结算，再展示/小步反馈"
    ],
    "pdg_constraints": [
      {
        "description": "WAIT/DIRECT/调用上限先于生成",
        "affected_statements": [
          "core/runtime/turn_service.py:281",
          "core/runtime/turn_service.py:291",
          "core/runtime/turn_service.py:301"
        ],
        "implementation_consequence": "social不突破早退或增加在线调用"
      },
      {
        "description": "prepare 后 epoch fence",
        "affected_statements": [
          "core/runtime/facade.py:191",
          "core/runtime/facade.py:197"
        ],
        "implementation_consequence": "过期轮次不得发出"
      },
      {
        "description": "取消与异常兜底不同",
        "affected_statements": [
          "core/runtime/facade.py:228",
          "core/runtime/facade.py:235",
          "core/runtime/facade.py:249"
        ],
        "implementation_consequence": "网关区分 E_CANCELLED，保留 finally 清理"
      },
      {
        "description": "DIRECT/SILENT 不 finalize",
        "affected_statements": [
          "core/runtime/facade.py:259",
          "core/runtime/facade.py:267"
        ],
        "implementation_consequence": "外层追踪覆盖所有终态"
      },
      {
        "description": "已结算 guard 不是并发事务",
        "affected_statements": [
          "memory/expression_learning.py:190",
          "memory/expression_learning.py:192"
        ],
        "implementation_consequence": "effect与aggregate同事务CAS"
      }
    ],
    "architectural_patterns": [
      {
        "pattern": "prepare / facade / finalize",
        "example_location": "core/runtime/turn_service.py; core/runtime/facade.py",
        "usage_guidance": "保留职责和每 key 锁，不新增第二聊天引擎"
      },
      {
        "pattern": "组件旁表及有界 SQLite 存储",
        "example_location": "memory/expression_store.py",
        "usage_guidance": "social独立版本事务升级，新增表不改核心memory schema"
      },
      {
        "pattern": "鉴权 trace router",
        "example_location": "webui/routers/trace.py",
        "usage_guidance": "复用require_auth和响应封装"
      },
      {
        "pattern": "确定性 prompt 护栏",
        "example_location": "tests/test_pipeline_compose.py",
        "usage_guidance": "空social保持字节相同、两种intent保留顺序"
      }
    ],
    "files_to_modify": [
      {
        "file": "core/context.py",
        "symbols": [
          "ChatContext"
        ],
        "intended_change": "身份字段和投影兼容"
      },
      {
        "file": "core/runtime/facade.py",
        "symbols": [
          "submit_turn",
          "cancel_turn"
        ],
        "intended_change": "追踪、gate、取消与身份"
      },
      {
        "file": "core/runtime/turn_service.py",
        "symbols": [
          "prepare_turn",
          "_compose_prompt"
        ],
        "intended_change": "可选social插槽与完整快照"
      },
      {
        "file": "core/context_budget.py",
        "symbols": [],
        "intended_change": "先裁可选学习，保留输出余量"
      },
      {
        "file": "memory/expression_learning.py",
        "symbols": [
          "on_reply_sent",
          "_resolve_effect",
          "sweep_pending_effects"
        ],
        "intended_change": "ACK入口和持久幂等结算"
      },
      {
        "file": "memory/expression_store.py",
        "symbols": [],
        "intended_change": "兼容迁移与新存储代理"
      },
      {
        "file": "memory/pre_processors.py",
        "symbols": [
          "record_message"
        ],
        "intended_change": "标准化事件关联，旁表关系"
      },
      {
        "file": "memory/participation/__init__.py",
        "symbols": [
          "observe",
          "note_stella_spoke",
          "_score_with_embedding"
        ],
        "intended_change": "Clock/信号/合成评分"
      },
      {
        "file": "memory/participation/scorer.py",
        "symbols": [],
        "intended_change": "share与新信息抑制"
      },
      {
        "file": "memory/participation/decision.py",
        "symbols": [],
        "intended_change": "Clock/退避/过期决策"
      },
      {
        "file": "stella_project/plugins/bot_main/ai_gateway.py",
        "symbols": [
          "handle_chat",
          "_proactive_at_user",
          "_proactive_speak_for_group",
          "record_group_chat",
          "expression_sweep_job"
        ],
        "intended_change": "回执、精确取消、worker生命周期"
      },
      {
        "file": "webui/chat_ingress.py",
        "symbols": [
          "run_turn"
        ],
        "intended_change": "身份、server_emitted"
      },
      {
        "file": "webui/services/trace.py",
        "symbols": [],
        "intended_change": "turn/effect/replay读模型"
      },
      {
        "file": "webui/routers/trace.py",
        "symbols": [],
        "intended_change": "鉴权分页API"
      },
      {
        "file": "core/llm/scheduler.py",
        "symbols": [
          "acquire"
        ],
        "intended_change": "共同资源边界，保持可验证的FIFO语义"
      },
      {
        "file": "core/llm/usage_store.py",
        "symbols": [],
        "intended_change": "任务标签和社交子预算"
      },
      {
        "file": "core/social/contracts.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "core/social/context_builder.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "core/observability/turn_trace.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "core/observability/replay.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "memory/social_schema.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "memory/social_store.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "memory/social_worker.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "memory/expression_selector.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "memory/jargon_service.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      },
      {
        "file": "memory/reply_effect_service.py",
        "symbols": [],
        "intended_change": "拟新增；接口契约见第6节"
      }
    ],
    "tests": [
      {
        "file": "tests/test_expression_learning.py",
        "scenarios": [
          "默认零LLM",
          "不学BOT_SELF",
          "unknown不是负面",
          "三入口投递后学习"
        ]
      },
      {
        "file": "tests/test_expression_store.py",
        "scenarios": [
          "旧数据导入不重复",
          "事务结算一次计数",
          "版本重评撤旧贡献"
        ]
      },
      {
        "file": "tests/test_pipeline_compose.py",
        "scenarios": [
          "空social逐字一致",
          "ordinary/proactive_at顺序",
          "预算只裁optional"
        ]
      },
      {
        "file": "tests/runtime/test_facade_turns.py",
        "scenarios": [
          "早退完整追踪",
          "epoch/cancel静默",
          "超时兜底保留",
          "共享gate无双重锁"
        ]
      },
      {
        "file": "tests/test_participation.py",
        "scenarios": [
          "Clock",
          "元数据",
          "强触发不越硬门禁",
          "embedding开关同公式"
        ]
      },
      {
        "file": "tests/benchmark/participation/runner.py",
        "scenarios": [
          "冻结时钟",
          "真实回放无生产写入",
          "原场景不退化"
        ]
      },
      {
        "file": "tests/test_social_delivery.py (proposed)",
        "scenarios": [
          "ACK/failed/partial/unknown",
          "网路不确定不自动重发",
          "多段逻辑发言一次"
        ]
      },
      {
        "file": "tests/test_social_migrations.py (proposed)",
        "scenarios": [
          "空库/旧四表/中断/重复迁移",
          "legacy scope不猜测",
          "旧时间不可核验"
        ]
      },
      {
        "file": "tests/test_reply_effect_service.py (proposed)",
        "scenarios": [
          "引用归因",
          "全群目标",
          "多effect冲突弃权",
          "deadline/cap/重启/并发"
        ]
      },
      {
        "file": "tests/test_social_replay.py (proposed)",
        "scenarios": [
          "冻结资产",
          "无联网/发送/工具/学习",
          "不完整拒绝",
          "密钥清理"
        ]
      },
      {
        "file": "tests/webui/test_webui_conversations_trace.py",
        "scenarios": [
          "旧API兼容",
          "鉴权",
          "完整性标记",
          "新trace/资产/replay API"
        ]
      }
    ],
    "verification_commands": [
      "python -m pytest tests/test_expression_store.py tests/test_expression_learning.py tests/test_pipeline_compose.py tests/test_participation.py tests/runtime/ tests/webui/test_webui_conversations_trace.py -q",
      "python -m ruff check .",
      "npm --prefix dashboard run typecheck",
      "npm --prefix dashboard run build",
      "docker exec -w /repo stella-gitnexus gitnexus detect-changes --scope all --repo Stella_project"
    ],
    "risks": [
      "HIGH结算并发",
      "UNKNOWN facade图漏边，已源码补证",
      "ACK与落库不能跨网络原子",
      "共享模型FIFO延迟",
      "串群学习/旧scope不明确",
      "取消fallback误发",
      "trace不完整误称可重放"
    ],
    "assumptions": [
      "用户已选择Deep/Full；只计划不实施，插件隔离排除。",
      "实现前以安装适配器的API和假bot测试核实send返回message_id及finish()结束语义。",
      "预算400 tokens、反馈120秒、20后台请求/日、性能指标为初始建议，必须以本机模型/真实群shadow验证。",
      "social旁表无需修改核心memory schema；若改核心结构，重新核查Python/Rust版本与migrate_vN。",
      "Docker stella-gitnexus当前可用；后续不可用则按AGENTS提供runner重新确认，不跳过图分析。",
      "pytest/Node/npm及脚本入口已核对；本轮未执行功能/构建测试，实施前确认项目依赖完整。"
    ],
    "open_questions": [
      "实际群活跃度与可用黄金集数量决定灰度时长；样本不足延长",
      "是否将来允许跨群显式共享已确认资产：本期默认否",
      "共享本地端点是否适合后台模型：未通过负载门槛则保持关闭"
    ],
    "avoid": [
      "Do not repeat full repository discovery",
      "Do not replace established patterns without evidence",
      "不实现插件隔离",
      "不编辑符号前跳过impact",
      "不将UNKNOWN/partial/truncated当安全",
      "不在ACK前计发言/效果",
      "不自动重发unknown",
      "不以monotonic跨重启结算",
      "不让空反馈等于负反馈",
      "不增加在线学习LLM调用",
      "不回放真实工具/发送/学习",
      "不跨真实群共享资产",
      "不把生成完成视为投递",
      "不未经graph检查提交"
    ]
  }
}
```

## 12. Assumptions / Open Questions / Deferred — 假设与暂缓项

- **[assumed] 本地模型与预算**：按现有 8K 和低额外成本路线设计，不假定硬件足以并行。400 token 学习额度、观察窗口、后台请求上限和性能阈值均为初值；P0 记录模型/硬件基线，P6 实测后调整。
- **[assumed] 平台回执**：需在安装版本的 NoneBot/OneBot 适配器上验证 send 返回结构及 finish() 行为，用假适配器测试补强，不能以一般经验替代。消息 ACK 表示接口接受，不保证所有群成员已阅读。
- **[inferred] 迁移范围**：旁表独立版本可避免无意义扩大核心 memory/Rust schema；实施如发现实际核心结构依赖则重新评估，走已有版本迁移规范。
- **[assumed] 资源与工期**：24–32 开发日是熟悉项目、现有 CI 可用的单人估算；上线观察不靠加班压缩。数据不足时延期启用自适应，不伪造“已验证提升”。
- **未决但不阻塞计划**：试点群、黄金集真实数据量、是否已有独立后台模型端点。默认选一个允许试点的群、后台模型关闭、所有群共享关闭；实施阶段按现有配置确定，不需要重新讨论架构。
- **明确暂缓**：插件运行隔离、每轮 LLM 表达 selector、逐词多轮黑话鉴定、强化学习/全自动阈值训练、在线重跑工具链、自动跨群资产共享、复杂抢占式 LLM 调度。
- 现有规则效果分类和旧统计保留历史查询，但不作为新系统高置信训练标签。此计划没有建立任何生产模型调用、定时自动化、外部发送或代码提交。

## 13. Definition of Done — 完成标准

完成必须同时满足：

- [ ] 五项功能能由 trace → 真实投递 → 证据 → 资产/时机决策相互追溯；没有发送的轮次有可解释原因。
- [ ] 普通、主动 @、主动群聊、WebChat 的不同投递语义正确；partial/unknown 可见；不自动重发未知消息。
- [ ] 旧库可迁移、重复迁移安全；旧 monotonic 不跨重启复用；队列/结算/重评幂等且经崩溃恢复测试。
- [ ] 新资产真实群隔离；来源可查、词义可修订、表达可禁用；旧无来源资产不自动进入 prompt。
- [ ] no-op prompt、Planner WAIT、DIRECT、预算、取消和 provider 兜底行为通过回归；在线模型调用数不增加。
- [ ] 回放默认零副作用；只允许完整冻结快照声明可重放；显式重生成单独计费计量且不污染正式学习。
- [ ] 既有参与 benchmark 不退化，新增策略有解释；真假时钟隔离、过期主动生成与精确取消通过测试。
- [ ] 后台预算、共享模型闸门、追踪容量、数据清理、鉴权与敏感字段清理通过实际验证。
- [ ] 通过第 8 节离线/性能/试点门槛；报告覆盖率、未知率、样本量及失败案例，不只给平均分。
- [ ] 各开关回退演练成功；部署/迁移/操作说明齐全；提交前 GitNexus detect_changes 完整无截断，HIGH/UNKNOWN 风险已逐项处理。

**本次计划交付状态**：[verified] 已完成固定版本源码调查、五主符号 impact、中央控制依赖 PDG、接口/数据/迁移/测试/灰度设计；本轮只新增这份计划。功能实现、迁移执行、测试结果与效果提升仍须按阶段验证。
