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

---

## 6. 真机验证补记（2026-10-03 晚，NapCat + 双号实测）

环境：NapCat 桌面版（bot=self 1694717255，反向 WS）、Strata 本地推理、
小号 3089665724 全程配合；运行库为真实生产库。

### 6.1 通过项

| 清单项 | 实测证据 |
|---|---|
| A 自动化回归 | `3335 passed / 17 skipped`、cargo 16、ruff 绿、manifest 门禁绿 |
| 真实迁移 | 21:53 启动自动完成 v14→v15（pre-v15 备份 + stella_memory_backup 双备份生成）；956+1203+2 行回填 SPACE、0 NULL owner、0 PERSON 行 |
| B1 副本重放 | v14 备份副本重放成功、幂等重跑 0 变更（校验器如实上报**存量** FTS 漂移 12 行，v14 备份中即存在，非 v15 引入） |
| B2 回填 CLI（真数据副本） | 真实 PREFERENCE 记忆+真实 AT_MENTION 来源行：COPY 命中；坏行 SKIP 原因准确；apply 幂等（already_backfilled）；revoke 后副本消失原行保留 |
| B4 后端合同 | 旧 native（API1）下 auto 记录原因回退 Python、strict 明确抛错；**新 native 已用 maturin 构建并装入**（API2/schema15），重启后 auto/rust 正确选中 |
| B5 缺省 | PRIVATE_CHAT_ENABLED=true、ALLOWLIST 空、PERSONAL_MEMORY_WRITE_ENABLED=false（验证期已显式开） |
| C1 私聊首条 | 无 @ 私聊触发；注册表分配 storage=-2（-1 WebChat 保留）；「你好」以 PRIVATE_DIRECT 落库恰好一次；3 段回复 BOT_SELF；trace 会话身份完整且 group_id 留空 |
| C2 历史引用 | 「我刚刚说了什么呀？」→「你刚说了你好呀」 |
| C4 私聊称呼 | 称呼写入私聊空间（user_address_preferences），后续回复直接使用该称呼；群空间不受影响 |
| C5 PERSON 全链 | 整合提取 2 条偏好（含真实 source_message_ids）→ PERSON+PRIVATE_ONLY 候选 → 高置信晋升为 PERSON 记忆（归属保持）→ 证据逐行落 memory_evidence → **真库 scope 检索隔离**：私聊 scope 命中 2/2，群 scope 与无 scope 均为空集 |
| C6 Cometa 私聊委派 | Origin v2 私聊任务：ack **sent** + final **sent**（均真实平台回执），worker 执行成功，结果回原私聊 |
| B3 WebUI | /api/v1/personal-memory 三端点已挂载（401 鉴权拦截与既有路由一致）；页面登录点击验证留待用户 |

### 6.2 过程中发现并修复

- **cometa ack target 未跟随 v2 origin**（9dccae1）：submit_task 自建的 ack
  target 还是旧格式，私聊任务 ack 全部 delivery_unknown（final 正常）。
  提取 `_target_from_origin` 共享构造器后真机复验 ack sent。这正是计划
  §9.1「submit_task 自建 ack target 须源读同步」预告的漏网之鱼。
- **孤儿 worker**：换进程重启 bot 时旧 worker 子进程存活占租约，新 worker
  注册被拒（StoreBusyError）退出。处置：杀孤儿进程 + 重启 bot。**运维注意：
  重启 bot 前先确认 cometa worker 子进程已随主进程退出。**

### 6.3 遗留与建议

1. **存量 FTS 漂移**（fts 957 vs active 945）：归档/压缩路径未同步删 FTS 行，
   建议单列修复任务（与本分支无关）。
2. **证据归因偏松**（v1.1 改进项）：个人事实的证据绑定了说话人本批全部
   直接消息行，而非模型引用的 source_message_ids 交集——合规（同会话同说话人）
   但过宽，建议收窄。
3. **委派命令语法**：显式委派要求「委派␣目标」（委派后必须有空格），用户
   直觉常连写。属既有行为（群聊一致），建议后续加连写容错。
4. `PERSONAL_MEMORY_WRITE_ENABLED=true` 已写入 StellaData/.env（D2 观察期）；
   观察结束后如需回退改回 false 即可（已写入的 PERSON 行按受众继续受控）。
5. 当前 bot 由验证会话的后台进程托管（pid 见 /stella/status）；回交用户时
   直接在其终端按原方式重启 `.\bot.py` 即可（新 native pyd 已就位）。

### 6.4 补充修复（2026-10-03 深夜，用户真机反馈）

- **私聊短结果只发摘要 + 指针**（2b7d7dc）：私聊投递把「payload 带
  full_text_ref」一律当超长处理，54 字结果也被藏进 WebUI 指针。修正为
  与群 `file_above_chars`（默认 500）同阈值：阈值内读 artifact 全文，
  以「任务头 + 完整结果」直发；真超长才摘要+指针。真机复验：短任务
  final 直发全文（无误导性「过长」提示）。
- **任务跑在 FakeBackend 是部署配置**：cometa.toml `default_profile="complete"`
  指向 demo fake 后端。真实任务需 `default_profile="coding"`（codex_local）
  或显式「委派 codex_local <目标>」。属部署选择，非代码缺陷。
- **worker 孤儿坑再次确认**：多次重启后清理了 2 个累积的孤儿 worker；
  监管器不会自动重拉（需重启 bot），运维注意点已记入项目记忆。
