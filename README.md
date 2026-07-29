下面是 `Stella_project` 的 `README.md` 完整内容，可直接复制到 GitHub 仓库根目录：

```markdown
# Stella Project

> 基于 NoneBot2、OneBot v11、PI Coding Agent 和本地大语言模型的 QQ 群聊 AI 机器人。

[![Latest Release](https://img.shields.io/github/v/release/Eternal-Wanderer-Vegetable/Stella_project?display_name=tag&sort=semver)](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases)
[![GitHub Stars](https://img.shields.io/github/stars/Eternal-Wanderer-Vegetable/Stella_project)](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/stargazers)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-Node.js-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)

## 项目简介

Stella Project 是一个面向 QQ 群聊场景的本地化 AI 聊天机器人项目。

项目使用 NoneBot2 和 OneBot v11 接入 QQ 消息，通过 PI Coding Agent 管理 AI 会话，并调用本地 LM Studio 提供的大语言模型完成回复。机器人可以读取指定群聊的近期消息作为上下文，将对话记录保存到本地 SQLite 数据库，并把模型输出的思考、动作和最终回复写入 Markdown 日志。

项目的主要目标：

- 使用本地模型完成 QQ 群聊对话；
- 支持自定义角色设定和系统提示词；
- 为 AI 提供有限的群聊上下文；
- 保留本地对话和运行日志；
- 通过并发控制和超时机制提升运行稳定性；
- 为后续记忆系统和 Agent 工具扩展预留接口。

> 本项目仍处于持续开发阶段，配置方式和内部实现可能随版本变化。请以当前源码、`STARTCOMMAND.md` 和 Release 说明为准。

## 功能概览

### QQ 群聊 AI 对话

机器人监听 OneBot v11 群消息，仅在配置的群聊和触发条件满足时调用 AI：

- 支持通过 `@机器人` 触发对话；
- 对允许的群聊进行白名单过滤；
- 忽略空消息和部分系统指令；
- 将用户 ID、群号和问题传递给 AI Gateway；
- 以回复消息的形式发送 AI 结果。

### 本地大模型推理

项目默认通过 LM Studio 提供 OpenAI 兼容的本地模型服务：

- 对话默认在本地完成；
- 支持在 LM Studio 中加载自定义模型；
- 通过 PI Coding Agent 管理模型会话；
- 通过 `models.json` 配置模型提供者；
- 默认使用 `lm-studio` 提供者和 `stella-local` 模型配置。

常见默认地址：

```text
http://127.0.0.1:1234/v1
```

具体地址和模型名称请以 LM Studio 与项目当前配置为准。

### 群聊上下文

机器人会从本地 SQLite 数据库中读取指定群聊的近期文本消息，并将其作为模型上下文的一部分。

处理流程：

1. 接收群消息；
2. 过滤不符合条件的消息；
3. 将消息写入本地 SQLite；
4. 查询指定群聊最近的消息；
5. 将历史消息与当前问题组合为 Prompt；
6. 调用本地 PI Agent；
7. 解析并发送模型回复。

### 输出解析与容错

AI Gateway 会尝试从模型输出中提取：

- 思考内容；
- 动作信息；
- 最终回复。

即使模型输出不完整，程序也会尝试提取可用文本。如果无法提取有效回复，则使用默认兜底文本，避免整个消息处理流程中断。

### 并发与超时控制

为避免多个请求同时调用本地 Agent，当前实现使用全局异步锁控制模型请求：

- 同一时间只处理一个 AI 请求；
- 单次请求设置超时限制；
- Agent 执行失败时返回兜底消息；
- 错误信息写入 NoneBot 日志；
- 防止本地模型卡死导致消息处理器长期阻塞。

### 运行日志

项目会在运行过程中记录：

- 用户输入；
- 模型输出的思考内容；
- 模型判定的动作；
- 最终发送的回复；
- Agent 标准输出和错误输出。

默认思考日志文件为：

```text
stella_thought_logs.md
```

日志内容可能包含群聊消息、用户 ID 和模型输出，请妥善保护运行目录，不要直接上传日志文件。

## 系统架构

```text
QQ 用户
   │
   ▼
NapCat / OneBot v11
   │
   ▼
NoneBot2
   │
   ▼
stella_project/plugins/bot_main
   │
   ├── 群消息过滤与触发
   ├── SQLite 群聊记录
   ├── Prompt 组装
   ├── PI Agent 子进程调用
   ├── 模型输出解析
   ├── 日志写入
   └── QQ 回复发送
   │
   ▼
PI Coding Agent
   │
   ▼
LM Studio OpenAI-Compatible API
   │
   ▼
本地大语言模型
```

## 项目结构

```text
Stella_project/
├── pi_agent_core/
│   ├── agent_bridge.ts
│   ├── models.json
│   ├── extensions/
│   │   └── memory_system/
│   └── SYSTEM.md 或 prompt.txt
│
├── stella_project/
│   └── plugins/
│       └── bot_main/
│           ├── __init__.py
│           ├── ai_gateway.py
│           ├── config.py
│           ├── memory.py
│           ├── utils.py
│           └── watchdog.py
│
├── .env.dev
├── .env.prod
├── .gitignore
├── pyproject.toml
├── STARTCOMMAND.md
├── README.md
└── stella_thought_logs.md
```

### 主要模块

| 模块 | 作用 |
| --- | --- |
| `ai_gateway.py` | QQ 消息监听、群聊过滤、Prompt 组装、PI Agent 调用和回复发送 |
| `config.py` | 插件配置和环境变量读取 |
| `memory.py` | 记忆功能相关实现，具体行为以当前源码为准 |
| `utils.py` | 文本处理和其他通用工具 |
| `watchdog.py` | 机器人运行状态监控和恢复相关逻辑 |
| `agent_bridge.ts` | PI Coding Agent 会话与本地模型调用桥接 |
| `models.json` | PI Agent 模型提供者配置 |
| `extensions/memory_system` | PI Agent 扩展能力和记忆相关接口 |

## 运行环境

### 必需组件

- Python 3.10 或更高版本；
- Node.js 和 npm；
- NoneBot2；
- OneBot v11 适配器；
- NapCat 或其他兼容 OneBot v11 的 QQ 接入端；
- LM Studio；
- 一个可由 LM Studio 加载的本地大语言模型。

### 可选组件

根据当前配置和启用模块，项目可能还会使用：

- SQLite；
- PI Coding Agent；
- 向量数据库或文本嵌入模型；
- APScheduler；
- NapCat WebUI。

不同版本的依赖可能有所变化，建议优先检查：

```text
pyproject.toml
STARTCOMMAND.md
pi_agent_core/models.json
```

## 安装

### 1. 获取项目

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
```

使用稳定版本：

```bash
git checkout v1.1.0
```

也可以直接使用最新开发分支，但开发分支的配置和行为可能发生变化。

### 2. 创建 Python 虚拟环境

Linux/macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. 安装 Python 依赖

如果仓库提供了依赖配置，优先根据 `pyproject.toml` 安装：

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

如果当前版本提供 `requirements.txt`，也可以使用：

```bash
python -m pip install -r requirements.txt
```

> 如果当前仓库没有 `requirements.txt`，请以 `pyproject.toml` 为准。

### 4. 检查 Node.js

```bash
node --version
npm --version
```

PI Agent 当前通过 `npx` 调用。首次运行时，npm 可能需要下载相应的 Agent 包。

## 配置

### LM Studio

1. 安装并启动 LM Studio；
2. 加载需要使用的本地模型；
3. 启动 OpenAI 兼容 API 服务；
4. 确认 API 地址和端口；
5. 确认项目中的模型名称与 LM Studio 配置一致。

常见默认地址：

```text
http://127.0.0.1:1234/v1
```

### 模型配置

检查：

```text
pi_agent_core/models.json
```

当前 Python Gateway 使用类似下面的参数调用 PI Agent：

```text
--provider lm-studio
--model stella-local
```

如果模型名称、提供者名称或服务地址发生变化，需要同步修改模型配置。

### 角色设定

项目支持通过本地 Prompt 文件提供角色设定。相关文件可能包括：

```text
pi_agent_core/SYSTEM.md
pi_agent_core/prompt.txt
```

请以当前源码实际读取的文件为准。

不要把包含个人信息、凭证或私人群聊内容的角色设定提交到公开仓库。

### QQ 接入

配置 NapCat 或其他 OneBot v11 实现：

1. 登录专用 QQ 账号；
2. 开启 OneBot v11 通信；
3. 确认 NoneBot2 能够连接到 OneBot；
4. 确认机器人可以接收群消息；
5. 确认机器人可以发送群消息；
6. 将允许使用 AI 功能的群号加入项目配置。

建议使用独立 QQ 账号运行机器人。

### 环境变量

项目提供了不同环境配置文件作为参考：

```text
.env.dev
.env.prod
```

启动前可以根据部署环境创建 `.env`：

```bash
cp .env.dev .env
```

Windows PowerShell：

```powershell
Copy-Item .env.dev .env
```

请检查配置文件中的：

- NoneBot2 运行配置；
- OneBot v11 连接配置；
- NapCat 地址和端口；
- LM Studio 地址；
- 模型名称；
- 群聊白名单；
- 日志或数据目录。

不要提交包含以下内容的 `.env`：

- QQ 登录凭证；
- Access Token；
- API Key；
- WebUI 密码；
- 内网地址；
- 私人群号；
- 其他敏感配置。

## 启动

具体启动参数可能随版本变化，请优先阅读：

```text
STARTCOMMAND.md
```

常见的 NoneBot2 启动方式：

```bash
nb run
```

或者：

```bash
python -m nonebot
```

实际启动命令以当前仓库配置为准。

启动前确认：

- LM Studio API 已启动；
- 本地模型已经加载；
- NapCat 已登录；
- OneBot v11 通信正常；
- `.env` 配置正确；
- Agent 配置文件存在；
- 机器人账号已加入目标群聊。

## 消息处理流程

```text
用户在群聊中 @机器人
        │
        ▼
NoneBot2 接收 OneBot v11 事件
        │
        ▼
检查群聊白名单和消息内容
        │
        ▼
保存群聊消息到 SQLite
        │
        ▼
读取近期群聊上下文
        │
        ▼
拼接当前用户问题
        │
        ▼
启动 PI Coding Agent
        │
        ▼
调用 LM Studio 本地模型
        │
        ▼
解析模型输出
        │
        ▼
写入思考日志
        │
        ▼
分段发送 QQ 回复
```

## 数据与日志

项目运行时可能生成或使用：

```text
pi_agent_core/agent_memory.db
stella_thought_logs.md
```

其中可能包含：

- QQ 群号；
- QQ 用户 ID；
- 群聊文本；
- AI 生成内容；
- 模型思考或动作信息；
- 时间戳；
- 运行错误。

建议：

- 将运行数据放在独立目录；
- 将日志和数据库加入 `.gitignore`；
- 不要把生产日志上传到公开仓库；
- 对外分享日志前进行脱敏；
- 定期清理不再需要的历史记录。

## 安全与隐私说明

### 本地模型不等于绝对安全

虽然推理请求默认发送到本地 LM Studio，但以下内容仍可能暴露在本机环境中：

- 群聊消息；
- 用户 ID；
- 思考日志；
- SQLite 数据库；
- Agent 输出；
- 系统日志。

请确保运行机器的账户、磁盘和备份受到保护。

### QQ 账号风险

使用自动化 QQ 机器人可能受到平台规则、账号风控和网络环境影响。请：

- 使用专用账号；
- 控制消息频率；
- 仅在明确授权的群聊中使用；
- 不要用于骚扰、刷屏或自动化违规行为；
- 遵守 QQ、NapCat、OneBot 和相关模型服务的使用规则。

### Agent 权限

当前项目通过子进程调用 PI Coding Agent。运行账号对文件系统、网络和进程的权限会影响整体安全性。

建议：

- 使用低权限系统用户运行；
- 不要在生产服务器上直接运行；
- 不要给机器人账号不必要的文件权限；
- 将模型、机器人和日志运行在隔离环境中；
- 本地服务默认只监听回环地址。

## 开发

### 修改 Python 插件

Python 插件主要位于：

```text
stella_project/plugins/bot_main/
```

修改消息流程时，重点关注：

- 事件过滤；
- 群聊白名单；
- 异步锁；
- 子进程生命周期；
- 超时处理；
- 输出解析；
- 日志写入；
- QQ 消息发送。

### 修改 Agent 桥接层

TypeScript 桥接层位于：

```text
pi_agent_core/agent_bridge.ts
```

修改时应确认：

- 输入是否为合法 JSON；
- 模型提供者是否存在；
- 模型名称是否正确；
- system prompt 路径是否有效；
- Agent 会话是否能够正常创建；
- 输出是否始终返回可解析的 JSON；
- 异常是否返回明确的错误状态。

### 本地验证

提交前建议执行：

```bash
python -m compileall stella_project
```

如果项目配置了测试命令，则进一步运行：

```bash
pytest
```

同时检查：

```bash
git diff
git status
```

不要提交运行产生的数据库、日志、缓存、模型文件或本地环境配置。

## 常见问题

### 机器人没有回复

请检查：

1. QQ 账号是否已登录；
2. NapCat 是否正常运行；
3. OneBot v11 是否连接成功；
4. 机器人是否在允许的群聊中；
5. 消息是否正确 `@` 机器人；
6. NoneBot2 是否正常启动；
7. LM Studio API 是否可访问；
8. 模型是否已经加载；
9. `models.json` 中的模型名称是否正确；
10. 控制台是否出现 Agent 错误。

### Agent 调用失败

检查：

```bash
npx pi --help
```

并确认：

- Node.js 已安装；
- npm 可以访问所需包；
- PI Coding Agent 配置正确；
- `pi_agent_core` 路径没有移动；
- system prompt 文件存在；
- LM Studio 服务已经启动。

### 回复超时

本地模型推理时间受以下因素影响：

- 模型规模；
- 量化方式；
- GPU 显存；
- CPU 性能；
- 上下文长度；
- LM Studio 当前负载；
- 同时运行的其他程序。

可以先使用更小的模型验证完整链路，再逐步提高模型规模。

### 日志或数据库越来越大

项目会保存群聊记录和运行日志。请定期：

- 备份重要数据；
- 清理不需要的日志；
- 归档或删除历史 SQLite 数据；
- 检查磁盘空间；
- 避免将日志目录同步到公共云盘。

## 版本

当前仓库公开的最新 Release：

```text
v1.1.0
```

查看发布页：

[Releases](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases)

使用稳定版本：

```bash
git fetch --tags
git checkout v1.1.0
```

开发分支可能包含尚未完成或未充分验证的功能。

## 许可证

使用、修改或再分发本项目之前，请以仓库中的正式 `LICENSE` 文件和对应 Release 说明为准。

如果仓库没有提供明确的许可证文件，则默认不代表代码可以自由复制、修改或再分发。建议在项目正式发布前补充明确的开源许可证。

## 免责声明

本项目仅用于学习、研究和个人实验。

使用者需要自行承担以下风险：

- QQ 账号登录和自动化运行风险；
- 本地模型输出不准确或不符合预期的风险；
- 日志、数据库和群聊内容泄露风险；
- 第三方组件和平台政策变化带来的风险；
- 错误配置导致的服务异常或数据损失。

请在获得必要授权的前提下使用本项目，并遵守相关平台、软件和模型服务的使用条款。

## 致谢

- [NoneBot2](https://github.com/nonebot/nonebot2)
- [OneBot](https://onebot.dev/)
- [NapCat](https://github.com/NapNeko/NapCatQQ)
- [LM Studio](https://lmstudio.ai/)
- [PI Coding Agent](https://github.com/earendil-works/pi-coding-agent)

## 项目地址

[https://github.com/Eternal-Wanderer-Vegetable/Stella_project](https://github.com/Eternal-Wanderer-Vegetable/Stella_project)
```