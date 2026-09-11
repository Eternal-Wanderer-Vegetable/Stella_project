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

For compatibility with earlier rollout scripts, `MEMORY_RUST_SHADOW=true`
selects `shadow` and `MEMORY_RUST_STRICT=true` selects `strict` when
`MEMORY_BACKEND` is unset. If both flags are enabled, strict wins. An explicit
`MEMORY_BACKEND` value always takes precedence.

The first rollout keeps `python` as the recommended setting. Returning to the
Python engine is an environment-only change:

```text
MEMORY_BACKEND=python
```

Rust does not own embedding HTTP, LLM consolidation, schema migration,
Python async locks, scheduler work, cache invalidation, or compressor
side effects.

## Compatibility Matrix

| Rust distribution | Backend API | Memory schema | Python |
| --- | ---: | ---: | --- |
| `stella-memory-rust 0.1.x` | 1 | 14 | 3.10+ (`abi3`) |

The native loader rejects API or schema mismatches before selecting Rust. The
main Stella package keeps the Python engine and does not require this
distribution.

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
