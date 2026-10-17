# EXTRACT 契约对齐（阶段2 提示词修复）实施报告

> 计划：[2026-10-17-gitnexus-plan-extract-contract-prompt.md](plans/2026-10-17-gitnexus-plan-extract-contract-prompt.md)
> 分支：feat/memory-benchmark-suite；实施提交 4a45082（阶段1）+ 本证据提交（阶段2）
> 结论：**DoD 全达**——accepted 0 → 4，promotion 0% → 100%，无新增关键错误。

## 背景与根因

qwen3.8-flash（EXTRACT 角色）阶段2 候选在 Gate1 全部 unknown、0 accepted
（20261016 live 证据：候选 4 全 unknown、promotion 0%），链路本身已证通
（手造合格契约 100% 晋升）。根因是 `EXTRACTION_PROMPT` 未教模型产出闸门
（`memory/evidence_contract.py`）能接受的契约形状：

- span 带尾巴（整句当 span，未在逗号/分句处截断）；
- 自我介绍「我叫X」被标成 PREFERENCE（statement_kind/type 错配）；
- 提示词正例 content 是改写（与 content=逐字 span 规则自相矛盾）；
- 结构示例契约用闸门不认识的 `sleep_pattern` 句型，模型照抄。

## 改动（仅提示词，闸门零改动）

`memory/extraction_prompt.py`（4a45082）：

1. 新增「契约硬规则」块（分隔线之上，`{messages}` 仍在末尾）：
   - 枚举可审核句型与 predicate_key：`profile.residence` / `profile.origin` /
     `profile.nickname` / `profile.employer` 及 `.en` 英形、`preference.general`；
   - span 截尾规则：只取刻板最小句，逗号/分句截断，句尾至多一个 。！；
   - 值段禁标点；canonical_value=纯值段；content=span 逐字；
   - 绑定：self_report ⇒ FACT + polarity=positive；explicit_preference ⇒
     PREFERENCE，polarity 随词面（喜欢/偏好=positive，不喜欢/讨厌=negative）；
   - 反例三条（真实失败形态）；
   - 显式声明：非刻板句型照常提取（不漏目标不变），契约不被 accepted；
   - 调和称呼规则：自称「我叫X」= self_report/FACT/profile.nickname；
     称呼要求（以后叫我X）维持 PREFERENCE（去重稳定），契约暂不可 accepted。
2. 修正正例 content 为逐字片段、结构示例契约改为 accepted 形状
   （`sleep_pattern`/失眠 → `profile.residence`/杭州）。
3. 模块 docstring 增补硬规则块与闸门句型的同步约束。

新增 `tests/test_extraction_prompt_contract.py` 结构守卫：句型枚举、绑定措辞、
块位置（分隔线上方 + `{messages}` 最后），防规则块被误删。
`tests/test_prompt_cache_prefix.py` 未改（结构性断言，跑通即证）。

## 验证

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 守卫+缓存 | `python -m pytest tests/test_extraction_prompt_contract.py tests/test_prompt_cache_prefix.py -q` | 14 passed |
| 回归子集 | `python -m pytest tests/ -k "prompt or consolidat or evidence_contract" -q` | 109 passed |
| lint | `ruff check memory/extraction_prompt.py tests/test_extraction_prompt_contract.py` | 清 |
| manifest | `python scripts/generate_message_flow.py` | 重生成（body_hash 漂移） |

### 真模型 live 回放（决定性验收，Strata qwen3.8-flash-next-iq2_xs @ 8081）

命令：`NO_PROXY=127.0.0.1,localhost python scripts/eval_memory_replay.py --suite memory/benchmark/_replay/daily-life --live --json docs/reports/evidence/extract-contract-20261017/replay-live-strata-postfix.json`

第一遍（报告 `replay-live-strata-postfix.json`）：候选 6 / 记忆 4；
extraction 100%、fabrication 0%、**promotion 100%**（此前 0%）、qa 100%、delta +100。

第二遍（契约盘点 `contract-assessment-live.json`，同管线独立实录）：
候选 6 中 **4 条契约 accepted（此前 0）**、0 rejected——句型全部命中教学枚举
（`profile.residence`/`preference.general`×2/`profile.nickname`，statement_kind
全部 self_report/explicit_preference）；截尾规则生效
（「我叫小艾，以后多指教」→ span/content=「我叫小艾」）；记忆晋升 4 条。
晋升以 accepted 为前置（memory_manager.py:1007 缺 accepted 拒绝晋升），
promotion 100% 与 accepted 4 互为印证。

关键错误：无（fabrication 0%；归属正确；两遍结果一致）。

## 范围与备注

- `memory/evidence_contract.py` 零改动，ASSESSMENT_VERSION 未 bump（计划 avoid 项遵守）。
- GitNexus impact：`format_extraction_prompt` 上游 CRITICAL（3 直接调用方：
  consolidator._extract_candidates / probe_consolidation 两入口 / 缓存守卫测试，
  全部透传不钉正文，与计划 §4 一致）。
- 两遍 live 候选数 6/6、accepted 4/4，真模型非确定性下修复效果稳定复现。
- 遗留（计划 §12 开放项，未在本计划范围）：称呼要求（「以后叫我X」）闸门无支持
  句型，其契约不会 accepted；扩 gate（evidence_contract 新 pattern）另立课题。
- 本机 dev bot 与回放共用 8081 Strata 端点，回放只读模型、写临时库，生产库零接触。

## 证据清单

见 [evidence/extract-contract-20261017/manifest.json](evidence/extract-contract-20261017/manifest.json)：
`replay-live-strata-postfix.json`（第一遍标准报告）、
`contract-assessment-live.json`（第二遍逐候选契约审核状态）。
