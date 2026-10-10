# 排查问题

中文 | [English](troubleshooting.en.md) · [文档总览](../README.md)

**所有运行期日志都在 `logs/`**（由 `LOG_DIR` 决定，见[配置参考](../reference/configuration.md#日志)）。排查基本上就是在这个目录里翻。

| 现象 | 查看 |
|---|---|
| 回复内容不对 | `logs/stella_thought_logs.md`（完整 prompt / 原始输出 / 内部思考） |
| 插件没加载 / 能力没注册 | `logs/boot_debug.log`（每次启动清空重写，只反映最近一次启动） |
| 记忆没生成 | `logs/memory_consolidation_log.md`（每批整合的原始输出与候选数） |
| 记忆被误删 | `logs/memory_compressor_log.md` + `compressor_stats` 表 |
| 检索选错记忆 | `memory_traces` 表（候选 / 过滤 / 最终 / 拒绝），或 `python -m memory.benchmark --verbose` |
| 主动发言异常 | 日志里的 `🎯 [主动@]` / `🔇 未回应`；`proactive_state` 表 |
| 链路掉线 / 收不到消息 | 日志里的 `[LinkMonitor]` 告警（含排查步骤）；NapCatQQ Desktop 日志确认账号是否掉线 |
| 整合输出被截断 | 日志里的 `finish_reason=length` 告警 |
| @ 对话完全学不到东西 | `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`；`AT_MENTION` 为 0 说明落库监听器被 `block=True` 拦截（priority 必须为 0） |
| 某个模型排队严重 / 回复变慢 | 日志里 `[Scheduler]` 的等待/持有/队列深度告警；`core.llm.snapshot()` 导出累计统计 |
| 记忆读写静默无效 | 先运行 `python -m deploy paths` 确认 `STELLA_HOME` 与数据库位置；再检查启动日志中的迁移结果，以及 `PRAGMA table_info(memories)` 是否包含 `group_shared_space` |
| GUI 显示不出链路状态 | 检查 `STELLA_STATUS_API_ENABLED`，用 `curl http://127.0.0.1:8080/stella/status` 直接验证；进程在但接口 403 说明路由被误暴露限制、连不上说明 uvicorn 未起来 |

### 常用 SQL

```sql
-- 候选队列状态分布
SELECT status, COUNT(*), AVG(confidence), AVG(occurrence_count)
FROM memory_candidates GROUP BY status;

-- 卡在观察区的候选（被反复提及却晋升不了的）
SELECT user_id, content, confidence, occurrence_count, source_kinds, first_seen_at
FROM memory_candidates WHERE status = 'OBSERVING' ORDER BY occurrence_count DESC;

-- 每用户记忆数（配额观察）
SELECT group_shared_space, user_id, COUNT(*) FROM memories
WHERE status = 'active' GROUP BY group_shared_space, user_id ORDER BY 3 DESC;

-- 记忆的来源分布（审计：哪条路径产生的）
SELECT source_kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY source_kind;

-- 消息来源分布
SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;

-- 整合进度
SELECT * FROM consolidation_state;

-- Schema 版本
SELECT * FROM schema_meta;

-- 消息来源分布（AT_MENTION 为 0 而 BOT_SELF > 0 说明落库被拦截）
SELECT group_id, source_kind, COUNT(*) FROM group_messages
GROUP BY group_id, source_kind;

-- 候选的来源构成（AT_MENTION 来源应单次即可晋升）
SELECT source_kind, source_kinds, status, COUNT(*) FROM memory_candidates
GROUP BY source_kind, source_kinds, status;

-- 空间归属核对：QQ 群维度的表应是群号，记忆维度的表应是空间名
SELECT DISTINCT 'consolidation_state' AS t, group_id AS id FROM consolidation_state
UNION ALL SELECT DISTINCT 'memories', group_shared_space FROM memories;

-- 决策追踪：同时看触发群与检索空间
SELECT group_id, group_shared_space, mode, trigger, ts FROM memory_traces
ORDER BY ts DESC LIMIT 20;
```
