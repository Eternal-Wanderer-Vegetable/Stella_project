# Release Process

[中文](release.md) | English · [Documentation](../README.en.md)

After a tag is pushed, CI (`.github/workflows/release.yml`) automatically packages and publishes six Windows product assets: `Stella-OneClick-Python/Rust-vX.Y.Z-windows-amd64.exe` (single-file installers), `Stella-OneClick-Python/Rust-Offline-vX.Y.Z-windows-amd64.exe` (offline installers, see below), and `Stella-Standalone-Python/Rust-vX.Y.Z-windows-amd64.zip` (Stella-only archives), plus independent assets such as the CLI and the llama backend.

### The OneClick Offline payload

The Offline variants share **the same code and the same profile id** as the online installers; their NSIS resources simply carry an extra `offline/` payload (its presence decides whether the installer resolves artifacts locally or over the network — see `desktop/src-tauri/src/python.rs` and `deploy/bootstrap.py`; since v6 the released installer is built from `desktop/src-tauri`, while the frozen v1 lives in `stella-installer/`). The payload is built in CI by `scripts/build_offline_payload.py` and contains:

- the embedded Python runtime zip (hash parsed from `PY_VER`/`PY_SHA256` in `python.rs` — single source of truth);
- `get-pip.py` (`MANIFEST.json` records its sha256; the installer verifies it and installs pip offline with `--no-index`);
- the full wheel closure of requirements.txt (built in CI with `pip wheel`, which also covers sdist-only packages such as `qrcode_terminal`);
- every component declared by the package catalog (llama.cpp backend / NapCat / the default embedding model; file names equal the catalog `artifact` field, verified through the same catalog-checksum path as online installs);
- playwright's chromium-headless-shell (`PLAYWRIGHT_BROWSERS_PATH` points at the bundled kernel, so rendering needs no download).

The WebView2 runtime is not part of the payload; instead it is embedded into the NSIS installer itself via Tauri's `webviewInstallMode: offlineInstaller` (about +127MB): at install time the registry is checked first — an existing WebView2 is left alone, a missing one is installed silently from the embedded offline package, with no network either way. The default `downloadBootstrapper` needs to download the runtime, which leaves the GUI unable to start on offline machines without WebView2 (real user report, 2026-09), and `embedBootstrapper` still requires internet — `offlineInstaller` is the only truly offline option.

**When touching install-time components, keep the payload in sync**: new catalog components need no payload-script change (it iterates the catalog); new Python dependencies must produce wheels under `pip wheel`; a playwright upgrade must be reflected by the bundled kernel revision (the script installs it live, so it always matches).

### Checklist Before Tagging

1. `python -m pytest tests -q` is fully green
2. `ruff check .` reports no warnings
3. The version in `pyproject.toml` has been updated (CI compares it with the tag and fails immediately if they differ)
4. If configuration items changed, `.env.example` and `docs/configuration.en.md` are synchronized
5. `release_assets/RELEASE_NOTES_TEMPLATE.md` has been updated with this version's notes, and **breaking changes are listed explicitly** (for example, deprecating all `NAPCAT_*` configuration). Note that "make the user lose data" is no longer a valid upgrade strategy: every increment of the schema must include an automatic migration
6. The Release exclusion list is maintained independently of `.gitignore` (see the comments in `release.yml`); when adding runtime artifacts or configuration files, update both the exclusion list and the sensitive-file-check regex
7. **For every new top-level directory, determine whether it belongs in the Release**: development tools (such as `stella-installer/`, the independently distributed Tauri installer) and tool scripts must not be included in the user installation package. Add them to the rsync exclusion list in `release.yml` and the regex for "checking development directories", then run a manual packaging verification
8. `release_assets/start.bat` hard-codes the Python version and SHA256; when upgrading the Python patch version, update both locations, and for a major/minor version change also check the handling of `python*._pth`

Then:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

CI automatically: validates the version -> constructs the release directory (excluding `tests/`, `design_docs/`, `scripts/`, `_deprecated/`, `.github/`, `memory/benchmark/`, etc.) -> copies the four files from `release_assets/` and converts bat/txt files to CRLF -> creates the zip -> creates a GitHub Release.

### Notes on Upgrading Embedded Python

`release_assets/start.bat` **hard-codes**:

- `PY_VER` (such as `3.12.10`)
- `PY_ZIP` (the embed-amd64 package filename, which changes with `PY_VER`)
- `PY_SHA256` (the official checksum from the python.org download page; a wrong value makes installation fail forever)
- The `python*._pth` wildcard in section 6 (`312` in `python312._pth` corresponds to the major/minor version; if the filename no longer matches when changing Python, update it as well)

When upgrading Python, update all four locations together and run `start.bat` completely once locally to verify it (this creates a `runtime/` directory, which is in `.gitignore`).

> **Note**: The released OneClick installer's first-install logic in `desktop/src-tauri/src/python.rs` (`runtime_bootstrap`) reimplements the same process in pure Rust. `PY_VER` / `PY_SHA256` / download-mirror constants must be changed together with `start.bat` (a sync test guards this); the installer does not depend on `start.bat`, which is only a fallback manual installation method. The frozen v1 installer keeps an older twin at `stella-installer/src-tauri/src/python.rs` that is no longer shipped.

> **Encoding convention**: `.bat` files under `release_assets/` use pure ASCII, with internal comments and output uniformly in English. They are still uniformly converted to CRLF at release time to ensure stable parsing by Windows `cmd`. The user-facing `README-快速开始.txt` may continue to use UTF-8 with BOM.

### Three Required Changes for Embedded Python

The Release package uses the Python Embeddable Package as its runtime. It behaves differently from regular Python in three ways, and both bootstrap paths (command-line `start.bat` and the released installer's `desktop/src-tauri/src/python.rs`) must handle them:

1. **`import site` is commented out by default** (in `python3xx._pth`). Unless it is uncommented, dependencies installed into `Lib\site-packages` cannot be imported at all;
2. **When `._pth` exists, Python builds `sys.path` only from that file**, equivalent to using `-E -s`; relative paths in it are resolved **relative to the directory containing `python.exe`**. The default `.` points to `runtime\` rather than the project root, so `runtime\python.exe -m deploy` reports `No module named deploy` (verified on 2026-08-18). A line `..` must be added;
3. **It contains only the standard library, with no `setuptools` / `wheel`**, and the current `get-pip.py` installs only pip (`setuptools`/`wheel` were removed from its defaults long ago). As a result, any dependency that ships **only an sdist and no wheel** cannot be installed -- pip must import `setuptools.build_meta` to build it, reports `BackendUnavailable: Cannot import 'setuptools.build_meta'`, and the entire dependency installation exits with code 2. `pip install setuptools wheel` must run **before** installing `requirements.txt`.

The first two are handled in the "enable site-packages" section, using the `python*._pth` wildcard to match the filename and avoid missing an update when changing the Python major/minor version. The third is handled by the `Installing build tools` section of `start.bat` and `ensure_build_tools()` in `python.rs`; `tests::both_bootstrap_paths_install_build_tools` pins the two paths together so they cannot drift.

> The third issue was a real incident in the 2026-08-26 v3.0.0 pre-release: `qrcode_terminal` has only a source package on PyPI, so installing dependencies in a freshly unpacked release package inevitably failed. **It cannot be reproduced on a development machine** because its `runtime/` acquired `setuptools` from an old version of `get-pip.py` years ago and has continued to reuse it.

**CI cannot catch this class of issue**: import checks on the Ubuntu runner can verify only directory completeness. `._pth` path behavior and the absence of `setuptools` appear only in the real Windows embedded runtime. Therefore, after every change to `start.bat` or `python.rs`, test it once in a **freshly unpacked directory** (do not reuse an already-installed directory; its `._pth` may have been corrected by a previous run and its `site-packages` may already contain setuptools, both of which hide the problem).

> To reproduce a "fresh runtime" on a development machine: temporarily rename `setuptools*`, `wheel*`, `_distutils_hack`, and `distutils-precedence.pth` under `runtime\Lib\site-packages`, then run dependency installation once more.
