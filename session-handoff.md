# Session Handoff

## Current Session — NoneBot adapter picker, preinstall, documentation forms, and visual polish

用户要求平台页支持全部 NoneBot 适配器，按需添加，并将可用适配器作为依赖随安装包预装；后续要求按各适配器项目文档预设运行时配置表单。用户决定：Walle-Q 与 NTChat 已缺乏维护，直接屏蔽并记录原因。当前分支 `codex/frontend-ui-polish` 从同步后的 `main@9de22e696f60a14fefa91f17024dd45bdef21cde` 创建。同步前的旧本地改动留在 `stash@{0}`，本任务未触碰。`PLATFORM-ADAPTER-PREINSTALL` 和 `PLATFORM-ADAPTER-FORM-PRESETS` 均完成各自记录的源码/本地验证范围。

- UI follow-up：主视图只显示已选平台，32 条适配器目录移入可搜索添加对话框；已选项可移除，选中后显示对应专用表单。移除后不会立即保存；只有点保存才会持久化选择。
- Picker UX：选择窗口只展示 30 个可用项，Walle-Q / NTChat 等 unavailable 项不显示且计数不包含它们；卡片不再给出 `nb adapter install ...` 指令。自定义 Python 模块在同一选择窗口逐个添加，主页面的自定义模块 textarea 已移除；若输入目录里已有的可用模块会直接选择，屏蔽模块不能通过该入口绕过策略。
- Visual polish：选择器隐藏目录来源和日期，搜索框占满可用宽度；目录网格末尾增加“+ 添加自定义适配器”卡片，点击后打开模块路径对话框；平台页和 picker 适配器卡片共享 `156px` 最小高度。标题不再保留空白第二行导致模块路径下沉，项目主页/文档入口在卡片和预设说明中改为外链图标，悬浮显示 tooltip。
- 已有实现：`PlatformsPage.vue` 保留 OneBot V11、QQ 官方、Telegram、Discord 专用表单，并从 `webui/services/nonebot_adapter_catalog.json` 提供 32 条目录记录（31 个唯一包名）。目录外的自定义模块仍可启用。适配器卡显示官方/社区维护标记、本机包状态与项目链接；选择对话框不显示包安装命令。
- 通用配置：平台页可为任意适配器录入环境变量键值；`STELLA_ADAPTER_ENV_KEYS` 追踪这些值。后端保护 Stella/NoneBot 核心字段，密钥不从 GET 返回；保存空白密钥会保留旧值，删除变量会移除其 dotenv 项。
- 专用连接配置：OneBot WS、QQ Bot、Telegram polling/webhook、Discord intents 与代理/命令配置写入本机 `.env`，GET 仅返回脱敏状态；多 Bot 配置保留其余 bot。配置使用专属原子 dotenv writer。审计事件只记连接平台名称，不记表单值。
- 文档预设：新增 `dashboard/src/data/nonebotAdapterPresets.ts`，与 30 个可选目录模块逐项一致；多 Bot JSON 列表用结构化字段编辑，未列入专用表单的变量仍在高级字段中。Villa 的 `pub_key`、每 Bot 连接方式与 callback path 修正为文档结构；Matrix 的登录/OAuth 字段、sync/invitation/E2EE 选项和 WxClaw 账号/全局默认项按项目文档预填。研究记录为 [2026-10-23-nonebot-adapter-config-research.md](docs/reports/2026-10-23-nonebot-adapter-config-research.md)。
- JSON 密钥保护：后端递归隐藏嵌套 token、secret、password、key、ticket、cookie 等凭据，并按 `account_id` 等标识恢复提交中的空白密钥；Matrix token 过期时间与状态文件路径不会因名字含 `token` 而误隐藏。此逻辑位于适配器配置服务，不修改共享 dotenv writer。
- 官方资料：[NoneBot Adapter 文档](https://nonebot.dev/docs/advanced/adapter)、[NoneBot Store 文档](https://nonebot.dev/docs/tutorial/store)、[官方适配器目录 JSON5](https://raw.githubusercontent.com/nonebot/nonebot2/master/assets/adapters.json5)、[NoneBot 配置文档](https://nonebot.dev/docs/appendices/config)；AstrBot Discord WebUI 指南曾用于专用字段参考。
- 依赖决策及状态：Walle-Q 0.2.0 要求 `nonebot-adapter-onebot~=2.2.2`，与 Stella `>=2.4.6` 冲突；NTChat 0.3.5 固定 `httpx==0.23.0`，与 Stella `>=0.24.0` 冲突。用户决定按维护状态直接屏蔽。两者不进依赖，picker/API/运行时均拒绝新启用或注册，并保留旧配置以便移除。其余 30 个目录记录对应 29 个唯一发行包，进入 `requirements.txt`、`pyproject.toml` 和安装包通用 requirements 链；Heybox 通过 Python >=3.11 marker，Python 3.10 跳过。
- GitNexus：针对 `update_adapters`、`parse_adapter_modules`、`register_enabled_adapters` 的 upstream impact 为 LOW；适配器预装阶段 all/compare 为 20 files / 94 symbols / 15 flows / HIGH。添加表单和状态记录后最终 all 与 compare/main 均为 20 files / 96 symbols / 15 affected processes / HIGH aggregate，无 partial/truncated。主要流程包括适配器读写、校验、模块解析及 dotenv 持久化；共享 env writer 未修改。
- 最新表单验证：`pnpm --dir dashboard build`（含 `vue-tsc`）与 `pnpm --dir dashboard sync:webui` 通过；30/30 目录模块都有预设，Python compileall、Ruff、双语 docs 门禁、feature/locale JSON 和 `git diff --check` 通过。Vite 保留既有 mixed import 和大 chunk 警告。未运行测试，也未在浏览器中完成表单保存/readback。
- 最新 picker 验证：Dashboard build 和资源同步成功；dashboard / webui / desktop 的入口 HTML SHA-256 一致；文档 121 files / 1262 links / 577 anchors / 0 errors；双语 locale 和 feature JSON parse、diff check 通过。`saveAdapters` upstream UNKNOWN / 0；最终 detect all 与 compare/main 均为 20 files / 98 symbols / 15 affected processes / HIGH aggregate，无 partial/truncated（包含此前平台改动）。未运行测试，也未在浏览器里交互检查加号卡片、tooltip 或保存/readback。
- 最新 UI follow-up：目录选择卡片勾选框移到右上角，标题与主页适配器卡片左对齐；NoneBot 全局 `DRIVER`、共享范围提示、进程环境覆盖提示和远程平台建议放入每个已选适配器的运行时配置弹窗。Driver 仍通过原有 `/platform/adapters` 保存字段提交，页面底部保留统一保存按钮。中英文指南已说明 `DRIVER` 是全局设置。当前源码构建、资源同步、文档和 locale/feature JSON 检查通过；最终 GitNexus all / compare main 结果见 progress.md。未运行测试或浏览器交互验收，也未保存配置或连接真实平台。
- 最新首页调整：删除平台首页顶部安装包说明与“当前进程生效”行；保存/重启提示以完整草稿快照比较，仅在配置发生变化时显示，保存后重读基线，恢复原配置时自动隐藏。连接状态入口收进“已添加的平台”卡片标题旁的单一图标，点击打开连接详情表；表格按运行中的适配器连接记录展示，健康度保留 OneBot 心跳/探活差异，其他适配器仍显示未知。“连接引用”使用表格正文的统一字体，并已在浏览器中目视确认。Dashboard 构建、`sync:webui`、文档与 locale JSON 检查通过；GitNexus 最终结果记入 progress.md。浏览器确认首页布局并打开连接状态弹窗；当前旧后端 API 不兼容，页面禁用保存，因此未验证新后端保存/回读，亦未连接真实平台；测试未运行。
- 当前运行边界：浏览器显示 32 项、30 可选和 2 个屏蔽项，但 `127.0.0.1:8080` 服务仍是旧后端，所以 UI 警告 API 不兼容并禁用保存。未保存任何配置、未重启服务、未输入凭据、未尝试真实连接；也没有构建最终安装器工件。源码与依赖变更已完成，当前 backend save/readback、实际 release installer 与平台 live 验收仍未确认。
- 下一步：如要做 UI 运行验收，在新版 WebUI backend 和 Dashboard 一起运行时检查 picker 交互与 API save/readback；如要宣称发布安装器验收，则需实际构建并检查安装器/离线 wheelhouse。不要将依赖 dry-run 等同于构建工件或真实平台兼容性。

## Previous Session — Source Dashboard startup rebuild and release audit

The blank test UI came from a stale `webui/dist`. This branch now rebuilds the Dashboard when `bot.py` is run from a source checkout or source archive, before serving requests; a failed build stops the new process rather than serving stale assets. Release products with a version-marked frontend skip this runtime path.

- Branch: `codex/auto-build-dashboard-on-source-start`, synchronized with `origin/main@08dbbb0` while preparing this PR. Earlier PR #116/Gravitas state was preserved; ignored local `dashboard/dist`, `webui/dist`, and `desktop/dashboard-dist` were not changed.
- Source build: `webui/source_build.py` runs frozen dependency install, `pnpm build`, and `pnpm sync:webui`. Git checkouts build even when an old version marker exists; source archives build when no release asset marker exists. `deploy/process.py` startup wait is 180 seconds for cold installs. `dashboard/pnpm-workspace.yaml` uses `allowBuilds` for `esbuild` and `vue-demi`; official pnpm docs state pnpm 10 supports it starting at 10.26 and pnpm 11 replaced the older `onlyBuiltDependencies` config.
- Release audit: Windows release workflow already builds and stages Dashboard artifacts. Docker previously had no Dashboard build, so clean release checkouts lacked `webui/dist`; Dockerfile now builds with Node 24, copies fresh dist, and adds a version marker. `.dockerignore` excludes local ignored bundles. Dashboard/WebUI PRs trigger Docker build and asset smoke.
- GitNexus before edit: `bot.py` UNKNOWN / 0 graph callers (source refs verified); `deploy/process.py` MEDIUM / 40 impacted / 6 direct callers; `Dockerfile` UNKNOWN / 0 (compose/workflow source refs verified); package.json UNKNOWN / 0 (manifest/workflow refs verified). `progress.md` returned HIGH / partial and the warning was reported before editing. GitNexus does not index the two deployment guide paths; `rg` confirmed references before changing them.
- Build evidence: isolated `/tmp/stella-dashboard-source-build-20261022` install/build/sync passed with pnpm 11.25.0, and the synced output contains `GravitasStatusPage-*.js`. No repository ignored dist was touched. Docker CLI build attempt failed before processing because `/var/run/docker.sock` is unavailable; hosted Docker CI remains necessary.
- Final checks passed: `.venv/bin/ruff check bot.py deploy/process.py webui/source_build.py`; `python3 -m py_compile bot.py deploy/process.py webui/source_build.py`; `python3 scripts/check_docs.py` (119 files / 1247 links / 577 anchors / 0 errors); `python3 -m json.tool feature_list.json`; `git diff --check`. GitNexus detect all: 12 files / 14 symbols / 0 processes / LOW; compare main: 17 files / 25 symbols / 0 processes / LOW. Do not run pytest or start the real Bot; neither was requested, and the running test service was not modified.
- PR: [#118](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/118) is open against `main@08dbbb0`, mergeable; hosted CI, Dashboard CI, and Docker Publish checks are pending on the latest PR head.
- Next: monitor hosted checks and repair any failures; direct Linux/Windows source startup and test-host acceptance remain external.

## Previous Session — Gravitas Dashboard test-environment diagnosis

User reported a blank Gravitas page and supplied `/api/v1/status`. The payload contains a Gravitas object with `mode=shadow`, `snapshot_valid=true`, and assessment `partial`, so the backend has status data. The source route and navigation are present, but the test service is serving an older Dashboard bundle.

Confirmed by read-only HTTP requests to `127.0.0.1:8080`: the served index SHA-256 is `bcc60e4d27803f551c9e16089d06f4e0924ad4ff4091412aade9112f59386b0f`; it references `assets/index-UXCygCID.js`, which contains no Gravitas route markers. Current local `webui/dist` has 52 files, SHA-256 `4cbc7dc5a32971508b8f383159fc2ec45a389cab0308273a71c7731c9b011fde`, with route-bearing entry `assets/index-Dqzv2b0Y.js` and lazy chunks `GravitasStatusPage-BM9b9YdZ.js` / `GravitasStatusPage-DwLkJqxt.css`. Both chunks return 404 from the test service. Root cause: test service static assets were not rebuilt/synced after the Gravitas route was added; the source-only sync script and Dockerfile do not build them automatically.

- Next: run `pnpm --dir dashboard build && pnpm --dir dashboard sync:webui` on the deployment checkout, then restart/recreate the service using its deployment method. Verify the served index changes, the Gravitas JS chunk returns 200, and `/#/gravitas` renders.

## Previous Session — OneBot v11 Alconna dependency fix (PR #117)

用户要求补齐 Stella 的默认运行依赖并提交 PR。PR [#117](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/117) 已合并至 `main@08dbbb0`，分支 `codex/onebot-alconna-required-dependency`，提交 `65f1b34`，基于 `main@f340917`。PR CI run `39727575917` 全部成功（Python 3.10/3.11/3.12、Windows native、flow、docs、lint、security、CLI、benchmark、notify）；Docker Publish `39727575966` 成功。

- Root cause：OneBot v11 `OneBotV11TargetCodec.encode` 延迟导入 `nonebot_plugin_alconna.uniseg.Target`，但 Alconna 0.62.1 只在可选 platform 依赖中。活跃 Bot 环境使用 `C:\Users\Vegetable\.conda\envs\stella\python.exe`，此前未安装它；已记录的两个失败 trace 都在 `target_codec_rejected` / `not_delivered` 结束。
- Fix：把 Alconna 固定版本加入 `pyproject.toml` 与 `requirements.txt`；`requirements-platform.in` 保留可选 Uninfo；重新生成平台锁并同步双语 CI 说明。运行环境已安装；`Target` import 和 `litellm` import 都成功。
- Environment caveat：pip 将 `importlib-metadata` 从 8.9.0 升到 9.0.1，因 Alconna 要求 `>=9`；现有 `litellm 1.96.0` 声明 `<9`。两者的导入探针通过，但环境元数据约束冲突仍存在，后续需确认是否有独立 LiteLLM 环境约束。未重启 Bot（发送 codec 在运行时延迟导入）。
- Verification：依赖锁解析 95 packages；TOML 有效；docs 检查 119 files / 1,247 links / 577 anchors / 0 errors；本地 pytest 未运行。没有主动向 QQ 发送测试消息，因此真实收发验收仍待一条用户发起的消息。
- GitNexus 1.6.12：`OutboundService.send` 上游 HIGH（11 / 6 direct / 2 processes / 3 modules）；codec impact UNKNOWN，源码核实动态路径。变更 all / compare main 均 LOW（6 files / 2 symbols / 0 flows），无 partial/truncated；索引的 flow extraction 本身漏掉 2,887 个候选入口。
- Files：`pyproject.toml`、`requirements.txt`、`requirements-platform.in`、`requirements-platform.lock`、双语 CI 指南及状态文件。下一步在用户发起的真实 QQ 消息后观察回复并由用户决定合并；TEST-REPO-SYNC 的 Linux/Windows 测试端验证因缺少主机访问而 blocked。

## Current Session — PR #116 CI repair and documentation conflict resolution

用户要求修复 PR #116 的 CI 失败并解决 main 同步后的文档冲突。当前分支 `codex/test-repo-sync-scripts` 包含合并提交 `0520a5a`，已合并 `origin/main@811ab69`；PR [#116](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/116) 保持 OPEN，原始同步脚本提交为 `37a9f4c`。

- Root cause：PR CI run `39718004194` 的 Python 3.11 job 中，`test_no_jobs_creates_no_root` 断言 `claimed == 0` 实际为 1，`test_no_handler_marks_dead` 断言 `dead == 1` 实际为 0。两个测试分别运行于 xdist `gw1` / `gw3`；同类 enqueue 测试在 `gw0` 运行。`flow_db` 仅隔离 `turn_trace.db`，`social_worker._connect()` 仍使用全局 `settings.DB_PATH`，故并行 worker 会竞态读写队列。
- Fix：`tests/observability/test_background_flow_roots.py::flow_db` 将 `settings.DB_PATH` 指向每个用例独立的 `tmp_path/social.db`，初始化 social schema，并在 teardown 清除 `social_store` 表就绪缓存；没有修改生产逻辑。
- Follow-up：docs-only head `5199657` 的 CI run `39720613488` 又暴露一个独立测试时序问题：`tests/runtime/test_facade_turns.py::test_prepare_timeout_is_control_signal_and_cancels_hook` 使用 150ms 总预算，负载高时在 prepare hook 启动前就过期（Python 3.11：4017 passed / 1 failed / 29 skipped）。将其测试预算改为 1.0s，让正常准备步骤先启动 hook 再验证超时取消；整个 facade-turn 文件在 3 个 xdist workers 下 13 passed / 2.04s，Ruff 与 py_compile 通过。此改动没有触及 `submit_turn` 生产实现。
- GitNexus：测试方法 upstream impact UNKNOWN / 0 图调用者（pytest 收集方式，源码引用已查）；`run_due_jobs` upstream LOW / 1 direct / 2 modules / 0 processes。GitNexus 1.6.12 索引于 PR 分支 HEAD；分析报告有 process truncation，不把遗漏流程视为无调用。
- 文档冲突：PR #115 已合并为 `main@811ab69`，hosted run `39716099609` 全通过。合并冲突只涉及 `feature_list.json`、`progress.md`、`session-handoff.md`；保留 TEST-REPO-SYNC 状态，并同步 LinkMonitor 的 merged 状态，远端 Gravitas 页面验收仍列为 pending。
- Verification：原 fixture 回归 7 passed / 1.68s；后续 timeout test file 13 passed / 2.04s，均用 3 个 xdist workers。Ruff、py_compile、docs（119/1247/577/0 errors）、JSON、冲突标记和 diff 门禁通过。GitNexus 1.6.12 强制重建后，timeout test impact UNKNOWN / 0 caller（源码引用已查），`submit_turn` CRITICAL / 492 impacted / 1 direct / 178 processes / 20 modules（生产代码未改）；state files impact LOW：feature 19/2、progress 26/3、handoff 19/2。最终状态文档 detect all: 3 files / 5 symbols / 0 processes / LOW; compare main: 10 / 10 / 0 / LOW。流程抽取遗漏 2,887 个入口候选，故零流程不作为无影响证明。PR run `39720042543` 在 head `5576e92` 全绿；最终 run `39721493074` 在 head `6236786` 的 Python 3.10/3.11/3.12、Windows native、flow、docs、lint、security、CLI 与 benchmark 检查全部成功。测试端 Linux/Windows 同步验收仍待执行，当前主机也没有 PowerShell parser。
- Next：在 Linux 与 Windows 测试 checkout 验证 clean fast-forward 和 dirty-worktree 安全中止；在 Windows 环境补做 PowerShell parser 检查。

## Inherited Session — LinkMonitor and Gravitas follow-up

PR #115 fixed the remaining `bot: Any` lifecycle-hook injection error and was merged at `main@811ab69`; hosted run `39716099609` passed all checks. Local Dashboard build/sync outputs included the Gravitas route, but deployment to the test environment, service restart, and live route plus authenticated status API verification remain blocked pending test-environment access.

## Completed Session — PR #113 CI repair

用户要求检查 PR [#113](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/113) 的 CI、修复失败，并将提交信息改成英文。任务已完成：分支 `codex/memory-envelope-fallback-followup` 已基于 `main@386b46f` 更新，提交标题为 `fix(memory): simplify invalid reply envelope fallback`。

- Root cause：原 CI run `39699060445` 的 `flow-manifest` 和 Python 3.10/3.11/3.12 均因 `TestDriftGate.test_committed_manifest_matches_source` 失败。语义漂移是 `cometa.claim` 与 `post.parse` 正文指纹变化、拓扑不变；PR 的 `parse_output` 文案更新使 `post.parse` 指纹变化，基线上还存在 `cometa.claim` 漂移。
- Fix：运行生成器并提交 `core/observability/flows/message-flow.982a65f5aef2.json`。`uv run --python 3.12.14 --no-project -- python scripts/generate_message_flow.py --check` 与 hosted `flow-manifest` 通过。
- Hosted verification：run `39707392594` 成功。Python 3.10 / 3.11 / 3.12 各为 4,017 passed / 29 skipped；flow-closure、Dashboard build、security、CLI、Windows native reliability、benchmark、documentation 与 lint 均通过。
- Local verification：Python 3.12.14 全量 4,014 passed / 29 skipped / 2 failed / 5 warnings。失败的 Cometa single-owner 与 WebUI OneBot config 用例各自在独立临时 `STELLA_HOME` 下单跑 1 passed；将本地全量失败保留为未确认的顺序/共享状态稳定性观察。全仓 Ruff、文档门禁（119 files / 1247 links / 577 anchors / 0 errors）、flow `--check`、JSON 和 diff checks 通过。
- Impact：`parse_output` upstream impact UNKNOWN / 0 edges；已在源码确认 `ai_gateway.py` 的动态 post-hook 注册及 runtime、回放、评估引用。文件级 impact LOW（7 个影响文件 / 3 个直接导入）。GitNexus 索引 sibling-worktree 提示和流程提取预算截断均已记录；manifest JSON 使用 Git 与 flow 门禁核验。
- Files：`memory/post_processors.py`、legacy trace fixture、generated message-flow archive、`feature_list.json`、`progress.md`、`session-handoff.md`。
- Blockers：本任务无 PR scoped CI blocker；PR 保持 open 等待 review / merge。真实平台、模型与干净 VM 验收不在本任务范围内。

## Previous Handoff — LinkMonitor dependency injection fix

用户要求修复开发环境同步提交后出现的 `link_monitor` 加载错误，并开新 PR。当前分支 `codex/link-monitor-event-injection-fix`，从 `origin/main@d136c90` 创建。原因是 NoneBot 注册 `@event_preprocessor` 时按 `Bot` / `Event` 类型做参数解析，`Any` 不受支持；源码签名已改为 `bot: Bot, event: Event`，并增加对 `Dependent.parse(..., EVENT_PCS_PARAMS)` 的回归测试。PR [#114](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/114) 已合入 `main@386b46f`；CI run `39702521767` 对 head `5df7ca5` 的结论为 success，Python 3.10/3.11/3.12 及全部其它 jobs 通过。

- Files：`extensions/link_monitor/__init__.py`、`tests/test_link_monitor.py`。
- GitNexus：索引 commit `f5e6a64` 与当前 `d136c90` tree 内容一致；目标 upstream impact `UNKNOWN / 0`，原因是 NoneBot 装饰器动态注册，已从源码确认注册点。提交前 `all` 与 `compare main` 均为 5 files / 8 symbols / 0 processes / LOW，无 partial/truncated。
- Verification：`tests/test_link_monitor.py` 12 passed；全仓 Ruff、改动文件 `py_compile`、docs（119 files / 1248 links / 577 anchors / 0 errors）、message-flow `--check`、diff check 均通过。全量 pytest 4014 passed / 29 skipped / 3 failed；失败为一个 memory-flow lifecycle 与两个 WebUI auth 用例，各自隔离重跑均通过，顺序/共享状态根因未确认。测试使用 `/tmp` 隔离 `STELLA_HOME`，未启动真实 Bot、平台或访问用户数据库。
- Next：PR #114 已合入 `main@386b46f`。全量 pytest 的三个顺序失败各自单测通过，但其共享状态/顺序根因尚未确认；当前本地全量仍按 4014 passed / 29 skipped / 3 failures 如实记录。

## Previous Session — Gravitas implementation

用户要求新建分支并执行[工程方案](docs/plans/2026-10-21-gravitas-engineering-plan.md)，阶段提交并创建 PR。GRAVITAS-IMPL G00–G09 已完成，PR [#112](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/112) 已提交且保持开放；当前分支 `codex/gravitas-implementation`，基于合并 PR #111 后的 `main@c662746`，HEAD `2bfb362`。最新 PR checks 全绿。

- Files：方案、[机器工作包清单](docs/plans/2026-10-21-gravitas-inventory.json)、[GitNexus 研究与基线证据](docs/reports/evidence/gravitas-20261021/README.md)。
- Current package：G00–G09 源码、测试、双语指南与分阶段提交均完成。CI 后续提交：`67f33a1` 为 package smoke 构建 Dashboard 资源，`4d0831c` 修正 Python 3.10 asyncio timeout 断言，`06be191` 消除 3.11 取消测试的 deadline 竞态，`2bfb362` 扩大 shared CHAT gate 回归的调度观察窗口。PR head `2bfb362` 的最终全量 CI 通过。
- Commits：G00 `709a4b4`、`82f377d`、`88de58c`、`f03eb0f`；G01 `dbcbe41`；G02 `8e87c6c`；G03a `dd8bb72`、G03b `6c625f9`、G03c `351878d`；G04a `c3d4c4d`；G04b `6458764`；G04c `8160289`、`5b87efa`；G05 `e7ee716`；G06 code `21fb77f`；G07 code `bfb1fa2`；G08 code `b78c72e`；G09 code `ddb1c53`；CI fixes `67f33a1`、`4d0831c`、`06be191`、`2bfb362`；status docs `21fe2a0`。
- Verification：G00 组合回归 78 passed；G01 定向合同/发布/flow 回归 65 passed；G03c 综合定向回归 446 passed；G04a QQ/主动/WebChat/runtime 相关定向回归 77 passed / 1 fixture warning；G04b Facade/TurnService/Planner/Capability/QQ/WebChat 相关定向回归 470 passed / 1 fixture warning；G04c runtime/capability/planner/QQ/private/WebChat/social/outbound/Cometa 回归 **517 passed / 1 fixture warning**。G05 相关定向回归 216 passed / 1 warning；全量 Python suite **3968 passed, 29 skipped, 1 warning**，使用全新 `/tmp/stella-gravitas-g05-full-20261021b`。G06 隔离回归 **97 passed / 1 existing warning**；Dashboard typecheck 通过、Vitest 7 files / **101 passed**、build 成功，localhost fake API 浏览器验收通过。G07 定向守卫 **4 passed**，全量 Python **3976 passed / 29 skipped / 1 existing warning（359.95s）**；10 seeds × 256 状态事件与 S01–S12 两轮离线回放、Standalone/OneClick staged import 均通过，same-seed digest 为 `6d35e75631c1861239cb4ac2cd8555a8e6a5058e`。Ruff、改动 Python 编译、文档门禁、flow archive `message-flow.d2b36de1444a.json`、CI YAML parse 与 diff 检查通过。详见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- G03c impacts：RoleBackend MEDIUM；`execute_model_call` CRITICAL（8 direct / 6 processes / 11 modules）；脚本探针 LOW；两个评估脚本文件 UNKNOWN/0 edges，已文本审计。`run_compact_evaluation` LOW（2 impacted/1 direct/1 flow），回放 `main` LOW（1/1）。这些 exact symbol/function impact 有编辑后补查的门禁偏差，细节见实施报告，不构成后续风险豁免。
- G08 evidence：`b78c72e` 加入 bounded dependency recovery registry、fenced passive outcomes、single-flight active probes、retry budgets/backoff 和 per-domain SQLite failure classification。涉及 endpoint/model calls、CapabilityProvider、CaptureGate、OneBot LinkMonitor、memory/social/Cometa/scheduling/knowledge/observability stores。定向回归 60 passed；最终 full suite 3,989 passed / 29 skipped / 1 existing warning（220.82s）；全仓 Ruff、改动 Python 编译、docs（119/1246/577/0 errors）、flow archive `message-flow.643390a24eac.json` 与 diff check 通过。两个中间 full run 分别遇到 WebUI replay 和 Cometa shutdown 单例失败，各单测重跑通过，之后完整全量通过；根因未确认，保留为间歇性稳定性风险。GitNexus all 13/47/31/CRITICAL；compare/main 503/1076/113/CRITICAL cumulative，扩大上限后 compare 列表仍 capped，统计和风险覆盖全部变更。具体影响、索引截断和 S13/S14 范围见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。
- Hosted verification：最终 PR CI run `39629392684` 在 `2bfb362` 上 Python 3.10 **4016 passed / 29 skipped / 3 warnings**、3.11 **4016 passed / 29 skipped / 4 warnings**、3.12 **4016 passed / 29 skipped / 5 warnings**；3.11 G07 S01–S12 fake evaluation 与 `release_package_layout_and_import` 均 PASS，digest `4a202051d493aaf8a67b8937e9a4003ef70f1ad7`。Dashboard run `39629392742`、Docker run `39629392600` 和 CI 内 lint/docs/security/flow/CLI/Windows native/benchmark 全部 PASS。本机 `tests/runtime/test_facade_turns.py` xdist 4-worker **13 passed**，`tests/observability/test_message_flow_runtime.py` **16 passed**；Ruff、`py_compile` 与 diff check 通过。之前 run `39628116553` 暴露的 1 秒 polling window 已由 `2bfb362` 修正，最终 CI 全绿。
- Local suite / remaining acceptance：一次完整本地回归为 **3942 passed / 22 skipped / 1 failed / 1 warning**，既有 WebUI Cometa empty-key 用例预期 400、实际 401；hosted 三版本全量已通过，但本地该异常根因未确认，不能声称本地全量绿。所有新验证使用隔离 `/tmp` `STELLA_HOME`；未启动真实模型、Bot 或平台，未读写用户数据库。真实模型/QQ/WebChat 灰度、生产跨进程恢复、clean VM、安装器与发布资产仍未验收，产品保持 **NOT READY**。
- Next：review 并合并 PR #112；之后在有授权平台账号与干净环境时完成外部验收。恢复命令：`git status --short && git log --oneline -10`。完整验证和 GitNexus 限制见[实施报告](docs/reports/2026-10-21-gravitas-implementation.md)。

## Previous Session — Gravitas planning

本轮用户要求把稳态讨论完善成可落地方案，并深入使用 GitNexus。交付仅限计划、研究证据与状态；业务实施未启动。方案及文档/档案/源码指纹/证据摘要/图变更门禁已完成，结果入口为[证据 README](docs/reports/evidence/gravitas-20261021/README.md)。

- Files：[方案](docs/plans/2026-10-21-gravitas-engineering-plan.md)、[机器工作包/73 源码/50 入口/16 场景清单](docs/plans/2026-10-21-gravitas-inventory.json)、证据目录和双语历史导航。
- Evidence：基线 `2b69402`；GitNexus 1.6.12 全量重解析后关键 Function 恢复；query/context/impact、823 流程分页、源码与动态接线补证。acquire CRITICAL、Compact 和 deliver_lines HIGH。首次 partial 已重跑；PDG 无第160行语句块，不作语句级证明。
- Verification：文档、档案/DAG/指纹/证据 SHA256 与 diff 门禁通过；GitNexus all LOW、compare/main 累计 CRITICAL，临时扩大展示清单上限后完整重跑，无 partial/truncated，原始统计/风险一致。临时 STELLA_HOME；定向既有测试 83 passed/2 warnings，清理器 16 passed；三个合成探针确认调度旁路、取消计数、零水位清理问题，未实施修复。无生产库、模型、Bot 或平台连接。
- Historical status：当时 GRAVITAS-IMPL 为 planned，XPLAT-IMPL 仍为 in_progress。PR #111 合并后，本轮新建 Gravitas 分支并开始实施；XPLAT 的外部验收缺口改记 blocked，不代表验收完成。
- Historical next step：按方案 §10 从 G00 开始，先重绑 HEAD 和跑 upstream impact，再用三个子提交关闭默认 provider、waiter 回收与清理保护。当前进度见本文件上方的 Gravitas implementation。

## Inherited Cross-platform Handoff

## Current Objective

XPLAT-IMPL：执行 [GitNexus 跨平台方案](docs/plans/2026-10-20-gitnexus-cross-platform-plan.md) 的 WP00–WP11，按工作包分阶段提交。WP00–WP10 已完成；WP11 的 32 项状态矩阵、OneBot V11 事件/回投夹具和本地全量 Python 回归已通过。修复提交 `1f5c900`、`54c4d4c`、`7f35347`；PR #111 已合并，因平台 live、干净 VM 与发布验收尚缺，状态为 `blocked / NOT READY`。分支 `codex/cross-platform-implementation`，原基线 `ba582a922f4d3379b6397c4c0a8d8ef3e7c3e77d`。

## Deliverables

- [执行方案](docs/plans/2026-10-20-gitnexus-cross-platform-plan.md)：版本化合同、12工作包、依赖、迁移/回滚、测试与发布边界。
- [执行附录](docs/plans/2026-10-20-cross-platform-inventory.md)：50运行入口、32适配器和180候选文件。
- [证据索引](docs/reports/evidence/cross-platform-20261020/README.md)：原始query/context/impact、PDG、命令参数、补证、哈希。
- [WP00实施记录](docs/reports/cross-platform-implementation-20261020.md)：依赖冻结、GitNexus风险、QQ/WebChat回归与命令结果。
- [WP01实施记录](docs/reports/2026-10-21-wp01-identity-registry.md)：opaque 身份合同、隔离注册表、alias 与定向回归证据。
- [WP02实施记录](docs/reports/2026-10-21-wp02-context-message-identity.md)：projection v7、opaque message ID、turn-bound target_ref、GitNexus 风险与验证结果。
- [WP03实施记录](docs/reports/2026-10-21-wp03-storage-backend.md)：schema 21 迁移、Python/native API 4、隔离 wheel、双后端 fullchain/parity 与未关闭验收项。
- [WP04实施记录](docs/reports/2026-10-21-wp04-memory-authorization-scope.md)：schema 22、主体/连接隔离、分享撤回、KB ACL、社交作用域和定向验证证据。
- [WP05实施记录](docs/reports/2026-10-21-wp05-ingress-admission.md)：OneBot/NoneBot normalizer、共享 admission、群注册接线、WebChat 主体与定向回归/GitNexus 证据。
- [WP06实施记录](docs/reports/2026-10-21-wp06-outbound-delivery.md)：统一出站、媒体/能力合同、OneBot codec、social v5 多 ID 回执、定向回归/GitNexus 证据。
- [WP07实施记录](docs/reports/2026-10-21-wp07-background-recovery.md)：后台投递目标与跨进程任务恢复。
- [WP08实施记录](docs/reports/2026-10-21-wp08-astrbot-compat.md)：AstrBot 事件和组件兼容边界。
- [WP09实施记录](docs/reports/2026-10-21-wp09-adapter-assembly-health.md)：多适配器装配与健康状态。
- [WP10实施记录](docs/reports/2026-10-21-wp10-control-plane-delivery.md)：平台控制面、安装器与发布清单。
- [WP11认证记录](docs/reports/2026-10-21-wp11-platform-certification.md)：32 项状态、夹具、回归失败和外部验收缺口。
- [机器可读适配器矩阵](tests/platforms/adapter_matrix.json)：官方快照 32 行，未知保持显式未评估。
- `.gitnexus/lbug`：本地代码图谱；`.gitnexus/gn`：固定1.6.11启动器。工具/索引不入业务提交。

## Verification / Boundaries

WP11 定向平台/Normalizer/Outbound 测试 18 passed；后续记忆 replay/candidate 27 passed，调度 service 176 passed，WebUI manage 12 + scheduling route 1 passed，Cometa worker 6 passed。CI 同款全量 Python 最新为 **3879 passed / 29 skipped / 5 warnings**（112.76 秒），先前记录的 6 项失败均已关闭。Dashboard Vitest 100 passed、typecheck 通过、build 成功；全仓 Ruff 与 message-flow 检查通过。详见 WP11 报告。整体仍 NOT READY：OneBot V11 L0 隔离 Driver 注册通过、L1 真实事件模型到 fake 回投夹具通过、L3 夹具部分；L2 与 live 未执行。官方 32 项全部 NOT CERTIFIED；仅 OneBot V11/V12 共用发行包在本地安装，另 30 项包未安装。

GitNexus 流程抽取仍有入口/分支预算截断、回调和跨语言缺边；UNKNOWN 与零调用者均用源码引用补查，不作为低风险。全量 pytest 使用隔离 `STELLA_HOME=/tmp/stella-wp11-final-allgreen-20261021`；未迁移生产库、未启动 Bot、未连接平台或模型。没有 Windows/Linux 干净 VM、QQ 灰度、跨进程 live 恢复和 Python 3.10/3.11 独立验收。

## PR #111 CI 修复（2026-10-21）

- 首轮失败根因：test job 只安装 `requirements.txt` 与开发工具，而跨平台测试直接导入可选的 `nonebot_plugin_alconna`；它只在平台 extra 与 `requirements-platform.lock` 中定义。提交 `e622c7a` 将测试安装切换到该 lock、加入 pip 缓存键，并同步双语 CI 复现说明。
- 首次重跑暴露独立的 Cometa 测试竞态：`test_pump_delivers_submitted_ack` 在 `PENDING → SENDING` 时提前结束轮询。提交 `97a2ea9` 让测试等到 `SERVER_EMITTED` 终态。
- 最终 hosted CI run `39557774555` 全绿：Python 3.10 / 3.11 / 3.12 各 3,879 passed / 29 skipped；CLI、文档、security、flow、Windows native、benchmark、Dashboard、Docker build/push 均通过。PR [#111](https://github.com/Eternal-Wanderer-Vegetable/Stella_project/pull/111)。
- 本地检查：`uv pip install --dry-run --python .venv/bin/python -r requirements-platform.lock`（95 packages，无改动）；平台失败相关测试 22 passed / 1 warning；Cometa runtime assembly 3 passed；`python3 scripts/check_docs.py`（119 files / 1,234 links / 577 anchors / 0 errors）。

## Next Steps

1. 外部具备平台账户与干净环境后，按 32 行矩阵逐平台补包版本/Python/driver、fixture、live 和维护证据；单独完成多账号恢复、QQ 灰度、Python 3.10/3.11 独立运行及 Linux/Windows clean VM。
2. 补齐 OneBot L2/L3 与至少一个代表平台的真实 live 收发；按各协议事件语义评估非聊天 adapter。
3. 只有 release、平台和 VM 验收关闭后才将 XPLAT-IMPL 改为 done；GitNexus 索引预算限制仍须如实保留。

---

## Previous Handoff — historical, superseded by the current objective


## Current Objective

- EXTRACT 契约对齐（阶段2 提示词修复，计划 `docs/plans/2026-10-17-gitnexus-plan-extract-contract-prompt.md`）已全量实施并验收：分支 `feat/memory-benchmark-suite`，本会话提交 `4a45082`（提示词硬规则块+守卫测试）→ `9a74b9a`（验收证据+报告）→ `af079df`（状态）→ `723ca57`（PR CI 修复）；**已推送，PR #110 CI 13/13 全绿（run 39014161067），待用户合并**。
- 实施报告：[docs/reports/2026-10-17-extract-contract-prompt-fix.md](docs/reports/2026-10-17-extract-contract-prompt-fix.md)；证据：`docs/reports/evidence/extract-contract-20261017/`（replay-live-strata-postfix + contract-assessment-live + manifest）。

## Completed This Session

- `4a45082`：`EXTRACTION_PROMPT` 增补「契约硬规则」块（分隔线之上，`{messages}` 仍在末尾）：枚举 `evidence_contract` 可审核刻板句型与 predicate_key（含 `.en` 英形）、span 截尾/值段禁标点/canonical_value=纯值段、self_report→FACT+positive 与 explicit_preference→PREFERENCE 绑定、反例三条、非刻板句照常提取（不漏不变）、称呼规则调和（自称「我叫X」=self_report/FACT；「以后叫我X」维持 PREFERENCE 但契约暂不 accepted）。另修正两处与闸门矛盾的既有示例：正例 content 改逐字片段、结构示例契约 `sleep_pattern`/失眠 → `profile.residence`/杭州。新增 `tests/test_extraction_prompt_contract.py` 结构守卫（句型枚举/绑定措辞/块位置）。flow manifest 重生成（body_hash 漂移）。
- `9a74b9a`：真模型验收证据落盘 + 实施报告。
- `723ca57`：PR #110 首推 CI 四项失败修复（三种根因）：EXTRACT 计划文件入库（docs 链接门禁）；`digest_dir` 哈希前 CRLF→LF 归一化 + FROZEN_DIGEST 平台无关值（Windows CRLF 检出 vs CI LF 使冻结摘要分叉）；`adapt_personamem` 默认 CSV 改指 fetch 落盘嵌套布局（CI 无本机手工扁平副本）。本地全链路镜像（generator --check / 13 passed / adapt 200 + gate 98.0% 绿）后推送，CI 全绿。

## Verification Evidence

- **决定性验收（live 回放两遍独立实录，Strata qwen3.8-flash-next-iq2_xs @8081，daily-life suite）**：
  - 第一遍（计划命令，`replay-live-strata-postfix.json`）：候选 6 / 记忆 4；extraction 100%、fabrication 0%、**promotion 100%（此前 0%）**、qa 100%、delta +100。
  - 第二遍（同管线+逐候选契约盘点，`contract-assessment-live.json`）：**accepted 4（此前 0）、0 rejected**，句型全命中教学枚举（profile.residence / preference.general×2 / profile.nickname），截尾生效（「我叫小艾，以后多指教」→「我叫小艾」）。
  - 晋升以 accepted 为前置（memory_manager.py:1007 缺 accepted 拒绝晋升），promotion 100% 与 accepted 4 互为印证；关键错误 0。
- pytest：守卫+前缀缓存 14 passed；子集 `-k "prompt or consolidat or evidence_contract"` 109 passed；ruff（改动文件）、check_docs（119 文件/1195 链接）过。
- GitNexus：`impact format_extraction_prompt` 上游 CRITICAL（3 直接调用方全透传，与计划 §4 一致）；detect_changes scope=all exit 0、无 partial/truncated。

## Blockers / Inherited State

- **工作树遗留（非本会话产物，未提交）**：`memory/benchmark/_replay/daily-life/recorded/live-20261017.json`（上上会话 live 重录件）及各 untracked plans/reports/skills-lock.json/.agents/ 等照旧保留，是否提交由用户决定。
- 闸门 `memory/evidence_contract.py` 本计划零改动（ASSESSMENT_VERSION 2026-10-08.1 未 bump）。
- dev bot（用户终端直启，与 prod 同用 8080）与回放共用 8081 Strata；**bot 进程需重启才会加载新提示词**（提示词是模块常量，非热载）。

## Next Steps

1. 用户合并 PR #110（分支 18 提交全绿）；QQ 真机灰度观察阶段2 晋升（需重启 bot 加载新提示词）。
2. 开放课题（计划 §12）：称呼要求（「以后叫我X」）闸门无支持句型，扩 gate（evidence_contract 新 pattern + ASSESSMENT_VERSION bump + 提示词同步）另立计划。
3. 上会话遗留：native `fts_text` 与 Python `_tokenize` 分词分歧对齐小课题；QQ 真机检索命中观察。
4. 备忘：personamem CI gate 现 98.0%（FTS 修复后的口径），若后续调 gate 阈值需连同 `ci.yml` 一起审。
