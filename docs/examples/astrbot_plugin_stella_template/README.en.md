# astrbot_plugin_stella_template

[中文](README.md) | English

This executable template is a reusable skeleton with command and tool examples,
an executable reference for the plugin contract, and a fixture for
`tests/test_plugin_check.py`, which expects zero errors/warnings. Imports use
`astrbot.api.*`; Stella supplies them through `astrbot_compat/shim.py`.

| File | Required | Purpose |
| --- | --- | --- |
| `main.py` | Yes | Plugin entry point |
| `metadata.yaml` | Recommended | Name/version/author and optional Stella egress disclosure |
| `capability.toml` | For routed LLM tools | Capability declaration; AstrBot does not read it |
| `_conf_schema.json` | Optional | Configuration defaults |
| `requirements.txt` | With third-party dependencies | Dependency list |

```bash
python -m deploy plugin-check docs/examples/astrbot_plugin_stella_template
```

The validator imports and instantiates the plugin, then reports its 16 checks.
To install, copy it into `<STELLA_HOME>/data/plugins/` and rename it. `/模板`
uses deterministic dispatch; `这段话有多少字` uses semantic routing through
the examples in `capability.toml`.

Match metadata name to the directory and disclose actual egress destinations.
Rewrite capability ID, domain, description, and examples. Write four to six user
questions as examples; instruction-style tool descriptions separate similar tools
poorly. `python -m deploy plugin-scaffold <directory>` generates a draft for review.
Leave Level 0 keywords absent for tools with required arguments, and remove unused
configuration fields.

Use explicit commands for state-changing operations. Keep routed tools read-only
and idempotent. Register background tasks with `self.context.register_task` for
unload/reload cleanup. Raise failures rather than returning failure prose as
successful data, which can contaminate model evidence and bypass provider backoff.
See the [plugin specification](../../plugin-spec.en.md) for the full contract.
