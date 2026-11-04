# Proactive and memory evaluation contracts

This directory contains the frozen B00 benchmark contracts and the B01 schema adapters, isolated runner, scorer, and CLI. B00 freezes source datasets, split boundaries, primary outcomes, baseline identity, cost limits, and report schemas.

## Frozen artifacts

- [`dataset-registry.json`](dataset-registry.json) pins dataset revisions, licenses, selected files, hashes, source units, and known exclusions. Raw third-party files live only under the gitignored `memory/benchmark/_public/` cache.
- [`protocol-lock.json`](protocol-lock.json) freezes primary endpoints, denominator rules, preregistered thresholds, cluster bootstrap settings, annotation protocol, and model-call caps.
- [`baseline-lock.json`](baseline-lock.json) records baseline inputs and exact report digests; raw per-case results remain gitignored.
- `schemas/` holds actor-only scenarios, scorer-only gold, and versioned report contracts. Gold is a sidecar to be read by the scorer process; it must never enter actor prompts, embeddings, caches, or initial memory state.
- [`NOTICE.md`](NOTICE.md) records source attribution and handling limits.

## Actor/scorer boundary

An actor scenario contains only the observed prefix, the memory visible at that point, and events already occurred. It has no gold label, future turn, acceptable window, answer, later confirmation, or future memory field. Scorer-only records use a separate schema and storage path. The CLI runs actor and scorer plugins in distinct worker processes: actor IPC contains only one scenario, while scorer IPC contains only its gold sidecar and actor output. Worker environments omit inherited credentials and set `STELLA_HOME` to a marked directory outside the repository. The evaluator rejects unknown fields instead of silently dropping them.

All reports retain total, completed, failed, skipped, and not-applicable counts. Each metric carries its own numerator, denominator, status, and value. An empty denominator is `not_applicable` or `not_run`, never a passing zero.

## Commands

Actor resume fingerprints include the selected actor plugin path alongside the pinned inputs, code commit, dirty-tree digest, protocol, resolved configuration, and seed. Scorer fingerprints include the scorer plugin path and gold hash; changing either plugin rejects resume before reusing results.

Validate frozen adapter output with the exact file hashes recorded when those files were prepared:

```powershell
python -m proactive_eval validate `
  --dataset-id when2speak `
  --scenarios memory/benchmark/_public/proactive_eval/adapted/when2speak-test.jsonl `
  --gold memory/benchmark/_public/proactive_eval/adapted/when2speak-test-gold.jsonl `
  --expected-scenario-sha256 <64-hex> `
  --expected-gold-sha256 <64-hex>
```

For a run, pass the same expected hashes, an isolated home outside the checkout, a run directory outside the checkout or under gitignored storage, and actor/scorer `module:callable` plugins. `--resume` requires the same actor fingerprint and input digest; changed inputs are rejected. An interruption after an external call but before its result checkpoint is recorded as a recovery retry, so possible duplicate calls remain visible.

The Python library's `run_actor_stage` callback is an in-process test seam. Use the CLI worker boundary when running application plugins so scorer gold is not resident in the actor worker.

## B03 PITCH timing audit

Run the scorer-side, turn-window audit with the pinned PITCH file and synthetic opportunity timing profiles:

```powershell
python -m proactive_eval.b03
```

The ignored output is written to `memory/benchmark/_public/proactive_eval/runs/B03/pitch-window-audit.json`. It preserves all 384 candidate IDs and timing outcomes, reports intersection, union, within-group, and `do_not_surface` views, and never sends candidate text or window labels to an actor. Synthetic seconds exercise debounce/TTL ordering only; they are not converted into PITCH elapsed-time labels. The run records the effective debounce, TTL, cooldown, and verification-window constants.

## Readiness

B00 freezes the offline protocol and data fingerprints. It does not certify model behavior, real QQ/WebChat delivery, release payloads, or Windows installation. See the date-stamped B00 report and the task state in `progress.md` for the exact run evidence and remaining gates.
