# Independent Knowledge Base

[中文](knowledge-base.md) | English

The knowledge subsystem is available in Stella 6.1.0, including WebUI administration.
Recursive crawling, OCR, external vector databases, automatic promotion into memory,
and an MCP knowledge provider remain deferred.

## 1. Purpose

`knowledge/` stores formal reference material separately from personal and group
memory. Administrators maintain managed libraries; members contribute to shared
libraries. Imports support Markdown, TXT, text-based PDF, DOCX, and explicitly
selected URLs. Access control, draft/review/publication states, versioned indexes,
hybrid retrieval, and bounded citations apply throughout.

## 2. Isolation contracts

1. **Storage:** `KNOWLEDGE_DB_PATH` defaults to
   `<STELLA_HOME>/knowledge/knowledge.db`. Its tables, indexes, and migrations are
   independent of `agent_memory.db`. Memory cleanup, promotion, retention, and
   space merging cannot alter imported documents.
2. **Context:** `tool_summaries`, `knowledge_evidence`, and `memories_for_prompt`
   have separate rendering and budgets. `KNOWLEDGE_EVIDENCE_MAX_ITEMS` and
   `KNOWLEDGE_EVIDENCE_MAX_TOKENS` limit evidence before rendering; the overall
   context-window fitter provides an additional final limit.
3. **Promotion:** consolidation reads original chat rows from `group_messages`.
   Retrieved evidence is never inserted there. `knowledge/isolation.py` checks
   for evidence copied into memory fields, logs an error, and clears that copy.

## 3. Domain model

```text
KnowledgeBase (managed/shared, owner, direct_publish, embedding fingerprint)
  ├── KBGrant: user/group/space principal → viewer/contributor/maintainer
  └── KBDocument: title, source, content hash, lifecycle, active version
        └── KBDocumentVersion: pending → ready → active → superseded/failed
              └── kb_chunk: locator + vector; kb_chunk_fts: FTS5 index
```

Documents follow `draft → in_review → published → archived`. Publication requires
an index-complete version; republishing an already published document is supported.
`knowledge/store.py` activates a version in one transaction: supersede the old
version, activate the ready version, advance the document pointer, and mark it
published. An incomplete index cannot become externally visible.

The first vectors lock the library fingerprint to `model / dim / encoder /
index_version`. A changed fingerprint disables dense retrieval and marks the
library `needs_rebuild`; BM25 remains available until rebuilding completes.

## 4. Permissions

The owner is `kb.owner_user_id`. Grants apply to `user:<QQ ID>`, `group:<group ID>`,
or `space:<shared space>`, with the highest matching role taking precedence.
A group grant and a space grant are distinct decisions.

| Operation | Managed library | Shared library |
| --- | --- | --- |
| Search published documents | Viewer or above | Viewer or above |
| Submit documents | Maintainer or above | Contributor or above |
| Review/publish | Maintainer or above | Maintainer or above |
| Manage grants | Maintainer or above | Maintainer or above |
| Archive library/change direct publication | Owner only | Owner only |

Upload permission does not grant publication permission. Maintainers in managed
libraries publish on upload. Shared libraries normally require review; the owner
can enable `direct_publish` as an explicit library policy.

Private libraries without group or space grants are excluded from group-chat
retrieval because the reply is visible to the whole group. The service first
selects authorized libraries; an empty set stops before querying data. Retrieval
SQL additionally filters by published state and active version. Explicit requests
for unauthorized libraries populate `denied_kb_ids` without exposing metadata.

## 5. Import

`knowledge/service.py` submits work to the ingestion worker thread; parsing never
runs synchronously in the reply path.

1. Parse Markdown by ATX headings, TXT by paragraph, PDF by page, or DOCX by
   headings with flattened tables. PDF and DOCX use optional `pypdf` and
   `python-docx`; missing dependencies produce actionable failures. Scanned PDF
   fails because OCR is deferred. URL import fetches one page with timeout,
   byte, and content-type limits. Failures raise `ParseError` and are persisted.
2. Pack complete paragraphs into chunks targeting about 500 characters, with
   a hard limit of 900. Chunks inherit section locators.
3. Normalize line endings and compute SHA-256. Duplicate content in the same
   library is ignored; reimporting the same title creates a replacement version.
4. Write chunks, FTS rows using the shared tokenizer in `knowledge/fts.py`, and
   optional vectors. Mark the version ready only when counts agree.
5. Activate imports eligible for direct publication. Other submissions remain
   `in_review` for a maintainer.
6. Record status and failure reasons in `kb_import_job` for diagnostics.

## 6. Retrieval and evidence

FTS5 BM25 uses Chinese two/three-character sliding tokens. Dense retrieval uses
cosine similarity over authorized active versions. Reciprocal rank fusion
(`KNOWLEDGE_RRF_K`), near-duplicate collapse, and optional injected reranking
combine the results. Reranking is disabled by default.

Unavailable FTS5 falls back to dense retrieval; unavailable embeddings or a
fingerprint mismatch fall back to BM25. Retrieval isolates failures from chat.
`core/runtime/turn_service.py` fits evidence to its item/token budget and renders
numbered references with title, section, paragraph, and library name after tool
summaries and before the current input. With no evidence, no evidence section is
added.

## 7. Capability integration

With `KNOWLEDGE_ENABLED=true` (the default),
`capability/adapters/knowledge.py` registers the native `KnowledgeBackend` and
`knowledge.search` capability. Examples describe user questions; Level 0 keywords
are deliberately absent to avoid forcing retrieval on a literal false positive.

The model supplies `query` and `kb_ids`, while the trusted chat event supplies the
ACL principal. Model output cannot impersonate another user. Hooks place the
structured excerpts in `ctx.knowledge_evidence`, outside tool summaries and
direct-reply text.

## 8. Configuration

| Key | Default | Meaning |
| --- | --- | --- |
| `KNOWLEDGE_ENABLED` | `true` | Register and enable the subsystem |
| `KNOWLEDGE_DB_PATH` | `<home>/knowledge/knowledge.db` | Independent database |
| `KNOWLEDGE_SEARCH_TOP_K` | `8` | Candidates per retrieval channel |
| `KNOWLEDGE_RRF_K` | `60` | Fusion constant |
| `KNOWLEDGE_EVIDENCE_MAX_ITEMS` | `4` | Evidence item limit |
| `KNOWLEDGE_EVIDENCE_MAX_TOKENS` | `600` | Evidence token limit |
| `KNOWLEDGE_EVIDENCE_MAX_CHARS` | `700` | Characters per excerpt |
| `KNOWLEDGE_RERANK_ENABLED` | `false` | Optional injected reranker |
| `KNOWLEDGE_EMBEDDING_BASE_URL` / `KNOWLEDGE_EMBEDDING_MODEL` | Empty | Inherit the memory embedding service |
| `KNOWLEDGE_URL_TIMEOUT` / `KNOWLEDGE_URL_MAX_BYTES` | `15` seconds / `2097152` bytes | URL fetch limits |
| `KNOWLEDGE_IMPORT_MAX_BYTES` | `20971520` bytes | Import size limit |

## 9. Administration

WebUI → Knowledge Base (`/#/knowledge-base`) provides library creation, document
import, retrieval testing, grant management, and archiving through
`/api/v1/knowledge-bases`. `webui/services/kb.py` uses the existing service and
administrator authentication; chat retrieval still enforces chat-principal ACLs.

```bash
python -m knowledge.schema --dry-run
python -m knowledge.schema
```

The knowledge schema is independently versioned (`SCHEMA_VERSION=1`).
`knowledge.service.get_service().kb_status(kb_id, principal)` exposes fingerprint,
versions, import jobs, and grants; `list_accessible_kbs(principal, in_group=)`
lists accessible libraries. Failed jobs survive restart.

## 10. Verification

`tests/knowledge/` covers domain models, ACLs, lifecycle, evidence isolation,
atomic activation, FTS consistency, parsers, idempotent import, replacements,
failure persistence, BM25/dense/fusion, fingerprint rebuilding, evidence limits,
deduplication, and capability wiring. `tests/webui/` covers the management API.
See the [configuration reference](configuration.en.md) and
[architecture](architecture.en.md) for the surrounding runtime.
