# 检测清单：多人对话身份与归属修复

> 对应分支 `feat/multi-user-identity-repair`（M0–M4 已实施 + M5 离线验收，7 提交至 `a6b40d7`）。
> 计划：`docs/plans/2026-10-04-gitnexus-plan-multi-user-identity-repair.md`；实施报告：`docs/reports/2026-10-04-multi-user-identity-repair-implementation.md`。
> 用法：A → B → F 本机可执行；**C / D / E 存档为待测试项**（2026-10-04：环境暂不具备，见各节「解除阻塞条件」）。
> 每项给出操作与**期望结果**；勾选前先确认期望成立。
>
> **执行记录（2026-10-04）**：
> - A 组全绿（全量 3392 passed ×2、ruff 全仓干净、manifest 门禁、detect-changes 无 partial/truncated）。
> - B 组全部完成（B1–B4，见下）；F1 完成：两轮测量总 p95 增量 **+2.51 / +2.55ms**，远低于 ≤20ms 门槛。
> - **运行时冒烟（重启）**：旧进程（PID 19992，run6）已终止，新进程 PID 46184 于 10:34 启动；生产库自动迁移 v15→v16 成功（迁移前自动备份 `agent_memory.db.pre-v16-20261004-103415.bak`）；8080 起服、OneBot Bot 1694717255 已连接；带白群新消息已带 v16 信封落库（conversation_key + relation_version=1，无关系字段为空 = unknown 语义正确）。
> - **native 后端注意**：bot 跑在 conda stella（py3.10）可加载 cp310 `.pyd`，但 pyd 仍是 schema 15 合同——首次检索时会因 15≠16 被拒并**回退 Python 后端**（预期，见 C1）。日志当前无 backend 告警是因为检索尚未触发（懒加载）。
> - **B1 校验器报警甄别**：空间名报警是隔离临时目录缺账本所致（真实账本含 space_1/space_2）；FTS 漂移在未迁移的 v15 副本上即存在（19 行，存量问题，10-03 记录为 12 行后自然增长，建议单列修复）。

---

## A. 本机自动化回归（已执行 ✅，合并前可重跑）

- [x] A1 全量测试：`python -m pytest tests/ -q -n auto --dist loadgroup`
  实际：`3392 passed, 17 skipped`，0 failed（连续两次一致）。
- [x] A2 lint：`python -m ruff check .` → All checks passed。
- [x] A3 flow manifest 门禁：`pytest tests/observability/test_message_flow_contract.py -q` → 11 passed。
- [x] A4 GitNexus 门禁：每次提交前 `detect-changes --scope all`，无 partial/truncated。
- [x] A5 关键新套件点验：`tests/test_multi_user_identity.py`（T01/T07/T18）、
  `tests/test_message_relations.py`（T08–T11）、`tests/test_conversation_identity.py`（T03–T06/T15）、
  `tests/test_structured_conversation_budget.py`（T12/T13/T19）、`tests/test_session_compact.py`（T14 CAS）。
- 已知抖动项（复跑确认非本分支回归）：`test_query_daily_reads_temp_db`（xdist 偶发）、
  `test_scheduling_settings_defaults`（子批隔离抖动，全量下通过）、
  `test_flow_watch_finish_captures_reply_text`（xdist 偶发，单独跑恒过）。
- 本机差异：pytest-timeout 未安装，全量命令去掉 `--timeout` 参数（CI 不受影响）。

## B. 副本迁移与回退演练（本机，用副本，不碰生产库）

> **PR 合并 CI 修复记录（2026-10-04，`4e6fe97`）**：linux py3.12 的
> `test_concurrent_replay_bounded_by_unique_constraint` 因「两线程各自懒加载
> ensure_v2_schema + deferred BEGIN 升级死锁」报 no such table。修复：迁移事务
> 改 BEGIN IMMEDIATE 串行化、迁移连接 timeout 30s、备份 O_EXCL 并发选举；
> 该夹具改为单线程预迁移；新增并发迁移回归测试 + BEGIN IMMEDIATE 源码锚点。
> 原用例连跑 10 次全绿，全量 3394 passed。

- [x] B1 生产库副本 dry-run：sqlite backup API 拷贝 → 隔离 STELLA_HOME 迁移。
  实际：v15→v16 成功，changed_rows=0、additive=14、group_messages 2554/memories 1136/candidates 1421/atomic_facts 2/user_profiles 48 全部守恒，信封列与身份两表就绪。
- [x] B2 升级后副本功能抽测（生产库 v16 实拷贝）：幂等 `ensure_v2_schema`→False（不重复迁移）；
  `build_context` 正常（short_term 561 字、tail_start_id=35536，重启后暂无 BOT_SELF 行故无「我：」渲染，逻辑有测试覆盖）；
  `retrieve_memories` 5 条候选**全带 owner 字段**、scope=PERSON（主体=真实 sender）；FTS 1137 行、版本 16；
  身份面 revision=0 / alias=''（空声明零异常）。
- [x] B3 回退演练（git worktree @ 516f79f 旧代码 × 生产库 v16 实拷贝）：旧 `ensure_v2_schema`→False 且版本保持 16
  （不降级、不回写）；旧 `record_message` 插入 v16 表成功（信封列取默认 NULL/0/'[]'）；旧 `build_context`、
  `retrieve_memories`（13 列、无 owner 键）、`fetch_pending_messages`（50 条）全链路可运行。**结论：回退应用+v16 库可正常运行。**
- [x] B4 双进程约束：演练全程探针只读写独立临时副本（B3 插入的 msg_id=990001 仅存在于副本），生产库仅由 bot
  进程（PID 46184）写入（行数 2554→2633 全部来自真实流量），bot 全程存活。**运维规则不变：真实回退时先停新进程再起旧进程。**

## C. native 双后端 —— **待测试（环境阻塞）**

> **解除阻塞条件**：py3.10 + maturin 可用的编译环境。

- [ ] C1 重新编译 native `.pyd`（`memory_rust/native`，随 `MEMORY_SCHEMA_VERSION=16` 合同）。
  期望：`_validate_native` 通过；`MEMORY_BACKEND` 默认模式下不再回退 Python。
  （当前已发布 wheel 为 cp310 schema15，在 bot 的 py3.10 下会因 15≠16 拒载回退——检索行为正确但走 Python 路径。）
- [ ] C2 `MEMORY_BACKEND=rust` 检索 parity（T07 native 半边）：scope/audience 矩阵与 Python 一致。
- [ ] C3 native 结果渲染降级：native 返回 dict 无 owner 字段 → `build_conversation_section` 按 legacy SPACE 语义呈现（不炸、不伪造归属）。
- [ ] C4 `MEMORY_BACKEND=shadow` 双跑对比：diff 报告无授权面差异。

## D. 真模型验收 T20 —— **待测试（环境阻塞）**

> **解除阻塞条件**：冻结的 IQ2_XS 端点与可复现采样条件。

- [ ] D1 冻结条件记录：模型字节/endpoint 角色/context_window/temperature/seed 支持/输出 reserve。
- [ ] D2 8 场景 × 5 次 = 40 场（A/B 切换、第三人纠正、同名自称、长上下文等）：
  三类串人（把 A 事实当 B / 机器人自称用户名 / 纠正者被当目标）**0/40**，且 ≥36/40 完成原问题；记录实际采样条件。
- [ ] D3 不达标回路：回改 prompt/规则；**禁止**新增每轮第二次身份 LLM 调用。

## E. 真机复演 —— **待测试（需要 NapCat 双号配合）**

> **解除阻塞条件**：NapCat 双号（A/B）+ 第三人 C 的测试 QQ 号；与 bot 操作者协调时间窗。
> bot 现以分离进程运行（PID 见下方「运行时交接」），重启由操作者执行。

- [ ] E1 A 自称 Allets → B 说「阿呆是我」→ B 问「我是谁」（T01）：B 得到「阿呆」，回答不出现 Allets。
- [ ] E2 A/B 轮流接同一话题、无 reply（T02）：身份不随话题继承。
- [ ] E3 C 说「他才是Allets」，无 reply 无 @（T03）：不写任何映射；有 reply/@ 时 C 不成为 A。
- [ ] E4 A「那我改名叫X」后问我是谁（T04）：下一轮立即生效，缓存/摘要不回旧名。
- [ ] E5 A/B 都自称 X（T05）：两个稳定 uid 并存，不合并。
- [ ] E6 第三人显式 @ 他人试图改称呼（T06）：现有权限拒绝，claim 服务无绕过。
- [ ] E7 一次回复 3 气泡（T09/T10）：history 呈现一个逻辑单元；失败泡不记「已送达」。
- [ ] E8 SOCIAL_ENABLED=false 时发带 reply/@ 消息（T11）：主历史关系照常入库。
- [ ] E9 私聊路径回归：上一分支 C1–C6 结论不倒退（含短结果直发全文）。

## F. 性能门槛（已执行 ✅）

- [x] F1 preprocess（record_message + build_context + build_user_context）+ compose+budget p50/p95：
  同一 v16 夹具（220 消息含 10×2 BOT_SELF 逻辑单元 + 42 记忆 + FTS）、隔离副本、N=120/轮、不含 LLM，
  基线=516f79f（generic 预算路径）vs 当前=HEAD（parts 预算路径），共两轮：

  | 阶段 | 基线 p50/p95 (ms) | 当前 p50/p95 (ms) | Δp95 |
  | --- | --- | --- | --- |
  | record | 2.97 / 4.11 | 3.36 / 4.45 | +0.34 |
  | context(tail) | 1.25 / 1.64 | 1.87 / 2.55 | +0.91 |
  | userctx(检索) | 2.63 / 3.24 | 3.53 / 4.34 | +1.10 |
  | budget | 0.16 / 0.26 | 0.21 / 0.33 | +0.07 |
  | **总 pipeline** | 7.10 / 8.40（次轮 8.08） | 9.07 / 10.91（次轮 10.63） | **+2.51 / +2.55** |

  **结论：总 p95 增量 ≈ +2.5ms，远低于 ≤20ms 门槛。** 增量来源符合预期：tail 关系列查询（48 行×11 列 vs 12 行×5 列）、
  身份 capsule 的 2–3 个小 SELECT、检索 owner 呈现列、record 17 列插入。budget 阶段（结构化 parts）本身仅 +0.07ms。

---

## 运行时交接（2026-10-04 重启）

- 新进程：PID **46184**，`C:\Users\Vegetable\.conda\envs\stella\python.exe bot.py`，工作目录仓库根，分离（隐藏窗口）。
- 日志：`logs/_bot_restart_20261004.log`（stdout）与 `logs/_bot_restart_20261004.err.log`（stderr，仅既有插件提示）。
- 想换回自己终端跑：`taskkill /PID 46184 /T /F` 后照常 `.\bot.py` 即可。
- 生产库迁移前备份：`StellaData/memory/agent_memory.db.pre-v16-20261004-103415.bak`。
