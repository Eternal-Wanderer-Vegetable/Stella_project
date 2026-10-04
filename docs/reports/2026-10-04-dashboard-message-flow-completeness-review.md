# Dashboard 消息工作流完整性复核

日期：2026-10-04（Asia/Shanghai）。范围：当前源码、随包 manifest、前后端合同和隔离探针；不修改业务代码。

## 结论

**目前展示不完整。** 群聊/WebChat 的高层处理链已经存在，运行状态、丢失事件、未知节点、回放和 SSE 也已有实现；但“完整流程”仍是人工语义目录的概览，不能等同于全部源码业务闭包，也不能把“实际路径”的所有连线视为已经发生的跳转事实。

最直接的缺口是 QQ 私聊未完整接入目录和消息 IO、观测 root 键可能串线、连线仍由端点推断、实时输出不刷新，以及源码闭包与版本绑定不足。现有测试全部通过，不能据此判定上述完整性要求已满足。

## 复核基线与证据边界

- 工作目录：`E:\stella\stella_project`。
- 分支：`feat/multi-user-identity-repair`。
- HEAD：`6d73b9f70bd3797cb97af88a999bc59d9582cdcf`。
- GitNexus 仓库：Docker `stella-gitnexus` 内 `/repo`，别名 `Stella_project`。
- 原索引为 `0ef8e2a`；本轮执行 `analyze --index-only --pdg` 后索引提交与 HEAD 一致。刷新耗时约 215 秒。
- 本轮图查询覆盖消息入口、私聊主链、`edgeTraversed`、manifest 生成、IO、spec、root 键和共享 runtime；再定点核对源码。图中发现 `handle_private_chat → send` 等真实流程，不沿用旧文档的“主入口仅支持群聊”结论。
- GitNexus 报告入口排名、分支和深度截断；845 条抽样流程不代表所有运行入口。大于 512KB 的消息 manifest 被图索引跳过，本轮直接读取其 JSON 核验。
- 初始已有未跟踪文件 `docs/plans/2026-10-04-gitnexus-plan-laya-decision-layer-integration.md`，未改动。
- 未执行真实 QQ adapter/账号现场消息验收、真实模型全链路数据集实验或最终安装包验收。下文区分源码确认、隔离复现与条件性影响。

## 已有覆盖与完成项

当前 manifest 为 `core/observability/flows/message-flow.da26f49a7853.json`，拓扑版本 `2026.10.03`。

| 项目 | 当前证据 | 如何理解 |
| --- | --- | --- |
| 语义节点/静态边/泳道 | 130 / 124 / 14 | 是已登记目录的规模，不是全部业务流程的覆盖率 |
| 可解析源码锚点 | 129 个节点、81 个不同文件/符号锚点 | 多个节点复用同一大函数，不能视为129段独立业务闭包 |
| 语句结构统计 | 6,725 个 closure sites | 含重复锚点；不是逐语句运行事件数量 |
| 未解析调用 | 1,808 | 已统计，但没有逐项解释并收口；也不是实际运行失败次数 |
| 同文件可达闭包截断 | 4 个语义节点 | `consolidate.extract/preflight/write`、`memory.consolidate.entry` |
| 声明入口/root接入 | 20 / 16 | 不可直接报告为80%覆盖；其中包括动态/跨语言边界和内部尚未接入入口 |
| 流程族 | 9 | 消息、记忆、主动、社交、维护、预约、知识、Cometa、生命周期 |

高层目录覆盖 WebChat、群消息记录/过滤、控制命令、回复门控/预算、prepare/Planner/能力、生成、后处理、发送/记账、整合/晋升、主动发言和 Cometa。后台族也已有部分节点和 root。

已实现并由本轮现有测试验证的能力包括：活跃运行与过期化身的区分、按运行归账的丢失/持久化完整性、脱敏、未知节点占位、实例计数、事件分页、SSE补读/重连、请求代际隔离，以及只读回放。应保留这些能力，增量修复缺口。

## 主要发现

### R1 · P1：私聊入口与消息 IO 没有完整进入流程展示

**源码确认、隔离复现。** `ai_gateway.py:388` 的前置处理器对私聊创建 `root_kind="qq_private"`；`handle_private_chat:1267` 已实际执行会话注册、消息落库、共享 runtime、分段发送和记账。当前 `flow_catalog.py:508` 的入口映射没有 `qq_private`，入口 inventory 也没有私聊主处理器；`FlowPage.vue:22` 的筛选/标签表缺少私聊及多种新后台 root。

私聊新增 `chat.conversation_lock`、`chat.persist`，群聊和私聊共用 `chat.runtime`，均未登记为语义节点/边。未知节点占位能保留事件，却不能补出这些节点在完整链路中的连通关系。

`webui/services/flow.py:335,361,457` 仍按群聊解释 IO：输入白名单不含 `qq_private`，`qq:<bot>:private:<user>` 被拆成 `<bot>:private:<user>` 作为 `group_id`。实际私聊历史使用注册表分配的 `storage_session_id`，不是该字符串。探针在隔离库写入真实形状的私聊消息后，`message_io()` 返回 `input=null`。

私聊发送使用 `scope=None`（`ai_gateway.py:1409`）；`core/social/delivery.py:223` 只在 scope 非空时持久化社交发送回执。流程 IO 的回执读取与 BOT_SELF 群号兜底因此也不能完整还原私聊输出。可保留“不进入群社交学习”的业务边界，同时增加会话中立的投递事实取数。

另有已使用、未登记的固定节点：`turn.direct_silent`、`compact.commit`、`proactive.consolidate`、`command.reply`。固定语义节点应登记或提供明确 alias，不应全部依赖 unknown 占位。

**建议：** 将规范会话身份、注册表存储键与来源键贯通到 root/IO，补私聊入口、节点和边；筛选项从 manifest/运行数据生成。验收私聊文本、图片、插件接管、预算阻断、取消、部分发送和压缩派生。

### R2 · P1：root去重键缺少Bot和会话身份，存在串线条件

**源码确认、键值探针复现；真实并发串线未现场触发。** `ai_gateway.py:232` 的 `_flow_key()` 返回 `(group_id或0, message_id)`。不同 Bot 的私聊事件只要 message_id 相同，都得到 `(0,相同ID)`。`_flow_ingress_root` 遇到已有键直接返回；`_flow_root_for` 和结束处理器也使用同一个键。

探针结果：Bot10001/用户20001/消息7与Bot10002/用户20002/消息7的键均为 `(0,7)`。并发时可复用同一 root，或由另一事件提前关闭；群事件同样缺 Bot 维度。私聊来源键 `qq:<bot>:0:<msg>` 也缺 peer 信息。

**建议：** 使用包含平台、Bot、conversation kind/key、message ID的完整事件身份；不要仅修scope显示。增加不同Bot同ID、私聊/群聊同ID及并发结束顺序的验收。

### R3 · P1：“实际路径”仍有推断连线，可能误报经过的分支

**源码确认、隔离复现。** `flowLayout.ts:361,373` 的 `sameChain/edgeTraversed` 以来源节点start/decision与目标节点finish/decision的时间顺序判断经过；没有同时存在instance_key时，`sameChain`最终直接返回true，即便双方有不同span且不是父子关系。

探针构造无transition事实的两个兄弟span：A start，B finish。预期不证明A→B，实际 `edgeTraversed=true`。即使同一instance_key，也仅说明属于同一轮业务，不证明该轮曾直接经过特定静态边。布局不消费包含from/to/edge/分支选择的明确跳转记录，也不依据attempt匹配两端。

`flowLayout.ts:251` 又把静态源/汇节点接到合成“开始/结束”。这些锚点是布局辅助，不能代表root已开始/终结；运行中的或未知孤立节点也可能被接到“结束”。

**建议：** 写入并消费边级跳转/guard/spawn事实，携带来源、目标、实例与attempt。旧事件只显示观测到的节点及“静态关系/未确认连线”；root终结锚点依据真正trace_end。验收兄弟span、并行、循环、重试和未选择分支。

### R4 · P1：源码闭包与漂移门禁不足，页面也没有展示其覆盖边界

**源码确认、内存变更探针复现。** `generate_message_flow.py:198` 把import目标统一解析为external，包括项目内的跨文件调用。`reachable_symbols:292`只递归同文件local目标；`build_manifest:411,414`为直接锚点计算body_hash，对可达辅助符号主要保存名称列表，未保存每个辅助符号的体hash和完整结构。

探针仅在内存中改变可达辅助函数 `_flow_key` 的返回逻辑，未改磁盘文件；重新生成的 `problems=[]`，content hash没有变化。故“当前 --check 通过”不能证明辅助函数实现或新入口没有漂移。已有私聊主入口未登记，但本轮检查仍通过，入口自检目前只校验已登记列表，没有自动发现所有新增入口。

manifest仍有1,808个unresolved调用和4处reachable截断；它们没有使生成失败。`FlowSpec`前端类型（`api/flow.ts:106`）只消费语义节点/边等字段，页面不展开source_closure、source_ref、entry_inventory、coverage。用户看不到业务/符号/语句三级结构，也看不到静态覆盖分母与未解析范围。

**建议：** 为声明入口生成跨文件本地业务闭包，逐符号保存hash/结构，新增入口和未解释调用必须对账；区分外部SDK边界、动态边界与内部待接入流程。前端展示源码展开及独立的目录、运行、数据集覆盖状态。`core_unresolved_allowed=0`是配置值，不能作为实际未解析调用为零的结论。

### R5 · P1：历史图未绑定内容digest，同拓扑版本可读到错误源码清单

**源码确认、隔离复现。** `message_flow.py:256`以topology_version作为flow_specs主键，`:689`使用INSERT OR IGNORE；`begin_trace:937`向root的spec_digest写空字符串。后端 `flow.spec:283`与前端 `flow.loadSpec:235`也只按topology_version读取/缓存。

设计允许源码内容变化但语义拓扑版本不变。在隔离库中先后归档相同拓扑版本、不同内容的old/new两份spec：第二个root仍读取第一份old spec，两个root的spec_digest均为空。当前不同topology_version隔离已有效，但同版本内容变更未受保护。

**建议：** 以不可变内容digest归档并让每个root实际持有它；读取和缓存优先使用digest，topology_version保留为语义版本/legacy字段。对旧数据明确unmapped/legacy状态，不能猜绑定。

### R6 · P1：实时查看结束后，输入/输出仍可能停在打开时的快照

**源码确认。** `flow.ts:183`仅在openTrace时调用getMessageIo；收到trace_end后（`:311`）只重新调用getMessage更新detail，不刷新IO。页面“刷新”按钮也只fetchEvents。

打开一条仍在生成的轨迹时，IO可能暂无回复；后续发送和root结束的事实已进入画布，但输入/输出卡仍可保持空白。重新打开才会重取IO。这是展示滞后，不是业务没有发送。

**建议：** 在终帧及相关投递/记账事实后刷新IO，并用请求代际与会话身份保护响应；手动刷新同时刷新元数据、IO和关系。验收先打开running轨迹、稍后发送成功的场景。

### R7 · P2：后台节点/派生关系/对象履历没有组成可追踪的闭环

**manifest和页面源码确认。** 130个节点中有10个没有任何目录边，其中包括知识入口/解析/版本、预约tick/gate/agent/deliver、社交worker、插件桥和参与评分节点。布局会将其分别合成为“开始→节点→结束”，不能展示知识和预约的实际执行顺序。

inventory还明确记录idle维护和startup未接入独立root；内部未接入不能按第三方opaque边界判为已完整覆盖。Rust/NoneBot动态边界可以明确保留，但需要报告可见范围。

`FlowPage.vue:480`仅将relation显示成短ID chip，没有跳转；`api/flow.ts:194,202`提供运行对象和对象履历API，但页面/store没有调用。因而消息→整合批次→候选/正式记忆、消息→Cometa→通知等过程尚不能从工作流页面完整追到下游。

**建议：** 补后台静态边及真实关系；关联轨迹可点击、对象可反查历史；内部未接入入口单独展示为待观测。保持业务提交、异步后处理、任务执行和通知投递状态分别可见。

### R8 · P2：历史可达性与“加载完整”没有独立状态

**页面/store源码确认。** 消息列表固定limit=100（`flow.ts:149`），虽然保存messagesTotal但没有列表翻页/加载更多。更早的轨迹无法在当前列表选择。

事件分页上限为100页（约10万事件），达到上限没有loaded/truncated状态；页面计数是visibleEvents/orderedEvents，即已加载集合内部的计数，不与event_count/high_watermark核对。SSE可继续补读，但未成功补齐时不能让用户误认为已加载完整。storage integrity与浏览器loaded completeness必须分开。

`FlowPage.vue:146`在spec不存在时直接不生成布局，即使已经取得真实事件，“实际路径”也没有事件占位图。详情只显示最近8个事件、最近一组metrics；输出只显示前4行，没有展开入口。

**建议：** 支持列表分页、显式加载进度/截断/重试；spec缺失时展示事件时间线/实例占位图；详情与输出可展开完整内容。没有观测事件的节点详情文案应统一为“未观测”，不要用`:719`的“没有经过”推断未执行。

### R9 · P2：checkpoint可把未结束实例投影为成功

**API合同探针复现；未确认常规路径都触发。** `flowReducer.ts:70`将checkpoint直接设为succeeded。对于带相同span_id的start→checkpoint、尚无finish的事件序列，探针得到succeeded，而该span仍在运行。checkpoint API允许携带span_id，但其语义是过程事实。

**建议：** checkpoint更新过程信息，不结束已有running实例；只有明确终态事件关闭span。增加“提交检查点后仍有后处理”和“中途checkpoint后异常”的验收。

## 本轮验证

| 检查 | 结果 | 证明范围 |
| --- | --- | --- |
| `python scripts/generate_message_flow.py --check` | 通过，da26f49a7853匹配 | 当前生成器能识别的目录/锚点内容没有漂移；不等于全部闭包完整 |
| `python -m pytest tests/observability tests/webui/test_message_flow_api.py -q` | 104 passed | 现有观测、运行、完整性、inventory、API合同 |
| `python -m pytest tests/test_private_chat_ingress.py -q` | 11 passed | 私聊入口业务合同，LLM/管线使用mock；未覆盖本报告私聊Dashboard IO缺口 |
| Dashboard `npm test -- --reporter=dot` | 6 files / 60 passed | 现有reducer/store/layout合同；边测试接受一定程度的端点推断 |
| Dashboard `npm run typecheck` | 通过 | TypeScript/Vue类型一致性 |
| 同步静态资源抽查 | dashboard/dist、webui/dist、desktop/dashboard-dist的FlowPage JS SHA256一致 | 本地三个快照一致；不证明最终发行包及运行服务使用的全部字节 |
| 定向探针 | 复现R1/R2/R3/R4/R5/R9 | 隔离数据库/内存/纯函数，不修改业务文件，不发送QQ消息 |

测试有依赖弃用警告，无失败。临时数据库已清理。未build或sync-dist，不以构建成功替代最终资源验收。

## 建议处理顺序与完成判据

1. **先恢复观测事实可信度：R2、R3、R5。** root不得串线；没有跳转事实不得高亮；每个root可定位其真实内容spec。
2. **补当前用户可见主链：R1、R6。** 群聊/私聊/WebChat各自入口、IO、身份和终态准确；实时结束后回复内容可见。
3. **补覆盖与追踪能力：R4、R7、R8、R9。** 完整目录可展开，未知/截断诚实显示；后台关系/对象可追踪；历史分页和加载完整独立报告。
4. **最后做真实入口与发行实物验收。** 覆盖私聊/群聊/WebChat、命令/插件/过滤、DIRECT/SILENT/取消/超时、并行/重试、部分/未知投递、后台派生和原生后端；运行完整性与数据集样本覆盖分别报告。

本报告只给复核结论和修复建议，未实施上述修复，也未对最终发布版本宣称完整。
