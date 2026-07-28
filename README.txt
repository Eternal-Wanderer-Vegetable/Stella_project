= Stella Project — AI 智能 QQ 聊天机器人 =

===== 项目概述 =====

Stella Project 是一个基于 NoneBot2 + PI Coding Agent 框架构建的
AI 智能 QQ 聊天机器人。它使用本地部署的大语言模型（LLM）作为
大脑，通过 ChromaDB 向量数据库实现长期记忆，具备人性化的对话
节奏控制与自动恢复机制，旨在提供沉浸式的 AI 角色扮演聊天体验。

项目代号：Stella（星之语）

===== 核心架构 =====

  ┌─────────────────────────────────────────────────────────┐
  │                   QQ 客户端（用户）                       │
  └─────────────────────┬───────────────────────────────────┘
                        │
  ┌─────────────────────▼───────────────────────────────────┐
  │           NapCat（QQ 协议实现层）                        │
  │           监听群消息 / 发送回复                          │
  └─────────────────────┬───────────────────────────────────┘
                        │
  ┌─────────────────────▼───────────────────────────────────┐
  │    NoneBot2 + OneBot v11（Python 机器人框架）            │
  │                                                         │
  │  ┌─────────────────────────────────────────────────┐    │
  │  │  bot_main 插件                                   │    │
  │  │  ├── ai_gateway.py  消息处理与 AI 编排           │    │
  │  │  ├── memory.py      ChromaDB 向量记忆/好感度   │    │
  │  │  ├── utils.py       工具函数（延迟/文本转换）   │    │
  │  │  ├── watchdog.py    NapCat 守护/自动重启        │    │
  │  │  └── config.py      插件配置模型                │    │
  │  └─────────────────────────────────────────────────┘    │
  └─────────────────────┬───────────────────────────────────┘
                        │ 调用 npx pi CLI
  ┌─────────────────────▼───────────────────────────────────┐
  │    PI Coding Agent（TypeScript AI 引擎桥接层）           │
  │                                                         │
  │  ├── agent_bridge.ts    Agent 会话管理/模型调用         │
  │  └── models.json        LM Studio 提供者配置            │
  └─────────────────────┬───────────────────────────────────┘
                        │
  ┌─────────────────────▼───────────────────────────────────┐
  │    LM Studio（本地 LLM 推理服务器）                      │
  │    默认地址：http://127.0.0.1:1234/v1                   │
  └─────────────────────────────────────────────────────────┘

===== 技术栈 =====

  [Python 层]
    • Python 3.10+
    • NoneBot2                     — 异步 QQ 机器人框架
    • nonebot-adapter-onebot v11   — OneBot v11 协议适配器
    • nonebot-plugin-apscheduler   — 定时任务调度
    • ChromaDB                     — 向量数据库（长期记忆）
    • sentence-transformers        — 文本嵌入模型（all-MiniLM-L6-v2）
    • httpx                        — 异步 HTTP 客户端
    • pydantic                     — 配置数据模型

  [TypeScript 层]
    • Node.js (通过 npx 调用)
    • @earendil-works/pi-coding-agent — PI Coding Agent 框架
    • LM Studio (OpenAI 兼容 API)     — 本地 LLM 推理

  [基础设施]
    • NapCat                       — QQ 协议实现 / 机器人登录
    • APScheduler                  — 心跳检测与自动恢复

===== 项目结构 =====

Stella_project-main/
│
├── pi_agent_core/                    # TypeScript AI 引擎桥接层
│   ├── agent_bridge.ts               # Agent 会话创建与模型调用
│   └── models.json                   # 模型提供者配置
│
├── stella_project/
│   └── plugins/
│       └── bot_main/                 # NoneBot2 插件主目录
│           ├── __init__.py           # 插件入口与元数据
│           ├── ai_gateway.py         # ★ 核心：消息处理与 AI 编排
│           ├── memory.py             # 向量记忆与好感度系统
│           ├── utils.py              # 工具函数
│           ├── watchdog.py           # NapCat 守护/自动重启
│           └── config.py             # 配置模型
│
├── .env                              # 环境变量（开发）
├── .env.dev                          # 开发环境变量
├── .env.prod                         # 生产环境变量
├── .gitignore                        # 版本忽略规则
├── pyproject.toml                    # Python 项目配置
├── README.md                         # 项目说明（原始占位）
├── STARTCOMMAND.md                   # 启动命令说明
└── stella_thought_logs.md            # AI 思考日志（运行生成）

===== 核心功能模块详解 =====

一、AI 对话引擎（ai_gateway.py）
─────────────────────────────

  这是整个项目的核心模块，负责：
  • 监听 QQ 群聊中 @Bot 的消息
  • 异步调用 PI Coding Agent CLI 子进程
  • 将用户消息发送给本地 LLM 处理
  • 解析 LLM 返回的 XML 格式回复
  • 将 AI 的"思考过程"记录到日志文件
  • 将最终回复消息发送回 QQ 群

  AI 回复的 XML 格式：
    <thought>（AI 的内部思考过程）</thought>
    <action>（判定要执行的动作）</action>
    <reply>（最终输出的台词）</reply>

  ★ 安全机制：
    - 采用 asyncio.Lock() 实现全局并发控制，
      确保同一时间只有一条消息被处理
    - 45 秒超时保护，防止 LLM 卡死
    - "破防兜底"过滤：拦截 AI 说出"作为AI"、
      "我是一个模型"等出戏台词
    - 极强的 XML 容错解析：即使模型输出被截断，
      也能正常提取关键内容

二、向量记忆系统（memory.py）
─────────────────────────────

  基于 ChromaDB 的长期记忆实现：
  • 使用本地 all-MiniLM-L6-v2 嵌入模型
  • 存储有价值的对话到向量数据库
  • 支持按用户查询相似历史记忆（RAG）
  • 用户好感度系统（持久化 JSON）

  记忆存储条件：
    只有当用户消息和 AI 回复都超过 5 个字符时，
    才会存入向量数据库，过滤掉无意义的寒暄。

三、人性化延迟（utils.py）
─────────────────────────────

  为了让 AI 回复更自然，实现了模拟人类行为的延迟策略：
  • 短回复（<5字）：快速回复（0.4~0.8秒）
  • 长文本（>120字）：稍作停顿（0.5~1.2秒）
  • 打字速度模拟：每字 0.05~0.12 秒
  • 思考时间：0.6~1.5 秒（含括号语句额外延迟）
  • 深夜模式（0:00~6:00）：反应速度降低 1.2~1.5 倍
  • 随机走神：5% 概率额外发呆 2~4 秒

  此外还包含 Markdown 转 QQ 纯文本的格式转换函数。

四、看门狗守护（watchdog.py）
─────────────────────────────

  保障机器人稳定运行的自动恢复机制：
  • 每 1 分钟检查一次消息流状态
  • 如果超过 5 分钟没有收到任何消息，
    自动调用 NapCat WebUI API 重启 NapCat
  • 重启后设置 2 分钟冷却期，防止频繁重启

===== 部署与启动 =====

  前置条件：
    1. Python 3.10 或更高版本
    2. Node.js（用于 PI Coding Agent）
    3. LM Studio（加载本地 LLM 模型）
    4. NapCat（QQ 协议登录）

  启动步骤：
    1. 启动 LM Studio，加载模型，开启本地推理服务
       （默认地址：http://127.0.0.1:1234）
    2. 配置 NapCat 并登录 QQ 账号
    3. 安装 Python 依赖：
       pip install -r requirements.txt  （若有）
       或参考 pyproject.toml 安装依赖
    4. 配置 .env 文件（参考 .env.dev / .env.prod）
    5. 参考 STARTCOMMAND.md 启动机器人

===== 注意事项 =====

  1. 本项目仅用于学习和娱乐目的
  2. 需要一台具备一定算力的机器运行本地 LLM
  3. 建议使用至少 8GB 显存的 GPU 以获得流畅体验
  4. 使用的 QQ 账号有被封禁的风险，请谨慎使用
  5. 人设提示词（persona prompt）位于 pi_agent_core/SYSTEM.md
     （在 .gitignore 中排除，需自行创建）

===== 许可证 =====

  本项目仅供学习参考，未指定开源许可证。
