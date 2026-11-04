# Proactive and memory evaluation contracts

This directory records the B00 benchmark contracts. B00 freezes source datasets, split boundaries, primary outcomes, baseline identity, cost limits, and report schemas. The adapters and executable CLI are introduced in B01; there is no `python -m proactive_eval` command yet.

## Frozen artifacts

- [`dataset-registry.json`](dataset-registry.json) pins dataset revisions, licenses, selected files, hashes, source units, and known exclusions. Raw third-party files live only under the gitignored `memory/benchmark/_public/` cache.
- [`protocol-lock.json`](protocol-lock.json) freezes primary endpoints, denominator rules, preregistered thresholds, cluster bootstrap settings, annotation protocol, and model-call caps.
- `schemas/` holds actor-only scenarios, scorer-only gold, and versioned report contracts. Gold is a sidecar to be read by the scorer process; it must never enter actor prompts, embeddings, caches, or initial memory state.
- [`NOTICE.md`](NOTICE.md) records source attribution and handling limits.

## Actor/scorer boundary

An actor scenario contains only the observed prefix, the memory visible at that point, and events already occurred. It has no gold label, future turn, acceptable window, answer, later confirmation, or future memory field. Scorer-only records use a separate schema and storage path. The evaluator must reject unknown fields instead of silently dropping them.

All reports retain total, completed, failed, skipped, and not-applicable counts. Each metric carries its own numerator, denominator, status, and value. An empty denominator is `not_applicable` or `not_run`, never a passing zero.

## Readiness

B00 freezes the offline protocol and data fingerprints. It does not certify model behavior, real QQ/WebChat delivery, release payloads, or Windows installation. See the date-stamped B00 report and the task state in `progress.md` for the exact run evidence and remaining gates.
