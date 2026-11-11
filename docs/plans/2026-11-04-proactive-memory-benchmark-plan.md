# Stella 主动参与与记忆系统 Benchmark 全面计划

- 日期：2026-11-04（Asia/Shanghai）。任务：`AOEDE-MNEME-BENCH-PLAN`。
- 状态：B00–B02 已完成各自离线工作包；B03–B08 尚未完成。整体 benchmark 与产品行为验收仍 **NOT READY**，执行记录见 §16。
- 源码锚点：`codex/aoede-mneme-proactive`，`cbcd6f9d3b725f73aee02a4e4c4ca7f5280d52bd`。后续执行必须重新冻结目标提交与工作区差异。
- 需求来源：[公开数据集 Benchmark 分享对话](https://chatgpt.com/share/6aeac3ac-df44-83e9-a790-932bc403ed6f)。已从公开 HTML 的 streamed JSON 读取正文；其中的建议经下列一手资料和当前源码复核后采用。
- 本轮 scope：本文及任务状态三文件；不运行模型、不发送消息、不读写生产聊天/数据库/配置、不启动或重启服务。
- 完成条件：数据选择有来源与边界；指标有分母；决策、时机、写入、检索、自然使用、求证闭环各有协议；工作包有依赖/交付/检查点；成本、统计、中文标注与真实平台门禁可执行。

## 1. 核心决策

建立三个独立版本的成绩面板：**Aoede 主动参与、Mneme 记忆、Aoede × Mneme 联合行为**。复用现有评测设施，保留逐事件证据；不计算掩盖安全退化的单一加权总分。

优先回答六个产品问题：

1. 没有记忆、未被点名时，Stella 能否发现有价值的参与机会？
2. 有机会时能否等待适当窗口；话题已结束时能否放弃？
3. 原始对话中的可靠信息能否经过采集、提取、验收、晋升和检索，支持正确回答？
4. 记忆是否改善当前交流，而非仅增加发言次数、无关个性化或虚构回忆？
5. 求证遭拒、含糊或无人回应后，是否真正终止，且旧证据不能使候选复活？
6. 在频率、并发、重启、故障与跨群场景下，上述效果和约束能否同时成立？

**推荐顺序**：B00 协议/来源 → B01 数据与隔离 → B02 无记忆决策 → B03 时机/机制 → B04 记忆全链路 → B05 记忆自然使用 → B06 中文联合盲测 → B07 完整离线验收 → B08 受控真实平台验收。每包独立提交；先保留原样基线，再提出产品改动。

计划撰写轮次只完成规划。随后执行已按单一工作包推进：截至 2026-11-04，B00–B02 完成；B03–B08 尚未完成。benchmark 的整体效果、发布成品、干净 Windows VM 与安装回滚仍走各自门禁，未通过前保持 NOT READY。

## 2. 当前能力与必须补齐的缺口

| 已核对入口 | 当前事实 | 本计划的用途与缺口 |
| --- | --- | --- |
| `aoede/participation/__init__.py:ParticipationManager` | 上下文观测与参与评分；有可注入 clock/embedding | 测原始参与意愿，必须与最终发送结果分开 |
| `aoede/opportunity.py:OpportunityManager` | 3s debounce、15s TTL、单在途、取消、生成前复核；进程内单调时钟 | 用生产类逐事件驱动，测 WAIT/DROP、过期与 stale；不能只测 observe |
| `aoede/budget.py:ProactiveBudgetStore` | R∈[0,6]/h、容量1、初始0、持久 UTC 补充；ACK/失败/UNKNOWN 不同结算 | 冷启动与稳定运行分别测；不是必须达到 R 次/h 的发送目标 |
| `mneme/verification.py:MnemeVerificationStore` | attempts、终态、tombstone、CAS 与恢复；与求证服务/整合/晋升连接 | 自建确定性生命周期轨迹；不能由自然语言 judge 判定事务正确性 |
| `core/evaluation/runner.py` | 四模式：trace_playback / decision_recompute / isolated_pipeline / model_validation；有子进程、VirtualClock、FakeSender、预算与 partial 报告 | 复用隔离骨架。当前主路径是 observe→简化生成→FakeSender，并未完整执行现行机会/预算/求证/生产回复装配；旧模式名不能直接当作完整 E2E 证明 |
| `memory_eval/` | LoCoMo 场景、live/oracle 摄入、gold 注入、QA、judge、checkpoint、证据指标 | 复用并扩展多数据集合同；当前 schema/report 含 LoCoMo 专属字段，不能只替换输入文件名 |
| `memory_eval/isolation.py:ReplayEnv` | 直接插消息、强制整合、capture=None、评测专用批量与压缩处理 | 保留为“受控摄入”诊断；另建遵守采集门/批次/晋升合同的生产等价隔离轨道 |
| `memory_eval/metrics.py` | 有 Any/All@K、MRR；现有聚合以 `gold-{dia_id}` 匹配注入记忆 | live 晋升记忆需 source→candidate→memory→pack lineage，不能拿 gold-ID 前缀给真实写侧算召回 |
| `memory_eval/report.py`、runner checkpoint | 有模型、schema、排序环境等元数据；数据名/revision 有 LoCoMo 固定值，续跑主要按场景/题号 | 多数据集 manifest 与严格 fingerprint 校验是前置工作；旧缓存不得跨模型/参数复用 |

历史参照使用 [LoCoMo 报告](../reports/2026-10-31-locomo-memory-benchmark.md)、[指标纠正与消融](../reports/2026-11-01-memory-benchmark-corrections-and-next-experiments.md)、[写侧合同生产化](../reports/2026-11-03-contract-expansion-production.md)。其中 gold 注入、改排序、T3、充分性守护和真实写侧是不同配置；不把旧最佳格当成本提交的产品成绩。写侧 202 条合同标注不能等同于真实提取模型的端到端召回；accepted 不能等同于 promoted。

本轮不重新确认旧报告中的端点或服务在线状态。`STELLA_HOME` 环境变量当前未设置；实施前先按 [数据边界](../agent/boundaries.md) 解析数据根，再在新子进程导入 config 之前设置隔离 home。不得使用生产库作为默认 fixture。

## 3. 数据集登记与分享资料的修正

以下为 2026-11-04 一手页面/文件核查结果，仍需 B00 固定 revision、文件哈希和实际下载计数。许可与可下载性属于各版本的事实，不由论文存在推断数据已可用。

| 数据与优先级 | 已核对任务/规模 | Stella 用法与限制 | 一手来源 |
| --- | --- | --- | --- |
| When2Speak，P0 | 216,800 个决策上下文；token 与 dialogue 两配置共享上下文；各自 train 173,325 / validation 21,788 / test 21,687；CC BY 4.0 | token 主测 SPEAK/SILENT；dialogue 测表达。433,600 是两配置相加，不能当独立样本。测试 SPEAK 约12.9%；合成群聊不等于 QQ 实测 | [官方数据卡](https://huggingface.co/datasets/duke-trust-lab/When2Speak) |
| PITCH，P0 | 35 个 conversation_id、384 个知识候选消息、1,091 人次时机标注；含 best_turn、window_start/end、do_not_surface；README声明MIT | 固定待插入消息的轮次窗口评测；不是1,091独立对话，也不是毫秒窗口。所有参与者窗口存在交集的子集为296/384，分母单列；B00固定许可文件与版本 | [项目](https://social.cs.washington.edu/PITCH-website/)、[数据文件](https://raw.githubusercontent.com/Social-Futures-Lab/pitch/master/data/pitch-benchmark-data.json)、[说明](https://github.com/Social-Futures-Lab/pitch/blob/master/data/README.md) |
| Social AI Ambient Bench，P0 | test 单一 split；1,212 场景、16,222 逐轮标签、429 RESPOND；约97.36% SILENT；Apache 2.0 | 作为工具助手/防打断专项。官方 Alfi 倾向普通闲聊 SILENT，不直接充当 Stella 社交人格的最终 gold；始终沉默的场景通过率也可能很高 | [数据与官方 prompt](https://huggingface.co/datasets/text-ai/social-ai-ambient-bench/blob/main/README.md) |
| ChMapData，P1 | 多配置任务：overall_dialouge_view test122；callback train1464；dialogue_data train3989/test400；topic_rank train1464/test149；卡片标 Apache2.0 | 中文记忆引题/回调/排序；不能将卡片5853行合为统一测试集。论文100例评估与发布 test 的关系须核对 ID；历史/未来目标字段必须隔离 | [数据卡](https://huggingface.co/datasets/FrontierLab/ChMap-Data)、[配置元数据](https://huggingface.co/api/datasets/FrontierLab/ChMap-Data) |
| MemUse，P1 | 72正例+72匹配负例、316个事实子问题；CC BY-NC4.0 | 测用户线索下的记忆整合，不提供自主插话时机标签；保留用户/正负配对。卡片记录删除一例污染样本及2026-10-07 judge输入修订，不能混用论文73例或旧schema成绩 | [官方数据卡](https://huggingface.co/datasets/RuiSumida/memuse) |
| LoCoMo-Conv，P1，有条件接入 | 官方 GitHub 有转换任务与数据；Hugging Face 同名地址本次401 | 隐含提示、反事实、多记忆组合的使用测试。继承 LoCoMo 内容许可；仓库无单独 LICENSE 的授权范围待核，论文许可不能代替数据/代码许可 | [作者仓库](https://github.com/MiuLab/LoCoMo-Conv) |
| LoCoMo + PersonaMem，P0回归 | 仓库已有冻结 fetch/adapt 与旧报告：LoCoMo 10场景/1986 QA、PersonaMem 5000行 | 先复跑现有冻结版本；PersonaMem用例命中通过率不等于检索 precision。LoCoMo inherited CC BY-NC4.0，原数据不进产品包 | [LoCoMo](https://github.com/snap-research/locomo)、[现有计划](2026-10-31-memory-benchmark-public-datasets.md) |
| LongMemEval，P2 | cleaned聊天记忆数据，500题；S/M/oracle有不同历史规模；代码及cleaned卡片标MIT | 在写侧漏斗和成本可控后测更新、时间与弃答。original/cleaned分开冻结；同仓V2转向多模态web-agent轨迹，超出本轮QQ/WebChat范围，不当作聊天数据的无缝升级 | [作者仓库](https://github.com/xiaowu0162/LongMemEval) |
| LiveChat / IRC，P2辅助 | 中文主播—观众互动 / 带回复关系的多线程 IRC | 测 addressee、thread、上下文选择；人类下一句与消息回复边不是 AI 应开口的标签；只取已核版本子集 | [LiveChat](https://github.com/gaojingsheng/LiveChat)、[IRC](https://github.com/jkkummerfeld/irc-disentanglement) |
| MPDD / ishiki 多人对话 / OP-Bench，P3 | 关系/情感、多参与者续话、过度个性化研究候选 | 本轮不进主验收：先核格式、来源许可、实际下载与标签语义。OP-Bench先作为题型参考，未核实完整原始数据可下载 | [MPDD](https://github.com/ntunlplab/Dialogue-MPDD)、[多人对话](https://huggingface.co/datasets/ishiki-labs/multi-party-dialogue)、[OP-Bench论文入口](https://aclanthology.org/2026.emnlp-main.1168/) |

每个数据源建立 registry：name/config/revision/file SHA256、license/NOTICE、原始单位、split、speaker-role、时间类型、标签含义、下载状态、适配版本、排除记录及数量。限制再分发的原文保存在忽略目录，公开报告只带允许发布的 ID/计数/派生指标；不把第三方对话放入 release payload。未完成许可/下载核对的源标 BLOCKED_DATA，其他数据包可继续。

本轮已经核得的来源锚点（B00可直接校验复用，不能重新下载main后沿用旧hash）：

- When2Speak revision `092e40995896b0c278a1e32954297ef125b70112`；test token SHA256 `72304bf61f588cffee8e0620e12778b215d6ae6c1815cd3204ab3e0425258db7`、dialogue `f24ea9e164c80e1fa82b0586f09587a54be4daba1ded1b79586c5d641d8c31dd`。两份test共21687行的输入前缀与二分类标签逐行一致；train/validation仅核文档构造与数量，未逐行核验。
- PITCH公开JSON SHA256 `02684a4355eb3bf716fe157a66330d2241233504ebe630b8870f263e08a14471`；commit pin仍需B00补齐。官方还允许lookahead/full-transcript placement，这些只能另列非因果上界，不能混入逐前缀主轨。
- Social revision `5efda0b267d6bd5ecae74cbe1141a66f64495661`、test SHA256 `44d477ab5874cdc3e082d95787cb78f26e0a894e8a0056b56caca74058f66cd1`；ChMap revision `bd3a65052113ceeb1111b0ee0b44427101806376`；MemUse revision `d268288a25c4d802cf071eb70d79b6e7dcb3b6c6`。后两者每文件hash待下载冻结。

LoCoMo官方token-F1与当前Stella LLM judge是不同判分协议，B04并列保留官方可比评分与Stella的支持/弃答评分；不能将当前J-accuracy称为官方F1。PersonaMem的检索适配也不等同于原任务的选项/生成正确率。

## 4. 评测矩阵与证据层级

| 轨道 | 输入 → 被测链路 | 主要证据 | 不能据此声称 |
| --- | --- | --- | --- |
| A 无记忆参与 | 已出现的消息前缀 → Participation 意愿 | source-native SPEAK/SILENT、分层混淆矩阵 | 已遵守频率或已实际送达 |
| B 时机与上下文 | 前缀+固定候选内容 → Opportunity/取消/时机 | PITCH轮次窗口、线程/对象、WAIT→SPEAK/DROP轨迹 | 已模拟真实参与者对机器人发言的反应 |
| C Mneme组件 | gold/受控记忆 → 检索/包/回答/充分性 | Any/All@K、precision、可回答/弃答拆分 | 原始聊天已被成功记住 |
| D Mneme写侧 | 原始对话 → 提取/合同/候选/晋升/检索/QA | 源证据 lineage、漏斗、版本更新与过期 | capture被绕过的模式属于完整生产链 |
| E 联合自然参与 | 同一前缀+不同记忆条件 → 意愿/时机/生成 | 记忆净收益、过度使用、自然度、支持关系 | 仅凭更多发言就改善体验 |
| F 机制/稳态 | 虚拟事件+故障/恢复 → 实际状态事务/FakeSender | 硬约束计数、DB终态、回执/预算一致性 | Fake ACK等于QQ回包 |

报告层级标识：L0 合同/确定性夹具；L1 公开数据的隔离重算与组件测量；L2 显式真实模型+隔离库+FakeSender；L3 获准的真实 QQ/WebChat 试验。各层分别 PASS/FAIL/NOT RUN/PARTIAL/BLOCKED；不存在“L1绿所以L3绿”。

## 5. 协议：前缀、状态、标签与时钟

### 5.1 两种语义、三个动作、多个发送结果

二分类源标签只回答“这个决策点应不应该参与”。不能把 SILENT 自动改标 DROP，也不能根据未来发言伪造 WAIT 标签。源原生二分类与 Stella 连续轨迹分别评分。

- **SPEAK**：机会/时机层允许进入生成，不等于最终发送成功。
- **WAIT**：同一机会仍在有效期，等待新消息或 timer；必须有下一事件/到期处理，不能无限等待。
- **DROP**：机会终止，原因包括 stale、TTL、取消等。权限、预算或模型故障另记具体阻断原因，不能混作语义判断正确。
- 单独记录 participation_intent、opportunity_action、generation_result（含SKIP）、delivery_outcome（ACK/definite_failure/UNKNOWN/none）、记账结果。

**双视图**：语义视图在统一可参与的评测条件下测意愿，明确是诊断；产品视图保留真实 R、冷启动、冷却、睡眠、mute、预算与发送复核。R=0或初始无token的“全沉默”不能算决策能力合格，也不能把合理预算拒绝当参与分类器误判。两视图都保留未过滤样本总数与条件子集覆盖率。

### 5.2 防未来信息泄漏

actor 只能读取当前前缀、当前可访问记忆和已发生的状态事件。gold 放 scorer 单独目录/进程；future utterance、正确回答、best_turn/窗口、后续确认、未来记忆不可进入 prompt、embedding、缓存或初始库。写侧按会话结束/事件时间逐批处理；问题必须使用其查询时点以前已到达的证据。

数据按完整 conversation/session/speaker-profile分组，继承官方 split；同一上下文的 token/dialogue变体、改写、翻译和记忆消融派生样本必须同 split。开发仅用 train/validation；Social单一test不反复调参，另用自建dev调参。不能随机按消息行切分。训练污染风险与来源交叠只能登记，不能承诺已排除模型预训练污染。

PITCH任务只预先提供该任务指定的待插入知识内容，不提供未来对话或人类时机标签。分别报告官方 intersection/everyone口径、union/多数口径和do_not_surface子集；使用296窗口交集子集时仍列384全体流转与不适用原因。联合生成另开实验，避免生成质量污染固定内容的时机归因。

### 5.3 时钟与回放

生产机会等待使用单调时钟；持久预算/求证期限使用UTC墙钟。runner需统一驱动虚拟 monotonic、UTC和async timer，不仅修改observe(now=...)；测量墙钟耗时仍用真实 monotonic。推进到下一消息前，先执行在此前到期的timer；同时间事件有固定排序并记录。

PITCH原标签是轮次窗口；没有可靠间隔的数据只报告turn delay，不能捏造毫秒真值。工程时序另外用明确标为synthetic的到达间隔（密集/普通/长停顿）做敏感性测试；TTL/debounce与600s冷却读实际配置/常量并入fingerprint。

公开历史回放采用 **open-loop**：机器人发言不能改写未来人类话语；记录“反事实状态记账”，不声称已模拟用户反馈。分支对话/用户模拟器仅作补充且与真人分开；正式闭环效果依赖B08。历史BOT_SELF与本轮模拟输出不得重复计入发言或冷却。

### 5.4 两种记忆摄入与上下文预算

I-controlled 保留现有 ReplayEnv 的force/capture绕过等条件，用来分解瓶颈；I-production 在隔离home/模型端口/FakeSender中按真实admission、capture、batch、EXTRACT、合同、晋升和回复装配运行。两模式报告所有覆盖/绕过项，不用I-controlled关闭I-production门禁。

长历史可在多轮离线摄入中持续积累；每次模型调用遵守相应角色真实token预算。8192是项目Compact合同，不能作为所有角色/数据集的统一窗口。记录 tokenizer版本、源历史总token、当前输入、压缩、裁剪/丢弃证据比例、输出上限和溢出错误。官方full-context对照用明确支持该长度的模型；受限窗口结果标为Stella-adapted，不能冒称官方可比成绩。

## 6. 数据与报告合同（B00/B01实施，当前为设计）

建议新增薄包 `proactive_eval/` 管理公开标签/适配/指标/CLI；沿用 `core/evaluation/` 的隔离进程、VirtualClock、FakeSender与报告思路，沿用 `memory_eval/` 的写侧/QA组件。不要复制Aoede/Mneme决策或晋升规则。跨子系统集成在评测宿主组合端口，保持Aoede/Mneme互不导入。

在实现前冻结新schema（建议 `stella-proactive-scenario/1`、`stella-proactive-report/1`、`stella-memory-report/2`；名称尚未实现）：

| 区域 | 必要字段 |
| --- | --- |
| source manifest | dataset/config/revision/file hashes/license/split/adapter_version、原始与成功/失败适配数、单位、去重与排除规则 |
| actor input | scenario_id/episode_id/event_id、sequence、可信Bot/connection/scene、speaker/subject、source_kind、文本、原生reply/mention、到达时间及real/synthetic标记、可访问的既有记忆 |
| scorer-only gold | label_origin/source_label/Stella-adjudication、允许动作、turn windows、gold支持证据集合、应弃答/禁用记忆、标注分歧/置信度 |
| trace | intent/score/reasons、opportunity id/revision/created/expiry/action、budget reserve/settle、model call与SKIP、delivery结果、attempt/generation/终态、state digest |
| memory lineage | source event/span/digest→claim/candidate/generation→promoted id→retrieval rank→packed引用→answer支持片段；多来源记忆允许many-to-many |
| reproducibility | git HEAD+dirty digest、schema/API/native实际模块/后端、所有有效设置和默认值、prompt/表/人格文件hash、数据/标签/adapter/scorer版本、模型revision/量化/seed/温度、tokenizer、端点角色别名、依赖/OS/硬件 |
| execution | run_id/fingerprint、总样本/完成/失败/跳过/不适用、每项分母、调用数/token/时间/资源、partial原因、cache与fallback、产物hash |

fingerprint覆盖有效参数，不只覆盖显式环境override。`--resume`必须在dataset/split/model/prompts/config/schema等指纹一致时续跑；不匹配拒绝或新建run。每条结果以run fingerprint+scenario+event/qid+condition唯一标识，原子checkpoint；崩溃恢复不重复摄入、发送结算或漏记调用。旧report/1按旧协议只读，不改写历史hash。

公开数据的原文不必脱敏成不能评测的内容，但用户真实聊天/配置不得进提交。真实平台证据经同意后本地最小留存；公开证据只给匿名ID、reason和聚合，prompt文件可能含原文时列为restricted artifact。候选记忆/源对话都是待处理数据，不能当系统指令；另设带指令注入的fixture。

## 7. 指标字典：明确分母，禁止空集PASS

### 7.1 Aoede

| 指标 | 定义/报告方式 |
| --- | --- |
| SPEAK precision / recall / Macro-F1 | TP/(TP+FP)、TP/(TP+FN)、两类F1平均；完整混淆矩阵、类别支持数。无预测SPEAK的precision标N/A，约定F1=0并解释 |
| False Interruption Rate | FP/(gold SILENT数)，是负类误触率；另报FP/(所有实际发言数)=1-precision，不混名 |
| Missed Intervention Rate | FN/(gold SPEAK数)；语义意愿与产品有效窗口分别计算 |
| Window hit / early / late / missed | eligible候选中，在允许turn窗口首次有效介入/过早/过晚/从未介入的比例；按源协议处理do_not_surface，禁止靠永远不发言提高命中率 |
| WAIT质量 | 可延后机会的WAIT→窗口内SPEAK率、WAIT→正确DROP率、TTL越界/反复创建次数；只在有轨迹gold/自建标签时计算 |
| 对象/线程 | addressee accuracy、reply-edge/thread指标；缺相应gold标N/A，不用相关性分数冒充正确对象 |
| 事件频率 | autonomous机会数、发言消息数/有效群小时、每100人类turn发言数；按CONTRIBUTE/VERIFY_ASK/announce拆分，物理分片另计 |
| 发送健康 | proposed→eligible→generated→SKIP→send_attempt→ACK/failed/UNKNOWN漏斗；失败与UNKNOWN作为产品未确认送达，不能从主分母静默删除 |

始终沉默、始终发言、最后一条显式提问触发等基线都输出；Accuracy仅附录。When2Speak/Social/PITCH/中文各自报告，不按条数把大合成数据集压过真人小样本。

### 7.2 Mneme

| 层 | 指标与约束 |
| --- | --- |
| 写侧 | MUST信息召回、MUST_NOT误收/误晋升、有效候选precision、accepted→promoted率、source支持完整性、到可检索延迟；分母来自独立可存信息标注，不来自模型自己提出的候选 |
| 归属/时效 | subject/owner/audience正确率、更新成功率、旧值残留/冲突优先级、计划到期、显式撤回后可检索/可输出残留；“过期抑制”与物理删除分开 |
| 检索 | source-ID对齐的Any/All-Evidence Recall@1/3/5/10、MRR、Precision@K、证据入包率、干扰带出数；无完整证据gold时指标N/A并报告coverage |
| 回答 | answerable correctness、unanswerable正确弃答、unsupported answer rate、answer coverage与选择性风险；五类LoCoMo及各数据集能力类别分开 |
| 自然使用 | 对必要记忆的正确使用/漏用、不需记忆时的无关引用、错误主体/旧值引用、重复个性化；出处支持与对话相关性分别打分 |
| 性能 | capture→extract→promote→retrieve→pack→answer各段P50/P95、DB增长、峰值RSS/显存、模型调用/token/重试/fallback；未测字段null |

不得将shared词片段/n-gram重叠当source支持；live可检索记忆与gold事件之间需要人工/可靠对齐器核验的lineage。无法对齐的样本列ALIGNMENT_UNRESOLVED，并同时给可评分覆盖率与最坏界，不默认为召回失败或满分。MRR只表首条证据，多跳必须看All@K。

### 7.3 联合收益与“记忆是否有害”

同一上下文、同一speaker、同一预算状态比较记忆条件；分别测 **固定参与决策后的内容收益** 和 **允许记忆影响决策的系统收益**，不以发言数增加充当效果改善。

- useful intervention rate：全部可参与机会中，窗口/对象/支持/自然度均合格的介入数；同时给条件于已发言的质量和未发言比例。
- memory overuse rate：标注“不需记忆”的机会中，出现无关/过度记忆引用的机会数/全部这类机会；另报只在已生成回复中的条件比例。
- memory benefit：必要记忆层的正确有用介入率条件差值；no-memory层检查误打断与自然度是否退化。
- repeat verification：相同scope+subject+claim+evidence generation在终态后再次ASK的次数；合法新证据generation单列。

## 8. 基线、消融与实验规模

### 8.1 统一冻结基线

主基线B-current为本轮源锚点的有效配置，不能只写“默认”；新候选B-candidate绑定具体改动提交。旧MBENCH最佳格仅为研究对照，先在新协议复现再比较。保留 source-native official baseline（若可运行）及成本，不能直接引用论文异模型数字作显著性证据。

主动决策对照：always-silent、always-speak、显式邀请/简单规则、当前Participation、当前完整Aoede、候选改动。旧版本主动模块只有在历史提交可隔离运行时才加入，不为对照重新实现旧规则。

记忆条件：M0无记忆；M1正确且相关；M2可靠但无关；M3过期/冲突旧值；M4错误主体/越权；M5明确标为不确定的候选；M6真实写侧产物。M4在检索/包边界应硬拒绝；fixture注入越权内容到生成器仅属故障诊断，不能作为正常授权流程。oracle/gold作为上界诊断，不进入产品端到端排名。

### 8.2 控制组合成本

先做串行漏斗，避免所有数据×后端×频率×prompt的笛卡尔积：

1. A轨完整When2Speak token test与Social原test，主要走本地决策；开发只用独立dev。dialogue生成先200个分层test诊断，不把同上下文计两次独立样本。
2. B轨PITCH全部384候选按原conversation分组回放；固定内容。自建工程间隔只在dev/机制集扫描debounce/TTL，不能用公开test挑最优参数。
3. C/D轨先复跑冻结LoCoMo/PersonaMem，再取LoCoMo两完整对话做受控与生产等价双轨诊断；通过后扩大10对话。LongMemEval-cleaned先每能力10题smoke，随后500题规模以下载版本与成本确认；不接V2的web-agent轨道。
4. E轨MemUse144全量；ChMap各官方test按任务单独运行；LoCoMo-Conv待许可与格式核对后先100题再全量。M0/M1/M2/M6为核心配对，M3–M5主要走压力子集。
5. B06中文独立集：240段完整情境，12类×20段；120段dev、120段holdout，预计约2400决策点，实际数量与正负比例以冻结manifest为准。按源会话/人物组切分；公开语料改写与合成分开登记，holdout的所有派生条件不进入dev。
6. 机制集至少120条完整状态轨迹（不是120条聊天句），覆盖§10；低成本确定性重复与故障矩阵，不重复制造“通过率”样本。

rule/embedding/fts/hybrid四模式先跑现有组件回归；Python/native只比较二者明确支持的同一模式，报告实际backend与fallback。端点失败不能把rule结果写成embedding成功。T0/T3、guard off/shadow/enforce做单变量配对；shadow不能强制改变回答，off保留兼容对照。完整联合模型评测只跑通过组件门禁的少量配置。

频率R=0/0.5/1/3/6分别测：冷启动、带固定已用历史的稳定态、24h虚拟轨迹、多人多群突发。保持同一到达流和记忆；R是预算上限而非利用率目标，不要求提升R后发言严格单调。超额硬门禁按初始token+实际补充−有效消耗核对，不用模糊“每小时大约R次”代替桶语义。

## 9. 中文标注、Judge与统计

中文12类：可自然接话的普通闲聊、信息帮助、明确邀请/被动回复对照、多话题交错、对象歧义、消息密集未说完、话题转移/过时、必要记忆、无关记忆、旧值/主体冲突、求证含糊/未回复、静音/睡眠/频率边界。跨群/多Bot身份与prompt注入放机制集中额外覆盖。

标注表包含“是否欢迎Stella参与”“允许轮次窗口”“对谁/哪一线程”“是否需要记忆”“哪些证据可用”“回复有用性/自然度/冒犯或纠缠”。自然度/有用性采用1–5分锚定量表；不得让标注员只看到孤立最后一句。SPEAK/SILENT存在分歧时保留分布与ambiguous，不强造唯一真值。

先用30段dev做标注校准；两名独立中文标注员覆盖全240段，第三人裁决分歧。冻结指南后再打开holdout；若κ/α<0.60，先修指南并重标dev，holdout停止评分，不能删掉难例提高一致性。报告一致性、分歧率与裁决数，0.60只是本项目预登记质量门槛。

生成评估采用匿名随机顺序的配对盲评；隐藏系统版本/记忆条件，允许平局。先对120条分层输出做双人复核（含全类失败、沉默与记忆负例），再扩展；公开源原标签与Stella人格重标结果并列，不覆盖原gold。额外人格重标集只作新派生benchmark，不能改称官方成绩。

LLM judge固定prompt/hash、模型revision、温度、输出schema；answer与judge优先异模型。相同模型仅作带自评偏差标记的诊断；至少120条人工复核中报告judging agreement与误放行。解析失败单列并纳入全流程可用性分母，不按correct处理。小MemUse/单对话上的置信区间宽，不能仅凭均值宣告改善。

统计单位按conversation/session/人物组聚类：配对cluster bootstrap 2000次、固定seed、95%CI；不能把PITCH1091人次或同上下文的变体当独立样本。各数据集、中文/英文、角色与正负类别分层。预登记主终点，次要指标标探索；多候选在dev选择一个后holdout只验一次。零故障报告样本数与区间，不能声称真实世界风险为零。

## 10. 确定性机制与故障矩阵

扩展既有 `tests/aoede/test_opportunity_timing.py`、`test_frequency_budget.py`、`test_verification_lifecycle.py`、`test_context_only_participation.py`；每条轨迹驱动实际生产对象，核对DB状态、发送计数和预算，不重写oracle里的业务判断。

| 家族 | 最少覆盖内容 | 硬失败条件 |
| --- | --- | --- |
| 机会 | 无记忆也可参与；单在途合并；debounce持续消息；TTL不顺延；换题/新直接请求取消；生成期间revision变化 | 重复在途、过期/stale仍发、取消后再发、timer无限延后 |
| 求证 | ACK后起期限、明确确认/否定/含糊/无回复、第三方/跨会话回复、无显式绑定、生成失败、发送失败/UNKNOWN | 错人确认、未确认自动晋升、终态旧generation再ASK、tombstone被旧证据绕过 |
| 恢复 | reserve前/后、发送后ACK前、ACK后落库前、终态CAS期间崩溃重启；候选删除/重建 | 重启免费再问、重复消耗/退款、未知投递自动重发、旧证据复活 |
| 预算 | R0及小数/上限；空启动；共享插话/ASK/播报；被动/预约独立；并发reserve；UTC回退/跃迁 | R0仍自发发言、双花、超容量、失败错误结算、跨Bot/会话串桶 |
| 记忆 | 拒绝、合法新证据generation、更新/矛盾/撤回/PLAN TTL、共享授权变化、个人/群/连接隔离 | 越权检索/入包/输出、主体错绑、禁存内容晋升、拒绝信息以同旧来源复活 |
| 故障 | store锁/不可用、模型超时/空输出/非法输出/预算耗尽、embedding故障、部分ACK、发送UNKNOWN | 以静默fallback伪造成功、真实send逃逸、丢失partial、失败样本被滤掉 |
| 评测器 | 两遍fixture重放、timer相同时间排序、gold隔离、fingerprint不符续跑、缺字段/坏hash/0样本 | 非确定性未解释、标签进actor、越目录、旧缓存混跑、空集PASS |

“no reply”与“换题”不等价于可以将别人的答复当确认；确认仅记录确认关系，仍经过Mneme原晋升门。拒绝终态的key包含证据generation；真正独立的新证据应允许新generation，不能把一次拒绝误变为永久禁止记忆。

## 11. 验收门槛（预登记草案）

数值门槛是项目建议，尚无本轮实测依据；B00在独立dev和用户产品目标上冻结一次，holdout开始后不得为通过而移动。若样本量不足支撑结论则INCONCLUSIVE，保留NOT READY。

| Gate | 通过条件 | 适用范围 |
| --- | --- | --- |
| G0 可复现 | source/adapter/协议/指纹完整；fixture两遍逐事件一致；坏hash/续跑不符/0样本均能拒绝；完成/失败/跳过数量守恒 | 所有后续实验前置 |
| G1 硬约束 | §10适用轨迹100%完成；越权/错人确认/旧证据复活/重复终态求证/R0发送/预算双花/真实send逃逸均0 | 有限测试集安全门；不外推无限场景 |
| G2 主动语义 | 相同holdout优于always-silent/always-speak；候选相对B-current的Macro-F1配对差值95%CI下界>0；误打断差值95%CI上界≤+1pp | 公开源各自报告；Stella人格最终依据中文holdout。未改善可记完成测量，不能宣称优化成功 |
| G3 时机 | 中文可插话窗口命中率目标≥80%、提前插话率≤5%；PITCH同时保留官方口径与样本coverage；任何TTL/stale硬违规=失败 | 数值先在dev校准冻结；轮次与秒分开 |
| G4 记忆 | 现有确定性/隐私/后端parity零退化；生产等价写侧报告完整漏斗；候选answerable correctness差值95%CI下界>0，正确弃答差值95%CI下界≥−2pp | oracle或gold单独改善不能通过该生产门 |
| G5 联合体验 | 必要记忆层useful intervention改善95%CI下界>0；无记忆需求层overuse差值95%CI上界≤+1pp；人工自然度均值不劣于B-current超过0.25/5分 | 同预算/相同参与机会条件；需双人盲评及一致性达标 |
| G6 成本/运行 | 每1000决策、每有效介入及各角色成本齐全；零模型模式0生成调用；本地纯决策P95暂定≤100ms、候选不超基线20%；真实模型延迟单列 | 硬件/并发/缓存状态固定；模型慢到错过TTL仍计真实失败，不删去 |
| G7 真实平台 | B08明确scope/模型/配置/commit；可追踪实际触发→生成→物理发送ACK→匿名反馈；无硬约束违规 | 单独关闭QQ/WebChat行为门，不关闭Windows VM/安装门 |

所有主指标带n/分母/95%CI；没有证据时不填0或PASS。机制通过但效果未提升，可以结束“基线测量”任务，产品行为优化仍NOT READY。原Aoede/Mneme功能任务与本计划的门禁映射写入最终报告，不能通过新增benchmark跳过旧G2。

## 12. 工作包、所有权与提交检查点

以下文件名为**拟新增/拟扩展**，不是已存在命令的承诺。按顺序执行，每包开始重查HEAD/工作区、upstream impact和依赖；HIGH/CRITICAL先提示，UNKNOWN/零边补源码。提交前 `detect_changes(scope=all)`；回归审查compare main，partial/truncated重跑。每包包含恢复说明与独立commit。

| 包 / 依赖 / 预计工程时间 | 交付与拟负责路径 | 验收 / 回滚 |
| --- | --- | --- |
| B00 / 无 / 1–2日 | 数据registry、协议/主终点/成本预算冻结；报告schema；`docs/plans/`及拟建`proactive_eval`合同。固定B-current，冻结现有LoCoMo/PersonaMem回归 | 核对下载/许可/配置单位；手算混淆矩阵与窗口例；记录冻结表。回滚仅移除新评测文件 |
| B01 / B00 / 2–3日 | `proactive_eval/` adapters/CLI/scorer；数据入忽略目录；扩展`core/evaluation/`事件与timer支持；`memory_eval/scenarios.py`/report/runner多数据集与resume合同 | 测坏数据、gold隔离、同上下文派生split、异指纹续跑、crash恢复、0样本；有兼容适配器读取旧报告，不改历史证据 |
| B02 / B01 / 1–2日 | When2Speak token、Social适配与无记忆原样基线；公开/native与中文人格标签分栏 | 完整holdout计数；always-silent等基线；本地决策0生成；保留错误明细。仅测量不调生产表 |
| B03 / B02 / 2–3日 | PITCH轮次窗口；统一虚拟时间驱动OpportunityManager、预算与Mneme求证；扩展`tests/aoede/`和`tests/evaluation/` | §10状态/重启/并发/UNKNOWN矩阵；PITCH交集缺失不丢样本。发现产品bug单列最小修复包，先保存失败基线 |
| B04 / B01,B03 / 3–5日 | `memory_eval/`双摄入轨、lineage、真实batch/capture、LoCoMo/PersonaMem复跑、写侧版本更新/撤回/过期；必要时扩展`tests/test_memory_eval*.py` | source-ID支持人工审计；两完整会话smoke→10场景全量；模式/实际backend可追溯；LongMemEval是有成本预算的P2扩展 |
| B05 / B03,B04 / 2–3日 | MemUse/ChMap，许可明确后LoCoMo-Conv；`proactive_eval`联合条件与内容评分；T3/guard单变量配对 | M0/M1/M2/M6核心与M3–M5压力条件；正确支持/无关引用/固定决策与系统收益拆开；不得无批准重写生产prompt |
| B06 / B02–B05 / 2–4工程日+标注排期 | 中文240段与指南、双标/裁决、120输出judge校准、holdout封存与盲测 | 一致性、persona标签来源、分组隔离、全体与ambiguous成绩；标注不足时BLOCKED_ANNOTATION，其他轨可继续 |
| B07 / B06 / 1–2日+模型时间 | 冻结候选一次holdout验收、成本/cluster CI、日期报告/manifest/runbook、CI轻量分层 | G0–G6逐项记录；完整tests/lint/docs/flow等对应门禁；FAIL/partial不能用平均分掩盖；保存原baseline与失败样本 |
| B08 / B07且G1通过 / 至少7日观察 | 指定单群/测试空间的shadow→隔离模型→低频真实试验；QQ/WebChat分别登记 | G7；首阶段R≤1并由用户授权实际目标/窗口；有硬违规立即关主动链、保留证据并恢复基线配置；不自动扩大范围 |

预计B00–B07合计14–24工程日（单人顺序估计，不含标注等待、数据解锁、长模型运行或产品缺陷修复）；B08至少一个7日观察周期。此为排期模型，smoke后更新实际吞吐，不能作为交付日期承诺。现有生产代码只在确认评测暴露具体问题后另包修改；不得借评测调整默认频率、隐私/晋升门或放宽时机约束。

## 13. 调用预算、资源与CI

本地决策批量先行；P0全量决策不逐点调用生成judge。只在明确的生成/记忆实验上计模型预算。每阶段开始导出预计calls/tokens/wall-time，再提交执行证据；不得从历史LM Studio/Strata地址推断当前可用模型，更不得自动装卸用户模型或改服务启动链。

默认试跑限额建议：单实验200次模型调用、30分钟墙钟，最大并发1；整合调用单列。联合诊断120机会×4核心条件，每次最多生成1+judge1=960调用（未含摄入/guard/重试）；若每次输入1500+输出250tokens，则约168万tokens，只是预算示例。smoke实测后按角色计算：Σ(calls_role×mean_input/output_role)，价格缺失时只报告tokens/硬件时间，不虚构金额。数据集全量/LongMemEval另设独立上限，达到上限保存PARTIAL，不自动透支。

缓存只复用输入/模型/role/prompt完全一致的embedding和生成结果；cold/hot分别报告。随机性实验3个seed仅在开发子集做；温度0也不假设真实端点完全确定。原始时序不因模型实测耗时偷偷加速：报告在虚拟时间与真实墙钟两种发送窗口结果。

CI分层：PR跑纯fixture、协议/泄漏/安全回归、已许可小子集和现有memory benchmark；定时/手动跑公开数据完整本地决策；显式手动且有端点/预算才跑真实模型与长历史。没有模型的CI显示NOT RUN，而非“通过效果验收”。不得在普通CI依赖私人聊天或用户生产端点。后端/native/发布校验延续现有CI，不由benchmark缓存代替。

## 14. 真实平台试验与停止条件

开始B08前固定唯一Bot/connection/scene、参与者同意、时间窗、模型与persona/prompt、baseline配置、R和回滚动作。仅在实际授权scope内发送；公开数据/fixture先行不依赖这个授权。现有进程已运行或OneBot健康不等于可向任意群发送。

shadow记录候选与决策但0发送；随后显式真实模型+FakeSender；再进入单群低频。每步保留“机会意愿/预算拒绝/模型SKIP/投递结果”漏斗。观察至少7日且有足够有效机会后，再判断样本量；样本不足延长观察或INCONCLUSIVE，不能用天数替代统计功效。不要在同群短时来回切A/B污染预算与记忆；采用完整日/会话区组、冻结切换规则、保留carryover/washout记录。

实际反馈含有用/自然/打断/记错/不想被记住，沉默不自动标满意或确认。严重误记/越权/重复纠缠/R0异常/错投立即停止主动路径；没有硬违规但主体验或成本越界，则回到shadow并审查，不能靠提高R补样本。最终QQ/WebChat发送验收、行为效果、Release payload、Windows VM/安装回滚分别签收。

## 15. 实施入口与计划撰写轮次证据

可恢复入口：先读本文B00，再读 [Aoede/Mneme改造计划](2026-11-03-gitnexus-plan-aoede-mneme-proactive-redesign.md)、[验证门禁](../agent/verification.md)、[模型探针](../development/probes.md)。实施前执行 `git status --short`、确认有效home/显式隔离home、检查数据manifest与选定模型身份；此后才运行需模型的命令。

现有入口（均需已适配数据与独立临时workdir；此处仅登记，不表示本轮运行过）：

```powershell
python scripts/run_flow_evaluation.py --help
python -m memory_eval --help
python -m pytest tests/aoede tests/evaluation tests/test_memory_eval.py tests/test_memory_eval_consistency.py -q
python scripts/check_docs.py
git diff --check
node .gitnexus/run.cjs detect-changes --scope all --repo Stella_project
node .gitnexus/run.cjs detect-changes --scope compare --base-ref main --repo Stella_project
```

拟建 `python -m proactive_eval` 尚不存在；先完成B01，不把设计参数当现成命令。记忆复跑显式 `--stage ingest` / `--stage qa` 与场景范围，聚合时不要误用 `--stage all` 启动新摄入。实际Python变更须按仓库规则跑全量tests/Ruff；涉及消息流程需flow检查，native/schema变更则另加Rust/迁移/parity门禁。

本轮证据与局限：

- 启动工作区仅有既有未跟踪 `.zcode/plans/plan-session_336c42cadee7b4396161f4d29c54c8fa.md`、`debug.log`、`extensions/ligamina_bridge/`、`scripts/start_managed_stella.ps1`；不纳入本轮提交。
- GitNexus CLI1.6.12 status：源HEAD索引up-to-date、content current、runnerIdentity current、2203 covered files，incompleteReasons为空。`.gitnexus/meta.json`另有旧Linux元数据；以本次CLI实际绑定索引为准，未据旧文件重建。
- query benchmark/opportunity与context先行；ParticipationManager / OpportunityManager / MnemeVerificationStore / ProactiveBudgetStore均定位到正式包；命名run/run_experiment查询缺失、流程列表为空及部分定义异常，已读实际runner/入口/测试补证。索引current不保证动态调用或文件内符号完整。
- 编辑前upstream impact：feature_list LOW，2 direct（AGENTS/workflow）、19 impacted；progress MEDIUM，5 direct（AGENTS/workflow、双语跨平台计划、文档迁移报告）、29 impacted；handoff LOW，2 direct、19 impacted；均0图流程，这只是文档引用图。新计划未入图，UNKNOWN，已检索新文件名/任务ID无既有引用，并人工核对链接。
- 拟扩展runner文件impact：core/evaluation/runner.py LOW，2 direct（包入口/flow CLI）；memory_eval/runner.py LOW，1 direct（memory_eval CLI）；均0图流程，已用源码核对实际入口和隔离实现。本轮未编辑这些文件；后续符号编辑仍需重新impact，不能用此文件级结果豁免。
- 文档基线：`python scripts/check_docs.py`为127 files / 1358 links / 577 anchors / 0 errors；`git diff --check`通过。本轮最终文档与图检查结果见progress/feature evidence。
- 本轮未跑业务测试、真实模型、数据集全量、QQ/WebChat、发布或VM；研究核查与文档通过只支持本计划可执行性。

尚待B00决定的事项：完整逐文件版本/许可清单；ChMap论文与发布test对应；LoCoMo-Conv衍生许可；当前模型/硬件与token预算；中文标注人员/排期。它们影响对应实验准入，不阻止先实现无需模型/私人数据的协议、夹具和本地决策基线。

## 16. 执行记录

- **B00：完成。** 协议、来源、指标分母、数据和门禁冻结；见 [B00 报告](../reports/2026-11-04-proactive-memory-benchmark-b00.md)。
- **B01：完成。** 通用数据合同、隔离 actor/scorer runner、指纹和断点恢复已提交并单独记录；见 [B01 报告](../reports/2026-11-04-proactive-memory-benchmark-b01.md)。
- **B02：离线公开基线完成。** When2Speak 21,687/21,687 与 Social AI Ambient 16,222/16,222 三种无记忆策略均完整计分；模型调用/生成/记忆输入为 0。公开数据源标签不等于 Stella 中文 persona 标注；不得据此宣称产品有效或调生产规则。提交 `e9738e9` 已推送；PR #130 中英文评论已发布。完整指标、数据哈希、误判边界与运行限制见 [B02 报告](../reports/2026-11-04-proactive-memory-benchmark-b02.md)。
- **B03：离线时机/机制评测完成。** 固定 PITCH 384 个候选全部保留，329 个官方窗口交集、55 个冲突；segment-start 命中 4/329，always-silent 漏掉 329，非因果 oracle 单列。合成时序与隔离状态矩阵通过；44 项定向回归通过。生产符号未改，模型/平台/产品效果仍 NOT READY。提交 `152e7e6` 已推送；PR #130 双语评论 ID `6630358374`。详见 [B03 报告](../reports/2026-11-04-proactive-memory-benchmark-b03.md)。
- **B04–B07：未完成。** 记忆全链路、联合条件、中文双标盲测及完整离线验收仍按依赖推进；B06 标注资源尚未安排。
- **B08：未开始且未准入。** 真实平台目标、参与者同意、模型/配置、观察窗口及回滚动作需要明确授权；不得从本机服务健康或公开数据推断可向群发送。
- 当前总状态保持 **NOT READY**。每包独立英文提交；每步完成评测后在对应 PR 评论写中英文结论。
