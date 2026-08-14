# Stella

Stella 是一个面向私有部署、以 QQ 群聊为场景的记忆型聊天机器人。当前版本已把“本地小模型接入记忆处理流程”作为核心能力之一，支持在聊天、短期摘要、长期记忆提取、记忆压缩以及 SQLite FTS5 检索增强生成（RAG）等环节中使用本地模型。

## 项目定位

当前系统的目标不是单纯做聊天回复，而是把群聊中的信息转成可持续使用的“记忆”，从而实现：

- 记录群聊上下文与用户特征
- 在对话时引用近期摘要、用户画像与长期记忆
- 利用本地小模型完成记忆候选生成、短期总结与压缩
- 通过 SQLite（含 FTS5 全文索引）持久化保存记忆与调试信息
- 用检索增强生成（RAG）提升“相关记忆”的命中质量

## 当前能力概览

- `@Bot` 触发的群聊问答
- 本地 LM Studio 模型作为主聊天后端
- 本地小模型参与短期记忆总结、记忆候选生成与记忆压缩
- 记忆整合统一走本地 LM Studio（在线整合已废弃，归档于 `_deprecated/`）
- 两层记忆过滤：捕获层宽（允许不确定信息进入候选，如实标注置信度）、晋升层严（Gate 1 三档 + 交叉验证 + 每用户配额）
- 候选强化：同一事实反复被观察时累积证据（`occurrence_count` / 置信度增益 / 来源集合），而非重复插入；超期未获新证据的候选自动淘汰
- 消息来源分级：`AT_MENTION`（用户直接对 Bot 说）视为高密度证据，单次即可晋升；`PASSIVE`（被动摄入群聊）需要复现才能晋升
- 每用户记忆配额：单用户 active 记忆封顶，超额时竞争性淘汰最弱记忆（默认关闭，先观察）
- 基于群聊活跃度的主动发言
- 支持 Pipeline 前后置 Hook 扩展
- SQLite 持久化、思考日志与记忆压缩日志
- SQLite FTS5 记忆全文索引 + 关键词/权重综合排序的 RAG 检索（可开关）
- 可选的 embedding 语义检索（本地 `/v1/embeddings`，失败自动回退规则版）
- pytest 自动化测试覆盖记忆晋升、跨用户隔离、候选强化、FTS 索引同步与 RAG 开关行为

## 项目结构

```text
stella_project/
├── bot.py                         # NoneBot 启动入口
├── pyproject.toml                 # Python 依赖、NoneBot 配置、ruff/pyright 规则
├── config/
│   └── settings.py                # 集中配置：群聊限制、LM Studio、RAG 开关、记忆压缩阈值等
├── core/
│   ├── context.py                 # ChatContext 数据结构
│   ├── pipeline.py                # Pipeline 编排器，串联 pre/post hooks 与 LLM 调用
│   └── llm/
│       ├── base.py                # LLM 后端抽象接口
│       └── lm_studio.py           # LM Studio 本地模型后端
├── extensions/
│   └── __init__.py                # 扩展自动加载入口（扫描 setup(pipeline)）
├── memory/
│   ├── SYSTEM.md                  # 机器人系统提示词
│   ├── schema.py                  # Schema 迁移（Additive，当前 v4）
│   ├── text_similarity.py         # 内容相似度与合并（单一真相源，三处共用）
│   ├── consolidator.py            # 记忆整合与候选写入（含 checkpoint、候选强化）
│   ├── memory_manager.py          # 候选晋升：Gate 1 三档、配额淘汰、FTS 同步
│   ├── policy.py                  # Memory Policy：Mode 检测、三层过滤、排序、Gate 3 校验
│   ├── retrieval_v2.py            # v2 检索（Context-aware Memory Activation）
│   ├── retriever.py               # 旧检索：RAG(FTS5) + 加权回退排序
│   ├── embeddings.py              # 本地 embedding 服务客户端（可选语义分）
│   ├── compressor.py              # 记忆压缩与轻量/周度压缩调度
│   ├── benchmark.py               # Memory Benchmark 运行器（Evaluation & Debug）
│   ├── benchmark/                 # 检索层用例 + _fixtures（含整合正例回归基准）
│   ├── trace.py                   # 记忆决策追踪
│   ├── pre_processors.py          # 记录消息（含来源标记）、构造短期/用户上下文
│   ├── post_processors.py         # 解析回复、过滤破防语句、分行输出与日志
│   ├── proactive.py               # 主动发言概率与冷却控制
│   ├── prompt_builder.py          # 把记忆与上下文拼成自然语言 Prompt
│   ├── consolidation_prompt.py    # 整合任务 JSON 输出模板
│   ├── consolidation_log.py       # 整合日志追加
│   └── db_cleaner.py              # 清理测试期脏数据 + 消息表定时裁剪
├── stella_project/plugins/bot_main/
│   ├── ai_gateway.py              # QQ 事件监听、Pipeline 接入、主动发言与调度
│   ├── watchdog.py                # NapCat 看门狗（消息流中断自动重启）
│   └── config.py                  # 插件配置（pydantic）
├── scripts/
│   ├── probe_consolidation.py     # 整合探针：跑生产链路观察 LLM 行为 / 正例回归基准
│   ├── sample_windows.py          # 从真实库采样消息窗口
│   ├── probe_embedding.py         # embedding 服务探针
│   └── build_embedding_fixture.py # 构建 benchmark 用向量 fixture
├── tests/                         # pytest 测试（记忆晋升、FTS 同步、RAG 开关、全流程端到端）
└── _deprecated/                   # 废弃/历史代码与旧数据库归档（gitignore）
```

## 当前工作流程

### 1. 消息接收与落库

群消息进入系统后，先由监听器记录到 SQLite（`group_messages` 表）。这样后续的摘要、检索与记忆整合都能基于真实历史进行。

### 2. 触发路径

- `@Bot` 回复：在允许群中 @机器人时，触发完整的上下文构建与回复生成。
- 主动发言：当群聊活跃度低、间隔较大时，以低概率自然插话。

### 3. 上下文构建与 RAG 检索

生成回复前，系统按顺序加载：

1. 短期上下文：最近的群聊摘要或原始消息回退
2. 用户画像：与当前用户相关的长期偏好、态度等描述
3. 长期记忆：与当前用户或当前群相关的重要摘要（带用户消息作为 query 触发 RAG）
4. 相关记忆：基于关键词相关度补充的额外历史记忆

`memory/retriever.py` 的检索逻辑：

- 若开启 `RAG_ENABLED` 且 `RAG_SQLITE_FTS_ENABLED`：先走 FTS5 全文索引（`bm25` 排序，`RAG_TOP_K` 控制候选池下限）；
- 索引与 `memories` 表行数不一致时会自动全量重建；
- FTS 无命中或开关关闭时，回退到“关键词重叠 + 近期度衰减 + 重要度 + 置信度 + 用户相关性”的多维加权排序（`get_group_memories` / `get_user_memories` 均适用）。

这些内容通过 `memory/pre_processors.py` 和 `memory/prompt_builder.py` 组织成结构化 Prompt。

### 4. LLM 调用

主聊天路径使用 LM Studio 的本地模型：

- 通过 `core/llm/lm_studio.py` 发起 OpenAI-compatible 请求
- 同一进程内使用异步锁保证不会同时打爆本地模型
- 回复结果由 `memory/post_processors.py` 进行解析与清洗

记忆整合统一使用本地 LM Studio 的小模型进行小批量处理，与主聊天模型分离，且使用全CPU推理，避免显存/推理竞争。

### 5. 记忆写入与晋升（两层过滤）

- **捕获层（宽）**：整合阶段产出短期摘要、用户画像与记忆候选。这一层不做置信度。不确定的信息也允许进入候选，但必须如实标注 `confidence`，且严禁编造；候选必须有出处、归属必须是消息的实际发送者（代码层还有发送者白名单兜底）。

> 理由：在 prompt 里过滤不可审计、不留数据、无法改进。把判断推迟到有数据的一层。

- **候选强化（交叉验证）**：`memory/consolidator.py` 写入候选时，同群同用户同类型且内容相似的待处理候选不重复插入，而是累积证据——`occurrence_count` +1、置信度加`MEMORY_CANDIDATE_REOCCURRENCE_BONUS`、`source_kinds` 取并集、状态回到 `NEW`，重新参与评估。超过 `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS` 仍未获新证据的候选标记`REJECTED`（不删除，保留供审计）。

- **晋升层（严）**：`memory/memory_manager.py` 的 Gate 1 三档：

| 置信度 | 判定 |
|---|---|
| ≥ `MEMORY_CONFIRM_HIGH_CONFIDENCE`(0.85) | 直接晋升 |
| ≥ `MEMORY_OBSERVE_LOW_CONFIDENCE`(0.6) | 看证据充分度：历次来源含 `AT_MENTION` → 晋升；`occurrence_count` 达标 → 晋升；否则 `OBSERVING` |
| < 0.6 | `OBSERVING`，等更多证据 |

另设 `importance` 下限（`MEMORY_PROMOTE_MIN_IMPORTANCE`）淘汰过于琐碎的信息。`importance` 由 LLM 自评、可靠性最低，因此不单独构成晋升依据。

晋升时与同群同用户同类型的相似记忆合并（跨用户合并会造成不可恢复的归属污染，`memory_manager` / `compressor` / `retrieval_v2` 三处合并路径都必须按归属过滤），并同步维护 FTS5 索引。

- -配额（呈现层封顶）-：新建记忆后检查该群该用户的 active 记忆是否超过`MEMORY_USER_QUOTA`，超额时按「重要度 × 确认次数 × 近期访问」竞争性淘汰最弱者（置 `archived`，不删除）。`MEMORY_QUOTA_ENFORCE` 默认关闭，先以 dry-run 观察它想淘汰什么。

### 6. 记忆压缩

- 轻量压缩：在候选记忆处理后按条件触发，用于小规模去重和原子化
- 周度压缩：在后台任务中执行更重的全量压缩

压缩结果写入压缩日志与统计表，便于观察记忆系统的演化过程。

## 测试

项目使用 pytest：

```bash
python -m pytest tests -q
# 覆盖率（目标 ≥ 80%）
python -m pytest tests --cov=core --cov=memory --cov-report=term -q
```

覆盖内容：

- 记忆候选晋升 / 观察（`tests/test_memory_manager.py`）
- FTS 索引与 `memories` 表完全同步、过期索引自动重建（`tests/test_memory_manager_fts_sync.py`）
- RAG 开关（`RAG_ENABLED` / `RAG_SQLITE_FTS_ENABLED` / `RAG_TOP_K`）的开关组合行为（`tests/test_rag_switches.py`）
- 检索排序与回退（`tests/test_retriever.py`）
- 短期记忆说话人归属（`tests/test_short_term_attribution.py`）
- 全流程端到端：消息入库 → 上下文构建 → Pipeline 编排 → 输出解析/分行 → 整合 → 记忆晋升 + FTS（`tests/test_full_workflow.py`，全程 Dummy LLM、不触网）
- 记忆策略 / 准入过滤 / 约束拆分（`tests/test_policy.py`、`tests/test_proactive_rules.py`、`tests/test_prompt_builder_v2.py`）
- v2 记忆检索与分布式 Schema（`tests/test_retrieval_v2_and_schema.py`）
- 决策追踪、内存评估基准、整合日志（`tests/test_trace.py`、`tests/test_benchmark_and_log.py`）
- 记忆整合私有流程与越权候选隔离（`tests/test_consolidator_core.py`）
- 压缩器（OpenAI / Ollama / Gemini）、DB 清理、LM Studio 客户端（`tests/test_compressor.py`、`tests/test_db_cleaner.py`、`tests/test_lm_studio.py`）
- 跨用户记忆隔离：候选晋升 / 周度压缩 / v2 检索三条合并路径都不得跨用户（`tests/test_cross_user_isolation.py`）
- 候选强化与 Gate 1 三档：累积证据、来源分级、超期淘汰、配额竞争（`tests/test_candidate_reinforcement.py`）
- 整合 prompt 的防编造条款护栏（`tests/test_consolidation_prompt.py`）
- 内容相似度与合并的行为基线（`tests/test_text_similarity.py`）

整合链路的模型侧验证不走 pytest（需要真实本地模型），用探针脚本：

```shell
# 正例回归基准：验证「该记的时候记得住」，改动 consolidation_prompt.py 后必须仍全绿
python scripts/probe_consolidation.py --positive --repeat 3
# 真实窗口观察：看编造率（目标 ≈ 0）与解析成功率
python scripts/probe_consolidation.py --limit 20
```

CI 采用最小化配置（`.github/workflows/ci.yml`）：Ubuntu 上按 `requirements.txt` 安装全部运行依赖（nonebot2 / onebot 适配器 / apscheduler 插件 / httpx / dotenv / pydantic）+ pytest，然后 `pytest tests -q`；所有测试均使用临时 DB 与伪 LLM 后端，不依赖真实机器人、网络或 LM Studio 服务。

## 运行方式

### 依赖

- Python 3.10+
- NoneBot 2
- OneBot V11 兼容适配器，如 NapCat
- LM Studio 本地模型服务

### 启动步骤

1. 启动 LM Studio 并确保 `/v1/chat/completions` 可访问
2. 启动 OneBot V11 适配器并完成连接
3. 在项目根目录运行：

```bash
python bot.py
```

### 旧数据库迁移说明

```markdown
为避免新旧表结构冲突与历史脏数据干扰观察，每次大重构后运行时数据库都会归档：

- `_deprecated/legacy_agent_memory.db`：早期版运行库
- `_deprecated/legacy_agent_memory_2026.db`：v2 schema 升级前的运行库
- `_deprecated/legacy_agent_memory_pre_v4.db`：两层过滤重构（Gate 1 三档 / 候选强化 /
  配额）之前的运行库

启动时会按当前 schema（v4）在 `memory/` 下自动重建新库。
```

## 配置说明

核心配置位于 [config/settings.py](config/settings.py)，敏感值与机器相关项（群号、令牌、路径）一律从 `.env` 读取，模板见 [.env.example](.env.example)，`settings.py` 中的默认值仅作兜底：

- `ALLOWED_GROUPS`：限制可响应的群聊（`.env` 中逗号分隔多个群号）
- `LM_STUDIO_BASE_URL` / `LM_STUDIO_MODEL`：本地模型地址与模型名
- `PROACTIVE_ENABLED`：是否启用主动发言。消息频率过低（群平均间隔 ≥ `PROACTIVE_LOW_FREQ_INTERVAL`，或消息不足两条）时完全不主动发言；频率足够时按间隔高低以 `PROACTIVE_HIGH_FREQ_INTERVAL` / `PROACTIVE_LOW_FREQ_INTERVAL` 之间的线性概率复用历史逻辑，并通过 `PROACTIVE_COOLDOWN` 硬冷却与相似内容去重防刷屏
- `RAG_ENABLED` / `RAG_TOP_K` / `RAG_SQLITE_FTS_ENABLED`：RAG 检索开关与参数
- `MEMORY_COMPRESS_LIGHT_THRESHOLD`：轻量压缩触发阈值
- `MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS`：轻量压缩冷却时间

两层过滤相关：

- `MEMORY_SOURCE_KIND_ENABLED`：是否启用消息来源分级（`AT_MENTION` / `PASSIVE`）
- `MEMORY_CANDIDATE_REOCCURRENCE_BONUS`：同一事实复现时的置信度增益
- `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS`：候选在观察区停留的最长天数
- `MEMORY_CONFIRM_HIGH_CONFIDENCE` / `MEMORY_OBSERVE_LOW_CONFIDENCE`：Gate 1 三档阈值
- `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`：被动来源晋升所需的最低观察次数
- `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT`：`AT_MENTION` 来源是否单次即可晋升
- `MEMORY_PROMOTE_MIN_IMPORTANCE`：晋升所需的最低重要度
- `MEMORY_USER_QUOTA` / `MEMORY_QUOTA_ENFORCE`：每用户记忆配额与是否真正执行淘汰
- `MEMORY_EMBEDDING_ENABLED`：是否启用向量语义检索（失败自动回退规则版）

## 项目开发中使用到的本地部署模型

- 语言模型：google/gemma-4-26b-a4b-qat，google/gemma-4-e4b
- 向量检索模型：text-embedding-qwen3-embedding-0.6b

> 注1.：这些模型是开发者基于自身设备的配置，只能作为现有代码库信息的补充，不能构成对您进行二次开发的配置建议。如果您探索出了更好的配置方案，欢迎提交PR和issue。

> 注2.：开发过程中模型可能会变更测试使用的模型（视输出情况而定）。开发者会在release界面详细说明现阶段测试所使用的模型（如果此处有多组模型并列）。

## 致谢

本项目在开发过程中得到了很多人和组织的鼓励和支持：

- 我的父母给予了最重要的经济支持。没有他们，这一切都无从开始。
- 灵感来源于和 [@t1mb2rg](https://github.com/t1mb2rg) 的讨论和 [@CST-Cat](https://github.com/CST-Cat) 的争执中。感谢他们贡献了属于自己的想法。
- [@MIO-456](https://github.com/MIO-456) 开发的 [Lumi_Nox](https://github.com/MIO-456/Lumi_Nox) 项目激励了本项目的开发。
- 感谢 [@qian-o](https://github.com/qian-o) 和他的伙伴们，以及 [@MIO-456](https://github.com/MIO-456) 和他的伙伴们。没有他们的鼓励，就没有最初开发这个项目的动力。
- 本项目开发中得到了来自如下组织的支持：
  - 模型提供商：Deepseek，OpenAI（chatGPT），Google（Gemini，Gemma）和通义千问（text-embedding-qwen3-embedding-0.6b）。没有他们的优秀模型作为基础，这个项目不可能诞生。
  - Coding Agent:[Opencode](https://github.com/anomalyco/opencode)，感谢Opencode Zen对本项目的大力支持。
  - 开源代码库：[nonebot2](https://github.com/nonebot/nonebot2)，[NapCatQQ](https://github.com/NapNeko/NapCatQQ)，以及源代码中引用的所有第三方库。向与之相关的所有开发与维护者致敬。此外本项目也是为了向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 与 [MaiBot](https://github.com/Mai-with-u/MaiBot) 两位前辈看齐，创造一个真正的，能够完整本地循环，不泄露任何群聊信息和个人隐私的AI朋友。
  - 开发者社区：[Linux Do](https://linux.do)
- 特别致谢Freya，这是献给你的作品。我的探索之旅因你的馈赠而起，是时候交出一份并不完美的回礼了。 

## License

本项目基于 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布。详见 [LICENSE](LICENSE) 文件与各源文件头部的版权声明。

## 免责声明

**在使用本项目的部分或者全部代码时，请遵守您所在国家/地区的相关法律和您所接入相关平台的用户协议中的相关条款。全体开发者无法且没有任何义务承担使用者使用该项目所造成的任何直接/间接后果**（包括但不限于账号封禁，任何的民事/刑事责任等）
