# Capability System (Capability Router and Comes)

[中文](capability-system.md) | English

> Note: This version of the document was translated from the Chinese version by GPT-5.6 luna.

This document describes Stella's task scheduling layer: the Router determines what capabilities are needed, Comes executes tools, and the two exchange only tasks and results with chat and memory. The design process is documented in `design_docs/Stella 智能机器人架构升级方案：基于 Capability Router 与 Comes 工具执行层的任务调度系统.md` and `design_docs/Capability Router 与 Comes 落地方案 v1.0.md`.

## Why It Is Needed

When making the AstrBot ecosystem compatible, we found that many functional plugins depend on LLM tool calls. If all plugin tool definitions are injected directly into Stella's main chat context, four problems occur at once:

- Each tool schema is about 60~120 tokens; after loading plugins, the 8192-token working window cannot fit a normal conversation;
- Tool descriptions interfere with chat, and the model tends to "find a tool to use" instead of replying;
- The system cannot scale at all as the number of plugins increases;
- Stella's personality and tool logic become tightly coupled.

The solution is to **decouple capabilities and communicate through a task protocol**:

```
                   User Message
                        |
                  +-------------+
                  |   Router    |   Determines which capabilities are needed
                  +-------------+
                        |
         +--------------+--------------+
         |              |              |
        Stella        Memory          Comes
    Personality & response   Memory retrieval  Tool execution
         |              |              |
         +--------------+--------------+
                        |
                  Final Response
```

The four modules **do not share chat context**; they only pass `Task` and `Result`.

## Two Directions of Context Isolation

This is the core of the entire design, and both directions must be blocked:

| Direction | What to block | How to block it |
|---|---|---|
| Stella → Comes | Stella's personality, chat context, and memory | Comes requests contain only `COMES_SYSTEM_PROMPT` + the task objective + the 1~3 tool schemas for the capabilities hit this time |
| Comes → Stella | Tool schemas and raw tool returns | Stella receives only `Result.summary` (one compressed sentence); `Result.data` never enters the prompt |

`Result.data` must also be blocked: a single search can return several thousand characters, and inserting it into the prompt unchanged would push both memory and conversation context out of the window. Tool descriptions pollute the context, and result data does too.

> `summary` is produced only when the task succeeds (`success` / `partial`). When a task fails, the model output is often the restricted agent talking to itself ("I don't think we need to search"). It would be given the title "Information just retrieved (real data)" and sent to Stella, causing Stella to repeat the executor's muttering to the user as fact. This invariant is guaranteed by `Result` itself and does not depend on consumers remembering to check `.ok` first.

## Directory Structure

```text
core/tasks.py                    # Task / Result / TaskGraph protocol (shared by all four modules)
capability/
├── registry.py                  # Capability / CapabilityProvider / registry singleton
├── loader.py                    # config/capabilities/*.toml → registry
├── hooks.py                     # activate_capabilities pre-hook (pipeline integration point)
├── router/
│   ├── __init__.py              # route() three-level cascade entry point
│   ├── types.py                 # Route / CapabilityHit
│   ├── rules.py                 # Level 0: keyword rules
│   ├── semantic.py              # Level 1: Embedding prototype matching
│   ├── fallback.py              # Level 2: stronger-model fallback
│   └── benchmark.py             # Routing accuracy benchmark (determines whether gating can be enabled)
├── comes/
│   ├── __init__.py              # execute / execute_all
│   ├── executor.py              # Capability → Provider → Tool → Result
│   └── summarizer.py            # Result.data → Result.summary
└── adapters/
    └── astrbot.py               # llm_tools → automatic Provider derivation + bootstrap
```

## Task / Result Protocol

```
Task                              Result
- task_id     Task number (DAG/debugging) - status     success / failed / partial / cancelled
- type        chat.respond, etc.           - data       Raw tool return, **does not enter prompt**
- capability  Required capability id       - summary    One compressed sentence, **only this enters prompt**
- objective   Semantic-level objective      - metadata   provider / elapsed time / debug information
- input       Known slots
- dependencies  Dependent task_id values
- constraints  Execution constraints
```

Two conventions are easy to get wrong:

**`objective` belongs to the semantic layer.** Write "query tomorrow's weather in Tokyo", not `call weather_api()`. Which Provider to use and which parameters to fill in are decided by Comes, so changing plugins does not require changing the task-generation side. The implementation directly uses the user's original words as the objective: extracting them only loses information (if "Tokyo tomorrow" is reduced to "check the weather", the city and date disappear, and Comes instead has to guess).

**`status` is unrelated to whether a tool call succeeds.** An API can return normally but find no results; that is `failed`, not `success`:

| Situation | status |
|---|---|
| At least one tool returned substantive non-error content | `success` |
| Some tools succeeded and some failed | `partial` |
| No tool was called / all errored / timed out | `failed` |
| Aborted upstream (`event.is_stopped()`) | `cancelled` |

`failed` and `cancelled` must be separate: the former requires an alert (the tool is broken), while the latter is a normal early exit (a plugin hook called `stop_event`). Mixing them would bury real problems.

## Capability Layers

> A plugin is not a capability; a plugin is merely a way to implement a capability.

```
Capability Domain  →  Capability     →  Provider          →  Tool
information           weather.query     AstrBot weather plugin     get_weather()
```

The registry is the **only** place that knows the "capability ↔ tool" mapping. No other place may assemble this layer itself. It is a module-level singleton (like `star_handlers_registry` and `llm_tools`): putting it in a class or function would cause different import paths to receive separate copies. Once the registry splits, the symptom is "the plugin is clearly installed but the Router cannot route to it."

> The registry singleton is deliberately **not re-exported from `capability/__init__.py`**. An entry-point import such as `from capability.registry import registry` makes the package attribute `capability.registry` change from the submodule into that singleton object. Then `import capability.registry as m` gets the instance rather than the module (`import a.b as c` degenerates into `getattr(a, "b")`). This shadowing occurs only after `__init__` has run, so behavior varies with import order. Always access it with `from capability.registry import registry`.

### Two Registration Paths

**Explicit declaration** in `config/capabilities/*.toml` (**the filename is the domain**; see the `.example` file in the same directory):

```toml
[[capability]]
id = "weather.query"
description = "Query weather information"
examples = ["What will the weather be like tomorrow", "Will it rain"]   # Level 1 semantic prototype corpus; write natural sentences
keywords = ["weather", "temperature", "rain"]                        # Level 0 literal matching; write nouns
providers = ["get_weather"]                                             # Tool name in llm_tools, not the plugin name
```

**Automatic derivation**: at startup, active tools that have not been claimed by any declaration are registered as `tool.<tool name>`, with `description` taken from the tool description. They are registered normally and can still be executed explicitly, but **do not participate in routing by default** (`route_enabled=False`, see below).

Ownership between the two is determined on a "first come, first served" basis, and the **assembly order cannot be swapped**: declarations must be read first, followed by automatic derivation. In the opposite order, automatic derivation would first claim every tool as `tool.<name>`, and declarations would be unable to claim those tools afterward. The carefully written Chinese examples would then never be used. This does not raise an error; it only appears as "routing accuracy did not improve." The order is guaranteed by `adapters/astrbot.py::bootstrap`, which is registered in `bot.py` **after** `initialize_plugins` (a plugin can call `add_llm_tools` in its own `initialize()`, so running earlier would miss it).

### Declaration Priority: Why Automatically Derived Capabilities Do Not Participate in Routing

`ROUTER_ROUTE_AUTO_CAPABILITIES=false` (default). The single execution point is `Capability.route_enabled` + `registry.routable()`; all three routing levels use `routable()` as their candidate set, so one filter covers everything.

The reason is not "English descriptions paired with Chinese users"; plugin tool descriptions are often standardized Chinese. The real mismatch is in **purpose**:

| | Who it is written for | Required form |
|---|---|---|
| AstrBot tool `description` | A decision-maker choosing from **all** visible tools | Imperative sentence + boundary condition: "Call this when the user asks what anime was updated today" |
| Router prototype corpus | Cosine similarity against the user's **question** | How the user would ask: "What anime was updated today" |

The consequence is that tools in the same linguistic domain have almost no distinction from one another. In the first real test on 2026-08-24 (5 bgm/bilibili tools), the sentence "Manager, what is this?" produced 0.443 / 0.412 / 0.388 / 0.386 / 0.385—the scores differed by less than 0.06, while the confidence line at the time was 0.45. It was only 0.007 away from invoking a tool out of nowhere.

Comparison using 12 cases and real embeddings:

| Prototype corpus | Tool false positives | Top-ranked wrong | Unrelated tools executed | Negative-sample threshold margin |
|---|---|---|---|---|
| Tool descriptions (automatic derivation) | 1 | 2 / 5 | 13 times | **−0.024** |
| Chinese-question examples (declaration) | 0 | 0 | 0 times | **+0.141** |

Excluding undeclared tools from routing is **intentional, but not silent**: at startup, a WARNING names the tools in this state and gives two options (write a declaration or set the switch to `true`). Without naming them, the symptom is "the plugin is installed, the log says derivation succeeded, but it is never called," which is extremely difficult to diagnose.

This limitation deliberately is not addressed by generation: machine-generating Chinese examples from tool descriptions requires a model call and the quality cannot be verified. Incorrect examples are worse than no examples (they pull unrelated requests in).

## Router Three-Level Cascade

```
Level 0  Fast rule-based decision     Zero latency, no model call
    ↓ No conclusion
Level 1  Embedding semantics           One encoding (prototype vectors cached by registry version)
    ↓ Falls in the uncertainty band
Level 2  Stronger-model fallback       Disabled by default, handles very few requests
    ↓ Unavailable
Fallback  chat + memory, no tools
```

**Fallback is the only failure destination.** If embeddings are unavailable, the registry is empty, a timeout occurs, or any exception occurs, return `chat=True, memory=True, tool=False`. Routing must never become a hard dependency of the main path. The conservative direction is deliberate: if a tool is missed once, the user can ask again at worst; invoking a tool out of nowhere might actually send a message or change external state.

### Level 0 Short-Circuits Only When It Can Determine "What Is Needed"

It makes a final decision in three cases: a capability keyword hits (with `tool=true` and the capability already determined), the entire sentence is a pure greeting or small talk (`memory=false`), or there is only memory intent and no tool intent (saving one embedding call).

A hit on "help me check" **does not** count as a final decision. What follows might be the weather, a stock price, or an anime; capability selection must be left to Level 1.

Capability keywords **only recognize explicit declarations and never infer from examples**. Chinese has no word boundaries: candidates cut from "Will it rain" include both "rain" and "won't", and the latter would match almost any sentence ("I won't use this software" → check the weather). Sliding-window tokenization can find good words, but it will necessarily find bad words too, and the cost of a bad word is invoking a tool out of nowhere.

Pure small-talk detection must use **whole-sentence matching** with a very narrow set: "Hello, do you still remember my travel plans?" is not small talk. The cost of deciding that memory is unnecessary is asymmetric, so it is better to perform one extra lookup.

### Level 1 Prototype Vectors

A prototype vector is the **mean** of the encodings of all `prototype_texts()` for a capability (examples + description), followed by normalization. The mean is used instead of taking the maximum per item: examples are different phrasings of the same intent, and their mean represents the center of that intent and is more robust to an individual poorly written example. Taking the maximum for each item would let one outlying example skew the recall of the entire capability.

Prototype vectors are cached by **registry version number**. When a new plugin is installed (the registry changes → version increments), the cache is invalidated automatically. Otherwise the new capability would never match. This degradation does not raise an error; it only appears as "the plugin is installed but unusable." Changing the embedding model also invalidates it (both the dimensions and semantic space differ).

The cache is persisted **one item at a time** (write after each capability is computed), rather than only after the whole round completes. After declarations are written, the prototype corpus grows from "one tool description per capability" to "4~6 example sentences + description," and the number of encoding calls during the initial build increases by about 5 times. That build happens inside a user's request, wrapped by `ROUTER_TIMEOUT`. If the entire round were written at once, a timeout would leave nothing behind, and the next message would start over from zero. The symptom would be "the tool fails to trigger for several consecutive rounds" with no error. A capability whose encoding fails is also not considered "finished for this version" and will be retried next time.

At startup, `bot.py` performs one **background** warm-up (`semantic.warmup()`), moving the initial-build cost away from the first message that gets routed. A warm-up failure or timeout only makes the first message a little slower; already computed prototypes remain.

### The Two Filters at Level 1

After `tool=true`, it is still necessary to decide **which capabilities** to execute. There are two filters here with completely different roles (`semantic.select_hits`):

- `ROUTER_SEMANTIC_THRESHOLD` (absolute floor): suppresses long-tail noise;
- `ROUTER_CAPABILITY_MARGIN` (relative gap): keeps only those within the tolerated gap from the highest score.

**The relative gap is necessary; the absolute floor cannot replace it.** In the first real test, the correct capability for "Recommend some new anime" scored 0.911, while the hitchhiking Daily Broadcast / Bilibili Hot capabilities scored 0.689 / 0.678. Those hitchhiking scores were higher than any usable floor value (the floor had to be below the positive-sample lower bound of 0.851 to avoid false negatives). Every hit capability is **executed once independently**, and its result is sent to Stella's prompt with the label "Information just retrieved (real data; use it as the basis for the answer)." Thus hitchhiking is not merely a little wasted latency; it inserts unrelated data into the evidence section. That round consequently added a Bilibili Hot video segment ("seriously watching the son's viewing history") to Stella's prompt, even though the user asked about new anime.

More than one capability may remain after the gap filter. That is a genuine multi-capability request (a sentence with two strong intents), and both should be executed; `ROUTER_MAX_CAPABILITIES` imposes the final cap.

When `tool=false`, the `capabilities` list is **not gap-trimmed**: it is then purely diagnostic information ("how far away from invoking a tool"), and trimming it would hide how close the second and third choices were.

Reuse `EmbeddingService` from `memory/embeddings.py` (caching, L2 normalization, gate serialization governed by `MEMORY_EMBEDDING_GATE`, and failure returning `None` so the caller can fall back); do not create another client.

> `Route.top_score` is the highest score **before filtering** and must be recorded separately. `capabilities` has already been filtered by `ROUTER_SEMANTIC_THRESHOLD`; deriving the highest score from it would make all scores in `(ROUTER_UNCERTAIN_FLOOR, ROUTER_SEMANTIC_THRESHOLD)` read as 0, silently narrowing Level 2's trigger range.

## Comes Execution

```
Task.capability
       ↓  registry.find_providers() (descending priority, excluding providers in backoff)
Provider list
       ↓  Take the corresponding FunctionTool from llm_tools and compose a ToolSet containing only them
ToolSet (1~3 tools, not all tools)
       ↓  Restricted agent: run_tool_loop(provider, req, event)
LLMResponse + req.tool_calls_result
       ↓  summarizer
Result(status, data, summary, metadata)
```

The tool loop reuses `astrbot_compat.llm.agent.run_tool_loop`: it already implements parameter filtering (the model may generate parameters outside the schema; passing them directly to the plugin causes `TypeError`), timeouts, async-generator normalization, and the complete set of lifecycle hooks on which plugins depend. These behaviors were aligned with extensive upstream multi-round testing; rewriting it would certainly omit something. Comes changes only two things: a smaller ToolSet and its own system prompt.

**Sources of `data` and `summary`**: `data` is the `(name, content)` of each `ToolCallMessageSegment` (the raw tool return); `summary` is the restricted agent's `completion_text`—the natural-language sentence it writes after reading the tool output, which is naturally a summary. **Compression no longer calls a model**: spending another 27B round trip on a summary would add another serial wait to the main chat path while the user is waiting for a reply.

**Direct call with no arguments** (`COMES_DIRECT_CALL_NO_ARGS`): when a hit capability has only one Provider and its tool has no required parameters, skip the LLM and call the tool directly. This saves one 27B round trip and makes it impossible to fill in incorrect parameters.

**Provider health**: accounting is tracked at the tool level. After consecutive failures reach `COMES_PROVIDER_FAILURE_THRESHOLD`, the provider enters **time-window** backoff (`COMES_PROVIDER_RECOVER_SECONDS`), during which another provider for that capability takes over. Only tools that were actually called this time are counted. Counting providers that were not selected would let "never selected" slowly accumulate into backoff. Backoff is not permanent disabling: external API instability is normal, and permanent disabling would let one network fluctuation permanently turn off a capability. This would not raise an error; it would only appear as "this feature stopped working well later."

## Integration Pipeline

Pre-hooks execute in **descending** priority order:

```
50  build_context           # Short-term context (summary + tail + session summary), always executes
45  activate_capabilities   # Router decision → parallel {long-term memory retrieval, Comes execution}
```

`build_user_context` is **no longer registered separately**; `activate_capabilities` now owns it. The design requires Memory and Comes to run in parallel. Two independent hooks would run serially, so they must be put into the same `gather`. Registering it separately again would run memory retrieval twice.

`build_context` remains unconditional: short-term context is conversation material and is unrelated to "whether long-term memory should be retrieved."

> **An honest note about parallelism**: resource names for gates are currently endpoint slot names (`registry.gate_of(role)`). With the pure-local default configuration, Comes's LLM call (`gate_of(ROLE_PLUGIN)`) and Memory's embedding encoding (`embedding_gate()` is `auto` and resolves to the local slot) land on the same `LOCAL` gate, so their **model calls** are still serialized FIFO. `gather` provides the real part of the benefit: Memory's SQL/FTS query overlaps with Comes's HTTP wait. This is not fake parallelism, but it is not two GPUs either.
>
> After binding the PLUGIN role to an online endpoint (`LLM_ROLE_PLUGIN_ENDPOINT=ONLINE_CHAT`), this serialization disappears: embedding remains on the local machine by design, so the two no longer share a gate, and `gather` becomes two genuinely parallel model calls. See [configuration.en.md · Endpoint and role configuration](configuration.en.md#endpoint-and-role-two-layer-configuration) for configuration details.

Hooks **must never raise exceptions**; the two branches must not impede each other (`return_exceptions=True`). The capability layer is an incremental feature, so its failure should mean "tools were not used this round," not "Stella stopped talking."

### Platform Handles

When Comes calls an AstrBot tool, the tool handler internally uses `event.send()` / `event.bot.call_action()`, which must be real objects; an equivalent substitute cannot be constructed. Therefore `ChatContext` carries two opaque fields, `raw_event` / `bot`, which `handle_chat` fills in; core does not interpret their types.

Only the @-reply path can provide them. Proactive speech has no corresponding user event, so tool capabilities are naturally unavailable on that path. This is normal and does not raise an error. Command-style intents (`proactive_at` / `proactive_join`) also **do not undergo capability routing**: `ctx.message` is a task instruction for Stella rather than a user request. The presence of the character "check" in "generate a sentence to start a conversation" does not mean the user wants anything checked.

### How Results Return to Stella

The paragraph order in `core/pipeline.py::_compose_prompt` is:

```
{context}

【Information just retrieved (real data; use it as the basis for the answer)】
Tokyo tomorrow: 27℃, sunny, 10% chance of rain.

【Now User(123) says to you】Please check the weather in Tokyo
Please respond to this sentence. The conversation above is background only; do not respond to any other content in it.
```

Tool results are placed between the context and the current input: they are "evidence for answering this sentence" and must be close to the current input. The instruction "Please respond to this sentence" must remain on the last line; otherwise the model will treat it as another piece of background. For command-style intents, the order is: instruction → tool results → context.

Clearly labeling **real data** is necessary. Without the label, the model will treat it as another sentence spoken by someone in the context, then repeat, question, or even contradict it.

## Memory Gating: Why It Is Disabled by Default

When `ROUTER_GATE_MEMORY=false`, the Router still makes its decision and still writes logs and the decision trace, but memory retrieval **still executes unconditionally**.

If the Router incorrectly decides `memory=False`, Stella silently loses long-term memory for that round. No exception is raised and the reply is unaffected; it simply becomes "it suddenly doesn't remember you." This is the same type of defect as the 2026-08-17 incident where all `AT_MENTION` values were 0: silent, difficult to notice, and serious in its consequences.

To enable it, first run the benchmark and confirm that **memory false negatives are 0**:

```bash
python -m capability.router.benchmark              # Full pipeline (requires embedding service)
python -m capability.router.benchmark --rules-only # Test Level 0 only; suitable for CI
python -m capability.router.benchmark --cases my.json
```

The report counts the four types of errors **separately and deliberately does not combine them into a single accuracy score**; combining them would hide high-cost errors in the average:

| Error | Consequence | Severity |
|---|---|---|
| Memory false negative (should read but does not) | Stella suddenly does not remember you, with no error | **High**, the only risk of gating |
| Memory false positive (should not read but does) | One extra retrieval, wasting a little latency | Low |
| Tool false positive (should not call but does) | Calls a tool out of nowhere and may change external state | **High** |
| Tool false negative (should call but does not) | The user asks again | Low |

Exit code 0 means memory false negatives are 0 (gating can be enabled); non-zero means it cannot.

## Troubleshooting

To determine online "why was no tool called this time," look only at these two lines in `logs/stella_thought_logs.md`:

```
- **🧭 Routing decision**: `chat+memory` via `semantic` (capabilities: none, top score 0.31, 42ms)—top score 0.31 did not reach the tool confidence line 0.70
- **🔧 Tool execution**: weather.query → `success` (1 tool call, direct call, 0.83s)
  > Tokyo tomorrow: 27℃, sunny, 10% chance of rain.
```

| Symptom | Check first |
|---|---|
| Plugin is installed but never called | Most commonly, **no capability declaration was written**—the startup log contains a WARNING naming it; next check `routable` in `[capability][boot] Capability assembly complete` (a large `derived` and small `routable` means this); then check whether the tool is `active` |
| Declaration was written but examples have no effect | Whether `registry.claimed_by(tool name)` points to your capability (it should point to the declared id, not `tool.<name>`) |
| Routing decision is always `default` | Whether the embedding service is available (`MEMORY_EMBEDDING_BASE_URL`); whether the registry is empty |
| Tool was called but Stella does not mention the result | Whether `Result.status` is `failed` (failures produce no summary); or whether the tool sent an image directly to the user (successful but with no content that can be relayed) |
| Several tools were called at once, some clearly unrelated | This is **hitchhiking**, not a wrong selection—lower `ROUTER_CAPABILITY_MARGIN`. The individual scores appear under "semantic hits" in the log |
| Replies are slower | Each hit capability is an independent restricted-agent call, and all queue at the gate for the endpoint bound to the `PLUGIN` role (with a pure-local setup, this is the same gate as chat); lower `ROUTER_MAX_CAPABILITIES`, or point `LLM_ROLE_PLUGIN_ENDPOINT` at the online slot |
| Every message takes about 2 extra seconds | The Router's embedding call. The encoding itself measures about 70ms; the 2.5s comes from swapping models in and out when it shares one LM Studio instance with the 27B chat model. Point the embedding service to a separate instance/port |

See [Configuration Reference](configuration.en.md#capability-routing-and-tool-execution) for the configuration option list.
