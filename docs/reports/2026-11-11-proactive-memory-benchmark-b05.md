# 主动参与与记忆 Benchmark B05 — MemUse / ChMap 实现与离线门

- 状态：**B05 runner、离线 rank/boundary、MemUse 72-pair joint、pairing 72-pair 扩样已完成；M6 有 5-pair COMPLETE 样本和 full72 的 200-call partial，ChMap topic points 仍为部分覆盖。** `MEASURED_IN_SCOPE` 仅适用于各自完成的样本范围；完整 B05、B06 人工盲评、B08 平台验收及整体产品效果仍 NOT READY。
- 分支：`codex/proactive-memory-benchmark-implementation`；PR #130。
- 数据：MemUse frozen registry 的 72 个正例、72 个负例及训练期 session-summary corpus；ChMap topic_rank 149 条。原始公开数据留在 gitignored `memory/benchmark/_public/proactive_eval/raw/`。
- 运行环境：Python 3.12.3 / `uv` 隔离依赖；临时工作区 `/tmp/stella-pr130-b05-offline-final`，隔离 home 位于工作区内。没有读写生产库、用户配置或聊天记录。
- 离线报告：`/tmp/stella-pr130-b05-offline-final/report/proactive_b05_report.json`；SHA-256 `b465421aa511b9059cb8312c2a6f83ebb3584fee363bc68d05d246ad6a3e505a`；`stella-proactive-b05-report/1` schema **PASS**；状态 `MEASURED_IN_SCOPE`，`rank` 与 `boundary` 均 `COMPLETE`，embedding 与模型调用为 0。Rust selector 实际结果 backend 为 Python（requested/selected 均为 python）。

## 离线结果

| 检查 | 样本 | 结果 |
| --- | ---: | --- |
| ChMap topic_rank / rule | 149（113 可评分，36 条 gold 不在候选集） | MRR 0.1230；Recall@1/3/5/10 为 0.0354 / 0.1062 / 0.1327 / 0.3186；gold never-ranked 26 |
| ChMap topic_rank / FTS | 149（113 可评分，36 条 gold 不在候选集） | MRR 0.1301；Recall@1/3/5/10 为 0.0354 / 0.1062 / 0.1327 / 0.3186；gold never-ranked 7 |
| MemUse M3/M4/M5 boundary / rule | 72 positive items | 0 violations；gold packed 72/72 |
| MemUse M3/M4/M5 boundary / FTS | 72 positive items | 0 violations；gold packed 72/72 |

排名结果是组件级检索基线，不表示回复质量或产品收益。`boundary` 在每个正例隔离库中同时放入合格 gold、归档/过期副本、跨空间副本、内部可见性副本和 observing candidate；统计未发现违规副本进入 pack。

## 有界真实模型样本（2026-11-11）

- endpoint：用户提供 `http://127.0.0.1:8081/`。只读 `/v1/models` 返回 HTTP 200，唯一 ID 为 `qwen3.8-flash-next-iq2_xs`；B05 对 reply/judge 和 M6 memory role 的 `/models` 预检均通过。未指定独立 `--judge-model`，所以 reply 与 judge 使用同一模型。所有工作目录在 `/tmp/stella-pr130-b05-*`，每次运行的 `STELLA_HOME` 在对应工作目录内；没有访问生产 home、数据库、聊天记录或配置。

| Task | 样本范围与执行 | 结果摘要 | 最终 JSON 报告 / SHA-256 |
| --- | --- | --- | --- |
| `joint` | MemUse 12/72 pairs（12 正、12 负；60 条）；`chmap-records=10` 展开为 15 topic points（45 条）；首轮 200 次调用后续跑 10 次，合计 210 | 0 errors，105 reply + 105 judge，未截断。正例 integration：M0 3/12、M1 8/12、MS 4/12；M1−M0 差 +0.4167，95% cluster-bootstrap CI [−0.2222, 0.7143]，12 项/4 clusters。ChMap yes 点 M1 callback 5/9、M0 0/9；M1−M0 差 +0.5556，CI [0.2222, 0.8889]，9 clusters。 | `/tmp/stella-pr130-b05-joint-qwen38-12pairs-10chmap/report/proactive_b05_report.json`；`234f7b94071c5ecbb4f0545374cafa5bdea6c5f2c7988ff6b6810ab9bf27805e` |
| `joint-full` | MemUse 全部 72 pairs（positive/negative；360 条）；`chmap-records=0` 选全部 record indices，156/417 topic points（468 条）；8 个 200-call partial 后最后 56 次，合计 1,656（828 reply + 828 judge） | `MEASURED_IN_SCOPE`、`COMPLETE`、0 errors、无截断。MemUse 正例 integration：M0 10/72、M1 39/72、MS 25/72；M1−M0 +0.4085，95% CI [0.3000,0.5303]（71 项/22 clusters）；MS−M0 +0.2083，CI [0.1000,0.3448]（72 项/22 clusters）。负例 overuse：M0 25/72、MS 27/72，MS−M0 +0.0278，CI [−0.0625,0.1081]（72 项/23 clusters）。ChMap label_yes callback：M0 15/99、M1 54/99，M1−M0 +0.3939，CI [0.2828,0.4949]；label_no 的 M1 premature callback 差 +0.2807，CI [0.1579,0.4035]；M2 irrelevant-topic intrusion 24/99（2 unscored），M2−M0 +0.2078，CI [0.1503,0.2710]。 | `/tmp/stella-pr130-b05-joint-qwen38-full/report/proactive_b05_report.json`；`846f35f1be8ec493c28fb43802fcb22b58d33b62508ae14134dcfaa85a72cb02` |
| `pairing` | MemUse 33/72 pairs，T0/T3/T0+guard 各 33 条，共 99 条；首轮 200 次后续跑 17 次，合计 217 | 0 failed/unscored、无截断。正确 verdict：T0 14/33、T3 12/33、guard 8/33。T3−T0 差 −0.0606，95% CI [−0.1724, 0.0690]；guard−T0 差 −0.1818，CI [−0.2857, −0.0938]，各 11 clusters。 | `/tmp/stella-pr130-b05-pairing-qwen38-33pairs/report/proactive_b05_report.json`；`f8206b67aa93cf543049a040d4d14acc714154321982c578bdca4effc7451331` |
| `pairing-full` | MemUse 72/72 pairs，T0/T3/T0+guard 各 72 条，共 216 条；两轮预算各 200 次，最后续跑 9 次，共 409（243 reply + 166 judge） | `MEASURED_IN_SCOPE`、`COMPLETE`、0 errors、无截断。correct verdict：T0 18/72、T3 15/72、guard 11/72；unscored 分别 17、17、16。配对差异按 55 项 / 20 clusters 计算（17 对因 unscored 排除）：T3−T0 −0.0545，95% CI [−0.1321, 0.0192]；guard−T0 −0.1273，CI [−0.2000, −0.0435]。 | `/tmp/stella-pr130-b05-pairing-qwen38-72pairs/report/proactive_b05_report.json`；`6a5a891725c0242e96de46730203db804750f571505721f9411c1b907160e938` |
| `m6` | 最短历史 1 pair（正负各 1 项），7 sessions / 122 messages | 13 次调用、65.638 秒，0 errors；准入/采集 122/122 允许。产生 10 个候选，全部 OBSERVING、active memories 为 0，因此此 smoke 未验证到写入后可检索记忆。1 次 consolidation 截断后缩小批次重试；3 次 extract 达到 1,000 token 上限并按生产逻辑回退到阶段一候选。 | `/tmp/stella-pr130-b05-m6-qwen38/report/proactive_b05_report.json`；`52470a20c3e2965f06782a5edbc51bb21563523758ffe5e80708c4de4c6d3c5b` |
| `m6-5pairs` | 最短历史 5 pairs、10 items，40 sessions / 390 messages | `MEASURED_IN_SCOPE` / `COMPLETE`、0 errors；62 calls、322.626 秒。48 candidates 全为 OBSERVING、active memories 为 0；positive integration 0/5，negative overuse 1/5、fabricated recall 1/5、unprompted recall 0/5。consolidation 截断 8 次、extract 截断 10 次并回退阶段一。 | `/tmp/stella-pr130-b05-m6-qwen38-5pairs/report/proactive_b05_report.json`；`3d5e24f53ca948c9052ab417f01a024a3dc8409f64d4335172594af4eeb9fb45` |
| `m6-full72-partial` | 配置 72 pairs；首个 200-call 预算轮次，1,597.847 秒 | `PARTIAL` / `PARTIAL_BUDGET`，200 calls 到限；7 条 positive M6 row、7 个 pair ID，尚无 negative rows，因此不计算 paired estimate。报告仅有 1 个 `BudgetExceededError`、没有其他错误。多次缩批/回退和 consolidation 中止保留在隔离库与日志；预算内 role calls：capture 25、consolidation 101、extract 60、reply 7、judge 7；consolidation/extract 截断分别 41/60。partial JSON schema PASS，SHA 见右侧。 | `/tmp/stella-pr130-b05-m6-qwen38-full72/report/proactive_b05_report.json`；`a492903defec0833b9f82d65ba1bee21a5d315f76002e1a705eece09008e2805` |

扩样前另跑了 1-pair 链路 smoke：joint 16 次调用，报告 `/tmp/stella-pr130-b05-joint-qwen38/report/proactive_b05_report.json`（SHA `d7a180e486a077f72d45a74689e81fd0f6a5b8dd321995440e0242437e2b5d8b`）；pairing 6 次调用，报告 `/tmp/stella-pr130-b05-pairing-qwen38/report/proactive_b05_report.json`（SHA `a5f21c05b1dbde09f9dad0d9456a0242a077f7c865f7512a11e5a4e7936108d8`）。两者样本被后续扩样覆盖，单独用于先验链路检查。原先已完成模型样本共 462 completions；pairing 72-pair 扩样 409 次，joint-full 扩样 1,656 次，M6-5pairs 62 次，M6-full72 partial 200 次，当前累计 2,789 completions。joint-full 每轮 200 次预算，共 8 份 partial + 最后一轮 56 次；文件保存在 `/tmp/stella-pr130-b05-joint-qwen38-full/report/`，最终 JSON 的 `budget` 只记最后一轮。

此前 joint 和 33-pair pairing 扩样都曾在首轮 200 次调用预算处留 partial 报告，随后按同一指纹续跑；保留文件分别为 `/tmp/stella-pr130-b05-joint-qwen38-12pairs-10chmap/report/proactive_b05_report.partial-budget.json`（SHA `e0bfed54633233deaf82ffa69ba5238be373922c13801057a53487443c81db73`）与 `/tmp/stella-pr130-b05-pairing-qwen38-33pairs/report/proactive_b05_report.partial-budget.json`（SHA `be0353e87e5fdca8c7b5a9b92721a1afd1dfa4dd3e001e180e77498dce3dd53e`）。72-pair 扩样因端点短暂停止保存了两份 partial：`/tmp/stella-pr130-b05-pairing-qwen38-72pairs/report/proactive_b05_report.partial-budget.json`（SHA `56a21c86e2dc990dfd4c0f5830eb314749fdd791bc38654b61cc7ce36e3a2eaa`）和 `.../proactive_b05_report.partial-budget-2.json`（SHA `28a5af90a329aab8bda06a65f4ab13c5d13bb9d9086554162b23e851ce3bb355`）；用户恢复 8081 后同指纹续跑 9 次调用完成，最终报告 SHA `6a5a891725c0242e96de46730203db804750f571505721f9411c1b907160e938`。

pairing 与 joint 的 MemUse 部分均在当前模型和固定 `rule` retrieval 下覆盖完整 72 pairs；joint 的 ChMap 使用全部 record indices 选出 156/417 topic points，仍未覆盖全部 points。M6 的独立 5-pair 样本已完成；full72 尝试止于 200-call 预算，报告仅有 7 个正例判分行，没有可配对的负例结果。reply/judge 同模型有自评偏差；M1 是 oracle 上界。上述比例和区间仅作当前评测范围内诊断，不构成产品收益或真实平台行为结论。

## Pairing 全量扩样续跑（已完成，2026-11-11）

- 新隔离目录：`/tmp/stella-pr130-b05-pairing-qwen38-72pairs`；固定模型 `qwen3.8-flash-next-iq2_xs`、`--channel rule`、`--memuse-pairs 0`，每次进程 `--max-calls 200 --max-runtime-seconds 1800`，复用同一 fingerprint。
- 两次模型调用预算各耗尽 200 calls；checkpoint 有 212/216 条条件记录（T0 71/72、T3 71/72、T0_GUARD 70/72）。报告均为 `PARTIAL` / `PARTIAL_BUDGET`，不作为完整 72-pair 结果解读。partial JSON SHA-256 分别为 `56a21c86e2dc990dfd4c0f5830eb314749fdd791bc38654b61cc7ce36e3a2eaa` 与 `28a5af90a329aab8bda06a65f4ab13c5d13bb9d9086554162b23e851ce3bb355`，保存在同目录 `report/proactive_b05_report.partial-budget*.json`。
- 第三次续跑起初因 `URLError` 无法预检，未调用模型；用户恢复 `http://127.0.0.1:8081/` 后，保持同一参数与 fingerprint 再次 `--resume`，9 次调用后状态 `MEASURED_IN_SCOPE` / `COMPLETE`、216 行、0 errors、无截断。最后报告 SHA-256 `6a5a891725c0242e96de46730203db804750f571505721f9411c1b907160e938`，schema 为 `stella-proactive-b05-report/1`。正确 verdict 与配对 CI 见上表；各 cell 有 16–17 个 unscored，配对差异只基于 55 个可评分项。

## M6 写侧扩样与 budget checkpoint（2026-11-11）

- 5-pair 隔离样本：选择最短历史 5 pairs（10 items、40 sessions、390 messages），执行 62 model calls / 322.626 秒，`MEASURED_IN_SCOPE` / `COMPLETE`、0 errors、10 条 judge rows。48 个 memory candidates 全部 `OBSERVING`、active memories 为 0；正例 integration 0/5、负例 overuse 1/5，未测出写后可检索记忆。report SHA-256 `3d5e24f53ca948c9052ab417f01a024a3dc8409f64d4335172594af4eeb9fb45`。
- full72 checkpoint 使用独立 workdir `/tmp/stella-pr130-b05-m6-qwen38-full72`，选全 72 pairs、相同 8081 reply/MEMORY endpoint、固定 `rule` retrieval。单轮达到 200 calls 后停止，耗时 1,597.847 秒；状态 `PARTIAL_BUDGET` / `PARTIAL`，7 条正例 judge rows、7 pair IDs、0 negative rows；报告仅有一个 `BudgetExceededError`，没有其他错误，因此没有 paired estimate。角色调用为 capture 25、consolidation 101、extract 60、reply 7、judge 7；consolidation/extract 截断 41/60。生产写入阶段出现多次在批次缩到 7 条后仍截断而中止；budget exception 在 `run_m6` 返回前触发，所以报告 `m6_write_side` aggregate 为空，但已完成 judge rows、数据库和 meta/checkpoint 都留在该隔离 workdir。最终报告 schema PASS，SHA-256 `a492903defec0833b9f82d65ba1bee21a5d315f76002e1a705eece09008e2805`。
- 这次 200-call 预算是 full72 的首个 partial，不代表整个 M6 有足够预算。按计划全数据集要另设总调用上限，当前未自动续跑。后续若继续，使用相同 workdir 与 fingerprint，原命令参数保持不变并加 `--resume`；先确认新的累计模型调用上限，再继续。不要把当前 7 条正例与 5-pair 完整样本相加成一组配对成绩。

## 未运行与限制

- 尚未覆盖的全量样本：ChMap 剩余 261/417 topic points；M6 full72 仅完成首个 200-call partial，尚余配对与负例。根据本次 1,597.847 秒 / 200 calls 的覆盖量，继续 M6 前需要单独确定总调用上限；未自动透支或续跑。本次所有模型任务固定使用 `rule` retrieval，embedding/hybrid 通道未运行。
- B05 会话用户 ID 显式传给生产 retrieval，避免 group-space 查询跨用户读取；pairing actor 输入只含 qid/question，不传 scorer gold answer。reply/judge prompt 把回忆内容和判分字段标为数据，不作为可执行指令。
- M1 是 oracle 上界，MS 是同一用户在触发 session 之前的 summary store；B06 人工盲评与 B08 平台验收未覆盖。分支 participation manager 不读取记忆内容决定是否发言，因此本轮及未来 B05 模型结果只测固定决策下的内容。
- 已完成的 M6 1-pair 与 5-pair 样本均未形成 active memory，不能据此声称写后 retrieval 已验证。full72 首轮 partial 的 `m6_write_side` 汇总为空，因为预算异常在 `run_m6` 返回前终止；7 条逐项 judge 行仍保存在 checkpoint。模型截断和回退均保留在报告中，不因 runner 完成或写侧轨迹继续推进而视为行为通过。
- LoCoMo-Conv license 问题未解除；ChMap dialogue_data 的话题摘要任务不属于本包范围。

## 验证命令

- `uv run --no-project --with-requirements requirements.txt --with-requirements requirements-dev.txt --with jsonschema pytest tests/evaluation/test_proactive_b05.py tests/test_memory_eval.py -q` — 21 passed。
- `uv run --no-project --with-requirements requirements.txt --with-requirements requirements-dev.txt --with jsonschema ruff check proactive_eval/b05.py proactive_eval/b05_data.py proactive_eval/b05_prompts.py memory_eval/answer.py tests/evaluation/test_proactive_b05.py tests/test_memory_eval.py` — PASS。
- 同一 `uv` 隔离依赖执行 `pytest tests -q` — 4,399 passed、34 skipped、3 existing warnings，退出码 0。
- 原提交文档门禁：`python3 scripts/check_docs.py` — 127 files / 1,365 links / 577 anchors / 0 errors；模型结果更新后及本次 partial checkpoint 更新后均为 127 files / 1,366 links / 577 anchors / 0 errors。
- 实际离线运行：`python -m proactive_eval.b05 --workdir /tmp/stella-pr130-b05-offline-final --tasks rank,boundary --rank-channels rule,fts --max-runtime-seconds 1800` — exit 0、schema PASS、298 rank rows / 144 boundary rows、28.961 秒。
- 原有已完成 model task、最终 72-pair pairing、joint-full、M6-5pairs 和 M6-full72 partial 报告均通过 B05 内置 `stella-proactive-b05-report/1` Draft 2020-12 schema 验证；joint pilot、joint-full、33-pair pairing pilot、72-pair pairing、M6 smoke 与 M6-5pairs 为 `COMPLETE`、0 errors；M6-full72 为 `PARTIAL_BUDGET`、7 rows、唯一 error 为预算耗尽。joint-full 报告有 2 个 ChMap M2 judge failures/unscored，bootstrap 按报告排除了相应配对；pairing-full 17 个 pair 因 unscored 输出未进入差异估计，结果表保留排除数。
- 本轮 `python3 scripts/check_docs.py` 为 127 files / 1,366 links / 577 anchors / 0 errors；`python3 -m json.tool feature_list.json`、`git diff --check` 与 M6-5pairs/full72 partial 的 Draft 2020-12 schema 验证通过；joint-full workdir 的 8 个 partial + 1 个 final 报告也均通过 schema。GitNexus 编辑前索引为 `ed3c2c7`、比 HEAD 落后 1 个提交，当时章节 upstream impact 报 292 / CRITICAL（29 direct、4 processes、8 modules）。刷新后索引与 HEAD `d20a9f2` 一致，runner identity current、`incompleteReasons=[]`；工作树 4 个文档/状态文件有内容 drift。精确 Section UID context/impact 为 UNKNOWN / 0 callers，依规则以文本搜索补证：标题无外部引用，报告路径只见于 feature/progress/handoff 状态文档，UNKNOWN 不按 LOW 处理。当前 `detect-changes --scope all` 对 4 个文档/状态文件无 indexed-symbol hunk overlap。compare main 为 364 files / 782 affected processes / CRITICAL；changed-symbol 归因在重复运行中不稳定，已观察到 317–627；`--limit 1000` 输出仍截断，最近一次仍有 772 个流程未列出。图抽取仍截断（3,563/3,763 候选入口未入图、25 条 trace 深度封顶、1,148 个 callee 跳过、45 个 walk 达预算），缺失流程不代表无影响。源 diff 没有代码文件。
