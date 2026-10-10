# 关键数据结构

中文 | [English](data-boundaries.en.md) · [文档总览](../README.md)

## 关键数据结构

### ChatContext

一次处理的运行期载体，是各模块间传递数据的唯一通道。

| 分组 | 字段 |
|---|---|
| 输入标识 | `user_id` `group_id` `group_shared_space` `msg_id` `message` `source_kind` |
| 处理产物 | `raw_output` `thought` `action` `reply` `lines` |
| 诊断 | `trigger` `intent` `intent_detail` `llm_backend` `llm_model` `llm_elapsed` `prompt_log` |
| 结构化上下文 | `short_term` `user_profile` `memories_for_prompt` `tail_start_id` |
| 记忆 v2 | `memory_mode` `conversation_memories` `behavior_constraints` `memory_trace` |
| 任务调度 | `route` `task_results` `tool_summaries` `knowledge_evidence` |
| 平台句柄 | `raw_event` `bot` |

`group_id` 始终是真实 QQ 群号；`group_shared_space` 由 `config.spaces.resolve_space()` 自动填入，是记忆与画像的归属标识。两者不可混用。

`raw_event` / `bot` 是**不透明句柄**：Comes 调 AstrBot 工具时，工具 handler 内部会用 `event.send()` / `event.bot.call_action()`，必须是真实对象，构造不出等价替身。`core` 不解释它们的类型、也不碰任何方法，只负责从接入层传递到能力层。两者都标了 `repr=False`——OneBot 事件的 `repr` 会把整条消息与 sender 全展开，日志里 `ChatContext` 一旦被 `repr` 就会刷屏。

`route` 的类型标注是 `Any` 而非 `Route`：`core` 是「与业务无关的编排骨架」，不该 import `capability`，反向依赖会成环。

`tool_summaries` / `knowledge_evidence` / `memories_for_prompt` 是**三轨分离**的：工具摘要（压缩文本）、知识库证据（带编号引用的结构化摘录，独立预算 `KNOWLEDGE_EVIDENCE_*`，见 docs/knowledge-base.md）、记忆检索结果各自走各自的渲染与预算，互不挤占。知识证据**绝不**进入记忆整合——`knowledge/isolation.py` 是这条红线的运行时护栏。

### 主要数据表

**会话与记忆归属分开**。以下表保留群业务字段命名；`group_messages`、`short_term_context`、`consolidation_state` 的会话物理键也承载私聊/WebChat。群空间可共享 SPACE 记忆，PERSON 记忆还必须通过 owner、subject 与 audience 判定；共享空间不会合并不同会话的消息尾巴。

| 表 | 归属 | 作用 |
|---|---|---|
| `group_messages` | 会话 | 原始群消息（含 `source_kind`） |
| `short_term_context` | 会话 | 每群的话题摘要与关键发言 |
| `consolidation_state` | 会话 | 每群的整合 checkpoint |
| `proactive_state` | QQ 群 | 主动 @ 的配额、冷却、退避状态 |
| `group_runtime_state` | QQ 群 | 静音开关、睡眠/苏醒播报去重 |
| `participation_topics` | QQ 群 | 话题生命周期与当前参与状态 |
| `participation_log` | QQ 群 | Participation 每次评分与决策记录 |
| `memory_candidates` | **SPACE/PERSON** | 记忆候选（含 `occurrence_count` / `source_kinds` / `first_seen_at`） |
| `memories` | **SPACE/PERSON** | 长期记忆（含 `usage_tags` / `visibility` / `behavior_rule`） |
| `memories_fts` | **SPACE/PERSON** | FTS5 全文索引（按 `mem_id` 与 `memories` 同步） |
| `user_profiles` | **空间** | 用户稳定画像，主键 `(group_shared_space, user_id)` |
| `user_address_preferences` | **空间** | 用户称呼偏好（v14），主键 `(group_shared_space, user_id)` |
| `atomic_facts` | **空间** | 长记忆拆分出的原子事实 |
| `memory_traces` | 两者 | 记忆决策追踪（`group_id` 记触发来源，`group_shared_space` 记检索空间） |
| `expression_examples` / `jargon_glossary` / `behavior_patterns` / `reply_effects` | **空间** | 表达与插话效果学习（`expression_store` 独立建表，不走 schema 迁移；`reply_effects` 另记 `group_id`） |
| `compressor_stats` / `compressor_state` | 全局 | 压缩统计与节流状态 |
| `llm_usage_daily` | 全局 | 每日 LLM 用量，主键 `(date, role, slot, model)` |
| `schema_meta` | 全局 | Schema 版本号 |

Schema 采用**版本化迁移**：简单变更加列/索引，结构调整在事务内重建与校验，保留业务数据；迁移前自动备份。独立执行：

```bash
python -m memory.schema --dry-run   # 预览
python -m memory.schema             # 执行
python -m memory.schema --backup    # 仅备份
```

> **改结构与改数据在另一个模块**：`memory/migrations.py` 按版本注册（`migrate_v7` / `v8` / …），
> 每版一个函数、一个事务，成功后才推进 `schema_meta.version`；`schema._migrate()` 的加列/建表
> 作为每次迁移的收尾步骤。当前 `SCHEMA_VERSION` 为 **18**；v7（画像分群）、v8（记忆表改按空间归属）、
> v13（Participation 话题/决策日志）与 v14（称呼偏好表）等数据迁移均由 `memory/migrations.py` 注册，v5 → 当前版全自动：
> 列改名 + 值重写为空间名 + 画像主键重建 + FTS 重建 + Participation 表创建与校验，
> 失败整级回滚。**新规矩：`SCHEMA_VERSION` 每 +1 必须同时提交 `migrate_vN` 与旧库夹具测试。**
>
> 每次迁移写一份 `agent_memory.db.pre-vN-<时间戳>.bak`（这次迁移前的状态）；
> `stella_memory_backup.db` 是「有史以来第一份原始库」，见备份已存在即跳过——封存旧库时
> 要连它一起移走，否则会留下「看起来有备份、实际备份错了」的状态。
## 时间处理约定

SQLite 的 `CURRENT_TIMESTAMP` 写入 **UTC**。所有「拿 Python 时间与 DB 时间戳比较」的地方**必须**走 `memory/timeutil.py`，否则在非 UTC 时区会产生固定偏移。

SQL 内部的比较（`julianday('now')` vs `julianday(col)`）两侧同为 UTC，无需处理。
## 两层归属的分界线

「群」在本项目里有两个含义，混用会产生难查的错乱。

**按 QQ 群归属的**（当下这场对话的状态）：
- 消息尾巴、整合 checkpoint、短期话题、会话压缩状态
- 静音开关、主动 @ 配额与冷却、活跃度统计

**按共享空间归属的**（对人的长期认知与身份）：
- 用户画像、长期记忆、原子事实、FTS 索引
- 人格（system prompt）、发言策略

**分界依据**：如果一个数据被两个群共用会造成「答错话」，它必须按 QQ 群；如果被两个群共用是「同一个人的同一份认知」，它应该按空间。

代码里的约定：函数形参用 `group_id: int` 表示 QQ 群，用 `group_shared_space: str` 表示空间。`resolve_space(qq_group_id)` 是唯一的转换入口。

一个遗留的歧义：`long_term_memories`（待废弃的旧兼容表）列名仍是 `group_id`，但**写入与查询的都是空间标识**。为一张即将淘汰的表改列名不值得，但这个不一致必须知道。
