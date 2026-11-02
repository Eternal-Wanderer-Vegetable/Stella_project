# P1 证据合同扩展生产化：验收句型族扩容与误晋升审计（MBENCH-005b / MEMWRT-001）

- 日期：2026-11-03
- 分支：`codex/evidence-contract-expansion`（独立 PR，base main；承载 MBENCH-004 计划的「证据合同扩展」）
- 前置：MBENCH-004 P1 离线对照（docs/reports/2026-11-02-mbench004-p1-evidence-contract.md，202 样本标注集 `memory_eval/annotation/locomo-contract-gold.jsonl`）
- 状态：**隔离评测达标；提取模型行为变化（需 live 重跑）标注 NOT READY**

## 变更内容

`memory/evidence_contract.py` 验收句型族扩容（精确镜像离线对照验证过的 A1+A2，不额外发挥）：

| statement_kind（新增） | 谓词族 | 候选 type | 极性 |
| --- | --- | --- | --- |
| identity_state | identity.state / identity.have（+ .en 变体） | FACT | positive only |
| plan_intent | plan.intend / want / will / doing（+ en going-to/want-to 变体） | **PLAN**（自动获得 14 天观察 TTL——计划时效管理） | positive only |
| ability_habit | ability.can（+ en can/play 变体） | FACT | positive only |
| past_event | past.used_to（+ en used-to/went-to/had 变体） | FACT | positive only |

既有 self_report（7 谓词）与 explicit_preference 不动。kind↔type 绑定改为表驱动（`_KIND_TYPE_BINDINGS`，原 reason 命名保持兼容）。

A2 值段过滤器进 `assess_candidate` 语义段（全部 kind 生效），新增拒绝 reason：
- `value_second_person`：值段含「你/您/you」——杜绝「我喜欢你画画」式夸赞被记成说话者偏好（标注集难点样本的修复）
- `value_placeholder`：值段含占位符 X（抽取模板残留形态）
- `value_too_short`：值段 <2 字符（碎片句）

`memory/extraction_prompt.py` 契约硬规则块同步扩枚举（新族逐字规则 + 「第一人称陈述取逐字原文」指引 + 「我喜欢你的画」新反例）。

## 验收数字（202 样本标注集，shipped=生产语义直调）

| 配置 | 验收数 | MUST 召回（143） | MUST_NOT 误收（19） | MAY 验收（40） | 精度代理 |
| --- | --- | --- | --- | --- | --- |
| A0 扩容前生产 | 4 | 3（2.1%） | 1 | 0 | 75.0% |
| **shipped（本 PR 生产语义）** | 35 | **30（21.0%）** | **1** | 4 | **97.1%** |

- MUST 召回 **10 倍提升**（2.1%→21.0%）且 MUST_NOT 误收维持 1（= 扩容前基线水平）；
  精度代理 75.0%→97.1%。
- 误晋升审计：MUST_NOT 19 条禁捕样本中 18 条未验收、1 条为扩容前既有的误收（非本次引入）；
  且 **accepted ≠ promoted**——晋升仍需通过 Gate 1（置信度/复现次数）与配额，P4 生命周期
  安全回归（32 测试）在合并前须保持全绿。

## 明确不做（与离线研究结论一致）

- ASSESSMENT_VERSION 不 bump：避免 Rust 常量级联（promotion.rs 镜像）+ .pyd 重编译；
  家族归因经 predicate_key（claim_key 哈希含谓词，provenance 可按族审计）；
  版本级归因随「结构化候选 + span 绑定」重设计落地。
- 主体归一化（三人称主语归一为第一人称）不做：需可靠的名字解析，标注集 32 例三人称
  漏检留待结构化重设计；提取提示词已教模型优先取第一人称逐字原文以缓解。
- 提取模型行为变化（新提示词让模型输出新族候选）**NOT READY**：需 live 整合重跑验证，
  本 PR 只保证「模型输出新族候选时服务端能正确验收」。

## 测试与门禁

- tests/test_memory_evidence_contract.py：新族正例（identity/plan/ability/past accepted）
  + A2 反例（value_second_person / value_placeholder / value_too_short 逐 reason 断言）
- tests/test_extraction_prompt_contract.py：谓词枚举扩至 25 个（superset 钉死）+ 新 kind
  绑定措辞断言
- 硬门禁回归：cross_user_isolation / personal_memory_sharing / private_chat_ingress /
  memory_rust_promotion / memory_cas_contract / candidate_reinforcement 全绿（Rust 无需改动：
  语义合同为 Python 独有实现，版本常量未动）
- 数据文件：`memory_eval/annotation/locomo-contract-gold.jsonl`（202 样本标注，
  文本不入库 sha1 锚定）与 `memory_eval/contract_study.py`（A0–A3+shipped 对照器）随 PR #127 已入库