# Mneme: Canonical Name of the Memory Subsystem

[中文](mneme.md) | English · [Architecture map](README.en.md)

Mneme is the canonical Python package of the Stella memory subsystem
(2026-11-03 plan §3.1, since S1-03). The design body and gate rules live in
[Memory System](memory-system.en.md) — this page only records naming and
code boundaries, not a second body.

## Code boundaries

- The canonical implementation lives in `mneme/` (retrieval, consolidation,
  promotion, schema, social, expression learning, and all other memory
  modules); `memory/*` is an explicit alias layer to `mneme/*`: each module
  self-replaces `sys.modules` on import, so legacy and canonical paths
  resolve to the same module object. Monkeypatching
  `memory.schema.DB_PATH` and `mneme.schema.DB_PATH` hits one
  implementation.
- CLIs work both ways: `python -m memory.schema` forwards to
  `python -m mneme.schema` with identical exit codes and output.
- The proactive participation subsystem is [Aoede](aoede.en.md); Mneme does
  not import Aoede — both depend only on `stella_contracts/aoede.py`
  ports. `mneme/verification.py` and the verification attempt/tombstone
  persistence land in stage two (S2-01).
- The `memory_rust` release name, native ABI, `BACKEND_API_VERSION` and the
  SQLite file name do not change with this rename; the Rust wheel is a
  versioned external dependency, not an unfinished rename.

## Data and resources (unchanged)

The database path stays `DB_PATH` (default user-directory
`memory/agent_memory.db`); `memory/SYSTEM.md`, `memory/benchmark/` fixtures
and user overrides stay in place with traceable provenance. The package
rename migrates no user data.
