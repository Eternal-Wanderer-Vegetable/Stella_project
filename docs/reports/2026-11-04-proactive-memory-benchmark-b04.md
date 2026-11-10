# 主动参与与记忆 Benchmark B04 — 记忆双轨全链路与写侧生命周期

- 状态：**B04 完成——10/10 LoCoMo 场景 × 双摄入轨（受控/生产等价）全链路、source-lineage 与写侧生命周期机制评测；本分支基线下生产等价轨晋升门 0 晋升（828 个候选全部保持 OBSERVING、memories 表 0 行），回答正确率不构成记忆能力结论；整体 benchmark 仍 NOT READY。**
- 分支：`codex/proactive-memory-benchmark-implementation`；PR #130。
- 数据：LoCoMo 10 个 conversation（frozen adapted 快照，见运行指纹 `datasets.locomo`）；PersonaMem 200 个 adapted case（revision `ed956dea41521fc4499acbc63f966e0fd3c053ba`）。原始对话不进仓库，运行工件在 gitignored `E:/stella/runs/memory-eval/`。
- 模型：生产引擎 Strata `qwen3.8-flash-next-iq2_xs`（http://127.0.0.1:8081/v1，START-HERE 启动，生产配置）；answer/judge 请求带 `reasoning_effort="none"`（思考引擎上的确定性评测协议，记录于报告 `fingerprint_inputs.answer_model`）；MEMORY 角色（consolidation/extract）保持生产默认（思考开启）。LM Studio 1234 本轮未使用（B04 mode=rule 不需要 embedding）。
- 运行报告：gitignored `E:/stella/runs/memory-eval/b04-full-strata-20261111-r2/report/memory_eval_b04_report.json`；SHA-256 `f93a3086e6e5e4e6fe9b9c4a1fc677c3cea5aeeef8a1c2a77efa4b78727e4230`，Draft 2020-12 schema（`memory_eval/schemas/memory-eval-report-2.schema.json`）**PASS**，`status=MEASURED_IN_SCOPE`、0 errors。首轮 800 预算运行（同节记录）fail-closed 留档。

## 双轨语义

`memory_eval/b04.py` 同一 LoCoMo 场景在两条隔离轨各跑一次完整 写侧→检索→QA：

| 轨 | 摄入方式 | 整合 | 声明 |
| --- | --- | --- | --- |
| controlled（受控诊断） | `ReplayEnv` 直接插行、绕过 CaptureGate、按会话覆盖批量常数、`force=True` | 默认 oracle（合同刻板句后端，零模型调用） | `bypass_flags=[direct_group_messages_insert, capture_gate_omitted, batch_constants_overridden, force_consolidation]` |
| production（生产等价） | `ProductionReplayEnv`：真实 `AdmissionPolicy` + `CaptureGate`（真实默认 probe，逐 fixture 会话前显式续租）+ `record_message` 写路径，平台消息 ID（`dia_id`）保留为 source ID | 生产 `backend_for` 角色，不改动批量常数，`force=False` | `bypass_flags=[]`；批量阈值逐项记录 |

两轨共同点：virtual 时钟不参与（数据集时间戳保留在 transport 事件，生产 `group_messages` 用墙钟写入时间——差异记录在报告 limitations）；QA/lineage/漏斗口径一致。

## Smoke（两完整会话，机制门）

首次 smoke 用 LM Studio `qwen/qwen3.8-27b`（本机 1234）在 controlled QA 第一个 answer 请求即被服务端 HTTP 400 拒绝（EvalLLM 未捕获响应体），runner fail-closed 未产出生产轨数据——按用户指引切换到生产引擎 Strata 后重跑。Strata smoke（conv-26/conv-30 全部会话，两轨）：

- exit 报告 `MEASURED_IN_SCOPE`，0 errors；37 次预算内调用（answer 10 / judge 10 / capture_gate_probe 17），21 分钟。
- 生产等价轨真实漏斗：admission 419+369 全放行，CaptureGate ready，conv-26 45 / conv-30 68 个候选（全部 OBSERVING），evidence 73/121 行，claim links 73/121，41/76 个 source 挂有候选/证据/实体。
- PersonaMem 静态检索适配器：200/200 case ok，forbidden activation 0.0，cross-scope leak 0.0。
- 已知缺陷（已修）：当时 `BudgetedBackend` 只拦截 `generate`/`generate_detailed`，而生产 `RoleBackend` 路径经 `attempt_plan()`→`endpoint.generate_single_attempt`——MEMORY 角色的模型调用未被计量。修复后 `attempt_plan` 返回预算化 endpoint（`record_attempt_result` 先解包保持端点同一性），smoke 数字中的 MEMORY 调用计数为 0 属该缺陷，不作成本证据。

## 全量 10 场景（两轨）

### 第二轮（预算 1600，`b04-full-strata-20261111-r2`，SHA-256 `f93a3086e6e5e4e6fe9b9c4a1fc677c3cea5aeeef8a1c2a77efa4b78727e4230`，schema PASS）——主证据

**10/10 场景 × 两轨全部完成**，`status=MEASURED_IN_SCOPE`、0 errors，919/1600 次调用（consolidation 604 / extract 177 / probe 118 / answer 10 / judge 10），耗时 8,748 s。截断：consolidation 427/604（71%）、extract 175/177（99%）——与首轮同量级，确证为基线行为而非偶发。

生产等价轨漏斗（10 场景全量；候选/证据/claim 全为真实写侧产物，**全部候选停在 OBSERVING，memories 表 0 行**）：

| 场景 | 消息 | 候选 | evidence/claim 行 | 有候选/证据/实体的 source | memories 行 |
| --- | ---: | ---: | ---: | ---: | ---: |
| conv-26 | 419 | 60 | 89 | 54 | 0 |
| conv-30 | 369 | 65 | 104 | 71 | 0 |
| conv-41 | 663 | 118 | 159 | 109 | 0 |
| conv-42 | 629 | 117 | 152 | 106 | 0 |
| conv-43 | 680 | 62 | 93 | 58 | 0 |
| conv-44 | 675 | 88 | 149 | 89 | 0 |
| conv-47 | 689 | 45 | 58 | 40 | 0 |
| conv-48 | 681 | 111 | 183 | 111 | 0 |
| conv-49 | 509 | 97 | 148 | 89 | 0 |
| conv-50 | 568 | 65 | 99 | 58 | 0 |

受控轨（oracle）仅 conv-41/42/43/47/48 有刻板句候选（2/3/3/6/3），其余为 0；两轨 QA 数字一致（见下）。

### 第一轮（预算 800，`b04-full-strata-20261111`，SHA-256 `68fe16b4acfe72a9883d2744e94be60e1d2e381fb8bffb2073a17a096e39ea9d`，schema PASS）——预算耗尽留档

受控轨 10/10 完成；生产等价轨 9/10 完成，conv-50 在生产轨 ingest 阶段把 800 次模型调用预算耗尽（`BudgetExceededError`，报告 `status=NOT_READY`，错误逐字记录）。耗时 7,512 s。修正计量后的角色分布：consolidation 533 / extract 144 / capture_gate_probe 103 / answer 10 / judge 10。截断：533 次 consolidation 中 389 次（73%）、144 次 extract 中 142 次（99%）。

QA（每类别跨 10 场景抽样 1 题/轨，共 5 题/轨；两轮一致）：conv-42（1 题，acc 0）、conv-44（2 题，acc 0）、conv-47（2 题，acc 50%——adversarial 正确弃答判对，single_hop 无记忆可检索判错）；两轨数字一致。所有题 `retrieved_ids=0`、`pack_memory_count=0`——与「0 晋升 → memories 空表 → 检索为空」的漏斗一致，是空检索下的诚实下界。

PersonaMem 静态适配器：200/200 case ok，forbidden activation 0.0，cross-scope leak 0.0（与 B00 基线一致）。

## 写侧生命周期矩阵（隔离测试证据）

| 生命周期 | 机制 | 证据 |
| --- | --- | --- |
| 编辑 | 同 `platform_message_id` edit 事件写入新行，旧行 `source_state=superseded`、`source_effective=false`；挂其上的 active claim 计入 `active_claim_links_with_noncurrent_sources` | `test_production_track_uses_admission_capture_and_idempotent_transport_events` |
| 撤回 | `delete` 事件经真实 transport 写路径将 evidence 置 `source_unavailable`；lineage 中 `deleted_sources` 计数 | 同上 |
| 过期 | 超期 OBSERVING 候选被 MemoryManager `_reject_stale_candidates` 拒绝（REJECTED） | `test_expired_observing_candidate_is_rejected_by_memory_manager` |
| 幂等 | 重复 record 同一 fixture 会话产生相同 source→row 映射，不重复落行 | 同上 |
| 续跑 | `memory-eval-resume/2` 指纹含数据/模型/轨/QA 计划/code fingerprint；mismatch 拒绝 | `test_resume_fingerprint_requires_schema_match_and_exact_identity` |

`build_lineage`（`memory_eval/b04_lineage.py`）输出 source→candidate→evidence→claim 全边与 `source_effective` 状态；`retrieval_source_alignment` 用真实 source ID（LoCoMo `dia_id`）判 `gold_source_alignment`，语义支持保持 `ALIGNMENT_UNRESOLVED`（无人工裁定不改写）。这替代了 MBENCH-002 的 `gold-{dia_id}` 注入匹配，使 live 写侧的召回可用 source-ID 审计。

## 关键发现（基线事实，非产品结论）

1. **本分支基线晋升门 0 晋升**：生产等价轨全部候选停在 OBSERVING，`memories` 表 0 行，检索无记忆可返回。在复制库上显式重放 `MemoryManager.process_new_candidates()` 复现同一结果（45 OBSERVING → 45 OBSERVING）。这与 MBENCH-004 时代「live 漏斗 188 候选 0 晋升」的基线一致；本分支的 `mneme/evidence_contract.py` 仍只有 self_report/explicit_preference 两族（MEMWRT-001 的四族扩展在独立分支/PR）。benchmark 如实暴露了这一点。
2. 因此 answerable QA 正确率接近 0、abstention 类仍判对——这些数字是**空检索下的诚实下界**，不是 Stella 记忆能力结论。
3. controlled 轨的 oracle 只对合同刻板句逐字命中产生候选（conv-26/30 为 0），同样不是 gold 注入召回测量；B04 刻意不带 `--inject-gold`，避免把组件数字混入全链路轨。

## 验证命令

- `python -m pytest tests/evaluation/test_proactive_b04.py -q` — 13 passed（1 条 Python 3.14 asyncio 弃用警告）。
- `python -m pytest tests/evaluation/ -q` — 70 passed（含 B01 契约/指纹套件；`proactive_plugin_fixtures.py` 把子进程插件夹具抽成 stdlib-only 模块，修复用户级 site-packages 主机上 PYTHONNOUSERSITE=1 子进程无法 import 测试模块的问题）。
- `Draft202012Validator(memory-eval-report-2.schema.json).validate(report)` — 两轮运行报告均 PASS。
- `python -m ruff check memory_eval/ tests/evaluation/` — 通过。
- `python scripts/check_docs.py` — 127 files / 1,362 links / 577 anchors / 0 errors。
- 全量运行（两轮同参数，仅预算不同）：`python -m memory_eval.b04 --workdir <workdir> --stage all --tracks both --conversations 10 --qa-sample 1 --mode rule --llm-base-url http://127.0.0.1:8081/v1 --llm-model qwen3.8-flash-next-iq2_xs --memory-base-url http://127.0.0.1:8081 --memory-model qwen3.8-flash-next-iq2_xs --max-calls 1600 --max-runtime-seconds 21600`（第一轮 `--max-calls 800 --max-runtime-seconds 14400`）。预算进 fingerprint，故两轮为独立 workdir。

## GitNexus 影响与边界

- `EvalLLM.chat` 上游影响：UNKNOWN（0 direct）→ 源码清点确认调用方为 `memory_eval/answer.py`、`runner.py`、`b04.py`；改动为向后兼容可选参数 `reasoning_effort`。
- 提交前 detect-changes（scope=all）：`EvalLLM`/`chat` 计 **CRITICAL**（785 个受影响流程，绝大多数为跨语言同名 `chat` 符号聚合）；风险保留不豁免。新增 B04 源码尚未入索引，未把空图边当作无调用者。
- 生产 Aoede/Mneme 符号未改动；B04 只新增 `memory_eval/b04*.py`、schema、测试与报告。

## 未覆盖范围

- embedding/hybrid 检索模式 NOT RUN（B00 起的 fixture 缺口延续；本轮 mode=rule）。
- QA 计划为每类别跨场景抽样（qa-sample=1 → 每轨 5 题），非 1,986 题全量；LoCoMo 官方 token-F1 判分协议未并行实现。
- 无真实 QQ/WebChat、无生产数据/配置、无 clean VM、无发布验收；LongMemEval 是有成本预算的 P2 扩展。
- PersonaMem 分数为 Stella 静态检索适配器指标，不是原任务准确率；LoCoMo 为英文域外部参照，不是中文 persona 验收。
