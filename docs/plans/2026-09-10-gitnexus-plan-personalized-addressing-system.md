# GitNexus Engineering Plan

> Task: 为 Stella 增加按共享空间隔离的个性化称呼系统，支持自然语言设置/清除，并使用 LM Studio embedding 模型做称呼意图初筛。
> Evidence verified at commit `71d91decabb2ae3674fabaaecffbdc9b1fc369da`; GitNexus index current at HEAD（已手动刷新）。
> GitNexus runner: `npx gitnexus` distribution `1.6.11`; PDG layer unavailable.
> Evidence provenance schema 2; global dirty digest `0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd`; cited-path manifest 25 entries; exact generated plan path excluded.

## 1. Objective

让用户可以用自然语言表达自己的称呼偏好，例如“以后叫我哥哥”，Stella 在明确面向该用户时自然使用该称呼；偏好按 `group_shared_space + user_id` 隔离，并支持清除、查询、管理员代设和空间合并。

Embedding 只用于语义路由/置信度判断；任何持久化写入都必须经过结构化解析、目标解析、权限校验、内容校验和统一偏好服务。

## 2. Current Behaviour

[verified] `ChatContext` 统一承载 `user_id`、`group_id`、`group_shared_space`、画像和 Prompt 结构化上下文（`core/context.py:17-120`）。

[verified] 用户上下文由 `capability/hooks.py:_retrieve_memory` 间接调用 `memory.pre_processors.build_user_context`，不应再注册第二个独立记忆 hook（`capability/hooks.py:94-99,197-203`）。

[verified] v2 Prompt 入口是 `build_v2_prompt_context`，稳定身份段位于动态时间/摘要/画像之前（`memory/prompt_builder.py:186-255`）；普通回复和主动流程最终都经 `Pipeline.run`（`core/pipeline.py:155-307`）。

[verified] `memory.embeddings.EmbeddingService` 已实现 LM Studio `/v1/embeddings`、进程缓存、共享模型闸门和失败返回 `None` 的降级契约（`memory/embeddings.py:4-28,79-164`）。

[verified] `capability.router.semantic` 已实现原型均值、模型变更失效、绝对阈值、相对 margin 和缓存预热（`capability/router/semantic.py:4-28,71-161,191-302`）。

[verified] 现有 `nickname` 来自画像/平台群名片，不承载“哥哥”等关系性称呼；群级主动发言使用群级上下文，主动 @ 用户才构造目标用户上下文（`ai_gateway.py:1066-1113`）。

## 3. Relevant Architecture

[verified] SQLite schema 当前为 v13；空间归属表按 `group_shared_space` 存储，`user_profiles` 主键为 `(group_shared_space, user_id)`（`memory/schema.py:56,364-390`）。

[verified] 迁移按版本逐级执行，每级独立事务，失败回滚；新增 schema 版本必须加入 `memory/migrations.py` 的迁移表（`memory/migrations.py:658-689,710-755`）。

[verified] `space_merge.merge_spaces` 在单一大事务中改写所有空间归属表、重建 FTS 并更新账本；画像冲突目前按互动次数选择并写入报告（`memory/space_merge.py:35-172`）。

[verified] OneBot 兼容层能从消息段读取 @ 目标，并将群主/管理员映射为 `event.role == "admin"`（`astrbot_compat/events.py:488-505,811-870`）。

[inferred] 称呼配置属于显式用户偏好，不属于画像推断、普通记忆或 embedding 向量；因此应由独立表和独立服务承载。

## 4. GitNexus Findings

- [graph] `context(build_v2_prompt_context, file_path=memory/prompt_builder.py)`：6 个直接调用方，包含 `Pipeline.run` 和 Prompt 缓存测试；下游调用 `build_behavior_section`、`build_conversation_section`、`build_time_section`；参与 `handle_chat` 和 `proactive_speak_job`。
- [graph] `impact(build_v2_prompt_context, upstream, maxDepth=3)`：HIGH；直接影响 6 个符号、4 条流程、3 个模块，深度计数为 d1=6、d2=8、d3=2。必须回归普通回复、主动发言、主动 @ 和 Prompt 顺序。
- [graph] `context(build_user_context, file_path=memory/pre_processors.py)`：唯一直接调用方是 `capability/hooks.py:_retrieve_memory`；下游包含 `_build_user_context_v2`、`resolve_space`、画像读取和三类记忆检索。
- [graph] `impact(Pipeline.run, upstream, maxDepth=3)`：HIGH；d1=8、总影响 11，4 条流程。结果为 lower-bound，因为 1 个 receiver 类型无法解析的调用点可能未进入图；该缺口需以源码/文本检索兜底。
- [graph] `impact(ChatContext, upstream, maxDepth=2)`：MEDIUM；14 个直接依赖、5 个间接依赖，涉及 pipeline、memory、bot_main 和多个测试。
- [graph] `impact(_proactive_at_user, upstream, maxDepth=2)`：LOW；直接影响主动发言流程 1 个调用点。
- [graph] `impact(merge_spaces, upstream, maxDepth=2)`：MEDIUM；9 个直接测试依赖，修改合并表清单或冲突策略必须保持既有 dry-run、备份和报告契约。
- [graph] `impact(migrate_v13, upstream, maxDepth=2)` 返回 UNKNOWN 且无解析调用方；源码已确认它通过 `MIGRATIONS[13]` 参与版本迁移，因此不能把空 caller 集合当成无影响。
- [graph] `query("user preference natural language capability semantic routing embedding LM Studio ...")` 找到现有 `EmbeddingService`、`route_semantic`、`build_user_context` 和相关 embedding/路由测试，说明新能力应复用既有 embedding 服务而不是重建 HTTP 客户端。

## 5. Statement-Level PDG Findings

PDG 查询 `pdg_query({mode:"controls", target:"build_v2_prompt_context", repo:"Stella_project"})` 返回 `no PDG layer`。因此没有可引用的 CDG/REACHING_DEF/TAINT 结论；以下约束来自当前源码和调用图，不伪造 statement-level 边。

[verified] `Pipeline.run` 先执行 pre-hooks，再在 `ctx.reply`/Planner 分支后组装 Prompt，随后单次调用回复 LLM，并执行 post-hooks（`core/pipeline.py:167-307`）。实现时不能让称呼识别递归进入 `Pipeline.run`，也不能破坏“普通快速路径单次 LLM 调用”。

[verified] `build_v2_prompt_context` 的稳定区先于时间和动态记忆区（`memory/prompt_builder.py:219-255`）。称呼偏好应放入稳定身份区，且仅在 `current_user_id` 明确非 `0/None` 时注入。

[verified] `EmbeddingService.embed` 的失败路径缓存 `None`，调用方必须把 `None` 当作语义层不可用并降级；网络请求通过 `_maybe_gate` 串行化共享本地模型（`memory/embeddings.py:79-99,125-156`）。

[inferred] 自然语言称呼请求应在高优先级消息 handler 中处理并阻断普通聊天，否则“设置称呼”可能被当成普通对话或同时触发其他设置 handler。

## 6. Proposed Changes

### 6.1 偏好数据与服务

**新增 `memory/addressing.py`**

- 新增 `user_address_preferences` 数据访问和领域服务。
- 表主键为 `(group_shared_space, user_id)`；字段包括 `address_term`、`source`、`updated_by_user_id`、`updated_at`。
- 提供读取、设置、清除、查询和内容校验入口；所有 SQL 参数化，设置/清除使用统一事务边界。
- 只保存规范化后的短称呼，不保存 embedding 向量；不从普通记忆或 LLM 自动学习。
- 校验拒绝空值、控制字符、换行、超长文本和会破坏 Prompt 结构的内容。

**修改 `memory/schema.py`、`memory/migrations.py`**

- 将 `SCHEMA_VERSION` 从 13 升到 14。
- 增加可幂等创建新表的 DDL 和 `migrate_v14`。
- 遵循现有逐级事务、失败回滚、迁移备份和校验逻辑。

### 6.2 Embedding 意图路由与自然语言解析

**新增 `memory/addressing_intent.py`**

- 复用 `memory.embeddings.EmbeddingService`、`cosine_similarity` 和现有 `MEMORY_EMBEDDING_*` 配置。
- 建立小型原型集：`SET_SELF_ADDRESS`、`SET_OTHER_ADDRESS`、`CLEAR_ADDRESS`、`QUERY_ADDRESS`、`NOT_ADDRESS_REQUEST`。
- 采用“原型均值 + 绝对阈值 + top-1/top-2 margin”判断是否进入称呼配置流程；缓存必须包含模型标识，模型变更时失效。
- Embedding 不可用时退回低成本规则识别；仍无法确认时按普通聊天处理或请求澄清。
- 解析层输出结构化 `AddressingRequest`，至少包含操作、目标用户、称呼、置信度和是否需要澄清。
- 目标用户优先从 OneBot @ 消息段解析；没有明确他人目标时默认当前发送者；多个或模糊目标不猜测。
- 称呼文本优先由确定性短语提取；必要时可调用现有 `ROLE_ROUTER` 后端做受限 JSON 提取，但该调用只能产出候选，不能直接写库。

**修改 `config/settings.py`**

- 增加称呼功能开关、语义开关、超时、绝对阈值和 margin 配置。
- 默认保持 embedding 失败可降级；不新增第二套 LM Studio URL/model 配置，复用 `MEMORY_EMBEDDING_BASE_URL`、`MEMORY_EMBEDDING_MODEL` 和 `MEMORY_EMBEDDING_TIMEOUT`。
- 文档注明 embedding 与本地聊天共享闸门时可能增加排队，独立端点可避免竞争。

### 6.3 消息入口、权限和互斥

**修改 `stella_project/plugins/bot_main/ai_gateway.py`**

- 增加高优先级、`block=True` 的称呼偏好 handler，触发条件为已启用群、@ Stella、非空文本和称呼意图命中。
- 与现有 toggle、capability、reload handler 同级时，加入机械互斥规则和启动期穷举自检，避免同一句话既修改称呼又执行其他设置。
- 自设：用户可设置/清除自己的称呼。
- 代设：仅群主、群管理员或全局管理员可为他人设置/清除。
- 高置信度且字段完整时直接写入并自然确认；缺少称呼、目标或语义不明确时澄清，不写库。
- 非管理员尝试修改他人时不写库，并返回符合现有设置 handler 约定的拒绝响应。
- 处理成功后阻断普通 `chat_handler`，避免再次调用回复 LLM。

### 6.4 运行时上下文与 Prompt

**修改 `core/context.py`**

- 增加可选运行期字段 `preferred_address`，默认 `None`。
- 字段只代表当前明确目标用户的称呼偏好，不替代 `nickname`，不进入普通记忆字段。

**修改 `memory/pre_processors.py`**

- 在 `build_user_context` 的 v1/v2 共同入口读取称呼偏好，使用已解析的 `group_shared_space` 和明确用户 ID。
- 当前用户为 `0/None`、触发为群级主动插话或目标不明确时不填充 `preferred_address`。
- 不新增独立 memory hook；继续由 `_retrieve_memory` 统一调用，避免重复检索。

**修改 `memory/prompt_builder.py`、`core/pipeline.py`**

- 扩展 `build_prompt_context` 和 `build_v2_prompt_context` 的可选 keyword 参数，保持既有 positional 调用兼容。
- 将称呼规则放入稳定身份段：自然使用、不要每句重复、只对目标用户使用、不要暴露内部配置；称呼文本作为不可信用户数据处理。
- `Pipeline.run` 在 v1/v2 两条 Prompt 分支通过 keyword 传入 `preferred_address`。
- 不改变 `_compose_prompt` 的当前输入标记和 `proactive_at` 指令前置顺序。

### 6.5 空间合并

**修改 `memory/space_merge.py`**

- 将 `user_address_preferences` 纳入空间归属表清单和行数/合并处理。
- 同一用户冲突时按最近一次显式 `updated_at` 选择；并列时按稳定规则选择。
- 报告记录冲突、胜出空间和操作来源；不沿用画像的互动次数规则。
- 保持单事务、dry-run、备份、账本更新和失败回滚契约。

## 7. Implementation Sequence

1. 先在执行分支中重新运行 `impact`，确认本计划引用的 HIGH/MEDIUM 符号未发生漂移；检查当前工作树和 schema 版本。
2. 增加 `memory/addressing.py` 的领域对象、校验和 CRUD；先完成隔离、清除、更新来源和时间戳语义。
3. 增加 v14 DDL/迁移，并补旧库夹具、幂等、失败回滚和新表校验。
4. 增加 `memory/addressing_intent.py`：原型语料、缓存、阈值/margin、规则提取和澄清结果；复用既有 embedding service，不接入 `CapabilityRegistry`/Comes。
5. 增加配置项和日志/指标：命中意图、分数、margin、降级原因、解析失败和拒绝原因；日志不得记录不必要的称呼隐私。
6. 在 `ai_gateway.py` 增加自然语言称呼 handler、OneBot @ 解析、权限判断和与同优先级 handler 的互斥自检；成功后阻断普通聊天。
7. 扩展 `ChatContext`、用户上下文构建、v1/v2 Prompt builder 和 `Pipeline.run`；先保持未设置称呼时输出逐字不变。
8. 更新主动 @ 路径：`_proactive_at_user` 的目标用户上下文允许注入称呼；群级 `_proactive_speak_for_group` 明确保持不注入。
9. 扩展 `space_merge` 及其报告/冲突测试。
10. 完成定向测试、全量测试、ruff 检查；随后运行 `detect_changes({scope:"all"})`，若非 clean 或 partial/truncated，继续复核，不提交未经解释的变更。

## 8. Test Strategy

**新增单元测试**

- `tests/test_addressing.py`：按空间/用户读取；设置；清除；覆盖更新；非法称呼拒绝；来源和操作者记录。
- `tests/test_addressing_intent.py`：原型均值、缓存按模型失效、阈值和 margin、embedding 失败降级、普通聊天负样本、中文自然表达解析。
- `tests/test_addressing_handler.py`：自设、清除、查询、管理员代设、非管理员拒绝、模糊目标澄清、handler 阻断和互斥。

**更新既有测试**

- `tests/test_prompt_builder_v2.py`：称呼位于稳定身份区；主动/群级上下文不注入；空称呼不生成空段；旧调用输出保持兼容。
- `tests/test_pipeline_compose.py`：v1/v2 传参不改变当前输入标记、指令前置和普通路径单次 LLM 调用。
- `tests/test_embeddings.py`、`tests/capability/test_router_semantic.py`：复用 `EmbeddingService` 的缓存、失败降级、模型变更和 margin 约定；不修改现有工具路由语义。
- `tests/test_proactive_at_flow.py`：主动 @ 目标可读取称呼；群级主动插话不读取具体用户称呼。
- `tests/test_migrations.py`：v13 → v14、旧库迁移、空新表、重复迁移、失败回滚和版本校验。
- `tests/test_space_merge.py`：新表归属改写、称呼冲突按 `updated_at` 选择、报告记录、dry-run/备份/回滚。
- `tests/astrbot_compat/conftest.py` 或现有事件夹具：增加带 `at` segment 的目标解析样例。

**关键输入 → 期望结果**

- `@Stella 以后叫我哥哥` → 当前用户设置 `哥哥`，确认回复，普通聊天不再执行。
- `@Stella 别再这样称呼我` → 当前用户称呼清除。
- `@Stella 我哥哥来了` → 不改配置，走普通聊天。
- `@Stella 把 @1002 的称呼改成队长`（管理员）→ 写入用户 1002；非管理员 → 拒绝。
- 群级主动插话 → `preferred_address is None`。
- embedding 服务不可用 → 不阻断聊天；高置信规则表达仍可处理，其他消息按普通聊天。

**验证命令**

```text
python -m pytest tests/test_prompt_builder_v2.py tests/test_pipeline_compose.py tests/test_embeddings.py tests/capability/test_router_semantic.py tests/test_proactive_at_flow.py tests/test_migrations.py tests/test_space_merge.py -q
python -m pytest tests -q
ruff check .
node .gitnexus/run.cjs detect-changes --scope all --repo .
```

现有仓库约定确认于 `pyproject.toml:102-110` 和 `.github/CONTRIBUTING.md:46-55`；新增测试文件名需在实现阶段按实际测试布局确认。

## 9. Risk and Impact Analysis

- **HIGH：`memory/prompt_builder.py:build_v2_prompt_context`、`core/pipeline.py:Pipeline.run`。** 直接影响普通回复、主动发言、主动 @、Prompt 缓存顺序和多个调用测试；必须保持可选参数和旧输出兼容。
- **MEDIUM：`core/context.py:ChatContext`、`memory/space_merge.py:merge_spaces`。** 前者有 14 个直接依赖；后者有 9 个直接测试依赖，且空间合并不可逆。
- **LOW：`_proactive_at_user`。** 只需将目标用户偏好纳入已有目标上下文，不能改变发送、配额、退避和 skip 副作用。
- **UNKNOWN：`migrate_v13` 图上无 caller。** 源码确认它由版本映射表调用；执行阶段必须以文本和迁移集成测试核验，不把空影响结果当成安全证明。
- **误触发风险。** 普通聊天、引用、反问和角色扮演可能被误识别；embedding 需配合负样本、margin、规则提取和澄清，不可单独写库。
- **安全风险。** 称呼是用户输入，必须限制长度/字符并作为数据注入 Prompt；管理员代设必须在后端校验权限。
- **性能风险。** 每次候选消息可能额外调用本地 embedding；应先走廉价规则预筛，复用进程缓存和既有闸门，并记录耗时/降级原因。
- **一致性风险。** 称呼配置和空间合并必须使用参数化 SQL、事务和确定性冲突规则；迁移失败必须保留备份并回滚。
- **可观测性。** 记录意图类别、分数区间、降级/拒绝原因和命中率，不记录不必要的完整用户称呼或完整私密消息。

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `memory/addressing.py` | new preference service | 称呼配置 CRUD、校验、权限入口 |
| `memory/addressing_intent.py` | new intent classifier/parser | embedding 原型路由、结构化解析、澄清 |
| `memory/schema.py` | `SCHEMA_VERSION`, new DDL | v14 新表 |
| `memory/migrations.py` | `migrate_v14`, `MIGRATIONS` | 旧库升级 |
| `memory/space_merge.py` | `merge_spaces`, report/conflict helpers | 合并新表和冲突报告 |
| `config/settings.py` | new addressing settings | 开关、阈值、超时 |
| `stella_project/plugins/bot_main/ai_gateway.py` | new handler/rules | 自然语言入口、权限和互斥 |
| `core/context.py` | `ChatContext` | 运行期称呼字段 |
| `memory/pre_processors.py` | `build_user_context`, `_build_user_context_v2` | 读取当前目标用户偏好 |
| `memory/prompt_builder.py` | `build_prompt_context`, `build_v2_prompt_context` | 稳定身份区注入称呼规则 |
| `core/pipeline.py` | `Pipeline.run` | v1/v2 传递称呼字段 |
| `tests/test_addressing.py` | new | 数据服务测试 |
| `tests/test_addressing_intent.py` | new | embedding/解析测试 |
| `tests/test_addressing_handler.py` | new | handler/权限/互斥测试 |
| `tests/test_prompt_builder_v2.py` | existing tests | Prompt 回归 |
| `tests/test_pipeline_compose.py` | existing tests | 管线兼容回归 |
| `tests/test_embeddings.py` | existing tests | embedding 服务回归 |
| `tests/capability/test_router_semantic.py` | existing tests | 语义路由约定回归 |
| `tests/test_proactive_at_flow.py` | existing tests | 主动 @ 回归 |
| `tests/test_migrations.py` | existing tests | v14 迁移回归 |
| `tests/test_space_merge.py` | existing tests | 空间合并回归 |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: "Add a shared-space/user-scoped personalized addressing system with natural-language configuration, LM Studio embedding intent screening, deterministic authorization/persistence, and prompt injection only for explicit target users."
  acceptance_criteria:
    - "Natural-language self-set, clear, query, and administrator-targeted addressing requests are recognized without making ordinary conversation mutate state."
    - "Embedding failures degrade without interrupting normal chat."
    - "All writes pass target resolution, authorization, content validation, and the single addressing service."
    - "Preferences are isolated by (group_shared_space, user_id)."
    - "v1/v2 prompts preserve existing call compatibility and only inject addressing for explicit nonzero target users."
    - "Group-level proactive speech never receives a specific user's addressing preference; proactive @ does."
    - "Schema v14 migration, space merge, dry-run, rollback, and conflict reporting are covered."
    - "Targeted tests, full pytest, ruff, and GitNexus detect-changes pass."
  evidence_provenance: {
      "schema_version": 2,
      "head_commit": "71d91decabb2ae3674fabaaecffbdc9b1fc369da",
      "generated_plan_path": "docs/plans/2026-09-10-gitnexus-plan-personalized-addressing-system.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd"
      },
      "cited_path_manifest": [
        {
          "path": ".github/CONTRIBUTING.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
          "index_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
          "worktree_digest": "sha256:223299c36b0202408b5980ff7fe84a6593a2212a3628834da269e897a33ba382",
          "untracked_digest": "absent"
        },
        {
          "path": "astrbot_compat/events.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:5df84449d4184fe4797743c8e3f727e5833bf5aa07196c142b1ff756e663bf13",
          "index_digest": "sha256:5df84449d4184fe4797743c8e3f727e5833bf5aa07196c142b1ff756e663bf13",
          "worktree_digest": "sha256:5df84449d4184fe4797743c8e3f727e5833bf5aa07196c142b1ff756e663bf13",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/hooks.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3191c5a4d065b4af5b65d58b0087cfa116cd943376407b6eb81e1463a8e836f2",
          "index_digest": "sha256:3191c5a4d065b4af5b65d58b0087cfa116cd943376407b6eb81e1463a8e836f2",
          "worktree_digest": "sha256:2ef9b3ce5730920cf0243c0a792c108e9aba5cc4919e8b5a7b169bb26e8a1a22",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/router/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:78e640acb52d2a8d1a92bf3eaffba126cb4d2a2cb02791895c9c06ae83041da4",
          "index_digest": "sha256:78e640acb52d2a8d1a92bf3eaffba126cb4d2a2cb02791895c9c06ae83041da4",
          "worktree_digest": "sha256:78e640acb52d2a8d1a92bf3eaffba126cb4d2a2cb02791895c9c06ae83041da4",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/router/fallback.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:d94c2d3638ce5f5cb1961d0ddf8236510e9c18f3282a803e89448757be1a3b2d",
          "index_digest": "sha256:d94c2d3638ce5f5cb1961d0ddf8236510e9c18f3282a803e89448757be1a3b2d",
          "worktree_digest": "sha256:d94c2d3638ce5f5cb1961d0ddf8236510e9c18f3282a803e89448757be1a3b2d",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/router/semantic.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a71b598e84081656697f0d58b669456763dba698b62b6ea76c4e9513268d09b2",
          "index_digest": "sha256:a71b598e84081656697f0d58b669456763dba698b62b6ea76c4e9513268d09b2",
          "worktree_digest": "sha256:6691236abd25f1d701232fe100a090f26ac679349e342bea0d34c7d51bb06afe",
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
          "head_digest": "sha256:0b5195b4c983fdc804960a29eee82ec1b2103ed6ea7f795f4feda5f7dfe8b199",
          "index_digest": "sha256:0b5195b4c983fdc804960a29eee82ec1b2103ed6ea7f795f4feda5f7dfe8b199",
          "worktree_digest": "sha256:33e0f1da3fd1111dcfb593c772a69af2d9b6e89e8e6f97d81e9ee8f86f5dc496",
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
          "head_digest": "sha256:68bd188e50ccedd3bf1aaed6c81b348a60e3efc968efcb3ea24dc62557398673",
          "index_digest": "sha256:68bd188e50ccedd3bf1aaed6c81b348a60e3efc968efcb3ea24dc62557398673",
          "worktree_digest": "sha256:af55bd32335a92fce6d79b07f7dfb7ff4600b15d6dcc6329caacf0a170e435f9",
          "untracked_digest": "absent"
        },
        {
          "path": "core/pipeline.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0dc49bedb5407e64b4100d9737bd6d4ca9c87121e511db7f48e2f309d9893e2c",
          "index_digest": "sha256:0dc49bedb5407e64b4100d9737bd6d4ca9c87121e511db7f48e2f309d9893e2c",
          "worktree_digest": "sha256:43fa4c21fde92262c3a89d9989976122599b57e5c6efcb7b3f2d35f86e95a7f7",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/embeddings.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3cc1610562879116d474b74b1a44876dffd0c9125c5126feb9820f4d1cae3226",
          "index_digest": "sha256:3cc1610562879116d474b74b1a44876dffd0c9125c5126feb9820f4d1cae3226",
          "worktree_digest": "sha256:87f1267d9dec0883325fcdca02f90a38e5ac51d8349f66de6657c5198476ee53",
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
          "head_digest": "sha256:d191eb9cc6a3f4ebd89e41cd42de7c0b8f8d30c5fae7c0df7570c7229dd5b24d",
          "index_digest": "sha256:d191eb9cc6a3f4ebd89e41cd42de7c0b8f8d30c5fae7c0df7570c7229dd5b24d",
          "worktree_digest": "sha256:cd88f38eaa818266daa1814b966e7b6e617b09f0a3ad611971d4537c27a73dac",
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
          "head_digest": "sha256:281331cad478029c4d0156b9498b2a4bb946cd4b7e699eef21c65ffc115bf7c5",
          "index_digest": "sha256:281331cad478029c4d0156b9498b2a4bb946cd4b7e699eef21c65ffc115bf7c5",
          "worktree_digest": "sha256:4b754b571639fc56dd46230aaf5f19ffc897ce3e53719bc1aeb7aa86316b02dd",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/prompt_builder.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:628ddc0acb88e14d95ce3c34c29b00a800a7716813317488823de7c617af04fc",
          "index_digest": "sha256:628ddc0acb88e14d95ce3c34c29b00a800a7716813317488823de7c617af04fc",
          "worktree_digest": "sha256:5bffdc01deee32174d03076e177c17dc652fd65373ec58c73d7b4a626208729a",
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
          "head_digest": "sha256:b603587f93f6829fac5027c162d5a9ec8325720848a63d94a118a913b0c469ad",
          "index_digest": "sha256:b603587f93f6829fac5027c162d5a9ec8325720848a63d94a118a913b0c469ad",
          "worktree_digest": "sha256:82bfe44a75be7a3c87670f305e870160a32225683d7c4d8a700dfa4f48c16e04",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/space_merge.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:8d4b63a513be6c99d38ee87d1fb5963d3814472d8d83e7771166f5b39b684398",
          "index_digest": "sha256:8d4b63a513be6c99d38ee87d1fb5963d3814472d8d83e7771166f5b39b684398",
          "worktree_digest": "sha256:3e705e2553fe90c50f4d059107fbd9754112b7bcfa273e31ddc0abb86da34373",
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
          "head_digest": "sha256:7a023c8fbf7c5ad4fc2cf19a5f692cc8244440ebe57f7c728f30b024e8e2f313",
          "index_digest": "sha256:7a023c8fbf7c5ad4fc2cf19a5f692cc8244440ebe57f7c728f30b024e8e2f313",
          "worktree_digest": "sha256:55a0c7d9118d363c2588e03d880ff67e51b86cb68aeac32f9eaf95aeef19ea5a",
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
          "head_digest": "sha256:b1e8029857d790568f0f5a4866e6d9567fb2859535cd3937a7e75ee321a4ef91",
          "index_digest": "sha256:b1e8029857d790568f0f5a4866e6d9567fb2859535cd3937a7e75ee321a4ef91",
          "worktree_digest": "sha256:c32002fb1596ec7b235e77fa7c8f46a8125372b37c0261c906f262644a20037f",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/astrbot_compat/conftest.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:752393c9b3dba065e5adf97f13204a2e59eca65ef2dd476d530bb35d2f788f42",
          "index_digest": "sha256:752393c9b3dba065e5adf97f13204a2e59eca65ef2dd476d530bb35d2f788f42",
          "worktree_digest": "sha256:752393c9b3dba065e5adf97f13204a2e59eca65ef2dd476d530bb35d2f788f42",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/capability/test_router_semantic.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c45b1c21b6c5da71f1171467dc718b093a5d1be6fef1f26a8f191ae6ec85723b",
          "index_digest": "sha256:c45b1c21b6c5da71f1171467dc718b093a5d1be6fef1f26a8f191ae6ec85723b",
          "worktree_digest": "sha256:373f02fae035871994bcb1b0e7ce4d2c629fd7bc6037f104f3a82938fd167d86",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_embeddings.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:4f7afe4ae04c44599d1988cbfd3472950342be0a5a04d8af1c5676de155b7da7",
          "index_digest": "sha256:4f7afe4ae04c44599d1988cbfd3472950342be0a5a04d8af1c5676de155b7da7",
          "worktree_digest": "sha256:4f7afe4ae04c44599d1988cbfd3472950342be0a5a04d8af1c5676de155b7da7",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_migrations.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:402e33cfe610ec570c167fe717575e471f303a1560ede9b680fe109c9636f5d6",
          "index_digest": "sha256:402e33cfe610ec570c167fe717575e471f303a1560ede9b680fe109c9636f5d6",
          "worktree_digest": "sha256:402e33cfe610ec570c167fe717575e471f303a1560ede9b680fe109c9636f5d6",
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
          "head_digest": "sha256:f12660db3f7a36dde668d2b4a359fe849c25c056556bde6b71d57f3d19bba84c",
          "index_digest": "sha256:f12660db3f7a36dde668d2b4a359fe849c25c056556bde6b71d57f3d19bba84c",
          "worktree_digest": "sha256:18a996300982e1f13a5cf5dd53301ae5db9039041464ea33df369d2eff6cbecd",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_proactive_at_flow.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:9b7a9bfff912daf611b2ad90f6bcb6a9ce23bdf72446a5bd0a325b13cffefd03",
          "index_digest": "sha256:9b7a9bfff912daf611b2ad90f6bcb6a9ce23bdf72446a5bd0a325b13cffefd03",
          "worktree_digest": "sha256:9b7a9bfff912daf611b2ad90f6bcb6a9ce23bdf72446a5bd0a325b13cffefd03",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_prompt_builder_v2.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:70bf8c557f8e2fba32a33f8f6667de706557c23feac9e020cb559de94abfe40e",
          "index_digest": "sha256:70bf8c557f8e2fba32a33f8f6667de706557c23feac9e020cb559de94abfe40e",
          "worktree_digest": "sha256:70bf8c557f8e2fba32a33f8f6667de706557c23feac9e020cb559de94abfe40e",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_space_merge.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:dd9622c69432cd4f3a80b6bb7e11343bd5e50017a96ddb0748b5123a5e6a697f",
          "index_digest": "sha256:dd9622c69432cd4f3a80b6bb7e11343bd5e50017a96ddb0748b5123a5e6a697f",
          "worktree_digest": "sha256:dd9622c69432cd4f3a80b6bb7e11343bd5e50017a96ddb0748b5123a5e6a697f",
          "untracked_digest": "absent"
        }
      ]
  }
  primary_symbols:
    - {symbol: "ChatContext", file: "core/context.py", lines: "17-120", role: "运行期上下文契约"}
    - {symbol: "Pipeline.run", file: "core/pipeline.py", lines: "155-307", role: "Prompt 组装和回复主链路"}
    - {symbol: "build_user_context", file: "memory/pre_processors.py", lines: "425-538", role: "用户画像/记忆上下文入口"}
    - {symbol: "build_v2_prompt_context", file: "memory/prompt_builder.py", lines: "186-255", role: "v2 Prompt 稳定/动态分区入口"}
    - {symbol: "merge_spaces", file: "memory/space_merge.py", lines: "120-172", role: "共享空间合并事务入口"}
  related_symbols:
    - {symbol: "_build_user_context_v2", relationship: "CALLS", relevance: "v2 用户上下文分支"}
    - {symbol: "_retrieve_memory", relationship: "CALLS", relevance: "唯一现有 build_user_context 直接调用方"}
    - {symbol: "EmbeddingService", relationship: "REUSES", relevance: "LM Studio embedding 客户端/缓存/降级"}
    - {symbol: "route_semantic", relationship: "PATTERN", relevance: "原型均值/阈值/margin 语义路由模式"}
    - {symbol: "route_fallback", relationship: "PATTERN", relevance: "受闸门保护的结构化模型兜底模式"}
    - {symbol: "_proactive_at_user", relationship: "CALLS", relevance: "明确目标用户的主动 @ 流程"}
    - {symbol: "migrate_v13", relationship: "PATTERN", relevance: "版本化新表迁移模式"}
  execution_path:
    - "消息进入高优先级称呼 handler；不是称呼请求则不改变普通链路。"
    - "称呼请求先由规则/embedding 识别 intent，再提取目标用户和称呼。"
    - "后端完成权限、范围和内容校验；通过 addressing service 写入或清除。"
    - "普通用户上下文由 _retrieve_memory → build_user_context 构建；称呼字段写入 ChatContext。"
    - "Pipeline.run 将称呼字段传入 v1/v2 Prompt builder；只有明确目标用户时进入稳定身份段。"
    - "主动 @ 使用目标用户上下文；群级主动插话不提供具体用户 ID。"
    - "schema v14 迁移和 space_merge 维护称呼表的一致性。"
  pdg_constraints:
    - description: "当前索引没有 PDG layer，不能使用 CDG/REACHING_DEF/TAINT statement edges。"
      affected_statements: []
      implementation_consequence: "执行阶段以源码和测试验证控制流，并在安全敏感写入点补确定性校验。"
  architectural_patterns:
    - {pattern: "本地 embedding 统一客户端/缓存/闸门/失败降级", example_location: "memory/embeddings.py:101-164", usage_guidance: "称呼意图复用，不创建第二个 HTTP 客户端。"}
    - {pattern: "原型均值 + 绝对阈值 + 相对 margin", example_location: "capability/router/semantic.py:118-161,230-254", usage_guidance: "只用于意图筛选，不直接写状态。"}
    - {pattern: "高优先级 block=True handler 机械互斥", example_location: "stella_project/plugins/bot_main/ai_gateway.py:585-729", usage_guidance: "称呼 handler 与 toggle/capability/reload 互斥并启动自检。"}
    - {pattern: "版本迁移逐级事务化", example_location: "memory/migrations.py:658-755", usage_guidance: "v14 新表必须有迁移、回滚和旧库测试。"}
    - {pattern: "空间合并单事务 + dry-run + 报告", example_location: "memory/space_merge.py:120-172", usage_guidance: "称呼冲突按 updated_at，并写报告。"}
  files_to_modify:
    - {file: "memory/addressing.py", symbols: ["new"], intended_change: "新增称呼偏好领域服务和校验。"}
    - {file: "memory/addressing_intent.py", symbols: ["new"], intended_change: "新增自然语言意图路由和结构化提取。"}
    - {file: "memory/schema.py", symbols: ["SCHEMA_VERSION", "new table DDL"], intended_change: "新增 v14 表定义。"}
    - {file: "memory/migrations.py", symbols: ["migrate_v14", "MIGRATIONS"], intended_change: "新增 v14 迁移。"}
    - {file: "memory/space_merge.py", symbols: ["merge_spaces"], intended_change: "合并称呼表并处理冲突。"}
    - {file: "config/settings.py", symbols: ["new settings"], intended_change: "增加称呼语义路由配置。"}
    - {file: "stella_project/plugins/bot_main/ai_gateway.py", symbols: ["new handler"], intended_change: "自然语言入口、权限、目标解析、handler 互斥。"}
    - {file: "core/context.py", symbols: ["ChatContext"], intended_change: "增加 preferred_address。"}
    - {file: "memory/pre_processors.py", symbols: ["build_user_context", "_build_user_context_v2"], intended_change: "读取当前明确目标用户的称呼。"}
    - {file: "memory/prompt_builder.py", symbols: ["build_prompt_context", "build_v2_prompt_context"], intended_change: "在稳定身份区安全注入称呼规则。"}
    - {file: "core/pipeline.py", symbols: ["Pipeline.run"], intended_change: "v1/v2 Prompt 传递字段，保持兼容。"}
    - {file: "tests/test_addressing.py", "symbols": ["new"], intended_change: "偏好服务测试。"}
    - {file: "tests/test_addressing_intent.py", "symbols": ["new"], intended_change: "embedding 和自然语言解析测试。"}
    - {file: "tests/test_addressing_handler.py", "symbols": ["new"], intended_change: "handler、权限和互斥测试。"}
    - {file: "tests/test_prompt_builder_v2.py", "symbols": ["existing"], "intended_change": "Prompt 稳定区和空值回归。"}
    - {file: "tests/test_pipeline_compose.py", "symbols": ["existing"], "intended_change": "管线顺序和单次 LLM 回归。"}
    - {file: "tests/test_embeddings.py", "symbols": ["existing"], "intended_change": "embedding 缓存/失败回归。"}
    - {file: "tests/capability/test_router_semantic.py", "symbols": ["existing"], "intended_change": "原型/margin 约定回归。"}
    - {file: "tests/test_proactive_at_flow.py", "symbols": ["existing"], "intended_change": "主动 @/群级主动发言边界回归。"}
    - {file: "tests/test_migrations.py", "symbols": ["existing"], "intended_change": "v14 迁移回归。"}
    - {file: "tests/test_space_merge.py", "symbols": ["existing"], "intended_change": "空间合并和冲突回归。"}
  tests:
    - {file: "tests/test_addressing.py", scenarios: ["设置/清除/查询 → 正确空间和用户行", "非法内容 → 拒绝且不写库", "重复设置 → updated_at/source/操作者正确"]}
    - {file: "tests/test_addressing_intent.py", scenarios: ["自然语言设置 → SET_SELF_ADDRESS", "普通聊天/引用 → NOT_ADDRESS_REQUEST", "embedding 失败 → 规则或普通聊天降级", "top-1 与 top-2 接近 → 澄清"]}
    - {file: "tests/test_addressing_handler.py", scenarios: ["自设 → block 普通聊天", "管理员代设 → 成功", "非管理员代设 → 拒绝", "@ segment → 目标 user_id 正确"]}
    - {file: "tests/test_prompt_builder_v2.py", scenarios: ["称呼在稳定身份段", "user_id=0/None 或未设置 → 不注入", "旧 positional 调用 → 输出兼容"]}
    - {file: "tests/test_proactive_at_flow.py", scenarios: ["主动 @ 目标可用称呼", "群级主动插话不使用称呼"]}
    - {file: "tests/test_migrations.py", scenarios: ["v13 → v14", "失败回滚", "重复迁移幂等", "新表为空且旧数据不变"]}
    - {file: "tests/test_space_merge.py", scenarios: ["新表空间归属改写", "updated_at 冲突选择", "报告/dry-run/备份保持"]}
  verification_commands:
    - "python -m pytest tests -q"
    - "ruff check ."
    - "node .gitnexus/run.cjs detect-changes --scope all --repo ."
  risks:
    - "Prompt builder 和 Pipeline.run 为 HIGH 影响符号，必须保持签名兼容和现有 Prompt 顺序。"
    - "自然语言误触发可能导致未授权状态改变，必须使用 embedding/规则/澄清/后端校验多层门控。"
    - "Embedding 与本地聊天共享 LM Studio 闸门，需关注延迟和缓存命中。"
    - "space_merge 的称呼冲突不能套用画像互动次数规则。"
  assumptions:
    - "Check that current OneBot event segments expose target @ users through get_message(); otherwise add a narrow adapter helper and tests."
    - "Check that ROLE_ROUTER backend can be reused for optional constrained extraction; if not, keep deterministic extraction plus clarification for v1."
    - "Check exact current migration validation table ownership before adding user_address_preferences."
  open_questions:
    - "是否允许管理员代设冒犯性称呼，以及是否需要敏感词策略。"
    - "是否需要私聊/跨群全局称呼；当前计划明确只支持共享空间级。"
    - "是否在第一期开放查询称呼的自然语言响应。"
  avoid:
    - "不要把关系性称呼写入 user_profiles.nickname 或普通 memory。"
    - "不要把称呼注册成会触发 Comes 的工具能力。"
    - "不要让 embedding 或 Chat LLM 直接执行数据库写入。"
    - "不要在群级主动发言中注入具体用户称呼。"
    - "不要新增独立 build_user_context hook。"
    - "不要绕过现有 EmbeddingService、缓存和 embedding_gate。"
    - "不要在执行阶段跳过每个既有共享符号的 impact 检查。"
```

## 12. Assumptions and Open Questions

### Assumptions

- [assumed] 当前消息入口仍要求 @ Stella；执行阶段确认是否需要支持不 @ 的私聊入口。
- [assumed] `ROLE_ROUTER` 可作为可选结构化提取后端；若验证不成立，v1 只使用确定性提取并在歧义时澄清。
- [assumed] 称呼偏好只按共享空间隔离，不提供跨空间全局继承。
- [verified] 当前 working tree 无 Git dirty path；provenance 中若 worktree digest 与 HEAD 不同，属于平台换行/过滤层差异，状态仍由 helper 判定为 clean。
- [verified] GitNexus index 当前与 HEAD 一致；PDG 不可用，实施阶段不能把缺失 PDG 当成没有数据/控制依赖。

### Open Questions

- [open] 管理员代设是否需要目标用户确认；本计划默认管理员可直接设置，但建议保留操作者审计字段。
- [open] 是否需要对称的“查看我的称呼”自然语言回复；不影响底层数据模型。
- [open] 称呼的最大长度和敏感词集合需结合 Stella 的内容治理策略最终确定。
- [deferred] 不在本任务中改造整个 capability semantic router 为通用分类框架；只复用其已验证的 embedding 模式。
- [deferred] 不在本任务中增加 GUI 配置页；第一期以群内自然语言和现有管理员权限为入口。

## 13. Definition of Done

1. 用户可以通过明确自然语言在当前共享空间设置、替换、清除自己的称呼，并获得自然确认。
2. 普通闲聊、引用、反问和低置信度表达不会自动改变称呼配置。
3. 管理员代设路径完成目标解析、权限校验和审计；普通用户无法修改他人。
4. 新表按 `(group_shared_space, user_id)` 隔离，v13 → v14 迁移幂等、可回滚并有旧库回归测试。
5. v1/v2 Prompt 只在明确目标用户时使用称呼；群级主动发言不使用具体用户称呼；主动 @ 目标用户可使用。
6. embedding 服务不可用时 Stella 主链路仍可工作，并有可观测的降级原因。
7. 空间合并迁移称呼数据，冲突按最终确定的显式更新时间规则处理并记录报告。
8. 定向测试、`python -m pytest tests -q`、`ruff check .` 和完整 GitNexus 变更检测通过。
