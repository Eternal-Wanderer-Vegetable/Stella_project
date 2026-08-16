# 多群支持方案

## M0 — 落地 B2-2（两阶段提取 + 三层锁）

已完全指定，语义已确认：阶段2 返回 `[]` 则覆盖阶段1 候选。清单见前述六项改动，只改 `memory/consolidator.py`。

这是**多群改造的前置**：它建立的「群级锁 + 每模型一把全局锁」结构正是多群并发的地基。

验收：整合日志出现「阶段2 提取」段落，且失眠/馒头这类信息能进 `memory_candidates`。

## M1 — `core/llm/scheduler.py`：把锁显式化

现状是两把裸 `asyncio.Lock` 散在 `core/llm/__init__.py`，多群下无法判断延迟来自哪里。封装成资源队列：

- 每个模型资源一把锁（`chat` = 27B，`consolidation` = E4B），严格 FIFO（`asyncio.Lock` 原生保证）
- 提供 `async with acquire("chat", tag="reply:群号")`，记录队列深度、等待时长、持有时长
- 队列深度超阈值时告警（多群下这是唯一能发现「27B 过载」的手段）
- **把 embedding 路径纳管**：`MEMORY_EMBEDDING_ENABLED` 打开后 `/v1/embeddings` 也打 27B 实例，现在完全不持锁，会绕过闸门
- 优先级机制写好但**默认关闭**（`LLM_SCHEDULER_PRIORITY_ENABLED=false`），等你实际部署多群观测到延迟再开

兼容性：保留 `chat_llm_lock` / `consolidation_llm_lock` 名字作为 scheduler 的薄封装，现有调用点不用一次性全改。

## M2 — Schema v7：`user_profiles` 分群

这是隔离正确性的地基，**必须在人格分群之前**。

- 新表主键 `(group_id, user_id)`，迁移现有行到主群（`ALLOWED_GROUPS` 里最小群号，或新增 `PRIMARY_GROUP_ID` 显式指定），其他群从零积累
- 改 `consolidator._write_user_profiles`（加 `group_id` 参数）与所有读取点
- 迁移必须幂等、可重跑（沿用 `ensure_v2_schema` 的风格）
- 顺带核实 `compressor` 的压缩路径是否也需要分群（我还没读这个文件，M2 开始前读）

## M3 — `GroupConfig` 分层配置

三层优先级：代码默认 → 全局 `.env` → `groups/<group_id>.toml`。

`get_group_config(group_id)` 返回不可变对象，带缓存。**分群白名单**（你已认可）：

- 分群：全部 `PROACTIVE_*`、人格路径、`MAX_REPLY_LINES`、`RECENT_TAIL_*`、`SESSION_*`、`MEMORY_LIMIT_*`、`MEMORY_USER_QUOTA`、`CONSOLIDATION_LOCAL_BATCH_SIZE`
- 全局：所有 LLM 后端配置、`DB_PATH`、清理策略、看门狗、`ALLOWED_GROUPS`

迁移是渐进的：模块级常量保留为全局默认（老代码不报错），首批只迁 `proactive_*`（收益最大、边界最清晰）。这一步会碰很多文件，但每个文件的改动都是机械的（`from config import X` → `cfg = get_group_config(gid); cfg.X`）。

## M4 — 人格分群

`memory/personas/<group_id>.md`，缺失回落 `memory/SYSTEM.md`。本质是 M3 的一个特例，不需要单独机制。

**前置依赖 M2**：人格分群但画像不分群，会出现「群A 的形象说出群B 学到的东西」。

## M5 — 定时任务多群化

- `proactive_check_job` / `consolidation_drain_job` / `session_idle_job` 遍历 `ALLOWED_GROUPS`
- **按群号哈希错峰**：否则每 120 秒所有群同时唤醒挤同一条队列，形成周期性尖峰
- `process_new_candidates` 收敛为按群处理，避免晋升时机跨群耦合
- 日志带群号（整合日志已有），`THOUGHT_LOG_PATH` 补上

## M6 — 文档

D-4 欠账一并结清：`configuration.md`（会话压缩/整合调度/排除名单/两阶段提取/群级配置）、`architecture.md`（两阶段整合、三层锁、群隔离边界）、`development.md`（排查表）、check_point#2 后两段。

---

## 顺序依赖

```
M0 ──→ M1 ──→ M2 ──→ M3 ──→ M4
                       └──→ M5
                              └──→ M6
```

M0 必须先做（它在修正在漏信息的缺陷）。M2 必须早于 M4。M1 可与 M2 并行，但先做 M1 能让后面所有阶段都有可观测性。