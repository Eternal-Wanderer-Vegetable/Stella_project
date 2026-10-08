# Scheduling: Group Cron Reminders and Bounded Agents

[中文](scheduling.md) | English

Group members can schedule a reminder, or administrators can schedule an agent
that generates bounded content from recent group context.

The subsystem is **disabled by default** (`SCHEDULING_ENABLED=false`). Enabling
it explicitly permits scheduled group messages. Tasks live in the independent
SQLite database `<STELLA_HOME>/scheduling/tasks.db`.

## Group commands

Mention the bot when using these commands. The command words remain Chinese:

```text
定时帮助                              # help
定时添加 <cron> <timezone> <text>      # member reminder
定时智能 <cron> <timezone> <goal>      # administrator agent
定时列表                              # tasks in this group
定时详情 <task-id-prefix>
定时编辑 <id> cron=… tz=… text=… notify=always|on_content [rev=N]
定时暂停 <id>                         # pause
定时启用 <id>                         # resume
定时取消 <id>                         # cancel
定时立即 <id>                         # new run now
定时历史 <id>                         # recent runs
定时允许 <id> <tool-name>              # allow MCP tool (administrator)
定时禁止 <id> <tool-name>              # remove tool permission
```

IDs are UUIDs; a unique prefix within the current group is sufficient. Ambiguous
prefixes require more characters.

## Permissions and quotas

| Operation | Member | Group owner/admin | Global admin |
| --- | --- | --- | --- |
| Create a reminder | Yes | Yes | Yes |
| Create an agent | No | Yes | Yes |
| Edit/pause/resume/cancel/run own reminder | Yes | Yes | Yes |
| Manage another user's task | No | Yes | Yes |
| Change tools or catch-up policy | No | Yes | Yes |

`SCHEDULING_GLOBAL_ADMINS` contains global administrator QQ IDs. Task resolution
is limited to the operator's group: another group's ID appears absent. Controlled
changes are audited with operator, group, task, and action.

Default quotas are eight tasks per group, three tasks per user per group, and
40 runs per group per day. A run exceeding its quota is recorded as
`skipped` with reason `quota_exceeded`.

## Cron dialect

Cron has five fields: minute, hour, day, month, weekday.

```text
0 9 * * MON-FRI        # weekdays at 09:00
*/15 * * * *           # every 15 minutes
0 9-17/2 * * MON-FRI   # weekdays at 09, 11, 13, 15, 17
30 8 1,15 JAN,JUL *    # January/July 1st and 15th, 08:30
0 9 13 * FRI           # Friday the 13th at 09:00
```

Wildcards, values, ranges, steps, and lists are supported. Months accept
`JAN`–`DEC`; weekdays accept **names only**, `MON`–`SUN`. Numeric weekdays are
rejected to avoid incompatible numbering conventions.

Day-of-month and weekday use **intersection** when both are specified. Thus
Friday the 13th means both conditions must hold, unlike Linux crontab's union.
Timezone is required: use an IANA name such as `Asia/Shanghai`, or a fixed offset
such as `UTC+8` or `GMT-05:30`. Fixed offsets do not track daylight saving.

Nonexistent spring-forward wall times are skipped without delayed delivery.
Repeated fall-back wall times use the first occurrence. A daily New York 02:30
task therefore skips the spring-transition date; a task also including 03:00
still runs at 03:00.

## Execution

Tasks and history survive restart. Missed reminders default to catch-up `all`,
draining across ticks when the per-tick cap is reached; agents default to
`latest`. Edits, pauses, and cancellation form a fence: revision and status are
rechecked before generation and before sending, invalidating stale runs.

One scheduling run executes at a time within a group and shares the group lock
with mention replies and proactive chat. Enablement, administrator mute, sleep,
wake-up buffer, and group cooldown gates apply. Only the heuristic requiring
enough new messages is exempted. Failed group-state reads stop execution.

Agent runs receive bounded read-only recent context without interactive pipeline
context hooks. Defaults limit them to four model rounds, eight tool calls,
300 seconds, and 1,200 output characters. Only individually approved MCP tools
are reachable; optional schema fingerprints reject drift. AstrBot tools,
arbitrary plugin/skill execution, dynamic discovery, and `@all` are excluded.
The result is sent through the QQ group delivery boundary.

## Delivery states

| State | Meaning |
| --- | --- |
| `sent` | Platform receipt obtained |
| `silent` | Completed without sendable content under `notify=on_content` |
| `failed` | Generation/provider/budget failure |
| `skipped` | Gate, quota, or policy prevented execution |
| `cancelled` | Task revision or state invalidated the run |
| `delivery_unknown` | Sending may have happened; receipt is unknown |

A crash after starting a QQ send but before persisting its receipt, or a send
timeout/exception, produces `delivery_unknown`. It is **never automatically
resent**. Inspect the group and use `定时立即` if appropriate; this creates a new
run while preserving the old history. A deterministic content fingerprint helps
compare results. Exactly-once delivery is not promised.

## Deployment and recovery

Use one active worker per database. The worker lease TTL is controlled by
`SCHEDULING_WORKER_LEASE_TTL`; multiple processes sharing one database are outside
the supported deployment model. Expired execution leases return runs to the
queue; interrupted `sending` runs become `delivery_unknown`. Migration failure
disables the worker while leaving other Stella features available. Invalid
settings are rejected during configuration loading.

## Configuration

See [configuration](configuration.en.md) and `.env.example`. The settings are
`SCHEDULING_ENABLED`, `SCHEDULING_DB_PATH`, `SCHEDULING_WORKER_LEASE_TTL`,
`SCHEDULING_TICK_INTERVAL`, `SCHEDULING_DAILY_GROUP_RUN_CAP`,
`SCHEDULING_MAX_TASKS_PER_GROUP`, `SCHEDULING_MAX_TASKS_PER_USER`,
`SCHEDULING_RUN_TIMEOUT_SECONDS`, `SCHEDULING_MAX_MODEL_ROUNDS`,
`SCHEDULING_MAX_TOOL_CALLS`, `SCHEDULING_OUTPUT_MAX_CHARS`,
`SCHEDULING_CONTEXT_MAX_CHARS`, `SCHEDULING_SEND_TIMEOUT`, and
`SCHEDULING_GLOBAL_ADMINS`.

## Scope and WebUI

Private-chat tasks, cross-group targets, multiprocess database sharing, arbitrary
plugin/skill execution, and `@all` fan-out are outside this version's scope.

WebUI → Scheduled Tasks (`/#/cron`) provides listing, creation, editing, run-now,
history, and audit through `/api/v1/scheduling/tasks` in
`webui/routers/manage.py` and `webui/services/sched.py`. WebUI and group commands
share `scheduling/store.py`, validation, and quotas. Panel access uses the
existing administrator login.
