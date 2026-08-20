<div align="center">

# 🌟 Stella

*一个依托记忆系统进行拟人化聊天的 QQ 群聊机器人 —— 完全本地运行，不外传任何聊天内容*

[![CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/workflows/ci.yml/badge.svg)](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![NoneBot2](https://img.shields.io/badge/NoneBot-2-ea5252)](https://nonebot.dev/)
[![OneBot V11](https://img.shields.io/badge/OneBot-V11-black)](https://onebot.dev/)
[![Rust](https://img.shields.io/badge/Rust-1.75%2B-dea584?logo=rust&logoColor=white)](https://www.rust-lang.org/)
[![Tauri](https://img.shields.io/badge/Tauri-2-24C8DB?logo=tauri&logoColor=white)](https://tauri.app/)

</div>

---

Stella 不只是把消息丢给大模型换一句回复。它把群聊里零散的信息**沉淀成可检索、可验证、会遗忘的记忆**，并在合适的时机主动开口了解你。

全部推理在本机完成 —— 聊天用 GPU 上的大模型，记忆整理用 CPU 上的小模型，互不抢占资源。**没有任何一条群聊内容离开你的机器。**

## ✨ 特性

- **🧠 两层记忆过滤** —— 捕获宽松（允许不确定信息进入候选），晋升严格（置信度分档 + 交叉验证 + 每用户配额）。过滤发生在有数据、可审计、可回滚的那一层，而不是 prompt 里

- **🔍 记忆需要证据** —— 同一件事被反复提到才会累积置信度；用户直接对 Bot 说的话视为高密度证据，单次即可采信；长期无新证据的候选自动淘汰

- **💬 主动获取信息** —— 群聊被动摄入的信息密度极低，因此 Stella 会主动 @ 活跃用户搭话或确认记忆。有每日配额、用户级冷却与「连续无回应即退避」保护

- **🎯 记忆分区注入** —— 聊天素材与行为约束严格分离，敏感信息（边界、忌口、冲突）永不作为聊天话题被提起

- **🏠 多群共享空间** —— 多个 QQ 群可归入同一空间，共享用户画像、长期记忆与人格；而消息尾巴、话题状态、静音开关仍按群隔离，不会在 A 群回应 B 群的对话

- **🗜 长对话不断线** —— 滚出上下文窗口的早期对话自动压缩成回顾，三层上下文按消息 id 划分绝不重叠

- **🔎 混合检索** —— SQLite FTS5 全文索引 + 多维加权排序，可选接入本地 embedding 语义检索，服务不可用时自动降级

- **♻️ 会遗忘** —— 按记忆类型设定生命周期，低价值记忆自动归档，长记忆拆分为原子事实

- **🔌 可扩展** —— Pipeline 前后置 Hook 机制，扩展目录自动加载

- **🧪 可验证** —— 490+ 单元测试覆盖记忆晋升、跨用户隔离、两层归属、防编造护栏；另有探针脚本对真实模型做回归验证（含一个专门复现「噪音环境下漏掉信息」的用例）

## 🚀 快速开始

### 📦 下载（普通用户）

**不需要 clone、不需要自己装 Python。** 到 [Releases](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases) 下载最新的 `Stella-*-win64.zip`，解压后有两种启动方式：

- **图形界面（推荐）**：双击 `Stella.exe`，首次运行会自动下载约 100MB 的嵌入式 Python 并安装依赖；之后每次启动自动跑一遍环境自检——尚未配置会打开「配置」页，有阻塞问题会打开「环境自检」页，一切正常则直接进入「运行状态」页。
- **命令行**：双击 `start.bat`，同样会自动下载 Python 并安装依赖，然后进入配置向导并启动 Bot。

> **杀软提示**：首次运行会下载并运行 Python，部分杀软可能拦截，需将目录加入信任列表。

### 环境要求

| 组件 | 要求 |
|---|---|
| Python | 3.10+（Release 包内置嵌入式 Python，无需自装） |
| 框架 | [NoneBot 2](https://nonebot.dev/) |
| QQ 协议端 | [NapCat](https://github.com/NapNeko/NapCatQQ) 或其他 OneBot V11 实现（推荐用 [NapCatQQ Desktop](https://github.com/NapNeko/NapCatQQ-Desktop) 安装并登录） |
| 模型服务 | [LM Studio](https://lmstudio.ai/)（需 OpenAI 兼容接口，也可以提供APIkey接入在线LLM） |

### 安装

**普通用户**：见上方「下载」——下载 Release 的 zip，解压后双击 `Stella.exe` 或 `start.bat` 即可，无需自行安装 Python。

**开发者**（clone 源码调试）：

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
```

### 配置

**普通用户（推荐）**：在 `Stella.exe` 的「配置」页填写群号、连接方式、地址与两个模型 ID，保存后写入项目根目录的 `.env`；模型列表可从本机 LM Studio 自动读取（也可手工输入），避免手打完整 ID 漏掉 `google/` 前缀。

**开发者**：可用交互式向导生成 `.env`——只需回答 5 个必答项（群号、连接方式、地址、两个模型 ID），
**模型 ID 会从 LM Studio 拉列表让你选编号**：

```bash
python -m deploy init
```

若偏好手工配置，也可复制模板后自行修改：

```bash
cp .env.example .env
```

至少需要填写如下数据：

```env
ALLOWED_GROUPS=123456789          # 允许响应的群号，多个用逗号分隔
LM_STUDIO_BASE_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=your-chat-model    # 主聊天模型
CONSOLIDATION_LM_STUDIO_MODEL=your-small-model  # 记忆整理模型（建议 CPU 推理）
```

多群部署若需要共享画像与记忆，另见 `config/spaces/`（[配置文档](docs/configuration.md) 的「群组共享空间」一节）。单群部署无需配置，程序会自动分配空间标识。

完整配置项见 **[配置文档](docs/configuration.md)**。

### 启动

**普通用户**：在 `Stella.exe` 的「运行状态」页点「启动」（会先跑一遍 doctor 自检）；或双击 `start.bat` 走命令行流程。

**开发者**：

```bash
# 1. 安装依赖
pip install -r requirements.txt
# 2. 生成配置
python -m deploy init
# 3. 用 NapCatQQ Desktop 安装并登录 NapCat（需扫码，必须人工），
#    在 NapCat WebUI 的网络配置里添加「WebSocket 客户端」指向 Bot（反向 WS）：
#    ws://127.0.0.1:8080/onebot/v11/ws
#    （若用正向 WS 则改在 .env 里配 ONEBOT_WS_URLS）
# 4. 启动 Stella（会先跑一遍 doctor 自检）
python -m deploy start
```

在群里 @ 机器人即可开始对话。

## 📖 文档

| 文档 | 内容 |
|---|---|
| [架构说明](docs/architecture.md) | 目录结构、消息处理流程、模块职责 |
| [记忆系统](docs/memory-system.md) | 两层过滤的设计理由、晋升规则、检索策略 |
| [配置参考](docs/configuration.md) | 全部配置项与调参建议 |
| [开发指南](docs/development.md) | 测试、探针脚本、CI、贡献流程 |

> 设计过程记录（规范草案、检查点、缺陷报告）在 [`design_docs/`](design_docs/)。

## 🧠 记忆形成流程

```mermaid
graph LR
    A[群聊消息] --> B[短期摘要]
    B --> C[记忆候选]
    C -->|证据不足| C
    C -->|置信度 + 交叉验证| D[长期记忆]
    D --> E[Policy 过滤]
    E --> F[分区注入 Prompt]
    D -->|超期 / 低价值| G[归档]
```

三条设计原则：

1. **捕获宽，晋升严。** 允许不确定的信息先进入候选并如实标注置信度，但只有经过复现或高密度证据确认的才成为长期记忆。在 prompt 里做过滤不可审计、不留数据、无法改进。且小模型会根据过滤要求设定的正面提示词/负面提示词做出过度反应，不具备任何实用价值。
2. **有价值的信息不会很多。** 每个用户的长期记忆有明确且可调整的数量上限，到顶后新记忆必须挤掉最弱的一条。
3. **相关 ≠ 应该使用。** 检索到的记忆还要经过模式匹配、用途兼容、可见性三层过滤才能进入回复。

整合分两阶段执行，各用适合的模型：

| 阶段 | 任务 | 模型 |
|---|---|---|
| 阶段 1 | 短期摘要 + 用户画像 + 「本批是否含自我披露」判断 | CPU 上的小模型 |
| 阶段 2 | 精确提取记忆候选 | GPU 上的主聊天模型 |

阶段 2 只在阶段 1 判定有自我披露时唤醒 —— 日常刷屏与寒暄不消耗 GPU。这样拆是因为小模型能总结主题，却在噪音环境下会把候选提取判空（实测：信息明确出现在它自己写的摘要里，但候选返回空数组）。

> 细节见 [记忆系统文档](docs/memory-system.md)。

## 🛠 技术栈

**Bot 后端**：`NoneBot 2` · `OneBot V11` · `SQLite (FTS5)` · `LM Studio` · `APScheduler` · `httpx`

**桌面安装器**：`Tauri 2` · `Rust`（`stella-installer/`，原生 HTML/JS 前端，无前端构建步骤）

**开发与验证**：`pytest` · `ruff` · `pyright`

### 开发中使用的本地模型

- 语言模型：`google/gemma-4-26b-a4b-qat`（聊天，GPU）、`google/gemma-4-e4b`（记忆整理，CPU）
- 向量模型：`text-embedding-qwen3-embedding-0.6b`

关键在于**分工与部署**：整合模型设置 GPU Offload = 0 走纯 CPU 推理，聊天/提取模型独占 GPU。两者同时常驻、互不挤显存，因此记忆整理与聊天可以真正并行。这是两阶段方案可行的前提。

应用层为每个模型设了串行闸门（LM Studio 本身不限并发，多请求同时打到同一模型只会互相拖慢）。

> 以上是开发者基于自身设备的配置，仅作为理解代码库的补充，**不构成配置建议**。如果你探索出了更好的方案，欢迎提交 PR 和 issue。
>
> 开发过程中测试用模型可能变更，具体会在 release 说明中标注。

## 🤝 贡献

欢迎 issue 与 PR。提交前请确认：

```bash
python -m pytest tests -q
ruff check .
```

> 详见 [开发指南](docs/development.md)。

## 📄 License

本项目基于 **[GNU Affero General Public License v3.0](LICENSE)** （AGPL v3.0）发布。详见 LICENSE 文件与各源文件头部的版权声明。

## 💛 致谢

本项目在开发过程中得到了很多人和组织的鼓励和支持：

- 我的父母给予了最重要的经济支持。没有他们，这一切都无从开始。
- 灵感来源于和 [@t1mb2rg](https://github.com/t1mb2rg) 的讨论和 [@CST-Cat](https://github.com/CST-Cat) 的争执中。感谢他们贡献了属于自己的想法。
- [@MIO-456](https://github.com/MIO-456) 开发的 [Lumi_Nox](https://github.com/MIO-456/Lumi_Nox) 项目激励了本项目的开发。
- 感谢 [@qian-o](https://github.com/qian-o) 和他的伙伴们，以及 [@MIO-456](https://github.com/MIO-456) 和他的伙伴们。没有他们的鼓励，就没有最初开发这个项目的动力。
- 本项目开发中得到了来自如下组织的支持：
  - **模型提供商**：Deepseek，OpenAI（ChatGPT），Google（Gemini，Gemma）和通义千问（text-embedding-qwen3-embedding-0.6b）。没有他们的优秀模型作为基础，这个项目不可能诞生。
  - **Coding Agent**：[Opencode](https://github.com/anomalyco/opencode)，感谢 Opencode 对本项目的大力支持。
  - **开源代码库**：[nonebot2](https://github.com/nonebot/nonebot2)，[NapCatQQ](https://github.com/NapNeko/NapCatQQ)，以及源代码中引用的所有第三方库。向与之相关的所有开发与维护者致敬。此外本项目也是为了向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 与 [MaiBot](https://github.com/Mai-with-u/MaiBot) 两位前辈看齐，创造一个真正的、能够完整本地循环、不泄露任何群聊信息和个人隐私的 AI 朋友。
  - **开发者社区**：[Linux Do](https://linux.do)
- 特别致谢 Freya，这是献给你的作品。我的探索之旅因你的馈赠而起，是时候交出一份并不完美的回礼了。

## ⚠️ 免责声明

**在使用本项目的部分或者全部代码时，请遵守您所在国家/地区的相关法律和您所接入相关平台的用户协议中的相关条款。全体开发者无法且没有任何义务为使用者使用该项目所造成的任何直接/间接后果负责**（包括但不限于账号封禁，任何直接/间接的经济损失，任何的民事/刑事责任等）。
