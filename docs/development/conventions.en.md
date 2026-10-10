# Code Conventions

[中文](conventions.md) | English · [Documentation](../README.en.md)

## Code Conventions

**Lint / formatting**: ruff (configured in `pyproject.toml`). black is not used -- do not introduce black formatting, as it creates large amounts of meaningless diff.

**Type checking**: pyright (`pyrightconfig.json`). CI does not run type checking, but new code should include type annotations.

**Comments should explain "why", not "what".** Many comments in the project record the empirical basis for a threshold, why an order is necessary, or the cause of a bug. Once removed, that information cannot be inferred from the code. For example:

```python
# The confidence / importance weights are deliberately reduced to 0.05: they describe
# whether the memory itself is reliable/important and have little to do with "whether
# it should be used now", so they are suitable only as tie-breakers. Otherwise a
# high-quality decoy with conf~=0.98 could cheat on "whether it should be used".
```

**Do not keep a second copy of logic.** The existence of `memory/text_similarity.py` is itself a consequence of similarity checks once existing in three modules; the cross-user merge bug then had to be fixed three times and was missed twice.

**Silent fallback must leave a trace.** The project contains many `except sqlite3.OperationalError` clauses to tolerate "the table does not exist yet" (lazy table creation), and that design is correct. But it also swallows fatal errors such as "column name mismatch" -- both incidents on 2026-08-17 (a missing memory-table column and @ messages not entering the database) remained unnoticed for hours for this reason.

Convention: classify SQLite exceptions by message content when catching them.

```python
if "no such table" in str(e):
    logger.debug(...)   # Normal case for lazy table creation
else:
    logger.warning(...)  # Especially no such column; it must be visible
```

Likewise, every path that "returns an empty result on failure and continues" must leave a warning. A feature that fails silently is much harder to diagnose than a crash.

**Prompt changes need guardrails.** `tests/test_consolidation_prompt.py` and `tests/test_proactive_prompt.py` use string assertions for key clauses, including reverse assertions (confirming that removed clauses have not been written back). After such a clause is removed, the feature still "works" but its quality immediately degrades; only assertions can lock this down.
## Commits and Contributions

**Commit messages** should briefly describe the substance of the change in English or Chinese. Avoid information-free descriptions such as "fix bug" or "update".

**Before a PR**:

- `python -m pytest tests -q` is fully green
- `ruff check .` reports no warnings
- If a prompt changed, the two-way gate was run (positive regression + real windows)
- If the schema changed, `python -m memory.schema --dry-run` output is as expected
- If configuration items changed, `.env.example` is synchronized (`deploy init` renders from it; if it is missed, the new configuration item will not appear in the generated `.env`), and `docs/configuration.en.md` is synchronized
- If listener priority changed or a handler with `block=True` was added, confirm that the persistence listener remains the highest priority and send one @ message to verify that `AT_MENTION` is persisted
- If memory-table SQL changed, confirm that it uses `group_shared_space` rather than `group_id` (the two ownership layers are described in architecture.en.md)
- If Router rules / capability declarations changed, `python -m capability.router.benchmark --rules-only` still reports 0 memory false negatives and 0 tool false positives
- Before enabling `ROUTER_GATE_MEMORY`, run the full-pipeline benchmark (requires an embedding service) and confirm exit code 0; this is the only way to verify that it will not silently lose memories
- When adding a new capability Provider type (MCP / API / native), implement its branch in `capability/comes/executor.py::resolve_tools`; do not let it silently fall into `missing`

**Explain the reason in the PR description when the change involves any of the following**:

- Thresholds or decision logic for memory promotion
- Anti-fabrication clauses in prompts
- Ownership filtering in the three merge paths
- Link-monitor liveness / alert logic (heartbeat + active probe, alert only and no restart)
- Listener priority and block relationships
- The division between the two ownership layers (QQ group / shared space)

All of these areas have empirical evidence (recorded in `design_docs/check_point/` and `bug_report/`); before changing them, reading the relevant records is recommended.
