# QQ 灰度执行清单 —— 对话归属复发修复（P8 出口 → 生产）

日期：2026-10-05。计划：[2026-10-05-gitnexus-plan-dialogue-attribution-recurrence-repair.md](../plans/2026-10-05-gitnexus-plan-dialogue-attribution-recurrence-repair.md)（§7 发布与回滚顺序、§8.3 灰度判据）。
执行人：用户（操作者）。本清单只列**生产机上要做的动作**；开发侧已完成项见文末「P8 离线验收状态」。

## 0. 前置门（全部满足才进灰度）

| # | 门 | 状态 |
| --- | --- | --- |
| G1 | 260 样本生产条件模型重放达标：0 关键错归 / 0 越权共享 / 0 不相关候选记账（最终发送口径，guard 兜底后）；原始错误率/阻断率/漏过率/兜底率同时报告 | ⏳ 重放进行中，结果见 `docs/reports/evidence/dialogue-attribution-20261005/p8/` |
| G2 | 模型自由文本不遵守 `<reply_plan>` 协议时的兜底率可接受（全 fallback = 模型原话全被替换为受限兜底，属可运行但体验降级；若 enforce 下 fallback 率影响可用性，先 shadow 观察） | ⏳ 与 G1 同批判定 |
| G3 | native parity：cargo test 16/16 ✅；wheel 已构建安装（api 2 / schema 18）✅；benchmark 硬匹配 21/24（rank 系 3 例 conversation_order 硬不一致，**未闭环**——灰度不依赖 benchmark 排序差异，但须在报告里如实记录） | ⚠️ 部分达标 |
| G4 | 生产副本 round-trip：13 条 duplicate apply→revoke 逐列还原（含 updated_at），与生产库整行零差异 ✅ | ✅ PASS |
| G5 | 生产库 schema 16 → 18 迁移在**副本**上先演练（migrate + FTS + 行数守恒），成功后才动生产 | ⬜ 用户执行 |
| G6 | 消息流 manifest 无漂移（`python scripts/generate_message_flow.py --check`） | ✅ 通过（新 manifest 0cbb0ab4f203） |

## 1. 发布顺序（生产机，逐条打勾）

1. **快照**：用 SQLite backup API 生成一致快照（不要裸拷 .db，防 WAL 漏页）：
   `python -c "import sqlite3; s=sqlite3.connect('StellaData/memory/agent_memory.db'); d=sqlite3.connect('<备份路径>.db'); s.backup(d)"`
   记录 schema 版本、应用 commit、native api/schema 版本。
2. **部署代码**：合并本分支；重启 bot（新进程清空易失 compact 状态）。三个开关出厂默认全关（guard=off / 主动合同=off / share=false），部署本身不改变行为。
3. **副本迁移演练（G5）**：在备份副本上跑 `migrate_to_latest` → 校验 schema_meta=18、行数守恒、FTS 可查询；再对生产库执行迁移。
4. **数据修复（只做审查过的）**：
   - preview 已冻结在 `docs/reports/evidence/dialogue-attribution-20261005/p8/repair-preview-*.json`：**duplicates 13 / orphans 1851 / identity_rechecks 16 / unknowns 2 / private_owner_repairs 0**。
   - 第一批：13 条 `duplicate_deprecate`（清单已审查，apply 后抽查保留行内容）。
   - **不自动做**：1851 条 orphan（多为候选行缺来源键，逐条确认或放弃）；16 条 identity recheck 走 identity 模块落库；unknown 2 条人工判。
   - 每批 apply 记下 batch_id（撤回凭证）。撤回含归属修复的批次必须 `confirm_owner_repair=True`。
5. **灰度开关序列**（改 `StellaData/.env`，每次改完重启）：
   1. `REPLY_ATTRIBUTION_GUARD_MODE=shadow` —— 记录拦截/兜底决策，不改变发送；观察 24h 日志无异常。
   2. 单群切 `enforce` —— 只对指定灰度群；其余群维持 shadow。
   3. `PROACTIVE_VERIFICATION_CONTRACT_MODE` 同样 off→shadow→enforce，主动候选缺源应 skip（skip 是正确动作，单独统计）。
   4. `PERSONAL_MEMORY_SHARE_ENABLED=true` 只在用户明确表达过分享意愿的私聊对上验证；不全库泛化。
6. **灰度窗口**：≥48 小时；≥200 个多人/历史/纠正有效轮次；≥20 个**有来源且可承接**的主动验证机会。流量不足延长。

## 2. 观察项（灰度期间每日核对）

- 最终台词 vs 证据来源：作者/对象/极性抽查（人工，每次 ≥20 条）。
- 实际 @ 的对象、receipt、BOT_SELF 源/收件人一致。
- memory owner/audience：新写入 PERSON 行归属正确；无新的 SPACE 错误副本。
- 候选记账：无不相关候选被确认；缺源候选 skip 有终态记录。
- 撤回暖缓存：撤回后立即不可见（现场复演一次）。
- guard 日志：shadow 阶段统计 blocked/fallback/pass 占比；enforce 后漏过关键错误=立即停。

## 3. 中止与回滚

**任一发生即停止晋级**（计划 §8.3）：关键错归、越权召回、错误记账、旧错误副本复活。

回滚顺序：
1. 关主动发送与共享新增（合同模式回 off，share 回 false）——保留 ref 与隔离防线；
2. guard 从 enforce 退 shadow（不退 off：不能回到会发已确认错归内容的自由通道）；
3. 数据按 batch 撤回（`revoke_batch(batch_id, confirm_owner_repair=...)`，副本先演练）；
4. 应用/native 版本配套回退（schema 18 为 additive，回退应用保留新列表可运行）。

## 4. P8 离线验收状态（开发侧，供对照）

- 确定性测试：repair 43 例（含强化后的整行 round-trip 断言）、attribution wiring+repair 55 例、focused 集合 42 例、native selector/benchmark/promotion 22 例、cargo test 16 例 —— 全绿。
- native wheel：`stella_memory_rust-0.1.0-cp310-abi3-win_amd64.whl` 已构建并安装（api 2 / schema 18）。
- benchmark parity：21/24 硬匹配；`rank-casual/recency/tech` 3 例 `conversation_order` 硬不一致（其余为诊断级 score_delta）。未闭环，灰度门不卡此项但必须记录。
- 模型重放：260 样本（4 现场×30 + 16 矩阵×5 + 12 边缘×5），生产 persona（sha256 24b960…bee5f 与冻结基线一致）、8081/qwen3.8-flash-next-iq2_xs、temp 0.7、max_tokens 2000、guard enforce。结果目录 `docs/reports/evidence/dialogue-attribution-20261005/p8/`。
- 数据修复：生产库快照 round-trip PASS（见 p8/repair-roundtrip-result.json）；preview 清单四件套已冻结。

## 5. 明确不做

- 不在灰度前打开任何 enforce 开关「先试试」；
- 不把离线矩阵通过当作灰度替代；
- 不清理长期记忆、不改写原始历史、不做生产全库 backfill（orphans 只逐条确认）；
- 0/N 通过不宣称未来绝对零错误。
