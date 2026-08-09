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
- 基于群聊活跃度的主动发言
- 支持 Pipeline 前后置 Hook 扩展
- SQLite 持久化、思考日志与记忆压缩日志
- SQLite FTS5 记忆全文索引 + 关键词/权重综合排序的 RAG 检索（可开关）
- pytest 自动化测试覆盖记忆晋升、FTS 索引同步与 RAG 开关行为

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
│   ├── consolidator.py            # 记忆整合与候选记忆写入（含 checkpoint）
│   ├── memory_manager.py          # 记忆候选处理：晋升、合并、去重（同步 FTS 索引）
│   ├── compressor.py              # 记忆压缩与轻量/周度压缩调度
│   ├── retriever.py               # 检索：RAG(FTS5) + 加权回退排序
│   ├── pre_processors.py          # 记录消息、构造短期上下文与用户上下文
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

记忆整合统一使用本地 LM Studio 的小模型进行小批量处理，与主聊天模型分离，避免显存/推理竞争。

### 5. 记忆写入与处理

记忆整合阶段会产出短期上下文摘要、用户画像与记忆候选，写入 SQLite；随后 `memory/memory_manager.py` 判断是否合并、更新或归档，并在写入 / 合并时同步维护 FTS5 索引，保证 `memories_fts` 与 `memories` 完全一致。

### 6. 记忆压缩

- 轻量压缩：在候选记忆处理后按条件触发，用于小规模去重和原子化
- 周度压缩：在后台任务中执行更重的全量压缩

压缩结果写入压缩日志与统计表，便于观察记忆系统的演化过程。

## 测试

项目使用 pytest：

```bash
python -m pytest tests -q
```

覆盖内容：

- 记忆候选晋升 / 观察（`tests/test_memory_manager.py`）
- FTS 索引与 `memories` 表完全同步、过期索引自动重建（`tests/test_memory_manager_fts_sync.py`）
- RAG 开关（`RAG_ENABLED` / `RAG_SQLITE_FTS_ENABLED` / `RAG_TOP_K`）的开关组合行为（`tests/test_rag_switches.py`）
- 检索排序与回退（`tests/test_retriever.py`）
- 短期记忆说话人归属（`tests/test_short_term_attribution.py`）
- 全流程端到端：消息入库 → 上下文构建 → Pipeline 编排 → 输出解析/分行 → 整合 → 记忆晋升 + FTS（`tests/test_full_workflow.py`，全程 Dummy LLM、不触网）

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

为避免新旧表结构冲突，历史运行时数据库已从 `memory/` 迁移到 `_deprecated/` 归档：

- `_deprecated/legacy_agent_memory.db`：早期版运行库；
- `_deprecated/legacy_agent_memory_2026.db`：当前 schema 升级前的运行库。

启动时会按当前 schema 在 `memory/` 下自动重建新库。

## 配置说明

核心配置位于 [config/settings.py](config/settings.py)，敏感值与机器相关项（群号、令牌、路径）一律从 `.env` 读取，模板见 [.env.example](.env.example)，`settings.py` 中的默认值仅作兜底：

- `ALLOWED_GROUPS`：限制可响应的群聊（`.env` 中逗号分隔多个群号）
- `LM_STUDIO_BASE_URL` / `LM_STUDIO_MODEL`：本地模型地址与模型名
- `PROACTIVE_ENABLED`：是否启用主动发言。消息频率过低（群平均间隔 ≥ `PROACTIVE_LOW_FREQ_INTERVAL`，或消息不足两条）时完全不主动发言；频率足够时按间隔高低以 `PROACTIVE_HIGH_FREQ_INTERVAL` / `PROACTIVE_LOW_FREQ_INTERVAL` 之间的线性概率复用历史逻辑，并通过 `PROACTIVE_COOLDOWN` 硬冷却与相似内容去重防刷屏
- `RAG_ENABLED` / `RAG_TOP_K` / `RAG_SQLITE_FTS_ENABLED`：RAG 检索开关与参数
- `MEMORY_COMPRESS_LIGHT_THRESHOLD`：轻量压缩触发阈值
- `MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS`：轻量压缩冷却时间

## 致谢

本项目在开发过程中得到了很多人和组织的鼓励和支持：

- 我的父母给予了最重要的经济支持。没有他们，这一切都无从开始。
- 灵感来源于和 [@t1mb2rg](https://github.com/t1mb2rg) 的讨论和 [@CST-Cat](https://github.com/CST-Cat) 的争执中。感谢他们贡献了属于自己的想法。
- [@MIO-456](https://github.com/MIO-456) 开发的 [Lumi_Nox](https://github.com/MIO-456/Lumi_Nox) 项目激励了本项目的开发。
- 感谢 [@qian-o](https://github.com/qian-o) 和他的伙伴们，以及 [@MIO-456](https://github.com/MIO-456) 和他的伙伴们。没有他们的鼓励，就没有最初开发这个项目的动力。
- 本项目开发中得到了来自如下组织的支持：
  - 模型提供商：Deepseek，OpenAI（chatGPT）和Google（Gemini）
  - 开源代码库：[nonebot2](https://github.com/nonebot/nonebot2)，[NapCatQQ](https://github.com/NapNeko/NapCatQQ)，以及源代码中引用的所有第三方库。向与之相关的所有开发与维护者致敬。
  - 开发者社区：[Linux Do](https://linux.do)
- 特别致谢Freya，这是献给你的作品。我的探索之旅因你的馈赠而起，是时候交出一份并不完美的回礼了。 

## License

本项目基于 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布。详见 [LICENSE](LICENSE) 文件与各源文件头部的版权声明。
