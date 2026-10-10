# 目录结构

中文 | [English](code-map.en.md) · [文档总览](../README.md)

```text
Stella_project/
├── bot.py                          # NoneBot 启动入口
├── pyproject.toml                  # 依赖、NoneBot 配置、ruff/pytest 规则
├── pyrightconfig.json              # 类型检查配置
│
├── config/
│   ├── settings.py         # 集中配置：读 .env，导出模块级常量
│   ├── spaces.py           # 群组共享空间解析（config/spaces/*.toml）
│   ├── spaces/             # 空间配置（文件名即空间名，不进 .env）
│   ├── capabilities/       # 能力声明（文件名即 domain，可选；见 *.example）
│   └── participation/      # 主动插话外置打分表
│
├── core/                           # 与业务无关的编排骨架
│   ├── context.py                  # ChatContext：一次处理的运行期载体
│   ├── tasks.py                    # Task / Result / TaskGraph 协议（四模块共用）
│   ├── pipeline.py                  # Pipeline 编排器 + prompt 拼装顺序
│   ├── context_budget.py           # 聊天上下文预算：8192 工作窗口下输入/输出/估算误差的硬边界
│   ├── planner.py                  # 受限 Planner：深度回复路径的编排器（触发判定零 LLM）
│   ├── reply_gate.py               # 零 token 的回复必要性门控（主动插话只加本地状态与冷却）
│   ├── turn_runtime.py             # 轻量会话运行时：门控需要的按群状态（不持聊天内容）
│   ├── logging_sink.py             # 结构化 JSON 日志（stella.jsonl，供 GUI 消费）
│   ├── shutdown.py                 # 优雅停止：等待在途后台任务收尾（独立成模块以便单测）
│   ├── stop_signal.py              # 停止哨兵：deploy 写、Bot 读并自杀（deploy 层可独立 import）
│   ├── vision.py                   # 图片转述：提取图源 → VISION 角色转述 → 并入消息文本（可选，默认关闭）
│   ├── llm/
│       ├── base.py                 # LLM 后端抽象接口
│       ├── registry.py             # 端点 × 角色注册表：全项目唯一的后端构造入口
│       ├── compat.py               # OpenAI 兼容端点的参数差异自适应（不用厂商白名单）
│       ├── lm_studio.py            # LM Studio 后端（含重试与截断告警）
│       ├── openai_client.py        # 完整 chat-completions 客户端（tools / 图片 / 流式）
│       ├── usage_sink.py           # 用量上报口（截断信号 / token 聚合 / 缓存命中率）
│       ├── usage_store.py          # 日账 + 每日预算判据（llm_usage_daily 的唯一写者）
│       └── scheduler.py    # 模型级资源闸门（FIFO 串行 + 排队可观测性）
│   └── runtime/                    # facade 统一运行时：§R.5 后唯一执行引擎（纯 Python，无跨进程桥 / 无 Node 依赖）
│       ├── facade.py               # RuntimeFacade：统一入口 owner 与轮次执行（旧 STELLA_RUNTIME 双路开关已退役；迁移记录见 docs/migration/cortico/）
│       └── turn_service.py         # 单轮执行服务：证据注入与 prompt 拼装的落地层（知识证据段在此渲染）
│
├── capability/                     # 能力层（详见 docs/capability-system.md）
│   ├── registry.py                 # Capability / Provider / 注册表单例 + 健康度退避
│   ├── loader.py                   # config/capabilities/*.toml → 注册表
│   ├── hooks.py                    # activate_capabilities 前置钩子（管线接入点）
│   ├── inventory.py                # 能力清单快照（供状态接口与 deploy capabilities）
│   ├── router/                     # 三级路由
│   │   ├── types.py                # Route / CapabilityHit
│   │   ├── rules.py                # Level 0：关键词规则（零延迟）
│   │   ├── semantic.py             # Level 1：Embedding 原型匹配
│   │   ├── fallback.py             # Level 2：更强模型兜底（默认关闭）
│   │   └── benchmark.py            # 路由准确率基准（决定能否开记忆门控）
│   ├── comes/                      # 工具执行层
│   │   ├── executor.py             # Capability → Provider → Tool → Result
│   │   └── summarizer.py           # Result.data → Result.summary
│   └── adapters/
│       ├── astrbot.py              # llm_tools → Provider 自动派生 + bootstrap
│       ├── knowledge.py            # knowledge.search 能力装配（KNOWLEDGE_ENABLED 时）
│       └── mcp.py                  # MCP Manager 启停 + Provider Runtime 接线
│
├── knowledge/                      # 独立知识库子系统（详见 docs/knowledge-base.md）
│   ├── domain.py                   # 领域模型：库/文档/版本/授权 + 引用值对象
│   ├── acl.py                      # ACL 判定唯一入口（user/group/space 三态主体）
│   ├── lifecycle.py                # 文档生命周期状态机（draft→review→published→archived）
│   ├── schema.py                   # knowledge.db 独立 Schema（与 agent_memory.db 零交集）
│   ├── store.py                    # 存储层唯一读写入口 + 原子版本激活
│   ├── parsers.py                  # Markdown/TXT/PDF/DOCX/URL 导入解析（带定位符）
│   ├── chunking.py                 # 段落原子切块（定位符继承）
│   ├── ingest.py                   # 导入管道：解析→切块→编码→索引就绪（worker 线程）
│   ├── fts.py                      # FTS5 分词（写入/查询两侧共用）
│   ├── embedding.py                # KB 向量编码 + 指纹锁定（复用记忆 embedding 服务）
│   ├── retrieval.py                # BM25+dense 双通道 → RRF 融合 → 有界证据
│   ├── service.py                  # 门面：角色 API / 发布流 / ACL 强制检索 / 状态面
│   └── isolation.py                # 记忆隔离护栏（证据不得成为记忆候选）
│
├── skills/                         # Anthropic 风格任务技能层（SKILL.md；详见 docs/skills.md，SKILLS_ENABLED 默认关）
│   ├── catalog.py                  # 技能目录：发现 / 隔离 / 插件局部刷新
│   ├── orchestrator.py             # 选择与调用编排（预算 / 超时 / 输出截断）
│   ├── runtime.py                  # 运行时装配（bot.py 启动期接线）
│   ├── audit.py                    # 审计事件（logs/skills_audit.jsonl）
│   └── runners/                    # 受控执行后端（docker 沙盒 runner）
│
├── memory/                         # 记忆系统主体
│   ├── SYSTEM.md                   # 机器人系统提示词
│   ├── schema.py                   # Schema 迁移（版本化，当前 v19）+ 来源枚举
│   ├── migrations.py               # 按版本执行结构与数据迁移
│   ├── space_merge.py              # 空间合并：把若干空间的记忆/画像并进一个（deploy space-merge）
│   ├── timeutil.py                 # DB 时间戳统一按 UTC 解析
│   ├── text_similarity.py          # 内容相似度与合并（单一真相源）
│   ├── cache_keys.py               # 缓存 key 统一来源（会话上下文 / 检索两层共用，无循环依赖）
│   │
│   ├── pre_processors.py           # 消息落库、短期上下文、用户上下文组装
│   ├── session_context.py          # 会话压缩的状态与判定（纯逻辑）
│   ├── session_compact.py          # 会话压缩的执行侧（取消息、调 LLM、写回）
│   ├── post_processors.py          # 输出解析、破防过滤、分行、思考日志
│   ├── prompt_builder.py           # 记忆与上下文 → 分区 Prompt
│   │
│   ├── cost_gates.py               # 成本闸门：整合前的本地免费预筛（Tier 1，零 I/O 纯函数）
│   ├── consolidator.py             # 整合：消息 → 摘要/画像/候选（含候选强化）
│   ├── consolidation_prompt.py     # 整合任务的 JSON 输出模板
│   ├── extraction_prompt.py        # 阶段2 候选提取的 prompt 模板
│   ├── consolidation_log.py        # 整合过程日志
│   ├── memory_manager.py           # 晋升：Gate 1 三档、配额淘汰、FTS 同步
│   ├── policy.py                   # Policy：Mode 检测、三层过滤、排序、候选校验
│   ├── compressor.py               # 压缩：去重合并、原子化、归档、衰减
│   │
│   ├── retrieval_v2.py             # v2 检索（Context-aware Memory Activation）
│   ├── retriever.py                # FTS5 检索 + 加权回退排序
│   ├── embeddings.py               # 本地 embedding 客户端（可选语义分）
│   │
│   ├── proactive.py                # 活跃度统计与发言概率曲线
│   ├── proactive_state.py          # 主动发言的持久化状态（配额/冷却/退避）
│   ├── proactive_gate.py           # 主动发言的统一准入闸门（六道条件）
│   ├── proactive_target.py         # 主动 @ 的目标选择与配额判定
│   ├── proactive_prompt.py         # 主动 @ 的任务指令模板
│   ├── addressing.py               # 用户个性化称呼偏好：规范化、校验、持久化（v14 表）
│   ├── addressing_intent.py        # 称呼意图识别：规则预筛 + embedding 语义判定（只返回结构化请求）
│   ├── expression_learning.py      # 表达与插话效果学习：回复发出后的异步结算（零 LLM）
│   ├── expression_store.py         # 表达学习的独立存储（「怎么说效果好」，与记忆系统分离）
│   ├── participation/              # 主动插话 Participation Decision Layer
│   │   ├── decision.py             # 参与决策与模式
│   │   ├── signals.py              # 群聊信号提取
│   │   ├── scorer.py               # 参与评分
│   │   ├── state.py                # 话题与群状态
│   │   ├── tables.py               # 外置 TOML 打分表加载
│   │   └── observability.py        # 决策日志与可观测性
│   │
│   ├── trace.py                    # 记忆决策追踪
│   ├── benchmark.py                # Memory Benchmark 运行器
│   ├── benchmark/                  # 检索层用例 + _fixtures（含整合正例基准）
│   └── db_cleaner.py               # 脏数据清理 + 消息表定时裁剪
│
├── memory_rust/                    # MEMORY_BACKEND=rust 的 Rust 检索后端（独立 wheel 发布，见 docs/memory-rust-backend.md）
│   ├── backend.py                  # Python 侧封装（BACKEND_API_VERSION 协商）
│   ├── selector.py                 # 引擎选择（wheel 探测 + 旧 shadow/strict 开关兼容）
│   └── native/                     # PyO3/maturin 源码（schema.rs 内嵌 SQL）
│
├── extensions/                     # 自动加载的扩展（扫描 setup(pipeline)）
│   ├── __init__.py                 # 扩展加载器
│   └── link_monitor/               # OneBot 链路监测（心跳 + 主动探活，只告警）
│
├── astrbot_compat/                 # AstrBot 插件兼容层（见下文）
│   ├── shim.py                     # 伪造 astrbot.* 模块树，让插件 import 得通
│   ├── loader.py                   # 发现并加载 data/plugins/* 下的插件
│   ├── base.py                     # Star 基类 / StarTools（含 html_render 入口）
│   ├── registry.py                 # 插件与 handler 注册表（模块级单例）
│   ├── filters.py                  # @command / @regex / @event_message_type 等装饰器
│   ├── events.py                   # OneBot 事件 → AstrMessageEvent，含唤醒判定
│   ├── components.py               # 消息段（Plain/Image/Json/Node…）双向转换
│   ├── pipeline.py                 # should_dispatch + 唤醒检查 + handler 执行
│   ├── render.py                   # HTML → 图片（本地 Chromium，见下文）
│   └── llm/                        # 插件侧 LLM：Provider / ToolSet / 工具循环
│
├── deploy/                         # 部署 CLI（python -m deploy ...）
│   ├── probe.py                    # doctor 的采集层（只探测，不判断）
│   ├── checks.py                   # doctor 的判断层（纯函数，每项一个）
│   ├── process.py                  # start --detach / status / stop
│   ├── init_wizard.py              # 配置向导与答案文件
│   ├── migrate.py                  # 旧安装导入与数据库升级
│   ├── plugin_check.py             # 插件接入规范检查
│   ├── plugin_scaffold.py          # 能力声明草稿与 embedding 量化
│   ├── capability_view.py          # 能力清单查询与渲染
│   ├── manifest.py                 # 发布包清单
│   ├── env_schema.py               # settings.py → GUI 配置表单 schema
│   └── __main__.py                 # 子命令编排；领域逻辑仍在各模块
│
├── stella_project/plugins/bot_main/
│   ├── ai_gateway.py               # QQ 事件监听、Pipeline 装配、主动发言调度
│   ├── status_api.py               # 本地状态接口（回环，供 deploy status / GUI）
│   └── config.py                   # 插件配置（pydantic）
│
├── cli/                            # stellacli：本地 / Docker 的编排与渲染层
│   └── src/                        # Rust CLI；领域逻辑透传 deploy / Compose
│
├── runtime-manager/                # Rust「Stella Runtime Contract」组件监督器（schemas/ 契约 + src/，可选 Runtime）
│
├── data/                           # 运行期数据（全部 gitignore）
│   ├── plugins/                    # 第三方 AstrBot 插件
│   ├── plugin_data/                # 插件自己的 KV / 数据目录
│   └── render_cache/               # HTML 渲染产物（要发出去的图片，不是日志）
│
├── logs/                           # 全部运行期日志（LOG_DIR，gitignore）
│   ├── stella.jsonl                # 结构化日志（GUI 消费，10MB 轮转、留 5 份）
│   ├── stella_thought_logs.md      # 思考/决策日志
│   ├── memory_consolidation_log.md # 整合日志
│   ├── memory_compressor_log.md    # 压缩日志
│   ├── boot_debug.log              # 启动诊断（每次启动清空重写）
│   └── stella.pid                  # 进程号（不是日志，但同目录）
│
├── scripts/                        # 开发工具、生成器与 CI 门禁
│   ├── probe_consolidation.py      # 整合探针 / 正例回归基准
│   ├── sample_windows.py           # 从真实库分层采样消息窗口
│   ├── probe_embedding.py          # embedding 服务探针
│   └── build_embedding_fixture.py  # 构建 benchmark 向量 fixture
│
├── release_assets/                 # 发布产物模板与发布校验（快速开始 README、发布说明模板、SHA256SUMS/清单语义、VM 验证矩阵）
│
├── stella-installer/               # v1 桌面安装器（Tauri 2 + Rust，原生 HTML/JS；已冻结，见 gui-v1-final）
├── dashboard/                      # v2 控制面前端（Vue 3 + Vuetify 3 + TS，pnpm 构建；浏览器与桌面壳共用）
├── webui/                          # v2 控制面后端（FastAPI 子应用挂 NoneBot 同端口；静态托管 dashboard/dist）
├── desktop/                        # v2 桌面壳（Tauri 2；内嵌面板 + 窄契约启动/自检，自 v1 移植）
├── openspec/                       # WebUI API 契约（openapi-v1.yaml）
├── tests/                          # pytest 测试
├── docs/                           # 按任务分类的项目文档
│   ├── agent/                      # Agent 按需加载的工作规则
│   ├── guides/                     # 部署、管理和使用
│   ├── architecture/               # 模块、流程和数据边界
│   ├── reference/                  # 配置与插件合同
│   ├── development/                # 测试、迁移、发布与排查
│   ├── history/                    # 历史档案导航
│   └── plans/ reports/ migration/  # 原日期证据
├── design_docs/                    # 设计过程记录（规范/检查点/缺陷报告/日志/测试清单）
└── _deprecated/                    # 废弃代码与旧数据库归档（gitignore）
```
