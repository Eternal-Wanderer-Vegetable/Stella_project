# Anthropic-style Skills and Controlled Sandboxes

[中文](skills.md) | English · [Documentation](../README.en.md)

A skill consists of `SKILL.md` and optional `scripts/` and `references/`.
Selection sees only names and descriptions. The body is loaded after a match;
script and file actions execute through a controlled sandbox.

Skills are **disabled by default** (`SKILLS_ENABLED=false`). The only execution
mode is `sandbox`: unavailable isolation fails closed without executing arbitrary
host code. Skills are independent of capabilities: they do not enter the
`CapabilityRegistry` provider graph, compete in routing, or consume Comes' tool
budget.

## Sources and precedence

| Source | Location | Trust |
| --- | --- | --- |
| Workspace | `<SANDBOX_WORKSPACE_ROOT>/<conversation>/skills/<name>/SKILL.md` | Untrusted |
| User | `<STELLA_HOME>/data/skills/<name>/SKILL.md` | Managed |
| Plugin | `<plugin>/skills/<name>/SKILL.md` | Managed |
| Built-in | `assets/skills/<name>/SKILL.md` | Controlled |

Names resolve in order **workspace > user > plugin > built-in**; same-layer
conflicts use deterministic path ordering. The front-matter name must match the
directory name.

## Manifest

```markdown
---
name: doc-lookup
description: Find and quote project documentation when a user asks about documented behavior.
license: AGPL-3.0
---

# Instructions for the executor

Follow these steps…
```

Only scalar allowlisted front-matter fields are accepted: required `name` and
`description`, optional `license` and `compatibility`. Permission declarations
such as `allowed-tools` are ignored: source determines trust, and skills cannot
authorize themselves. Parsing uses `yaml.safe_load` and discards composite values.
Descriptions should explain purpose and triggering situations within about
1,000 characters; name and description drive selection.

## Progressive disclosure

```text
Scan front matter → atomic catalog snapshot
  → name/description selection (optional embeddings) → metadata candidates
  → load matched body (SKILLS_BODY_MAX_CHARS limit)
  → planning model emits allowlisted JSON actions
  → each action runs in a separate restricted container
  → bounded summary + ArtifactRef returns to the chat runtime
```

Startup and selection never read bodies, scripts, or references. Bodies are
untrusted instructions and cannot change sandbox policy. Planning excludes
Stella's persona, long-term memory, and complete tool list. Only bounded summaries
and workspace-relative artifact paths enter the prompt; raw stdout/stderr belong
in the audit log. A skill failure isolates its result and allows normal reply
generation to continue.

## Sandbox actions

The five actions are `run_shell`, `run_python`, `read_file`, `write_file`, and
`list_files`. Paths must be workspace-relative POSIX paths: absolute paths,
`..`, and symbolic links are prohibited.

With `SANDBOX_BACKEND=docker`, every action gets an independent container with
numeric non-root UID 65532, a read-only root filesystem, `no-new-privileges`, and
all capabilities dropped. CPU, memory, process, timeout, and output limits come
from `SandboxLimits`/`SANDBOX_*`; callers may narrow limits but cannot widen them.
The workspace is mounted at `/workspace` and skill sources are read-only. The
project root, `.env`, memory databases, plugin directories, Docker socket, and
host user directories are never mounted. Containers are removed after use;
timeouts terminate and audit them.

Networking defaults to `NetworkMode=none`. In-process execution rejects sandbox
mode with networking enabled because enforced domain allowlists require an
external runner. Do not mount `/var/run/docker.sock` into the Stella container;
use a sidecar/proxy endpoint through `DOCKER_HOST`.

The in-process Windows runner does not accept named-pipe endpoints. Keep
`SANDBOX_BACKEND=disabled` for local development or configure a supported remote
runner. The integration-test fixture can bridge the local named pipe to TCP:

```bat
python tests/sandbox/_npipe_bridge.py --port 2377
set STELLA_DOCKER_TEST_ENDPOINT=http://127.0.0.1:2377
python -m pytest tests/sandbox/test_docker_integration.py -v
```

The integration suite skips when its daemon is unavailable.

## Configuration

See the [configuration reference](../reference/configuration.en.md).

| Goal | Settings |
| --- | --- |
| Browse only | `SKILLS_ENABLED=true`; execution stays `disabled` |
| Execute sandboxed actions | `SKILLS_ENABLED=true`, `SKILLS_EXECUTION_MODE=sandbox`, `SANDBOX_BACKEND=docker` |
| Semantic selection | `SKILLS_EMBEDDING_ENABLED=true`; uses `MEMORY_EMBEDDING_*` with a separate cache |

## Authoring

1. Use lowercase letters, digits, and `._-` in names; describe the trigger clearly.
2. Organize the body into precise steps and boundaries.
3. Put scripts in `scripts/` and reference material in `references/`. They become
   visible only after selection; per-file and total byte limits exclude oversized
   content from indexing.
4. Start with `assets/skills/doc-lookup/`, which lists files, reads documents, and
   quotes text with sources.
5. Requests to read `.env`, memory databases, or paths outside the workspace fail
   path/action checks. Non-allowlisted actions are discarded and audited;
   front-matter permission claims are ignored.

## Administration and diagnostics

WebUI → Extensions → Skills provides listing, body editing, ZIP upload, and
deletion through `/api/v1/skills`. The service restricts editing/deletion to
user/workspace sources; browsing a built-in or plugin skill does not grant write
access to it.

The loopback-restricted `/stella/status` response includes catalog version,
source counts, quarantine counts, recent errors, and sandbox status. It contains
policy summaries rather than bodies and detailed paths. Discovery, selection,
loading, policy rejection, startup, timeout, truncation, and cleanup appear in
`logs/skills_audit.jsonl` with sensitive values redacted.

If an installed skill never appears, inspect name/description validity and
`SKILLS_MANIFEST_MAX_BYTES`, then quarantine counts and startup logs. Unavailable
execution usually means a disabled backend or unreachable daemon; inspect
`skills.sandbox.reason`. Plugin reload refreshes only that plugin's source;
failure retains the old snapshot with a warning, so reload again after fixing it.
