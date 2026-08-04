# Stella

基于 **NoneBot 2**、**OneBot V11** 与本地大语言模型的 QQ 群聊机器人。

Stella 面向有明确群聊边界的私有部署场景，支持：

- `@Bot` 触发的群聊问答
- LM Studio 本地 OpenAI-compatible API
- 原始群消息记录、短期上下文、长期记忆和用户画像
- 可选 FlexiWeb 在线模型辅助记忆整合，本地模型自动兜底
- 按群聊活跃度概率触发的主动发言
- 可扩展的前置/后置 Pipeline Hooks
- SQLite 持久化与 LLM 调试日志

> 当前消息处理插件使用 `nonebot.adapters.onebot.v11`，实际部署请使用 OneBot V11 兼容适配器，例如 NapCat、Lagrange.Core 或其他 V11 实现。

## 架构

```text
QQ 群消息
  |
  +-- 静默监听器
  |     |
  |     +-- 仅记录允许群内的普通消息
  |     +-- 写入 SQLite 原始消息表
  |     +-- 更新群聊活跃度统计
  |
  +-- @Bot 消息处理器
  |     |
  |     +-- 按需触发记忆整合
  |     +-- Pipeline
  |           |
  |           +-- Pre-hooks
  |           |     +-- 记录消息
  |           |     +-- 读取短期上下文
  |           |     +-- 读取用户画像与长期记忆
  |           |
  |           +-- LLM Backend
  |           |     +-- LM Studio 本地模型
  |           |
  |           +-- Post-hooks
  |                 +-- 解析 XML 格式回复
  |                 +-- 过滤 AI 身份泄露语句
  |                 +-- 分行发送与诊断日志
  |
  +-- 定时主动发言任务
        |
        +-- 根据群消息频率与冷却时间决定是否插话
```

## 功能说明

### 聊天 Pipeline

机器人只有在允许的群中被 `@` 且附带文本时才会调用主聊天模型。

`Pipeline` 将处理分为三个阶段：

1. **Pre-hooks**：写入当前消息，构建最近群聊上下文，加载用户画像和长期记忆。
2. **LLM**：通过 LM Studio 的 HTTP 接口请求本地模型。
3. **Post-hooks**：解析模型输出、过滤不符合角色设定的句子、拆分多行回复，并记录完整诊断信息。

同一进程内的 LLM 调用通过异步锁串行化，避免本地推理服务被并发请求压垮。

### 记忆系统

记忆数据库默认位于：

```text
memory/agent_memory.db
```

原始群消息会被记录；对话时，系统按需将以下信息注入提示词：

| 类型 | 用途 |
| --- | --- |
| 短期上下文 | 当前群近期话题与对话摘要 |
| 用户画像 | 用户偏好、表达习惯、态度等长期特征 |
| 长期记忆 | 与当前用户相关的重要事实 |
| 原始消息回退 | 没有可用摘要时读取最近原始消息 |

记忆整合有两条路径：

1. 优先使用 FlexiWeb 驱动的在线模型进行较大批次总结。
2. 在线路径不可用、超时或处于冷却期时，回退到 LM Studio 本地模型，并自动缩小批量避免上下文溢出。

默认配置下：

- 在线整合批次：100 条新消息，附带 15 条历史重叠窗口。
- 本地兜底批次：10 条新消息。
- 在 `@Bot` 对话前，累计存在足够新消息时会按需整合。
- 主动发言前也会先尝试更新短期记忆。

### 主动发言

Stella 可以在未被 `@` 时，以较低概率自然插话。

它不是固定时间刷屏，而是基于最近消息频率动态调整概率：

- 群聊活跃时：维持很低但非零的插话概率。
- 群聊冷清时：提高插话概率。
- 每次主动发言后：进入硬冷却期，默认 120 秒内不会再次主动发言。

该功能默认开启，可在 `config/settings.py` 中关闭。

## 目录结构

```text
Stella_project/
├── bot.py                         # NoneBot 启动入口
├── pyproject.toml                 # Python 依赖与 NoneBot 配置
├── config/
│   └── settings.py                # 集中运行时配置
├── core/
│   ├── context.py                 # ChatContext 数据结构
│   ├── pipeline.py                # Pipeline 编排器
│   └── llm/
│       ├── base.py                # LLM 后端抽象
│       ├── lm_studio.py           # LM Studio 后端
│       └── flexiweb.py            # FlexiWeb 进程与在线 LLM 接口
├── extensions/
│   └── __init__.py                # 扩展自动发现与加载
├── memory/
│   ├── SYSTEM.md                  # 主模型系统提示词
│   ├── consolidator.py            # 记忆整合与 SQLite 持久化
│   ├── pre_processors.py          # 上下文和记忆注入
│   ├── post_processors.py         # 输出解析、过滤与日志
│   ├── proactive.py               # 主动发言决策
│   └── db_cleaner.py              # 测试期数据库清理工具
└── stella_project/plugins/
    └── bot_main/
        ├── ai_gateway.py          # QQ 事件、Pipeline 和定时任务
        └── watchdog.py            # 运行监控逻辑
```

## 环境要求

- Python `>= 3.10`
- 已安装并可运行的 OneBot V11 QQ 适配器
- LM Studio，或任何兼容 OpenAI Chat Completions 接口的本地服务
- 可选：FlexiWeb Stream Scraper，用于在线模型记忆整合

## 安装

推荐使用 `uv`：

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project

uv sync
```

也可以使用 `pip`：

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

python -m pip install -U pip
python -m pip install "nonebot2[fastapi,websockets]>=2.5.0" \
  "nonebot-adapter-onebot>=2.4.6" \
  "nonebot-plugin-apscheduler>=0.5.0"
```

开发工具可额外安装：

```bash
uv sync --group dev
```

## 配置

主要运行时配置位于 `config/settings.py`。

### 1. 限制可用群聊

```python
ALLOWED_GROUPS = {123456789}
```

机器人会忽略不在该集合中的群消息。生产环境务必改为自己的群号，不建议开放给所有群。

### 2. 配置本地模型

```python
LM_STUDIO_BASE_URL = "http://127.0.0.1:1234"
LM_STUDIO_MODEL = ""
LLM_TIMEOUT = 90.0
```

- `LM_STUDIO_BASE_URL`：LM Studio 本地服务地址。
- `LM_STUDIO_MODEL`：单模型服务通常可留空；多模型服务时填入实际模型 ID。
- `LLM_TIMEOUT`：单次模型请求超时秒数。

在 LM Studio 中加载模型后，启用本地 API Server，并确认 `/v1/chat/completions` 可访问。

### 3. 配置系统提示词

系统提示词路径默认是：

```text
memory/SYSTEM.md
```

该文件决定机器人的角色、表达方式和 XML 输出约定。请勿在仓库中提交私人信息、账号凭据或敏感群聊规则。

### 4. 可选：配置 FlexiWeb

```python
FLEXIWEB_BASE_URL = "http://127.0.0.1:8000"
FLEXIWEB_PROJECT_DIR = "../FlexiWeb_Stream_Scraper"
CONSOLIDATION_SITE = "deepseek"
FLEXIWEB_HEADLESS = False
```

首次使用时应设置：

```python
FLEXIWEB_HEADLESS = False
```

手动完成网页端登录并保存浏览器会话后，再切换为无头模式。若不使用 FlexiWeb，可将：

```python
CONSOLIDATION_LLM_PRIORITY = ["lm_studio"]
```

此时所有记忆整合均由本地模型执行。

### 5. 调整主动发言

```python
PROACTIVE_ENABLED = True
PROACTIVE_COOLDOWN = 120
PROACTIVE_CHECK_INTERVAL = 30
PROACTIVE_MAX_PROB = 0.5
PROACTIVE_MIN_PROB = 0.05
```

若只希望机器人在被 `@` 时回答：

```python
PROACTIVE_ENABLED = False
```

## 配置 OneBot

Stella 使用 NoneBot 2 的 OneBot V11 适配器。需要先启动 QQ 适配器，并让它反向 WebSocket 或 HTTP WebSocket 连接到 NoneBot。

NoneBot 的基础配置通常放在项目根目录 `.env` 中，例如：

```dotenv
DRIVER=~fastapi
HOST=127.0.0.1
PORT=8080

ONEBOT_V11_ACCESS_TOKEN=replace_with_a_strong_token
```

具体反向 WebSocket 地址、端口和 Token 必须与 NapCat、Lagrange.Core 或其他 V11 实现中的配置一致。

> 不要提交 `.env`、QQ 登录会话、访问令牌、SQLite 数据库、浏览器用户目录或 `stella_thought_logs.md`。

## 启动

启动顺序：

1. 启动 LM Studio，并加载本地模型与 API Server。
2. 启动 QQ OneBot V11 适配器，并完成连接配置。
3. 在项目根目录启动 Stella。

```bash
# uv
uv run python bot.py

# 或虚拟环境
python bot.py
```

程序启动后，在 `ALLOWED_GROUPS` 中 `@Bot` 并发送文字即可触发对话。

## 编写扩展

扩展放在 `extensions/` 下。每个扩展包导出 `setup(pipeline)`，即可自动加载。

示例：`extensions/my_feature/__init__.py`

```python
from core.context import ChatContext
from core.pipeline import Pipeline

async def inject_context(ctx: ChatContext) -> ChatContext:
    ctx.context += "\n[自定义上下文]"
    return ctx

def setup(pipeline: Pipeline) -> None:
    pipeline.register_pre_hook(inject_context, priority=30)
```

Hooks 按优先级从高到低执行：

- Pre-hook：适合补充上下文、拦截请求、读取外部状态。
- Post-hook：适合解析模型输出、过滤内容、格式化发送结果、写日志。

若 Hook 返回 `None`，Pipeline 保持当前上下文继续执行。

## 调试与数据维护

模型调用诊断会写入：

```text
stella_thought_logs.md
```

日志包含后端、模型标识、完整 Prompt、原始模型输出和耗时，便于定位本地模型空回复、超时、格式不符合预期等问题。

测试阶段可使用：

```python
DB_CLEANUP_ON_START = True
```

它会在启动时清理短期/长期记忆并重置整合检查点，默认保留用户画像。

如需连原始消息也删除：

```python
DB_CLEANUP_CLEAR_MESSAGES = True
```

这会造成不可恢复的数据删除，仅应在测试环境使用。

## 当前限制

- 主聊天路径依赖本地 LM Studio；模型质量、上下文长度和响应速度由所加载模型决定。
- 记忆整合依赖 LLM 输出质量，不应将其视为精确、不可变的事实数据库。
- 当前聊天事件实现直接使用 OneBot V11 类型；尽管 `pyproject.toml` 声明了 V12 适配器，V12 不应视为已完整验证支持。
- 没有自动化测试目录或 CI 流程；部署前建议至少验证 OneBot 连接、LM Studio 可用性、数据库写入和消息发送。
- 插件元数据中仍残留早期 “PI Agent + TypeScript 记忆系统” 描述，实际实现已经是 Python Pipeline + SQLite 记忆系统。

## 安全建议

- 将 `ALLOWED_GROUPS` 设置为最小必要范围。
- 使用强随机 OneBot Access Token。
- 不要将本地 API、OneBot WebSocket 或 FlexiWeb 服务直接暴露到公网。
- 为 SQLite 数据库和调试日志设置访问权限，它们可能包含群消息、用户画像和模型上下文。
- 若使用网页端在线模型，遵守对应服务的条款与访问限制。

## License

当前仓库未包含 `LICENSE` 文件。若计划公开分发、接受贡献或用于商业场景，建议尽快补充明确许可证。