# 6.1.0 当前架构增补

中文 | [English](overview.en.md) · [文档总览](../README.md)

## 6.1.0 当前架构增补

- **可信接入与会话身份**：`core/conversation.py` 的 `ConversationRef` 统一 QQ 群、QQ 私聊与 WebChat；`memory/conversation_registry.py` 分配存储键。运行 owner、取消、trace、消息去重和 Cometa 回投都依赖规范会话身份。
- **个人记忆**：`memory/ownership.py` 定义 SPACE/PERSON 与 audience；私聊事实默认 PRIVATE_ONLY。`memory/personal_sharing.py` 按本人、来源消息和具体事实授权，使用副本台账与缓存版本支持撤回。写入和分享出厂默认关闭。
- **对话归属**：消息包络保留作者、收件人、回复/引用关系、带符号平台 ID 与逻辑轮次。`memory/conversation_projection.py` 同时服务短尾巴与压缩，`memory/conversation_identity.py` 存会话内的来源绑定声明；`core/dialogue_attribution.py` 处理结构化回复计划与证据检查。
- **长任务**：`cometa/` 持久化受理、租约、worker、workspace、产物与通知；`capability/delegation.py` 在工具层之外委派。Codex 认证由每后端托管 home 现读，WebUI 提供商页可配置。
- **流程观测**：`core/observability/` 记录 root/span/transition、输入输出、生命周期与损失账本；`webui/routers/flow.py` 和 Dashboard FlowPage 提供查询、SSE、拓扑与历史回放。拓扑来自源码 manifest，记录事件与设计可达路径分别呈现。

当前分支记忆 schema 为 **19**，Python/Rust backend API 为 **3**；v15-v18 引入会话与个人归属，v19 扩展来源审核与派生关系。合同来源见 [源码合同](../development/contracts.md)；这是分支源码事实，不代表已发布资产或真实验收。知识库、调度、Cometa 和观测库各自版本化。真实 QQ 灰度与 Rust 排序差异见 [文档索引](../README.md)。
## 分层概览

```
QQ 群消息 / QQ 私聊 / WebChat
    ↓  OneBot V11 / NapCat
stella_project/plugins/bot_main/ai_gateway.py     ← 事件接入层
    ↓
core/runtime/facade.py                           ← 入口所有权与轮次执行
    ↓
core/runtime/turn_service.py                     ← prepare → generate → finalize
core/pipeline.py                                 ← Hook 注册与兼容门面
    ↓
capability/*                                      ← 能力层（Router 判定 / Comes 执行工具）
memory/*                                          ← 记忆层（写入 / 晋升 / 检索 / 压缩）
    ↓
SQLite（STELLA_HOME/memory/agent_memory.db）
```

五层各自独立：接入层只做协议适配与调度，编排层不含业务逻辑，能力层不感知人格与记忆内容，记忆层不感知 QQ，存储层由 `memory/schema.py` 统一管理迁移。

能力层与记忆层是**并列**的两条分支，都由编排层的同一个前置钩子激活，彼此之间只通过 `ChatContext` 通信、不互相调用。

`astrbot_compat/*` 是横在旁边的第六块：它把 AstrBot 插件生态接进来，既供能力层执行工具（Comes → `llm_tools`），也自己走一条独立的分发通路（`plugin_handler`）响应插件指令。它**不参与**记忆与人格，见下文[兼容层](integrations.md#astrbot-插件兼容层)。

> 会话、用户与空间身份分别管理。群会话的 `group_id` 保持真实群号；私聊的旧表物理键是注册表分配的负数，WebChat 保留 `-1`，不得按整数正负推导会话类型。记忆另受 owner/subject/audience 约束。

主动插话还有一条位于记忆层旁的 **Participation Decision Layer**：它从近期群聊提取信号，
对话题机会、相关性与打扰风险做本地评分，输出 `IGNORE` / `OBSERVE` / `CANDIDATE` /
`ALLOW_LLM` 决策，再决定是否把证据交给生成器。
它不替代 `proactive_gate.py` 的硬闸门，也不调用 LLM；外置权重在 `config/participation/`，
决策日志同时写入运行期日志与 v13 的 `participation_log` 表。

称呼偏好是记忆层旁的另一个小分支：`memory/addressing.py` 存用户明确设置的称呼偏好
（v14 的 `user_address_preferences` 表，与 `user_profiles.nickname` 和普通记忆分开），
`memory/addressing_intent.py` 负责从自然语言里识别「叫我 X」这类意图——规则做廉价预筛、
embedding 判语义，只返回结构化请求，不把模型输出当可执行命令。
