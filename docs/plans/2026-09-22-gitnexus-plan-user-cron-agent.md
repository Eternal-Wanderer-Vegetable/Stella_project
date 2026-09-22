# GitNexus Engineering Plan

> Task: 为 Stella 增加用户可管理的 Cron / 主动 Agent（仅覆盖报告第 4 项）。
> Evidence verified at commit `0dafa5fe293288f26bb55bae9f279407dd7c5a5f`; GitNexus index refreshed in Docker at `2026-09-22T01:33:52Z` with runner 1.6.11 using `analyze --index-only --pdg`. The refreshed index is current and complete for its configured limits (51,137 nodes, 121,555 edges, 696 flows); dynamic-dispatch and cross-language gaps remain explicitly marked by GitNexus.
> Evidence provenance schema 2; global dirty digest and cited-path manifest are embedded in §11; the exact generated plan path is excluded from that digest.

## 1. Objective

[verified] Implement a durable, user-manageable scheduling surface for group-scoped reminders and bounded proactive Agents: create/list/show/edit/pause/resume/cancel/run-now/history; evaluate a documented APScheduler-compatible Cron dialect; build a bounded context; optionally run an explicit MCP tool allowlist; deliver through the existing QQ bot with auditable run status. The first release is deliberately group-only, uses the real bound QQ group as the target, and keeps private-chat and unrestricted AstrBot/plugin/skill execution deferred.

[verified] A task must survive process restart, enforce owner/admin permissions, serialize per-group execution, bound model/tool/time budget, and distinguish sent, silent, failed, skipped, cancelled, and delivery-unknown outcomes. Exactly-once QQ delivery is not claimed because a process can die after the platform call and before receipt persistence.

## 2. Current Behaviour

[verified] `stella_project/plugins/bot_main/ai_gateway.py:_proactive_speak_for_group` (line 1629) performs an in-memory proactive cycle. It acquires the group lock, checks `can_speak`, starts a proactive run, creates a normal `ChatContext`, invokes the normal `Pipeline`, and records proactive state around sending. `memory/proactive_gate.py:can_speak` (line 182) gates master switch, group toggle, mute/sleep/wake, cooldown, and the “enough new messages” condition.

[verified] `core/pipeline.py:Pipeline.run` (line 220) executes registered pre-hooks, planner/knowledge/skill routing, context fitting, model acquisition, and a fallback reply on errors. The global `build_context` pre-hook (`memory/pre_processors.py:build_context`, line 111) initializes session state and includes recent conversation material, so reusing this pipeline for scheduled work would run interactive hooks and hidden side effects.

[verified] The compatibility agent (`astrbot_compat/llm/agent.py:run_tool_loop`, line 217) runs global call-event hooks, model rounds and tools; `capability/comes/executor.py:execute` (line 310) requires a live event and resolves the broad provider registry. `capability/hooks.py:_run_comes` (line 171) dispatches event-bound capability tasks through `execute_all`; these are not a safe background boundary as-is.

[verified] `core/llm/usage_store.py:budget_blocked` (line 360) is a read-only budget check, not a per-run reservation. `core/llm/scheduler.py:acquire` (line 128) provides an async gate but does not provide durable task state or delivery semantics. `core/tasks.py:Task` (line 76) is an in-process task model with non-persistent IDs.

## 3. Relevant Architecture

[verified] Runtime configuration is rooted at `STELLA_HOME`/`INSTANCE_ID` (`config/settings.py`); migrations already use SQLite schema-version patterns in memory/knowledge stores. `pyproject.toml` provides `nonebot_plugin_apscheduler` and the CI workflow runs Ruff plus pytest on Python 3.10–3.12.

[verified] The QQ-facing gateway owns group locks, admin checks, command-priority guards, pending work shutdown, and bot delivery. The new scheduler should register one lifecycle service beside that gateway, inject the existing group lock and bot adapter at the boundary, and leave ordinary reply/proactive pipeline behaviour unchanged.

[verified] MCP tools expose provider-backed `FunctionTool` objects (`capability/providers/mcp/tool.py`) and provider liveness/resolve checks (`capability/providers/registry.py`). The background path must use those checks plus a task-owned allowlist; provider metadata alone is not authorization.

[verified] The refreshed graph confirms `astrbot_compat/llm/tool.py:FunctionTool.is_background_task` exists as a dataclass property but has no resolved callers, so it is metadata rather than an authorization boundary. `core/llm/scheduler.py:PRIORITY_BACKGROUND` exists, but `acquire` documents priority ordering as disabled/FIFO; the plan must not promise background preemption or fairness from either symbol.

[inferred] A separate SQLite database under `STELLA_HOME` is the smallest durable boundary: it avoids memory cleanup and conversation-schema migrations while allowing unique occurrence keys, leases, quotas, and run history to be transactional.

## 4. GitNexus Findings

[graph] After the Docker refresh, `query({search_query:"proactive scheduled task Cron background Agent delivery", task_context:"Revalidate the user managed Cron/proactive Agent plan after index refresh", repo:"/repo", limit:6})` returned the proactive gateway flows plus existing scheduler/provider definitions and `tests/test_scheduler_concurrency.py`; it also surfaced the new plan document as a definition because the plan is now indexed.

[graph] `context({name:"can_speak", file_path:"memory/proactive_gate.py"})` is exact at lines 182-220 with direct calls `_proactive_at_user` and `_proactive_speak_for_group`. `impact({target:"can_speak", direction:"upstream", maxDepth:3})` remains HIGH: direct=2, depth counts 2/2/1, and the affected path reaches `_runner`, `proactive_speak_job`, and `_spawn_participation_speak`. Preserve the existing contract and add a separately validated scheduled profile.

[graph] `context({name:"run", file_path:"core/pipeline.py"})` resolves `Pipeline.run` exactly at lines 196-350. `impact({target:"run", file_path:"core/pipeline.py", direction:"upstream", maxDepth:3})` is HIGH with direct callers `handle_chat`, `_proactive_at_user`, and `_proactive_speak_for_group`, depth counts 3/2/1, and one receiver-typing call site dropped. The scheduled executor must not alter this shared method.

[graph] `impact({target:"run_tool_loop", direction:"upstream", maxDepth:3})` remains HIGH: direct=4 (`run_provider_request`, `_agent_call`, `probe_tools`, `Context.tool_loop_agent`), depth-2 `pipeline._emit`/`execute`, and depth-3 `_invoke`/`execute_all`. Any policy parameter would need backwards-compatible defaults; the preferred path is a separate runner.

[graph] `context({name:"execute", file_path:"capability/comes/executor.py"})` is lower-bound with four receiver-typing call sites dropped. The file-scoped impact walk resolves the known chain `execute_all → _run_comes → activate_capabilities` at depths 1–3, but this is not authorization evidence. Preserve the event-required API and add a background adapter.

[graph] `context({name:"is_background_task", file_path:"astrbot_compat/llm/tool.py"})` and `context({name:"PRIORITY_BACKGROUND", file_path:"core/llm/scheduler.py"})` are exact but have no incoming callers; `impact` reports UNKNOWN for both. They are useful compatibility markers only after explicit source checks, not substitutes for the task allowlist or durable scheduler.

[verified] Source checks still resolve the graph limits: `build_context` is registered from `ai_gateway.py:214` despite its UNKNOWN impact result; `execute` rejects a missing event; `run_tool_loop` always performs global hooks and may execute multiple tools per model round; `get_runtime_state` fails open to an unmuted state on DB errors.

## 5. Statement-Level PDG Findings

[graph] `can_speak` PDG slice (control depth 2, data depth 2) shows the master/toggle/mute/sleep/wake/cooldown gates return before the final allow. The message-count gate is a separate final branch. A scheduled profile must retain safety gates and explicitly bypass only message-count scoring; on a strict policy-read error it must fail closed.

[graph] `_proactive_speak_for_group` PDG slice (63 control edges; control depth 2, data depth 2) shows the ReplyGate/run gate and group lock before context creation, a consolidation branch guarded by `new_count > 0`, a duplicate/run guard, `mark_spoke` before the QQ send, and cleanup in `finally`. The new run path must fence task revision/status before generation, persist `sending` before the platform call, and record delivery only after the adapter returns a receipt; it must not retrofit the old pre-send mark ordering or silently invoke the consolidation branch.

[graph] `run_tool_loop` PDG slice has 74 data-flow edges: context → pre-hook dispatch → tool/model loop → flush → stop hook → response hook. Passing `hooks=None` only suppresses per-run custom hooks; it does not disable global hooks. Scheduled execution therefore needs an explicit policy boundary in the new adapter and a test proving no global side effect is emitted.

[graph] `capability/hooks.py:_run_comes` PDG slice flows `ctx` to `execute_all(..., event=event)`, and `capability/comes/executor.py:execute` rejects `event=None`. A background adapter must never fabricate an event; it should resolve an allowlist and call a restricted tool facade directly.

[verified] `budget_blocked` has no reservation mutation, and provider model calls acquire the existing plugin gate internally. The scheduler must cap logical model/tool calls and wall-clock time without double-acquiring that provider gate.

## 6. Proposed Changes

1. **Durable scheduling store — new `stella_project/plugins/bot_main/scheduling/store.py` and `migrations.py`.** [inferred] Add SQLite schema versioning under `STELLA_HOME/scheduling/tasks.db`. `tasks` stores UUID, instance/bot/group scope, owner, mode (`reminder|agent`), objective/template, APS3 named Cron text plus timezone, policy JSON, revision, status, next/last occurrence, limits, notification mode, and timestamps. `runs` stores task revision, scheduled-for UTC, idempotency key, lease, state, counters, rendered result, delivery receipt/error, and message fingerprint. Add a unique key `(task_id, revision, scheduled_for_utc)`; manual runs use a caller request id. Add partial uniqueness for one active run per task and transactional quota/lease rows.

2. **Cron and lifecycle service — new `scheduling/cron.py`, `service.py`, `models.py`.** [inferred] Pin and validate a five-field APScheduler 3.x-compatible dialect with named weekdays (`MON-FRI`), AND semantics when day-of-month and day-of-week are both constrained, explicit timezone, and reject ambiguous numeric-weekday input in v1. Normalize to UTC only after validation; expose next-fire preview. Handle DST by recording the resolved local/UTC occurrence and skipping a nonexistent wall time; choose the first occurrence for a repeated wall time. Add create/list/show/edit/pause/resume/cancel/run-now/history operations with optimistic `revision` fencing. An edit creates a new revision; a pause prevents new claims and causes a claimed run to re-check before generation and before send.

3. **Command and permission boundary — extend `ai_gateway.py` with a small dispatcher or new `scheduling/commands.py`.** [verified] Parse task commands before existing toggle/capability/addressing classifiers, add their prefixes to mutually-exclusive guards, and preserve current listener priority assertions. Group members may create/edit/cancel their own reminder tasks; group owners/admins and configured global admins may create agent tasks, change allowlists/quotas, or manage another user’s task. Every mutation records actor and group scope. Reject private targets and cross-group identifiers in v1.

4. **Scheduler lifecycle integration — new `scheduling/runtime.py`, wired from `ai_gateway.py` startup/shutdown.** [inferred] Start one worker per `INSTANCE_ID`/bot identity with a renewable DB lease; claim due occurrences transactionally, coalesce missed Cron fires according to an explicit policy (`latest` for agent, `all` only for short reminders with a cap), and use the existing per-group lock. On graceful shutdown stop new claims, await bounded active runs, mark expired leases recoverable, and leave `sending` as delivery-unknown after a crash. A single runtime lease is the supported deployment model for a shared DB in v1.

5. **Scheduled context and policy — new `scheduling/context.py`, plus a strict scheduled gate in `memory/proactive_gate.py`/`memory/proactive_state.py`.** [verified] Keep `ChatContext` unchanged. Build a bounded read-only summary from the target group/task history (no `build_context` pre-hook, no raw event), with a fixed character/token cap and an explicit “no context” result. Preserve master/group mute/sleep/wake and cooldown policy; pass `kind="scheduled"` only through the new validated adapter and fail closed if the scheduling policy read is unavailable. Do not consume the normal enough-new-messages heuristic.

6. **Bounded Agent runner — new `scheduling/agent.py` and `scheduling/delivery.py`; narrow additions to `astrbot_compat/llm/agent.py` only if an explicit policy keyword is needed.** [inferred] Run the configured backend with a per-run wall-clock deadline, model-round cap, logical tool-call cap, output cap, and estimated usage reservation/check. Resolve only the task’s provider/tool allowlist; require provider live/resolve success and an optional schema fingerprint. Allow only read-only or explicitly approved MCP tools in v1; deny bot send, task mutation, arbitrary plugin/skill execution, and dynamic tool discovery. Return `silent` for a policy-approved no-op, then persist result and delivery intent.

7. **Delivery and observability — new `scheduling/delivery.py` and metrics/log hooks.** [inferred] Persist `ready` → `sending` before the QQ adapter call; attach a deterministic fingerprint and platform receipt when returned; classify timeout/exception after the call as `delivery_unknown` and require manual retry. Enforce per-group task count, daily run/message quota, concurrent-run cap, and cooldown in one transaction; expose task/run ids, revision, due time, lease owner, state, policy denials, and latency without logging full prompts or tool secrets.

8. **Configuration and migration documentation — extend `config/settings.py`, `.env.example` if present, and user documentation.** [verified] Add disabled-by-default or explicit enablement, DB path, worker lease TTL, timezone default, per-run limits, group quotas, allowed MCP provider/tool patterns, and delivery retry policy. Keep provider credentials out of task rows. Document the Cron dialect, DST rule, permission matrix, delivery-unknown recovery, and the group-only v1 boundary.

9. **Do not change** `Pipeline.run`, the existing proactive job ordering, normal `execute(event=...)` semantics, or the generic `core.tasks.Task` identity model. These are high-connectivity/shared boundaries or insufficiently durable for this feature.

## 7. Implementation Sequence

1. Add the schema/migration layer and repository-scoped models; test idempotency, revision fencing, lease expiry, quotas, and transaction rollback.
2. Implement Cron parse/normalize/next-fire preview and DST/timezone tests before wiring a worker.
3. Implement lifecycle service commands and authorization; add command-classifier exclusions and audit records.
4. Implement strict scheduled policy/context builders; verify the old `can_speak` and interactive `Pipeline` tests remain unchanged.
5. Implement the restricted Agent runner with explicit limits, allowlist resolution, no-event tool facade, and per-call accounting.
6. Implement delivery state transitions, receipt/fingerprint handling, manual retry, silent results, and metrics/log redaction.
7. Add the leased runtime, group-lock integration, coalescing, restart recovery, and shutdown hook; run worker integration tests with a fake clock and fake bot.
8. Add configuration/docs and migration checks; run the full verification matrix. Before each shared-symbol edit, rerun GitNexus impact and stop on HIGH/CRITICAL or UNKNOWN until source confirms the path.

## 8. Test Strategy

[verified] Existing targets include `tests/test_proactive_gate.py`, `tests/test_proactive_at_flow.py`, `tests/test_pipeline_compose.py`, `tests/astrbot_compat/test_llm_tools.py`, `tests/capability/test_comes_executor.py`, `tests/test_usage_accounting.py`, `tests/test_env_schema.py`, and `tests/test_scheduler_concurrency.py`; update only where the new boundary changes an existing contract. The scheduler concurrency suite is the regression guard for semaphore limits, independent resources, and resolver-failure fallback.

New tests should cover:

- Cron: named weekdays, invalid fields, day/day-of-week AND semantics, timezone conversion, nonexistent/repeated DST times, next-fire preview, and latest/all coalescing.
- Store: create/edit revision, duplicate occurrence insert, pause/resume/cancel, cross-group/actor rejection, lease acquire/renew/expire, quota atomicity, and restart recovery.
- Commands: member-owned reminder CRUD, admin-only agent/allowlist changes, classifier collision with existing toggles/capability commands, private target rejection, audit record contents.
- Gate/context: master off, group mute/sleep/wake, cooldown, strict DB error fail-closed, no-new-messages still permits an explicit scheduled run, bounded summary and no raw event/pre-hook.
- Agent policy: tool not in allowlist, provider unavailable/schema drift, read-only MCP success, denied send/task mutation, model/tool/time/output limits, silent result, cancellation at each checkpoint.
- Delivery: ready→sending ordering, successful receipt, pre-call failure, post-call timeout→delivery_unknown, manual retry, fingerprint idempotency, and no duplicate automatic retry after unknown.
- Runtime: fake clock due claim, one active run per task/group, group lock serialization, worker lease takeover, restart with queued/running/sending rows, graceful shutdown, and metrics/redaction.

Verification commands (verified in `.github/workflows/ci.yml`): `python -m ruff check .`; `python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout 120 --timeout-method thread`; on a focused iteration use `python -m pytest <new-or-updated-test> -q` with the project’s Python 3.10–3.12 environment.

## 9. Risk and Impact Analysis

[graph] HIGH-risk shared symbols are `memory/proactive_gate.py:can_speak`, `core/pipeline.py:Pipeline.run`, and `astrbot_compat/llm/agent.py:run_tool_loop`; preserve compatibility and isolate scheduled behaviour. Direct callers reported by GitNexus are accounted for: `can_speak` → `_proactive_at_user`, `_proactive_speak_for_group`; `Pipeline.run` → `handle_chat`, `_proactive_at_user`, `_proactive_speak_for_group`; `run_tool_loop` → provider request, COMES `_agent_call`, probe, and context agent. The `execute` impact is lower-bound/UNKNOWN for dynamic receivers; do not infer safety from its LOW label.

[verified] Concurrency risks are duplicate claims, edit/pause races, group-lock overlap, and crash windows around platform delivery. SQLite transactions, unique occurrence keys, leases, revisions, and checkpoints address these; delivery-unknown remains a human-visible state. APScheduler Cron’s DST and weekday conventions must be tested and documented.

[inferred] Runtime cost is bounded by task quotas plus per-run model/tool/time/output caps; a background run does not receive an interactive pipeline’s unrestricted hooks or long memory context. `PRIORITY_BACKGROUND` currently falls back to FIFO, so fairness/preemption is not part of the guarantee. Provider-side retry may still multiply physical calls, so accounting and observability should report logical run calls and provider attempts separately.

[inferred] Migration risk is isolated to a new DB and additive settings. A failed migration must leave the worker disabled and preserve the prior schema version; no destructive memory migration is required.

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `stella_project/plugins/bot_main/scheduling/` (new) | new store, cron, service, runtime, context, agent, delivery, commands | Durable task lifecycle, worker, policy and delivery boundary |
| `stella_project/plugins/bot_main/ai_gateway.py` | startup/shutdown wiring, command dispatch | Existing QQ boundary, locks, admin checks and lifecycle |
| `memory/proactive_gate.py`, `memory/proactive_state.py` | scheduled strict gate/profile | Reuse safety controls without changing interactive defaults |
| `astrbot_compat/llm/agent.py` | optional explicit policy keyword only | Make hook policy explicit while preserving old defaults |
| `astrbot_compat/llm/tool.py`, `core/llm/scheduler.py` | existing `is_background_task` / `PRIORITY_BACKGROUND` markers | Verify compatibility; do not treat either as the authorization or fairness mechanism |
| `config/settings.py` | scheduling settings | Typed config and enablement |
| `.env.example` / user docs | new settings and command help | Operability and dialect/permission disclosure |
| `tests/` listed in §8 | new and focused regression tests | Durable lifecycle, policy, delivery and compatibility coverage |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: "Add durable group-scoped Cron reminders and a bounded proactive Agent with explicit MCP allowlists and auditable delivery states."
  acceptance_criteria:
    - "CRUD/pause/resume/cancel/run-now/history is durable across restart and fenced by task revision."
    - "Cron dialect, timezone and DST behaviour are validated and previewable."
    - "Permissions, group scope, quotas, leases, model/tool/time/output caps and redaction are enforced."
    - "Interactive Pipeline/proactive/COMES contracts remain unchanged."
    - "Delivery states distinguish success, silent, failure, cancellation and delivery_unknown; no exactly-once claim."
  evidence_provenance:
    {
      "schema_version": 2,
      "head_commit": "0dafa5fe293288f26bb55bae9f279407dd7c5a5f",
      "generated_plan_path": "docs/plans/2026-09-22-gitnexus-plan-user-cron-agent.md",
      "global_dirty_digest": {
        "algorithm": "sha256",
        "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
        "value": "ddae2d79e44267d6fd40de31c3f37d8d0f10af2a37e7e7e7753d1c4300704ecf"
      },
      "cited_path_manifest": [
        {
          "path": ".github/workflows/ci.yml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "index_digest": "sha256:bd4bc7fccb641a01d37fecc43014a27a0e01fbee36f8b892b39721e207af1419",
          "worktree_digest": "sha256:34d982e2622d379623fa8dcb96e87e6b2b352afadb1ae1be27de86e1ef7ec957",
          "untracked_digest": "absent"
        },
        {
          "path": "astrbot_compat/llm/agent.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2de7b63a50a516dc5a0d2dcb360b62e2f1f69f7a8e546afbcb442bffa4f40852",
          "index_digest": "sha256:2de7b63a50a516dc5a0d2dcb360b62e2f1f69f7a8e546afbcb442bffa4f40852",
          "worktree_digest": "sha256:2de7b63a50a516dc5a0d2dcb360b62e2f1f69f7a8e546afbcb442bffa4f40852",
          "untracked_digest": "absent"
        },
        {
          "path": "astrbot_compat/llm/provider.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:7c3019173d2c60c7d8366ab820bcc8dcbe3278ace971a051ae71bbb30022eb29",
          "index_digest": "sha256:7c3019173d2c60c7d8366ab820bcc8dcbe3278ace971a051ae71bbb30022eb29",
          "worktree_digest": "sha256:c7a5f69917a9188044550617ca5258cc7f86551dc7c8ee7604f640b31cf3158a",
          "untracked_digest": "absent"
        },
        {
          "path": "astrbot_compat/llm/tool.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:98189386e6ef4a14dc90eef7d4f085537e674723ff5652c9267d4901bd6485da",
          "index_digest": "sha256:98189386e6ef4a14dc90eef7d4f085537e674723ff5652c9267d4901bd6485da",
          "worktree_digest": "sha256:98189386e6ef4a14dc90eef7d4f085537e674723ff5652c9267d4901bd6485da",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/comes/__init__.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
          "index_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
          "worktree_digest": "sha256:093e161a3ea22b6e05ddd7024fdd5b667103171729b313e3fc976d7f00b11f3c",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/comes/executor.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0a86f86e19c8a212dc2aff6c2ee5cb72f13b2296e4dc5c18b4ff10f72ca0677d",
          "index_digest": "sha256:0a86f86e19c8a212dc2aff6c2ee5cb72f13b2296e4dc5c18b4ff10f72ca0677d",
          "worktree_digest": "sha256:0a86f86e19c8a212dc2aff6c2ee5cb72f13b2296e4dc5c18b4ff10f72ca0677d",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/hooks.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2e47fd4c0aa0f0fffe666ba800837ef2c3034ec8f265a76be145bff9bed875a4",
          "index_digest": "sha256:2e47fd4c0aa0f0fffe666ba800837ef2c3034ec8f265a76be145bff9bed875a4",
          "worktree_digest": "sha256:2e47fd4c0aa0f0fffe666ba800837ef2c3034ec8f265a76be145bff9bed875a4",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/providers/mcp/tool.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:91e41a8fb2875c85395c6c5a57b8258c367a59f517208e1c11a2b4e15e47c3a5",
          "index_digest": "sha256:91e41a8fb2875c85395c6c5a57b8258c367a59f517208e1c11a2b4e15e47c3a5",
          "worktree_digest": "sha256:91e41a8fb2875c85395c6c5a57b8258c367a59f517208e1c11a2b4e15e47c3a5",
          "untracked_digest": "absent"
        },
        {
          "path": "capability/providers/registry.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a2da39a1d994aee55246439f5184e4c318fc659b1cbbad3c2938197f588f2b59",
          "index_digest": "sha256:a2da39a1d994aee55246439f5184e4c318fc659b1cbbad3c2938197f588f2b59",
          "worktree_digest": "sha256:a2da39a1d994aee55246439f5184e4c318fc659b1cbbad3c2938197f588f2b59",
          "untracked_digest": "absent"
        },
        {
          "path": "config/settings.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:7c1f4c66bc86b04140e4002cbb09c3116ed831e3c6ee02307e0f5258949005ea",
          "index_digest": "sha256:7c1f4c66bc86b04140e4002cbb09c3116ed831e3c6ee02307e0f5258949005ea",
          "worktree_digest": "sha256:ca5a1f4025aaa065b2041a6549cac4fcca651c45425b100be342c61dc4d467a9",
          "untracked_digest": "absent"
        },
        {
          "path": "core/context.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:3ca8c974bc19040b7298abf40e6ab5d45c64d1560f42fe2288d1315fd4cfd7bb",
          "index_digest": "sha256:3ca8c974bc19040b7298abf40e6ab5d45c64d1560f42fe2288d1315fd4cfd7bb",
          "worktree_digest": "sha256:3ca8c974bc19040b7298abf40e6ab5d45c64d1560f42fe2288d1315fd4cfd7bb",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/scheduler.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",
          "index_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",
          "worktree_digest": "sha256:1867025f4767030a779914106ec075106a3860baa67b247787aad90426d412a2",
          "untracked_digest": "absent"
        },
        {
          "path": "core/llm/usage_store.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:0ca65c7e790d9e962839d755de0395e89dffabb30e99b50d6891127493145771",
          "index_digest": "sha256:0ca65c7e790d9e962839d755de0395e89dffabb30e99b50d6891127493145771",
          "worktree_digest": "sha256:0ca65c7e790d9e962839d755de0395e89dffabb30e99b50d6891127493145771",
          "untracked_digest": "absent"
        },
        {
          "path": "core/pipeline.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b622f79f3ccfe09e162c3ff599a030f92ec7001bccba5c3c85e5355144767bbf",
          "index_digest": "sha256:b622f79f3ccfe09e162c3ff599a030f92ec7001bccba5c3c85e5355144767bbf",
          "worktree_digest": "sha256:502094c4dc7052c1a585aee06332d5d7d35cc48e421ea827d8b3222b8d9ac40a",
          "untracked_digest": "absent"
        },
        {
          "path": "core/tasks.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:293c3172eb239663188e214e65eb7f20b83989c16e42f0e5fb4a6bba11e500d7",
          "index_digest": "sha256:293c3172eb239663188e214e65eb7f20b83989c16e42f0e5fb4a6bba11e500d7",
          "worktree_digest": "sha256:293c3172eb239663188e214e65eb7f20b83989c16e42f0e5fb4a6bba11e500d7",
          "untracked_digest": "absent"
        },
        {
          "path": "design_docs/AstrBot 特性吸收对比报告.md",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:bf9f7c7d9c4cc23190eb0291ab5e874236f3488e89175294248a048aa7637182",
          "index_digest": "sha256:bf9f7c7d9c4cc23190eb0291ab5e874236f3488e89175294248a048aa7637182",
          "worktree_digest": "sha256:bf9f7c7d9c4cc23190eb0291ab5e874236f3488e89175294248a048aa7637182",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/pre_processors.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:c9ed86b5e52ca9c0d12c121039be66e6c4b955e3a4d2fd5935882c6d628c9940",
          "index_digest": "sha256:c9ed86b5e52ca9c0d12c121039be66e6c4b955e3a4d2fd5935882c6d628c9940",
          "worktree_digest": "sha256:cf5a22c54e5c799efec1bd2572e2cb237def5a35f15c8a2e10939701f519ff34",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cffe3998072a7c3c583b96211b392e81d31ddd9e9b570dfeee4e519efc3dfd7b",
          "index_digest": "sha256:cffe3998072a7c3c583b96211b392e81d31ddd9e9b570dfeee4e519efc3dfd7b",
          "worktree_digest": "sha256:58b2703c433ca698224861c57f303133a3688d6ef6fc6fd0c04b5b9b376559d7",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive_gate.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:a4190156b5ca670c0744ee414957073332934dcd1c72d4515c1342573a257b0e",
          "index_digest": "sha256:a4190156b5ca670c0744ee414957073332934dcd1c72d4515c1342573a257b0e",
          "worktree_digest": "sha256:a4190156b5ca670c0744ee414957073332934dcd1c72d4515c1342573a257b0e",
          "untracked_digest": "absent"
        },
        {
          "path": "memory/proactive_state.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:66dbb5a847f380533021fc82c696024066a7252612e850114b92f7a116e38c51",
          "index_digest": "sha256:66dbb5a847f380533021fc82c696024066a7252612e850114b92f7a116e38c51",
          "worktree_digest": "sha256:66dbb5a847f380533021fc82c696024066a7252612e850114b92f7a116e38c51",
          "untracked_digest": "absent"
        },
        {
          "path": "pyproject.toml",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:15f9425125da784c02d267114ccf47ddc02143100b16d1b72258bdf8d053c655",
          "index_digest": "sha256:15f9425125da784c02d267114ccf47ddc02143100b16d1b72258bdf8d053c655",
          "worktree_digest": "sha256:f17308657cce1b51c8763d2404002bbb9f9152387c401e9912fa659f86b7ec2a",
          "untracked_digest": "absent"
        },
        {
          "path": "stella_project/plugins/bot_main/ai_gateway.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:2d7f6606ae194cb12c0dd8982632fbbee0cccd08187a6794b46a04459072456a",
          "index_digest": "sha256:2d7f6606ae194cb12c0dd8982632fbbee0cccd08187a6794b46a04459072456a",
          "worktree_digest": "sha256:a0fc43e505e6830f4d74f74df57c73007657e23049eca74774eb4f8d6ab3e923",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/astrbot_compat/test_llm_tools.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1149fc14519cfdd218ddcc8bbea45fc4431f17ed9a46485021757985b88f35bd",
          "index_digest": "sha256:1149fc14519cfdd218ddcc8bbea45fc4431f17ed9a46485021757985b88f35bd",
          "worktree_digest": "sha256:1149fc14519cfdd218ddcc8bbea45fc4431f17ed9a46485021757985b88f35bd",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/capability/test_comes_executor.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:e83a0474e6a0b8ee63f5ed257524d7ca37513f02828bf3fceba583b9a3fdcd56",
          "index_digest": "sha256:e83a0474e6a0b8ee63f5ed257524d7ca37513f02828bf3fceba583b9a3fdcd56",
          "worktree_digest": "sha256:e83a0474e6a0b8ee63f5ed257524d7ca37513f02828bf3fceba583b9a3fdcd56",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_env_schema.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:f85d14be195d32afc4a0bc92044f20055a9f99796dafd48e43e53dfb9fa0e99b",
          "index_digest": "sha256:f85d14be195d32afc4a0bc92044f20055a9f99796dafd48e43e53dfb9fa0e99b",
          "worktree_digest": "sha256:5490ed37bc0865e6e7d2dad31c2da35ee9d4745c4dc156282a16bd15ef086ce8",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_pipeline_compose.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:cc9d6f54871db100107067f60833e3682dc8ae30daf64281949cd82faceb36a2",
          "index_digest": "sha256:cc9d6f54871db100107067f60833e3682dc8ae30daf64281949cd82faceb36a2",
          "worktree_digest": "sha256:5714b0bf23cb8d02942230ac3991dcec8e9a080fcc74cf213a824366cdf79658",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_proactive_at_flow.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:b7a708d24f62a3f05ed1c9c0592d24eeb02e8c3703d98b2549ebfe6c11682432",
          "index_digest": "sha256:b7a708d24f62a3f05ed1c9c0592d24eeb02e8c3703d98b2549ebfe6c11682432",
          "worktree_digest": "sha256:b7a708d24f62a3f05ed1c9c0592d24eeb02e8c3703d98b2549ebfe6c11682432",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_proactive_gate.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:1f16b8b56a79dddd6fd3f43d49e306c81c5d584fa69fc3e65457afdf209a8642",
          "index_digest": "sha256:1f16b8b56a79dddd6fd3f43d49e306c81c5d584fa69fc3e65457afdf209a8642",
          "worktree_digest": "sha256:1f16b8b56a79dddd6fd3f43d49e306c81c5d584fa69fc3e65457afdf209a8642",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_scheduler_concurrency.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",
          "index_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",
          "worktree_digest": "sha256:6b69eecff94c40ddbc1a4bf2ee680ec08ce1a98544c1fb4c30297b69f199add0",
          "untracked_digest": "absent"
        },
        {
          "path": "tests/test_usage_accounting.py",
          "object_kind": {
            "head": "regular",
            "index": "regular",
            "worktree": "regular",
            "untracked": "absent"
          },
          "state": "clean",
          "rename_from": null,
          "rename_to": null,
          "head_digest": "sha256:823c499606d08f094fd70150eebb87df43ba41da6d2423e37a7641f1ffd6e046",
          "index_digest": "sha256:823c499606d08f094fd70150eebb87df43ba41da6d2423e37a7641f1ffd6e046",
          "worktree_digest": "sha256:823c499606d08f094fd70150eebb87df43ba41da6d2423e37a7641f1ffd6e046",
          "untracked_digest": "absent"
        }
      ]
    }
  primary_symbols:
    - symbol: "can_speak"
      file: "memory/proactive_gate.py"
      lines: "182-220"
      role: "existing proactive safety gate; scheduled profile must preserve safety gates"
    - symbol: "_proactive_speak_for_group"
      file: "stella_project/plugins/bot_main/ai_gateway.py"
      lines: "1629-1775"
      role: "existing group proactive flow and ordering reference"
    - symbol: "Pipeline.run"
      file: "core/pipeline.py"
      lines: "220-350"
      role: "shared interactive pipeline; preserve"
    - symbol: "run_tool_loop"
      file: "astrbot_compat/llm/agent.py"
      lines: "217-321"
      role: "compatibility tool-loop contract and hook ordering"
    - symbol: "execute"
      file: "capability/comes/executor.py"
      lines: "310-469"
      role: "event-required boundary; do not fabricate event"
  related_symbols:
    - symbol: "build_context"
      relationship: "registered pre-hook"
      relevance: "interactive session initialization; scheduled context bypasses it"
    - symbol: "_run_comes"
      relationship: "CALLS execute_all with event"
      relevance: "event-bound capability path"
    - symbol: "budget_blocked"
      relationship: "CALLS/read"
      relevance: "check only; not durable reservation"
    - symbol: "acquire"
      relationship: "CALLS/provider gate"
      relevance: "existing async gate; no task persistence"
    - symbol: "Task"
      relationship: "existing in-process model"
      relevance: "not the durable task identity"
    - symbol: "McpFunctionTool.call"
      relationship: "tool invocation"
      relevance: "candidate execution primitive behind explicit allowlist"
    - symbol: "FunctionTool.is_background_task"
      relationship: "HAS_PROPERTY"
      relevance: "unreferenced compatibility marker; not authorization"
    - symbol: "PRIORITY_BACKGROUND"
      relationship: "constant"
      relevance: "defined but FIFO priority is disabled; not a fairness guarantee"
  execution_path:
    - "Command parser authenticates actor and group, validates Cron/policy, then commits task revision and audit row."
    - "Leased worker claims a due occurrence using unique task/revision/scheduled-for key and per-group lock."
    - "Scheduled context builder creates bounded read-only input; strict scheduled gate checks master/mute/sleep/wake/cooldown."
    - "Agent runner resolves only approved live providers/tools and enforces model/tool/time/output/usage limits."
    - "Run persists ready/sending before QQ call, then receipt or delivery_unknown; history and metrics expose the result."
  pdg_constraints:
    - description: "can_speak safety gates dominate the final allow; only scheduled message-count scoring may be bypassed."
      affected_statements: ["memory/proactive_gate.py:198-220"]
      implementation_consequence: "Preserve interactive function and add explicit scheduled validation/fail-closed read path."
    - description: "proactive group flow records state before its send and cleans up in finally."
      affected_statements: ["stella_project/plugins/bot_main/ai_gateway.py:1650-1769"]
      implementation_consequence: "Use new durable sending/receipt ordering; do not copy old mark-before-send semantics."
    - description: "run_tool_loop global hooks are independent from hooks=None."
      affected_statements: ["astrbot_compat/llm/agent.py:226-320"]
      implementation_consequence: "Use explicit scheduled hook policy and test that global side effects are disabled."
    - description: "COMES execute requires an event."
      affected_statements: ["capability/hooks.py:171-184", "capability/comes/executor.py:310-344"]
      implementation_consequence: "Background tools use a restricted facade, never a fabricated event."
  architectural_patterns:
    - pattern: "SQLite schema versioning"
      example_location: "memory/proactive_state.py:get_runtime_state"
      usage_guidance: "Use a separate scheduling DB and transactional migrations."
    - pattern: "Existing group lock and gateway delivery boundary"
      example_location: "stella_project/plugins/bot_main/ai_gateway.py:_proactive_speak_for_group"
      usage_guidance: "Inject/reuse at the edge; keep normal chat paths unchanged."
    - pattern: "Provider live/resolve checks"
      example_location: "capability/providers/registry.py"
      usage_guidance: "Combine with task-owned allowlist and schema fingerprint."
  files_to_modify:
    - file: "stella_project/plugins/bot_main/scheduling/"
      symbols: ["new TaskStore", "new CronService", "new SchedulerRuntime", "new BackgroundAgent", "new DeliveryService"]
      intended_change: "Implement durable lifecycle, worker, policy, bounded agent and delivery."
    - file: "stella_project/plugins/bot_main/ai_gateway.py"
      symbols: ["startup/shutdown wiring", "task command dispatch"]
      intended_change: "Connect scheduler to existing QQ/admin/lock lifecycle."
    - file: "memory/proactive_gate.py"
      symbols: ["can_speak or new scheduled gate helper"]
      intended_change: "Add explicit strict scheduled policy without changing old defaults."
    - file: "memory/proactive_state.py"
      symbols: ["strict runtime-state read or new scheduling policy read"]
      intended_change: "Fail closed for scheduled policy DB errors."
    - file: "config/settings.py"
      symbols: ["new scheduling settings"]
      intended_change: "Expose enablement, DB, quotas, limits and allowlists."
  tests:
    - file: "tests/test_proactive_gate.py"
      scenarios: ["scheduled profile keeps safety gates", "strict policy error denies", "interactive defaults unchanged"]
    - file: "tests/test_proactive_at_flow.py"
      scenarios: ["existing proactive flow remains compatible", "group lock and shutdown integration"]
    - file: "tests/astrbot_compat/test_llm_tools.py"
      scenarios: ["explicit scheduled hook policy does not change legacy loop", "tool/round limits"]
    - file: "tests/capability/test_comes_executor.py"
      scenarios: ["event-required legacy path remains failing fast", "background facade does not fabricate event"]
    - file: "tests/test_usage_accounting.py"
      scenarios: ["logical scheduled budget and provider attempts are bounded/accounted"]
    - file: "tests/test_scheduler_concurrency.py"
      scenarios: ["background runs use existing semaphore limits and do not assume priority preemption"]
    - file: "tests/test_env_schema.py"
      scenarios: ["new settings parse/default/validation"]
    - file: "tests/scheduling/test_lifecycle.py"
      scenarios: ["CRUD, revision, pause/resume/cancel, leases, quota, restart"]
    - file: "tests/scheduling/test_cron.py"
      scenarios: ["dialect, timezone, DST, next-fire and coalescing"]
    - file: "tests/scheduling/test_agent_policy.py"
      scenarios: ["allowlist, limits, no-event facade, silent/denied outcomes"]
    - file: "tests/scheduling/test_delivery.py"
      scenarios: ["receipt, unknown, manual retry, fingerprint"]
  verification_commands:
    - "python -m ruff check ."
    - "python -m pytest tests/ -v --cov=. --cov-branch --cov-report=xml -n auto --dist loadgroup --timeout 120 --timeout-method thread"
  risks:
    - "HIGH shared-symbol blast radius; rerun impact before each edit."
    - "Delivery crash window is explicitly delivery_unknown, not exactly-once."
    - "Multiple workers on one DB are unsupported beyond the runtime lease contract."
    - "Cron/DST semantics and provider retry multiplication require integration tests."
  assumptions:
    - "Check the installed APScheduler version and pin it before implementing the dialect."
    - "Check the QQ adapter can return a stable receipt or message id; otherwise retain unknown/manual retry."
    - "Check provider schema fingerprints are available for every approved MCP tool; disable drift checking where unavailable only with an explicit setting."
    - "Check deployment uses one leased runtime per bot identity for the shared scheduling DB."
  open_questions:
    - "Should private-chat tasks be added after group-only v1, and what durable private target identity is authorized?"
    - "Which MCP servers/tools are approved for the first production allowlist?"
    - "What are the default per-group daily quotas and operator override process?"
  avoid:
    - "Do not reuse Pipeline.run for scheduled work."
    - "Do not fabricate NoneBot/AstrBot events for background execution."
    - "Do not enable arbitrary plugins, skills, dynamic tool discovery, @all, or cross-group targets in v1."
    - "Do not mark delivery successful before the platform adapter returns a receipt."
    - "Do not auto-retry delivery_unknown without an explicit manual action."
    - "Do not treat FunctionTool.is_background_task or PRIORITY_BACKGROUND as sufficient authorization/fairness; verify their current no-caller/FIFO semantics."
    - "Do not alter the generic core.tasks.Task model or existing proactive ordering."
```

## 12. Assumptions and Open Questions

**Assumptions to verify before implementation**

- [assumed] APScheduler is available at a version whose CronTrigger weekday and DST behaviour match the documented 3.x API; inspect the lock/environment and pin it before coding.
- [assumed] The QQ adapter can expose a message id or equivalent receipt. If it cannot, retain `delivery_unknown` with a manual retry command and no automatic duplicate suppression claim.
- [assumed] The first deployment uses one active scheduler lease per bot identity and shares no task DB across unrelated instances.
- [assumed] The selected first-party MCP tools are read-only or have explicit idempotent semantics; operator approval is required before adding them.

**Open questions**

- [assumed] Whether private-chat scheduling should follow group-only v1; no safe durable private target identity was verified in this pass.
- [assumed] Default quotas, retention period, and operator override workflow need product values.
- [assumed] Whether schema fingerprinting is mandatory for every approved provider or only for providers that expose a stable schema.

**Explicitly deferred**

- WebUI task management, multi-bot federation, shared multi-worker scheduling beyond the lease, arbitrary AstrBot/plugin/skill execution, @all/mention fan-out, private targets, and redesign of the generic pipeline/MCP registry are outside this item.

## 13. Definition of Done

- [ ] A group member can create/list/show/edit/pause/resume/cancel/run-now a reminder; an admin can manage agent tasks and allowlists; cross-group and unauthorized mutations are rejected and audited.
- [ ] A task survives restart; duplicate occurrence insertion is idempotent; edit/pause fences queued and claimed work; lease recovery and shutdown are tested.
- [ ] The documented Cron dialect, timezone conversion, DST rules, next-fire preview and coalescing behaviour pass tests.
- [ ] Scheduled context is bounded and read-only; the interactive pre-hook/pipeline and event-required COMES contracts remain regression-clean.
- [ ] Agent runs enforce provider/tool allowlist, model-round/tool/time/output/usage limits, quotas and cancellation checkpoints; denied operations are observable without secrets.
- [ ] Delivery history distinguishes succeeded, silent, failed, skipped, cancelled and delivery_unknown; no implementation claims exactly-once QQ delivery.
- [ ] `python -m ruff check .` and the CI pytest command pass on supported Python versions; migrations, docs and configuration defaults are reviewed.