# Behavior Contract（M0 冻结）

> 本文件冻结「同样输入与配置下必须逐项相同」的可观察行为。真实模型文本有随机性，不承诺逐字相同；验收一律使用固定模型响应 + 规范化事件 trace（见 baseline-report.md §4）。行号基线 `acd5aee`。
> 「怪癖」= 现有失败或怪异行为，按计划 Q1 **默认保留并记录，另开修复项**，不混入迁移。

## 1. 调用预算契约（最易回归）

| ID | 契约 | 证据 | 新运行时义务 |
| --- | --- | --- | --- |
| BC-1 | 普通回复恰好 **1 次**聊天模型调用；Core 不得自动增加总结/续写/重试/工具推理轮次 | tests/test_pipeline_compose.py:178 | ResponseClient 每轮恰好一次 generate；禁用一切批量/抢占/续写默认行为 |
| BC-2 | 前置直接回复 **0 次**生成调用：`_set_direct_reply` 写 ctx.reply/lines 后 pipeline :239 短路；Core 不得再进默认生成路径 | capability/hooks.py:267-301、pipeline.py:239 | prepare 返回 direct 时 provider 零调用 |
| BC-3 | Planner：`PLANNER_MAX_LLM_CALLS_PER_TURN=2` 硬上限（pipeline :256）；WAIT 有触发条件；`planner_wait=True` → 本轮不回复 | core/planner.py:163、tests/test_planner.py | 调用计数留在 Python prepare 内，不跨进程丢失 |
| BC-4 | 预算拒绝发生在生成前：QQ pause_all 静默不回（无提示句无回落，ai_gateway :575-580）；agent 任务 failed（agent.py:183）；其余角色按端点闸门 | usage_store.budget_blocked | IPC/队列不得绕过或重解释为可重试任务 |
| BC-5 | 超时/异常产出兜底 `<reply>......？`（pipeline 内 wait_for 包裹），与 planner_wait 早退（**无输出**）是两种不同结果 | pipeline.py run 末段 | silent / empty-result / failed 三态分离，不得统一映射为空 lines |

## 2. Prompt 与历史边界

| ID | 契约 | 证据 |
| --- | --- | --- |
| BC-6 | 最终 prompt 裁剪（`fit_prompt_to_window`，8192 窗口-1000 输出保留-200 安全余量）后才交给 provider；预算估算与实际输入是**同一份**最终 prompt | pipeline.py:266/281/303/322 |
| BC-7 | 不因 Cortico 持久会话额外拼入第二份历史：Core 事件历史不进模型上下文；sessionHead 追加不使用；人格解析（system_prompt_resolver）按配置每轮执行 | §2 计划 + A2 门槛 |
| BC-8 | V1/V2 记忆分支按 `MEMORY_V2_ENABLED`（默认 true）保持同分支同 trace 行为；知识证据 ≤4 items/600 tokens/700 chars；`_INSTRUCTION_INTENT`（proactive_at）把 message 前置 | pipeline.py:32/116 |
| BC-9 | 输出协议：`<thought>/<action>/<reply>` 解析（parse_output p=100）→ BAD_PHRASES 兜底（p=80）→ 空兜底+去半角括号+分行 ≤MAX_REPLY_LINES=5（p=60）→ thought 日志（p=40） | memory/post_processors.py |

## 3. 副作用与发送顺序（QQ）

| ID | 契约（顺序敏感，本次不顺带调整） |
| --- | --- |
| BC-10 | chat 发送序：record_spoken → note_stella_spoke("passive") → expression_learning.on_reply_sent → `_record_bot_lines`（发送前落库 BOT_SELF）→ schedule_compact → **首行** `MessageSegment.reply(message_id)` 引用 → 多行间 `asyncio.sleep(SEND_INTERVAL=0.8)` → 末行 `finish()`（抛 FinishedException） |
| BC-11 | 主动 @ 发送：at+空格、**无引用**、多行合并一句；发送前 mark_spoke/record_spoken；**发出即计数** record_at；之后起 `_check_reply_later` 回访退避 |
| BC-12 | 主动 join 发送：逐行无引用、行间 SEND_INTERVAL；记账/BOT_SELF/schedule_compact 在发送侧 |
| BC-13 | 发送失败单独记录，不自动重发（平台不承诺 exactly-once） |

## 4. 会话所有权与互斥

| ID | 契约 |
| --- | --- |
| BC-14 | 每群一把 `_group_locks` 互斥：@ 回复、主动 @、主动 join、调度 worker 执行四处共享；迁移期由 RuntimeFacade 统一，同轮回调**不得重入**该锁 |
| BC-15 | conversation key ≠ shared space：QQ key 含平台/机器人身份/group_id；WebChat 独立命名空间（group=-1, space="webchat"）；共享记忆空间只影响检索范围 |
| BC-16 | WebChat `run_turn` 模块级锁串行（同刻仅一轮）；120s 硬超时；reset 先 fence/cancel/drain 再清记录并递增 epoch，已取消旧轮不得晚到重建历史 |
| BC-17 | 调度群内互斥：群内有执行中 run 则本轮不认领；revision 乐观锁贯穿认领与发送 |

## 5. ChatContext 字段契约（跨进程只传 JSON 投影，不改名不变语义）

输入侧：`user_id, group_id, msg_id, message, source_kind, group_shared_space, trigger, intent, raw_event*, bot*, image_sources`（* 仅 Python 进程内短期 handle，重启失效，不过桥）。
pre 侧：`short_term, user_profile, memories_for_prompt, preferred_address, memory_mode, conversation_memories, behavior_constraints, memory_trace, tail_start_id, route, task_results, tool_summaries, knowledge_evidence, skill_candidates, skill_results, skill_summaries, skill_artifacts, image_captions`。
诊断：`llm_backend, llm_model, llm_elapsed, llm_call_count, context_window_tokens, prompt_budget_tokens, prompt_estimated_tokens, prompt_truncated, system_prompt_len, prompt_log`。
输出：`raw_output, thought, action, reply, lines`。门禁：`gate_path, gate_score, gate_reasons`。Planner：`planner_trigger, planner_action, planner_wait, deep_tool_calls`。
JSON 投影新增字段必须带 schema_version；`raw_event/bot` 一律不序列化。

## 6. 配置默认值冻结（迁移不得改变默认行为）

关键默认：`MEMORY_V2_ENABLED=true`、`MEMORY_BACKEND=python`（start.bat 有 wheel 时 rust）、`PROACTIVE_ENABLED=true`（AT_ENABLED=true、MAX_LINES=1、SLEEP 23:30-07:30、RUNTIME_TOGGLE=true）、`PLANNER_ENABLED=true`（MAX_CALLS=2、PROACTIVE_WAIT=false）、`COMES_ENABLED=true`、`KNOWLEDGE_ENABLED=true`、`SKILLS_ENABLED=false`（SANDBOX disabled）、`MCP_ENABLED=false`、`SCHEDULING_ENABLED=false`、`WEBUI_ENABLED=true`、`ROUTER_GATE_MEMORY=false`、`LLM_DAILY_TOKEN_BUDGET=0`、`BUDGET_EXHAUSTED_ACTION=pause_memory`、`SEND_INTERVAL=0.8`、`MAX_REPLY_LINES=5`、`LLM_CONTEXT_WINDOW_TOKENS=8192`。
新增键仅允许加法：`STELLA_RUNTIME=legacy|native`（v2 修订：原 `cortico` 取值更名 `native`=自有 facade 运行时；过渡期默认 legacy）+ runtime 诊断键。`.env.example` 披露被 test_env_schema/test_deploy_init 钉底，新增键须同步。

## 7. 既有怪癖（Q1：保留、记录、另修）

| ID | 怪癖 | 位置 |
| --- | --- | --- |
| Q-1 | nonebot shutdown 钩子实际按注册**逆序**执行；bot.py:180-183 注释声称顺序执行——与实现不符。迁移保序以实测为准 | bot.py |
| Q-2 | chat SSE 仅 RuntimeError/TimeoutError 产生 error 帧，其余异常流中断无帧 | webui/routers/chat.py:110-139 |
| Q-3 | run_turn 返回无 `ts` 字段，docstring 称有 | webui/chat_ingress.py:65 |
| Q-4 | openapi yaml 落后实现约 60 端点；restart 模式缺 `"self"`；plugins_mg 注释引用不存在的 `/api/v1/files` | openspec/openapi-v1.yaml 等 |
| Q-5 | WebUI 登录限流三桶（login/setup/desktop-session）共享同一容量 | webui/auth.py:30-61 |
| Q-6 | `build_user_context` 已从独立钩子移入 capability gather；「恢复旧注册」的实现会导致记忆检索跑两遍 | capability/hooks.py |
| Q-7 | skills/sandbox 配置 import 期 fail-fast（`validate_skills_config`），校验时序是行为的一部分 | config/settings.py:1629-1707 |

## 8. runtime 状态机（新增，全阶段遵守）

轮次：`accepted → preparing → generating|direct|silent → finalizing → completed|failed|cancelled`；投递另记 `delivered|unknown`，generated ≠ delivered。
崩溃恢复：只自动恢复可证明无副作用且 deadline/上下文仍有效的工作；发送结果未知/工具已执行未确认/Event handle 失效 → 待判定，禁止自动重放。
回退：不在超时后把同事件交给旧引擎重跑；回退经 drain/fence/epoch 在后续安全接入点切换。
