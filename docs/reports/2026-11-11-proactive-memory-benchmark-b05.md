# 主动参与与记忆 Benchmark B05 — MemUse / ChMap 实现与离线门

- 状态：**B05 runner、离线 rank/boundary 和已完成的有界真实模型样本已完成；pairing 全量扩样已启动但被模型端点中断。** `MEASURED_IN_SCOPE` 仅适用于各自选定的样本范围；完整 B05、B06 人工盲评、B08 平台验收及整体产品效果仍 NOT READY。
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
| `pairing` | MemUse 33/72 pairs，T0/T3/T0+guard 各 33 条，共 99 条；首轮 200 次后续跑 17 次，合计 217 | 0 failed/unscored、无截断。正确 verdict：T0 14/33、T3 12/33、guard 8/33。T3−T0 差 −0.0606，95% CI [−0.1724, 0.0690]；guard−T0 差 −0.1818，CI [−0.2857, −0.0938]，各 11 clusters。 | `/tmp/stella-pr130-b05-pairing-qwen38-33pairs/report/proactive_b05_report.json`；`f8206b67aa93cf543049a040d4d14acc714154321982c578bdca4effc7451331` |
| `m6` | 最短历史 1 pair（正负各 1 项），7 sessions / 122 messages | 13 次调用、65.638 秒，0 errors；准入/采集 122/122 允许。产生 10 个候选，全部 OBSERVING、active memories 为 0，因此此 smoke 未验证到写入后可检索记忆。1 次 consolidation 截断后缩小批次重试；3 次 extract 达到 1,000 token 上限并按生产逻辑回退到阶段一候选。 | `/tmp/stella-pr130-b05-m6-qwen38/report/proactive_b05_report.json`；`52470a20c3e2965f06782a5edbc51bb21563523758ffe5e80708c4de4c6d3c5b` |

扩样前另跑了 1-pair 链路 smoke：joint 16 次调用，报告 `/tmp/stella-pr130-b05-joint-qwen38/report/proactive_b05_report.json`（SHA `d7a180e486a077f72d45a74689e81fd0f6a5b8dd321995440e0242437e2b5d8b`）；pairing 6 次调用，报告 `/tmp/stella-pr130-b05-pairing-qwen38/report/proactive_b05_report.json`（SHA `a5f21c05b1dbde09f9dad0d9456a0242a077f7c865f7512a11e5a4e7936108d8`）。两者样本被后续扩样覆盖，单独用于先验链路检查；原已完成模型样本共 462 completions（joint 210 + pairing 217 + M6 13 + 初始 smoke 22）。本次额外全量 pairing 未完成扩样已增加 400 completions，总计 862 次成功 completions；最后一次续跑在模型预检阶段失败，没有发出 completion。

两个扩样任务都曾在首轮 200 次调用预算处留有 partial 报告，之后按完全相同指纹续跑；保留的首轮文件分别为 `/tmp/stella-pr130-b05-joint-qwen38-12pairs-10chmap/report/proactive_b05_report.partial-budget.json`（SHA `e0bfed54633233deaf82ffa69ba5238be373922c13801057a53487443c81db73`）和 `/tmp/stella-pr130-b05-pairing-qwen38-33pairs/report/proactive_b05_report.partial-budget.json`（SHA `be0353e87e5fdca8c7b5a9b92721a1afd1dfa4dd3e001e180e77498dce3dd53e`）。最终 checkpoint 报告包含续跑后的全部行；表中合计调用数由首轮与续跑各自报告相加，最终 JSON 的 `budget` 字段只记录最后一次续跑进程。

这些是当前模型、固定 rule retrieval 和选定样本上的 pilot，不能外推为 72-pair 全量结果。joint 只覆盖 12/72 MemUse pairs 和 15/417 ChMap topic points；pairing 覆盖 33/72 pairs；M6 只运行 1 pair。judge 与 reply 同模型也有自评偏差；M1 是 oracle 上界。上述比例和区间仅供当前样本诊断，不构成产品收益或真实平台行为结论。

## Pairing 全量扩样续跑（未完成，2026-11-11）

- 新隔离目录：`/tmp/stella-pr130-b05-pairing-qwen38-72pairs`；固定模型 `qwen3.8-flash-next-iq2_xs`、`--channel rule`、`--memuse-pairs 0`，每次进程 `--max-calls 200 --max-runtime-seconds 1800`，复用同一 fingerprint。
- 两次模型调用预算各耗尽 200 calls；checkpoint 有 212/216 条条件记录（T0 71/72、T3 71/72、T0_GUARD 70/72）。报告均为 `PARTIAL` / `PARTIAL_BUDGET`，不作为完整 72-pair 结果解读。partial JSON SHA-256 分别为 `56a21c86e2dc990dfd4c0f5830eb314749fdd791bc38654b61cc7ce36e3a2eaa` 与 `28a5af90a329aab8bda06a65f4ab13c5d13bb9d9086554162b23e851ce3bb355`，保存在同目录 `report/proactive_b05_report.partial-budget*.json`。
- 第三次 `--resume` 在模型预检时因 `URLError` 失败，未调用模型；随后对 `http://127.0.0.1:8081/v1/models` 的连接检查也失败。需恢复端点后，用相同参数加 `--resume` 完成剩余四条记录。checkpoint 与前两份 partial 报告保留。

## 未运行与限制

- 尚未覆盖的全量样本：joint 剩余 MemUse pairs 和 ChMap topic points、pairing 原计划剩余 39 pairs（扩样 checkpoint 尚缺 4 条条件记录）、M6 剩余 pairs；embedding/hybrid 通道也未运行。本次所有模型任务固定使用 `rule` retrieval。
- B05 会话用户 ID 显式传给生产 retrieval，避免 group-space 查询跨用户读取；pairing actor 输入只含 qid/question，不传 scorer gold answer。reply/judge prompt 把回忆内容和判分字段标为数据，不作为可执行指令。
- M1 是 oracle 上界，MS 是同一用户在触发 session 之前的 summary store；B06 人工盲评与 B08 平台验收未覆盖。分支 participation manager 不读取记忆内容决定是否发言，因此本轮及未来 B05 模型结果只测固定决策下的内容。
- 当前模型写侧 smoke 的活动记忆数为 0；不能据此声称 M6 retrieval 已被验证。模型截断和回退均保留在报告中，不因 runner 完成而视为行为通过。
- LoCoMo-Conv license 问题未解除；ChMap dialogue_data 的话题摘要任务不属于本包范围。

## 验证命令

- `uv run --no-project --with-requirements requirements.txt --with-requirements requirements-dev.txt --with jsonschema pytest tests/evaluation/test_proactive_b05.py tests/test_memory_eval.py -q` — 21 passed。
- `uv run --no-project --with-requirements requirements.txt --with-requirements requirements-dev.txt --with jsonschema ruff check proactive_eval/b05.py proactive_eval/b05_data.py proactive_eval/b05_prompts.py memory_eval/answer.py tests/evaluation/test_proactive_b05.py tests/test_memory_eval.py` — PASS。
- 同一 `uv` 隔离依赖执行 `pytest tests -q` — 4,399 passed、34 skipped、3 existing warnings，退出码 0。
- 原提交文档门禁：`python3 scripts/check_docs.py` — 127 files / 1,365 links / 577 anchors / 0 errors；模型结果更新后及本次 partial checkpoint 更新后均为 127 files / 1,366 links / 577 anchors / 0 errors。
- 实际离线运行：`python -m proactive_eval.b05 --workdir /tmp/stella-pr130-b05-offline-final --tasks rank,boundary --rank-channels rule,fts --max-runtime-seconds 1800` — exit 0、schema PASS、298 rank rows / 144 boundary rows、28.961 秒。
- 原有已完成 model task 报告均通过 B05 内置 `stella-proactive-b05-report/1` Draft 2020-12 schema 验证；joint、33-pair pairing pilot、M6 状态为 `COMPLETE`，错误数均为 0。新增 72-pair 扩样报告通过同一 schema，但状态为 `PARTIAL_BUDGET`；不能将它算作完成样本。
- 本轮 `git diff --check`、feature JSON parse 和文档门禁通过。GitNexus 刷新至当前提交 `949306b`；all 检查为 4 files / 7 symbols / 0 flows / LOW；compare main 为 364 files / 782 flows / CRITICAL，重复运行的 changed-symbol 计数与展示受索引上限影响。索引流程提取有截断（3,563/3,763 候选入口未入图、25 条 trace 深度封顶、1,148 个 callee 跳过、45 个 walk 达预算），未列出流程不代表无影响。本轮仅改报告和状态文档，未改运行代码。
