# 实施报告：QQ 私聊与跨会话个人记忆（feat/qq-private-personal-memory）

> 计划：`docs/plans/2026-10-03-gitnexus-plan-qq-private-personal-memory.md`
> 分支：`feat/qq-private-personal-memory`（自 `feat/cometa-agent-task-layer` @ 0600226 切出）
> 状态：M0–M4 代码面全部落地并分阶段提交；M5（真实适配器验收）需要测试账号，
> 见 §4 待办。

## 1. 提交清单

| 提交 | 里程碑 | 内容 |
|---|---|---|
| ac9c690 | — | 计划与证据报告文档 |
| e6839b3 | M0 | ConversationRef / MemoryOwner / MemoryAccessScope / Origin v2 合同 + 30 例测试 |
| 28cda79 | M1 | schema15（registry/evidence/personal_facts/scope_versions 四新表 + 三表 owner 七列）、migrate_v15（存量回填 SPACE）、memory/conversation_registry（负整数分配）、Rust BACKEND_API_VERSION 2 / schema 15（scope 谓词 + 晋升 owner 收口）、灰度 flags |
| 1215b9a | M2 | 私聊端到端闭环：matcher（无须 @）、会话锁/注册/落库/预算/取消/分条发送/BOT_SELF/压缩、整合按注册会话、trace v15 会话列、cometa build_origin v2 + 私聊 sender + policy 用户级授权、技能 sandbox 会话隔离、drain 覆盖私聊 |
| 2de2d62 | M3 | 检索 scope 全链路（SQL/FTS/Planner/embedding/rust 同授权谓词）、PERSON 写入路由（证据验证 + audience 路由）、证据去重表、晋升/压缩保持归属、持久缓存版本 |
| 9bc2f5f | M4 | 回填 CLI（preview/apply/revoke，复制语义 + 幂等 + 审计）、WebUI 个人记忆管理（服务端 PERSON-only 过滤/删除/导出）+ 页面 |

## 2. 已验收（本机自动化证据）

- 全仓 pytest：见最新 CI/本地全量（3300+ 用例，收尾轮全绿）；
- `cargo test --manifest-path memory_rust/native/Cargo.toml`：16 passed（含 v2
  scope 谓词矩阵、schema15 握手）；
- `ruff check .` 全绿；GitNexus detect-changes 最终零变化；
- 关键矩阵（计划 §8.1 抽取，全部有自动化用例）：
  - 同 QQ peer=同整数时 group/private 全维度隔离
    （tests/test_conversation_identity.py）；
  - 私聊无须 @ 触发、插件接管短路、消息只落一次、storage 隔离
    （tests/test_private_chat_ingress.py）；
  - USER_SHARED 跨空间命中 / PRIVATE_ONLY 对群不可见 / 无 scope SPACE-only /
    INTERNAL 不进 prompt / FTS 同授权（tests/test_personal_memory_scope.py）；
  - 伪造归属被白名单+证据验证拒绝、证据重放不翻倍、并发唯一约束兜底、
    晋升同 owner 收敛（tests/test_personal_memory_concurrency.py）；
  - 回填 preview 零写入/不明来源 skip/幂等/撤回（tests/test_personal_memory_backfill.py）；
  - v14→v15 迁移回归（tests/test_migrations.py）。

## 3. 关键设计决定（实施中的取舍）

1. **Origin conversation_key 推导**：v2 缺 conversation_key 时由
   platform/bot/kind/peer 规范推导而非拒绝（roundtrip 闭环）；kind/peer 缺失
   仍严格拒绝（计划 §6.8 的「不猜默认群」语义保持）。
2. **USER_SHARED 第一版不自动写**：群内「用户明确分享意图」需要提取提示词
   支持，本版不新增 LLM 分类调用（计划 §6.5 确定性原则），仅实现私聊
   PRIVATE_ONLY 写入路径；共享写入的落点（副本/受众/版本）已就绪，欠共享
   优于越权共享。
3. **私聊长结果**：不做 upload_private_file / 私聊转发尝试（真实 NapCat 能力
   未验证，计划 §12 假设 4），文本摘要 + WebUI 任务页指针；绝不调用群投递 API。
4. **私聊称呼**：第一版按私聊空间隔离生效（不调用群管理员检查、不可改他人）；
   跨空间个人称呼属 M3 个人事实层，待 USER_SHARED 路径启用后接入。
5. **回填语义 = 复制**：原 SPACE 行永不修改；撤回只删审计登记的副本行。

## 4. 待办（M5：真实适配器验收，需测试账号）

- 真实 QQ 私聊收发（好友私聊/临时会话）、reply 引用在私聊的兼容性、
  upload_private_file / 私聊合并转发能力探测（决定是否升级长结果私聊投递）；
- 插件（AstrBot 兼容层）私聊接管与本体优先权的真机回归；
- Cometa 私聊任务全生命周期真机验收（ack/结果/取消/重启后投递）；
- 灰度放量：`PERSONAL_MEMORY_WRITE_ENABLED` 打开 → shadow 观察 → 白名单
  canary → manifest 审查 → 跑 `python -m tools.backfill_personal_memory`。
- Windows native wheel 发布物随 v下一版本走既有 release 流程（maturin 构建）。

## 5. 风险记录

- GitNexus detect_changes 曾在 M2 报 CRITICAL（Origin/ChatContext 横切，
  73 processes）——属计划 §9.1 预告的影响面，以 v1 兼容层 + 矩阵测试缓解，
  最终工作树零漂移。
- 多 Bot 群历史绑定：单 Bot 部署（当前实态）下首个注册者获得 legacy 绑定；
  多 Bot 环境第二个 Bot 拿独立负存储 ID，不盲绑历史（有测试锁定）。
