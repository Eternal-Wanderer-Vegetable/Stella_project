# Stella Project

> 面向 QQ 群聊的本地 AI 对话插件，基于 NoneBot2、OneBot v11、PI Coding Agent 和 LM Studio 构建。

[![GitHub Stars](https://img.shields.io/github/stars/Eternal-Wanderer-Vegetable/Stella_project)](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/stargazers)
[![Latest Release](https://img.shields.io/github/v/release/Eternal-Wanderer-Vegetable/Stella_project?display_name=tag)](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases)
[![License](https://img.shields.io/badge/license-see%20repository%20files-lightgrey)](https://github.com/Eternal-Wanderer-Vegetable/Stella_project)

## 项目简介

Stella Project 是一个用于 QQ 群聊的本地 AI 对话插件。

项目通过 NoneBot2 和 OneBot v11 接收群消息，在满足群号白名单和 `@机器人` 触发条件时，将当前问题以及近期群聊记录发送给 PI Coding Agent。PI Coding Agent 再通过 LM Studio 的 OpenAI 兼容接口调用本地大语言模型，最后由插件解析并发送回复。

当前仓库主要包含：

- NoneBot2 消息处理插件；
- PI Coding Agent 调用桥接代码；
- LM Studio 模型配置；
- 记忆系统实验性扩展；
- NapCat 看门狗代码。

> 当前仓库是插件和 Agent 扩展源码，不是一个包含完整 NoneBot 启动入口的独立应用工程。仓库中目前没有 `pyproject.toml`、`requirements.txt`、`.env` 模板或可直接执行的启动脚本，需要将代码接入已有的 NoneBot2 工程后使用。

## 当前状态

当前 `main` 分支包含以下源码：

- QQ 群消息监听和 AI 回复；
- 群聊白名单过滤；
- 本地 SQLite 群聊记录；
- 近期群聊上下文拼接；
- PI Coding Agent 子进程调用；
- LM Studio 本地模型配置；
- AI 输出解析和回复分段发送；
- 基于 SQLite 的记忆系统代码；
- NapCat 空闲检测和重启逻辑。

记忆系统目前仍处于开发阶段。虽然仓库包含用户画像、短期上下文和长期记忆的数据访问代码，但当前入口插件主要使用 `group_messages` 表保存近期群聊记录，记忆扩展中的部分能力尚未形成完整的自动调用流程。

## 系统架构

```text
QQ 群聊
   │
   ▼
NapCat / OneBot v11
   │
   ▼
NoneBot2 宿主工程
   │
   ▼
stella_project/plugins/bot_main
   │
   ├── 群号白名单检查
   ├── @机器人触发检查
   ├── 群聊记录写入 SQLite
   ├── 近期消息读取
   ├── Prompt 组装
   ├── 启动 PI Coding Agent
   ├── 解析模型输出
   └── 发送 QQ 回复
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

## 目录结构

```text
Stella_project/
├── pi_agent_core/
│   ├── agent_bridge.ts
│   ├── models.json
│   └── extensions/
│       └── memory_system/
│           ├── consolidator.ts
│           ├── consolidator_prompt.ts
│           ├── db.ts
│           ├── index.ts
│           ├── llm_provider.ts
│           └── types.ts
│
├── stella_project/
│   └── plugins/
│       └── bot_main/
│           ├── __init__.py
│           ├── ai_gateway.py
│           ├── config.py
│           └── watchdog.py
│
├── .gitignore
└── README.md
```

### Python 插件

| 文件 | 作用 |
| --- | --- |
| `ai_gateway.py` | 群消息监听、消息过滤、上下文读取、PI Agent 调用、输出解析和 QQ 回复 |
| `config.py` | 插件配置入口，当前内容较少 |
| `watchdog.py` | 监控消息事件，并在长时间无事件时尝试重启 NapCat |
| `__init__.py` | NoneBot 插件入口和元数据 |

### PI Agent 核心

| 文件 | 作用 |
| --- | --- |
| `agent_bridge.ts` | 通过标准输入接收 JSON，创建 PI Agent 会话并调用本地模型 |
| `models.json` | PI Agent 的 LM Studio 提供者和模型配置 |

### 记忆系统扩展

| 文件 | 作用 |
| --- | --- |
| `index.ts` | PI Agent 扩展入口，目前注册生命周期事件并清空 Agent 工具列表 |
| `db.ts` | SQLite 记忆仓库，包含用户画像、短期上下文和长期记忆表 |
| `types.ts` | 记忆系统数据类型 |
| `llm_provider.ts` | 在线 OpenAI 兼容接口和本地 SLM 接口 |
| `consolidator.ts` | 记忆整理相关逻辑 |
| `consolidator_prompt.ts` | 记忆整理 Prompt |

## 功能说明

### 群号白名单

当前 AI 回复仅针对源码中配置的允许群号生效。

在：

```text
stella_project/plugins/bot_main/ai_gateway.py
```

中修改 `ALLOWED_GROUPS`，将目标群号加入集合。

建议不要把真实群号、账号信息和私人配置直接提交到公开仓库。

### 触发条件

AI 回复处理通常需要同时满足：

1. 消息来自允许的群聊；
2. 消息确实 `@` 机器人；
3. 消息正文不为空。

未满足条件的消息不会调用模型。

### 群聊上下文

插件会将允许群聊中的普通文本消息写入 SQLite，并读取最近若干条消息作为上下文。

当前数据库路径由 `ai_gateway.py` 计算，默认位于：

```text
pi_agent_core/agent_memory.db
```

数据库中可能包含：

- 群号；
- 用户 ID；
- 群聊文本；
- 消息时间；
- 其他运行时记录。

该文件已被 `.gitignore` 忽略，不应上传到公开仓库。

### Agent 调用

Python 插件通过子进程调用 PI Coding Agent，核心参数包括：

```text
--provider lm-studio
--model stella-local
--system-prompt <system prompt 路径>
--extension <memory_system/index.ts 路径>
-p <当前 Prompt>
```

调用时会设置工作目录为：

```text
pi_agent_core/
```

因此不要随意移动 `pi_agent_core` 目录，除非同步修改路径计算逻辑。

### 输出解析

插件会尝试从模型结果中提取：

- 思考内容；
- 动作内容；
- 最终回复。

如果模型输出格式不完整，代码会尝试使用剩余文本作为回复。回复还会经过简单清理，并最多分成若干段发送到 QQ。

### 并发控制和超时

当前实现使用全局异步锁控制 Agent 调用：

- 同一时间只处理一个模型请求；
- 单次 Agent 调用存在超时限制；
- 调用失败时返回兜底文本；
- 错误写入 NoneBot 日志。

如果本地模型推理速度较慢，可能需要根据实际硬件调整超时和并发策略。

## 本地模型配置

当前 `pi_agent_core/models.json` 使用 LM Studio 的 OpenAI 兼容接口：

```json
{
  "providers": {
    "lm-studio": {
      "name": "LM Studio Local",
      "baseUrl": "http://127.0.0.1:1234/v1",
      "api": "openai-completions",
      "apiKey": "lm-studio",
      "models": [
        {
          "id": "stella-local",
          "name": "Stella Local Model",
          "contextWindow": 32768,
          "maxTokens": 4096
        }
      ]
    }
  }
}
```

使用前需要：

1. 安装并启动 LM Studio；
2. 加载一个本地大语言模型；
3. 启动 OpenAI 兼容 API 服务；
4. 确认服务监听在 `127.0.0.1:1234`；
5. 确认模型名称与配置一致。

如果 LM Studio 使用其他端口或模型名称，需要同步修改：

```text
pi_agent_core/models.json
stella_project/plugins/bot_main/ai_gateway.py
```

## `agent_bridge.ts`

`agent_bridge.ts` 是一个独立的 TypeScript Agent 桥接入口。

它从标准输入读取 JSON，例如：

```json
{
  "prompt": "你好，介绍一下你自己"
}
```

成功时输出类似：

```json
{
  "status": "success",
  "reply": "..."
}
```

失败时输出类似：

```json
{
  "status": "error",
  "error": "..."
}
```

该文件使用：

- `@earendil-works/pi-coding-agent`；
- `lm-studio` provider；
- `stella-local` model；
- `pi_agent_core/prompt.txt` 作为角色设定（如果文件存在）。

当前仓库没有提交 `package.json` 或锁定的 Node.js 依赖配置，因此需要在宿主工程中自行准备对应的 Node.js/PI Agent 环境。

## 记忆系统

记忆系统代码位于：

```text
pi_agent_core/extensions/memory_system/
```

SQLite 数据库包含三类数据：

### 用户画像

```sql
user_profiles
```

保存：

- 用户 ID；
- 昵称；
- 性格特征；
- Agent 对用户的态度；
- 互动次数；
- 更新时间。

### 短期上下文

```sql
short_term_context
```

保存：

- 群号；
- 当前摘要；
- 待处理话题；
- 更新时间。

### 长期记忆

```sql
long_term_memories
```

保存：

- 群号；
- 用户 ID；
- 记忆摘要；
- 重要程度；
- 访问次数；
- 最近访问时间。

当前长期记忆查询使用关键词匹配和简单权重排序，不是向量数据库检索。代码注释中提到未来可以接入 `sqlite-vec`，但当前仓库没有实现该依赖。

### 当前扩展入口的行为

`memory_system/index.ts` 当前主要做以下事情：

- 输出扩展加载日志；
- 监听 Agent 生命周期事件；
- 调用 `pi.setActiveTools([])` 清空 Agent 工具；
- 返回一个没有工具的扩展定义。

因此，记忆数据库代码和扩展生命周期代码目前并不等同于“已经完整接通的自动记忆功能”。

## 接入 NoneBot2 宿主工程

当前仓库没有完整的 NoneBot2 启动工程。使用时需要先准备一个已有的 NoneBot2 项目，并确保宿主工程包含：

- Python 3.10 或更高版本；
- NoneBot2；
- OneBot v11 适配器；
- `nonebot-plugin-apscheduler`；
- `httpx`；
- 可用的 Node.js 和 npm；
- 可调用的 PI Coding Agent；
- NapCat 或其他 OneBot v11 实现。

将以下目录复制到宿主工程的插件目录，或通过 Python 包路径使其可被加载：

```text
stella_project/plugins/bot_main/
```

同时保留：

```text
pi_agent_core/
```

因为 `ai_gateway.py` 会通过项目路径查找该目录。

宿主工程还需要自行提供：

- NoneBot2 配置文件；
- OneBot v11 连接配置；
- QQ 登录和 NapCat 配置；
- 插件加载配置；
- 依赖安装方式；
- 启动命令。

本仓库当前没有提供通用的 `nb run` 启动入口，因此不能直接在仓库根目录执行：

```bash
nb run
```

除非你已经将它放入一个完整的 NoneBot2 宿主项目中。

## NapCat 看门狗

`watchdog.py` 使用 APScheduler 每分钟检查一次消息事件时间。

当超过一段时间没有消息事件时，代码会尝试调用 NapCat WebUI 重启接口：

```text
http://127.0.0.1:6099/api/Process/Restart
```

重启接口属于高权限管理接口。部署前必须：

- 确认 NapCat WebUI 地址；
- 确认 API Token；
- 不要把 Token 硬编码到公开仓库；
- 将 Token 改为环境变量或宿主工程配置；
- 确认机器人运行账户有合适的权限；
- 先在测试账号和测试环境中验证重启逻辑。

当前源码中的看门狗配置仍属于开发状态，建议在生产环境启用前重新设计认证、失败重试、冷却时间和健康检查逻辑。

## 安全与隐私

### 群聊数据

插件会读取和保存允许群聊中的文本消息。使用前请确认：

- 已获得群聊使用授权；
- 已告知相关用户可能存在本地记录；
- 数据库和日志目录权限受控；
- 不要将数据库提交到 Git；
- 不要将群聊内容上传到公共服务。

### 角色设定

以下文件可能被用于角色设定：

```text
pi_agent_core/SYSTEM.md
pi_agent_core/prompt.txt
```

这些文件可能包含：

- 人设 Prompt；
- 内部规则；
- 私人信息；
- API 配置；
- 运行环境信息。

不要把敏感内容提交到公开仓库。

### 网络服务

默认 LM Studio 地址为回环地址：

```text
127.0.0.1
```

建议不要将 LM Studio 或 NapCat WebUI 直接暴露到公网。

### 凭证管理

不要将以下内容写入源码：

- NapCat Token；
- QQ 登录凭证；
- API Key；
- WebUI 密码；
- 私人群号；
- 内网地址；
- 其他服务凭证。

仓库的 `.gitignore` 已忽略部分本地配置和数据文件，但使用者仍需检查提交内容：

```bash
git status
git diff --cached
```

## 开发与验证

当前仓库没有测试目录、CI 配置或统一构建脚本。修改代码后，可以先执行基础语法检查：

```bash
python -m py_compile \
  stella_project/plugins/bot_main/__init__.py \
  stella_project/plugins/bot_main/ai_gateway.py \
  stella_project/plugins/bot_main/config.py \
  stella_project/plugins/bot_main/watchdog.py
```

如果宿主工程配置了 TypeScript 工具链，再对 Agent 代码执行对应的类型检查或编译。

建议至少进行以下手动验证：

1. NoneBot2 可以加载插件；
2. 非白名单群聊不会触发回复；
3. 未 `@` 机器人时不会触发 AI；
4. 群聊记录可以写入 SQLite；
5. 近期上下文能够正确读取；
6. LM Studio API 可以访问；
7. PI Agent 可以正常启动；
8. 模型超时后程序仍能继续处理后续消息；
9. NapCat 重启接口只在明确需要时启用；
10. 日志和数据库不会被提交到仓库。

## 已知限制

- 仓库没有独立的 Python 打包配置；
- 仓库没有完整的 NoneBot2 启动入口；
- 仓库没有固定的 Python 依赖文件；
- 仓库没有固定的 Node.js `package.json`；
- 记忆系统尚未完全接入主对话流程；
- 当前长期记忆使用 SQLite 关键词匹配，不是向量检索；
- Agent 工具在记忆扩展生命周期中会被清空；
- 模型名称和 LM Studio 地址需要手动保持一致；
- 群号白名单目前位于源码中；
- NapCat 重启配置需要重新进行安全加固；
- 当前仓库没有自动化测试和 CI 验证。

## 许可证

当前仓库目录中未发现明确的 `LICENSE` 文件。

在仓库补充正式许可证之前，不能默认代码可以被自由复制、修改或再分发。使用者应遵循仓库所有者的授权范围，并在项目发布前补充合适的开源许可证。

## 免责声明

本项目仅用于学习、研究和个人实验。

使用者需要自行承担：

- QQ 账号自动化运行风险；
- 平台规则和账号风控风险；
- 本地数据库和群聊数据泄露风险；
- 模型输出错误或不符合预期的风险；
- NapCat 重启配置不当导致的服务中断风险；
- 第三方软件和模型服务变化带来的兼容性风险。

请在获得必要授权并充分了解运行环境的前提下使用本项目。

## 项目地址

[https://github.com/Eternal-Wanderer-Vegetable/Stella_project](https://github.com/Eternal-Wanderer-Vegetable/Stella_project)
