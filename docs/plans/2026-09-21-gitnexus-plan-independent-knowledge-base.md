# GitNexus Engineering Plan

> Task: 为 Stella 增加同时支持统一维护资料库和共享资料库的独立知识库。
> Evidence verified at commit 2563aaac1f49e9e7e7a01db85f94de842a8f655c; GitNexus index refreshed this session in Docker. Query/impact CLI could not reuse the container-local registry, so graph claims are non-load-bearing and source verification is primary.
> Evidence provenance schema 2; global dirty digest 0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd; cited-path manifest 13 entries; exact generated plan path excluded.

## 1. Objective

[verified] Add an independent knowledge-base subsystem for Markdown, TXT, PDF, DOCX, and selected URLs. Support administrator-maintained libraries and member-contributed shared libraries with ACL, draft/review/publish lifecycle, versioned indexing, hybrid retrieval, bounded evidence injection, citations, and strict isolation from personal memory.

## 2. Current Behaviour

[verified] Memory storage/retrieval is keyed by `group_shared_space`; `memory/schema.py` owns additive migrations and visibility/source fields, while `memory/retriever.py` uses FTS5 over memories. This is a personal-memory boundary and must not become the knowledge-base identity.

[verified] `memory/embeddings.py` supplies an optional embedding client with cache and graceful failure, but no persistent document/chunk index or model-lock metadata.

[verified] Capability execution compresses tool output into `ChatContext.tool_summaries` through `capability/comes/summarizer.py`; this cannot carry cited excerpts. `core/context.py` carries cross-module state and `core/context_budget.py` enforces the 8192-token window.

## 3. Relevant Architecture

[verified] `docs/architecture.md` separates orchestration, capability, memory, and SQLite storage. Knowledge should be a parallel bounded subsystem exposed through a capability/provider boundary, with ingestion/indexing outside the synchronous reply path.

[inferred] Separate knowledge storage is safer than adding document rows to `agent_memory.db`, preventing memory cleanup, promotion, and retention logic from operating on external documents.

## 4. GitNexus Findings

[graph] Docker refresh completed: 12,021 nodes, 28,641 edges, 665 flows. The follow-up CLI could not load its container-local repository registry and FTS was unavailable; no graph-only caller claim is used.

[verified] Source boundaries relevant to implementation are `memory.schema`, `memory.retriever`, `memory.embeddings`, capability hooks/execution, `ChatContext`, and context budgeting.

## 5. Statement-Level PDG Findings

[assumed] No usable PDG slice was obtained. The executor must run fresh impact/PDG on current `ChatContext`, capability hooks, embedding, retrieval, and schema symbols before editing production code.

[verified] Knowledge retrieval must complete before prompt fitting; permission filtering must happen before evidence injection; existing memory promotion must remain separate.

## 6. Proposed Changes

1. Add `knowledge/` domain, repository, ACL, ingestion, chunking, retrieval, and job services. Model KB owner/mode, roles, document versions, source locators, hashes, publish state, and embedding profile/version.
2. Add an isolated knowledge schema/migration path with indexes for KB, ACL subjects, document state/version, and chunk lookup. Never reuse memory tables.
3. Add Markdown/TXT, text-PDF, DOCX, and explicitly selected URL importers. Preserve title, section/page/paragraph locator, source URI, content hash, importer version, and errors. Build a new index before atomically activating a `ready` version.
4. Implement ACL-scoped dense + BM25 retrieval, RRF fusion, deduplication, optional rerank, and hard evidence budgets. Lock each KB to embedding model, dimension, encoding and index versions; changes require rebuild.
5. Managed KBs default to maintainer publication. Shared KBs default to member submission plus maintainer approval; owner may enable direct publish for low-risk libraries. Upload and publish permissions are separate.
6. Add a `knowledge.search` capability/provider with explicit KB selection or authorized session scope. Carry structured `knowledge_evidence` separately from `tool_summaries` and `memories_for_prompt`, then apply context budgeting and citations.
7. Add a consolidation/promotion guard so external document text and citations cannot become personal-memory candidates.
8. Expose import/index state, failures, active version, ACL changes, scores, and citations through service/status APIs; defer full WebUI.

## 7. Implementation Sequence

1. Fresh GitNexus impact/PDG pass; resolve HIGH/CRITICAL risk before edits.
2. Define domain types, ACL evaluation, lifecycle transitions, and repository interfaces.
3. Add isolated schema/migrations and atomic version activation.
4. Implement parsers, chunking, locators, hashes, import jobs, and failure states.
5. Implement persistent BM25/dense indexes, RRF, optional rerank, fingerprints, and previews.
6. Implement managed/shared role APIs and enforce ACL at search and chunk hydration.
7. Register `knowledge.search` and structured evidence; preserve existing tool-summary behavior.
8. Add context-budget integration, citations, and memory-promotion exclusion.
9. Add status/API documentation and run the complete test matrix.

## 8. Test Strategy

- ACL matrix: managed contributor draft, maintainer publish, shared approval/direct-publish, viewer denial, group/space/user grants, private KB unavailable in group chat.
- Lifecycle: duplicate hash, replacement, parse/embedding failure, atomic version switch, archived exclusion.
- Parsers: Markdown/TXT, text-PDF locators, DOCX headings/tables, URL metadata, scanned/unsupported PDF failure.
- Retrieval: exact BM25 term, semantic match, RRF ordering, deduplication, rerank-off, model mismatch rebuild, evidence cap.
- Integration: citations returned only for authorized chunks; evidence fits budget; no memory candidate is produced from evidence.
- Regression: existing memory/capability suites remain green. Verify with `python -m pytest`, `ruff check .`, and `pyright` as configured in `pyproject.toml`.

## 9. Risk and Impact Analysis

- Permission leakage: filter before retrieval and again before chunk hydration.
- Memory contamination: separate context field and explicit consolidation guard.
- Partial index activation: fingerprint profiles and activate complete versions transactionally.
- Prompt growth: enforce evidence count/token limits through context budgeting.
- Import security: bounded, timeout-limited, user-selected URLs; file-size and extraction caps.
- SQLite contention: isolate ingestion transactions/connections from reply reads.
- Compatibility: additive migrations; do not alter memory visibility, source kinds, or cleanup semantics.

## 10. Files Expected to Change

| File | Symbols | Reason |
| ---- | ------- | ------ |
| `knowledge/` (new) | domain, ACL, repository, ingestion, retrieval, jobs | Independent subsystem |
| `capability/` | provider/search adapter | `knowledge.search` |
| `core/context.py` | `ChatContext` | Structured evidence |
| `core/context_budget.py` | budget accounting | Evidence cap |
| `memory/` | migration/promotion boundary | Storage and memory isolation |
| `tests/knowledge/` (new) | domain/import/retrieval/ACL/integration | Coverage |
| `docs/architecture.md` and KB docs | architecture/operations | Document boundaries |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: "Independent managed/shared knowledge bases with ACL, ingestion, hybrid retrieval, citations, and memory isolation."
  acceptance_criteria:
    - "Managed and shared libraries use one model with different default publication policies."
    - "Unauthorized users/groups receive no metadata or excerpts."
    - "Supported imports preserve locators and versions."
    - "Dense + BM25 retrieval uses RRF and bounded cited evidence."
    - "Embedding profile changes require rebuild and incomplete indexes are inactive."
    - "Knowledge evidence cannot become personal memory."
  evidence_provenance:
    schema_version: 2
    head_commit: "2563aaac1f49e9e7e9e7a01db85f94de842a8f655c"
    generated_plan_path: "docs/plans/2026-09-21-gitnexus-plan-independent-knowledge-base.md"
    global_dirty_digest: {algorithm: sha256, canonicalization: "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records", value: "0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd"}
    cited_path_manifest: [{"path":"capability/comes/summarizer.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:d1dda057d2a1f81e990c2034f93a14a0140fdda055b2d2c08280f62025557c5f","index_digest":"sha256:d1dda057d2a1f81e990c2034f93a14a0140fdda055b2d2c08280f62025557c5f","worktree_digest":"sha256:d1dda057d2a1f81e990c2034f93a14a0140fdda055b2d2c08280f62025557c5f","untracked_digest":"absent"},{"path":"capability/hooks.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:62d6b1e32bd9738bd691d9b67c258f9fcdff11b9f471e71051742404346ff20b","index_digest":"sha256:62d6b1e32bd9738bd691d9b67c258f9fcdff11b9f471e71051742404346ff20b","worktree_digest":"sha256:1e3e6cadfb2b6cdea63fbdc6789baa0cae68f205329b375228ab683e77fae7cf","untracked_digest":"absent"},{"path":"core/context.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:115774ed357d50cd475fa9897e7c35e16ec0918afc5ef35ec751976e16b9d2f3","index_digest":"sha256:115774ed357d50cd475fa9897e7c35e16ec0918afc5ef35ec751976e16b9d2f3","worktree_digest":"sha256:8566c07d2c4f0e7644c80d7d568fc1300c95b331b86e1b600d17347335818482","untracked_digest":"absent"},{"path":"core/context_budget.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:4970bd917ddb031cb3b983a02b54e1c7e5b01d2f5193c042606f87609c3ecc26","index_digest":"sha256:4970bd917ddb031cb3b983a02b54e1c7e5b01d2f5193c042606f87609c3ecc26","worktree_digest":"sha256:4970bd917ddb031cb3b983a02b54e1c7e5b01d2f5193c042606f87609c3ecc26","untracked_digest":"absent"},{"path":"docs/architecture.md","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:c3a34d252a607d19934606c758176f39a6f8fa3f75fe8ccc241d724b3487de58","index_digest":"sha256:c3a34d252a607d19934606c758176f39a6f8fa3f75fe8ccc241d724b3487de58","worktree_digest":"sha256:02a6ded57c12917c94575e22cda9ac219c3588b241571d2511790d9131ce8c87","untracked_digest":"absent"},{"path":"docs/capability-system.md","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:452419508dbec0496ea223affe0efe1fe187c63883b326a4143d267c1c618454","index_digest":"sha256:452419508dbec0496ea223affe0efe1fe187c63883b326a4143d267c1c618454","worktree_digest":"sha256:75c5bbe4732c790c2a112ee477958901a3f3db876ae567bec8741c26eee5b2fa","untracked_digest":"absent"},{"path":"memory/embeddings.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:8f323c85e94757fe79770b4b00f338fddae4281fece992e9ef412bce41194249","index_digest":"sha256:8f323c85e94757fe79770b4b00f338fddae4281fece992e9ef412bce41194249","worktree_digest":"sha256:a86890ec780696c5abc766183d21c79449837913c9c2bd7aede2a19c2c7d68a2","untracked_digest":"absent"},{"path":"memory/retriever.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:8ed809ea232638e45b84e9a87c3d4bb1ab1b147cc695da3369c0085d09ef21a5","index_digest":"sha256:8ed809ea232638e45b84e9a87c3d4bb1ab1b147cc695da3369c0085d09ef21a5","worktree_digest":"sha256:7b8319e05efb04a936aaccfd7936766272c04245ccfd8ec09f7e9c08ed1cf3e0","untracked_digest":"absent"},{"path":"memory/schema.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:6ae50e678d229df3090dfba16878fe5ae89e9ab70c85c711013a7099f78c226f","index_digest":"sha256:6ae50e678d229df3090dfba16878fe5ae89e9ab70c85c711013a7099f78c226f","worktree_digest":"sha256:59f885df0c9c6a8f4afbfaa2d4168e0ed643882aa4e68c788ceac581d9d9e4a9","untracked_digest":"absent"},{"path":"pyproject.toml","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:15f9425125da784c02d267114ccf47ddc02143100b16d1b72258bdf8d053c655","index_digest":"sha256:15f9425125da784c02d267114ccf47ddc02143100b16d1b72258bdf8d053c655","worktree_digest":"sha256:f17308657cce1b51c8763d2404002bbb9f9152387c401e9912fa659f86b7ec2a","untracked_digest":"absent"},{"path":"tests/conftest.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:11235f7aa5917857eb2abdf4334ca5fae50647b79a9f6659c8c21a00c578dc85","index_digest":"sha256:11235f7aa5917857eb2abdf4334ca5fae50647b79a9f6659c8c21a00c578dc85","worktree_digest":"sha256:11235f7aa5917857eb2abdf4334ca5fae50647b79a9f6659c8c21a00c578dc85","untracked_digest":"absent"},{"path":"tests/test_access_semantics.py","object_kind":{"head":"regular","index":"regular","worktree":"regular","untracked":"absent"},"state":"clean","rename_from":null,"rename_to":null,"head_digest":"sha256:c2d78ed515ae6625722039d297afb5924fae28227bfbd49b1c3a74d4f6962f44","index_digest":"sha256:c2d78ed515ae6625722039d297afb5924fae28227bfbd49b1c3a74d4f6962f44","worktree_digest":"sha256:c2d78ed515ae6625722039d297afb5924fae28227bfbd49b1c3a74d4f6962f44","untracked_digest":"absent"}]
  primary_symbols:
    - {symbol: ChatContext, file: core/context.py, role: runtime evidence carrier}
    - {symbol: EmbeddingService, file: memory/embeddings.py, role: embedding client pattern}
    - {symbol: memory schema/migrations, file: memory/schema.py, role: migration convention}
    - {symbol: memory retrieval, file: memory/retriever.py, role: existing FTS boundary}
  related_symbols:
    - {symbol: tool_summaries, relationship: capability hooks, relevance: keep separate from evidence}
    - {symbol: fit_prompt_to_window, relationship: called before LLM, relevance: evidence budget}
  execution_path: ["Resolve principals and authorized KBs", "Search ready chunks with dense/BM25", "Fuse, deduplicate, cap evidence", "Attach citations and fit prompt", "Answer without memory promotion"]
  pdg_constraints: []
  architectural_patterns: ["Additive migrations in memory/schema.py", "Provider boundary in capability/providers/registry.py", "Bounded prompt in core/context_budget.py"]
  files_to_modify: ["knowledge/", "capability/", "core/context.py", "core/context_budget.py", "memory/", "tests/knowledge/", "docs/"]
  tests: ["tests/knowledge/: ACL, lifecycle, parsers, ranking, citations, isolation", "tests/test_access_semantics.py: memory semantics unchanged"]
  verification_commands: ["python -m pytest", "ruff check .", "pyright"]
  risks: ["permission leakage", "memory contamination", "partial index activation", "prompt growth", "unsafe URL fetching"]
  assumptions: ["Separate SQLite knowledge storage is acceptable; verify config convention", "URL importer is explicit and non-recursive", "OCR is deferred"]
  open_questions: ["DB path/vector backend", "evidence limits", "first management surface", "group_id versus group_shared_space principal grants"]
  avoid: ["Do not reuse agent_memory.db tables", "Do not reuse group_shared_space as KB identity", "Do not inject full documents", "Do not retrieve drafts/unauthorized chunks", "Do not auto-promote evidence", "Do not edit production symbols before impact/PDG"]

## 12. Assumptions and Open Questions

- [assumed] Separate SQLite knowledge storage is acceptable; verify deployment/config conventions first.
- [assumed] Shared libraries default to review, with owner-controlled direct publish.
- [assumed] URL ingestion is explicit and bounded; recursive crawling and OCR are deferred.
- [open] Decide whether group grants target real `group_id`, resolved `group_shared_space`, or both as distinct principals.
- [open] Choose the first management surface and evidence budget defaults.
- Deferred: WebUI/ChatUI, recursive crawlers, OCR, external vector databases, automatic memory promotion, MCP knowledge providers.

## 13. Definition of Done

- Managed and shared KBs can be created, granted, populated, reviewed, published, versioned, archived, and queried.
- Unauthorized users/groups receive no metadata or excerpts.
- Every excerpt has a stable citation and locator.
- Hybrid retrieval, embedding fingerprints, version activation, and parser failures are tested.
- Evidence stays within context budget and remains separate from memory retrieval/promotion.
- Import/index failures, ACL changes, and active versions are observable.
- Existing memory and capability tests pass unchanged.

