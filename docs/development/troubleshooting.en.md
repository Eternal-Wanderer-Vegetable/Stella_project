# Troubleshooting

[中文](troubleshooting.md) | English · [Documentation](../README.en.md)

**All runtime logs are in `logs/`** (determined by `LOG_DIR`; see [configuration reference](../reference/configuration.en.md#logs)). Troubleshooting is essentially searching this directory.

| Symptom | Check |
|---|---|
| Incorrect reply content | `logs/stella_thought_logs.md` (complete prompt / raw output / internal reasoning) |
| Plugin not loaded / capability not registered | `logs/boot_debug.log` (cleared and rewritten at every startup; reflects only the most recent startup) |
| Memory not generated | `logs/memory_consolidation_log.md` (raw output and candidate count for each consolidation batch) |
| Memory deleted incorrectly | `logs/memory_compressor_log.md` + `compressor_stats` table |
| Wrong memory selected during retrieval | `memory_traces` table (candidate / filtered / final / rejected), or `python -m memory.benchmark --verbose` |
| Abnormal proactive speech | `🎯 [proactive@]` / `🔇 no response` in the logs; `proactive_state` table |
| Link disconnected / messages not received | `[LinkMonitor]` alerts in the logs (including troubleshooting steps); NapCatQQ Desktop logs to confirm whether the account disconnected |
| Consolidation output truncated | `finish_reason=length` alert in the logs |
| @ conversations learn nothing at all | `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`; `AT_MENTION` at 0 means the persistence listener was intercepted by `block=True` (`priority` must be 0) |
| Proactive @ always uses cold start | `mode=coldstart` remains constant in the logs, or `[ProactiveTarget] failed to read candidates`; indicates that the space column name in the candidate query does not match |
| A model has severe queueing / replies are slow | Wait/hold/queue-depth alerts under `[Scheduler]` in the logs; `core.llm.snapshot()` exports cumulative statistics |
| Memory reads/writes silently do nothing | Run `python -m deploy paths` to confirm `STELLA_HOME` and the database location; then inspect migration results in the startup log and check whether `PRAGMA table_info(memories)` contains `group_shared_space` |
| GUI cannot display link status | Check `STELLA_STATUS_API_ENABLED`, and verify directly with `curl http://127.0.0.1:8080/stella/status`; if the process is running but the endpoint returns 403, the route was incorrectly exposed or restricted; if it cannot connect, uvicorn did not start |

### Common SQL

```sql
-- Candidate queue status distribution
SELECT status, COUNT(*), AVG(confidence), AVG(occurrence_count)
FROM memory_candidates GROUP BY status;

-- Candidates stuck in the observation area (repeatedly mentioned but unable to be promoted)
SELECT user_id, content, confidence, occurrence_count, source_kinds, first_seen_at
FROM memory_candidates WHERE status = 'OBSERVING' ORDER BY occurrence_count DESC;

-- Memory count per user (quota observation)
SELECT group_shared_space, user_id, COUNT(*) FROM memories
WHERE status = 'active' GROUP BY group_shared_space, user_id ORDER BY 3 DESC;

-- Memory source distribution (audit: which path produced them)
SELECT source_kind, COUNT(*) FROM memories WHERE status = 'active' GROUP BY source_kind;

-- Message source distribution
SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind;

-- Consolidation progress
SELECT * FROM consolidation_state;

-- Schema version
SELECT * FROM schema_meta;

-- Message source distribution (AT_MENTION at 0 while BOT_SELF > 0 means persistence was intercepted)
SELECT group_id, source_kind, COUNT(*) FROM group_messages
GROUP BY group_id, source_kind;

-- Candidate source composition (a single AT_MENTION source should be enough for promotion)
SELECT source_kind, source_kinds, status, COUNT(*) FROM memory_candidates
GROUP BY source_kind, source_kinds, status;

-- Verify space ownership: tables at QQ-group granularity should contain group numbers;
-- memory-granularity tables should contain space names
SELECT DISTINCT 'consolidation_state' AS t, group_id AS id FROM consolidation_state
UNION ALL SELECT DISTINCT 'memories', group_shared_space FROM memories;

-- Decision tracing: inspect the triggering group and retrieval space together
SELECT group_id, group_shared_space, mode, trigger, ts FROM memory_traces
ORDER BY ts DESC LIMIT 20;
```
