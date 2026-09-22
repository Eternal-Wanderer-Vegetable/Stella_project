# GitNexus 计划：Anthropic 风格 Skills 与受控沙盒执行

> **Evidence provenance schema:** 2  
> **Generated:** 2026-09-21  
> **Repository:** `E:\stella\stella_project`  
> **Indexed commit:** `1304f3cb579948c5199c039662a8eefc29d5048c`  
> **Scope:** 只覆盖 Anthropic 风格 Skills 与其受控沙盒执行；不扩展到本轮报告中的 MCP、知识库、WebUI、定时 Agent 或多平台改造。

## 1. Objective

[assumed] 为 Stella 增加与 Anthropic Skills 兼容的、可按需加载的任务技能机制，并把“沙盒执行”作为 Skill 脚本和代码操作的唯一受控执行边界。目标是让模型开始请求时只看到技能的名称、描述和有限元数据；命中技能后再读取 `SKILL.md`，并在明确授权的沙盒中运行脚本、读写工作区和返回受限产物。

[verified] `design_docs/AstrBot 特性吸收对比报告.md:67-81` 已确定 Skill 的核心形态为 `SKILL.md`、`scripts/`、`references/`，建议优先级为工作区 > 用户本地 > 插件内置 > 内置；`...:118-122` 要求沙盒先提供工作区、CPU/内存/时间限制、网络开关和输出大小限制，默认关闭且不能假设 Windows 支持 Linux 专有隔离工具。

[assumed] 第一版提供 Shell/Python/文件操作的沙盒适配器，浏览器和 CUA 只保留扩展点，不把桌面自动化和浏览器依赖带入首个交付面。失败必须退化为普通回复或结构化的 Skill 失败摘要，不得阻断主聊天链路。

## 2. Current Behaviour

[verified] 当前没有独立 Skills 目录发现、`SKILL.md` 解析、来源优先级合并或 Skill 结果载体。`CapabilityRegistry`（`capability/registry.py:217-530`）承载可路由能力和 Provider，`Capability`（`...:146-215`）要求可用 provider 才能进入路由；Skill 是“完成一类任务的说明书”，不应伪装成 Provider 或工具能力。

[verified] `capability/hooks.py:291-343` 的 `activate_capabilities` 先调用 Router，将 `route` 写入 `ChatContext`，再并行启动记忆检索和 Comes 工具执行；使用 `asyncio.gather(..., return_exceptions=True)` 隔离增量能力故障。Skill 接入应沿用这个故障隔离边界，且不能让正文、脚本输出直接进入主 Prompt。

[verified] `capability/comes/executor.py:310-469` 的 `execute` 对单个 `tool.execute` 任务执行能力查找、Provider 解析、直接调用或受限 Agent 调用、超时和摘要压缩；`Result.data` 不进主 Prompt，只有有界 `summary` 进入回复上下文。该约定可作为 Skill 结果的参考，但不应把 Skill 强行新增为 `TaskType` 或 Capability Provider。

[verified] `core/context.py:98-113` 已分别保存 `route`、`task_results`、`tool_summaries` 和 `knowledge_evidence`；`core/pipeline.py:40-124` 只把有界的工具摘要和独立知识证据渲染到 Prompt。Skills 应新增独立的候选、调用状态、摘要和产物引用字段，保持与个人记忆和知识证据的隔离。

[verified] `bot.py:231-310` 的 `_bootstrap_capabilities` 在 `initialize_plugins` 后同步 MCP、AstrBot 插件和知识能力，再后台预热 Router；`astrbot_compat/loader.py:617+` 负责插件初始化，`...:960-1074` 负责能力重建和热重载。Skill catalog 应在插件能力准备后建立，并在 `reload_plugin` 后按插件来源刷新。

[verified] 当前 `Dockerfile:17-76` 使用 Python 3.12-slim、非 root 的 `stella` 用户和可写 `/data` 数据卷；`docker-compose.yml:19-53` 只编排 Stella 服务，没有沙盒服务，也没有 Docker socket 挂载。因此现有 Docker 运行时是应用容器边界，尚不是按调用创建的 Skill 沙盒。

[verified] `config/settings.py:962-999` 的插件目录和热重载默认安全关闭，`...:1362-1391` 已有 Comes 的步骤、单工具超时、总超时和摘要上限配置；`memory/embeddings.py:102-150` 提供带缓存、超时和失败降级的 `EmbeddingService`，可复用于 Skill 摘要匹配但必须使用独立缓存命名空间。

## 3. Relevant Architecture

[verified] 当前主链路可抽象为：

```text
message -> capability.router.route -> ChatContext.route
                                      ├─ memory retrieval
                                      └─ Comes -> CapabilityRegistry -> Provider -> tool
                                   -> Pipeline -> bounded summaries -> LLM reply
```

[inferred] Skill 应形成旁路但受同一主链路治理的流程：

```text
message
  -> SkillCatalog (metadata only; precedence merge)
  -> SkillSelector (local match, optional embeddings, budget)
  -> SkillInvocation (lazy SKILL.md load, source/trust policy)
  -> SkillOrchestrator / SkillAgent
  -> SandboxExecutor (disabled | docker; bounded workspace)
  -> SkillResult (summary + artifact refs + audit id)
  -> ChatContext.skill_summaries / skill_artifacts
  -> Pipeline (bounded rendering only)
```

[inferred] 关键边界如下：

- `SkillCatalog` 只负责发现、解析和合并元数据；不读取正文和脚本，不注册 `CapabilityRegistry`。
- `SkillSelector` 只消费名称、描述和可选示例，返回有限候选；正文命中后才由调用编排器加载。
- `SkillOrchestrator` 负责一次调用的预算、正文加载、工具范围和结果压缩；它可以复用插件角色模型，但不能复用 Stella 人格或记忆上下文。
- `SandboxExecutor` 是协议接口。首个实现以 Docker 受限容器为主，`DisabledSandboxExecutor` 为默认后端；宿主平台差异由后端能力探测处理，Windows 不直接依赖 `bubblewrap`。
- `Pipeline` 只接收摘要和产物引用，不接收完整 `SKILL.md`、原始 stdout/stderr、任意脚本内容或未压缩文件。

## 4. GitNexus Findings

[graph] 本次在 Docker 中用 GitNexus 1.6.12 刷新了当前分支索引（`--index-only --pdg`）：48,443 nodes、115,224 edges、612 clusters、669 processes，索引提交为 `1304f3cb579948c5199c039662a8eefc29d5048c`。索引位于 `.gitnexus`，生产代码未改动。

[graph] `CapabilityRegistry` 精确命中 `capability/registry.py:217-530`，上游影响 31 个符号（direct 23、depth-2 6、depth-3 2），风险 `HIGH`。它是工具路由中心，Skill 设计必须绕开它，避免把“技能说明”误当成可执行 Provider。

[graph] `activate_capabilities` 精确命中 `capability/hooks.py:291-343`；符号影响结果为 `UNKNOWN`，因为 hook 注册和动态调用未完全解析。源码确认它是主聊天增量能力入口，任何修改都必须保留异常吞掉、记忆与工具并行、`return_exceptions=True` 的行为。

[graph] `execute` 精确命中 `capability/comes/executor.py:310-469`；上游影响为 direct 1、depth-2 1、depth-3 1，结果是 lower-bound，索引报告 3 个 receiver 未解析的调用点。计划不直接修改该执行器，只借鉴其 Result、超时、摘要和健康度约定。

[graph] `Pipeline` 精确命中 `core/pipeline.py:127-350`，上游影响 6 个文件（direct 3、depth-2 2、depth-3 1），风险 `LOW`；但它被多个扩展和 Bot 入口导入，因此 Skill 结果渲染必须保持有界和可选，不改写现有工具/知识证据语义。

[graph] `ChatContext` 上游影响 10 个符号（direct 6、depth-2 3、depth-3 1），风险 `MEDIUM`；新增字段要使用默认值、保持旧调用方可构造，并避免把 Skill 类型导入 `core` 造成依赖环。

[graph] 语义查询因 GitNexus DuckDB FTS 扩展在 Docker 镜像中不可用而降级；本计划的概念结论以直接 `context`/`impact`、PDG 结果和源代码核对为准，不把空的 FTS 查询当作“没有调用方”。

## 5. Statement-Level PDG Findings

[graph] 新索引对 `capability/hooks.py:activate_capabilities` 从可执行行 300 做了上游 PDG 切片，得到函数自身的 owner projection；它没有解析出动态 hook 注册者。结合源码，`route`、`ctx.route`、`jobs`、`asyncio.gather` 是 Skill 接入必须保留的控制和数据流节点。

[graph] 新索引对 `capability/comes/executor.py:execute` 从行 336（`reg.get(task.capability)`）做 PDG 切片，覆盖函数入口、`COMES_ENABLED`、`event is None` 等 4 个局部语句，并通过 callgraph bridge 到 `capability/comes/__init__.py:execute_all`、`capability/hooks.py:_run_comes` 和 `activate_capabilities`；跨过程结论是 lower-bound，且明确有 3 个未解析 receiver 调用点。

[graph] 对 `Pipeline` 行 55 的切片没有对应 executable block，但 callgraph bridge 精确显示 `extensions`、`ai_gateway`、`status_api` 和 `bot.py` 的导入链。实现时不把 Skill 正文注入 `Pipeline` 早期 prompt 组装点，改为在现有摘要渲染边界追加有界字段。

[inferred] 由上述 PDG 和源码可得：Skill 选择可以在 `activate_capabilities` 前后作为独立阶段，但调用结果必须走与 Comes 相同的故障隔离；沙盒执行器不应被塞进 `CapabilityRegistry` 的 Provider 图，也不应通过修改通用 `TaskGraph` 扩大影响面。

## 6. Proposed Changes

### 6.1 Skill 数据模型、发现与优先级

[proposed] 新增 `skills/model.py`，定义 `SkillManifest`、`SkillSource`、`SkillCandidate`、`SkillInvocation`、`SkillResult` 和 `ArtifactRef`。模型只保存规范化相对路径、名称、描述、来源层、信任等级、文件大小/摘要哈希和可选目录能力，不持有任意可执行对象。

[proposed] 新增 `skills/discovery.py` 与 `skills/catalog.py`：

1. 扫描 `STELLA_HOME/data/skills/<name>/SKILL.md` 的用户技能、插件目录下的 `skills/<name>/SKILL.md`、当前会话 workspace 下的 `skills/<name>/SKILL.md`，以及仓库内受控 builtin 目录。
2. 复用 `astrbot_compat.loader._plugin_dir_of` 的插件目录解析语义；插件卸载/重载后只刷新该插件来源。
3. 只解析 `SKILL.md` 的有限 front matter（最小必需字段 `name`、`description`）和目录索引，不在启动/匹配阶段读完整正文、脚本和 references。由于当前依赖没有 PyYAML，先选择受限标量解析或显式引入并锁定一个 front matter 依赖；禁止为了方便把任意 YAML 对象执行或展开到配置。
4. 验证名称、目录边界、大小、编码、重复项和符号链接；无效技能被隔离记录并继续启动。
5. 合并优先级固定为 `workspace > user > plugin > builtin`。同层冲突按确定性路径排序，重载必须原子替换 catalog 快照，旧快照继续服务正在进行的请求。

[proposed] `skills/loader.py` 在选中后才读取 `SKILL.md` 正文，并提供 `references/`、`scripts/` 的受限索引。正文和资源都要有单次读取上限、总字节上限、禁止 `..`/绝对路径/越界 symlink 的校验；正文作为不可信指令传给 Skill Agent，不能改变沙盒安全策略。

### 6.2 选择器与主链路接入

[proposed] 新增 `skills/selector.py`。先做确定性关键词/名称描述匹配，再在开启 embedding 时复用 `EmbeddingService`，但缓存键增加 `skills:<catalog_version>:<model>:<dim>:<sha256>` 前缀，避免污染 Router 原型缓存。Selector 输出前 `K` 个候选和匹配理由，带最大描述字符数和 token 预算；无命中、超时或 embedding 失败均返回空候选。

[proposed] 在 Router 结果或 `ChatContext` 中增加可选 `skill_candidates`，推荐优先扩展 `Route` 的非破坏性字段并由 `activate_capabilities` 负责填充；不要把 Skill 注册成 `Capability`。候选只包含名称、描述、来源、信任级别和目录摘要，不含正文。

[proposed] 在 `capability/hooks.py` 增加独立 `_run_skills` 分支，并沿用 `asyncio.gather(..., return_exceptions=True)`。当 `SKILLS_ENABLED` 关闭、没有候选、Skill 执行模式为 `disabled` 或无沙盒后端时，该分支立即返回；记忆、Comes 和 Skill 任一分支异常不得阻止 Pipeline 生成回复。

### 6.3 Skill 编排与结果契约

[proposed] 新增 `skills/orchestrator.py`，为每次命中创建 `SkillInvocation`：唯一调用 ID、会话/工作区 ID、Skill 版本摘要、来源、允许动作、总超时和最大输出。它按需加载正文，再把“任务目标 + Skill 正文 + 有限参考索引 + 允许的沙盒工具 schema”交给专用 Skill Agent；不得附带 Stella 人格、长期记忆候选或完整工具注册表。

[proposed] Agent 只能请求抽象的 `run_shell`、`run_python`、`read_file`、`write_file`、`list_files` 等沙盒操作。脚本路径必须相对当前 Skill 根目录或 workspace；所有执行经过 `SandboxExecutor`，不允许直接 `subprocess`、`eval`、`exec` 或导入宿主插件。

[proposed] `SkillResult` 只允许 `status`、有界 `summary`、结构化 metrics、`ArtifactRef` 和 audit ID；原始 stdout/stderr 留在沙盒审计存储，默认不进主 Prompt。Pipeline 可像 `_tool_result_section` 一样追加不超过配置上限的摘要和下载/预览引用；不能把 `knowledge_evidence` 混入个人记忆。

### 6.4 受控沙盒执行层

[proposed] 新增 `skills/sandbox.py` 定义 `SandboxExecutor` 协议、`SandboxSpec`、`SandboxLimits`、`SandboxResult` 和能力探测；实现 `DisabledSandboxExecutor` 与 `DockerSandboxExecutor`。后端创建失败、Docker 不可用、平台不支持或策略拒绝时返回可诊断的 `sandbox_unavailable`，不回退到宿主任意代码执行。

[proposed] Docker v1 的每次调用约束如下：

- 为会话/调用创建 `STELLA_HOME/workspaces/<normalized_session>/<invocation_id>`，只挂载为容器 `/workspace`；Skill 源和 references 只读挂载或受控复制，禁止挂载项目根目录、`.env`、记忆数据库、插件目录、Docker socket 或宿主用户目录。
- 使用非 root 镜像、只读 root filesystem、`no-new-privileges`、丢弃 Linux capabilities、受限 PID 数和临时 writable workdir；容器退出后清理临时层。
- CPU、内存、进程数、墙钟时间、单次 stdout/stderr 和总产物大小均来自 `SandboxLimits`，默认采用报告要求的保守值，且必须由调用上下文的更小预算覆盖；超限主动终止并记录原因。
- 默认 `network=false`；开启网络时仅允许显式域名/端口 allowlist，并在审计记录里保存策略版本。不得把 `network=true` 作为 Skill 自己的 front matter 权限。
- 将 Shell/Python/文件操作映射到容器内 `/workspace`，采用 POSIX/Windows 无关的相对路径协议；前端只看 workspace 相对路径。浏览器和 CUA 通过后续 `SandboxCapability` 适配器加入，不在 Docker v1 中隐式启用。

[proposed] 运行时配置增加 `SKILLS_ENABLED`、`SKILLS_EXECUTION_MODE`（`disabled|sandbox`，默认 `disabled`）、`SKILLS_MAX_CANDIDATES`、`SKILLS_BODY_MAX_CHARS`、`SKILLS_TOTAL_TIMEOUT`、`SKILLS_OUTPUT_MAX_CHARS`、`SANDBOX_BACKEND`、`SANDBOX_CPU_LIMIT`、`SANDBOX_MEMORY_LIMIT`、`SANDBOX_TIMEOUT`、`SANDBOX_NETWORK_ENABLED`、`SANDBOX_NETWORK_ALLOWLIST`、`SANDBOX_WORKSPACE_ROOT` 和审计保留配置。沙盒默认关闭；配置校验拒绝负数、不合法路径和 `network=true` 但无 allowlist 的组合。

[proposed] Docker 部署先增加可选的 sandbox runner 边界或显式配置的 Docker API 代理，不把 `/var/run/docker.sock` 直接给 Stella。若部署环境不能提供安全的 runner，Skill 仍可浏览 metadata/正文但脚本调用必须失败关闭。Windows 本地运行优先使用同一协议的远程/sidecar runner，不根据 OS 名称猜测 Linux 隔离设施。

### 6.5 生命周期、热重载、可观测性和文档

[proposed] 在 `bot._bootstrap_capabilities` 的插件能力准备之后创建初始 catalog，并在 Router warmup 前完成一次 metadata snapshot；在 `astrbot_compat.loader.reload_plugin` 的能力重建旁刷新受影响插件的 Skills。刷新失败保留上一版 catalog，并写入诊断状态。

[proposed] 为每次发现、选择、加载、策略拒绝、沙盒启动、超时、输出截断和产物清理记录结构化 audit event；敏感参数、环境变量值、Skill 正文和 API key 必须脱敏。状态 API 只返回数量、来源、后端状态、最近失败计数和策略摘要。

[proposed] 更新 `docs/configuration.md`、`docs/architecture.md`、Docker 部署文档和 Skill 编写指南：说明目录布局、优先级、管理员开关、默认关闭的执行模式、Docker runner 安装、Windows 限制、失败行为和产物生命周期；提供一个只读文档处理示例和一个拒绝任意宿主命令的安全示例。

### 6.6 保持的边界

[verified] 不修改 `CapabilityRegistry` 的 Provider 合并和 `routable()` 语义；不把 Skill 新增到 `core.tasks.TaskType`；不改变个人记忆、知识证据和 Comes 的结果协议；不把所有 Skill/MCP 全文塞入人格 Prompt；不启用本地任意代码执行。

## 7. Implementation Sequence

1. **契约与配置**：落地 `SkillManifest`、`SkillCandidate`、`SkillInvocation`、`SkillResult`、`SandboxSpec`、`SandboxLimits`，增加默认关闭的配置和错误枚举；先建立单测夹具。
2. **发现与 catalog**：实现四层扫描、受限 front matter 解析、路径/符号链接/大小校验、优先级合并和原子快照；加入用户、插件、builtin、workspace 的最小样例。
3. **选择与延迟加载**：实现确定性选择、可选 embedding、独立缓存、候选预算和命中后正文加载；验证未命中时不读正文/scripts/references。
4. **编排与上下文**：实现 `SkillOrchestrator` 和结果契约，在 `ChatContext` 增加默认空的 Skill 字段，在 `activate_capabilities` 接入独立分支并保持主链路故障隔离。
5. **沙盒协议与禁用后端**：先实现策略校验、审计事件和 `DisabledSandboxExecutor`，确保没有后端时不会偷偷使用宿主 `subprocess`。
6. **Docker runner**：实现非 root、只读 root、无 socket、无网络默认、workspace 挂载、资源/输出限制、超时终止和清理；增加可选 Docker 集成测试与无 Docker 的降级测试。
7. **插件生命周期与部署**：接入 bootstrap、plugin reload 和状态 API；补充 Docker Compose/runner 文档，不改变默认 Stella 单容器拓扑，除非显式启用 runner。
8. **安全回归与灰度**：跑完整 Skills/Sandbox/Capability/Pipeline 回归；在测试部署开启 sandbox，检查 audit、资源回收、路径隔离和失败降级后再考虑打开生产开关。

## 8. Test Strategy

[proposed] 新增 `tests/skills/`、`tests/sandbox/`，并扩展现有 capability/pipeline/hot-reload 测试：

- catalog：四层优先级、同名覆盖、插件重载局部刷新、非法名称、缺失/重复 front matter、UTF-8、超大文件、越界 symlink、确定性排序。
- lazy loading：启动和选择只读取 manifest；命中后才读取正文；references/scripts 不可越界；正文和脚本上限生效。
- selector：关键词命中、embedding 可用/失败/超时、缓存隔离、候选数量和字符预算；无命中不启动 Agent。
- orchestration：Skill Agent 不接收 Stella 记忆和完整工具表；只允许声明的沙盒动作；`SkillResult` 摘要有界，原始输出不进入 Pipeline；Skill 失败不影响 memory/Comes/reply。
- sandbox policy：默认关闭、无 runner、无 Docker、network 默认拒绝、allowlist 校验、CPU/内存/TTL/PID/输出限制、超时杀进程、容器退出清理、只读源和 workspace 相对路径。
- Docker integration：以 marker/CI 条件运行，验证非 root、不可访问 `/app` secrets、不可访问 Docker socket、网络开关和产物回收；Windows runner 走协议兼容测试，不依赖 Linux 工具。
- lifecycle：bootstrap 顺序、插件 reload 后技能可见性、刷新失败保留旧 snapshot、并发请求读取同一不可变 snapshot。
- regression：现有 `tests/capability/test_capability_hooks.py`、`tests/capability/test_comes_executor.py`、Router、`tests/test_context_budget.py`、`tests/test_pipeline_compose.py`、`tests/astrbot_compat/test_hot_reload.py` 全部通过；重点确保 `return_exceptions=True` 和知识证据隔离不变。

## 9. Risk and Impact Analysis

| 风险 | 证据 | 处理 |
|---|---|---|
| 把 Skill 错当成 Capability 导致路由/Provider 污染 | [graph] `CapabilityRegistry` HIGH，31 个上游影响 | 独立 `skills/` 包和 catalog；只向 Route/Context 传候选 metadata |
| 主链路被 Skill 阻塞 | [verified] hooks 使用并行分支和异常吞掉；PDG 覆盖 route/jobs/gather | 单独超时、`return_exceptions=True`、执行结果可选；无后端立即返回 |
| 任意宿主代码执行 | [verified] 报告要求默认关闭和权限/资源/审计；当前 Docker 无 per-call sandbox | 没有本地 fallback；Docker/远程 runner；不挂 socket；安全策略 fail-closed |
| Windows 隔离误判 | [verified] 报告明确不能假设 bubblewrap；AstrBot 文档区分运行时 | 后端能力探测和远程 runner；路径协议平台无关 |
| Prompt/context 爆炸 | [verified] Pipeline 只渲染有界摘要，Comes 结果已压缩 | metadata-only catalog、命中后延迟正文、摘要/产物引用上限 |
| 插件热重载留下旧技能 | [verified] loader reload 会拆除插件并重建 capability | immutable catalog snapshot、按插件来源刷新、刷新失败保留旧版本 |
| FTS/图索引低估影响 | [graph] FTS 不可用；execute PDG lower-bound 且有 3 个 unresolved receivers | 以源码核对为准；Skill 不改高风险 Registry；实现后再跑 fresh `detect_changes` 和 impact |
| 沙盒资源泄漏或产物失控 | [proposed] per-call workspace、TTL、限制和清理 | 审计所有创建/终止/清理事件；集成测试失败回收和最大产物 |

## 10. Files Expected to Change

[proposed] 预计新增：

- `skills/__init__.py`
- `skills/model.py`
- `skills/discovery.py`
- `skills/catalog.py`
- `skills/loader.py`
- `skills/selector.py`
- `skills/orchestrator.py`
- `skills/sandbox.py`
- `skills/runners/docker.py`
- `skills/audit.py`
- `tests/skills/*`
- `tests/sandbox/*`
- `docs/skills.md` 或同等 Skill 编写指南

[proposed] 预计修改：

- `core/context.py`：加入默认空的 Skill 候选/调用/摘要/产物字段。
- `capability/hooks.py`：加入独立 Skill 分支，保持主链路降级语义。
- `capability/router/types.py` 或等价 Route 定义：加入可选候选字段（若实现选择只放 Context，则不改此文件）。
- `bot.py`：bootstrap catalog 和 warmup 顺序。
- `astrbot_compat/loader.py`：插件 Skill 来源发现与 reload 刷新回调。
- `config/settings.py`、`.env.example`、`docs/configuration.md`：Skills/Sandbox 配置。
- `core/pipeline.py`：只追加有界 Skill 摘要/产物引用的渲染段，保持 knowledge evidence 分离。
- `Dockerfile`、`docker-compose.yml`、Docker 部署文档：仅在选择本地 Docker runner 交付时增加 runner/镜像或安全代理配置。

[proposed] 明确不预计修改：`capability/registry.py` 的 Provider 核心语义、`capability/comes/executor.py` 的现有工具执行协议、`core/tasks.py` 的 TaskType、memory 表结构和记忆提取/晋升逻辑。

## 11. Reusable Implementation Context

### GitNexus snapshot

下面的 JSON 是在生产代码未改动、Docker 刷新索引后，用 evidence-provenance schema 2 生成的原始快照。后续实现代理应在首次编辑前重新运行影响分析；若引用文件变化，应重新生成 provenance。

```json
{
  "schema_version": 2,
  "head_commit": "1304f3cb579948c5199c039662a8eefc29d5048c",
  "generated_plan_path": "docs/plans/2026-09-21-gitnexus-plan-anthropic-skills-sandbox.md",
  "global_dirty_digest": {
    "algorithm": "sha256",
    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
    "value": "ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf"
  },
  "cited_path_manifest": [
    {
      "path": "Dockerfile",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
      "index_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
      "worktree_digest": "sha256:4cec31dff9e5186477015cb7d43b0ed64599d94f1ba8be93307e711faf26e024",
      "untracked_digest": "absent"
    },
    {
      "path": "astrbot_compat/loader.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:76fb46c1421d101a4dafabf4f448df2d34cf8a86ac9059b4e963cb2e410e5b1a",
      "index_digest": "sha256:76fb46c1421d101a4dafabf4f448df2d34cf8a86ac9059b4e963cb2e410e5b1a",
      "worktree_digest": "sha256:76fb46c1421d101a4dafabf4f448df2d34cf8a86ac9059b4e963cb2e410e5b1a",
      "untracked_digest": "absent"
    },
    {
      "path": "bot.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:ca3a3555c340ce9133fea47d32122de924bdc70c6093305a55bd49b2de4acf37",
      "index_digest": "sha256:ca3a3555c340ce9133fea47d32122de924bdc70c6093305a55bd49b2de4acf37",
      "worktree_digest": "sha256:86a80bd0fefe8990442b7e9fd6d9558ed3dac3ee4fc8dc59293bc042196ef726",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/comes/__init__.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
      "index_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
      "worktree_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/comes/executor.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:0a86f86e19c8a212dc2aff6c2ee5cb72f13b2296e4dc5c18b4ff10f72ca0677d",
      "index_digest": "sha256:0a86f86e19c8a212dc2aff6c2ee5cb72f13b2296e4dc5c18b4ff10f72ca0677d",
      "worktree_digest": "sha256:0a86f86e19c8a212dc2aff6c2ee5cb72f13b2296e4dc5c18b4ff10f72ca0677d",
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
      "head_digest": "sha256:6662c64a130b4ce030ceff7847cc94f3209825630f042b4e5c875a6064278ea5",
      "index_digest": "sha256:6662c64a130b4ce030ceff7847cc94f3209825630f042b4e5c875a6064278ea5",
      "worktree_digest": "sha256:6662c64a130b4ce030ceff7847cc94f3209825630f042b4e5c875a6064278ea5",
      "untracked_digest": "absent"
    },
    {
      "path": "capability/registry.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:26a3f188656807b871faccd00a21eb246f8b0e0d9653dabfa3204c4edd29d6a9",
      "index_digest": "sha256:26a3f188656807b871faccd00a21eb246f8b0e0d9653dabfa3204c4edd29d6a9",
      "worktree_digest": "sha256:b4336ba0d6cb945a4c13d3cdbcdb9112ebced06ef5b3de89160b0f3c09f6a724",
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
      "head_digest": "sha256:d80898bb376a0ea9c41097e55640cb98b48f3b3bd8657e62fae88d2e63392c81",
      "index_digest": "sha256:d80898bb376a0ea9c41097e55640cb98b48f3b3bd8657e62fae88d2e63392c81",
      "worktree_digest": "sha256:e10e713ff0e1178e1a1f936d33b13e1279fe2f7557aef53f2a13b0176b894bc1",
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
      "head_digest": "sha256:e1b0a29521b996f7e5793d1e7a0b94748bdce8439f2f992ea57fd9e18f8a20a4",
      "index_digest": "sha256:e1b0a29521b996f7e5793d1e7a0b94748bdce8439f2f992ea57fd9e18f8a20a4",
      "worktree_digest": "sha256:f74734e103a42438c26038df44b4b2fe19a0ff7b5ae6829c484bd2523a16563a",
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
      "head_digest": "sha256:2b7fdebd5ba85ff6ddbfa5086629abd5bf9beffd21afb3c155a94b17627815a7",
      "index_digest": "sha256:2b7fdebd5ba85ff6ddbfa5086629abd5bf9beffd21afb3c155a94b17627815a7",
      "worktree_digest": "sha256:2b7fdebd5ba85ff6ddbfa5086629abd5bf9beffd21afb3c155a94b17627815a7",
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
      "head_digest": "sha256:b22250d1909f9afbfa27e91482e447ed225c36a6b433da1af5d722c71a3a1ac8",
      "index_digest": "sha256:b22250d1909f9afbfa27e91482e447ed225c36a6b433da1af5d722c71a3a1ac8",
      "worktree_digest": "sha256:08f3ac68d9a0f4359e050b71440f9a4c6c4aeb19f2fffcc60112da3492e93687",
      "untracked_digest": "absent"
    },
    {
      "path": "core/tasks.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:293c3172eb239663188e214e65eb7f20b83989c16e42f0e5fb4a6bba11e500d7",
      "index_digest": "sha256:293c3172eb239663188e214e65eb7f20b83989c16e42f0e5fb4a6bba11e500d7",
      "worktree_digest": "sha256:293c3172eb239663188e214e65eb7f20b83989c16e42f0e5fb4a6bba11e500d7",
      "untracked_digest": "absent"
    },
    {
      "path": "design_docs/AstrBot 特性吸收对比报告.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:bf9f7c7d9c4cc23190eb0291ab5e874236f3488e89175294248a048aa7637182",
      "index_digest": "sha256:bf9f7c7d9c4cc23190eb0291ab5e874236f3488e89175294248a048aa7637182",
      "worktree_digest": "sha256:bf9f7c7d9c4cc23190eb0291ab5e874236f3488e89175294248a048aa7637182",
      "untracked_digest": "absent"
    },
    {
      "path": "docker-compose.yml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:edd8054f3c860edbf2e6797794854476ba6ec35c4ca70284dbf9fd5b3abd5340",
      "index_digest": "sha256:edd8054f3c860edbf2e6797794854476ba6ec35c4ca70284dbf9fd5b3abd5340",
      "worktree_digest": "sha256:edd8054f3c860edbf2e6797794854476ba6ec35c4ca70284dbf9fd5b3abd5340",
      "untracked_digest": "absent"
    },
    {
      "path": "docs/configuration.md",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c35f78112a8403fd8dd3a0cfe356d057bf2c61ac079579f446c8da51719e3ddc",
      "index_digest": "sha256:c35f78112a8403fd8dd3a0cfe356d057bf2c61ac079579f446c8da51719e3ddc",
      "worktree_digest": "sha256:c317e72e9fd9269f5b8a574e4aef600a3708487ebdc6d0327f46020101b7277a",
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
      "head_digest": "sha256:8f323c85e94757fe79770b4b00f338fddae4281fece992e9ef412bce41194249",
      "index_digest": "sha256:8f323c85e94757fe79770b4b00f338fddae4281fece992e9ef412bce41194249",
      "worktree_digest": "sha256:a86890ec780696c5abc766183d21c79449837913c9c2bd7aede2a19c2c7d68a2",
      "untracked_digest": "absent"
    }
  ]
}

```

### Indexed graph facts

- [graph] GitNexus 1.6.12，commit `1304f3cb579948c5199c039662a8eefc29d5048c`，48,443 nodes、115,224 edges、612 clusters、669 processes，PDG 可用；FTS 扩展未安装，embedding 数为 0。
- [graph] `CapabilityRegistry`：HIGH，31 upstream impacted；`activate_capabilities`：UNKNOWN/dynamic hook；`execute`：lower-bound，3 个 receiver 未解析；`Pipeline`：6 个 upstream imports，风险 LOW；`ChatContext`：10 个 upstream，风险 MEDIUM。
- [graph] PDG `execute` 行 336 的局部影响覆盖入口、COMES gate 和 event gate，并桥接到 `execute_all -> _run_comes -> activate_capabilities`；这不是完整 receiver 闭包。

### External reference

- [verified] AstrBot Skills 文档说明名称/描述渐进披露、`data/skills/<name>/SKILL.md`、插件 Skills、workspace Skills 及来源优先级：[Anthropic Skills | AstrBot](https://docs.astrbot.app/use/skills.html)。
- [verified] AstrBot Agent Sandbox 文档说明 Shell/Python/文件系统/浏览器/CUA 运行时、Shipyard/Shipyard Neo/CUA、workspace、资源限制和运行时差异：[Agent 沙盒环境 | AstrBot](https://docs.astrbot.app/use/astrbot-agent-sandbox.html)。本计划只吸收“受控后端、workspace、资源/网络边界”的原则，首版不复制其全部驱动器。

## 12. Assumptions / Open Questions

1. [assumed] Python 支持范围继续为 `>=3.10`；需要在实现前决定采用受限 front matter 解析还是新增一个经过锁定的依赖，不能依赖开发机偶然存在的 PyYAML。
2. [assumed] 首版执行模式只有 `disabled` 和 `sandbox`；是否提供管理员专用 `local-read-only` 需要单独安全评审，不能作为默认或静默回退。
3. [assumed] 生产 Docker 部署能提供安全的 sidecar/remote Docker runner；若不能，交付 catalog、选择和正文预览，执行保持关闭。
4. [assumed] 工作区身份由现有会话/UMO 规范化得到；需要确认 workspace 生命周期、磁盘配额、并发调用上限和用户下载产物的 API。
5. [assumed] Skill 来源是否允许第三方插件和 workspace 默认参与选择，需要在配置中提供 source allowlist/trust policy；同名覆盖规则固定但是否允许 workspace 覆盖管理员禁用项需产品确认。
6. [assumed] 浏览器/CUA、长期运行 sandbox、跨会话文件和在线 Skill 安装不属于本次实现；它们只在 `SandboxCapability` 和目录协议中预留接口。
7. [assumed] 实现完成后必须在 fresh index 上运行 `detect_changes --scope all`、重新 impact 受影响符号并运行完整回归；任何 HIGH/CRITICAL 新风险都要先处理。

## 13. Definition of Done

- [ ] Skills 四层来源可发现，`SKILL.md` 最小 metadata 校验和同名优先级行为有测试和文档。
- [ ] 启动/匹配阶段只读 metadata；只有命中后才读取正文和 references/scripts，并有大小、路径和 symlink 防护。
- [ ] Skill 不进入 CapabilityRegistry Provider 图；候选、调用、摘要和产物在 ChatContext 中有默认值且与 memory/knowledge evidence 隔离。
- [ ] Skill Agent 使用独立预算和允许动作；原始脚本输出不进入主 Prompt，主链路只接收有界摘要/ArtifactRef。
- [ ] 沙盒默认关闭；没有安全 runner 时 fail-closed，绝不偷偷在宿主执行任意代码。
- [ ] Docker runner（若当前交付目标包含它）验证非 root、workspace-only mount、网络默认关闭、CPU/内存/时间/PID/输出限制、超时终止、审计和清理；Windows 不依赖 Linux 专有隔离工具。
- [ ] 插件 bootstrap、热重载、并发快照和失败保留旧版本均有测试；状态/审计不泄露正文、密钥或环境变量。
- [ ] 现有 capability、Comes、Router、Pipeline、memory 和 hot-reload 回归通过。
- [ ] GitNexus fresh index、impact、PDG/源代码核对和 `detect_changes` 完成；计划中记录的风险与实际变更一致。


