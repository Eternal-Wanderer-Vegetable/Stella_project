# Rust Memory Backend

[中文](memory-rust-backend.md) | English

The Python `memory/` engine remains the default and fallback. The optional
`stella-memory-rust` wheel exposes native retrieval and promotion through the
`memory_rust` namespace. Stella 6.1.0 requires **backend API 2 and memory schema
18** on both sides; the wheel package version is independent of the application
version.

## Runtime modes

Set `MEMORY_BACKEND` before starting Stella:

| Mode | Behavior |
| --- | --- |
| `python` | Default Python implementation |
| `rust` | Require compatible native retrieval/promotion; surface failures |
| `auto` | Select compatible Rust when available, otherwise Python |
| `shadow` | Return Python results and compare read-only Rust retrieval; no native write or post-commit effect |
| `strict` | Require Rust and surface load/contract failures |

When `MEMORY_BACKEND` is unset, legacy `MEMORY_RUST_SHADOW=true` selects shadow,
and `MEMORY_RUST_STRICT=true` selects strict. Strict wins if both flags are set.
An explicit backend setting takes precedence. To return to Python, set
`MEMORY_BACKEND=python` and restart.

Rust does not own embedding HTTP, LLM consolidation, schema migration, Python
async locks, scheduling, cache invalidation, or compressor side effects. The
Python integration retains those responsibilities.

## Compatibility

| Payload built from | Backend API | Memory schema | Python |
| --- | ---: | ---: | --- |
| Stella `v6.1.0` native source (`stella-memory-rust 0.1.0`) | 2 | 18 | 3.10+ (`abi3`) |

The loader validates exported API/schema constants before selecting Rust.
An older wheel can also be named `0.1.0`; **package version alone cannot prove
compatibility**. Use the wheel shipped with the matching Stella release and
verify its exported constants. Python and Rust owner/audience contracts must
agree, including personal-memory scopes and source-bound promotion.

## Release assets

```text
Stella-OneClick-Rust-v6.1.0-windows-amd64.exe
Stella-OneClick-Rust-Offline-v6.1.0-windows-amd64.exe
Stella-Standalone-Rust-v6.1.0-windows-amd64.zip
```

Standalone-Rust bundles one wheel under `wheels/`. `start.bat` or `Stella.exe`
performs first-run bootstrap, installs that local wheel into the application
directory, and selects `MEMORY_BACKEND=rust`. OneClick prepares it during
installation; Offline includes the runtime and dependencies as well. Python
products keep the Python engine. Installing beside the bundled `memory_rust`
package makes the extension importable from embedded Python. `VERSION.txt` and
`SHA256SUMS.txt` describe the payload; the asset name uses the main release tag.

## Acceptance boundaries

The dated [P8 report](reports/2026-10-05-dialogue-attribution-p8-acceptance.md)
records API 2/schema 18 loading, native tests, and 21/24 hard matches in the
retrieval benchmark. Three conversation-ranking differences remain open. Those
results are historical evidence, not a fresh benchmark of every downloaded
6.1.0 asset. Keep Python selected when identical ranking is required, and assess
shadow diagnostics before changing an existing deployment.
