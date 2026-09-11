# Rust Memory Backend

Stella keeps the existing `memory/` Python engine as the default and fallback.
The optional Rust distribution is installed independently as
`stella-memory-rust`; it uses the `memory_rust` namespace and targets memory
schema 14 with backend API version 1.

## Runtime Modes

Set `MEMORY_BACKEND` before starting Stella:

- `python`: existing Python implementation, the default.
- `rust`: use the native Rust retrieval backend; incompatibility or runtime
  errors are surfaced.
- `auto`: use Rust when available and compatible, then fall back to Python.
- `shadow`: run Rust read-only beside Python, record parity diagnostics, and
  return the Python result. Rust performs no write or post-commit side effect.
- `strict`: require the Rust backend and surface load or contract failures.

The first rollout keeps `python` as the recommended setting. Returning to the
Python engine is an environment-only change:

```text
MEMORY_BACKEND=python
```

Rust does not own embedding HTTP, LLM consolidation, schema migration,
Python async locks, scheduler work, cache invalidation, or compressor
side effects.

## Release Assets

The main release keeps its existing name:

```text
Stella-vX.Y.Z-win64.zip
```

The same `vX.Y.Z` GitHub Release also receives the independent Rust engine:

```text
Stella-Rust_engine_version-vX.Y.Z-win64.zip
```

The Rust asset contains the separately installable wheel and checksums. Its
package version is independent of the Stella application version, while the
asset filename always uses the exact main Release tag.
