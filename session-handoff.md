# Session Handoff

## Current Objective

- CI-106：PR #106 flow-closure 的 GitNexus native heap corruption 已修复并推送；提交 `c22dcecdde227564cecd6a7290f246ae43ba3efa`，对应所有 hosted checks 通过。
- RELEASE-620：Stella 6.2.0 已正式发布，hosted release workflow 与发布后回读全部通过。
- Branch: `codex/release-6.2.0`; release commit `6c62fdc3f7ae010896f7f308e37f356eb3c20581`, based on online `main` commit `f4d6247eab0236019133e168f4ab1f68e54340f2` (PR #105 merge). Tag `v6.2.0` points to the release commit.

## Completed This Session

- Synchronized Python, CLI, desktop Cargo/Tauri versions and locks to 6.2.0.
- Updated bilingual README, source-contract docs, migration templates, and release notes for schema 19 / Rust API 3.
- Preserved v6.1.0 history and all pre-existing untracked user files.

## Verification Evidence

- PR #106 CI failure: flow-closure GitNexus analyze logged `malloc(): unaligned tcache chunk detected` after npm reported an optional Zig Tree-sitter peer mismatch; job exit code 1 caused the two later inventory steps to skip. No upstream 1.6.12 note claims to fix this crash.
- Local repair candidate adds `--workers 1` to the pinned 1.6.11 analyzer; a new test asserts that command and preserves the separate Runtime inventory validation and Discovered entry reconciliation workflow gates.
- Red/green regression: workflow-contract test failed before the command change because `--workers 1` was absent; passed afterward.
- `python -m pytest tests/observability/test_internal_flow_inventory.py tests/observability/test_flow_source_closure.py tests/observability/test_message_flow_contract.py -q`: 41 passed, 2 warnings. A Python 3.14/NoneBot access-violation traceback appeared once in a parallel run, but pytest completed successfully; standalone contract test reran cleanly and focused suite passed again.
- CI-equivalent `npx -y gitnexus@1.6.11 analyze --index-only --workers 1 --default-branch main`: passed in the project container; index current for 1167 covered files. Existing callable-value-flow warnings remain at `astrbot_compat/filters.py` (candidate set 33 > cap 32), distinct from crash.
- CI-equivalent inventory checks: 49 entries / 9 families; 33 discovered entries, reconciliation clean.
- `python -m ruff check tests/observability/test_internal_flow_inventory.py` and `python -m ruff check $(git ls-files '*.py')`: passed. `python scripts/check_docs.py`: 0 errors. GitNexus scope=all: 5 files/10 symbols/low; compare against verified `origin/main@f4d6247`: 18 files/34 symbols/low, no partial/truncated. Compare includes pre-existing release changes and local release-state edits because PR #106 itself is the release PR.
- PR #106 repair commit `c22dcecdde227564cecd6a7290f246ae43ba3efa` is pushed. Hosted CI run [38357443346](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38357443346) passed all 11 jobs, including `flow-closure`, Python 3.10/3.11/3.12, lint, security, CLI, flow-manifest and Windows native reliability. Docker Publish run [38357443338](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38357443338) also passed.
- Hosted flow-closure confirmed command `npx -y gitnexus@1.6.11 analyze --index-only --workers 1`, then `entries: 49 families: 9` and `discovered entries: 33 - reconciliation clean`; no native heap corruption. npm still emits the optional Zig grammar peer warning; analyzer reports existing candidate-cap warnings, neither failed the job.
- `python -m pytest tests -q`: 3669 passed, 17 skipped, 59 warnings (Windows Python 3.14).
- `python -m ruff check $(git ls-files '*.py')`: all tracked Python files passed. Unscoped `python -m ruff check .` detects I001 in the pre-existing untracked `docs/reports/evidence/dialogue-attribution-20261008/guard_probe.py`; that user file was not edited.
- `python scripts/check_docs.py`: 0 errors, 1186 local links, 577 migration anchors.
- `python scripts/generate_message_flow.py --check`: current manifest.
- Dashboard: 100 tests, vue-tsc, and production build passed; existing Vite chunk warnings only.
- CLI fmt/clippy/tests passed (20 tests); desktop `cargo check --locked` passed; Cargo metadata and all app version fields agree at 6.2.0.
- GitNexus index refreshed at f4d6247; impact of `_current_project_version` upstream is HIGH (8 symbols, including profile validation/load and release package builders), while status API version flow is LOW. `detect-changes --scope all`: 16 files/33 symbols, low, no partial/truncated; compare against verified base f4d6247 is identical.
- Hosted release run [38332591325](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38332591325) succeeded across all 17 jobs, including Rust wheel, Dashboard, CLI binaries, CPU backend, offline payload, four signed installer builds, four Windows install acceptance jobs, packaging, manifest/SHA-256 and published-byte readback.
- Stable Release: https://github.com/Eternal-Wanderer-Vegetable/Stella_project/releases/tag/v6.2.0; 14 assets uploaded. The release notes disclose that installers are unsigned under the maintainer-authorized `STELLA_ALLOW_UNSIGNED=1` exception.

## Changed Files

- Version: `pyproject.toml`, `cli/Cargo.toml`, `cli/Cargo.lock`, `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/Cargo.lock`, `desktop/src-tauri/tauri.conf.json`.
- Current documentation: `README.md`, `README.en.md`, `docs/development/contracts.md`, `docs/development/contracts.en.md`, `docs/reference/migration-report-template.md`, `docs/reference/migration-report-template.en.md`.
- Release notes: `release_assets/RELEASE_NOTES_TEMPLATE.md`.
- State: `feature_list.json`, `progress.md`, `session-handoff.md`.

## Blockers / Risks

- CI-106 fix is not committed/pushed; PR #106 must rerun hosted flow-closure before the failure can be considered cleared.
- Hosted GitHub installation checks and byte readback are complete. This is not clean-VM/GUI-first-launch or real QQ rollout acceptance; keep those open until separately tested.
- Installers are unsigned under the maintainer-authorized `STELLA_ALLOW_UNSIGNED=1` exception. Windows may show an unknown-publisher prompt; published `SHA256SUMS.txt` is available for integrity checks.
- Preserve unrelated untracked data. At task start they included `.agents/`, `.bot-restart.log`, `.zcode/plans/`, extra `docs/plans/`, research reports/evidence, `memory_rust/_native.pyd.v15.bak`, and `skills-lock.json`. They were not staged or modified.

## Next Session Startup

1. Read `AGENTS.md`, `feature_list.json`, `progress.md`, and this handoff; verify current branch/status.
2. `python scripts/check_docs.py` passed after release preparation. If state records are edited again, rerun the docs gate.
3. Do not rerun or recreate the release; `v6.2.0` is published. Follow up only on separately scoped clean-VM/GUI or real QQ acceptance.

## PR #105 CI Repair — 2026-10-10

- CI-001 done；scope：闭包预算、生成清单、回归与在线 CI。
- 基线 f8b2dce；本地复现两项合同失败：manifest 漂移、四个 ingress 截断。
- record_group_chat 实际闭包 257 个辅助符号，旧上限 256；显式 cap=512 完整展开。
- 修复：默认 cap 256 → 512，保留小预算截断与零核心截断门禁；按仓库惯例替换随包清单。
- 验证：40 项专项通过；全量 Python 3669 passed / 17 skipped（Windows Python 3.14、隔离 STELLA_HOME）；623 个已跟踪 Python 文件 Ruff 通过；清单漂移、文档门禁通过。
- 修复提交：3b31931，已推送 PR #105；[主 CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38043343651) 全部 11 项通过，[Dashboard CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38043343680) 通过。
- 提交前 GitNexus：6 文件、11 符号、low，无 partial/truncated；提交后索引刷新到修复提交并保留 PDG。
- CI-001 验收完成。完成记录的后续提交与 CI 以 Git／PR 最新状态为准；新任务由用户授权。

### Final-head Dashboard follow-up

- 2906569 的 Dashboard CI 暴露既有大数据功能用例超时（5.17s > 默认 5s）；原修复提交的主 CI 与 Dashboard 全部通过记录仍有效。
- 保留 100 页／100000 事件、全部水位断言、性能专项预算；仅该功能用例超时设为 15s。
- c7751f6 已修复该超时；本地 Dashboard 100 项测试、类型检查、生产构建通过。
- [主 CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38044052769) 全部 11 项通过，[Dashboard CI](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/actions/runs/38044052792) 通过；CI-001 done，无活动任务。
- 完成记录提交的最终 SHA／检查结果以 Git 和 PR 最新状态为准。

## Session Handoff — AI-Gated Memory Capture (2026-10-16)

- Branch: `feat/ai-gated-memory-capture`, 6 commits on top of `codex/release-6.2.0` @ `c22dcec`: `3db81e7` (gate module + probe + 23 tests), `8bc6404` (typed writer denial), `574250c` (QQ/WebChat ingress + BOT_SELF gating + lifecycle hooks + consolidator close-on-failure + e2e tests + flow manifest), `0ab17fb` (status snapshot + .env.example), `427825c` (bilingual docs), `502ef7d` (implementation report).
- Behavior: memory capture fails closed until the CONSOLIDATION role passes a bounded probe (minimal "ping" through the real generation path incl. fallback chain; /v1/models not required). Closed gate: no raw rows, no identity/social/expression/participation/consolidation-trigger side effects, BOT_SELF lines skipped; replies/plugins/usage accounting unaffected. No queue, no replay; recovery captures only newly arriving messages. `backend_for` untouched; no schema migration; no bypass switch.
- Verification: full suite `python -m pytest tests -q` = 3707 passed / 17 skipped (Windows, Python 3.14, isolated STELLA_HOME); ruff over tracked files clean; `check_docs.py` 0 errors; `generate_message_flow.py --check` ok (body-hash-only manifest change; new lifecycle entry `bot_main.start_capture_gate` registered in internal_flow_catalog).
- Baseline exceptions (pre-existing, untouched): untracked `docs/reports/evidence/dialogue-attribution-20261008/guard_probe.py` fails unscoped `ruff check .` (I001); local GitNexus CLI registry broken — caller inventory done via text search (record_message has 5 production call sites; _record_bot_lines covers all 13 BOT_SELF writers).
- Test-isolation note: tests/conftest.py now keeps `capture_gate.start_gate` inert and `_gate` unset under pytest — a stray FastAPI lifespan (leftover coroutine executed by pytest-asyncio's fixture runner) fires nonebot startup hooks in arbitrary tests; without this the gate would install closed and fire real probe requests. Gate-specific tests construct CaptureGate instances with injected fakes.
- NOT READY (external acceptance): live-provider probe smoke, QQ gray rollout, clean-VM install acceptance. Report: docs/reports/2026-10-16-ai-gated-memory-capture-implementation.md.
- Pre-existing uncommitted worktree files (feature_list.json, progress.md, session-handoff.md, plans/reports/evidence, .agents/, skills-lock.json, memory_rust backup) were left untouched and uncommitted, same as at session start.

## Session Handoff — Memory Benchmark Suite (2026-10-17)

- Branch: `feat/memory-benchmark-suite`（从 origin/main @ `4029877` 切出），10 提交（M0→M6+文档收口，见 progress.md「Memory Benchmark 评测体系」节与 git log）。计划文件：docs/plans/2026-10-16-gitnexus-plan-memory-benchmark-suite.md，M0–M6 全部落地。
- 核心成果：报告契约 `memory-benchmark-report/1` + 冻结基线（零容差 CI 门禁）；数据集 101 例（29 新维度手写 + 48 确定性生成）；四检索模式矩阵（fts/hybrid Python 单边，native 无 FTS 显式登记不可比）；PersonaMem 自动化（fetch pin+sha256+NOTICE / adapt 固定 seed / CI job）；写路径回放 recorded/live 双模式全绿；**Rust parity 101/101**（21/24 作废；根因=harness None→{} 折叠 + Python 缺 canonical tie-break，均修复）。
- 双硬零门禁：forbidden_activation_rate 与 cross_scope_leak_rate（结构化判定）。
- 验证：3750 passed / 17 skipped；ruff（tracked）全过；check_docs 0 errors；message-flow --check 过。证据：docs/reports/evidence/memory-benchmark-20261016/。
- NOT READY / Next：① live 回放真模型验证+录制（需 CONSOLIDATION 端点）；② embedding fixture 重建（覆盖 101 例后 embedding/hybrid 全量可评；本机 1234/8081 均不可达）；③ FTS 恒 0 命中=生产检索真实缺陷候选，建议另立课题；④ 本机 `_native.pyd` 已用 cargo 重建为 API 3（未跟踪文件，仓库只存源码，CI 走 release-memory-rust.yml）。
- 本机环境备注：huggingface.co 主站 API 不稳定但 resolve 端点可用，fetch 脚本带 HF_ENDPOINT/hf-mirror 回落；GitNexus CLI registry 仍损坏（调用方清点用文本检索兜底，本特性未做上游 impact——计划 §4/§5 已带 GitNexus 证据）。

## Session Handoff — 真模型验收第一轮 (2026-10-17)

- 生产双模型实测：Strata 8081（qwen3.8-flash-next-iq2_xs，CONSOLIDATION 角色）+ LM Studio 1234（qwen3-embedding-0.6b）。**本机系统代理（7890）劫持 127.0.0.1**（502 假象）——所有直连脚本必须 `NO_PROXY=127.0.0.1,localhost`。
- 交付：embedding fixture 重建（259 向量 101/101 全覆盖）；真实向量四模式矩阵 parity 全 101/101、硬零保持、embedding/hybrid 101/101；live 回放真模型打通并录制（`recorded/live-20261017.json`）；基线重生成（recency 列修复后）。
- **用户需知的生产发现**：`LLM_ROLE_EXTRACT_ENDPOINT=CHAT` 而 online 槽 base_url 为空 → 阶段2 契约提取回退，候选 verification=unknown **永不晋升**（live 回放 promotion/qa=0% 的根因）。启用完整晋升链路需给 CHAT 或 MEMORY 槽配可用端点（配置决策在用户，未擅自改 .env）。
- 修复：M1 用例补 `last_confirmed_at_offset_minutes`（15 文件，recency 判别此前未生效，真实 embedding 下 7 例旧值激活踩硬零）。
- 提交：真模型验收 commit（fixture/用例修复/基线/live 证据/双语文档/progress）。 NOT READY 余项：无（两大 NOT READY 均已闭环；FTS 恒 0 命中与 EXTRACT 配置为移交给用户的生产课题）。
