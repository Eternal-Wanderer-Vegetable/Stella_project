# Stella v6.1.0

6.1.0 增加 QQ 私聊、外部 Agent 长任务、消息流程观测与个人记忆归属合同，并同步中英文使用文档。相对版本：[v6.0.1](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases/tag/v6.0.1)。

## 主要变化

- **QQ 私聊与会话身份**：可信入口统一使用 ConversationRef；群、私聊和 WebChat 分别保有会话状态，Cometa 受理提示与结果回投原会话。私聊默认启用，`PRIVATE_CHAT_ALLOWLIST` 可限制好友；`ALLOWED_GROUPS` 仍只控制群。
- **个人记忆与对话归属**：记忆 schema 从 14 升至 18，backend API 升至 2。新增 owner/subject/audience、来源证据、消息包络、逻辑轮次和会话内身份声明；短尾巴与压缩共用作者/收件人/回复关系投影。个人事实分享按本人和具体来源事实授权，并支持副本台账撤回。
- **可选归属保护**：结构化 reply_plan 与服务器证据校验、主动核验对象合同、来源驱动的数据修复 preview/apply/revoke。`PERSONAL_MEMORY_WRITE_ENABLED`、`PERSONAL_MEMORY_SHARE_ENABLED` 默认 false；`REPLY_ATTRIBUTION_GUARD_MODE`、`PROACTIVE_VERIFICATION_CONTRACT_MODE` 默认 off。
- **Cometa 外部 Agent**：持久化任务、受理策略、worker 租约、取消、产物与通知。Codex SDK 为可选依赖，冻结于 `openai-codex==0.159.2`；WebUI「提供商 → 外部 Agent」支持设备码、API key、自定义 Responses 端点和旧认证迁移，每后端独立托管认证。短结果完整回投，长结果优先 Markdown 文件。默认 `COMETA_ENABLED=false`、显式委派。
- **消息流程与管理面板**：真实 root/span/transition、消息输入输出、损失账本、源码闭包 manifest 与历史拓扑归档。WebUI 消息流程页支持分页、完整性诊断、SSE、历史回放与隔离评估；个人记忆页提供 owner/audience 审计、导出与删除。
- **可靠性修复**：并发 SQLite 迁移串行化，Python/Rust 个人归属合同同步，Bot 作者/收件人和带符号平台消息 ID 保留，数据修复撤回逐列恢复，跨 Bot/跨会话诊断与分页补拉强化。
- **文档**：补齐知识库、定时任务、Skills、WebUI、Rust 记忆后端及模板插件英文说明；增加双语索引，补齐配置参考的 62 个环境变量，修正知识库 WebUI 与 Codex 认证入口等过期说明。

## 升级与兼容

1. 停止旧 Stella，备份完整 `STELLA_HOME`。活 SQLite 库使用 backup API，或停机后复制，不能只复制 WAL 数据库的主 `.db`。
2. OneClick 运行新安装程序；Standalone 解压到新目录并运行 `Stella.exe` 或 `start.bat`。原数据根继续保留。
3. 按配置导入流程迁移；数据库自动升到 schema 18，失败保留迁移前快照。建议先对副本演练。
4. Rust 产品使用本 Release 随包的原生 wheel，核对 **API 2 / schema 18**。wheel 仍标记 `0.1.0`，旧同名 wheel 不代表兼容；不兼容时 rust/strict 会拒绝，auto 可回退 Python。
5. 检查私聊允许范围及可选开关；不要把开启开关当成已完成真实 QQ 灰度，也不要自动共享旧库事实。

```bash
python -m deploy paths
python -m deploy migrate --dry-run
python -m deploy migrate
```

应用版本为 6.1.0；launcher、runtime-manager、原生 wheel 与私有 Dashboard 的组件包版本独立。冻结的 v1 GUI 不参与发布。

## 下载与数据

| 产品 | 资产 |
| --- | --- |
| 在线安装 / Python | `Stella-OneClick-Python-v6.1.0-windows-amd64.exe` |
| 在线安装 / Rust | `Stella-OneClick-Rust-v6.1.0-windows-amd64.exe` |
| 离线安装 / Python | `Stella-OneClick-Python-Offline-v6.1.0-windows-amd64.exe` |
| 离线安装 / Rust | `Stella-OneClick-Rust-Offline-v6.1.0-windows-amd64.exe` |
| 解压包 / Python | `Stella-Standalone-Python-v6.1.0-windows-amd64.zip` |
| 解压包 / Rust | `Stella-Standalone-Rust-v6.1.0-windows-amd64.zip` |

另有 Windows/Linux CLI、CPU backend、原生 wheel、catalog、发布清单与 `SHA256SUMS.txt`。OneClick 包含 WebView2 离线运行时；Offline 额外携带 Python、依赖、组件、embedding 模型和渲染内核。聊天模型仍需自行配置，QQ 仍需扫码登录。

全新 OneClick 数据根默认 `%LOCALAPPDATA%\Stella\Data`，已有指针/便携布局沿用原规则；Standalone 默认同级 `StellaData/`。`python -m deploy paths` 显示实际位置。备份还应包含 WebUI 管理员状态、知识库、调度、Cometa 任务与每后端认证目录。

## 已知边界

- 对话归属的 P8 离线模型重放及修复 round-trip 已有日期报告；**真实 QQ 灰度尚未完成**。保留默认关闭的写入/分享/guard/主动合同，按 [灰度清单](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/blob/v6.1.0/docs/reports/2026-10-05-qq-gray-rollout-checklist.md)逐步验证。
- Rust 检索 benchmark 的 3 个 conversation 排序差异仍未闭环（21/24 硬匹配）。需要排序一致时使用 Python；详见 [P8 报告](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/blob/v6.1.0/docs/reports/2026-10-05-dialogue-attribution-p8-acceptance.md)。
- `delivery_unknown` 表示投递可能已经发生，不能盲目重发。观测缺口与未知状态不能推导为业务成功。
- 发布工作流默认 `VERSIONED_LAYOUT=0`，launcher 搬移布局未默认开启。四个 EXE 的 hosted Windows 安装检查与发布后哈希回读由流水线把关；干净 VM 完整矩阵与 GUI 首启另按 runbook 验收。

中文文档：[索引](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/blob/v6.1.0/docs/README.md)。English documentation: [index](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/blob/v6.1.0/docs/README.en.md).

## English release summary

Stella 6.1.0 adds QQ private conversations, canonical conversation identity, Cometa persistent external-agent tasks, live Codex authentication on WebUI Providers, source-versioned message-flow observation, and personal-memory ownership/evidence contracts. The memory contract is now **schema 18 / backend API 2**. Bilingual documentation includes five new English guides, the plugin example, and 62 previously omitted configuration keys.

Private chat defaults to enabled, independently of allowed groups; an empty private allowlist permits all friends. Cometa defaults to disabled/explicit delegation. Personal writing/sharing, reply attribution guards, and proactive verification contracts remain disabled. Back up the entire data root before upgrading; migration does not automatically share old facts. Rust users must install the wheel from this release and validate API/schema exports, even though its package version remains `0.1.0`.

Real QQ attribution rollout is still incomplete. Three Rust conversation-ranking benchmark differences remain open. Delivery uncertainty is never proof of success or a reason for blind resend. Hosted Windows installation checks and published-byte verification are distinct from full clean-VM and GUI-first-launch acceptance; the installer relocation flag remains `VERSIONED_LAYOUT=0`.
