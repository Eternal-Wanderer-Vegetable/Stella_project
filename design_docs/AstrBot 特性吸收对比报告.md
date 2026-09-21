# Stella 与 AstrBot 特性吸收对比报告

日期：2026-09-21

## 结论

Stella 在长期记忆、主动参与、8192 token 上下文预算、隐私优先和工具与人格解耦方面更有特色；AstrBot 在平台化、可配置、Agent 工具基础设施和插件生态方面更成熟。

建议吸收 AstrBot 的外围能力，不替换 Stella 的核心记忆架构。优先顺序是：MCP、Skills、独立知识库、用户可管理的定时 Agent、WebUI/ChatUI，再考虑沙盒、多平台和插件市场。

## 对比范围与当前状态

本报告基于：

- Stella 当前工作树源码、README、架构文档和配置；
- GitNexus 已有索引中的调用关系和影响分析；
- AstrBot `master` 分支源码、中文文档和 v4.28.1 发布说明。

GitNexus 索引记录显示 Stella 索引落后当前 HEAD 12 个提交。刷新索引时 Windows 环境出现 `cmd.exe ENOENT`，因此调用图结果结合当前源码进行了复核。当前工作树本身还有未提交改动，本报告没有修改这些文件。

## Stella 已经具备的优势

- 以 8192 token 为基准拆分人格、记忆、历史、工具和压缩预算。
- 记忆候选、置信度、交叉验证、晋升、遗忘和决策追踪形成了完整链路。
- 共享空间隔离长期画像，同时按群隔离短期消息、会话和静音状态。
- 主动 @、主动发言、消息频率判断、用户级冷却、回应检测和退避机制已经较完整。
- Chat、Router、Plugin、Compact、Extract、Consolidation、Vision 角色可以绑定不同模型端点。
- 工具在聊天上下文之外执行，只将压缩后的结果交回人格层。
- 已支持 AstrBot 插件兼容、生命周期、热重载、`llm_tool`、能力声明和本地 Chromium 卡片渲染。

相关代码：[README.md](../README.md)、[docs/architecture.md](../docs/architecture.md)、[docs/capability-system.md](../docs/capability-system.md)、[memory/trace.py](../memory/trace.py)。

## 特性对比

| 能力 | Stella 当前状态 | AstrBot 的可借鉴点 | 建议 |
|---|---|---|---|
| 记忆与主动聊天 | 已较强：分区记忆、证据晋升、遗忘、主动 @、共享空间、会话压缩 | 主动 Agent、定时 Agent、会话级任务 | 保留 Stella 方案，吸收任务编排 |
| 插件系统 | 支持 AstrBot 插件、生命周期、热重载、工具路由和能力清单 | 插件市场、在线安装/更新、Pages、i18n、平台声明 | 高价值 |
| MCP | 注册表已有 `KIND_MCP` 占位，执行器暂不支持 | 多 Server 管理、测试连接、工具发现和连接状态 | 最高优先级 |
| Skills | 没有独立 Skills 机制 | `SKILL.md`、按需加载、插件内置和工作区 Skill | 最高优先级 |
| 知识库 | 有个人记忆检索和 embedding，没有独立文档知识库 | 文档/URL 导入，稠密检索 + BM25 + RRF + rerank | 高价值，必须与个人记忆分库 |
| Web 搜索 | 可由插件实现，没有统一内置入口 | 标准化搜索工具、参数校验、错误处理 | 可先作为 MCP/Capability Provider |
| Agent 沙盒 | 没有完整隔离执行环境 | Local/Sandbox、Shell、Python、文件、浏览器和资源限制 | 中高优先级，可选启用 |
| 多平台 | 架构以 OneBot V11/QQ 为中心 | 统一消息事件、平台状态、Webhook、Telegram/Discord/飞书/Slack 等 | 中长期改造 |
| WebUI/ChatUI | 有 Tauri 配置页、状态 API 和插件页，没有完整 ChatUI | 对话历史、流式回复、推理过程、统计、Profile、知识库和任务管理 | 高价值 |
| 定时任务 | 有固定 APScheduler 任务 | 用户可创建、编辑、暂停、一次性执行的持久化 Cron Agent | 高价值 |
| 子 Agent | Comes 是受限工具执行器，没有通用编排 | Handoff、子 Agent、Dify/Coze/百炼/DeerFlow Runner | 中长期 |
| 国际化 | 主要是中文界面和文档 | 核心、插件、Dashboard、平台适配器多语言 | 中低优先级 |

## 优先吸收的能力

### 1. MCP Provider

Stella 已经预留了 `KIND_MCP`、`KIND_API`、`KIND_NATIVE`。但 [capability/comes/executor.py](../capability/comes/executor.py) 当前只执行 AstrBot 工具，MCP/API/native 会被标记为暂不支持；[capability/registry.py](../capability/registry.py) 已有合适的 Provider 抽象位置。

建议增加：

- stdio、SSE 或 HTTP MCP 客户端；
- Server 启动、连接、断开、重连和健康状态；
- 工具 schema 自动同步到 Capability Registry；
- 命令、环境变量、网络权限和超时白名单；
- 每个 Server 的工具数量、调用次数和失败退避；
- 继续通过 Comes 压缩结果，避免把所有 MCP schema 放入人格 prompt。

AstrBot 的管理方式可参考 [MCP 文档](https://docs.astrbot.app/use/mcp.html)。

### 2. Anthropic 风格 Skills

普通工具负责执行，Skill 负责描述完成一类任务的方法。初始只暴露名称和简介，命中后才读取完整 `SKILL.md`，这与 Stella 的小上下文设计非常契合。

建议目录：

```text
data/skills/<skill-name>/SKILL.md
data/skills/<skill-name>/scripts/
data/skills/<skill-name>/references/
```

建议优先级：工作区 Skill > 用户本地 Skill > 插件内置 Skill > 内置 Skill。Router 只使用摘要，Comes 或 Agent 命中后再读取正文和脚本。

参考：[AstrBot Skills 文档](https://docs.astrbot.app/use/skills.html)。

### 3. 独立知识库

Stella 的记忆系统描述的是“关于用户和对话的长期认知”；知识库描述的是“用户主动上传的外部资料”，两者应分开存储、检索和权限控制。

建议第一版支持 Markdown、TXT、PDF、DOCX 和 URL，并采用：

```text
文档解析 → 分块 → embedding 检索
             + BM25 稀疏检索
             → RRF 融合 → 可选 rerank → 少量片段注入
```

每个知识库单独保存 embedding 模型、向量维度、召回参数、来源元数据和访问范围。参考：[AstrBot 知识库文档](https://docs.astrbot.app/use/knowledge-base.html)。

### 4. 用户可管理的 Cron / 主动 Agent

Stella 已有 APScheduler，但主要用于固定的清理、压缩、主动发言和整合任务。可以增加持久化的用户任务：一次性任务、Cron 表达式、时区、启停、下次执行时间、失败记录和会话上下文压缩设置。

任务执行应继续遵守群级锁、模型预算、工具权限和主动发言配额，不能绕过现有的主动行为闸门。

### 5. WebUI / ChatUI 控制面

在已有 Tauri 配置页和状态 API 上增加运行期控制：

- 对话历史和分页；
- 流式回复和推理过程显示；
- 人格、空间和模型 Profile；
- 插件启停、配置、更新和 Pages；
- MCP Server、Skills、知识库和 Cron 管理；
- 用量、错误、调用链和记忆检索统计。

AstrBot v4.28.1 已将 ChatUI 历史分页、流式交互、推理显示和工作区代码预览作为重点优化项，可作为 UI 方向参考：[v4.28.1 发布说明](https://github.com/AstrBotDevs/AstrBot/releases/tag/v4.28.1)。

## 中长期能力

### 沙盒执行

AstrBot 的 Agent 沙盒支持 Shell、Python、文件系统、浏览器和 CUA。Stella 应先实现工作区目录、CPU/内存/时间限制、网络开关和输出大小限制，默认关闭；Windows 部署不能直接假设 Linux 的 `bubblewrap` 等机制可用。

参考：[AstrBot Agent 沙盒文档](https://docs.astrbot.app/use/astrbot-agent-sandbox.html)。

### 统一消息来源与多平台

AstrBot 使用统一消息来源和平台适配器来承载 QQ、Telegram、Discord、飞书、Slack 等平台。Stella 当前 [docs/architecture.md](../docs/architecture.md) 仍以 OneBot V11/NapCat 为接入层，[astrbot_compat/context.py](../astrbot_compat/context.py) 中的 `register_platform_adapter` 和 `register_web_api` 也明确标记为暂不支持。

建议先抽象 `MessageSource`、`MessageEvent`、`MessageChain` 和 `unified_origin`，将 QQ 作为第一种适配器，再扩展其他平台。记忆、主动行为和限流应按统一来源隔离，不能把不同平台的会话混在一起。

### 插件市场、配置和国际化

Stella 已有插件元数据、能力声明和热重载，但仍缺少在线安装/更新、版本约束、插件配置页面、Pages 和完整 i18n。AstrBot 的这些能力可提升可发现性和维护性。

依赖自动安装应继续保持关闭或逐项确认。当前 [config/settings.py](../config/settings.py) 的 `ASTRBOT_AUTO_INSTALL_REQUIREMENTS=false` 是合理的安全默认值。

### SubAgent 与第三方 Agent Runner

可以吸收 Handoff、子 Agent、每个 Agent 的人格和工具范围、后台执行以及 Dify/Coze/百炼等外部 Runner。但子 Agent 必须拥有独立上下文和预算，不能直接污染 Stella 的人格、记忆和主动发言状态。

## 不建议直接照搬的内容

- 不要把所有 MCP 工具或 Skill 全文注入主聊天 prompt，继续保持 Stella 的工具隔离。
- 不要把外部知识库内容直接当作个人长期记忆，必须区分来源、权限、生命周期和可信度。
- 不要为了多平台而破坏 QQ 群专用的主动参与模型，应先增加适配器边界。
- 不要默认启用本地任意代码执行；沙盒必须有明确的权限、资源限制和审计记录。
- 不要直接复制 AstrBot 的大规模平台和前端代码，优先借鉴协议、数据模型和生命周期边界。

## 建议实施顺序

1. MCP Provider、工具健康状态和安全白名单；
2. Skills 按需加载和工作区覆盖；
3. 独立知识库；
4. 用户可管理的 Cron / 主动 Agent；
5. WebUI/ChatUI 控制面；
6. 可选沙盒执行；
7. 统一消息来源和多平台适配器；
8. 插件市场、i18n、SubAgent 和第三方 Agent Runner。

这条路线可以吸收 AstrBot 的生态和平台能力，同时保留 Stella 的记忆隔离、隐私和小上下文设计。

## GitNexus 影响记录

在本次分析中对当前关键符号执行了只读影响分析：

- `Pipeline`：LOW，直接调用方 3 个；
- `CapabilityRegistry`：HIGH，约 22 个上游影响点；
- AstrBot 兼容层 `Context`：MEDIUM，约 14 个上游影响点。

因此后续实现 MCP 或 Provider 扩展时，应优先在 Registry/Adapter 层增加新实现，避免直接改动聊天 Pipeline 和兼容层核心行为。

