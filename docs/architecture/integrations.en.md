# AstrBot Plugin Compatibility Layer

[中文](integrations.md) | English · [Documentation](../README.en.md)

## AstrBot Plugin Compatibility Layer

`astrbot_compat/` lets plugins from the [AstrBot](https://github.com/AstrBotDevs/AstrBot) ecosystem run in Stella **without source changes**. `shim.py` fakes an entire `astrbot.*` module tree and redirects the plugins' `import` statements to the compatibility layer's real implementations. Plugins placed in `data/plugins/` are discovered and loaded automatically.

It has two independent paths; do not conflate them:

| Path | Entry point | Purpose |
|---|---|---|
| **Command dispatch** | `plugin_handler` (priority 2) | Scenarios where plugins respond themselves through `@command` / `@regex` / `@event_message_type` |
| **Tool execution** | Comes → `llm_tools` | Function tools registered by plugins with `@llm_tool`, called on demand by the capability layer |

The dispatch path's wake-up check follows upstream `WakingCheckStage`: every message runs through each handler's filters once, and the filter decides whether to wake up. `should_dispatch()` decides whether the message enters the pipeline (group allowlist + block self-echoes + message is non-empty).

**The compatibility layer does not participate in personality or memory.** Plugins cannot access Stella's system prompt or memory; conversely, plugin tool results are compressed by Comes into one `summary` before entering Stella's prompt. The rationale is the same as the capability layer's context isolation; see [Capability System](capability-system.en.md).

Unsupported upstream capabilities always raise `StellaCompatNotSupported` (rather than silently returning a false value), so a plugin error directly identifies which interface is missing.

**The tool-execution path has one extra step**: registering an `@llm_tool` successfully does not make it reachable from chat — the routing candidate set comes from `registry.routable()`, which needs a capability declaration. Declarations live in three tiers (user `STELLA_HOME/config/capabilities/` > factory `<project root>/config/capabilities/` > shipped with the plugin at `<plugin dir>/capability.toml`) with one identical format; once a higher tier claims a tool, the lower tier's entry is skipped entirely. The plugin tier is gated by `ASTRBOT_PLUGIN_CAPABILITIES_ENABLED` (default `true`) and only scans plugins that loaded successfully. For the full rules on writing a plugin see [Plugin Integration Specification](../reference/plugin-spec.en.md); for the tiers and routing details see [Capability System](capability-system.en.md#four-registration-tiers).

**Hot reload** (`ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED`, default off; once on, an in-group admin triggers it with "@Stella 重载插件 &lt;name&gt;") is a debugging convenience rather than a restart: it can reclaim handlers, tools, capability declarations, the modules in `sys.modules` and the `__pycache__` directories on disk, but not tasks started with a bare `asyncio.create_task()`, threads a plugin started, monkeypatches, or references to the old instance already held elsewhere. That is why the specification requires background tasks to go through `context.register_task` — only registered tasks carry an owner tag, which is what lets a reload cancel just that one plugin's tasks.

### Load Timing and Directory Names

**Plugins are loaded in the event loop** through the `on_startup` hook `_bootstrap_astrbot_plugins()` in `bot.py` (loading + `initialize_plugins()`). This is intentional: upstream AstrBot's entire plugin-loading chain is asynchronous, so starting background tasks with `asyncio.create_task(...)` in `__init__` is a **standard pattern in official plugins** (`astrbot_plugin_bilibili` does exactly this). Loading synchronously during import would make such plugins fail with `RuntimeError: no running event loop`, leaving users with the only option of changing plugin source, exactly contrary to “run without source changes.” Do not break either constraint: the hook must be `async def` (NoneBot sends a synchronous hook to a thread pool, which likewise has no running loop), and it must be registered before `_bootstrap_capabilities` (startup hooks execute **serially** in registration order).

**Directory names do not have to be valid Python module names**. When `data/plugins/<directory>` cannot be installed as `import data.plugins.<directory>.main` (the `-master` / `-main` suffix produced by GitHub “Download ZIP” is the common case; upstream `git clone` installations do not encounter it), `loader.py` normalizes the directory to a valid module name and mounts it as a package by file path (`__path__` points back to the real directory), so the plugin's `from .x` / `from ..y` imports resolve normally. If two directories normalize to the same name, a short digest suffix distinguishes the second; they are never allowed to replace each other. When `ASTRBOT_PLUGINS_DIR` points outside the project, the same mounting path is used.

The metadata's `root_dir_name` is always the actual directory name on disk, while the plugin data directory follows the metadata `name`, so renaming `xxx-master` to `xxx` afterward does not lose subscription data.

### HTML → Image Rendering

Many plugins create result cards from Jinja2 templates + CSS and render images through `Star.html_render`. The implementation is in `astrbot_compat/render.py`, backed by **local Chromium** (playwright).

**Why not use a remote service**: upstream AstrBot sends HTML to a remote t2i service by default. Templates contain group-member nicknames, dynamic text, and avatar URLs, all of which are chat content. In a fully local deployment, every other component runs locally, so rendering has no reason to be the one component that sends data outside the machine. The same applies to deployments using online models: the outbound recipient is a provider the user selected and pays for; there is no reason to add another rendering service they did not choose.

**Why a browser engine is required**: plugin templates commonly use flexbox, linear gradients, border-radius, and box-shadow (one plugin was measured at 350–460 lines of CSS in each of three templates). Tools such as weasyprint lack complete flex support and produce broken layouts. A broken layout is worse than a fallback because it appears to have “succeeded.”

Dependencies have two layers: the `playwright` pip package is included in `requirements.txt` (a few MB); the browser engine is about 270MB and is downloaded in the background **the first time rendering is actually needed**. During the download, plugins fall back to plain text as usual; once installed, rendering takes effect automatically without a restart. Installing only the headless shell is deliberate: the system only ever takes screenshots and does not need a headed browser.

When rendering is unavailable, it returns **an empty string rather than raising**: plugins generally branch on `if img_path:` to fall back (the upstream remote service can also fail), while raising would only be swallowed by their `except` and retried.

The browser is reused as a single instance (a cold start takes 1–2 seconds, and this is synchronous waiting on the main path); `bot.py` registers `on_shutdown` to close it. Playwright starts independent node + chromium child processes, which Python exit does not take down.

See [Configuration Reference](../reference/configuration.en.md#html-to-image-rendering-plugin-cards) for configuration options.
## Local Status Interface

`deploy status` and the desktop GUI need to read process-internal state (`link_status()` and scheduler queue depth), which external processes cannot access.

**Why HTTP instead of a state file**: state files can become stale. After the Bot crashes, the file remains and reports a false “running” state. An HTTP endpoint naturally means “unreachable means not running,” and also covers the intermediate state where the process is running but its HTTP service is not yet up (`api_reachable=false`; the GUI uses this to display “Starting…”).

**Why not add a port**: NoneBot already runs FastAPI/uvicorn, and its reverse WS endpoint `/onebot/v11/ws` is provided by that server. The status route is mounted on the same app (`GET /stella/status`), so Stella still has only one listening port (`PORT`).

**Implementation**: `stella_project/plugins/bot_main/status_api.py`. `setup_status_api()` is called in ai_gateway's startup section (after extension loading); `build_payload()` aggregates `link_status()`, `core.llm.snapshot()`, `usage_store.usage_snapshot()`, `capability.inventory.snapshot()`, the skills runtime status, and version/process information, returning `{version, instance_id, pid, uptime_seconds, allowed_group_count, link, scheduler, usage, capabilities, skills}` plus two conditional keys: `runtime` (Runtime Contract status, present only when fetched) and `chat_engine` (the conversation-engine surface: mode/keys/inflight — a health snapshot of the facade, the sole engine; structured fields only). Consumers are `_fetch_live_status()` in `deploy/process.py` (loopback query, 1-second timeout) and the GUI/WebUI panel.

**Security constraints**: `HOST` may be `0.0.0.0` (required when NapCat is on another machine), in which case the route is exposed to the LAN. There are two protections: 1. accept only requests from loopback addresses and return 403 for others; 2. keep credentials and group-chat content out of the response. `allowed_group_count` provides a count, not group numbers, and `usage` contains only counts and ratios (token count, call count, cache hit rate, slot name, and model ID), never prompts or model output. `capabilities` contains structured fields only (capability id, domain, source tier, whether it is routable, provider tool names and health, `examples` count), without the `description` and `examples` free text from the declarations — those two fields are the only place that could smuggle in a URL or a key, and keeping them out of the response body means no extra guard is needed for them. `tests/test_status_api.py` locks this constraint in as an assertion: it serializes the real output of `usage_snapshot()` and fails if `api_key` / `Bearer` / `http://` appears.
## Extension Mechanism

Every module/package under `extensions/` that provides `setup(pipeline)` is loaded automatically at startup. Extensions can register Hooks, inject implementations, and start their own scheduled tasks.

`link_monitor` is the reference implementation: at import time it registers an `event_preprocessor` (refresh heartbeat for any OneBot event), two driver hooks (`on_bot_connect` / `on_bot_disconnect`), and its own scheduled task (actively probe after an event timeout, alert on probe failure without restarting). An extension can be integrated without changing the main business program.
## v2 Control Plane (WebUI and Desktop Shell)

The management panel shared by the browser and the desktop shell:
`dashboard/` (Vue 3 + Vuetify 3) is the frontend, `webui/` (FastAPI
sub-app) hangs off the same ASGI port as NoneBot — **no extra port**;
`desktop/` (Tauri 2 shell) embeds the same panel and works offline via a
narrow contract (start/doctor/config). Auth, first-run wizard and
troubleshooting: [docs/webui.md](../guides/webui.md). The v1 installer
(`stella-installer/`) is frozen at tag `gui-v1-final`.
