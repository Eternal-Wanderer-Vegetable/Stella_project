# Plugin Integration Specification v1.0

[中文](plugin-spec.md) | English

> Note: This document is a translation of the Chinese version. Where the two disagree, `plugin-spec.md` is authoritative.

This document is the specification for **plugin authors**: how to write a plugin that Stella can use in full, and why certain things must be written a certain way. The design process and the trade-offs behind it are recorded in `design_docs/插件接入规范落地方案 v1.0.md`; the runtime mechanics live in [Capability System](capability-system.en.md) and [Architecture](architecture.en.md).

In one sentence: **a Stella plugin = an AstrBot plugin + one optional `capability.toml`**. You do not need to learn a new framework, and you do not need to maintain a separate codebase for Stella.

## 0. Scope and Compatibility Promises

Stella uses `astrbot_compat/` to synthesize [AstrBot](https://github.com/AstrBotDevs/AstrBot)'s plugin API into `sys.modules`, so imports like `from astrbot.api.star import Star` work unchanged inside Stella. The version this layer claims compatibility with is `ASTRBOT_COMPAT_VERSION` (default `4.27.0`).

Three promises:

- **Additive, not a fork.** This specification only adds an **optional file** (`capability.toml`) and **optional fields** (the `stella` section in `metadata.yaml`). No new base class, no new decorators, no new loader.
- **Runs both ways.** A plugin written to this specification still runs on AstrBot unchanged — AstrBot does not read `capability.toml`, and one extra file does not bother it.
- **Not every plugin is guaranteed to work.** The compatibility layer is a reimplementation, not a port; some AstrBot APIs have no counterpart in Stella (see [§11 Compatibility Matrix](#11-compatibility-matrix)). Touching those raises `StellaCompatNotSupported` with the full API name in the message — it never degrades silently into wrong behaviour.

If you only want an existing AstrBot plugin to run on Stella, the three steps in the `README` are enough. This specification targets the case where you want the plugin to work **fully** on Stella — and the difference is concentrated in [§6 The Tool Path](#6-the-tool-path-core).

## 1. A Minimal Working Plugin

```python
# data/plugins/astrbot_plugin_hello/main.py
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class HelloPlugin(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context, config)

    @filter.command("你好")
    async def hello(self, event: AstrMessageEvent):
        yield event.plain_result(f"你好，{event.get_sender_name()}")
```

Drop it into `data/plugins/astrbot_plugin_hello/`, restart, and `@bot /你好` in a group works. Nothing else is required at this point.

A complete template you can copy wholesale lives in [`docs/examples/astrbot_plugin_stella_template/`](examples/astrbot_plugin_stella_template/) — it doubles as this specification's executable footnote (`plugin-check` asserts zero errors and zero warnings on it).

## 2. Directory Layout

| File | Required? | Purpose | Read by AstrBot too? |
|---|---|---|---|
| `main.py` | **Required** | Entry point; must contain a `Star` subclass. A directory without it is skipped outright | Yes |
| `metadata.yaml` | Recommended | `name` / `desc` / `version` / `author` / `repo`; falls back to `@register` arguments, then to the directory name | Yes |
| `capability.toml` | **Required if you have `@llm_tool`** | The capability declaration. Without it the tool still registers, but is **never triggered by chat** ([§6.2](#62-capabilitytoml-and-the-three-tiers)) | No (Stella extension) |
| `_conf_schema.json` | Optional | Schema for user-configurable options, read through `self.config` | Yes |
| `requirements.txt` | Optional | Dependencies. **Not installed automatically** by default (`ASTRBOT_AUTO_INSTALL_REQUIREMENTS=false`); only named in the log | Yes |
| `README.md` | Recommended | Also the best corpus for `plugin-scaffold` when it generates `examples` | — |

The directory name does not have to be a valid Python identifier: the `xxx-master` / `xxx-main` suffixes you get from GitHub's "Download ZIP" are mounted under a legal package name automatically (the log says what it was mounted as). But **the archive itself must be extracted first** — a `.zip` under `data/plugins/` is not loaded, and boot diagnostics list it separately.

Directories starting with `.` or `_` are ignored, which is a handy way to disable a plugin temporarily.

## 3. Choosing Between the Two Paths

Stella has two entirely different trigger paths, and the cost of choosing wrong is asymmetric:

```
User message
  ├─ wake prefix + @bot ──→ command path (@filter.command), deterministic
  └─ ordinary chat ──→ Router decides ──→ Comes executes ──→ tool path (@filter.llm_tool), semantic
```

**Decision tree:**

1. Does this feature **send messages, place orders, change external state, spend money, or delete things**?
   → It must be a `@filter.command`. Do **not** make it a routable tool.
2. Is it a **read-only, idempotent** query (weather, anime schedule, counting characters)?
   → Make it a `@filter.llm_tool` and write a `capability.toml`, so users can ask in natural language.
3. Want both?
   → Write both and share one internal implementation. The template plugin has exactly this shape.

Rule 1 is hard, because **Comes does not ask the user for confirmation before calling a tool**. Once the Router decides a tool is needed, Comes calls it directly inside an isolated, restricted agent — there is no human confirmation step and no "did you mean…?" follow-up. So a routable tool must mean "look something up", never "go do something".

> Compare the cost of one mistake: missing one read-only call costs the user a second question; firing a write-operation tool out of nowhere may actually send a message or change external state. The specification is calibrated to the latter.

## 4. Lifecycle and Load Order

```
bot.py starts
  ↓
install_shim()            synthesize the astrbot.* modules
  ↓
load_all_plugins()        import main.py per directory, instantiate the Star subclass
  ↓                       (the event loop is already running at this point)
initialize_plugins()      await plugin.initialize() one by one
  ↓
capability bootstrap()    read the three declaration tiers → auto-derive → log the assembly
```

Three hooks:

| Hook | When | Constraints |
|---|---|---|
| `__init__(self, context, config=None)` | Immediately after import | **Inside the event loop**, so starting tasks is allowed; but do not do slow IO |
| `async initialize(self)` | After all plugins are instantiated | The recommended place to start background tasks |
| `async terminate(self)` | On disable / reload / shutdown | **5-second timeout** — no slow IO, no waiting on the network |

**Background tasks must go through `self.context.register_task(coro, desc)`** — never a bare `asyncio.create_task(...)`:

```python
async def initialize(self) -> None:
    self.context.register_task(self._poll(), "my_poller")   # ✅
    # asyncio.create_task(self._poll())                     # ❌ cannot be reclaimed on unload
```

Only registered tasks are cancelled on unload and hot reload. A bare task **survives a reload and keeps running**, and nothing raises — what you see is "I changed the code and reloaded, but the old behaviour is still there", or two pollers hammering the same API. Check ⑮ of `plugin-check` scans for this pattern and warns.

The `config` parameter must tolerate `None`: plugins without a `_conf_schema.json`, and plugins instantiated directly in unit tests, both get `None`. Put the default in the code; do not assume the schema was read.

## 5. The Command Path

A command registered with `@filter.command("name")` fires only when **both** the wake prefix and the wake condition hold:

- the wake prefix comes from `ASTRBOT_WAKE_PREFIXES`, default `/` (comma-separated for several);
- in a group the bot must be @-mentioned; private chat is governed by `ASTRBOT_COMPAT_ALLOW_PRIVATE` (default `true`).

So the real usage in a group is `@Stella /你好`.

Which platform events reach the plugin pipeline is decided by `astrbot_compat.pipeline.should_dispatch()`, which has three gates:

1. **No self-echo** — messages the bot sent itself never trigger plugins;
2. **Group allowlist** — only groups in `ALLOWED_GROUPS` are dispatched; private chat follows `ASTRBOT_COMPAT_ALLOW_PRIVATE`;
3. **The message must have content** — the test is "segment count > 0", **not** "plaintext is non-empty".

Gate 3 is written that way for a measured reason: QQ mini-program cards, images, and bare @-mentions all have an empty `get_plaintext()`, so a plaintext test blocks that whole class of message from plugins (measured 2026-08-25) — and those messages are precisely the only input an image-processing or card-parsing plugin ever gets.

Once a plugin handles a message (`priority=2`), Stella's main chat path (`priority=3`) stays out of it, so you never get a second LLM reply stacked on top.

Other listeners not bound by the wake prefix (`@filter.regex`, `@filter.event_message_type`) work as usual, but be aware they see **every message in the allowlisted groups** — full-traffic regex matching in a group chat misfires easily.

## 6. The Tool Path (Core)

This chapter is where Stella differs most from AstrBot. AstrBot puts every tool's schema into every chat request and lets the main model pick; Stella does not (see [§7](#7-the-8k-context-budget-contract)). Instead it uses an embedding to decide "is a tool needed, and which one", then hands the selected tool to an isolated, restricted agent.

The consequence: **whether a tool can be triggered by chat depends on whether you supplied suitable semantic prototype text**, not on whether the tool registered successfully.

### 6.1 Signature and Docstring Contract

```python
@filter.llm_tool("get_weather")
async def get_weather(self, event: AstrMessageEvent, city: str, days: int = 1):
    """查询指定城市未来几天的天气。

    Args:
        city(string): 城市名，如「杭州」
        days(number): 查询天数，默认 1
    """
```

- The signature is fixed: `async def tool(self, event, <params...>)`;
- **Parameter types are read only from the docstring's `Args` section**, never from annotations. `parse_tool_docstring()` accepts only the format above (`name(type): description`, indented under `Args:`); getting the format wrong makes the parameter **vanish silently**, and the model calls the tool without it;
- Supported type spellings include `string` / `number` / `int` / `boolean` / `object` / `array` / `list[string]`;
- A Python default in the signature does **not** make a parameter optional — every parameter listed in the `Args` section is registered as required. Whether a tool has required parameters decides whether you should write `keywords` ([§6.4](#64-how-to-write-keywords));
- The tool name is the argument to `@filter.llm_tool("name")`, defaulting to the function name. That name is what goes into `providers` in `capability.toml`, and **a typo fails silently** (check ⑤ of `plugin-check` exists for exactly this).

### 6.2 `capability.toml` and the Three Tiers

The declaration goes in the plugin root, in a format **identical** to `config/capabilities/*.toml`:

```toml
reviewed = true      # human-review gate, see below

[[capability]]
id = "weather.query"
domain = "information"        # a plugin declaration defaults to the "plugin" domain; be explicit
description = "查询天气信息"
examples = [                  # Level 1 semantic prototype corpus: write how a USER would ask
    "明天天气怎么样",
    "会不会下雨",
    "杭州这几天热不热",
    "帮我看下天气",
]
# keywords = ["天气预报"]     # Level 0 literal terms; optional, and NOT for tools with required params
providers = ["get_weather"]   # tool names in llm_tools, not plugin names
```

**One format, three locations**, highest precedence first:

| Tier | Location | Maintained by |
|---|---|---|
| User | `<data dir>/config/capabilities/*.toml` | the deployer |
| Factory | `<program dir>/config/capabilities/*.toml` | the Stella repository |
| Plugin-supplied | `<plugin dir>/capability.toml` | **the plugin author** |
| (auto-derived) | no file; `tool.<name>` generated at boot | — |

Once a tool is claimed by a higher tier, the matching entry in a lower tier is skipped **in its entirety** (not per-provider — half a capability whose examples and providers no longer agree is worse than a missing one), and the log records which tier displaced it. So a deployer who dislikes the `examples` a plugin shipped only has to drop a declaration with the same id or the same tool name into their own `config/capabilities/`; no need to edit the plugin source.

The whole plugin tier can be turned off: `ASTRBOT_PLUGIN_CAPABILITIES_ENABLED=false`. The default is `true` — zero configuration is the entire point of this specification; the switch exists because "who decides what my bot is allowed to call" should be something the deployer can take back.

**Only declarations from plugins that loaded successfully are read.** A plugin that failed to import registered no tools, so its declaration would create a capability pointing at a tool that does not exist — and such a capability still competes in routing, still eats into the decision margin, and then inevitably fails inside Comes.

**The `reviewed` gate**: a file with `reviewed = false`, and any file with a `.draft` suffix such as `capability.toml.draft`, is never loaded; boot logs a single "there is a draft awaiting review" line. A missing key counts as reviewed (hand-written declarations need not include it). Why it exists is in [§12](#12-self-check-generation-and-release): machine-generated corpus must be looked at by a human before it reaches the Router.

**What happens without a declaration**: the tool registers normally and can still be executed explicitly, but it does not enter `registry.routable()`, so none of the three routing levels can see it — which shows up as "the plugin is installed, the log says it registered, and yet it is never called". Boot emits a WARNING naming those tools. `plugin-check` treats this as an **error**.

### 6.3 How to Write `examples`

`examples` is the Level 1 semantic prototype corpus. **Write how a user would ask, not an instruction aimed at a decider.**

This is the easiest thing to get wrong in the whole design, and the most consequential:

| | Written for | Required shape |
|---|---|---|
| AstrBot's tool `description` | A decider looking at **all** tools at once | Imperative + boundary conditions: "call this when the user asks what anime updates today" |
| Stella's `examples` | Cosine similarity against the user's **question** | How a user would ask: "今天更新什么动画" |

Measured comparison over 12 cases with a real embedding model:

| Prototype corpus | Tool false positives | Wrong top pick | Irrelevant tool executed | Negative-sample threshold margin |
|---|---|---|---|---|
| Tool descriptions (what you get with no declaration) | 1 | 2 / 5 | 13 times | **−0.024** |
| Chinese question `examples` | 0 | 0 | 0 times | **+0.141** |

A negative margin means a sentence unrelated to the tool scores above the confidence line — firing a tool out of nowhere is only a matter of time.

Practical rules:

- **4 to 6 sentences**, each covering a different way of asking (different wording, different sentence shape, some with a place name and some without). Fewer than 3 gets a warn from `plugin-check`;
- Write all of them as colloquial user questions. If they contain phrases like "when the user", "call this", "this tool", or "used for", they are almost certainly imperative sentences (check ⑧ warns);
- Do not repeat one sentence four times with different punctuation. The prototype vector is the **mean** of all encoded examples; repetition adds no information and only skews the centre;
- Capabilities in the same domain must be distinguishable. When prototypes are within 0.06 of each other, routing is essentially a dice roll — check ⑫ computes that number for you.

If you are stuck, let `plugin-scaffold` write a first draft and edit it ([§12](#12-self-check-generation-and-release)).

### 6.4 How to Write `keywords`

`keywords` are Level 0 deterministic literal terms: a hit decides immediately, with **no second opinion**. So the guiding principle is **when in doubt, leave it out**.

Four rules:

1. **Write noun phrases**, at least 3 characters. 「番剧推荐」 beats 「新番」 — short terms bleed into unrelated sentences;
2. **Never slice keywords out of your `examples`.** Chinese has no word boundaries: slicing 「会不会下雨」 yields both 「下雨」 and 「不会」, and the latter matches almost any sentence (「我不会用这个软件」 → goes and checks the weather). A sliding window does produce good terms, but it always produces bad ones too, and a bad one costs you a tool call out of nowhere;
3. **Do not bleed into another capability's `examples`.** One leaked keyword is one expensive false positive;
4. **No `keywords` for tools with required parameters.** Level 0 only matches literally and **does not extract arguments**, so deciding at Level 0 just makes Comes guess the required value.

The factory declarations contain both sides of this: `anime.search` (required `keyword`) ships no `keywords`; `video.dynamics` makes an exception because its parameters have sensible defaults. Calibrate against those.

Shipping no `keywords` at all is perfectly fine — Level 1 still routes to you, at the cost of one embedding call.

### 6.5 Return-Value Contract

A tool's return value **never enters Stella's persona prompt verbatim**. The chain is:

```
tool return  →  the restricted agent's 8192 window  →  summarizer (≤ COMES_SUMMARY_MAX_CHARS, default 300 chars)  →  Stella's prompt
```

Two consequences:

- **Do not dump thousands of characters of JSON.** It first has to fit into the restricted agent's own 8192-token window; anything past the truncation point is as good as never returned;
- **Return human sentences.** What reaches the prompt is that 300-character summary, and summarizing a blob of structured data works far worse than summarizing "杭州明天多云，18~26℃".

Returning `None` means "nothing to return, or I already replied to the user directly".

### 6.6 Failure Contract (the Easiest Thing to Get Wrong)

**Raise on failure. Do not `return "query failed: …"`.**

```python
# ✅
if resp.status_code != 200:
    raise RuntimeError(f"天气 API 返回 {resp.status_code}")

# ❌
if resp.status_code != 200:
    return "查询失败：接口超时了"
```

This is not a style preference. A raised exception is wrapped by `agent.execute_tool` into `f"error: {e}"`, and `summarizer.is_error()` detects failure by that `error:` prefix. Return a plain string instead and **three things happen at once**:

1. The string does not start with `error:` → it is treated as **successful output**;
2. So it is labelled "information just retrieved (real data, answer based on this)" and enters Stella's prompt → Stella **relays your failure message to the user as fact**;
3. Provider health **records no failure** → the consecutive-failure backoff (after `COMES_PROVIDER_FAILURE_THRESHOLD` failures, backing off for `COMES_PROVIDER_RECOVER_SECONDS`) never fires, and a broken tool keeps getting called.

The exception message goes into the log, so say what broke: `raise RuntimeError("和风天气 403，API key 可能过期")` is far more useful than `raise RuntimeError("失败")`.

### 6.7 Timeouts

Tool execution times out at `COMES_TOOL_TIMEOUT`, default **60 seconds**; the whole task at `COMES_TASK_TIMEOUT`, default 90 seconds.

This chain hangs off the main chat path — **the user is waiting in the group right now**. 60 seconds is a ceiling, not a budget; a tool that feels normal returns within 5 seconds. For genuinely long work, use the shape "reply immediately with 'looking into it' + a background `register_task` + `StarTools.send_message` when done"; do not leave the user in a synchronous wait.

### 6.8 Direct Call With No Arguments

A tool with no required parameters skips one model round trip and is called directly by Comes (`COMES_DIRECT_CALL_NO_ARGS=true`, on by default), saving one LLM call and its latency.

This means **side effects of argument-less tools happen sooner**, which reinforces [§3](#3-choosing-between-the-two-paths): write operations do not belong in tools.

### 6.9 One Capability, Several Implementations

A single `capability` may list several `providers` (say two different weather plugins). Selection follows `priority`; a failing provider is recorded and briefly backed off, and the next one takes over automatically.

So a second provider really does buy fault tolerance — but only given [§6.6](#66-failure-contract-the-easiest-thing-to-get-wrong): failures must raise, or the backoff never fires and the fault tolerance is fictional.

## 7. The 8K Context Budget Contract

Stella's working window is **8192 tokens**, and that number dictates the whole tool design.

| | AstrBot | Stella |
|---|---|---|
| How a tool gets picked | Every tool schema goes into every chat request; the main model picks | An embedding compares prototype vectors; only the chosen tool goes to the restricted agent |
| Context cost of N tools | N × 60~120 tokens per request, **grows linearly** | N prototype vectors, encoded once and cached on disk by registry version; **the chat window does not grow** |
| Cost as N grows | With enough plugins, ordinary conversation no longer fits | Same-domain tools get more likely to be confused |

Two conclusions to remember:

- **Neither tool descriptions nor raw return values enter the persona prompt.** What you write in `description` does not shape how Stella talks, and you cannot use it to pass instructions to Stella;
- **The cost changed form, it did not disappear.** The more you install, the more capabilities in one domain compete — so the distinguishability requirement in [§6.3](#63-how-to-write-examples) is not fastidiousness, it is where this design pays its bill.

## 8. Rendering Contract

`Star.html_render(tmpl, data)` / `text_to_image(text)` / `t2i(...)` render through a **local Chromium**. The first time an image is needed, roughly 270MB of browser is downloaded in the background, and rendering is unavailable until it finishes.

Two differences from upstream that plugins must handle:

1. **A local file path is returned, not a URL.** `return_url=True` is deliberately ignored — upstream that branch returns a URL from a remote t2i service, and Stella does not send chat content off the machine. Feed the path to `event.image_result(path)` or `chain.file_image(path)` and it works. **Do not use `url_image(path)`** — that function raises `ValueError` on a local path (check ⑭ of `plugin-check` greps the source for `url_image(`);
2. **Unavailable means an empty string, not an exception.** No browser, download still running, template error — all return `""`. So a plugin must have a fallback branch:

```python
img = await self.html_render(TMPL, data)
if img:
    yield event.image_result(img)
else:
    yield event.plain_result(self._render_as_text(data))   # required
```

Returning an empty string rather than raising is deliberate: plugins commonly wrap rendering in a `try` and retry, so an exception would just be swallowed and retried three times to no effect, whereas an empty string makes the most common idiom, `if img:`, fall into the fallback naturally.

## 9. Configuration and Data

**User-configurable options**: declared in `_conf_schema.json`, read through `self.config`.

```json
{
    "max_items": {"description": "max_items", "type": "int", "hint": "how many entries at most", "default": 10}
}
```

```python
limit = 10 if self.config is None else int(self.config.get("max_items", 10))
```

Always use `.get(key, default)` and handle `self.config is None` — unit tests and installs without a schema both pass `None`.

**Persistence**:

| Purpose | API | Location |
|---|---|---|
| Arbitrary files | `StarTools.get_data_dir()` | `<data dir>/data/plugin_data/<plugin name>/` |
| Small KV (async) | `await self.put_kv_data(k, v)` / `get_kv_data` / `delete_kv_data` | `kv.json` in that directory |
| Small KV (sync) | `self.set_data` / `get_data` + `self.save_data()` | Same file (`set_data` only touches memory; `save_data` is required) |

Do not write data into the plugin's own install directory — an upgrade replaces that directory wholesale.

**Groups versus spaces**: Stella has a notion of "shared spaces" (several groups sharing one memory and persona), but **plugins cannot see `group_shared_space`**. All a plugin gets is `event.get_group_id()`. To isolate data per group, build the key yourself:

```python
await self.put_kv_data(f"subscriptions:{event.get_group_id()}", items)
```

This is deliberate: space membership is memory-system semantics, and a plugin grouping by it would produce a pile of orphaned data the moment an admin merges or splits spaces.

## 10. Privacy and Egress Disclosure

Stella's default posture is that chat content does not leave the machine: deciding whether a tool is needed, compressing tool results, and rendering cards all happen locally. **A plugin is the only component allowed to make outbound requests**, so a plugin that does must say where it goes and why:

```yaml
# metadata.yaml
stella:
  egress:
    - host: api.weatherapi.com
      purpose: query public weather data; only the city name the user mentioned is sent
```

**This is a disclosure contract, not a sandbox.** We do not block undeclared requests, and the specification must say so plainly — the point of `stella.egress` is to let a deployer see "what does this plugin send where" before installing it, backed by community convention and `plugin-check` (check ⑯: imports `httpx`/`aiohttp`/`requests` but declares no `egress` → warn), not by technical enforcement.

Two accompanying requirements:

- Write **what is sent** in `purpose`, not just "queries data". "Only the city name" and "the user's raw message" are very different things to a deployer;
- Do not send raw group messages, user IDs, or message IDs to third-party services. A feature that needs to should say so explicitly in `purpose`, so the deployer can decide whether to install it.

## 11. Compatibility Matrix

The compatibility layer is a reimplementation. Three states:

**① Implemented, behavior matches upstream**

- All `Star` lifecycle hooks, command argument parsing, KV storage
- `@filter.command` / `command_group` / `regex` / `llm_tool` / `event_message_type` / `permission_type` / `platform_adapter_type` / `custom_filter`, all `on_*` hooks, `GreedyStr`
- `AstrMessageEvent` accessors (`get_sender_id` / `get_sender_name` / `get_group_id` / `get_messages` / `get_message_str` / `is_admin` / `is_private_chat` …) and result builders (`plain_result` / `image_result` / `chain_result` / `make_result`)
- `MessageChain` fluent construction, `MessageEventResult`'s `stop_event` / `continue_event`
- Message components: `Plain` / `Image` / `Record` / `Video` / `File` / `Face` / `At` / `AtAll` / `Reply` / `Poke` / `Json` / `Music` / `Share` / `Location` / `Dice` / `RPS` / `Shake` / `Contact` / `Forward` / `Unknown`
- `Context`: `get_registered_star` / `get_all_stars` / `send_message` / `register_task` / `get_platform` / the `activate_llm_tool` family / the provider family / `conversation_manager` / `persona_manager` / `register_llm_tool`
- `StarTools`: `send_message` / `get_data_dir` / the `activate_llm_tool` family
- `AstrBotConfig`, `sp` (preference storage), `FunctionTool` / `ToolSet`

**② Degraded, behavior differs from upstream**

| API | Difference | See |
|---|---|---|
| `html_render` / `text_to_image` / `t2i` | Ignores `return_url`, returns a local path; returns an empty string when unavailable | [§8](#8-rendering-contract) |
| Tools registered by `@filter.llm_tool` | Registered ≠ reachable from chat; needs `capability.toml` | [§6.2](#62-capabilitytoml-and-the-three-tiers) |
| `astrbot_version` in `metadata.yaml` | A mismatch only warns; the plugin still loads | [§15](#15-versioning-and-compatibility-policy) |
| `requirements.txt` | No automatic `pip install` by default; only named in the log | [§2](#2-directory-layout) |
| `Context.llm_generate` / `tool_loop_agent` / `get_current_chat_provider_id` | Raise `StellaCompatNotSupported` when `ASTRBOT_LLM_ENABLED=false` | — |

**③ Raises `StellaCompatNotSupported`**

| API | Why it is absent |
|---|---|
| `StarTools.get_db` / `Context.get_db` | Stella's database is the memory system's private schema, not exposed to plugins |
| `StarTools.get_event_queue` / `Context.get_event_queue` | Dispatch goes through NoneBot; upstream's queue does not exist here |
| `StarTools.get_config` | There is no upstream-style global config object |
| `StarTools.register_web_api` / `Context.register_web_api` | Stella exposes no outward HTTP service (the status endpoint is loopback-only and read-only) |
| `Context.kb_manager` / `subagent_orchestrator` / `knowledge_db_manager` | Knowledge bases and sub-agent orchestration are not implemented |
| `astrbot.api.platform.Platform` / `register_platform_adapter` | Only one platform is supported: OneBot V11 |
| `astrbot.api.html_renderer` / `astrbot.api.agent` | Use `Star.html_render` / Comes instead |
| Sending `Node` / `Nodes` as ordinary message segments | Merged forwarding goes through `send_group_forward_msg`, not a segment |
| A component's `convert_to_file_path()` (when the source cannot be resolved) | With no source file there is no path to return |

Among the third group, those three `Context` attributes raise `StellaCompatUnsupportedAttribute`, which is also a subclass of `AttributeError` — so a plugin probing with `hasattr(ctx, "kb_manager")` gets `False` and degrades gracefully, while direct access still raises a recognizable exception. That double inheritance is deliberate.

## 12. Self-Check, Generation and Release

The full pipeline:

```bash
python -m deploy plugin-scaffold <plugin dir>   # generate capability.toml.draft (optional)
#   → human review: fix examples, take the candidate keywords from the comments if wanted,
#     set reviewed = true, drop the .draft suffix
python -m deploy plugin-check <plugin dir>      # 16 checks; non-zero exit code if any error
python -m capability.router.benchmark           # routing benchmark: confirm the four error classes did not worsen
```

`plugin-check` **imports and instantiates your plugin** (the same thing boot does), and its output says so explicitly. `--json` is for the GUI: the report goes to stdout, logs to stderr.

The 16 checks:

| # | Check | Level |
|---|---|---|
| ① | Missing `main.py` / the directory holds an un-extracted archive | error |
| ② | Import fails / no `Star` subclass / `initialize()` raises | error |
| ③ | A package in `requirements.txt` is missing from the current environment | error |
| ④ | An `@llm_tool` tool is claimed by no declaration's `providers` | error |
| ⑤ | A declared `providers` entry names a tool that does not exist | error |
| ⑥ | Only a `.draft` exists / `reviewed = false` | error |
| ⑦ | Fewer than 3 `examples` | warn |
| ⑧ | An `example` looks like an imperative instruction | warn |
| ⑨ | A `keywords` entry leaks into another capability's `examples` | warn |
| ⑩ | A `keywords` entry is shorter than 3 characters | warn |
| ⑪ | The tool has required parameters yet `keywords` is given | warn |
| ⑫ | Insufficient prototype separation within a domain / negative negative-sample margin | warn |
| ⑬ | A capability id or tool collides with the user / factory tier | info |
| ⑭ | The source contains `url_image(` | warn |
| ⑮ | Bare `asyncio.create_task(` instead of `context.register_task` | warn |
| ⑯ | Imports httpx/aiohttp/requests but declares no `stella.egress` | warn |

The minimum bar for release is **zero errors**. A warn means "please double-check", not "must change" — check ⑩ already has one measured exception in the factory declarations (`anime.schedule`'s 「放送」 is only two characters, and it is what rescues a question scoring 0.641 from under the 0.70 confidence line). The judge is you, not the checker.

> `plugin-scaffold` (generation) and `deploy capabilities` ([§14](#14-capability-query)) are **not implemented yet** as of this specification's release; they are phases 3 and 2 of the rollout plan respectively. `plugin-check` and three-tier declaration loading are available today.

On generation: **generating a draft offline that only takes effect after human review is supported**; silently generating examples from tool descriptions at runtime and feeding them into memory is **not** (that is precisely why `ROUTER_ROUTE_AUTO_CAPABILITIES` defaults to off). The difference is whether there is a file, a reviewer, and a quantified baseline — the `reviewed` gate is how that line is drawn.

The generator's inputs, ranked by information content: the plugin's `README.md` → `@command` names and help text → the `Args` block of an `@llm_tool` docstring → tool `description` and tool name → `metadata.yaml`. Feeding it tool descriptions alone is exactly what produces that −0.024 row. After generation a report is computed with the real embedding model (same-domain separation, each example's cosine against its own capability prototype, negative-sample margin), so "generated quality cannot be verified" does not hold once there is a file, a review, and a baseline.

## 13. Debugging

**Read the log.** Everything about plugins at boot is in `logs/boot_debug.log`: which directories were discovered, whether each loaded, why one failed, the per-tier capability counts, and which tools have no declaration. Routing decisions and tool results are in `logs/stella_thought_logs.md`.

Triage order for **"the plugin is installed but is never called"**:

1. Is the plugin in `boot_debug.log` at all? No → the directory name starts with `.` / `_`, or the archive was never extracted;
2. Did it fail to load? → read the reason; usually a missing dependency (`requirements.txt` is not installed automatically by default);
3. Loaded, but the tool never fires → nine times out of ten `capability.toml` is missing; the WARNING in the log names it;
4. Declared, but still never fires → a tool name in `providers` is misspelled, or a higher tier claimed it. Checks ⑤ / ⑬ of `plugin-check` answer this directly.

**Hot reload** (not implemented yet; phase 4 of the rollout plan): it will be gated by `ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED`, **default off**, triggered by an in-group admin command. By design it can reclaim handlers, tools, capability declarations and the modules in `sys.modules`, but it **cannot** clean up:

- Background tasks started with a bare `asyncio.create_task()` (this is why [§4](#4-lifecycle-and-load-order) requires `register_task`)
- Threads a plugin started, global hooks it registered, monkeypatches, module-level state in third-party libraries
- References to the old instance already held elsewhere

So hot reload is a **debugging convenience, not a restart**. If you suspect the state is unclean, restart.

## 14. Capability Query

> The three surfaces in this chapter are not implemented yet (phases 2 and 4 of the rollout plan). For now, the way to see the capability list is the capability-assembly log in `logs/boot_debug.log`.

Three surfaces, one data source:

- **Ask in the group**: "what can you do", "what features do you have" — the routable capabilities grouped by domain, with a closing line saying how many plugin tools will never be triggered automatically because they carry no declaration. Any member may ask; the source tier, provider health and the specific list of undeclared tools are troubleshooting information and are shown to admins only;
- **`python -m deploy capabilities [--json]`** — as a table: what chat can trigger, what it cannot, which tier each came from, which provider is currently backed off;
- **GUI** — a read-only list over the same payload.

The payload carries structured fields only (id, domain, source tier, routable or not, provider tool names, whether the tool actually exists, backoff state, number of examples) and **no `description` or `examples` text** — the status endpoint has a hard constraint that responses contain no credentials and no chat content, and free text is the one field that could smuggle in a URL or a key. The text itself is right there in those three TOML tiers, locally.

## 15. Versioning and Compatibility Policy

- The `astrbot_version` constraint in `metadata.yaml` **only warns, never blocks**. The layer's claimed version is `ASTRBOT_COMPAT_VERSION` (default `4.27.0`), which states "which upstream version the API surface is aligned to", not "behavior is equivalent line by line" — enforcing it strictly would lock out a great many plugins that work fine;
- The `version` field follows upstream convention and may carry a `v` prefix (`version: v1.6.4`); when absent it is treated as `0.0.0`;
- **This specification is v1.0.** Later versions evolve additively only: new optional fields, new checks. The meaning of an existing field will not change in a minor version. That `capability.toml` shares its format with `config/capabilities/*.toml` is a promise, not a coincidence — it means anything written for one of the three tiers can be moved to another verbatim.

## Related Documents

| Document | Contents |
|---|---|
| [Capability System](capability-system.en.md) | The Router's three-level cascade, the Comes execution layer, runtime details of the layered registry |
| [Architecture](architecture.en.md) | Directory layout, message-processing flow, where the AstrBot compatibility layer sits |
| [Configuration Reference](configuration.en.md) | Every setting mentioned here |
| [Template Plugin](examples/astrbot_plugin_stella_template/) | A complete example you can copy wholesale |
