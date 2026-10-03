# 验证清单：QQ 私聊与跨会话个人记忆

> 对应分支 `feat/qq-private-personal-memory`（M0–M4 已实施）。
> 用法：按 A → B → C → D 顺序执行；E 是回滚预案演练（建议上线前做一次）。
> 每项给出操作与**期望结果**；勾选前先确认期望成立。
> 本机自动化部分（A）已全绿，重跑即可；C/D 需要你的 NapCat 与测试 QQ 号。
>
> **执行记录（2026-10-03 真机验证）**：A/B 全部通过；C1–C6 已真机验证通过
> （详见实施报告补记）；D2 已开启（PERSONAL_MEMORY_WRITE_ENABLED=true 写入
> StellaData/.env，进入观察期）；E 未演练。
> 过程中发现并修复：cometa ack target 未跟随 v2 origin（9dccae1）；
> 存量 FTS 漂移 12 行（与本次迁移无关，建议单列修复）。

---

## A. 本机自动化回归（合并前重跑，约 6 分钟）

- [ ] A1 全量 Python 测试：
  ```powershell
  python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/goldens
  ```
  期望：`3335 passed, 17 skipped`，0 failed。
- [ ] A2 Rust native 测试：
  ```powershell
  cargo test --manifest-path memory_rust/native/Cargo.toml
  ```
  期望：16 passed（含 v2 scope 谓词矩阵、schema15 握手）。
- [ ] A3 Lint 与漂移门禁：
  ```powershell
  python -m ruff check .
  python -m pytest tests/observability/test_message_flow_contract.py -q -p no:cacheprovider
  ```
  期望：全部通过。
- [ ] A4 关键新套件点验（可单独重跑）：
  `tests/test_conversation_identity.py`、`tests/test_conversation_registry.py`、
  `tests/test_private_chat_ingress.py`、`tests/test_personal_memory_scope.py`、
  `tests/test_personal_memory_concurrency.py`、`tests/test_personal_memory_backfill.py`、
  `tests/test_webui_personal_memory.py`、`tests/test_migrations.py`。

## B. 本机可验证（不需要 QQ 消息）

### B1 生产库迁移演练（先在**副本**上做）

- [ ] 复制真实库 → 对副本执行
  ```powershell
  python -c "from memory.schema import migrate_to_latest; r = migrate_to_latest(r'<副本路径>'); print(r.to_markdown())"
  ```
  期望：报告 ok、版本 v14→v15、`memories/memory_candidates/atomic_facts` 存量行
  回填 `owner_type='SPACE'`、四张新表就绪、生成 `*.pre-v15-*.bak` 备份。
- [ ] 对同一副本重跑一次：期望 `changed_rows == 0`（幂等）。
- [ ] `owner_key` 抽查：任取一行，应为 `'space:' || group_shared_space`。

### B2 回填 CLI 预演（对 B1 的副本）

- [ ] 手工构造小 manifest（bot_id + 1~2 条确定可共享的 PREFERENCE，
  含 memory_id / user_id / source_conversation_key / source_row_id）→
  ```powershell
  python -m tools.backfill_personal_memory preview --manifest m.json --db <副本路径>
  ```
  期望：输出逐条 COPY/SKIP 及原因；原库零写入（无 PERSON 行、无审计表）。
- [ ] 故意放一条错误项（source_row_id 不存在 / user_id 与消息 sender 不符 /
  类型不在白名单）：期望对应 SKIP 且原因准确。
- [ ] `apply --batch-id b1` → 期望：PERSON+USER_SHARED 副本生成、原 SPACE 行仍在、
  重跑 apply 报 `already_backfilled`；`revoke --batch-id b1` → 副本消失、原行仍在。

### B3 WebUI 管理页

- [ ] 启动面板 → 数据页 → 「个人记忆」页签：期望空列表（PERSON 行为 0 时）
  或仅显示 PERSON 行（**不含**群空间记忆）。
- [ ] B2 apply 后刷新：期望能看到副本行，筛选（主体/受众）生效、默认不含正文。
- [ ] 删除一条 → 行消失；导出 JSON → 内容完整。

### B4 后端选择合同

- [ ] `MEMORY_BACKEND=auto`（本机装旧版 native 时）：期望日志出现
  `Rust memory API mismatch` 类回退原因并落到 Python 后端（功能不中断）。
- [ ] `MEMORY_BACKEND=strict` + 旧 native：期望**明确报错**（不悄悄换后端）。
- [ ] （可选）`MEMORY_BACKEND=shadow` + 正确 ABI：parity 不匹配时告警日志可查。

### B5 私聊功能开关缺省

- [ ] `.env` 不写新键启动：期望 `PRIVATE_CHAT_ENABLED=true`（私聊可用）、
  `PERSONAL_MEMORY_WRITE_ENABLED=false`（不产生任何 PERSON 行）。
- [ ] `PRIVATE_CHAT_ENABLED=false` 启动 → 私聊发消息：期望无任何回复（群不受影响）。

## C. 真机私聊闭环验收（M5，需 NapCat + 两个测试 QQ 号）

> 建议用 dev bot（8080）＋ PRIVATE_CHAT_ALLOWLIST 先限定测试号。

### C1 接收与回复

- [ ] 测试号私聊发「你好」（**不带任何 @**）：期望本体直接回复。
- [ ] 再发「我刚才说了什么？」：期望能引用上一句（短期历史闭环）。
- [ ] 连发两条消息：期望逐条串行处理，不串上下文、不双写历史
  （`group_messages` 中该会话行数与发送条数一致）。
- [ ] 查 trace（WebUI 追踪页或 `memory_traces` 表）：期望
  `conversation_kind='private'`、`group_id` 为空、`storage_session_id` 为负整数。
- [ ] 纯图片私聊（识图开启时）：期望按 `[图片]` 占位进对话；识图关闭时按 A5 语义不触发。

### C2 群聊与 WebChat 回归（私聊上线不破坏既有）

- [ ] 群 @ → 回复照旧；被动消息照常入库（source_kind=PASSIVE）。
- [ ] 主动发言/参与评分照常（私聊消息不进入群参与统计）。
- [ ] WebChat 发消息：照常回复；注册表出现 `webchat` 行（storage -1）。
- [ ] 插件接管：私聊发插件命令 → 插件回复一次，本体不再生成（无重复回复）。

### C3 会话隔离矩阵

- [ ] 第二个测试号私聊同一 Bot：期望独立会话、独立存储 ID（注册表两行、
  storage_id 递减），A 说的内容 B 不可见。
- [ ] 同测试号在两个群分别 @ 说不同偏好：期望两群记忆互不串（既有 SPACE 语义）。
- [ ] 重启 bot → 测试号再私聊：期望存储 ID 不变（注册表持久）、历史仍可引用。

### C4 私聊整合与称呼

- [ ] 私聊积累若干条消息 → 触发总结（私聊发新消息或等 drain）：
  期望 `consolidation_state` 中该负存储 ID 的 checkpoint 推进、
  short_term_context 生成。
- [ ] 私聊说「称呼我为队长」→ 期望确认；再问「你怎么称呼我」→ 命中。
- [ ] 切到群 A @ 问「你怎么称呼我」：期望**不**用私聊里的称呼（空间隔离）。

### C5 个人事实写入与检索（先开 PERSON flag）

- [ ] `.env` 设 `PERSONAL_MEMORY_WRITE_ENABLED=true` 重启。
- [ ] 私聊说稳定偏好（如「我喜欢用 Python 写后端」）→ 等整合：
  期望 `memory_candidates` 出现 `owner_type='PERSON'`、`audience='PRIVATE_ONLY'`、
  `source_conversation_key='qq:<bot>:private:<uid>'` 行；
  `memory_evidence` 恰好一条（重复发同一句不再翻倍）。
- [ ] 私聊再聊相关话题：期望回复能引用该偏好（PERSON 行被检索）。
- [ ] 换第二个测试号私聊聊同一话题：期望**不**命中（PRIVATE_ONLY 隔离）。
- [ ] 群里聊同一话题：期望不命中（PRIVATE_ONLY 对群不可见）。
- [ ] WebUI「个人记忆」页：能看到这条 PERSON 行，删除后私聊再问 → 不再命中。

### C6 Cometa 私聊任务

- [ ] 私聊发委派指令（授权用户）：期望 ack 在**私聊**收到（仅一条）。
- [ ] 任务完成：期望结果回**原私聊**；长结果（>500 字）→ 私聊收文本摘要 +
  「可在 WebUI 任务页查看全文」指针，**无任何群 API 调用**（看 NapCat 日志）。
- [ ] 任务进行中重启 bot：期望完成后结果仍回原私聊（持久 target）。
- [ ] 群里同时有任务：互不干扰；取消/追问只能由原会话发起。

### C7 异常与恢复

- [ ] 私聊回复发送中途断网（拔线重连）：期望只有确认送达片段进 BOT_SELF，
  不重复发送（delivery_unknown 不自动重试）。
- [ ] bot 重启后旧私聊再发消息：无幽灵回复、无重复落库。

## D. 灰度放量序列（生产执行顺序）

- [ ] D1 `PRIVATE_CHAT_ALLOWLIST=<测试号>` 上线 → C 组全过。
- [ ] D2 `PERSONAL_MEMORY_WRITE_ENABLED=true` → 观察 1–2 天：
  `memory_candidates`/`memory_evidence` PERSON 行增长正常、无异常归属。
- [ ] D3 放开 ALLOWLIST（空 = 全部好友）→ 观察。
- [ ] D4 历史回填：**先 preview 全量导出审查**（不明主体全部应 SKIP）→
  分批 apply（小 batch_id）→ 找测试号验证「在另一群已认识我」
  （群 B 提及群 A 学过的共享偏好应命中）→ 保留每批审计。
- [ ] D5 撤回演练：`revoke --batch-id <某批>` → 确认群 B 立即不再命中
  （持久缓存版本生效）。
- [ ] D6 发布说明：区分「已实现 / 真机已验收 / adapter 能力限制」
  （模板见实施报告 §4）。

## E. 回滚预案（上线前演练一次）

- [ ] E1 功能降级：关 `PRIVATE_CHAT_ENABLED` → 私聊静默，群/WebChat 不受影响；
  关 `PERSONAL_MEMORY_WRITE_ENABLED` → 不再新增 PERSON 行（已写入行仍按受众可见）。
- [ ] E2 数据回滚：停 bot → 用迁移前 `.pre-v15-*.bak` 覆盖库 → 重启。
  已知代价：恢复点之后的消息/记忆丢失；旧 schema14 程序可读该备份。
- [ ] E3 副本清理：如需抹掉全部回填 PERSON 行，按审计表
  `personal_memory_backfill_audit` 逐批 revoke（勿手工 DELETE，保留审计）。

---

## 常见陷阱速查（实施期实测）

| 症状 | 原因/处置 |
|---|---|
| monkeypatch 了 `config.settings.X` 但行为没变 | config 星号导出：`from config import X` 读包级副本，两处都要 patch |
| 检索测试里 PERSON 行查不到 | `owner_scope_sql` 是**位置参数**；alias 传 `"m"` 不是 `"m."`（函数内补点） |
| flow manifest 门禁挂 | 改了被插桩源码后跑 `python scripts/generate_message_flow.py`；**只提交当前 hash 那一个文件**（生成器不清旧文件） |
| `from config import PERSONAL_MEMORY_WRITE_ENABLED` 恒为 False | 该值在 import 期固化；运行期判断请走 `config.settings` 或包属性 |
| 私聊消息表里 group_id 是负数 | 这是注册表分配的存储会话 ID（设计如此）；种类判断永远看 `conversation_kind`，不看符号 |
