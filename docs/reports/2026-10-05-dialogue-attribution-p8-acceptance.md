# P8 验收报告 —— 对话归属复发修复（模型重放 / native parity / 数据修复 round-trip）

日期：2026-10-05。分支 `feat/dialogue-attribution-role-repair`。
计划：[2026-10-05-dialogue-attribution-review-findings-repair-plan.md](../plans/2026-10-05-dialogue-attribution-review-findings-repair-plan.md) §8.2 / §8.3。
执行环境：本机生产同款（8081 / `qwen3.8-flash-next-iq2_xs`、temperature 0.7、max_tokens 2000、生产 persona `space_1.md` sha256 `24b96058…bee5f` 与冻结基线一致、guard enforce）。
逐样本原始报告（wire prompt hash、raw output、guard 决策、最终输出）在 [evidence/dialogue-attribution-20261005/p8/](evidence/dialogue-attribution-20261005/p8/)。

## 1. 模型重放（260 样本）

构成：4 冻结现场 ×30（120）+ 原 16 矩阵 ×5（80）+ 12 新边缘 ×5（60）。
每样本：V2 投影 prompt + 生产 persona + reply_plan 协议段（`--guard` 时与 guard 同源证据表注入，见提交 4036f21）→ 采样 → guard enforce 重放（证据/授权由夹具派生）。

### guard 统计（enforce 口径）

| 组 | 样本 | pass | blocked | fallback |
| --- | --- | --- | --- | --- |
| 冻结现场 ×30 | 120 | 108 | 4 | 8 |
| 原矩阵 ×5（80 场景） | 80 | 76 | 1 | 3 |
| 新边缘 ×5 | 60 | 57 | 0 | 3 |
| **合计** | **260** | **241 (92.7%)** | **5 (1.9%)** | **14 (5.4%)** |

- 采样错误 0；关键词筛查旗标 0；协议段缺失 0。
- 非 pass 原因分布：`parse_failed`（模型未输出协议块）14 例 → 服务端受限兜底；`risky_pattern:你之前说`（模型在 `<now>` 槽自由转述历史）5 例 → 拦截不发送。
- 典型拦截样例（scene-090046，私聊 CP 事实）：模型输出 `<ref id="msg_0"/>` 引用正确，但 `<now>` 里写「你之前说和Lumi是CP」——历史转述必须走服务端渲染（「N说过：…」），guard 按设计拦截。**行为保守但符合合同**；拦截/兜底率 ~7% 是灰度体验观察项（清单 G2）。

### 独立 oracle 判定（`tests/attribution_oracle.py::judge_reply`，不依赖业务模块）

- 260 条最终发送文本（reject 按"无发送"计）：**oracle 关键命中 1 例** —— scene-131951 样本 5，`alias_transfer`。
- **语义复核**：该样本 final 为「知道啦，Nox不是红中没摸鱼…… N说过：『我是Nox，不是红中没摸鱼』」——「红中」只出现在对 N 原话否定尾句的引用中，夹具 `acceptable` 明确「否定尾句不产生任何别名」；不构成「把红中登记为 N 的别名」。判为 **oracle 词法对否定辖域的误报**，留用户终审。
- 规则口径门槛：0 关键错归发送 / 0 越权共享 / 0 不相关候选记账 —— **达标**（1 例命中经复核为误报）。
- 任务完成：原 80 场景 **76/80 pass ≥ 72** ✓；新增边缘 57/60 = **95% ≥ 90%** ✓（3 例 fallback 为安全兜底，非错答）。
- 边界：身份**登记**层（judge_identity）不经离线重放覆盖（重放不落库），由 R5/R7 链路测试（attribution wiring + repair 55 例）与灰度现场覆盖。0/N 通过不宣称未来绝对零错误。

### 中途修正（重放有效性）

- 首轮重放（scene 阶段）全部 fallback 的根因：评估 prompt 未含 `<reply_plan>` 协议指令（生产链路由 prepare 注入），模型自由文本 → guard 结构性 `parse_failed` 兜底——量的是兜底路径不是归属质量。已修复（4036f21）并**作废首轮 120 样本重跑**；修复后同场景 25/30 pass + 4 拦截，模型稳定输出带版本协议块。

## 2. native parity（P8-1）

- `cargo test`：**16/16** 通过（native 测试夹具 v15→v18，提交 e4d234f）。
- maturin wheel 构建并安装：`stella_memory_rust-0.1.0-cp310-abi3-win_amd64.whl`，加载验证 api 2 / schema 18。
- benchmark `--compare`：**21/24 硬匹配（87.5%）**。硬不一致 3 例（`rank-recency-001` / `rank-tech-001` / `recommend_001` 的 `conversation_order`），其余为诊断级 `score_delta`（阈值 0.001）。**未闭环**：rank 排序的 Python/Rust 既有差异，benchmark 用例不含 owner/audience 维度，与本轮归属修复无直接交集；灰度门不卡此项，如实记录。

## 3. 数据修复 round-trip（P8-3）

- 生产库 SQLite backup API 快照（schema 16）上：13 条 `duplicate_deprecate` apply → revoke **逐列还原 PASS**（revoke 后副本与生产库整行零差异）。
- 期间发现并修复：`revoke_batch` 原来在还原 old_state 后又覆盖 `updated_at = CURRENT_TIMESTAMP`，违反 F8 列级合同——单测只断言 4 列未抓住（提交 b9bf470，含强化的整行断言）。
- preview 冻结（生产库只读）：**duplicates 13 / orphans 1851 / identity_rechecks 16 / unknowns 2 / private_owner_repairs 0**；四件套清单在 `p8/repair-preview-*.json`。
- **未对生产库做任何写入**；dry_run 零写入验证通过。

## 4. 确定性测试与门

- 全量 `pytest tests/`：**3594 passed / 17 skipped / 0 failed**（4 分 12 秒）。
- ruff 全仓：通过。
- 消息流漂移门：`--check` 通过（manifest 重生成 0cbb0ab4f203，提交 5512355）。

## 5. 出口判定

§8.2 离线验收：**达标（规则口径，含 1 例 oracle 误报复核）**。P8 的模型重放 / native 构建 / 数据修复 round-trip 三项从「用户待执行」变为「已执行、结果在案」。
**整计划仍不宣称「已修复」**：真实 QQ 灰度（§8.3：≥48h / 200 有效轮次 / 20 有源主动机会）未做——按 [QQ 灰度执行清单](2026-10-05-qq-gray-rollout-checklist.md) 由用户执行；benchmark rank 差异与 ~7% 拦截/兜底率是两个已知观察项。

## 6. 移交用户

1. QQ 灰度按清单执行（schema 16→18 副本演练 → 部署 → 修复批次审查 → off→shadow→enforce → 48h 观察）。
2. 1851 条 orphan 与 2 条 unknown 人工逐条判定（工具不猜，须 confirm 才可 apply）。
3. 本报告 §1 的 1 例 oracle 命中样本（scene-131951 #5）终审。
4. benchmark rank 差异若需闭环，另立任务。
