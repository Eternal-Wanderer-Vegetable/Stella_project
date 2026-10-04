# 检测清单：多人对话身份与归属修复

> 对应分支 `feat/multi-user-identity-repair`（M0–M4 已实施 + M5 离线验收，7 提交至 `a6b40d7`）。
> 计划：`docs/plans/2026-10-04-gitnexus-plan-multi-user-identity-repair.md`；实施报告：`docs/reports/2026-10-04-multi-user-identity-repair-implementation.md`。
> 用法：A → B → F 本机可执行；**C / D / E 存档为待测试项**（2026-10-04：环境暂不具备，见各节「解除阻塞条件」）。
> 每项给出操作与**期望结果**；勾选前先确认期望成立。
>
> **执行记录（2026-10-04）**：
> - A 组全绿（全量 3392 passed ×2、ruff 全仓干净、manifest 门禁、detect-changes 无 partial/truncated）。
> - B1 完成：生产库**副本** v15→v16 dry-run 干净（0 行改动、加列/索引 14 项、五表行数守恒、信封列就绪）。校验器两类报警均为**非 v16 问题**：空间名报警是隔离临时目录缺账本所致（真实账本含 space_1/space_2）；FTS 漂移在未迁移的 v15 副本上即存在（19 行，存量问题，10-03 记录为 12 行后自然增长，建议单列修复）。
> - **运行时冒烟（重启）**：旧进程（PID 19992，run6）已终止，新进程 PID 46184 于 10:34 启动；生产库自动迁移 v15→v16 成功（迁移前自动备份 `agent_memory.db.pre-v16-20261004-103415.bak`）；8080 起服、OneBot Bot 1694717255 已连接；带白群新消息已带 v16 信封落库（conversation_key + relation_version=1，无关系字段为空 = unknown 语义正确）。
> - **native 后端注意**：bot 跑在 conda stella（py3.10）可加载 cp310 `.pyd`，但 pyd 仍是 schema 15 合同——首次检索时会因 15≠16 被拒并**回退 Python 后端**（预期，见 C1）。日志当前无 backend 告警是因为检索尚未触发（懒加载）。

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
  `test_scheduling_settings_defaults`（子批隔离抖动，全量下通过）。
- 本机差异：pytest-timeout 未安装，全量命令去掉 `--timeout` 参数（CI 不受影响）。

## B. 副本迁移与回退演练（本机，用副本，不碰生产库）

- [x] B1 生产库副本 dry-run：sqlite backup API 拷贝 → 隔离 STELLA_HOME 迁移。
  实际：v15→v16 成功，changed_rows=0、additive=14、group_messages 2554/memories 1136/candidates 1421/atomic_facts 2/user_profiles 48 全部守恒，信封列与身份两表就绪。
- [ ] B2 副本真实升级后功能抽测：对升级后副本跑一轮检索/tail 组装，确认信封列与 FTS 行为。
- [ ] B3 回退演练：切回 038e419 代码 + v16 库启动/跑测试（additive 生效，旧代码照常运行）。
- [ ] B4 双进程约束：演练期间确认新旧进程不共享可写会话库。

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

## F. 性能门槛（本机可执行，待执行）

- [ ] F1 preprocess+compose+budget p50/p95：同一 fixture 库，基线（a470ce5^）与当前各测一轮（不含 LLM）。
  期望：p95 增加 ≤20ms；超标先合并查询/利用 revision 缓存，不得删归属头换速度。

---

## 运行时交接（2026-10-04 重启）

- 新进程：PID **46184**，`C:\Users\Vegetable\.conda\envs\stella\python.exe bot.py`，工作目录仓库根，分离（隐藏窗口）。
- 日志：`logs/_bot_restart_20261004.log`（stdout）与 `logs/_bot_restart_20261004.err.log`（stderr，仅既有插件提示）。
- 想换回自己终端跑：`taskkill /PID 46184 /T /F` 后照常 `.\bot.py` 即可。
- 生产库迁移前备份：`StellaData/memory/agent_memory.db.pre-v16-20261004-103415.bak`。
