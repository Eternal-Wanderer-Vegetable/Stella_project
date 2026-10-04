# 多人群聊归属修复 —— DoD #5 真实模型验收报告

日期：2026-10-04。状态：**80 次矩阵验收通过（0/80 关键错误，80/80 任务完成，门槛 ≥72/80）**。
计划：`docs/plans/2026-10-04-gitnexus-plan-dialogue-attribution-role-repair.md` §6.5/§8、DoD #5。
分支：feat/dialogue-attribution-role-repair（M0–M5 已实施）。

## 冻结的采样条件（运行时真实值）

| 项 | 值 | 来源 |
| --- | --- | --- |
| 端点 | `http://127.0.0.1:8081/v1` | `StellaData/.env` `LLM_ENDPOINT_CHAT_BASE_URL`（生产 chat 角色） |
| 模型 | `qwen3.8-flash-next-iq2_xs`（已加载，n_ctx=16384） | 同上 `LLM_ENDPOINT_CHAT_MODEL`；与 2026-10-04 复现报告中的模型一致 |
| 温度 | 0.7 | `LLM_ROLE_CHAT_TEMPERATURE`（未调低掩盖输入问题） |
| max_tokens | 2000 | `LLM_ROLE_CHAT_MAX_TOKENS` |
| 上下文预算 | window 8192 / reserve 1000 / safety 200 | `LLM_CONTEXT_WINDOW_TOKENS` 等（评估 prompt 经生产 `fit_conversation_parts` 真实拟合） |
| seed | 未使用；`seed_support: unknown`（未请求） | LM Studio 未提供模型文件指纹，`model_file_sha256: null`——如实记录，不虚称可复现 |
| system prompt | 缺省（生产人格提示词在运行数据目录，评估未携带；已留档 `system_prompt_present: false`） | — |

离线边界：不连 QQ、不写生产库；prompt 由冻结夹具经生产 `build_v2_named_sections` + `fit_conversation_parts` 构造；历史渲染即本次修复的投影格式（V1/V2）或其逐字重构（V0）。

## 消融（原复现场景 × 3 变体 × 10 次）

输入 = 冻结复现时间线 **seq0–13**（历史止于 C 的「摸摸」；被测的错误回复 seq14–16 绝不进历史——首轮消融曾误将其纳入历史导致模型只是续写既有台词，该轮作废并以修正输入重跑）。

| 变体 | 关键归属/状态错误 | 任务完成 | 备注 |
| --- | --- | --- | --- |
| V0 旧格式重构 | 0/10 | 10/10 | 原错误（把 Bot 的条件威胁归给 A 并当事实）未在 10 次中复现——低频事件 |
| V1 投影无规则 | 0/10 | 10/10 | 明确作者/收件人已消除跨行继承歧义 |
| V2 投影+规则 | 0/10 | 10/10 | 获选：生产配置，信息最完整，无新增错误 |

结论：三变体安全性等价（该失败为低概率事件，单模型 10 采样不保证复现）；按计划以 **V2**（修复后生产配置）进入 80 次矩阵。逐条复核结论已写回 `evidence/ablation2_V{0,1,2}.json` 的 `human_review`/`review_summary`。

## 80 次矩阵（V2 × 16 场景 × 5 次）

原 T20 八类身份场景 + 新八类状态/角色场景（16 号场景 = 冻结复现本身）。夹具：`tests/fixtures/dialogue_attribution/matrix/` + `recurrence_190922.json`；每夹具带 `oracle`（任务、合格判据、六类关键错误判据）。

| # | 场景 | 关键错误 | 任务完成 |
| --- | --- | --- | --- |
| N1 | Bot/用户角色反转（冻结复现） | 0/5 | 5/5 |
| N2 | 主体/受体反转（A 帮小美修电脑） | 0/5 | 5/5 |
| N3 | 条件未来（「再熬夜就不理你」不得当事实） | 0/5 | 5/5 |
| N4 | 否定（三人皆说没看片） | 0/5 | 5/5 |
| N5 | 第三人转述（听A说爬山） | 0/5 | 5/5 |
| N6 | 多人相同事实（两人都没吃早饭） | 0/5 | 5/5 |
| N7 | 多泡预算裁剪（薰衣草单元被裁） | 0/5 | 5/5 |
| N8 | 压缩后接续（条件摘要接续） | 0/5 | 5/5 |
| T01 | A/B 切人（B 当前提问） | 0/5 | 5/5 |
| T02 | 同话题轮流无 reply | 0/5 | 5/5 |
| T03 | 第三人纠正无目标 | 0/5 | 5/5 |
| T04 | 改名立即生效（问我是谁） | 0/5 | 5/5 |
| T05 | 同名并存 | 0/5 | 5/5 |
| T06 | 长背景（A 的事实不得沾 B） | 0/5 | 5/5 |
| T07 | 多人相同动作（第三人摸摸） | 0/5 | 5/5 |
| T08 | 冲突自称（B 当前问话题） | 0/5 | 5/5 |
| **合计** | | **0/80** | **80/80（≥72 ✓）** |

复核要点（逐条结论已写回 `evidence/matrix/*.json`）：

- 全部 80 条未见六类关键错误：speaker swap / recipient carry-over / agent-patient reversal / hypothetical-as-fact / quoted-denial-as-assertion / bot-user name mixing。
- 状态语义保持良好：N3 全部回答「没有不理人，那是玩笑」；N4 全部回答「没人看过」；N8 全部保留「下雨才改期，预报晴天→去得成」的条件语义；N7 无一泄露已被预算裁剪的「薰衣草」单元。
- 正确归属普遍成立：N2 全部把修电脑归给 A；N6 全部同时点名 A 与 B；T08 全部把「雪雪」争议概括为记录且不指认当前人。
- `screening` 正则对 n04/n06/t08 的 `suspected_speaker_swap` 标记经逐条复核均为**正确 UID 归属的误报**（正则只是辅助筛选，不作判定）。
- 两处非错误备注：n05#0 存在可双解的措辞（已按「引用是 B 所说」的保真解析判合格并留 note）；t02#2 出现「Stella 回答：」自我标签前缀（风格观察，非归属错误）。

## 结论与边界

**DoD #5 判定：通过**（80 样本 0 关键错误、任务完成 80/80 ≥ 72）。消融与矩阵的完整 wire 证据（prompt、预算拟合、逐条输出、usage、复核槽位）留档于 `docs/reports/evidence/dialogue-attribution-20261004/`。

边界（如实记录）：

1. 单模型（qwen3.8-flash-next-iq2_xs @8081）、温度 0.7、无 seed、无模型文件指纹——0/80 是**该采样条件下**的样本门槛，不是所有中文群聊/参数组合的绝对保证；
2. 评估 prompt 为离线重构：无生产人格 system prompt、身份 capsule 由夹具声明构造（离线无声明表）；与真实进程仍隔一层；
3. 80 次矩阵不含多 Bot、私聊回归与长 soak；
4. **DoD #8 真实 QQ 灰度（双号/第三人复演）待上线后观测**，操作者协调执行；离线结果不替代灰度。
