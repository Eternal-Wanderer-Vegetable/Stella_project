# 主动参与与记忆 Benchmark B05 — MemUse / ChMap 实现与离线门

- 状态：**B05 runner 与离线 rank/boundary 检查完成；joint、pairing、M6 模型任务未运行。整体 benchmark 继续 NOT READY。** 本报告中的 `MEASURED_IN_SCOPE` 仅指本轮明确请求的 `rank,boundary` 两项。
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

## 未运行与限制

- `joint` 的 MemUse/ChMap自然回复、`pairing` 的 T0/T3/T0+sufficiency guard、`m6` 的真实写侧 smoke 均 **NOT RUN**。CLI 要求显式模型 endpoint 和 model ID；当前没有本轮获准使用的配置，未从 B04 历史配置推定 endpoint，也未发起模型请求。需要运行时，reply/judge 的 `/models` ID 校验先于模型调用；M6 还要求显式 memory endpoint/model。
- B05 会话用户 ID 显式传给生产 retrieval，避免 group-space 查询跨用户读取；pairing actor 输入只含 qid/question，不传 scorer gold answer。reply/judge prompt 把回忆内容和判分字段标为数据，不作为可执行指令。
- M1 是 oracle 上界，MS 是同一用户在触发 session 之前的 summary store；B06 人工盲评与 B08 平台验收未覆盖。分支 participation manager 不读取记忆内容决定是否发言，因此本轮及未来 B05 模型结果只测固定决策下的内容。
- LoCoMo-Conv license 问题未解除；ChMap dialogue_data 的话题摘要任务不属于本包范围。

## 验证命令

- `uv run --no-project --with-requirements requirements.txt --with-requirements requirements-dev.txt --with jsonschema pytest tests/evaluation/test_proactive_b05.py tests/test_memory_eval.py -q` — 21 passed。
- `uv run --no-project --with-requirements requirements.txt --with-requirements requirements-dev.txt --with jsonschema ruff check proactive_eval/b05.py proactive_eval/b05_data.py proactive_eval/b05_prompts.py memory_eval/answer.py tests/evaluation/test_proactive_b05.py tests/test_memory_eval.py` — PASS。
- 同一 `uv` 隔离依赖执行 `pytest tests -q` — 4,399 passed、34 skipped、3 existing warnings，退出码 0。
- `python3 scripts/check_docs.py` — 文档与使用说明收尾后复跑，127 files / 1,365 links / 577 anchors / 0 errors。
- 实际离线运行：`python -m proactive_eval.b05 --workdir /tmp/stella-pr130-b05-offline-final --tasks rank,boundary --rank-channels rule,fts --max-runtime-seconds 1800` — exit 0、schema PASS、298 rank rows / 144 boundary rows、28.961 秒。
