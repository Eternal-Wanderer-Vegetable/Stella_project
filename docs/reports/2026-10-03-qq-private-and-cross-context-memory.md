# QQ 私聊与跨场景个人记忆排查及修复方案

日期：2026-10-03（Asia/Shanghai）。状态：排查完成，以下修复尚未实施。

## 结论

1. **Stella 本体主聊天不支持 QQ 私聊，已复现。** 普通私聊不能进入主聊天 matcher，因此没有本体对话、短期记忆及本体长期记忆整合。AstrBot 兼容插件已存在私聊分发和发送能力，不能把现状表述成“整个程序完全没有任何私聊能力”。
2. **同一 QQ 号跨不同共享空间引用个人记忆不支持，已复现。** 同一共享空间内的多个群已能共享长期记忆和画像；空间不同则检索 SQL 在排序前即排除另一空间的记录。QQ 群与私聊之间还受到问题 1 的入口阻断。
3. 当前工作区默认解析出的本地数据目录为 `StellaData`。两个启用群已经同属 `space_1`，另外两个启用群分别属于 `space_2`、`space_3`。因此不能把“所有跨群记忆均失效”作为诊断结论。

本轮没有修改业务代码、配置和生产数据库，没有向 QQ 发送消息，没有启动或停止用户机器人。新增本报告；GitNexus 索引已刷新。

## 调查基线及验证边界

- 仓库：`E:\stella\stella_project`；分支：`feat/cometa-agent-task-layer`；HEAD：`0600226b8879b01adf507308d7a71f3338d36b76`。
- 按要求使用 Docker 容器 `stella-gitnexus`，其 `/repo` 绑定当前工作区；GitNexus CLI 1.6.11。
- 先执行 `list`，确认容器里存在多个索引，后续图查询均显式绑定 `--repo Stella_project`。
- 初始索引为 `4b089b5`，落后 27 个提交。刷新后 indexed commit 与 HEAD 同为 `0600226`，status 为 up-to-date。最终刷新保留原索引的 `--pdg` 模式。
- 执行概念 query、符号 context、upstream impact，以及 `_build_user_context_v2 → retrieve_memories → _fetch_candidates` 的 trace，再以当前源码确认。
- 索引报告部分执行流受入口/深度/分支预算限制，Python 动态注册也可能缺失调用边。图中没有流程或调用者不代表代码没有运行；本报告没有用这些零值证明安全。
- 用真实 OneBot V11 事件模型及 NoneBot matcher 做本机隔离探针；记忆检索使用临时 SQLite 数据库。未验证真实 QQ 客户端、NapCat 私聊转发、实际模型生成或运行中机器人的环境覆盖。
- 本地配置和数据库统计是本轮默认配置解析的快照；数据库连接使用 `mode=ro`，未输出用户消息或记忆正文。

## 问题 1：主聊天入口只有群消息

源码证据（行号按当前源文件核对）：

| 位置 | 事实及影响 |
|---|---|
| `stella_project/plugins/bot_main/ai_gateway.py:773` | `is_chat_trigger(event: GroupMessageEvent)`，检查群白名单和 `is_tome()`；私聊事件不满足依赖类型。 |
| 同文件 `:842`、`:846` | 主 matcher 注册上述 rule；`handle_chat` 也只接收 `GroupMessageEvent`。 |
| 同文件 `:640` | 短期记忆监听函数 `record_group_chat` 同样只接收群消息。 |
| 同文件 `:346`、`:369` | 观测根的 pre/postprocessor 对非群消息直接返回。 |
| 同文件 `:856`、`:877`、`:901` | 锁、ChatContext、ReplyGate 均依赖 `event.group_id`。 |
| 同文件 `:482` | RuntimeFacade 使用 `qq:{group_id}` 会话键。 |
| `core/context.py:29`、`:217` | Context 要求群号，并按群号自动解析长期记忆空间。 |
| `stella_project/plugins/bot_main/cometa_bridge.py:31` | Cometa Origin 直接从群号构造 conversation_id；通知 Sender 也以群投递为主。 |

隔离探针结果：

```json
{
  "private_main_matcher": false,
  "group_main_matcher": true,
  "private_plugin_rule": true,
  "private_plugin_disabled": false,
  "private_has_group_id": false
}
```

测试通过 `chat_handler.check_rule(bot, event, {})`，使用相同文本并令群事件 `to_me=true`，群号在隔离白名单里。这个结果证明私聊被本体 matcher 排除，不是推测 LLM 不愿回复，也不是群白名单配置能够修好。

现有私聊能力属于插件路径：

- `ai_gateway.py:795` 的插件规则接受 `MessageEvent`，调用 `should_dispatch`。
- `astrbot_compat/pipeline.py:35` 在没有群号时依据 `allow_private` 决定是否分发。
- `config/settings.py:1004` 的 `ASTRBOT_COMPAT_ALLOW_PRIVATE` 默认 true；本地快照也为 true。
- `tests/astrbot_compat/test_dispatch.py:86` 覆盖私聊插件命令无需前缀；本轮测试通过。
- 兼容层还有 `FriendMessage`、私聊发送和插件自发请求 Provider 的路径；这与本体主聊天及其记忆链不同。

**打开 `ASTRBOT_COMPAT_ALLOW_PRIVATE` 无法修复本体聊天；本地该开关已经打开。**

## 问题 2：个人记忆实际归属于共享空间

GitNexus trace 及源码确认的检索链：

```text
build_user_context
  → _build_user_context_v2
  → retrieve_memories / retrieve_memories_emb
  → _fetch_candidates / _query_fts
  → Visibility / Usage Policy → Ranking → Prompt
```

关键证据：

- `config/spaces.py:161`：显式 TOML → 自动账本 → 为新群分配独立 `space_N`。
- `memory/pre_processors.py:551`：读取当前 context 的共享空间；稳定画像也按该空间查。
- `memory/pre_processors.py:617`：画像条件为 `group_shared_space = ? AND user_id = ?`。
- `memory/schema.py:380`：画像主键为 `(group_shared_space, user_id)`。
- `memory/retrieval_v2.py:154`：普通回复候选同样限定 `group_shared_space` 与 `user_id`。
- 同文件 `:278` 的 FTS 也限定空间；`retrieve_memories_emb` 的向量评分只能在该候选池内计算。
- `memory/retriever.py:518`：v1 检索也限定空间与用户。关闭 v2 不会实现跨空间共享。
- `memory_rust/native/src/retrieval.rs:111`、`:160`：Rust SQL 与 FTS 同样限定空间。切换后端也不能解决。
- `memory/retrieval_v2.py:518`：缓存键包含空间、用户、话题、模式和历史版本；改 SQL 时还需改缓存授权范围。

用同一用户 2001，在 A/B 空间分别写入一条合成 OPEN 个人偏好后，调用真实 `retrieve_memories`：

| 检索输入 | 候选数 | 返回记忆 ID |
|---|---:|---|
| `space_A / 2001` | 1 | `a` |
| `space_B / 2001` | 1 | `b` |
| `space_C / 2001` | 0 | 空 |
| `space_A / 2002` | 1 | `other` |

同一 QQ 号不会突破空间条件；不同 QQ 号不会串用记录。探针另放置了同用户 INTERNAL 记录，它没有进入普通回复候选。

当前本地配置映射：

| 启用群 | 归属空间 | 映射来源 |
|---|---|---|
| 263402786 | space_1 | 显式 TOML |
| 1124196924 | space_1 | 自动账本 |
| 1074455954 | space_2 | 显式 TOML |
| 913323767 | space_3 | 显式 TOML |

只读数据库快照：845 条 active 记忆全部在 `space_1`，涉及 54 个 user_id；画像为 `space_1` 46 条、`space_2` 1 条。`space_2/3` 的检索不会拿到那 845 条记忆。前两个群则已具有同空间共享的条件。实际是否出现在回复中，仍取决于当前用户、策略、相关性和 prompt 预算，不能将“不提及”直接当作“没有检索”。

## 修复方案

### A. 先接通本体私聊，统一会话身份

新增明确的平台会话描述，至少包括 `platform / bot_id / conversation_kind / peer_id / conversation_key`，并独立携带 `subject_id` 与 `memory_space_id`。

示例（拟议格式）：

```text
群会话：qq:<bot_id>:group:<group_id>
私聊会话：qq:<bot_id>:private:<user_id>
用户身份：qq:<user_id>
```

同一用户的身份跨群、私聊一致；群号与 QQ 号数值相同也不会撞会话。默认同一 bot 内共享个人认知；跨 bot / 不同人格的关系态度需保留独立归属。

实施要点：

1. 主 rule 接受群/私聊的 MessageEvent，分别判断：群维持白名单与 @ 触发；允许的私聊有文本或已启用的图片即可触发。新增本体私聊开关及用户允许/拒绝策略，与插件开关分别说明。
2. 共用现有 RuntimeFacade / TurnService / Pipeline。将事件规范化与投递适配放在入口边界，避免复制一套独立私聊引擎。
3. 锁、回复门禁、reset、短期历史、compact 和整合 checkpoint 按 `conversation_key` 隔离。保留旧群历史的兼容映射；新增字段/迁移不能使历史群消息突然查不到。
4. 不用 `group_id=0`、直接拿 `user_id` 当群号或所有私聊共用一个负数。群专属 participation、定时主动发言、群管理和群身份查询仅在 group 会话执行；私聊应走明确的直接请求路径。
5. 私聊的收发消息也进入同一条记忆流水线，BOT_SELF 仅在确认投递后记账；整合任务不能只遍历 `ALLOWED_GROUPS` 而漏掉私聊。
6. trace 根、插件已处理标记、去重键包含 bot、会话类型、peer 和 message_id，避免跨会话 ID 冲突。
7. 普通投递按 kind 选择 `send_group_msg` / `send_private_msg`，复用回执与多段投递契约。
8. 同步扩展 Cometa Origin、通知 target、Sender 与附件降级。私聊请求的 ack、后台结果只能回到原私聊；不可进入现有群通知分支。扩展跨进程 Context 投影及 schema 兼容读取。

退出条件：好友私聊正常回复；陌生人/临时会话按配置接受或明确拒绝；多用户私聊、群与私聊历史及锁不串用；重启后会话归属稳定；已有群路径与 WebChat 回归通过。

### B. 将“个人认知”从“空间记忆”中拆出

保留当前共享空间语义，增加 subject 级个人记忆。推荐模型：

| 层 | 归属键 | 适合保存的内容 | 跨场景行为 |
|---|---|---|---|
| 用户身份 | `(platform, native_user_id)` | 原生账号身份 | 同一 QQ 号跨群/私聊一致；不按昵称猜身份。 |
| 个人稳定认知 | subject，必要时附 bot 关系命名空间 | 明确姓名、语言/饮食偏好、稳定技能等 | 经共享策略允许后，跨群和私聊参与候选。 |
| 空间记忆 | 现有 shared space | 群内约定、群事件、空间人格与局部关系 | 保持现有空间归属。 |
| 会话历史 | conversation_key | 当前聊天尾巴、压缩摘要、checkpoint | 每个群、每个私聊独立。 |

可在现有 memories / candidates 增加明确的 `owner_scope / owner_key / subject_id / source_conversation_key / sharing_policy`，历史行默认仍为 space scope。画像另拆 subject 级稳定事实与空间级关系态度，避免把某个人在一个群的情绪/冲突判断直接当成所有场景的画像。数据契约的字段名在实施时统一冻结。

检索逻辑变为：

```text
当前空间可用记忆
  UNION 当前用户可向目标场景共享的 subject 记忆
  → Visibility / Usage Policy
  → 去重、冲突处理、排序与固定预算
  → Prompt 注入及 memory_trace
```

规则应在 SQL / FTS / 向量候选资格阶段一致执行，不能先找出所有记录再靠 prompt 要求模型保密。`OPEN` 目前是模式可见性，不等同“允许跨空间公开”。拟议默认：明确可共享的稳定个人事实可跨场景；私聊原文、私聊专属事实与局部冲突留在原会话/授权范围。用户可将指定事实明确标为共享。

写入链也必须改：候选提取区分个人事实与空间事实；晋升、合并、配额、冲突和压缩按新的 owner scope 处理；保留源证据。仅取消检索的空间 WHERE 条件会混入其他场景事件，且不能解决画像、写入和缓存归属。

同步范围：Python v1/v2、FTS、embedding 候选、Planner 深度查忆、Rust request/SQL/schema 握手、缓存 key/version、WebUI 查询及删除导出。当前 memory schema 为 v14、backend API 为 v1；新格式应整体升版并验证不兼容旧 native 模块的明确降级行为。8K 等既有上下文预算保持不变；跨场景记忆只是候选来源增加，不额外在主回复路径做 LLM 分类。

历史迁移：先备份和预览，旧数据维持原空间；从有明确用户证据的稳定个人事实做去重回填，保留来源与冲突，不把全部历史记忆直接提升为全局。新私聊写入应带 source kind；主动发言的 user_id=0 不可生成真实 subject。

退出条件：同一用户在 A 群形成的共享个人事实，在独立 B 群与该用户私聊都进入允许候选；其他用户、局部群事件、私聊专属事实按策略隔离；更新/删除立即使所有相关缓存失效；Python/Rust 的候选和结果一致。

### C. 可选的现成群间缓解措施

如果若干群本来就应该共用人格和全部空间级长期记忆，可在一个 `<STELLA_HOME>/config/spaces/<name>.toml` 中配置多个 `qq_groups`。已有历史数据需要使用现成 space-merge，而不只是改配置。

示例命令（本轮未执行，空间名仅作示例）：

```powershell
python -m deploy space-merge --from space_1,space_2 --to casual --dry-run
# 停止写入、核对预览与冲突后，再执行实际合并，并协调显式空间 TOML。
python -m deploy space-merge --from space_1,space_2 --to casual
```

现有 `memory/space_merge.py:158` 处理事务、备份、FTS、归属表和自动账本；显式 TOML 仍需与目标归属一致。画像冲突会择一保留，这不是无损的全字段合并。它能缓解群间共享需求，但不接通私聊，也不提供“不同人格空间仍记得同一个人”的能力。

## 影响分析与实施顺序

| 符号 | Docker GitNexus upstream 结果 | 需要注意的调用/流程 |
|---|---|---|
| `resolve_space` | **CRITICAL**；20 个影响节点、11 个直接关系 | Planner、群配置列表、知识库 principal、画像与检索、整合 drain、主动发言、称呼处理。不能按 `riskSharedAxes=MEDIUM` 降级解释。 |
| `ChatContext` | MEDIUM；17 个影响节点、9 个直接关系 | Runtime、Pipeline、Capability、记忆钩子、QQ 入口、WebChat 与投影。 |
| `retrieve_memories` | MEDIUM；11 个影响节点、6 个直接关系 | 上下文组装、Planner、embedding、后端桥和 benchmark。 |
| `handle_chat` | **UNKNOWN**；未解析到调用者 | 已以 `@chat_handler.handle()` 注册、文本调用点及真实 matcher 探针确认其有效；不能把 0 当安全结论。 |
| `build_origin` | LOW；1 个直接调用者 | `handle_chat`；通知 Sender 仍需单独完整审计。 |

建议顺序：

1. **P0：冻结会话/身份契约并接通私聊闭环。** 范围覆盖入口、历史、整合、观测及结果回传。保留群业务兼容路径。
2. **P1：增加 subject 记忆归属、共享资格和双层画像。** 同时完成写入、候选检索、缓存、后端契约及迁移。
3. **P2：补配置面板、追踪解释和现有历史的审慎回填。** 展示记忆来自哪层、因何允许或拒绝、是否因预算裁剪；便于区分未检索和未提及。

每次业务符号编辑前重跑对应 impact；提交前按项目要求执行完整 detect_changes。图的 UNKNOWN 与动态入口必须继续用源码和运行探针确认。

## 验收矩阵与本轮检查

| 场景 | 修复验收要求 |
|---|---|
| 好友私聊，无 @ | 本体回复，输入/确认送达输出记账，trace 完整。 |
| 插件先处理私聊 | 本体不再二次回复；跨会话 message_id 相同不互相抑制。 |
| 两个不同用户私聊 | 历史、锁、压缩、reset 和个人记忆互不串用。 |
| 群号恰好等于用户 QQ 号 | group/private 的会话键不会冲突。 |
| 同一 QQ 号跨两个独立空间 | 共享 subject 事实可用；各自群事件和人格保持原归属。 |
| 群 → 私聊、私聊 → 群 | 可共享事实按资格引用；私聊专属信息不自动公开。 |
| 临时/陌生人消息、纯图和自身回显 | 按明确配置与现有 vision 策略处理，无自激。 |
| 私聊 Cometa 任务 | ack、状态、最终结果与附件只投原私聊；unknown 不重复发送。 |
| 更新、删除、迁移、重启 | 跨场景缓存失效、归属稳定、历史可读、失败可回滚。 |
| Python/Rust、普通/Planner/embedding | scope、资格过滤及返回结果保持一致。 |

本轮检查：

```text
python -m pytest tests/test_spaces.py tests/test_retrieval_v2_and_schema.py tests/astrbot_compat/test_dispatch.py -q -p no:cacheprovider
42 passed, 1 warning
```

另完成上述真实 NoneBot matcher 探针与临时库检索探针，所有断言通过。既有测试通过说明当前的“群入口、空间隔离和插件私聊”行为符合现有测试，并不代表本体私聊或跨空间个人记忆已经实现。
