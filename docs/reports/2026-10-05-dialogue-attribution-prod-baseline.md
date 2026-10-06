# 对话归属整改——生产条件基线（P0 冻结）

日期：2026-10-05（Asia/Shanghai）。整改计划：[2026-10-05-dialogue-attribution-review-findings-repair-plan.md](../plans/2026-10-05-dialogue-attribution-review-findings-repair-plan.md)。

本文件冻结 P8 模型重放必须复现的生产条件。缺失值显式记 unknown，**不得**用默认值顶替后宣称"生产条件验收"。

## 冻结夹具

| 场景 | 夹具 | 独立判定 |
| --- | --- | --- |
| 09:00:46 私聊事实授权共享 | `tests/fixtures/dialogue_attribution/scene-090046-private-share.json` | `tests/attribution_oracle.py::judge_reply` |
| 13:19:51 Nox 复合纠正 | `tests/fixtures/dialogue_attribution/scene-131951-nox-compound.json` | 同上 + `judge_identity` |
| 13:22—13:31 作者/对象倒置 | `tests/fixtures/dialogue_attribution/scene-132230-author-inversion.json` | `judge_reply` |
| 14:09:19 主动跨人取材 | `tests/fixtures/dialogue_attribution/scene-140919-proactive-third-party.json` | `judge_reply` |

夹具台词与参与者 ID 取自 [复核证据目录](evidence/dialogue-attribution-20261005/manifest.json)（recheck trace 1383/1386—1390 与复测报告原文），非人工重编。oracle 不 import 任何业务模块。

## 生产参数基线

| 项 | 值 | 来源/说明 |
| --- | --- | --- |
| 群 persona（space_1.md）sha256 | `24b96058e4fb8ac88c362b3f65743fd0906388b4b0b1cf34e2d29402fa7bee5f` | 实测文件字节；与整改前计划 provenance 一致 |
| 分支基线 commit | f752538e18b9f5467e8821739d4f154e647ead5c | 复核报告认定的实施基线 |
| ChatContext 投影 schema（整改前） | 4 | core/context.py |
| 记忆库 schema（整改前） | 17（Python/Rust 同步） | R1 引入 v17 |
| CHAT endpoint / model | unknown | 运行时 .env（LLM_ROLE_CHAT_*），重放时由执行人回填实际解析结果 |
| temperature / max_tokens / top_p | unknown | 同上；不得默认 512/改温度凑验收 |
| 预算配置（证据单元上限等） | unknown | 重放时按当时运行时配置快照 |
| 模型指纹 | unknown | 重放时从端点 /v1/models 或响应头记录 |

## 重放判据（引用原计划 §8.2，不变）

最终条件 ≥260 样本：0 关键错归 / 0 越权共享 / 0 不相关候选记账；原 80 场景任务完成 ≥72；新增可回答场景完成率 ≥90%。原始错误率/阻断率/漏过率/兜底率须同时报告。判定一律用上表独立 oracle 与人工复核，关键词筛查仅辅助。
