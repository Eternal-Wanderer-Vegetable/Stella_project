# Environment Setup

[中文](environment.md) | English · [Documentation](../README.en.md)

## Environment Setup

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`requirements-dev.txt` contains development dependencies such as pytest, ruff, and numpy. numpy is used only for vector calculations in the embedding fixture; when it is missing, the relevant tests are skipped rather than failing.

### Developer machine user data lives in `StellaData/`

The `StellaData/` directory under the repository root (globally gitignored) is the local **user data directory** (`STELLA_HOME`):

```text
Stella_project/
  StellaData/          <- your .env, memory database, space configuration, persona, plugin data, and logs
    .env  deploy.answers.toml
    memory/  config/spaces/  system_prompts/  data/  logs/
  bot.py  config/  deploy/  memory/  ...   <- code
```

Rule 2 in `config/home.py` (portable mode) matches it, so the **relative layouts of the repository, release package, and runtime are the same**
they all put data in `StellaData/`; the only difference is which level this directory is attached to.

Existing old working copies (with data scattered at the repository root) are unaffected: Rule 3 in `config/home.py` recognizes the **legacy layout** and uses it in place.
To migrate, move `.env`, `deploy.answers.toml`, `memory/`, `config/spaces/`, `system_prompts/`,
`data/`, and `logs/` into `StellaData/`. All path constants follow `STELLA_HOME`, so no code changes are needed.
`python -m deploy paths` tells you where the current resolution points and which rule was used.

**Do not commit the data directory to the repository**: `.gitignore` contains `StellaData/`, the exclusion list in `release.yml` contains it as well, and `scripts/check_release_layout.py` adds another safeguard before release. All three layers are intentional:
this directory contains the real `.env` and chat history, and once they leave with a release package, they cannot be recovered.
## v2 Control Plane (Panel and Desktop Shell) Development

Three pieces of v2 GUI code live in the repo (see [docs/webui.md](../guides/webui.md)):

```bash
# Panel frontend (Vue 3 + Vuetify 3): dev server proxies to the local bot (8080)
cd dashboard && pnpm install
pnpm dev            # http://localhost:5173
pnpm build          # vue-tsc type gate + vite build → dist/

# Standalone WebUI server (auth/config pages without starting the bot)
python scripts/dev_webui.py --port 8091

# Desktop shell (Tauri 2): fill the embedded panel first, then compile
cp -r dashboard/dist/* desktop/dashboard-dist/
cd desktop/src-tauri && cargo tauri build   # or cargo check for a quick gate

# Forgot the panel admin password
python scripts/webui_reset_auth.py --yes
```

Convention: `webui/` is a leaf package and must **never import
`stella_project.plugins.bot_main`** (host-injection pattern, see
`webui/status_source.py`). When adding a new top-level Python package or
directory, sync `COMMON_DIRS` in `scripts/build_release_package.py` — a
missing payload directory cascades into a WebUI mount failure (2026-09-24
incident).
