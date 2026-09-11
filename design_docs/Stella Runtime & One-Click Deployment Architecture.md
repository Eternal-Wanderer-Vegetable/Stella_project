# Stella Runtime & One-Click Deployment Architecture

> **Project:** Stella  
> **Document Type:** Engineering Architecture / Deployment Design  
> **Status:** Proposed  
> **Version:** 1.0  
> **Last Updated:** 2026-09-11

---

## 1. 文档目的

本文档定义 Stella 从当前“机器人应用程序”向“完整本地 AI Bot Runtime”演进后的运行时与一键部署架构。

本方案的核心目标不是简单地将 Stella、NapCat 和 llama.cpp 打包到同一个安装包中，而是建立一个统一的：

> **Stella Runtime**

由 Runtime 负责管理 Stella Core、NapCat、llama.cpp、模型以及相关运行环境，使最终用户无需手动配置 Python、NoneBot、OneBot、LLM 推理后端或大量配置文件，即可完成 Stella 的安装、启动、更新和故障恢复。

同时，该架构需要兼容：

- Windows Desktop
- 本地 NVIDIA GPU
- 本地 CPU / 其他 GPU Backend
- Docker / Linux Server
- OpenAI-compatible 外部 LLM
- LM Studio / Ollama 等第三方本地 LLM
- AstrBot Plugin 兼容层
- Stella Memory System
- 后续独立 GUI

---

# 2. 核心设计目标

## 2.1 一键部署

最终用户理想体验：

```text
安装 Stella
    ↓
检测系统
    ↓
配置 Runtime
    ↓
安装/配置 NapCat
    ↓
安装 llama.cpp
    ↓
选择/下载模型
    ↓
初始化 Stella
    ↓
登录 QQ
    ↓
完成
```

用户不应被要求手动处理：

- Python
- pip
- NoneBot
- OneBot
- llama.cpp
- GGUF
- CUDA Runtime
- WebSocket
- NapCat 配置
- Stella `.env`

---

## 2.2 Stella Core 与 Runtime 解耦

Stella Core 不应该直接负责：

- 启动 llama.cpp
- 启动 NapCat
- 检测 GPU
- 管理模型文件
- 管理外部进程
- 自动重启崩溃进程

这些职责属于 Runtime Layer。

Stella Core 只需要关心：

```text
Conversation
Memory
Router
Persona
Plugin
LLM Provider
OneBot
```

---

## 2.3 推理后端可替换

llama.cpp 是默认本地推理后端，但不能成为 Stella Core 的硬依赖。

统一抽象：

```text
                LLM Provider
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   llama.cpp      LM Studio      Ollama
        │
        ├── Local GGUF
        │
        └── OpenAI-compatible API
```

未来也可以接入：

```text
OpenAI
其他云端 API
其他 OpenAI-compatible Server
```

因此 Stella Core 永远通过 Provider 接口访问 LLM，而不是直接调用 `llama-server.exe`。

---

# 3. 总体架构

```text
┌────────────────────────────────────────────────────┐
│                    Stella GUI                      │
│                Tauri + Rust Frontend               │
└───────────────────────┬────────────────────────────┘
                        │ IPC
                        ▼
┌────────────────────────────────────────────────────┐
│                Stella Runtime Manager              │
│                    Rust Runtime                    │
│                                                    │
│ Process Manager                                    │
│ Watchdog                                            │
│ Hardware Detection                                  │
│ LLM Manager                                         │
│ Model Manager                                       │
│ NapCat Manager                                      │
│ Configuration Manager                               │
│ Logging / Diagnostics                               │
│ Update Manager                                      │
└───────────────┬───────────────┬────────────────────┘
                │               │
                │               │
                ▼               ▼
       ┌──────────────┐  ┌──────────────┐
       │ Stella Core  │  │ llama-server │
       │              │  │   llama.cpp  │
       │ NoneBot      │  │              │
       │ Memory       │  │ GGUF Model   │
       │ Router       │  │ OpenAI API   │
       │ Plugins      │  └──────────────┘
       │ Persona      │
       └──────┬───────┘
              │
              │ OneBot V11
              ▼
       ┌──────────────┐
       │    NapCat    │
       │              │
       │     QQ       │
       └──────────────┘
```

---

# 4. Runtime 三层模型

Stella Runtime 采用三层结构。

## Layer 1 — Stella Application

Stella 本体。

主要负责：

```text
NoneBot
Conversation
Memory
Router
Persona
Plugin System
AstrBot Compatibility
LLM Decision
Message Processing
```

该层原则上不负责外部进程生命周期。

---

## Layer 2 — Stella Runtime

运行时管理层。

主要负责：

```text
Process Management
Watchdog
LLM Server
Model Management
NapCat
OneBot Runtime
Hardware Detection
Configuration
Logging
Update
Health Check
```

这是整个一键部署体系的核心。

---

## Layer 3 — Installer / GUI

用户交互层。

主要负责：

```text
Installation
First Run
Configuration
Model Selection
QQ Setup
Status
Logs
Updates
Diagnostics
```

GUI 不直接控制底层进程，而是通过 Runtime API / IPC 操作 Runtime。

---

# 5. 推荐进程结构

Windows Desktop 环境：

```text
Stella.exe
    │
    └── Stella Runtime Manager
            │
            ├── stella-core
            │
            ├── llama-server.exe
            │
            └── NapCat / QQ
```

推荐 Runtime Manager 作为生命周期管理中心。

---

## 5.1 进程状态

所有受 Runtime 管理的进程统一采用状态机：

```text
STOPPED
   │
   ▼
STARTING
   │
   ▼
STARTED
   │
   ▼
READY
   │
   ▼
RUNNING
```

异常：

```text
RUNNING
   │
   ▼
CRASHED
   │
   ▼
RESTARTING
   │
   ├── success → READY
   │
   └── failure → FAILED
```

---

# 6. Runtime Manager

Runtime Manager 是整个系统的核心组件。

建议使用 Rust 实现。

原因：

- 进程管理能力强
- Windows/Linux 跨平台
- 内存与生命周期可控
- 适合长期运行
- 与现有 Tauri 架构天然兼容
- 可以作为未来 Docker / Server Runtime 的基础抽象

---

## 6.1 Runtime Manager 职责

### Process Manager

负责：

```text
start
stop
restart
kill
status
PID tracking
stdout/stderr
```

---

### Watchdog

负责：

```text
Process crash detection
Automatic restart
Restart limits
Backoff
Health checks
```

例如：

```text
llama-server 崩溃
       ↓
检测
       ↓
等待 2 s
       ↓
重新启动
       ↓
/health OK
       ↓
恢复 Stella LLM
```

---

### Hardware Detector

负责检测：

```text
CPU
RAM
GPU
VRAM
GPU Vendor
Available backend
```

例如：

```text
NVIDIA
    ↓
CUDA backend

AMD
    ↓
HIP / Vulkan

Intel
    ↓
Vulkan / SYCL

CPU
    ↓
CPU backend
```

---

### Configuration Manager

统一管理：

```text
Stella configuration
LLM configuration
NapCat configuration
OneBot configuration
Runtime configuration
Model configuration
```

避免用户直接编辑底层配置。

---

# 7. LLM Runtime

## 7.1 默认后端

默认本地推理后端：

```text
llama.cpp
    └── llama-server
```

Stella 通过 OpenAI-compatible API 与其通信。

典型结构：

```text
Stella
   ↓
LLM Provider
   ↓
http://127.0.0.1:<port>/v1
   ↓
llama-server
   ↓
GGUF
   ↓
GPU
```

---

## 7.2 Stella 不直接调用 llama.cpp

禁止以下架构成为主架构：

```text
Python
   ↓
ctypes
   ↓
llama.cpp library
```

也不建议：

```text
Stella Core
   ↓
直接管理 llama-server 参数
```

推荐：

```text
Stella Core
   ↓
LLM Provider Interface
   ↓
Runtime-provided endpoint
```

这样 Stella Core 完全不知道后端是什么。

---

# 8. LLM Provider 抽象

建议建立：

```text
LLMProvider
```

概念接口：

```text
get_status()
list_models()
chat()
embedding()
health_check()
```

实现：

```text
LlamaCppProvider
LMStudioProvider
OllamaProvider
OpenAIProvider
CustomOpenAIProvider
```

例如：

```text
LlamaCppProvider
        │
        ▼
http://127.0.0.1:8080/v1
```

而：

```text
OpenAIProvider
        │
        ▼
OpenAI API
```

对 Stella Core 而言，两者完全一致。

---

# 9. 8192 Token Context 约束

Stella 将：

```text
8192 tokens
```

定义为当前产品级上下文约束。

这不是某一个模型的默认值，而是 Stella Runtime 的资源策略。

因此：

```text
Model
   ↓
Runtime
   ↓
Context Policy
   ↓
8192
```

而不是：

```text
Model
   ↓
随模型自由增长
```

这样可以保持：

- 本地 SLM 兼容
- 可预测显存占用
- 可预测延迟
- Memory / Plugin Tool Context 可控
- 云端 API 成本可控

---

# 10. Model Manager

模型不应该作为 Stella 主程序的一部分进行硬编码。

推荐：

```text
models/
├── chat/
├── embedding/
└── reranker/
```

例如：

```text
models/
├── chat/
│   └── qwen-27b-q4.gguf
│
└── embedding/
    └── qwen3-embedding-0.6b.gguf
```

---

## 10.1 模型管理职责

```text
list()
download()
verify()
delete()
activate()
deactivate()
metadata()
compatibility_check()
```

---

## 10.2 模型安装

Stella Installer 本身不应携带大型模型。

推荐：

```text
Stella Installer
       ↓
Model Manager
       ↓
选择模型
       ↓
下载
       ↓
Checksum
       ↓
安装
       ↓
Register
```

---

## 10.3 自定义 GGUF

高级用户允许：

```text
Import GGUF
```

Runtime 自动检查：

```text
Model architecture
Quantization
Context capability
File integrity
Approximate VRAM requirement
```

然后判断：

```text
Compatible
Warning
Unsupported
```

---

# 11. Embedding Runtime

Stella 已经存在 Memory System，因此 embedding 模型应该成为独立 Runtime Resource。

例如：

```text
chat model
    ↓
27B SLM

embedding model
    ↓
Qwen3 Embedding 0.6B
```

两者可以独立运行。

如果硬件资源允许：

```text
Chat Model
+
Embedding Model
```

同时运行。

否则：

```text
Chat Model
      ↓
temporary unload
      ↓
Embedding
```

具体策略由 Runtime 根据资源情况决定。

---

# 12. NapCat Runtime

NapCat 作为 QQ 接入 Runtime。

Stella 不重新实现 QQ 协议。

架构：

```text
QQ
 ↓
NapCat
 ↓
OneBot V11
 ↓
Stella
```

---

## 12.1 NapCat Manager

建议提供：

```text
install()
configure()
start()
stop()
restart()
health_check()
get_version()
get_status()
```

---

## 12.2 NapCat 配置自动化

Stella Runtime 自动生成：

```text
OneBot V11
Reverse WebSocket
```

例如：

```text
NapCat
    ↓
ws://127.0.0.1:<port>/onebot/v11/ws
    ↓
Stella
```

端口由 Runtime 管理。

用户无需手动填写 WebSocket 地址。

---

# 13. NapCat 分发策略

NapCat 不应被简单视为 Stella 自己编写的源代码。

推荐：

```text
Stella Installer
        │
        ├── Stella Runtime
        │
        ├── llama.cpp Runtime
        │
        └── NapCat Runtime
```

各组件保持独立版本信息：

```text
Stella       x.x.x
llama.cpp    x.x.x
NapCat       x.x.x
```

不要通过修改第三方项目源码来实现 Stella 特定功能。

---

## 13.1 第三方依赖原则

Stella 只负责：

```text
Acquire
Configure
Launch
Monitor
Update
```

第三方组件保持自己的：

```text
License
Version
Release
Update lifecycle
```

尤其不要未经确认地将 QQ 客户端等第三方软件直接重新包装成 Stella 的内部资源。

---

# 14. OneBot Adapter

Stella 与 NapCat 之间保持：

```text
OneBot V11
```

作为标准边界。

因此：

```text
NapCat
     ↓
OneBot V11
     ↓
Stella
```

未来甚至可以替换：

```text
NapCat
   ↓
其他 OneBot Implementation
```

而无需修改 Stella Core。

---

# 15. Stella Core

Stella Core 保持现有架构。

主要模块：

```text
Stella Core
│
├── Message Pipeline
├── Conversation Engine
├── AI Router
├── Persona
├── Memory
├── Plugin System
├── AstrBot Compatibility
└── LLM Provider
```

---

## 15.1 AI Optional

AI 不应该成为 Stella 基础运行的硬依赖。

即使：

```text
llama.cpp OFF
```

Stella 仍然应该能够运行：

```text
OneBot
规则匹配
Helldivers 2 Team System
基础命令
插件
基础自动化
```

AI 功能处于：

```text
AI Disabled
```

时，Runtime 不需要启动 LLM Server。

---

# 16. AI 生命周期

推荐：

```text
Stella启动
    ↓
读取 AI Mode
    │
    ├── OFF
    │     ↓
    │   不启动 llama.cpp
    │
    └── ON
          ↓
       检查模型
          ↓
       启动 llama.cpp
          ↓
       Health Check
          ↓
       Stella AI Ready
```

这尤其适合用户在同一台机器上运行游戏与 Stella 的情况。

---

# 17. Runtime Health System

Runtime 应提供统一健康状态：

```text
Runtime Health
│
├── Stella
├── LLM
├── Model
├── NapCat
├── OneBot
├── Memory
└── Plugins
```

例如：

```text
Stella       ● Ready
LLM          ● Ready
Model        ● Loaded
NapCat       ● Ready
OneBot       ● Connected
Memory       ● Ready
Plugins      ● Ready
```

---

## 17.1 Health State

统一：

```text
UNKNOWN
STARTING
READY
DEGRADED
ERROR
STOPPED
```

---

# 18. 日志系统

所有 Runtime Component 的日志统一收集。

目录：

```text
logs/
├── runtime.log
├── stella.log
├── llama.log
├── napcat.log
└── installer.log
```

GUI 可以提供：

```text
Runtime Log
Stella Log
LLM Log
NapCat Log
```

---

# 19. 故障恢复

Runtime 应避免：

```text
一个进程崩溃
      ↓
整个 Stella 停止
```

而采用：

```text
NapCat 崩溃
    ↓
Restart NapCat
    ↓
OneBot reconnect
```

或者：

```text
llama-server 崩溃
    ↓
Restart LLM
    ↓
Stella LLM Provider reconnect
```

Stella Core 本身崩溃：

```text
Restart Stella Core
```

---

## 19.1 Restart Policy

每个组件可以拥有：

```text
max_restart_attempts
restart_delay
backoff
health_timeout
```

例如：

```text
0s
 ↓
2s
 ↓
5s
 ↓
15s
 ↓
30s
```

连续失败后进入：

```text
FAILED
```

避免无限重启。

---

# 20. Runtime Directory

推荐 Windows 目录：

```text
Stella/
│
├── bin/
│   ├── stella.exe
│   └── stella-runtime.exe
│
├── runtime/
│   ├── python/
│   │
│   ├── llama/
│   │   └── llama-server.exe
│   │
│   └── napcat/
│
├── models/
│   ├── chat/
│   ├── embedding/
│   └── other/
│
├── config/
│   ├── stella.toml
│   ├── runtime.toml
│   ├── llm.toml
│   └── onebot.toml
│
├── data/
│   ├── memory/
│   ├── database/
│   └── cache/
│
├── plugins/
│
└── logs/
```

---

# 21. 数据与 Runtime 分离

程序升级不能破坏用户数据。

因此：

```text
runtime/
```

和：

```text
data/
```

必须严格分离。

升级：

```text
runtime → replace
```

而：

```text
data → preserve
```

同样：

```text
models → preserve
config → migrate
```

---

# 22. 配置版本迁移

配置文件需要版本号。

例如：

```toml
config_version = 3
```

升级：

```text
v1
 ↓
Migration
 ↓
v2
 ↓
Migration
 ↓
v3
```

禁止直接假设新版本配置结构与旧版本完全一致。

---

# 23. Installer

Installer 负责首次部署。

流程：

```text
Installer
   ↓
System Check
   ↓
Hardware Detection
   ↓
Runtime Installation
   ↓
NapCat Installation
   ↓
llama.cpp Installation
   ↓
Model Selection
   ↓
Configuration
   ↓
Initialization
   ↓
First Launch
```

---

# 24. System Check

安装前检查：

```text
OS
CPU
RAM
GPU
VRAM
Disk
Permissions
Network
Required Runtime
```

例如：

```text
System
────────────────────

Windows       ✓
RAM 64 GB     ✓
RTX 5080      ✓
VRAM 16 GB    ✓
Disk          ✓
Permissions   ✓
```

---

# 25. 硬件自适应

Runtime 根据硬件决定推荐配置。

例如：

```text
RTX 5080
64 GB RAM
        ↓
Recommended
        ↓
27B Quantized Model
8192 Context
GPU Offload
```

如果资源不足：

```text
27B
 ↓
Warning
 ↓
Recommend 7B / 14B
```

Runtime 可以给出：

```text
Recommended
Possible
Not Recommended
Unsupported
```

而不是简单地禁止运行。

---

# 26. 模型推荐系统

模型选择界面：

```text
Select AI Model

[Recommended]
27B Q4
Good quality / moderate performance

[Lightweight]
7B Q4
Lower resource usage

[Custom]
Import GGUF
```

模型推荐由：

```text
GPU
VRAM
RAM
Context
Quantization
```

综合决定。

---

# 27. 首次启动

首次启动：

```text
Stella
  ↓
Runtime initialization
  ↓
Model verification
  ↓
LLM startup
  ↓
NapCat startup
  ↓
OneBot connection
  ↓
QQ login
  ↓
Stella ready
```

用户最终只需要完成：

```text
QQ Login
```

---

# 28. GUI 架构

现有 Tauri + Rust GUI 可以继续发展。

推荐：

```text
Tauri Frontend
       │
       │ IPC
       ▼
Rust Runtime Manager
       │
       ├── Process Manager
       ├── Model Manager
       ├── LLM Manager
       ├── NapCat Manager
       └── Diagnostics
```

GUI 不应该直接执行：

```text
llama-server.exe
launcher.bat
python.exe
```

而应该请求：

```text
runtime.start("llm")
runtime.restart("napcat")
runtime.status()
```

---

# 29. GUI 功能规划

## Dashboard

```text
Stella
──────────────────────────

QQ          ● Connected
AI          ● Qwen 27B
Memory      ● Ready
Plugins     ● 14 Loaded

GPU         RTX 5080
VRAM        12.4 / 16 GB

LLM Latency  1.8 s

        [Start] [Stop]
```

---

## AI Settings

```text
AI Mode
[ON]

Provider
[Local llama.cpp]

Model
[Qwen 27B Q4]

Context
8192

GPU Offload
Auto
```

---

## Runtime

```text
Stella Core      ●
llama.cpp        ●
NapCat           ●
OneBot           ●
Memory           ●
```

---

# 30. CLI Interface

GUI 之外建议提供 CLI。

例如：

```text
stella start
stella stop
stella restart
stella status
stella logs
stella doctor
stella model list
stella model install
stella model remove
stella update
```

这样服务器部署与自动化脚本可以复用同一套 Runtime。

---

# 31. Doctor / Diagnostics

建议实现：

```text
stella doctor
```

自动检查：

```text
✓ Runtime
✓ Python
✓ llama.cpp
✓ Model
✓ GPU
✓ Configuration
✓ NapCat
✓ OneBot
✓ Port
✓ Stella Core
```

出现问题：

```text
✗ llama-server
  Port 8080 already in use

Suggested fix:
  Change LLM port to 8081
```

这是“一键部署”产品化非常重要的功能。

---

# 32. 更新机制

组件分别拥有版本：

```text
Stella
Runtime
llama.cpp
NapCat
Models
Plugins
```

更新时不要全部覆盖。

例如：

```text
Update Stella
    ↓
Only Stella Runtime/Core updated
    ↓
Models preserved
    ↓
User data preserved
```

---

# 33. Runtime Manifest

建议建立：

```text
runtime-manifest.json
```

记录：

```json
{
    "stella": "...",
    "runtime": "...",
    "llama_cpp": "...",
    "napcat": "...",
    "python": "...",
    "models": []
}
```

Runtime 可以根据 Manifest 判断：

```text
Installed
Missing
Outdated
Corrupted
```

---

# 34. Checksum / Integrity

所有下载的 Runtime 文件都应进行完整性检查。

例如：

```text
Download
   ↓
SHA256
   ↓
Compare
   ↓
Install
```

模型同样如此。

禁止：

```text
Download
 ↓
直接运行
```

---

# 35. 安全边界

Runtime Manager 是高权限组件时必须非常谨慎。

建议：

```text
GUI
 ↓
Runtime IPC
 ↓
Validated Commands
```

而不是允许 GUI 任意执行：

```text
cmd.exe /c <user input>
```

Runtime 应使用明确的操作枚举：

```text
StartComponent
StopComponent
RestartComponent
InstallModel
RemoveModel
```

而不是任意 Shell Command。

---

# 36. Python 与 Rust 边界

推荐最终结构：

```text
                 Tauri
                   │
                   ▼
          Rust Runtime Manager
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
      Python Stella     External Runtime
                           │
                    ┌──────┴──────┐
                    ▼             ▼
                 llama.cpp      NapCat
```

Python 不负责：

```text
Process supervision
System installation
Hardware lifecycle
```

Rust 不负责：

```text
Conversation
Prompt
Persona
Memory logic
Plugin logic
```

---

# 37. IPC

Rust ↔ Python 推荐：

```text
Local IPC
```

可以根据实际实现选择：

```text
stdin/stdout
Named Pipe
Unix Socket
TCP localhost
```

Windows Desktop 优先考虑：

```text
Named Pipe
```

Server / Docker 环境可以使用：

```text
Unix Socket
TCP
```

IPC 协议本身应该保持平台无关。

---

# 38. Docker 架构

桌面版和服务器版不应该维护完全不同的 Stella Core。

推荐：

```text
              Stella Core
                   │
        ┌──────────┴──────────┐
        │                     │
   Desktop Runtime       Server Runtime
        │                     │
        ▼                     ▼
   Windows Process        Docker
```

---

# 39. Docker Compose

服务器版可以采用：

```text
docker-compose.yml
```

逻辑结构：

```text
services:

  stella:
    image: stella
    depends_on:
      - llama

  llama:
    image: llama.cpp

  napcat:
    image: napcat
```

如果某些 QQ/NapCat 环境不适合标准容器化，则保留：

```text
NapCat Adapter
```

作为独立部署选项。

---

# 40. Desktop 与 Server 的共同 Runtime Contract

两种部署方式都实现：

```text
Runtime Contract
```

例如：

```text
start_component()
stop_component()
restart_component()
health_check()
get_status()
get_logs()
```

Desktop：

```text
Rust Process Manager
```

Server：

```text
Docker / Compose Manager
```

Stella Core 不关心底层实现。

---

# 41. 部署形态

最终支持：

```text
                    Stella
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   Desktop         Server          Developer
   Installer       Docker         Source
        │              │              │
   Rust Runtime    Compose        Manual Runtime
```

---

# 42. 资源管理策略

Stella 需要特别考虑“机器人与游戏共享机器”的情况。

因此 Runtime 应允许：

```text
AI Mode ON
AI Mode OFF
```

以及：

```text
LLM Auto Start
LLM Manual Start
LLM On Demand
```

---

## 42.1 推荐 On-Demand 模式

未来可以支持：

```text
Stella启动
    ↓
不启动 LLM
    ↓
检测到需要 AI
    ↓
启动 llama.cpp
    ↓
完成请求
    ↓
保持运行 / Idle Timeout
    ↓
自动关闭
```

这样可以减少：

```text
VRAM
RAM
GPU Load
```

---

# 43. Plugin 兼容性

Stella 当前存在 AstrBot Plugin Compatibility Layer。

该层继续属于 Stella Core。

Runtime 不应该理解插件逻辑。

结构：

```text
Runtime
   ↓
Stella Core
   ↓
Plugin Compatibility Layer
   ↓
AstrBot Plugins
```

如果插件需要 LLM Tool：

```text
Plugin
 ↓
Stella Tool Interface
 ↓
Comes / LLM Tool Agent
```

仍由 Stella Core 管理。

---

# 44. Memory

Memory System 与 Runtime 解耦。

```text
Runtime
   │
   └── Start Stella
             │
             └── Memory
```

Memory 数据：

```text
data/memory/
```

必须独立于：

```text
runtime/
```

升级 Runtime 不得删除 Memory。

---

# 45. 数据备份

Installer / GUI 应支持：

```text
Backup
Restore
```

至少包括：

```text
config/
data/
plugins/
```

模型可以选择性备份。

推荐：

```text
stella backup
stella restore
```

---

# 46. 安装包策略

推荐安装包分为：

## Bootstrap Installer

体积尽可能小：

```text
Stella Installer
```

只负责：

```text
System Detection
Download
Install
Initialize
```

---

## Runtime Packages

独立下载：

```text
Stella Runtime
llama.cpp
NapCat
Python Runtime
```

---

## Model Packages

独立下载：

```text
Model
Embedding
Optional Models
```

这样可以避免单个安装包达到数 GB～数十 GB。

---

# 47. 为什么不制作“超级单文件 EXE”

不推荐：

```text
Stella.exe
 ├── Python
 ├── llama.cpp
 ├── Model
 ├── NapCat
 └── QQ
```

原因：

1. 更新困难
2. 模型无法独立更新
3. 第三方组件无法独立升级
4. 文件体积巨大
5. 故障定位困难
6. License / redistribution 风险增加
7. GPU Backend 更新困难

推荐：

```text
Stella Installer
       ↓
Stella Runtime
       ↓
Independent Components
```

---

# 48. 推荐最终用户目录

```text
Stella/
│
├── bin/
├── runtime/
├── models/
├── config/
├── plugins/
├── data/
└── logs/
```

其中：

```text
bin/
```

属于 Stella 自己。

```text
runtime/
```

属于第三方运行时。

```text
models/
```

属于模型资源。

```text
data/
```

属于用户数据。

---

# 49. 实施路线

不建议一次性完成所有功能。

采用以下阶段。

---

## Phase 0 — Runtime Contract

首先定义：

```text
Runtime API
Component API
Health State
Process State
Configuration Schema
Manifest
```

**目标：建立架构边界。**

---

## Phase 1 — llama.cpp Runtime

首先集成：

```text
llama-server
```

实现：

```text
Install
Start
Stop
Restart
Health Check
Log
Model Load
```

让 Stella 可以完全脱离 LM Studio 运行。

---

## Phase 2 — LLM Provider

将现有 LLM 调用抽象为：

```text
LLMProvider
```

实现：

```text
LlamaCppProvider
```

确保 Stella Core 不依赖 LM Studio。

---

## Phase 3 — NapCat Runtime

实现：

```text
NapCatManager
```

负责：

```text
Install
Configure
Start
Stop
Restart
Health Check
```

自动生成 OneBot 配置。

---

## Phase 4 — Rust Runtime Manager

将：

```text
Process Manager
Watchdog
Health Check
Logging
```

统一进入 Rust Runtime。

---

## Phase 5 — Tauri GUI Integration

将现有 GUI 接入 Runtime：

```text
Tauri
 ↓
Rust Runtime
 ↓
Stella / llama.cpp / NapCat
```

---

## Phase 6 — Installer

实现：

```text
System Detection
Runtime Installation
Component Installation
Model Installation
First Run
```

---

## Phase 7 — Model Manager

实现：

```text
Model List
Download
Verify
Import
Delete
Switch
Hardware Compatibility
```

---

## Phase 8 — Diagnostics

实现：

```text
stella doctor
```

以及 GUI 中的：

```text
Repair
Diagnostics
Logs
```

---

## Phase 9 — Docker

将 Runtime Contract 映射到：

```text
Docker Compose
```

形成 Server Edition。

---

# 50. MVP

第一版不需要实现所有功能。

MVP 只需要：

```text
┌──────────────────────────────┐
│ Stella Runtime Manager       │
├──────────────────────────────┤
│ ✓ Start Stella               │
│ ✓ Start llama.cpp            │
│ ✓ Start NapCat               │
│ ✓ Health Check               │
│ ✓ Watchdog                   │
│ ✓ Logs                       │
│ ✓ 8192 Context               │
│ ✓ GGUF Model                 │
│ ✓ OneBot V11                 │
└──────────────────────────────┘
```

做到：

```text
双击 Stella
    ↓
Runtime启动
    ↓
llama.cpp启动
    ↓
NapCat启动
    ↓
Stella启动
    ↓
QQ连接
    ↓
开始运行
```

即可视为第一阶段成功。

---

# 51. 非目标

以下内容不属于第一阶段：

```text
自动模型训练
模型微调
在线模型市场
复杂云同步
自动账号管理
多 QQ 集群
分布式推理
```

这些功能应在 Runtime 基础稳定后再考虑。

---

# 52. 最终架构

Stella 最终形成：

```text
                         Stella
                            │
                 ┌──────────┴──────────┐
                 │                     │
             Application             Runtime
                 │                     │
       ┌─────────┼─────────┐     ┌─────┼─────┐
       │         │         │     │     │     │
    Memory    Plugins    Router  LLM  QQ   Model
       │         │         │     │     │     │
       └─────────┴─────────┘     │     │     │
                                 │     │     │
                                 ▼     ▼     ▼
                              llama  NapCat  GGUF
                                 │     │
                                 ▼     ▼
                                GPU    QQ
```

---

# 53. 核心原则总结

整个 Stella Runtime Architecture 遵循以下原则：

### 原则 1：Stella Core 不管理第三方进程

```text
Core ≠ Runtime
```

---

### 原则 2：Runtime 管理生命周期

```text
Install
Start
Stop
Restart
Update
Health
```

---

### 原则 3：LLM 使用标准接口

```text
OpenAI-compatible API
```

---

### 原则 4：llama.cpp 是默认 Runtime，而不是 Core Dependency

```text
Default ≠ Hard Dependency
```

---

### 原则 5：NapCat 通过 OneBot V11 与 Stella 解耦

```text
NapCat → OneBot → Stella
```

---

### 原则 6：模型独立于程序

```text
Application ≠ Model
```

---

### 原则 7：用户数据独立于 Runtime

```text
Runtime Upgrade
        ≠
Data Loss
```

---

### 原则 8：Desktop 与 Server 共用 Core

```text
Same Stella Core
        ↓
Different Runtime Backend
```

---

### 原则 9：AI 是可选组件

```text
Stella can run without LLM
```

---

### 原则 10：一键部署不是“超级 EXE”

真正的一键部署应当是：

```text
Installer
    ↓
Runtime Manager
    ↓
Managed Components
```

而不是把所有第三方软件粗暴塞进一个文件。

---

# 54. 最终产品形态

最终用户看到的 Stella 应当是：

```text
                    ┌─────────────────────┐
                    │       Stella        │
                    │                     │
                    │ QQ       ● Online   │
                    │ AI       ● Ready    │
                    │ Memory   ● Ready    │
                    │ Plugins  ● Ready    │
                    │                     │
                    │ GPU  RTX 5080       │
                    │ LLM  27B            │
                    │                     │
                    │       [运行中]       │
                    └─────────────────────┘
```

而用户实际上运行的是：

```text
Stella
 │
 └── Runtime Manager
      │
      ├── Stella Core
      │
      ├── llama.cpp
      │    └── GGUF
      │
      └── NapCat
           └── QQ
```

复杂性被 Runtime 隐藏起来。

**这才是 Stella 从“一个需要配置的 QQ Bot”向“可以直接安装和使用的本地 AI Companion Platform”转变的关键。**

---

# 55. 下一步实施建议

当前最合理的实施顺序不是立即制作 Installer，而是：

```text
① Runtime Contract
        ↓
② Rust Runtime Manager
        ↓
③ llama.cpp Manager
        ↓
④ LLM Provider
        ↓
⑤ NapCat Manager
        ↓
⑥ Watchdog / Health
        ↓
⑦ Tauri GUI
        ↓
⑧ Model Manager
        ↓
⑨ Installer
        ↓
⑩ Docker Server Edition
```

其中最重要的是：

> **先把 Runtime Manager 做出来。**

Installer、Tauri GUI 和 Docker 都应该成为 Runtime Manager 的不同控制入口，而不是各自重新实现一套启动、停止、配置和监控逻辑。

---

## Appendix A — 推荐模块结构

```text
stella-runtime/
│
├── runtime/
│   ├── process/
│   ├── watchdog/
│   ├── health/
│   ├── logging/
│   └── config/
│
├── llm/
│   ├── manager/
│   ├── provider/
│   └── model/
│
├── napcat/
│   ├── manager/
│   └── onebot/
│
├── hardware/
│
├── installer/
│
├── updater/
│
├── diagnostics/
│
└── ipc/
```

---

## Appendix B — 组件依赖关系

```text
Tauri
  │
  ▼
Runtime Manager
  │
  ├──────────────┐
  ▼              ▼
Stella Core     External Runtime
  │              │
  │        ┌─────┴─────┐
  │        ▼           ▼
  │     llama.cpp    NapCat
  │        │           │
  │        ▼           ▼
  │       GGUF        QQ
  │
  ├── Memory
  ├── Router
  ├── Plugins
  └── OneBot Adapter
```

---

## Appendix C — 一键部署的最终定义

Stella 的“一键安装”不应定义为：

> **“用户只点击一次安装程序。”**

而应该定义为：

> **“用户无需理解或手动配置 Stella 的内部运行时，即可从空白系统环境获得一个可运行、可诊断、可更新、可恢复的 Stella 实例。”**

这也是 Stella Runtime Architecture 的最终目标。