# Configuration Reference

[中文](configuration.md) | English

> Note: This version of the document was translated from the Chinese version by GPT-5.6 luna.

**Regular users (Release package)**: For first-time setup, use the `Configuration` page in `Stella.exe`: enter the group number, connection method, address, and model ID, then save to write them to `.env` in the project root. The model list can be read automatically from the local LM Studio, or entered manually.

**Developers**: Use the wizard `python -m deploy init`: answer only 5 required items (group number, connection method, address, and two model IDs). The wizard retrieves the model list from LM Studio and lets you choose by number, avoiding the common mistake of typing a complete ID but omitting the `google/` prefix. It generates `.env` line by line from `.env.example`, preserving the template comments exactly, especially the cross-NapCat OneBot connection instructions. You can also use `--answers` to save and reuse answers.

This is the complete configuration reference for tuning the system.

Configuration is centralized in [`config/settings.py`](../config/settings.py), which reads `.env` from the project root and exports module-level constants. Tune the system without changing this file or the business code.

```bash
cp .env.example .env
```

Depending on `ENVIRONMENT`, an environment override file can also be loaded: `dev` / `development` → `.env.dev`, or `prod` / `production` → `.env.prod` (same-named entries override `.env`).

Boolean values accept `true` / `1` / `yes` (case-insensitive); everything else is treated as false.

## Minimal Working Configuration

```env
ALLOWED_GROUPS=123456789
LM_STUDIO_BASE_URL=http://127.0.0.1:1234
LM_STUDIO_MODEL=your-chat-model
CONSOLIDATION_LM_STUDIO_MODEL=your-small-model
```

For a fully online deployment (without running local LM Studio), replace the minimum set with endpoints and roles. Local model IDs can be left completely empty. See [Model Services · Endpoint and Role](#endpoint-and-role-two-layer-configuration):

```env
ALLOWED_GROUPS=123456789
LLM_ENDPOINT_ONLINE_CHAT_BASE_URL=https://api.example.com
LLM_ENDPOINT_ONLINE_CHAT_API_KEY=sk-chat-key
LLM_ENDPOINT_ONLINE_CHAT_MODEL=vendor/chat-model
LLM_ENDPOINT_ONLINE_MEMORY_BASE_URL=https://api.example.com
LLM_ENDPOINT_ONLINE_MEMORY_API_KEY=sk-memory-key
LLM_ENDPOINT_ONLINE_MEMORY_MODEL=vendor/cheap-model
LLM_ROLE_CHAT_ENDPOINT=ONLINE_CHAT
LLM_ROLE_ROUTER_ENDPOINT=ONLINE_CHAT
LLM_ROLE_PLUGIN_ENDPOINT=ONLINE_CHAT
LLM_ROLE_COMPACT_ENDPOINT=ONLINE_MEMORY
LLM_ROLE_CONSOLIDATION_ENDPOINT=ONLINE_MEMORY
LLM_ROLE_EXTRACT_ENDPOINT=ONLINE_MEMORY
# Optional: use a stronger model for Stage 2 extraction on the same endpoint (role-level override; otherwise the endpoint model is used)
LLM_ROLE_EXTRACT_MODEL=vendor/strong-model
```

The model ID is set on the **endpoint**, so every role pointing to that endpoint uses it by default. There is no need to repeat the same string across all six roles. The two keys must be different; see [Why Two Online Keys Are Required](#why-two-online-keys-are-required). In the installer, selecting the `Fully online (dual key)` preset under `Configuration → Model Services` is equivalent to the block above.

---
## QQ Groups and Paths

| Configuration | Default | Description |
|---|---|---|
| `ALLOWED_GROUPS` | empty | Group numbers allowed to receive responses, comma-separated. **An empty value means no group receives responses** |
| `STELLA_HOME` | auto-detected | **User data root directory** (see below). It must be set as a real environment variable and cannot be written in `.env` |
| `SYSTEM_PROMPT_PATH` | `<data directory>/system_prompts/default.md` | System prompt file (persona). Uses the copy shipped with the Release package when absent from the data directory |
| `DB_PATH` | `<data directory>/memory/agent_memory.db` | SQLite database |
| `EXTENSIONS_DIR` | `<program directory>/extensions/` | Directory scanned for automatic extension loading (program code, replaced with each version) |
| `MEMORY_BENCHMARK_DIR` | `<program directory>/memory/benchmark` | Benchmark case directory |

Path-type settings are resolved as absolute paths when set in `.env`.

### Two Root Directories: Program and Data

Since 2026-08-27, user data can be stored outside the installation directory, so **an upgrade only needs to replace the program directory**:

| | Contents | During upgrade |
|---|---|---|
| Program directory (`PROJECT_ROOT`) | Code, `.env.example`, `extensions/`, default personas and capability configuration shipped with the Release package, `runtime/` | Replaced as a whole by the new version |
| Data directory (`STELLA_HOME`) | `.env`, `memory/` (memory database and ledger), `config/spaces/`, `system_prompts/`, `data/plugins`, `logs/`, and so on | **Untouched** |

The resolution order (the criteria are in `config/home.py`, which **does not read `.env`**; otherwise there would be a circular dependency: “read `.env` to find out where `.env` is”):

1. Environment variable `STELLA_HOME`;
2. Machine-level pointer file (Windows `%LOCALAPPDATA%\Stella\home.txt`, other platforms `~/.config/stella/home.txt`). It is outside the program directory, so any newly extracted program can immediately attach to the old data;
3. If `.env` or `memory/agent_memory.db` exists in the installation directory → **use it in place** (legacy layout; installations from 3.0.0 and earlier continue to work without changes);
4. If `StellaData/` exists in the installation directory → use it (**portable mode**: program and data are self-contained and can be moved together. This is the path used by the development repository);
5. If none of the above exists → use `StellaData/` **beside** the installation directory.

**Why the default is “beside” rather than “inside”**: the program directory is the directory that is replaced as a whole during upgrades and that users may delete as an “old version.”
Putting data there by default would turn the perfectly natural cleanup action of “deleting the old version folder” into irreversible data loss.
Therefore the default is outside; only when a user **explicitly** creates a `StellaData/` subdirectory is a self-contained layout assumed
(in that case, import or back up the data before upgrading).

The Release package therefore **does not contain an inner `Stella/` directory**: after extracting the zip, `Stella-v3.1.0-win64/` is the program directory and the data is placed beside it. An extra nesting level would turn “beside” into “inside the version folder,” which is the v3.1.0 defect.

The relative layout inside the data directory is exactly the same as in the old installation, so the “legacy layout” is simply the special case where the data directory happens to equal the installation directory.
Use `python -m deploy paths` to view the current resolution result (`deploy doctor` also displays it).

Files that ship with the Release package but may also be changed by users (`system_prompts/default.md`, `config/capabilities/*.toml`) are resolved with data-directory priority, falling back to the copy shipped in the program directory. New defaults arrive with upgrades without overwriting user changes.

## Logs

**All runtime logs go to `LOG_DIR` (default `logs/`).** Change this one variable to move all logs; individual files can still be overridden separately with their respective `*_PATH` settings. Writers create the directory as needed, so it does not need to be created manually.

| Configuration | Default | Contents |
|---|---|---|
| `LOG_DIR` | `logs/` | Root directory for all logs |
| `STELLA_JSON_LOG_PATH` | `logs/stella.jsonl` | Structured log for programs to read (the GUI log panel, `deploy status`) |
| `THOUGHT_LOG_PATH` | `logs/stella_thought_logs.md` | Thought/decision log: complete prompt, raw output, routing decision, and tool result for each round |
| `CONSOLIDATION_LOG_PATH` | `logs/memory_consolidation_log.md` | Runtime summary and original LLM output for each memory-consolidation batch |
| `MEMORY_COMPRESS_LOG_PATH` | `logs/memory_compressor_log.md` | Merge, atomization, and archive counts for each memory compression |
| `BOOT_DIAG_LOG_PATH` | `logs/boot_debug.log` | Startup diagnostics: plugin discovery and loading, capability assembly, and prototype warm-up. **Cleared and rewritten on every startup** |

The same directory also contains `logs/stella.pid` (`deploy start --detach` writes the process ID there; it is not a log).

> **Only `stella.jsonl` has rotation and retention policies** (10 MB rotation, 5 retained files, provided by loguru). The three Markdown logs and `boot_debug.log` are appended without a size limit. `boot_debug.log` is cleared on every startup and therefore does not grow; the other three grow indefinitely (in testing, the thought log was about 3.5 MB after one month). Clean them periodically if needed, or point `LOG_DIR` to a location with its own cleanup policy.

> Before 2026-08-25, these files were scattered in the project root (`stella_thought_logs.md`, etc.), making troubleshooting require searching through source files and requiring another `.gitignore` entry for every new log. After the migration, `.gitignore` only needs one `logs/` entry. The old `MEMORY_COMPRESS_LOG_FILENAME` is deprecated (it is a **filename**, not a path, and could only be placed in the project root); use `MEMORY_COMPRESS_LOG_PATH` instead. Leaving the old key in `.env` produces no error but has no effect; `python -m deploy doctor` reports it.

## Shared Group Spaces

Multiple QQ groups can belong to the same **shared group space**, sharing user profiles, long-term memories, and persona. The state of the current conversation remains isolated by the actual QQ group.

### Two Layers of Ownership

| Data | Owner | Reason |
|---|---|---|
| Message tail, consolidation checkpoint, short-term topics, session compaction | **QQ group** | Mixing groups could make the Bot answer a conversation from group B in group A |
| Mute switch, proactive @ quota | **QQ group** | The level of interruption is specific to each group |
| User profile, long-term memory, atomic facts | **Shared space** | The same person has one body of knowledge in the same space |
| Persona (system prompt), speaking strategy | **Shared space** | The same persona should have the same behavior |

### Configuration

Space configuration is **not in `.env`**. It consists of TOML files under `config/spaces/`, where the **filename is the space name**:

```toml
# config/spaces/casual.toml —— space name is "casual"
qq_groups = [123456789, 987654321]
```

Only `qq_groups` is currently parsed. Fields such as `persona` and `[proactive]` are reserved for future persona grouping and group-level configuration and are currently ignored.

### Implicit Spaces

Groups not included in any TOML file are **automatically assigned** a space name (`space_1` / `space_2` …), persisted in `.space_assignments.json` under the database directory. A single-group deployment works with zero configuration.

The numbers must be persisted rather than calculated on demand. If they were based on the index after sorting group numbers, adding a new group with a smaller number would shift every number, silently misassigning existing memories.

### Renaming and Merging

When an already-running group is changed from automatically assigned `space_1` to explicit `casual`, **historical memories remain under `space_1`**
(renaming does not follow automatically). The program emits a warning and provides a command:

```bash
python -m deploy space-merge --from space_1 --to casual --dry-run   # preview first
python -m deploy space-merge --from space_1 --to casual
```

It rewrites all space-owned tables (including `long_term_memories`, whose column is still named `group_id`), rebuilds the FTS index, updates the ledger, and, when primary keys collide in `user_profiles`, keeps the copy with more interactions (conflicts are written to the report). A backup is created automatically before the operation.

The absence of **“automatically follow a configuration rename at startup”** is deliberate: merging can collide on profile primary keys, requires explicit merge semantics, and is **irreversible**. After a merge, recovery is possible only through the `origin_group_id` provenance column or a backup. Silently triggering a cross-group profile merge because a user changed one line of TOML has disproportionate risk, so users should still **choose the space name before accumulating production memories**.

### Conflict Handling

If the same group appears in multiple TOML files, the first file in filename order wins and an error is logged. Silently taking the later file could place memories in different spaces across two startups, a corruption that is extremely difficult to discover afterward.

## Model Services

### Endpoint and Role: Two-Layer Configuration

Stella's model configuration has two layers:

- **Endpoint** = one OpenAI-compatible service: address, API key, kind, **default model**, concurrency gate, and timeout. It is both the unit that owns an API key and the unit that owns a queueing gate.
- **Role** = one concrete call: which endpoint to use, temperature, max_tokens, and an **optional** model override.

The model ID belongs on the endpoint rather than being repeated on every role. One endpoint normally corresponds to one provider's model list, so “switch provider” should require changing only one place.

There are 4 endpoint slots × 6 roles. A combination such as “chat online, consolidation local” therefore only changes a few `LLM_ROLE_*_ENDPOINT` settings; it requires no code changes and no provider-specific adapter.

The installer's `Configuration → Model Services` section is the graphical interface for these two layers (endpoint cards + role matrix + three one-click presets). Editing `.env` manually is equivalent to using the GUI. **Slot names and role names are statically declared**: `deploy/env_schema.py` scans literal `_env*("KEY", …)` calls in `config/settings.py` with the AST to generate the GUI form; dynamically constructed key names do not appear in the interface.

### Endpoint

Keys have the form `LLM_ENDPOINT_<SLOT>_<FIELD>`. Fields are `BASE_URL` / `API_KEY` / `MODEL` / `KIND` / `CONCURRENCY` / `TIMEOUT`.

| Slot | Purpose | Default `KIND` | Default `CONCURRENCY` | Default `TIMEOUT` |
|---|---|---|---|---|
| `LOCAL` | Local LM Studio | `local` | `1` | `120.0` |
| `ONLINE_CHAT` | Online provider · chat-generation domain | `online` | `4` | `120.0` |
| `ONLINE_MEMORY` | Online provider · memory domain | `online` | `2` | `120.0` |
| `EXTRA` | Spare slot / second local instance | `local` | `1` | `120.0` |

- `MODEL` is the default model ID for the slot; every role assigned to this slot uses it (a role can still override it; see the next section).
- `KIND` has only two values, `local` / `online`; it is a criterion, not a comment. An `online` endpoint without an API key, or one whose assigned roles ultimately have no model available, is classified as **error** by `registry.validate()` (`python -m deploy doctor` reports it). The GUI endpoint cards **do not provide a control for this field**; the badge in the card header only shows the result. The two `ONLINE_*` slots are fixed as `online`; `LOCAL` and `EXTRA` are inferred from the address (`127.*` / `10.*` / `192.168.*` / `172.16-31.*` / `localhost` / a bare hostname / empty means `local`, everything else means `online`) and the inferred value is saved. Manual `.env` edits can use any value, but the next GUI save overwrites it with the inferred value. If your deployment is a relay gateway running at `127.0.0.1` but billed by an upstream provider, put it in the two online cards instead of changing the local card's kind. Address-based inference must classify a local address with real billing as local, which would be wrong.
- `CONCURRENCY` is the slot gate's concurrency limit, with strict FIFO serialization within a slot. Local LM Studio **does not queue**; concurrent requests only slow one another down and make attribution difficult, so local slots remain at `1`. Online endpoints can be increased to the concurrency allowed by the provider.
- `TIMEOUT` is the timeout for one request. It is **not the same as `LLM_TIMEOUT`**, which is the full-round response budget in `core/pipeline.py`.

Leaving the address and key for `LOCAL` and `EXTRA` empty inherits the old keys, so **an unmigrated `.env` behaves exactly as before the upgrade** and requires no manual migration:

| New key | Inherited when empty |
|---|---|
| `LLM_ENDPOINT_LOCAL_BASE_URL` | `LM_STUDIO_BASE_URL` |
| `LLM_ENDPOINT_LOCAL_API_KEY` | `LM_STUDIO_API_KEY` |
| `LLM_ENDPOINT_EXTRA_BASE_URL` | `CONSOLIDATION_LM_STUDIO_BASE_URL` (which itself inherits `LM_STUDIO_BASE_URL`) |
| `LLM_ENDPOINT_EXTRA_API_KEY` | `CONSOLIDATION_LM_STUDIO_API_KEY` |

`MODEL` does not use this inheritance. Instead, when empty, each role falls back to its own old key (see the resolution order below). When `LLM_ENDPOINT_LOCAL_MODEL` is empty, roles bound to `LOCAL` continue to use `LM_STUDIO_MODEL` / `ASTRBOT_LLM_MODEL` / `MEMORY_EXTRACT_LM_STUDIO_MODEL` respectively, exactly as before; filling it means “use this one model for the entire local slot,” overriding those old keys. The model ID input on the GUI's local and spare cards writes the old keys (`LM_STUDIO_MODEL` / `CONSOLIDATION_LM_STUDIO_MODEL`); `LLM_ENDPOINT_LOCAL_MODEL` / `LLM_ENDPOINT_EXTRA_MODEL` remain in advanced configuration as escape hatches.

> In a purely local deployment, `EXTRA` and `LOCAL` point to the same address. Its purpose is only to provide consolidation with an **independent gate**: consolidation is a long-running task, and sharing a gate with chat would make @ replies wait behind it.

### Role

Keys have the form `LLM_ROLE_<ROLE>_<FIELD>`. Fields are `ENDPOINT` / `MODEL` / `TEMPERATURE` / `MAX_TOKENS` / `FALLBACK_ENDPOINT`.

| Role | Function | Default endpoint | Default temperature | Default max_tokens |
|---|---|---|---|---|
| `CHAT` | Main model for replying to group members, prioritizing quality | `LOCAL` | `0.7` | `2000` |
| `ROUTER` | Decides whether a message should receive a reply, a binary task | `LOCAL` | `0.7` | `2000` |
| `PLUGIN` | LLM borrowed by third-party plugins | `LOCAL` | inherits `ASTRBOT_LLM_TEMPERATURE` | inherits `ASTRBOT_LLM_MAX_TOKENS` |
| `COMPACT` | Session compaction: compresses earlier conversation into a recap | `LOCAL` | `0.3` | `0` (= `SESSION_SUMMARY_MAX_TOKENS × 3`) |
| `CONSOLIDATION` | Stage 1 of two-stage consolidation | `EXTRA` | inherits `CONSOLIDATION_LM_STUDIO_TEMPERATURE` | inherits `CONSOLIDATION_LOCAL_MAX_TOKENS` |
| `EXTRACT` | Stage 2 memory-candidate extraction | `LOCAL` | inherits `MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE` | inherits `MEMORY_EXTRACT_MAX_TOKENS` |

**`MODEL` normally does not need to be filled in.** The normal source of a model ID is `LLM_ENDPOINT_<SLOT>_MODEL` from the previous section, which is what the GUI endpoint card edits. Role-level `MODEL` is only an **override**, for cases where one role needs another model on the same endpoint, such as using a cheaper model for fallback decisions. The `Model` column in the GUI role matrix is therefore read-only and shows the final value and its source. To override it, edit `LLM_ROLE_<ROLE>_MODEL` in advanced configuration.

The complete resolution order (`core/llm/registry.py::_resolve_role_model`) is:

1. **Explicit role `MODEL`**: the criterion is that its value differs from the old key it inherits. All `MODEL` settings are inheritance-based (`CHAT` / `ROUTER` / `COMPACT` inherit `LM_STUDIO_MODEL`, `PLUGIN` inherits `ASTRBOT_LLM_MODEL`, `CONSOLIDATION` inherits `CONSOLIDATION_LM_STUDIO_MODEL`, and `EXTRACT` inherits `MEMORY_EXTRACT_LM_STUDIO_MODEL`). Thus an existing `.env` that only sets an old key reaches tier 3 and behaves exactly as before;
2. **The `MODEL` of the endpoint bound to the role**;
3. **The role's own old key** (the one in parentheses in tier 1). On an **online** endpoint, this tier applies only to the card that owns that old key: `LM_STUDIO_MODEL` belongs to `LOCAL`, and `CONSOLIDATION_LM_STUDIO_MODEL` belongs to `EXTRA`. If a role is moved to `ONLINE_CHAT` / `ONLINE_MEMORY` while the endpoint has no model, the local model name is not accidentally sent to the online provider (which would always produce a 400). Instead, the system immediately reports that the endpoint has no model.

> **“Empty means inherit” requires a genuinely empty setting.** Writing an inheritance-based key as `KEY=` (nothing after the equals sign) is **not equivalent** to omitting the line: the empty string is treated as an explicit value and cuts the inheritance chain at that point. Before 2026-08-28, this is how `MEMORY_EXTRACT_LM_STUDIO_BASE_URL` became an empty string, causing Stage 2 to construct a URL without a scheme every time and fail. When editing `.env` manually, **delete the whole line** instead of clearing the value after the equals sign. The GUI handles this for you and does not write empty inheritance-based keys to `.env`.

### Three Typical Scenarios

Only the 6 `LLM_ROLE_*_ENDPOINT` settings need to change; the GUI provides three corresponding one-click presets. `MEMORY_EMBEDDING_GATE` remains `auto` in all three scenarios.

| Role | A: Fully local | B: Fully online (dual key) | C: Hybrid: chat online · consolidation local |
|---|---|---|---|
| `CHAT` | `LOCAL` | `ONLINE_CHAT` | `ONLINE_CHAT` |
| `ROUTER` | `LOCAL` | `ONLINE_CHAT` (choose a cheap model) | `ONLINE_CHAT` (choose a cheap model) |
| `PLUGIN` | `LOCAL` | `ONLINE_CHAT` | `ONLINE_CHAT` |
| `COMPACT` | `LOCAL` | `ONLINE_MEMORY` | `LOCAL` |
| `CONSOLIDATION` | `EXTRA` | `ONLINE_MEMORY` | `LOCAL` |
| `EXTRACT` | `LOCAL` | `ONLINE_MEMORY` (choose a strong model) | `LOCAL` |

Scenario C balances cost and privacy: only chat generation goes online; the original group-chat text is not sent to the online provider.

### Why Two Online Keys Are Required

`ONLINE_CHAT` and `ONLINE_MEMORY` **must use different API keys**. Online providers partition prompt-cache domains by key, while these two kinds of calls have completely different prompt prefixes: chat includes persona and context, whereas consolidation includes consolidation instructions and original group-chat text. Sharing one key makes the two sides continually interrupt each other's prefix cache, collapsing the cache hit rate toward 0 and eliminating the premise of saving money.

The GUI warns when the two keys are identical; the `registry` shared-key check records it as a warning in the doctor report.

### Failure Fallback

| Configuration | Default | Description |
|---|---|---|
| `LLM_FALLBACK_ENABLED` | `true` | Global switch |
| `LLM_FALLBACK_COOLDOWN` | `300` | Seconds to cool down a failed endpoint before retrying it |
| `LLM_ROLE_<ROLE>_FALLBACK_ENDPOINT` | empty | Endpoint slot to use when this role fails |

**Fallback occurs only when the role explicitly sets `FALLBACK_ENDPOINT`**. The global switch does not choose a backup endpoint for you. A typical use is to fall back from online chat to `LOCAL`, degrading gracefully instead of going silent during network instability or exhausted quota.

### Cost Control: Usage Accounting and Daily Budget

Online endpoints charge by token, and the memory domain (consolidation / compression / extraction) consists of frequent background tasks. **Without accounting, you do not know where money goes; without a budget, there is no ceiling.** Usage accumulates in the `llm_usage_daily` table by date × role × endpoint slot × model and is visible on the GUI `Runtime Status` page and in `python -m deploy status`.

| Configuration | Default | Description |
|---|---|---|
| `LLM_USAGE_ACCOUNTING` | `true` | Whether to persist usage. When disabled, no hooks are attached, no table is created, and nothing is written to the database |
| `LLM_DAILY_TOKEN_BUDGET` | `0` | Daily token budget (input + output), **0 = unlimited** |
| `LLM_BUDGET_SCOPE` | `online` | Which endpoints count toward the budget: `online` counts only online endpoints (local is free) / `all` counts all |
| `LLM_BUDGET_EXHAUSTED_ACTION` | `pause_memory` | Action after the budget is exceeded; see the three options below |

The three actions after the budget is exceeded are:

| Value | Behavior |
|---|---|
| `pause_memory` (default) | Stops only the three memory-domain roles (consolidation / compression / extraction); **the bot continues talking in groups** |
| `pause_all` | Stops chat too: blocked messages are **silently ignored**, with only one warning log entry. No explanatory message is sent and there is no fallback to a local endpoint. Fallback would make “pause all” misleading, and a fully online deployment may not have a local endpoint |
| `warn_only` | Logs one warning and never blocks a call |

Unrecognized values are handled conservatively as `pause_memory`.

Three easy-to-miss points:

- **The budget rolls over naturally at midnight according to the local date.** It uses a date key rather than a timer; after a process restart, that day's accumulated total is read back from the table and is not reset. Otherwise a “daily budget” would become “24 hours after each startup.”
- **Disabling accounting also disables the budget**: without usage data, excess cannot be detected. `LLM_DAILY_TOKEN_BUDGET` becomes an ineffective number, and doctor reports a warning.
- **Excess is only a warning and does not block startup**: under the default action, chat remains available. Blocking startup would turn “memory temporarily stops updating” into “the Bot cannot start.”

Daily records are automatically cleaned up when read after 90 days. This duration is hard-coded and has no setting: there are at most a few dozen rows per day, so there is no reason to tune it. For long-term retention, export the data rather than allowing the database to grow without limit.

#### Cache Hit Rate: The Only Way to Verify Prefix Caching

The **denominator for cache hit rate in the usage panel is input tokens, not call count**. One long request with half its input cached and two short requests with all input cached save very different amounts of money.

If this number remains 0, the fixed prompt prefix has been broken and prefix caching is not working. The most common causes are changing content in the prefix (timestamps or randomly ordered memory lists), or sharing one key between `ONLINE_CHAT` and `ONLINE_MEMORY` (see the previous section). After an online deployment has run for half an hour, check this number.

### Embedding Does Not Follow LLM Online/Offline Selection

`MEMORY_EMBEDDING_*` always points to the local machine and **does not participate in the endpoint/role system**. Changing the embedding model changes the vector dimension and requires recomputing every vector in the database, so it must not drift with a decision such as “use online today.” The embedding endpoint column in the GUI role matrix is permanently disabled.

It only needs to determine ownership of the queueing gate:

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_EMBEDDING_GATE` | `auto` | `auto` = share the gate with the local LLM slot (equivalent to no queue when there is no local LLM endpoint); `<SLOT>` = share the gate of the specified slot; `none` = do not queue |

Both outcomes of `auto` are correct: when a local slot exists, sharing its gate prevents embedding and chat from competing for the same LM Studio; in a fully online deployment there is no local LLM endpoint, so embedding has the local machine to itself and queueing would only make it wait unnecessarily.

### Main Chat Model

The keys in this section and the following `Memory Consolidation Model` and `Memory Candidate Extraction` sections **remain the main configuration entry points**. They are what the wizard writes, and what the `Model ID` fields on the GUI local and spare endpoint cards edit. They also serve as the inheritance sources for the role keys above: when `LLM_ROLE_CHAT_MODEL` / `_ROUTER_MODEL` / `_COMPACT_MODEL` are empty, all use `LM_STUDIO_MODEL`. Fill the corresponding `LLM_ROLE_*` only when a role must differ from the local default.

| Configuration | Default | Description |
|---|---|---|
| `LM_STUDIO_BASE_URL` | `http://127.0.0.1:1234` | LM Studio address |
| `LM_STUDIO_MODEL` | empty | Model ID; when empty, the server chooses the default route |
| `LLM_TIMEOUT` | `90.0` | Timeout for one generation (seconds) |

### Memory Consolidation Model

Consolidation is separate from chat and can point to a different model on the same instance or to an independent port. **CPU inference is recommended for the consolidation model** to avoid competing with the main chat model for GPU memory.

| Configuration | Default | Description |
|---|---|---|
| `CONSOLIDATION_LM_STUDIO_BASE_URL` | same as `LM_STUDIO_BASE_URL` | Consolidation service address |
| `CONSOLIDATION_LM_STUDIO_MODEL` | `google/gemma-4-e4b` | Consolidation model ID |
| `CONSOLIDATION_LM_STUDIO_TEMPERATURE` | `0.3` | Low temperature for stable JSON output |
| `CONSOLIDATION_LOCAL_BATCH_SIZE` | `30` | Normal consolidation batch size |
| `CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE` | `10` | Small batch for the force path (before an @ trigger / proactive speaking) |
| `CONSOLIDATION_OVERLAP` | `15` | Number of previous messages to review, preventing topics from being cut at batch boundaries |
| `CONSOLIDATION_LOCAL_MAX_TOKENS` | `1200` | Maximum generated tokens for consolidation |
| `CONSOLIDATION_TRIGGER_NEW_MESSAGES` | `10` | Number of accumulated new messages required to trigger consolidation |

#### A Different Batch Configuration for Online Consolidation

The `CONSOLIDATION_LOCAL_*` values above are for the **local** endpoint. Local inference has no per-token charge and costs only time, so small batches, substantial overlap, and quick results on the force path are appropriate. After switching to an online endpoint, the same values mean paying the fixed cost repeatedly for every batch, so a separate online configuration is provided. It **takes effect only when the CONSOLIDATION role actually uses an online endpoint** (`LLM_ROLE_CONSOLIDATION_ENDPOINT` points to `ONLINE_*`). Set it to the same value as the local key to disable the corresponding behavior.

| Configuration | Default | Corresponding local key | Description |
|---|---|---|---|
| `CONSOLIDATION_ONLINE_BATCH_SIZE` | `60` | `CONSOLIDATION_LOCAL_BATCH_SIZE` (30) | Amortizes the fixed prompt cost across each batch; doubling the batch size halves the fixed cost allocated to each message |
| `CONSOLIDATION_ONLINE_FORCE_BATCH_SIZE` | `30` | `CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE` (10) | The force path originally pays the same fixed cost with one third of the batch size, making it the most expensive path per unit across the pipeline |
| `CONSOLIDATION_ONLINE_OVERLAP` | `0` | `CONSOLIDATION_OVERLAP` (15) | 0 = no overlap. Overlapping messages are billed repeatedly in every batch, while topic continuity is already provided by `current_summary`, which is sent in every batch |

> ⚠️ **Saving money requires larger batches; never achieve it by increasing `CONSOLIDATION_SCHEDULE_INTERVAL`.** Provider prefix caches have a TTL measured in minutes. Once the interval exceeds the TTL, the fixed prefix goes from the cached price back to the full price and costs more. Keep the interval ≤ 4 minutes. This is counterintuitive if the goal is to reduce call count, but it is how the bill is calculated.

> Increasing the force batch from 10 to 30 only makes the summary slightly less fresh; it does not slow @ replies. Force consolidation uses `asyncio.create_task` fire-and-forget and is not on the critical path of an @ reply.

> **Online endpoints should also tighten `LLM_ROLE_CONSOLIDATION_MAX_TOKENS`** (which by default inherits 1200 from `CONSOLIDATION_LOCAL_MAX_TOKENS`). Online model output is usually priced at 3~4 times the input price, while Stage 1 consolidation output rarely exceeds 800 tokens. Setting `800` removes a portion of pure unused allowance. **Do not reduce it below 600**: truncation causes JSON parsing to fail; see the previous caution. The default is intentionally unchanged because local inference is not billed and has no reason to be tightened.

> `CONSOLIDATION_LM_STUDIO_BASE_URL` remains the inheritance source for the `EXTRA` endpoint slot. `CONSOLIDATION_LM_STUDIO_MODEL` / `_TEMPERATURE` / `CONSOLIDATION_LOCAL_MAX_TOKENS` remain the sources for `LLM_ROLE_CONSOLIDATION_*`. **Do not delete them just because role keys are now available**: deleting them also clears the address of the `EXTRA` slot. To move consolidation online, set `LLM_ROLE_CONSOLIDATION_ENDPOINT=ONLINE_MEMORY` and put the model in `LLM_ENDPOINT_ONLINE_MEMORY_MODEL`.

> **Note `CONSOLIDATION_LOCAL_MAX_TOKENS`**: batch 30 + overlap 15 means up to 45 messages can be supplied in one request. Truncation causes JSON parsing to fail, while the checkpoint **still advances** on a parse failure to prevent repeatedly rerunning the same batch. That batch of messages is then permanently lost. `core/llm/lm_studio.py` logs a warning when `finish_reason=length`; after running for a while, check the logs for it.

### Consolidation Scheduling

| Configuration | Default | Description |
|---|---|---|
| `CONSOLIDATION_SCHEDULE_INTERVAL` | `120` | Check interval for scheduled consolidation (seconds) |
| `CONSOLIDATION_MAX_ROUNDS_PER_RUN` | `3` | Maximum number of consecutive batches consolidated by one scheduled run |
| `CONSOLIDATION_BACKLOG_WARN` | `300` | Promote the log level to warning when the backlog exceeds this count |
| `CONSOLIDATION_MAX_SKIP_STREAK` | `3` | Force one consolidation after this many consecutive pre-filter skips (`0` = no safety net, not recommended) |

> **Why scheduled consolidation is needed**: consolidation previously ran only before an @ trigger and before proactive speaking. When passive ingestion was faster than consolidation, the backlog could grow without bound (1004 messages measured on 2026-08-16), and messages not yet consolidated were discarded once they exceeded `MESSAGE_CLEANUP_KEEP_COUNT`.
>
> Do not use too many batches per run: a CPU small model takes 20~60 seconds per batch, so too many batches occupy the consolidation model for a long time, while too few cannot catch up with the backlog.

**What `CONSOLIDATION_MAX_SKIP_STREAK` protects against**: before consolidation there is a **purely local, zero-cost** pre-filter (image spam, one-character replies, too few @ messages, or high semantic repetition with the previous batch). A match skips the round and saves the messages for the next one. **Skipping does not advance the checkpoint, so it accumulates a batch rather than discarding it.** However, a group with only persistent image spam could remain indefinitely. Once consecutive skips reach this count, one consolidation is forced and the streak is cleared, ensuring the worst case is delay rather than loss.

### Memory Candidate Extraction (Stage 2)

Consolidation runs in two stages:

| Stage | Task | Model |
|---|---|---|
| Stage 1 | Short-term summary + user profile + `has_self_disclosure` boolean judgment | Consolidation model (small CPU model) |
| Stage 2 | Precise extraction of `memory_candidates` | Model configured in this section (defaults to the main chat model) |

Stage 2 is **activated only when Stage 1 determines that the batch contains user self-disclosure** (a soft gate). Everyday spam, greetings, and discussion of third parties therefore consume only the small model's compute.

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_EXTRACT_ENABLED` | `true` | When disabled, falls back to one stage (the consolidation model produces everything in one pass) |
| `MEMORY_EXTRACT_LM_STUDIO_BASE_URL` | same as `LM_STUDIO_BASE_URL` | Extraction service address |
| `MEMORY_EXTRACT_LM_STUDIO_MODEL` | same as `LM_STUDIO_MODEL` | Defaults to the main chat model |
| `MEMORY_EXTRACT_LM_STUDIO_TEMPERATURE` | `0.2` | Extraction does not need creative variation, so it is lower than consolidation's 0.3 |
| `MEMORY_EXTRACT_MAX_TOKENS` | `1000` | Only a candidate array is output, so a large value is unnecessary |

> These four `MEMORY_EXTRACT_LM_STUDIO_*` / `MEMORY_EXTRACT_MAX_TOKENS` settings are the inheritance sources for `LLM_ROLE_EXTRACT_*`. To send Stage 2 to a strong online model, change `LLM_ROLE_EXTRACT_ENDPOINT` (the model comes from that endpoint's `MODEL`; write `LLM_ROLE_EXTRACT_MODEL` only when it must differ from other roles on the same endpoint). The settings in this section do not need to change.

**Why split the stages**: a small model can summarize a topic, but in a noisy environment it systematically returns no candidates. On 2026-08-16, all 7 tested consolidation batches returned empty candidates even though the information was clearly present in the summaries it had written. It had read the information but actively discarded it; it had not failed to see it. Candidate extraction is a high-precision extraction task and is delegated to a larger model.

The `insomnia_breakfast_noisy` case in `probe_consolidation.py` locks in this difference: the same information is buried among Bot greetings and spam; one-stage processing hit 1/2, while two-stage processing hit 2/2.

**Cost**: extraction took about 20 seconds per call on the main chat model in testing (1600 prompt tokens + 280 generated at 19 tok/s). In the default configuration, EXTRACT and CHAT are both bound to the `LOCAL` slot, so they share one gate and serialize in FIFO order. An extraction started during chat waits behind it, and vice versa. Assigning them to different endpoint slots, such as EXTRACT on `ONLINE_MEMORY`, removes this serialization; see [LLM Resource Scheduling](#llm-resource-scheduling).

### Vector Semantic Search (Optional)

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_EMBEDDING_ENABLED` | `false` | When disabled, use rule-based lexical semantics (offline and deterministic) |
| `MEMORY_EMBEDDING_BASE_URL` | `http://127.0.0.1:1234` | Embedding service address |
| `MEMORY_EMBEDDING_MODEL` | empty | Vector model ID |
| `MEMORY_EMBEDDING_TIMEOUT` | `10.0` | Timeout for one request (seconds) |
| `MEMORY_EMBEDDING_CONTEXTUAL_MIN` | `0.25` | Cosine threshold for topic matching of `CONTEXTUAL` memories on the embedding path |

If the service or model is unavailable, the system **automatically falls back to the rule-based version** and the pipeline continues.

### LLM Resource Scheduling

LM Studio **does not limit concurrency**: when multiple requests reach the same model at once, the server does not queue them. It merely crowds inference with concurrent work, slowing every request and making it difficult to identify what is competing for compute. The application layer therefore needs gates for shared models.

**The endpoint slot is the gate**: the gate behind which a role waits is determined by the slot named in `LLM_ROLE_<ROLE>_ENDPOINT`, and its concurrency limit comes from `LLM_ENDPOINT_<SLOT>_CONCURRENCY`. Requests serialize strictly in FIFO order within a slot and run truly in parallel across different slots. The default fully local configuration creates two gates:

| Gate (slot) | Users | Default concurrency |
|---|---|---|
| `LOCAL` | Chat replies, fallback decisions, plugins, session compaction, candidate extraction, and embedding encoding when `MEMORY_EMBEDDING_GATE=auto` | `1` |
| `EXTRA` | Stage 1 of two-stage consolidation | `1` |

After moving chat to `ONLINE_CHAT`, chat and local consolidation use different slots and no longer queue behind one another. Besides saving GPU memory, this is another benefit of going online.

> The `RESOURCE_CHAT` / `RESOURCE_CONSOLIDATION` constants in `core/llm/scheduler.py` are old resource names with no remaining call sites. They remain only to avoid breaking external imports. Calling acquire with them creates an independent gate **that corresponds to no endpoint** and therefore provides no serialization protection. New code should use `registry.gate_of(role)`.

| Configuration | Default | Description |
|---|---|---|
| `LLM_SCHEDULER_WAIT_WARN_SECONDS` | `30.0` | Warn when queue wait exceeds this many seconds |
| `LLM_SCHEDULER_HOLD_WARN_SECONDS` | `90.0` | Warn when one hold exceeds this many seconds |
| `LLM_SCHEDULER_QUEUE_WARN_DEPTH` | `3` | Warn when queue depth reaches this value |
| `LLM_SCHEDULER_PRIORITY_ENABLED` | `false` | **Not implemented**; switch retained |
| `LLM_SCHEDULER_GATE_EMBEDDING` | `true` | **Deprecated**, replaced by `MEMORY_EMBEDDING_GATE` (`true` → `auto`, `false` → `none`). It is still read only when the new key is not explicitly set |

The hold-warning threshold accounts for 3 backend retries (120 seconds per timeout), so the upper bound for one hold is far greater than one normal request. Persistently exceeding it indicates that the call itself is stuck, not merely queued.

The reason `MEMORY_EMBEDDING_GATE` defaults to `auto` is that `MEMORY_EMBEDDING_BASE_URL` defaults to the same instance as main chat, while one retrieval encodes every candidate memory once (the candidate pool can reach 20+). Without serialization, intermittent slowdowns are difficult to diagnose. If embedding runs on an independent instance, set `none` to avoid unnecessary serialization. `python -m deploy doctor` identifies `LLM_SCHEDULER_GATE_EMBEDDING` as an old key.

**Why priority is not implemented**: strict FIFO across multiple groups can place an @ reply behind background tasks. However, each group has at most one background task in flight and the total is bounded; the actual impact requires real queueing data. Accumulate observations from `core.llm.snapshot()` first, then decide whether to deviate from FIFO.

## Context

| Configuration | Default | Description |
|---|---|---|
| `RECENT_TAIL_LIMIT` | `12` | Number of recent raw messages appended to each reply, including the Bot's own messages |
| `RECENT_TAIL_MAX_AGE_MINUTES` | `45.0` | Tail time window (minutes): messages older than this no longer count as “recent conversation”; `0` disables time filtering |
| `RECENT_TAIL_GAP_MARK_MINUTES` | `15.0` | Insert a gap marker in the tail when adjacent messages are more than this many minutes apart; `0` disables it |
| `SHORT_TERM_SUMMARY_STALE_MINUTES` | `60.0` | If the summary has not been updated for this long, change its title to “Previous topic” and include the age; `0` disables it |
| `MAX_REPLY_LINES` | `5` | Maximum lines in one reply |
| `SEND_INTERVAL` | `0.8` | Delay between multiple lines (seconds) |
| `FALLBACK_REPLY` | `......？` | Fallback reply |
| `BAD_PHRASES` | see settings.py | List of panic phrases; a match is replaced with the fallback reply |

> **The `RECENT_TAIL_LIMIT` trade-off**: too small a value lets spam in an active group push the Bot's own question out of the window, causing a short user reply (“phone,” “yes”) to attach to the previous topic; too large a value lets irrelevant history distract the model and lengthens the prompt. 12 is a starting point and should be adjusted for the group's message rate.

> **Tail time window and gap markers**: taking only the latest N IDs means that after several hours offline, a restart treats a conversation from hours ago as current (the 2026-08-15 defect). `RECENT_TAIL_MAX_AGE_MINUTES` filters out expired messages; when adjacent messages inside the window are more than `RECENT_TAIL_GAP_MARK_MINUTES` apart, it inserts a line such as “(... X elapsed in between ...)” so the model knows that the conversation happened before but a long time has passed, rather than simply forgetting it.

### Session Context Compaction

In a short, continuous conversation, early messages eventually roll out of the tail window and disappear completely. This mechanism compresses the rolled-out portion into a recap so the Bot remains coherent in long conversations, similar to compacting in a coding agent.

**The three context layers are divided by message ID and never overlap**:

| Layer | Range |
|---|---|
| Session summary | `summarized_up_to_id` → start of the tail (earlier, compressed portion) |
| Raw tail | The most recent `RECENT_TAIL_LIMIT` messages (original text) |
| Topic summary | Cross-session background produced by the consolidator |

Overlap would make two versions of the same conversation appear, causing the model to follow the summary and attach to the wrong topic (the cause of the 2026-08-13 defect).

| Configuration | Default | Description |
|---|---|---|
| `SESSION_CONTEXT_ENABLED` | `true` | Global session-compaction switch |
| `SESSION_COMPACT_THRESHOLD_TOKENS` | `600` | Trigger only when the text awaiting compaction exceeds this estimated token count |
| `SESSION_SUMMARY_MAX_TOKENS` | `300` | Budget for the summary itself; when exceeded, recompress it together with the new content |
| `SESSION_COMPACT_MAX_MESSAGES` | `60` | Maximum messages supplied to one compaction |
| `SESSION_IDLE_TIMEOUT_SECONDS` | `900.0` | Idle duration after which the session is considered finished (clears the summary and triggers one full consolidation) |
| `SESSION_IDLE_CHECK_INTERVAL` | `300` | Idle-check interval (seconds) |

Compaction uses the **main chat model**, not the consolidation model. The consolidation model runs on CPU and takes 20~60 seconds per call, while compaction is triggered asynchronously after every reply and must be fast. Compaction does not block the current reply; the summary takes effect from the next round.

The reason for consolidating once when a session ends is that the conversation's content previously existed in memory only as a compressed summary and would be lost on restart. End-of-session consolidation deposits it as long-term-memory candidates.

## Memory: Capture and Promotion

### Source Tiers and Candidate Reinforcement

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_SOURCE_KIND_ENABLED` | `true` | When disabled, all messages have equal weight and the prompt does not label their sources |
| `MEMORY_AT_MENTION_CONFIDENCE_BONUS` | `0.05` | Confidence bonus for candidates from the `AT_MENTION` source |
| `MEMORY_CANDIDATE_REOCCURRENCE_BONUS` | `0.12` | Confidence gain when the same fact recurs |
| `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS` | `30` | Maximum time in the observation area; mark as `REJECTED` after expiry (do not delete). Time-sensitive types have shorter tiers; see below |
| `MEMORY_CANDIDATE_EVIDENCE_MAX_CHARS` | `800` | Maximum accumulated `evidence` |

The value `0.12` means a candidate starting at 0.5 crosses the 0.6 threshold after approximately 2 recurrences.

The observation limit is **tiered by type**. The tier table is the code-level constant `MEMORY_CANDIDATE_MAX_OBSERVING_DAYS_BY_TYPE` (`config/settings.py`) and is not read from `.env`: 3 days for `EVENT`, 7 for `GROUP_CONTEXT`, 14 for `PLAN`; any type not listed falls back to the global value above. Like `MEMORY_DECAY_DAYS`, it is a semantic judgment about "how long this kind of information is still worth waiting for a second piece of evidence," not a deployment parameter.

### Gate 1: Three Tiers

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_CONFIRM_HIGH_CONFIDENCE` | `0.85` | Promote directly when reached |
| `MEMORY_OBSERVE_LOW_CONFIDENCE` | `0.6` | When reached, inspect the sufficiency of the evidence |
| `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE` | `2` | Minimum observations required to promote a passive-source candidate |
| `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` | `true` | Whether an `AT_MENTION` source can be promoted after one occurrence |
| `MEMORY_PROMOTE_MIN_IMPORTANCE` | `0.3` | Minimum importance required for promotion (a floor, not sufficient by itself) |

### Per-User Quota

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_QUOTA_ENFORCE` | **`false`** | When disabled, only dry-run logs are emitted and nothing is actually evicted |
| `MEMORY_USER_QUOTA` | `25` | Maximum active memories for one user in **one shared space** |
| `MEMORY_QUOTA_W_IMPORTANCE` | `0.4` | Competition-score weight: importance |
| `MEMORY_QUOTA_W_CONFIRMATION` | `0.3` | Competition-score weight: confirmation count |
| `MEMORY_QUOTA_W_RECENCY` | `0.3` | Competition-score weight: recent access |
| `MEMORY_QUOTA_CONFIRMATION_CAP` | `3` | Normalization cap for confirmation count |

> **Observe before enabling.** When `MEMORY_QUOTA_ENFORCE=false`, logs contain `[Quota dry-run] ... would evict xxx`. Confirm that the proposed evictions are reasonable before enabling enforcement. Eviction sets `archived`; it does not delete, but restoration requires manual SQL.

> When multiple QQ groups belong to one space, the quota is effectively tighter because the same person has only one body of knowledge in that space. This is intentional, but it matters when tuning.

## Memory: Retrieval and Ranking

### RAG Switches

| Configuration | Default | Description |
|---|---|---|
| `RAG_ENABLED` | `true` | When disabled, always use weighted fallback ranking |
| `RAG_SQLITE_FTS_ENABLED` | `true` | Whether to use the FTS5 full-text index |
| `RAG_TOP_K` | `5` | Lower bound for the FTS candidate pool |
| `MEMORY_V2_ENABLED` | `true` | When disabled, fall back to legacy retrieval and legacy prompt assembly |

### Ranking Weights

The six dimensions are weighted with a total of approximately 1.0. The principle is **Policy / Context before similarity**, avoiding “finding the wrong memory” rather than merely “finding no memory.”

| Configuration | Default | Dimension |
|---|---|---|
| `MEMORY_SCORE_W_CONTEXT` | `0.25` | Context fit (fit to trigger condition / use) |
| `MEMORY_SCORE_W_USAGE` | `0.20` | Fit between use and the current mode |
| `MEMORY_SCORE_W_SEMANTIC` | `0.35` | Semantic similarity (embedding cosine or lexical fallback) |
| `MEMORY_SCORE_W_RECENCY` | `0.10` | Recency decay (exponential, τ=30 days) |
| `MEMORY_SCORE_W_CONFIDENCE` | `0.05` | Confidence |
| `MEMORY_SCORE_W_IMPORTANCE` | `0.05` | Importance |

The `confidence` / `importance` weights are intentionally low. They describe whether the memory itself is reliable or important, which is weakly related to whether it should be used now, so they are suitable only as tie-breakers.

When embedding is disabled, the semantic dimension is discarded and the remaining weights are renormalized.

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_SCORE_MIN` | `0.40` | Scores below this do not enter the prompt (dynamic count rather than a fixed Top-K) |
| `MODE_DETECT_MIN_SCORE` | `0.5` | Minimum score for mode detection; below it, fall back to `CASUAL_REPLY` |
| `USAGE_TYPE_MISMATCH_PENALTY` | `0.75` | Down-weighting factor when use and type are incompatible (not hard exclusion) |

### Per-Mode Memory Limits

| Configuration | Default |
|---|---|
| `MEMORY_LIMIT_CASUAL_REPLY` | `3` |
| `MEMORY_LIMIT_ACTIVE_JOIN` | `3` |
| `MEMORY_LIMIT_HUMOR` | `3` |
| `MEMORY_LIMIT_TECH_HELP` | `5` |
| `MEMORY_LIMIT_RECOMMEND` | `5` |
| `MEMORY_LIMIT_EMOTIONAL` | `3` |
| `MEMORY_LIMIT_CONFLICT_AVOID` | `10` |
| `MEMORY_LIMIT_GROUP_EVENT` | `5` |

The `CONFLICT_AVOID` limit is the largest because safety takes priority: behavioral constraints should err on the side of including more rather than missing one.

### Prompt Length Budget

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_CONVERSATION_MAX_TOKENS` | `500` | Maximum chat-material section |
| `MEMORY_CONVERSATION_TECH_MAX_TOKENS` | `1000` | Expanded allowance for technical scenarios |
| `MEMORY_BEHAVIOR_MAX_TOKENS` | `150` | Maximum behavior-constraint section |

### Legacy Retrieval (`MEMORY_V2_ENABLED=false`)

| Configuration | Default | Description |
|---|---|---|
| `PROACTIVE_LONG_TERM_LIMIT` | `10` | Number of memories cited in proactive speaking |
| `REPLY_LONG_TERM_LIMIT` | `3` | Number of that user's memories cited in an @ reply |
| `LONG_TERM_RELEVANCE_ENABLED` | `true` | Whether to keyword-filter other users' old memories for relevance |
| `LONG_TERM_RELEVANCE_KEYWORDS` | `5` | Number of keywords to extract |
| `LONG_TERM_RELEVANCE_CANDIDATE_LIMIT` | `20` | Candidate-pool limit |
| `LONG_TERM_RELEVANCE_WEIGHT_KEYWORDS` | `2.0` | Weight: keyword overlap |
| `LONG_TERM_RELEVANCE_WEIGHT_RECENCY` | `1.0` | Weight: most recent access |
| `LONG_TERM_RELEVANCE_WEIGHT_IMPORTANCE` | `1.2` | Weight: importance |
| `LONG_TERM_RELEVANCE_WEIGHT_CONFIDENCE` | `0.8` | Weight: confidence |
| `LONG_TERM_RELEVANCE_WEIGHT_USER_RELEVANCE` | `0.6` | Weight: user relevance |

## Proactive Speaking

### Topic Participation Probability Curve

Two-anchor interpolation with power shaping. One curve can express two opposite intentions through parameters alone, without a mode switch.

```
interval <= FAST → PROB_AT_FAST
interval >= SLOW → PROB_AT_SLOW
middle           → t = (SLOW - interval) / (SLOW - FAST)
                   prob = PROB_AT_SLOW + (PROB_AT_FAST - PROB_AT_SLOW) × t^GAMMA
```

| Configuration | Default | Description |
|---|---|---|
| `PROACTIVE_ENABLED` | `true` | Global proactive-speaking switch |
| `PROACTIVE_INTERVAL_FAST` | `20.0` | Upper bound of the average interval considered “high frequency” (seconds) |
| `PROACTIVE_INTERVAL_SLOW` | `180.0` | Lower bound of the average interval considered “quiet” (seconds) |
| `PROACTIVE_PROB_AT_FAST` | `0.15` | Probability at the high-frequency end |
| `PROACTIVE_PROB_AT_SLOW` | `0.0` | Probability at the quiet end |
| `PROACTIVE_PROB_GAMMA` | `1.0` | Curve-shaping exponent; >1 is more conservative |
| `PROACTIVE_TOPIC_WARMUP_SECONDS` | `45.0` | Topic warm-up duration; do not participate before it is reached |
| `PROACTIVE_COOLDOWN` | `600` | Hard group-level cooldown (seconds) |
| `PROACTIVE_CHECK_INTERVAL` | `60` | Scheduled check interval (seconds) |
| `PROACTIVE_FREQ_WINDOW` | `10` | Frequency-estimation window (most recent N messages) |
| `PROACTIVE_MAX_LINES` | `1` | Maximum lines in a proactive interjection |
| `PROACTIVE_MIN_MESSAGES_SINCE_SPOKE` | `15` | Minimum new group messages required after the Bot last spoke before it may speak again. 0 means unlimited |

**Three presets**:

```env
# Interject when the group is lively (default, suitable for casual-chat groups)
PROACTIVE_PROB_AT_FAST=0.15
PROACTIVE_PROB_AT_SLOW=0.0

# Stay quiet when the group is lively (old behavior, suitable for technical groups)
PROACTIVE_PROB_AT_FAST=0.05
PROACTIVE_PROB_AT_SLOW=0.5

# Disable topic participation completely (retain proactive @ mentions)
PROACTIVE_PROB_AT_FAST=0.0
PROACTIVE_PROB_AT_SLOW=0.0
```

**Why a message-count threshold is needed**: a pure time cooldown in a quiet group can result in “say something, wait 10 minutes, then say something again.” The message threshold ensures that the topic has actually moved forward before an interjection. The count is in-process; after a restart, it is treated as if enough new messages exist, so a restart cannot permanently block proactive speaking.

For a practical frequency reference for the three presets (`CHECK_INTERVAL=60`): with `PROB_AT_FAST=0.15`, an active group is expected to hit approximately every 6.7 minutes. With `COOLDOWN=600` and the message threshold included, the actual speaking interval is usually more than 10 minutes.

### Proactive @ Mentions

| Configuration | Default | Description |
|---|---|---|
| `PROACTIVE_AT_ENABLED` | `true` | Global proactive-@ switch |
| `PROACTIVE_AT_QUOTA_BASE` | `2` | Daily base quota per user |
| `PROACTIVE_AT_QUOTA_BONUS_MAX` | `2` | Maximum bonus for a high-frequency user |
| `PROACTIVE_AT_BONUS_MSGS_LOW` | `20` | Bonus starting point (messages in 24h) |
| `PROACTIVE_AT_BONUS_MSGS_HIGH` | `100` | Full-bonus point |
| `PROACTIVE_AT_USER_COOLDOWN` | `7200.0` | Minimum interval between two proactive @ mentions of the same user (seconds) |
| `PROACTIVE_AT_ACTIVE_WITHIN` | `300.0` | Window for deciding that a user is “currently active” (seconds) |
| `PROACTIVE_MAX_NO_REPLY` | `2` | Maximum consecutive non-responses before follow-up questions are paused |
| `PROACTIVE_REPLY_WINDOW_SECONDS` | `300.0` | Response-detection window (seconds) |
| `PROACTIVE_COLDSTART_TOPICS` | see settings.py | Cold-start topic list, comma-separated |
| `PROACTIVE_AT_EXCLUDE_USERS` | empty | QQ numbers that will not be selected for proactive conversation (comma-separated) |
| `PROACTIVE_VERIFY_EXCLUDE_TYPES` | `EVENT,PLAN,GROUP_CONTEXT` | Candidate types that are never verified via a proactive follow-up (comma-separated; empty = any type may be asked about) |

The exclusion list is primarily for **other AIs in the group**: mutually @-mentioning them can trigger an endless conversational loop. Excluded accounts are still passively collected (messages are stored and consolidated normally); the Bot simply does not ask them questions proactively.

`PROACTIVE_VERIFY_EXCLUDE_TYPES` excludes **candidate types**, not people. The quota is extremely scarce (2 per user per day by default), and verification exists to push a candidate past the promotion line into **long-term** memory — time-sensitive information has already expired by the time it is confirmed, and asking "did you hear the earthquake warning" a week later is absurd. These candidates are still stored and can still be promoted by `AT_MENTION` or passive reoccurrence; the Bot simply will not bother a user about them.

The quota is hard-capped at `BASE + BONUS_MAX` (4 times per day by default). **“The more active a user is, the more they are harassed” is a failure mode that must be avoided**, so increasing the bonus is not recommended.

Quota is counted when a mention is sent, regardless of whether the user responds. Otherwise unanswered follow-ups would consume no quota and could repeatedly target the same person.

### Sleep Period

This simulates a human schedule: all proactive speaking (topic interjections + proactive @ mentions) is disabled during sleep, but **@ replies continue normally**.

Replies are not disabled during sleep because ignoring a user who actively calls the Bot looks like a disconnection. `AT_MENTION` is also currently the only memory source, so not replying during sleep would lose several hours of collection every day. Passive collection (message storage and consolidation) continues normally during sleep.

| Configuration | Default | Description |
|---|---|---|
| `PROACTIVE_SLEEP_ENABLED` | `true` | Global sleep-period switch |
| `PROACTIVE_SLEEP_START` | `23:30` | Sleep time (`HH:MM`, **local time**) |
| `PROACTIVE_SLEEP_END` | `07:30` | Wake time (`HH:MM`, **local time**) |
| `PROACTIVE_WAKEUP_GRACE_SECONDS` | `900.0` | Wake-up grace period: how long after waking the Bot remains non-proactive |
| `PROACTIVE_SLEEP_ANNOUNCE` | `true` | Whether to announce sleep and wake-up |
| `PROACTIVE_SLEEP_MESSAGES` | see settings.py | Sleep announcement lines (comma-separated; one selected at random) |
| `PROACTIVE_WAKEUP_MESSAGES` | see settings.py | Wake-up announcement lines |

Intervals crossing midnight are supported (`START > END` means the interval crosses the day boundary). `START == END` means no sleep. Invalid time formats fall back to the defaults and emit a warning; a configuration typo should not make the Bot talk all night.

**Local time rather than UTC is used here** because this describes a human schedule and is unrelated to database timestamps. This is the only place in the entire project where local time is appropriate.

**Why the wake-up grace period is needed**: activity statistics accumulated overnight could make the Bot send several messages immediately upon waking. The grace period starts when the wake-up transition is detected.

Announcements are deduplicated to at most once per group per type per day, recorded in `group_runtime_state`. A scheduled task triggers announcements; without deduplication, restarting during the sleep period would repeat “I am going to sleep.” Announcements do not pass through the Pipeline (no LLM is needed), but they are written to `group_messages` (`BOT_SELF`) so the next consolidation understands the context.

### Runtime Toggle

Administrators can temporarily disable proactive speaking in a group, providing another gate in addition to the configuration-level switch. This lets deployers react immediately to member feedback.

| Configuration | Default | Description |
|---|---|---|
| `PROACTIVE_RUNTIME_TOGGLE_ENABLED` | `true` | Whether to enable runtime-toggle commands |
| `PROACTIVE_TOGGLE_ADMINS` | empty | Additional authorized QQ numbers (comma-separated). When empty, only the group owner/administrators can operate it |

Usage: @ the Bot and say a keyword.

| Action | Keywords |
|---|---|
| Mute | 安静、闭嘴、别说话、停止主动发言 |
| Resume | 恢复、醒醒、可以说话、开启主动发言 |

Mute state is **persisted in the `group_runtime_state` table and remains effective after restart**. Administrators usually disable it because something went wrong, so a restart should not silently re-enable it.

Mute affects proactive speaking only; @ replies continue normally. A non-administrator trigger makes no change and receives no reply.

## Memory Compression

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_COMPRESS_LIGHT_THRESHOLD` | `500` | Number of active memories that triggers light compression |
| `MEMORY_COMPRESS_LIGHT_COOLDOWN_SECONDS` | `3600` | Light-compression cooldown (seconds) |
| `MEMORY_ARCHIVE_IMPORTANCE_THRESHOLD` | `0.3` | Importance threshold for archiving low-value memories |
| `MEMORY_ARCHIVE_INACTIVE_DAYS` | `180` | Days without access before low-value archival |
| `MEMORY_COMPRESS_LOG_PATH` | `logs/memory_compressor_log.md` | Compression log (see [Logs](#logs)) |
| `MEMORY_RECENCY_HALF_LIFE_DAYS` | `120.0` | Fallback recency half-life (days) |

`MEMORY_DECAY_DAYS` is a dictionary in code, not an `.env` setting, defining the lifetime of each memory type:

| Type | Days |
|---|---|
| `FACT` | 730 |
| `STYLE` | 365 |
| `PREFERENCE` / `RELATION` | 180 |
| `EVENT` / `PLAN` | 60 |
| `GROUP_CONTEXT` | 30 |

## Decision Tracing and Cleanup

| Configuration | Default | Description |
|---|---|---|
| `MEMORY_TRACE_ENABLED` | `true` | Whether to record memory-decision traces |
| `MEMORY_TRACE_TABLE` | `memory_traces` | Trace table name |
| `MESSAGE_CLEANUP_ENABLED` | `true` | Whether to enable periodic message-table cleanup |
| `MESSAGE_CLEANUP_KEEP_COUNT` | `1000` | Most recent messages retained per group |
| `MESSAGE_CLEANUP_HOUR` | `4` | Daily cleanup time (24-hour clock) |
| `MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED` | `true` | Protect unconsolidated messages during cleanup (do not delete messages after the checkpoint) |
| `DB_CLEANUP_ON_START` | `false` | **For testing**: clear short- and long-term memory and reset the checkpoint at startup |
| `DB_CLEANUP_CLEAR_MESSAGES` | `false` | Whether cleanup also deletes original messages (dangerous) |

> `DB_CLEANUP_ON_START=true` loses memory and resets consolidation progress on every startup. Change it back to `false` after testing.

> Disabling `MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED` causes unconsolidated messages to be permanently discarded when the backlog exceeds `MESSAGE_CLEANUP_KEEP_COUNT`. That content will never enter the memory system, and checkpoint alignment makes the loss invisible.

## HTML to Image Rendering (Plugin Cards)

Many AstrBot plugins implement result cards as Jinja2 templates + CSS and render images through `Star.html_render`. The implementation is in `astrbot_compat/render.py`.

| Variable | Default | Description |
|---|---|---|
| `RENDER_ENABLED` | `true` | Global switch. When disabled, card plugins always use their own plain-text fallback |
| `RENDER_AUTO_INSTALL` | `true` | Automatically download the browser engine in the background before the first render when it is missing |
| `RENDER_INSTALL_RETRY_SECONDS` | `3600` | Cooldown after an automatic-install failure (seconds) |
| `RENDER_CACHE_DIR` | `data/render_cache` | Directory for rendered artifacts. **Do not put it in `logs/`**: these are images to send, not logs |
| `RENDER_CACHE_KEEP` | `50` | Number of most recent artifacts to retain |
| `RENDER_MAX_CONCURRENCY` | `2` | Maximum number rendered simultaneously |
| `RENDER_SETTLE_MS` | `300` | Milliseconds to wait after page `load` before taking a screenshot |
| `RENDER_TEXT_WIDTH` | `800` | Output width in pixels for `text_to_image` / `t2i` |

**The backend is local Chromium (playwright), not a remote service.** Upstream AstrBot normally sends HTML to a remote t2i service for rendering, but Stella does not: templates contain group-member nicknames, dynamic post text, and avatar URLs, all of which are chat content. In a fully local deployment, every other stage is local, so rendering should not be the one stage that sends data out. The same applies to deployments using online models: the selected provider is the destination chosen by the user, and there should not be an additional rendering service the user did not choose.

**Dependencies have two layers**: the `playwright` pip package is in `requirements.txt` (a few MB); the browser engine is about 270 MB and is downloaded in the background **only when rendering is first actually needed**. Plugins continue to fall back to plain text while the download runs, then use rendering automatically after installation without a restart.

Installing only the headless shell is intentional: screenshots are the only operation, so a browser with a visible interface is unnecessary.

```bash
python -m playwright install chromium-headless-shell   # about 270MB
python -m playwright install chromium                  # about 700MB, including the unused full browser
```

At startup, the system tries `chromium-headless-shell` and then the default `chromium`, so machines with the full browser already installed work directly as well.

> Some domestic pip mirrors do not include `playwright` (the Tsinghua mirror was observed to fail). If installation fails, switch to the official index: `pip install playwright -i https://pypi.org/simple`.

> `pillow` is also required: plugins commonly use PIL to validate an image after receiving it (the bilibili plugin's `_validate_image`). Without it, rendering silently fails as “image validation failed.” It is now explicitly listed in `requirements.txt`; previously it happened to arrive as a transitive dependency of `qrcode`.

**Return an empty string rather than raising an exception when rendering is unavailable.** Plugins commonly branch on `if img_path:` to fall back (the upstream remote service can also fail). An exception would only be swallowed by their `except` and retried; in testing on 2026-08-25, the bilibili plugin waited needlessly for 3×2 seconds because of this.

`deploy doctor` checks the rendering backend and provides the installation command. A missing backend produces only a warning because it affects card plugins only; the main conversation pipeline is unaffected.

## Capability Routing and Tool Execution

The system determines which capabilities a request needs (chat / memory / tools) and executes tools **outside** Stella's chat context. See the [Capability System](capability-system.en.md) design and troubleshooting guide.

### Router

| Variable | Default | Description |
|---|---|---|
| `CAPABILITY_ROUTER_ENABLED` | `true` | Global switch. When disabled, behave as “chat normally, read memory normally, do not call tools” |
| `ROUTER_ROUTE_AUTO_CAPABILITIES` | `false` | Whether undeclared plugin tools (`tool.<TOOL_NAME>`) participate in routing competition |
| `ROUTER_RULE_ENABLED` | `true` | Level 0 keyword rules (zero latency, no model call) |
| `ROUTER_SEMANTIC_ENABLED` | `true` | Level 1 embedding semantic routing, reusing the service and model from `MEMORY_EMBEDDING_*` |
| `ROUTER_FALLBACK_ENABLED` | `false` | Level 2 model fallback. Triggered only when L1 lands in the uncertain band |
| `ROUTER_SEMANTIC_THRESHOLD` | `0.50` | Absolute floor for entering the capability candidate list |
| `ROUTER_TOOL_THRESHOLD` | `0.70` | Confidence line required to classify `tool=true` |
| `ROUTER_CAPABILITY_MARGIN` | `0.12` | How far below the top score a matched capability may be (relative-margin clipping). `0` disables it |
| `ROUTER_UNCERTAIN_FLOOR` | `0.55` | Lower bound of the uncertain band. Below it means “definitely no tool needed” and does not enter Level 2 |
| `ROUTER_MAX_CAPABILITIES` | `3` | Maximum capabilities routed in one call |
| `ROUTER_GATE_MEMORY` | `false` | Whether long-term retrieval is actually gated by `route.memory` |
| `ROUTER_TIMEOUT` | `8.0` | Timeout for one decision (seconds). A timeout is handled as a fallback and does not block the reply |

> **Declarations take priority (`ROUTER_ROUTE_AUTO_CAPABILITIES=false`).** For a plugin tool to be triggered in chat, add a `[[capability]]` entry for it in `config/capabilities/*.toml`. An undeclared tool is still registered and can still be executed explicitly, but it does not participate in semantic routing. **Startup logs name the affected tools**, so this is not a silent failure.
>
> This is based on the first-round measurement from 2026-08-24. Tool descriptions are instruction sentences written for a decision-maker that sees all tools (`"call this when the user asks about X"`). Using them as semantic prototypes against the user's **question** produces almost no separation among tools in the same domain. The comparison used 5 bgm/bilibili tools, 12 cases, and real embeddings:
>
> | | Tool false positives | Wrong top choice | Irrelevant tools executed | Negative-sample threshold margin |
> |---|---|---|---|---|
> | Automatically derived (tool descriptions as prototypes) | 1 | 2 / 5 | 13 times | **−0.024** |
> | Explicit declarations (Chinese examples as prototypes) | 0 | 0 | 0 times | **+0.141** |
>
> Setting it to `true` restores the old behavior where installing a plugin makes it routable, but **three thresholds must be lowered at the same time**: automatically derived scores are about 0.2 lower overall (positive samples reach only 0.61~0.71), so without adjustment the tool silently never triggers.

**The four thresholds are one set.** They were calibrated on 2026-08-25 with `qwen3-embedding-0.6b` on 12 cases, assuming the capability has Chinese `examples`. The measured distribution was negative-sample upper bound `0.559` and positive-sample lower bound `0.851`. Reproduce it with:

```bash
python -m capability.router.benchmark --cases capability/router/benchmark/acg.json
```

`ROUTER_TOOL_THRESHOLD=0.70` is the midpoint of the two distributions, leaving margins of +0.141 / +0.151 on the two sides. It was not raised further even though false-positive tools cost more, because only 1 sample was a real online user message and raising it would first sacrifice recall for real users.

`ROUTER_CAPABILITY_MARGIN` addresses **riding-along capabilities**: once `tool=true`, every capability above the absolute floor is **executed once**, and its result is placed in the prompt as “real data; use it as authoritative when answering.” In the first-round measurement, “recommend some new anime” therefore invoked both the daily broadcast schedule and Bilibili trending videos. **The absolute floor cannot replace this**: correct capabilities scored 0.851~0.911, while riding-along capabilities scored 0.616~0.743, above any floor that would avoid killing positive samples. Only relative margin separates them; the measured gap between the correct capability and the runner-up was 0.155~0.336.

`ROUTER_MAX_CAPABILITIES` is a latency valve. Each matched capability is an independent constrained agent call in Comes, and each waits behind the gate of the endpoint bound to the `PLUGIN` role (in a fully local setup this is `LOCAL`, shared with chat; see [LLM Resource Scheduling](#llm-resource-scheduling)). Without a limit, one message could stall replies for the entire group.

> **One class of false positives can be fixed only by Level 2.** Cosine similarity cannot distinguish “state X” from “request X”: “I have recently been following new anime” scored 0.835 in testing and was highly similar to the example “What new anime is worth following?” Raising the threshold cannot fix it because the positive-sample floor is 0.851, leaving only 0.016 of margin. This remains in `capability/router/benchmark/acg.json` as a known failure.

> **`ROUTER_GATE_MEMORY` is disabled by default; do not enable it casually.** If the Router incorrectly sets `memory=false`, Stella silently loses long-term memory for that round: no exception is raised and the reply is unaffected, but “it suddenly does not remember you.” This is the same class of defect as the 2026-08-17 incident where all `AT_MENTION` values were 0: silent, difficult to notice, and consequential. Before enabling it, run the benchmark and confirm that **memory false negatives are 0**:
>
> ```bash
> python -m capability.router.benchmark              # Full pipeline (requires an embedding service)
> python -m capability.router.benchmark --rules-only # Level 0 only; suitable for CI
> ```
>
> Exit code 0 means it is safe to enable. The report counts four error classes separately rather than deliberately combining them into one accuracy number, because an aggregate can hide high-cost errors in the average.

`ROUTER_FALLBACK_ENABLED` is disabled by default to save 27B inference resources. In the default fully local configuration, Level 2 (the `ROUTER` role) shares the `LOCAL` endpoint slot, model, and gate with main chat. Run L0/L1 for a while and measure accuracy with the benchmark before deciding. Pointing `ROUTER` to a cheap online endpoint removes this concern.

### Comes

| Variable | Default | Description |
|---|---|---|
| `COMES_ENABLED` | `true` | Global tool-execution switch |
| `COMES_SYSTEM_PROMPT` | see `.env.example` | Executor persona; intentionally different from Stella's persona |
| `COMES_MAX_TOOL_STEPS` | `5` | Maximum tool-call rounds per task |
| `COMES_TOOL_TIMEOUT` | `60` | Timeout for one tool call (seconds) |
| `COMES_TASK_TIMEOUT` | `90` | Total timeout for one task (seconds), including model round trips |
| `COMES_SUMMARY_MAX_CHARS` | `300` | Maximum summary length inserted into Stella's prompt |
| `COMES_DIRECT_CALL_NO_ARGS` | `true` | Skip the LLM and call directly when there is one no-argument tool |
| `COMES_PROVIDER_FAILURE_THRESHOLD` | `3` | Number of consecutive failures before backing off one provider. `0` means no backoff |
| `COMES_PROVIDER_RECOVER_SECONDS` | `600` | Backoff recovery time (seconds) |

`COMES_MAX_TOOL_STEPS=5` is smaller than `ASTRBOT_LLM_MAX_TOOL_STEPS=10`: Comes performs targeted execution for one capability, and more than 5 rounds usually means the model is looping. `COMES_TOOL_TIMEOUT=60` is much shorter than `ASTRBOT_LLM_TOOL_TIMEOUT=120`: Comes is on the main chat path while the user waits for a reply, so one tool cannot hold it for two minutes.

Provider backoff is a **time window**, not a permanent disable. External API fluctuations are normal for plugin dependencies; permanent disablement would permanently turn off a capability after one network fluctuation, without an error, showing only as “this feature later stopped working.”

### Capability Declarations

`config/capabilities/*.toml` uses the **filename as the domain**. See `config/capabilities/information.toml.example` for the format and field-by-field explanation. A real declaration shipped with the repository is `config/capabilities/entertainment.toml` for the 5 tools from the bilibili/bgm plugins; it can be copied as a template.

**Declarations are no longer optional** since `ROUTER_ROUTE_AUTO_CAPABILITIES=false`: undeclared plugin tools are still registered and can still be executed explicitly, but do not participate in semantic routing. Startup logs identify tools in this state.

| Field | Used for | How to write it |
|---|---|---|
| `examples` | Prototype corpus for Level 1 semantic matching | **How users would ask**, written as Chinese questions. Do not copy the tool description, which is an instruction sentence for the decision-maker (“call when the user asks about X”); its form differs from a question and cannot distinguish tools in one domain |
| `keywords` | Level 0 literal matching | Noun phrases. A match decides immediately with zero latency and avoids one embedding encoding |
| `providers` | Comes execution | **Tool names** in `llm_tools`, not plugin names. Find them in the startup log's “registered function tools” list |

> `keywords` must **never be guessed from `examples`**. Chinese has no word boundaries: candidates split from “will it rain” include both “rain” and “will not,” and the latter matches almost any sentence (“I don't know how to use this software” → check the weather). Level 0 handles high-confidence requests; guessed words do not meet that standard.

Two lessons from measurement:

- **Use `keywords` sparingly, but include the ones that matter.** The L1 score for “today's broadcast schedule” is only 0.641, below the 0.70 confidence line and therefore likely to be missed. The `anime.schedule` keyword “broadcast” catches it with zero latency. Conversely, use “new anime” rather than “new anime recommendation” as the `anime.recommend` keyword; otherwise “I have recently been following new anime” would be sent directly to the lookup by Level 0.
- **Do not give `keywords` to capabilities that need parameters to execute.** `anime.search` needs a search keyword and `video.dynamics` needs a UID. Level 0 cannot obtain those parameters; deciding early only makes Comes guess.

### Capability Query

| Variable | Default | Description |
|---|---|---|
| `CAPABILITY_QUERY_ENABLED` | `true` | Whether a group member can @-mention the bot and ask "what can you do" / "what features do you have" and have Stella list the currently routable capabilities |

On by default: undeclared plugin tools not participating in routing is **deliberate**, but if users have no way to learn that, the symptom degrades into "I installed the plugin and it is never called" — the one problem in this layer that used to require reading the boot log to diagnose. The reply does not go through a model (it reads the registry and formats text directly), so it costs no tokens.

**Permission split**: regular members see the routable capability list and a *count* of plugin tools without a declaration; the source tier, provider health and the **specific names** of undeclared tools are troubleshooting information and are shown to admins only (`PROACTIVE_TOGGLE_ADMINS`, or the group owner/admins).

The same data has two other exits: `python -m deploy capabilities [--json]` (a table, including a "why not routable" column) and the `capabilities` block of `GET /stella/status`. **The response body carries structured fields only**, no `description` or `examples` free text — see [Local Status API](#local-status-api) for that constraint. For field meanings and how the three exits relate, see [Plugin Specification §14](plugin-spec.en.md#14-capability-query).

## OneBot Connection

The Bot communicates with NapCat through a OneBot V11 WebSocket. **NapCat must be logged in first**: install [NapCatQQ Desktop](https://github.com/NapNeko/NapCatQQ-Desktop) and complete QQ login. The Bot no longer manages the NapCat process; automatic login falls back to QR-code scanning, so a person must be present for login
(see `design_docs/deprecated_napcat_manager.md`).

| Method | Bot side (`.env`) | NapCat side (WebUI network settings) |
|---|---|---|
| Reverse WS (recommended) | `HOST` + `PORT` (NoneBot default `0.0.0.0:8080`), with the reverse WS endpoint fixed at `/onebot/v11/ws` | Add a `WebSocket client` and set the URL to `ws://<BOT_ADDRESS>:<PORT>/onebot/v11/ws` |
| Forward WS | `ONEBOT_WS_URLS` (JSON array) + `ONEBOT_ACCESS_TOKEN` | Enable the `WS server` and note its listening address and token |

If both sides configure an access token, the values must match. The relevant environment variables are at the top of `.env.example`.

## Port Usage Overview

**Stella listens on only one port**: the reverse WS endpoint and status interface reuse the same HTTP server (NoneBot's FastAPI app), so no extra port is added. Check this table first when troubleshooting network problems:

| Port | Owner | Listener | Configuration |
|---|---|---|---|
| 8080 | **Stella's only listening port** | This project | `PORT` |
| 1234 | LM Studio | External program | `LM_STUDIO_BASE_URL` |
| 6099 | NapCat WebUI | External program | NapCat side |
| 3001 | NapCat forward WS server | External program (forward mode only) | `ONEBOT_WS_URLS` |
| 8765 | Installer frontend preview | Development `stella-installer/serve.bat` | Not included in Release |

## Local Status API

`deploy status` and the desktop GUI read **in-process** status from `http://HOST:PORT/stella/status` (link health, scheduler queue depth, today's token usage, the capability inventory, and uptime). External processes cannot obtain those data directly, while an HTTP endpoint naturally means “if it cannot connect, it is not running.”

| Configuration | Default | Description |
|---|---|---|
| `STELLA_STATUS_API_ENABLED` | `true` | Whether to register the status route |
| `STELLA_STATUS_API_PATH` | `/stella/status` | Route path (change it only if it conflicts with a future route) |

**Only loopback requests are accepted** (`127.0.0.1` / `::1` / `127.x.x.x` / `localhost`), and the response contains neither credentials nor group-chat content. `allowed_group_count` gives a count rather than group numbers, `usage` gives counts and ratios only, never prompts or model output, and `capabilities` gives structured fields only, without the `description` and `examples` free text from the declarations. `HOST` may be set to `0.0.0.0` when NapCat is on another machine, which exposes the route to the LAN. See the “Local Status API” section of `architecture.en.md` for the design.

### Security Verification: Loopback-Only Access with `HOST=0.0.0.0`

`HOST=0.0.0.0` makes Stella listen on all network interfaces, but `/stella/status` checks at the application layer whether `request.client.host` is a loopback address. Non-loopback requests always return `403 {"error":"forbidden"}` (implemented by `stella_project/plugins/bot_main/status_api.py:_is_loopback`).

Measured with (`PORT=8080`, `HOST=0.0.0.0`):

```bash
# Local loopback → 200
curl -i http://127.0.0.1:8080/stella/status
# HTTP/1.1 200 OK
# {"version":"2.6.0","pid":1234,"uptime_seconds":...}

# LAN IP on the same host → 403 (simulates another machine on the LAN)
curl -i http://192.168.1.20:8080/stella/status
# HTTP/1.1 403 Forbidden
# {"error":"forbidden"}

# IPv6 loopback → 200
curl -i http://[::1]:8080/stella/status
# HTTP/1.1 200 OK
```

Thus, even when `HOST=0.0.0.0` exposes Stella to the LAN, external machines cannot use the status interface to probe runtime information or credentials. `deploy status` and the GUI always connect through `127.0.0.1` and are unaffected.

## Graceful Shutdown

| Configuration | Default | Description |
|---|---|---|
| `SHUTDOWN_GRACE_SECONDS` | `30.0` | Maximum time for the Bot to wait for in-flight tasks (consolidation/compression) to finish during shutdown (seconds) |
| `STELLA_STOP_SENTINEL` | `.stella-stop-request` | Stop-request sentinel path (`deploy stop` writes it; the in-Bot watcher observes it and exits); change it to a writable location if the project directory is read-only |
| `STOP_WATCH_INTERVAL_SECONDS` | `0.5` | Sentinel polling interval (seconds) |

Shutdown flow: deploy writes the sentinel → the in-Bot watcher detects it and triggers uvicorn graceful shutdown (`on_shutdown` → consolidation cleanup) → timeout fallback signal → hard-kill fallback. There is no `POST /shutdown`: `status_api` is read-only, and adding a write endpoint would create an unauthenticated remote shutdown that could be triggered from the LAN. See the “Stop Flow (Sentinel First)” section of development.en.md.

## Link Monitoring

| Configuration | Default | Description |
|---|---|---|
| `LINK_MONITOR_ENABLED` | `true` | Whether to enable link monitoring |
| `LINK_MONITOR_TIMEOUT` | `300` | Perform one active health probe only after more than this many seconds have passed since **any** OneBot event, including heartbeat meta-events |
| `LINK_MONITOR_CHECK_INTERVAL` | `60` | Scheduled check interval (seconds) |
| `LINK_MONITOR_ALERT_INTERVAL` | `300` | Alert throttling (seconds): do not repeat the same error during a disconnection |

**It alerts but does not restart.** Login risk controls make automatic restarts ineffective because automatic login falls back to QR-code scanning. Process management therefore provides no benefit (see `design_docs/deprecated_napcat_manager.md`). The Bot only monitors the link and provides troubleshooting guidance; NapCat startup, shutdown, and login are handled manually in NapCatQQ Desktop.

> **Silence is not a disconnection.** NapCat periodically sends `meta_event.heartbeat` (15s by default), and heartbeats continue when nobody is talking in a group. After a timeout, the Bot actively calls `get_status()` once for confirmation: a successful probe means only “nobody is talking”; a failed probe is a real disconnection. Registering only `on_message` would misclassify a quiet group as a broken link (the cause of the restart loop on 2026-08-14).

## Tuning Recommendations

| Desired effect | Adjustment |
|---|---|
| Bot is too noisy | Lower `PROACTIVE_PROB_AT_FAST`; raise `PROACTIVE_COOLDOWN` and `PROACTIVE_MIN_MESSAGES_SINCE_SPOKE`; lower `PROACTIVE_AT_QUOTA_BASE`; or have an administrator say “mute” in the group to disable it temporarily |
| Bot is too quiet | Raise `PROACTIVE_PROB_AT_FAST`; lower `PROACTIVE_TOPIC_WARMUP_SECONDS` |
| Bot still talks late at night | Confirm `PROACTIVE_SLEEP_ENABLED=true` and check whether `PROACTIVE_SLEEP_START/END` cover the target period |
| Bot sends several messages after waking | Raise `PROACTIVE_WAKEUP_GRACE_SECONDS` |
| Bot does not remember things | Lower `MEMORY_OBSERVE_LOW_CONFIDENCE`; lower `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`; confirm `PROACTIVE_AT_ENABLED=true` (passive-ingestion output is close to zero) |
| Bot remembers things incorrectly | Raise `MEMORY_CONFIRM_HIGH_CONFIDENCE`; raise `MEMORY_PROMOTE_MIN_OCCURRENCE_PASSIVE`; disable `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` |
| Replies mention irrelevant old topics | Raise `MEMORY_SCORE_MIN`; lower each `MEMORY_LIMIT_*` |
| Bot follows the wrong topic | Raise `RECENT_TAIL_LIMIT` |
| Conversations from hours ago are treated as current | Lower `RECENT_TAIL_MAX_AGE_MINUTES` |
| Too many/few gaps in the tail | Adjust `RECENT_TAIL_GAP_MARK_MINUTES` |
| Memory database is growing | Enable `MEMORY_QUOTA_ENFORCE` (inspect the dry run first); lower `MEMORY_USER_QUOTA` |
| Consolidation is too slow | Lower `CONSOLIDATION_LOCAL_BATCH_SIZE`; switch to a smaller consolidation model |
| Online bill is higher than expected | First inspect **cache hit rate** in the usage panel: a long-term zero means prefix caching is not working (see [Cache Hit Rate](#cache-hit-rate-the-only-way-to-verify-prefix-caching)). If the hit rate is normal, raise `CONSOLIDATION_ONLINE_BATCH_SIZE`, keep `CONSOLIDATION_ONLINE_OVERLAP` at 0, and tighten `LLM_ROLE_CONSOLIDATION_MAX_TOKENS`. **Do not increase `CONSOLIDATION_SCHEDULE_INTERVAL`** |
| Add a hard ceiling to the bill | Set `LLM_DAILY_TOKEN_BUDGET`; the default `pause_memory` action stops only the memory domain, so the group can continue talking |
| Memory suddenly stops updating but chat is normal | The daily budget was most likely exceeded (`python -m deploy doctor` warns and the usage panel names the paused roles); next check whether the pre-filter is skipping repeatedly (raise or clear `CONSOLIDATION_MAX_SKIP_STREAK`) |
| The usage panel is entirely missing | The Bot is not running or the status API is unreachable; “disabled” means `LLM_USAGE_ACCOUNTING=false`, which also disables the budget |
| @ conversations teach the Bot nothing | Run `SELECT source_kind, COUNT(*) FROM group_messages GROUP BY source_kind`; `AT_MENTION` being 0 means @ messages were not stored (see the troubleshooting table in development.en.md) |
| Memory promotes too quickly and quota pressure is high | With `MEMORY_PROMOTE_AT_MENTION_SINGLE_SHOT` active, an @ conversation can promote after one occurrence, which is expected. Inspect dry-run logs with `MEMORY_QUOTA_ENFORCE=false` before tightening it |
| Replies are slower and Scheduler warnings appear in logs | Queueing is heavy on the 27B model because chat + compression + extraction share it; temporarily disable `MEMORY_EXTRACT_ENABLED` or increase `CONSOLIDATION_SCHEDULE_INTERVAL` |
| Link is down / messages are not received | Check `[LinkMonitor]` warnings in the logs and follow their troubleshooting steps. The Bot only alerts and does not restart; NapCat requires manual handling |
| A plugin is installed but never called | The most common reason is **no capability declaration**. The startup WARNING saying “the following N tools have no capability declaration and do not participate in semantic routing” names them. Then check the `routable` count in `[capability][boot] capability assembly complete` (`derived` large and `routable` small indicates this case), and confirm that the tool is `active` |
| Declared `examples` seem ineffective | Confirm the tool ownership: it should point to the declared capability ID, not `tool.<TOOL_NAME>`. Assembly requires declarations to be read before automatic derivation |
| Tools are called out of nowhere / the wrong tool is called | Raise `ROUTER_TOOL_THRESHOLD`; check for overly broad words in `keywords`. If irrelevant tools are **also** executed, lower `ROUTER_CAPABILITY_MARGIN` (that is a riding-along capability, not a wrong selection) |
| A tool should be called but is not | Add Chinese question-form `examples` and `keywords` to the capability; lower `ROUTER_TOOL_THRESHOLD`. Run the benchmark once after changing it before deciding further |
| Replies become clearly slower after enabling tools | Each matched capability is an independent constrained agent call, and all wait behind the `PLUGIN` role's gate (the same gate as chat when fully local). Lower `ROUTER_MAX_CAPABILITIES` or `COMES_MAX_TOOL_STEPS`, or point `LLM_ROLE_PLUGIN_ENDPOINT` to an online slot |
| Every message is about 2 seconds slower than before | One Router embedding encoding. The encoding itself takes only about 70 ms; 2.5 s comes from model swapping when embedding and the 27B chat model share one LM Studio instance. Point `MEMORY_EMBEDDING_BASE_URL` to an independent instance/port, or set `MEMORY_EMBEDDING_GATE=none` so it does not queue |
| “It suddenly does not remember me” | First check whether `ROUTER_GATE_MEMORY` was enabled; run `python -m capability.router.benchmark` to inspect memory false negatives |

Before changing thresholds, run a probe for validation; see the [Development Guide](development.en.md).
