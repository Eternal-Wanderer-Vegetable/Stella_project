# 多人对话身份与归属修复 — 实施报告

日期：2026-10-04。分支：`feat/multi-user-identity-repair`（自 `feat/qq-private-personal-memory` @ `038e419` 切出）。
计划：`docs/plans/2026-10-04-gitnexus-plan-multi-user-identity-repair.md`。
状态：**M0–M4 全部落地，M5 离线部分完成；T20（真模型 40 场）与真机灰度未执行**——计划整体不能标记为完成，见「未验证项」。

## 里程碑落地情况

| 里程碑 | 提交 | 内容 |
| --- | --- | --- |
| M1 | `a470ce5` | `scope_for_chat_context`：检索主体统一取 `ctx.user_id`（平台 sender / pick_target 验证目标），群号 `peer_id` 不再当人；无目标主动与旧入口保持 scope-free；主回复与 Planner 深度查询共用同一 helper；记忆归属标签（当前用户的记忆 / 其他成员的公开背景 / 群共享背景[记录=用户(x)；事实主语未确认]），归属头先拼进条目再算 token |
| M2 | `341ddfa` | ChatContext v4 消息身份信封（display name 规范化、reply/@、逻辑分组字段，投影白名单 + JSON 安全）；schema 15→16 additive（group_messages 信封列、`(group_id,msg_id)` 与 `(conversation_key,logical_message_id,part_index)` 非唯一索引、身份声明两表，`migrate_v16` 事务化幂等）；关系提取无条件执行并在入库前完成，reply 目标只在同 canonical conversation+bot 内解析（缺失/多义 = unknown）；`_record_bot_lines` keyword-only origin/receipts——只记确认气泡、保留原始 part_index、收件人≠作者；tail 按逻辑单元渲染（48 行扫描上限 + token 上限），无关系行逐字旧格式 |
| M3 | `3318921` | `memory/conversation_identity.py`：有界本人声明规则（我是X/X是我/我才是X/改名/以后叫我；引号、多自称、角色词、超长一律 ambiguous）、第三人纠正（目标必须由 @/reply 作者/BOT_SELF 气泡收件人唯一解析；肯定只落带来源证据并把同名他人声明置 conflicted，不创建 confirmed_self）；claim+revision 同事务、T15 原子性；身份 capsule 每轮重建进 prompt 稳定区；整条「我是谁」且有已验证声明时零 LLM 直复；不改称呼偏好表 |
| M4 | `d77bee2` | `fit_conversation_parts`/`ConversationPromptParts`（身份块+当前输入受保护；evidence→memories→profile 整节丢弃；history 按行边界从最旧让位；正文只裁尾部；over_protected → DIRECT 短回复不调超额 LLM）；不丢弃时与旧 `_compose_prompt` 输出逐字节一致；TurnService v2 预算路径 + 版本化 trace（含冻结 parts_input）；SessionState reset_generation/identity_revision + compact CAS（apply 与 skip 都在 await 后校验，过期结果丢弃、watermark 不动、可重试）；replay 按版本分派 v1/v2；会话上下文缓存键纳入身份 revision |

## M5 验证结果

验证命令按计划 §8 执行（本机无 pytest-timeout 插件，全量命令去掉 `--timeout` 参数，其余同 CI）：

- 批次 1（prompt/budget/tail/bot_self/compact/cache/replay/migrations/personal_scope/private/proactive/facade）：**127 passed**。
- 批次 2（四个新测试文件，T01–T19 确定性断言）：**82 passed**。
- 批次 3（runtime/capability/cometa/knowledge/observability/webui/scheduling + 12 个顶层测试文件）：修复两个自伤回归后与基线一致（唯一失败 `test_scheduling_settings_defaults` 为**基线既有**，已用基线 worktree 复核）。
- 全量 `tests/ -n auto --dist loadgroup`：见下节最终数字。
- `docker exec stella-gitnexus detect-changes --scope all`：每次提交前执行，无 partial/truncated。

实施中发现并修掉的两个自伤回归（提交 `5ada13b`）：

1. **owner 列 SELECT 破坏 v2 形状表评分**：owner 列加入主查询后，无 owner 列的 v2 形状库整体跌进 legacy 回退，`usage_tags` 丢失导致强信号候选跌破分数门槛（`test_retrieval_v2_score_floor_filters_noise` 等 4 例）。修复：PRAGMA 探测确认列存在才追加 owner 列，否则保持原 13 列查询逐字不变。
2. **cometa ack 测试断言泄漏**：exact-call 断言未按新契约放行 `origin` kwarg 而失败，跳过了 `cometa_runtime.set_current(None)` 清理，连带 webui cometa 门禁两个用例被污染。修复：断言放行 `origin=ANY`；message-flow manifest 为新增 `compact.commit` 节点重新生成。

## 未验证项（诚实清单）

- **T20 真模型 40 场采样**：需要冻结的 IQ2_XS 端点与真实采样条件，本离线环境未执行。0/40 串人与 ≥36/40 任务完成的发布门槛**未达成也未声称达成**；确定性断言（T01–T19）不能替代它。
- **Python/Rust 双后端 parity**：本机 Python 3.14 无法加载 cp310-abi3 的 `_native.pyd`，检索走 Python 后端。native 路径的 scope/owner 列行为未实测；`.pyd.api1.bak` 不作为证据。native 环境下需按计划 §12 假设 2 复验（尤其 Python 侧新增的 owner 呈现列在 native 结果 dict 中不存在——渲染按 legacy SPACE 语义降级，属预期保守行为，但需实测确认）。
- **真实群灰度/回退演练**：schema16 为 additive（回退应用保留新列表即可运行），副本 dry-run 由迁移测试覆盖（v15 夹具升级/幂等/行数守恒/FTS），但未在真实生产副本上演练；灰度发布未开始。
- **性能门槛（p95 ≤ +20ms）**：未做同 fixture 前后对比测量。新增的每轮开销：一次身份版本 PK 查询 + capsule 的一至两次小 SELECT + 关系列读取（同查询扩展列），量级可控但未量化。

## 明确不做（与计划一致）

跨群别名统一、一般性第三人实体解析、旧 memory 自动个人化 backfill、全局 ranking 重写、全部摘要 JSON 化、任意复杂中文纠错语义模型、新增正常回复 LLM 调用（身份问句直复是零 LLM 的确定性规则）。

## 后续步骤建议

1. 在有 native 环境的机器上跑 `MEMORY_BACKEND=rust` 的检索 parity 与 scope 断言（T07 的 native 半边）。
2. 用冻结的 IQ2_XS 端点执行 T20（8 场景 × 5 次），记录采样条件；不达标回改 prompt/规则，不加第二轮身份 LLM 调用。
3. 真机（NapCat 双号）复演 A/B/C 场景后，再评估小范围灰度。
