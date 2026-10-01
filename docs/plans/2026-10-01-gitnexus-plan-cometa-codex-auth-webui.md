# GitNexus Engineering Plan

> Task: cometa codex 认证配置化——WebUI 双路线（OpenAI 账号登录 + 自定义端点接入，与三端点 providers 模式统一）+ 托管 codex_home + probe 一致性修复
> Evidence verified at commit e20f6794a250d76d80de1403983050856f6da13e; GitNexus index fresh（本会话经 docker `analyze --index-only` 重建至 HEAD，19,169 nodes / 45,394 edges；无 PDG 层）。
> Evidence provenance schema 2; global dirty digest `0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd`; cited-path manifest 16 条（全部 clean）；本计划路径已从摘要排除。
> 图查询经 docker 执行（`MSYS_NO_PATHCONV=1 docker exec -w /repo stella-gitnexus gitnexus …`；宿主 CLI 注册表 foreign 不可用）。

## 1. Objective

把 codex 后端的认证从「管理员在开发机手工 `codex login` 写 `~/.codex/auth.json`」改为 Stella 托管、WebUI 可配置：

1. **OpenAI 账号路线**：WebUI 发起 ChatGPT 设备码登录（辅以 API-key 登录与退出）；
2. **自定义端点路线**：base_url + api_key + model（+wire_api），交互与存储纪律与现有三端点 providers 页面完全一致——api_key 永不回显、空串=不修改、保存前可测试；
3. 认证落盘到**每后端托管的 codex_home**（`STELLA_HOME/cometa/codex_home/<backend_id>/`），随数据根走，换机不失效；
4. 修复 probe 与后端实际 codex_home 解析不一致的问题，并把认证状态暴露给前端（今日 health 从不探测后端，AUTH_REQUIRED 对用户不可见）；
5. `openai-codex` SDK 以 optional extra 进入 pyproject（M0 冻结 0.159.2）。

明确不改动：cometa.toml schema、store/executor 事务、delivery 泵、QQ/委派链路、SDK 版本矩阵。

## 2. Current Behaviour

- 认证探测：`CodexBackend.probe`（cometa/backends/codex.py:131-158）顺序查 executable → SDK import → `_auth_ok()`；`_auth_home()`（codex.py:84-93）读 **bot 进程**的 `CODEX_HOME` 或 `~/.codex`；auth.json 缺失 → `AUTH_REQUIRED`。[verified]
- probe 的唯一生产调用点是 executor 认领时（cometa/executor.py:121-129），未通过即 `backend_probe_failed` fail-fast；`CometaService.health()`（cometa/service.py:384-398）只查 store/config，**从不 probe 后端**——前端无法看到认证状态。[verified]
- 后端构造：`_build_codex`（codex.py:161-177）以 SDK `AsyncCodex(env=dict(self._config.env))` 启动 app-server——env 来自 toml `[backends.<id>.env]` 透传；SDK 侧以 `os.environ.copy()` 为底再 update（外部证据：openai_codex client.py `start()`）。若管理员只在 toml env 里声明 CODEX_HOME，probe（读 bot 进程 env）与 app-server（读透传 env）会解析到不同 home——现状无人触发，属潜伏缺陷。[verified]
- SDK 认证 API（外部证据，openai_codex 0.159.2，api.py:107-130 同步 / 360-387 异步）：`login_api_key(key)`、`login_chatgpt()`（本机浏览器）、`login_chatgpt_device_code()`（设备码，headless 可用）、`account(refresh_token)`、`logout()`；`CodexConfig` 支持 `codex_bin/config_overrides/env`（client.py:196-209）。这些文件在仓库外（site-packages），不在引用清单内。[verified-external]
- codex 二进制（SDK 自带 codex_cli_bin 0.159.2）含 `model_providers`/`base_url`/`env_key`/`wire_api` 配置键（二进制 grep 命中 83/66 次；`preferred_auth_method` 不存在）——自定义 OpenAI 兼容端点可用 codex 原生 config.toml 声明。[verified-external]
- 三端点 providers 模式（对齐对象）：`LLM_ENDPOINT_<SLOT>_{BASE_URL,API_KEY,MODEL,KIND,CONCURRENCY,TIMEOUT}`（config/settings.py:1098-1180，`_endpoint_slot` 统一读取）；`webui/services/providers.py:40-90`：`endpoints()` 只回 `has_api_key` 不回显、`update_endpoints()` 空串=不修改、经 `envfile.write_values` 落 .env、返回 `restart_required: true`；`test_endpoint/fetch_models`（providers.py:156-180）复用 `deploy/probe`。前端 `ProvidersPage.vue`（301 行）：has_api_key 徽章、「API Key（留空不变）」输入、每槽测试按钮、模型列表拉取、保存后「需重启生效」提示。[verified]
- WebUI cometa 面：`webui/routers/cometa.py` 全部 `require_auth`、写操作 `audit.record`（routers/cometa.py:26 起十个端点，无任何配置类端点）；服务经 `cometa.runtime.current_service()` 进程内定位（webui/services/cometa.py:40-45）；CometaPage.vue:187 的空态文案让用户手改 `.env` + toml + 重启。[verified]
- 配置装配：bot 进程 `build_runtime`（cometa/runtime.py:146-180）与 worker 子进程 `main()`（cometa/worker.py:269）各自 `CometaConfig.load()`；无热重载。[verified]
- 依赖声明：pyproject.toml:26 起 `[project.optional-dependencies]` 已有 `mcp` extra 先例（可选、版本钉住、注释说明理由）；**无 cometa/codex extra**——最终用户装不到 SDK。[verified]

## 3. Relevant Architecture

- 后端契约：`backends/base.py` AgentBackend；类型→工厂显式注册（backends/registry.py:52-61，「注册 ≠ 可用」，拒绝动态加载）；executor 认领时 resolve backend → probe → 开会话。[verified]
- 认证数据归属：auth 是**凭据**而非路由配置。进 cometa.toml 会被 `config_hash`（cometa/config.py:426，TOML 原始字节 sha256）吸进在途任务一致性守卫；放 STELLA_HOME 下独立目录则与 config_hash 解耦，改认证不影响在途任务——这是托管 home 方案的配置语义依据。[inferred]
- 三进程一致性约束：bot（probe/状态 API）与 worker（真执行）必须把 codex_home 解析到**同一路径**，否则健康检查说谎。[inferred]
- 前端范式：ProvidersPage.vue 是三端点编辑的既定实现；CometaPage.vue 目前只有运行面（提交/跟踪/产物/输入答复）。[verified]

## 4. GitNexus Findings

- `impact CodexBackend --direction upstream` → risk LOW / epistemic exact；d=1 依赖 = {backends/registry.py}。 [graph]
- `impact _auth_ok --direction upstream` → LOW/exact；唯一调用方 `probe`。 [graph]
- `context CometaConfig` → incoming imports 覆盖全部 12 个 cometa 模块 + 测试；对类的扩展是纯增量，无签名破坏面。 [graph]
- `impact handle_delegation_turn --direction upstream` → LOW/exact；唯一调用方 `activate_capabilities`（capability/hooks.py:357）——委派链路本计划不触碰。 [graph]
- 裸方法名 `load`/`health` 的 impact 查询返回 UNKNOWN（歧义不可解析）——已按规则弃用该入口，改用 `context CometaConfig` + 源读核实装配点（runtime.py:146 / worker.py:269）。 [graph]
- 生产代码中 `probe()` 调用仅 executor.py:121 一处（全仓 grep 复核）。 [verified]

## 5. Statement-Level PDG Findings

索引无 `--pdg` 层，且本计划中心函数（`probe` / `_build_codex` / `BackendConfig.from_toml`）均为全文源读过的短线性流程，不存在需要 PDG 裁决的多分支守卫或跨函数数据流——**PDG slice 跳过**。执行代理如需，可 `analyze --index-only --pdg` 后补建。

## 6. Proposed Changes

**C1 新增 `cometa/backends/codex_auth.py`** — codex 认证唯一真源模块：
- `codex_home_for(backend: BackendConfig, stella_home: Path) -> Path`：toml `env.CODEX_HOME` 显式声明则用之；否则默认 `stella_home/cometa/codex_home/<backend_id>/`。probe 与 `_build_codex` 必须经它同源解析。
- `auth_state(backend) -> CodexAuthState`：`ready_chatgpt | ready_api_key | ready_custom | legacy | none` + 面向用户的 reason。检测依据：托管 home 的 `auth.json`（含 tokens → chatgpt；含 OPENAI_API_KEY → api_key）；`config.toml` 声明 `model_provider="stella_custom"` 且凭据文件在 → custom；托管 home 为空而 `~/.codex/auth.json` 在 → legacy。
- `write_custom_endpoint(home, base_url, api_key, model, wire_api="chat")`：写 codex 原生 `config.toml`（`model` + `model_provider="stella_custom"` + `[model_providers.stella_custom]` 的 base_url/env_key="STELLA_CODEX_API_KEY"/wire_api；模板拼接 + TOML basic-string 转义，不引新依赖）+ 凭据文件 `stella_credentials.json`（JSON；POSIX 0600，Windows 尽力收紧）。
- `backend_spawn_env(backend) -> dict`：toml env ⊕ `CODEX_HOME` ⊕ custom 模式的 `STELLA_CODEX_API_KEY`（读凭据文件）——`_build_codex` 与登录流程共用。
- SDK 登录包装：`start_device_login` / `poll_device_login` / `login_with_api_key` / `account_status` / `logout`——临时 AsyncCodex（env=backend_spawn_env），用毕 close；阻塞调用经 `asyncio.to_thread`。约束：不阻塞事件循环；客户端不 close 即子进程泄漏。
- 行为变化：认证从「进程环境隐式继承」变为「每后端显式托管」；依赖：仅 stdlib + 可选 openai_codex。

**C2 `cometa/backends/codex.py`** — probe/build 换源：
- `probe()`：`_auth_ok()` → `codex_auth.auth_state`；`AUTH_REQUIRED` 的 reason 指名托管路径与 WebUI 配置入口；legacy 报 DEGRADED 附「可在 WebUI 一键迁移」；SDK 缺失文案维持今日安装指引（codex.py:146-149）。READY/DEGRADED 放行、其余 fail-closed 的语义不变。
- `_build_codex()`：env 换 `codex_auth.backend_spawn_env(self._config)`。
- `_auth_home/_auth_ok` 收缩为 legacy 检测助手。

**C3 新增 `webui/services/cometa_auth.py`** — WebUI 认证服务（providers 服务同款纪律）：
- `status(backend_id)` → `{backend_id, mode, ready, reason, has_api_key, has_custom_endpoint, legacy_available}`，**永不回显 key/token**；
- `apply_api_key(backend_id, api_key)`：空串=不修改；经 SDK `login_api_key` 落 auth.json；
- `apply_custom_endpoint(backend_id, {base_url, api_key, model, wire_api?})`：api_key 空串=保留原值（读旧凭据回填）；
- `start_device_login` / `device_login_status`：进程内 session 注册表 `{session_id: handle}`；bot 重启丢 session，前端重新发起（文档明示）；
- `migrate_legacy(backend_id)`：复制 `~/.codex/auth.json`（+config.toml 若有）→ 托管 home；仅显式触发，不静默搬运；
- `logout(backend_id)`；`test_endpoint(backend_id, base_url, api_key)` 复用 `deploy.probe.fetch_endpoint_models`（与 providers.test 同款）。
- 全部写操作由路由层记 audit；audit/payload 不含 key 原文。

**C4 `webui/routers/cometa.py`** — 新端点（全部 require_auth；写操作 audit；backend_id 必须存在且 type=="codex"，否则 400）：
- `GET  /api/v1/cometa/backends/{backend_id}/auth/status`
- `POST /api/v1/cometa/backends/{backend_id}/auth/api-key`
- `POST /api/v1/cometa/backends/{backend_id}/auth/custom-endpoint`
- `POST /api/v1/cometa/backends/{backend_id}/auth/device-login` → `{session_id, device_code, verification_url}`
- `GET  /api/v1/cometa/backends/{backend_id}/auth/device-login/{session_id}` → `{state, account?}`
- `POST /api/v1/cometa/backends/{backend_id}/auth/migrate-legacy`
- `POST /api/v1/cometa/backends/{backend_id}/auth/logout`
- `POST /api/v1/cometa/backends/{backend_id}/auth/test`

**C5 `dashboard/src/api/cometa.ts` + `dashboard/src/views/CometaPage.vue`** — 认证卡片：
- codex 型后端选择器 + 状态徽章（映射 auth_state 五态）；
- 三条路线 UI 全按 ProvidersPage 范式：API Key「留空不变」+ has_api_key 徽章；自定义端点表单（base_url/model/wire_api 下拉 chat|responses + 测试按钮 + 模型列表 chips）；设备码路线（展示 code+URL + 2s 轮询至 completed/failed）；
- legacy 迁移横幅；显式提示「认证即时生效，无需重启」（与 providers 页 restart_required 的差异要写清——probe 与任务启动现读托管 home）。

**C6 `pyproject.toml`** — `[project.optional-dependencies]` 增 `cometa = ["openai-codex==0.159.2"]`，注释照 mcp extra 格式（版本= M0 冻结值，升级须重跑 M0 探针）。

**C7 新增 `docs/cometa.md` + `docs/cometa.en.md`** — 安装、两条认证路线步骤、权限模型、故障诊断（M4 文档项的认证子集；docs/ 目录为中英成对惯例）。

依赖关系：C1 是 C2/C3 的地基；C3 依赖 C1；C4 依赖 C3；C5 依赖 C4 契约；C6/C7 独立可并行。

## 7. Implementation Sequence

1. **T-0 实机认证探针（先于一切 UI 承诺）**：脚本化验证 0.159.2 `login_chatgpt_device_code` 在本机代理/受限网络下的可用性、`login_api_key` 落盘 auth.json 的位置与内容形状、自定义 provider config.toml 跑通一轮真实 turn。结论固化为 fixtures/文档。失败则回 §12 OQ-1 调整路线。
2. C1 `codex_auth.py` + 单测（纯函数为主，tmp home 造各种形状，不依赖真 SDK）。
3. C2 `codex.py` 换源；`tests/cometa/test_backend_contract.py` 回归（probe 失败路径语义保持）。
4. C3+C4 WebUI 服务与端点 + `tests/webui/test_webui_cometa.py` 扩展（`cometa_runtime.set_current` 注入模式 + fake 托管 home）。
5. C5 前端（cometa.ts 客户端函数 → CometaPage.vue 认证卡片）。
6. C6 pyproject extra + C7 文档。
7. 端到端人工验收：清空托管 home → WebUI 自定义端点路线 → status ready → 提交真实 codex 任务 → succeeded；设备码路线登录 → account 可见；logout 回落。增补 `design_docs/test_checklist/Cometa人工测试清单_v1.0.md` 对应 T 项。

每步独立可停且树保持绿色（`pytest` + `ruff check .` 全仓——CI 既有纪律）。

## 8. Test Strategy

- 新增 `tests/cometa/test_codex_auth.py`：
  - codex_home_for：显式 env.CODEX_HOME 胜出 / 默认托管路径 / backend_id 隔离（两后端两 home）；
  - auth_state 五态判定（tmp home 分别造 auth.json 两种内容 / config.toml+凭据 / legacy ~/.codex / 全空）；
  - write_custom_endpoint：config.toml 含 base_url（含需转义字符用例）+ env_key 名 + 凭据文件内容；POSIX 0600 断言（Windows 跳过）；
  - backend_spawn_env：toml env ⊕ CODEX_HOME ⊕ key 的合并优先级。
- 扩展 `tests/webui/test_webui_cometa.py`：
  - status 响应无 key/token 原文（断言 JSON 全文不含写入值）；apply api_key 空串=不修改；custom-endpoint 写入后 status→ready_custom；device-login 轮询 pending→（fake handle）completed；非 codex 后端 400；cometa 未启用 503（现有基建）。
- 回归：`tests/cometa/` 全绿——尤其 test_backend_contract（probe 换源）与 test_cometa_config（schema 未变）；委派链路 `tests/capability/test_delegation.py` 零改动应保持绿。
- 边界/失败路径：凭据文件损坏 → auth_state=none + 明确 reason；登录 session 因重启丢失 → 重新发起；SDK 缺失 → status DEGRADED 且文案含安装指引。
- 验证命令（存在且可运行）：`python -m pytest tests/cometa tests/capability tests/webui/test_webui_cometa.py -q`；`python -m ruff check .`；CI 为 3.10/3.11/3.12 矩阵。

## 9. Risk and Impact Analysis

d=1 依赖盘点（impact 输出 + 源读）：
- `CometaConfig`（12 个 importer）：本计划不改其 schema——零感知。
- `CodexBackend`（d=1: registry.py）：构造路径不变；probe 语义 READY/DEGRADED 放行不变，仅判定来源换托管 home——`test_backend_contract.py` 是回归闸。
- `probe()`（d=1: executor.run_attempt:121）：认领期 fail-fast 行为保持；失败 reason 更可操作（指向 WebUI 配置入口）。
- WebUI：纯增量端点，现有 8 个端点与鉴权/审计基建不动。
- 其他消费方：ProvidersPage.vue / providers 服务只作范式参照，不修改；委派链路（hooks/delegation）零改动。

风险：
- R1 设备码登录在受限网络不可用（国内网络正是本需求动因）→ T-0 探针先行；若不可用，自定义端点路线成为缺省推荐（产品语义，非缺陷）。
- R2 codex 对自定义 provider config.toml 的键名/行为未经真实运行验证（目前证据是二进制键命中）→ T-0 一轮真实 turn 通过才算 DoD。
- R3 凭据安全：auth.json 含 ChatGPT refresh token、stella_credentials.json 含明文 key——不进日志/audit/DB/tasks.db/cometa.toml；文件权限尽力收紧；文档写明存放位置与删除方式（logout/手动删除托管 home）。
- R4 SDK 客户端生命周期：登录流的 AsyncCodex 必须 close，否则 app-server 子进程泄漏（webui 进程常驻）。
- R5 「无需重启」口径：providers 页保存要重启（registry import 期冻结），cometa 认证不需要（probe/任务启动现读托管 home）——前端文案与文档必须一致，避免用户误等重启。
- 并发/事务：无 SQLite/事务面变更。性能：status 每次为文件 stat +（设备码完成后）一次 account() 调用，前端 5s 轮询可承受。

## 10. Files Expected to Change

| File | Symbols | Reason |
| --- | --- | --- |
| cometa/backends/codex_auth.py (new) | codex_home_for, auth_state, write_custom_endpoint, backend_spawn_env, 登录包装 | 认证唯一真源 |
| cometa/backends/codex.py | probe, _build_codex, _auth_home, _auth_ok | 换源 codex_auth；reason 可操作化 |
| webui/services/cometa_auth.py (new) | status / apply_api_key / apply_custom_endpoint / device_login / migrate_legacy / logout / test_endpoint | providers 同款服务纪律 |
| webui/routers/cometa.py | 8 个新 auth 端点 | 认证管理 API |
| dashboard/src/api/cometa.ts | +8 client 函数 | 前端契约 |
| dashboard/src/views/CometaPage.vue | 认证卡片 | 双路线 UI |
| pyproject.toml | optional-dependencies | cometa extra（0.159.2） |
| docs/cometa.md / docs/cometa.en.md (new) | — | 认证与安装文档 |
| tests/cometa/test_codex_auth.py (new) | — | 单测 |
| tests/webui/test_webui_cometa.py | 扩展 | 端点测试 |
| design_docs/test_checklist/Cometa人工测试清单_v1.0.md | 增补 T 项 | 验收清单 |

## 11. Reusable Implementation Context

```yaml
implementation_context:
  task_summary: >
    codex 后端认证配置化：每后端托管 codex_home（STELLA_HOME/cometa/codex_home/<id>）+
    WebUI 双路线（ChatGPT 设备码/API-key 登录 + 自定义 OpenAI 兼容端点），
    交互纪律对齐三端点 providers 模式（has_api_key/空串不修改/测试复用 probe）；
    修复 probe 与 _build_codex 的 codex_home 解析不一致；pyproject 增 cometa extra。
  acceptance_criteria:
    - 全新环境（无 ~/.codex）经 WebUI 自定义端点路线配置后 probe=ready 且真实任务 succeeded
    - 设备码路线登录后 status=ready_chatgpt 且 account 可见；logout 后回落
    - probe 与 _build_codex 对同一 backend 解析出同一 codex_home（单测证明）
    - status/audit/日志零秘密回显；空串=不修改有测试
    - pytest 矩阵与 ruff check . 全绿；cometa.toml schema 与 config_hash 语义不变

  evidence_provenance: {
  "schema_version": 2,
  "head_commit": "e20f6794a250d76d80de1403983050856f6da13e",
  "generated_plan_path": "docs/plans/2026-10-01-gitnexus-plan-cometa-codex-auth-webui.md",
  "global_dirty_digest": {
    "algorithm": "sha256",
    "canonicalization": "gitnexus-evidence-provenance-v2 NUL-framed UTF-8 records",
    "value": "0a9c85780067d9afcd0764f307b60891e3cee927ee11eaeb5ec7826d10fd82cd"
  },
  "cited_path_manifest": [
    {
      "path": "cometa/backends/codex.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:34a2678ed2b7ae9e879256621a93b43d42318bd7586563087cb87a733127c544",
      "index_digest": "sha256:34a2678ed2b7ae9e879256621a93b43d42318bd7586563087cb87a733127c544",
      "worktree_digest": "sha256:34a2678ed2b7ae9e879256621a93b43d42318bd7586563087cb87a733127c544",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/backends/registry.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:9115f42e3d4226294307acade33a775467c8b671cc984868ae95f246add8194a",
      "index_digest": "sha256:9115f42e3d4226294307acade33a775467c8b671cc984868ae95f246add8194a",
      "worktree_digest": "sha256:9115f42e3d4226294307acade33a775467c8b671cc984868ae95f246add8194a",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/config.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6979b24c2afd1c7f9bfac4ec402da7c72303097ddd000398d4180d19bed225f3",
      "index_digest": "sha256:6979b24c2afd1c7f9bfac4ec402da7c72303097ddd000398d4180d19bed225f3",
      "worktree_digest": "sha256:6979b24c2afd1c7f9bfac4ec402da7c72303097ddd000398d4180d19bed225f3",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/executor.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:1e81aa14775dfc4a02e7850887326a59c32e52a29efc5f8b44d26127e6e54068",
      "index_digest": "sha256:1e81aa14775dfc4a02e7850887326a59c32e52a29efc5f8b44d26127e6e54068",
      "worktree_digest": "sha256:1e81aa14775dfc4a02e7850887326a59c32e52a29efc5f8b44d26127e6e54068",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/runtime.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:75129c68b0047be06c7bf5d54e729d9eba1b1310c7e9d9cffee04033c6df4988",
      "index_digest": "sha256:75129c68b0047be06c7bf5d54e729d9eba1b1310c7e9d9cffee04033c6df4988",
      "worktree_digest": "sha256:75129c68b0047be06c7bf5d54e729d9eba1b1310c7e9d9cffee04033c6df4988",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/service.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:bd51ca625dcde43062308e3676a046ab0f591f285cc24f552eed8bb19b052997",
      "index_digest": "sha256:bd51ca625dcde43062308e3676a046ab0f591f285cc24f552eed8bb19b052997",
      "worktree_digest": "sha256:bd51ca625dcde43062308e3676a046ab0f591f285cc24f552eed8bb19b052997",
      "untracked_digest": "absent"
    },
    {
      "path": "cometa/worker.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:27bebd505db32c07b56f6a985f66bc97ba93ddd2c165b6314fe4fab46252b6e9",
      "index_digest": "sha256:27bebd505db32c07b56f6a985f66bc97ba93ddd2c165b6314fe4fab46252b6e9",
      "worktree_digest": "sha256:27bebd505db32c07b56f6a985f66bc97ba93ddd2c165b6314fe4fab46252b6e9",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/api/cometa.ts",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:a13d6f2e11f58bb0a6d3fae302df9e7efb3aebfd68084444db537d427659c693",
      "index_digest": "sha256:a13d6f2e11f58bb0a6d3fae302df9e7efb3aebfd68084444db537d427659c693",
      "worktree_digest": "sha256:a13d6f2e11f58bb0a6d3fae302df9e7efb3aebfd68084444db537d427659c693",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/views/CometaPage.vue",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:cee2cc4e3a37a1df1d1f5dd012bf40d4e0aa5178458b829470eb6ac1a0e0111e",
      "index_digest": "sha256:cee2cc4e3a37a1df1d1f5dd012bf40d4e0aa5178458b829470eb6ac1a0e0111e",
      "worktree_digest": "sha256:cee2cc4e3a37a1df1d1f5dd012bf40d4e0aa5178458b829470eb6ac1a0e0111e",
      "untracked_digest": "absent"
    },
    {
      "path": "dashboard/src/views/ProvidersPage.vue",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:e84f14a7d07cb409162d6ce903e0fbef36035f14482f62366eab65934131497e",
      "index_digest": "sha256:e84f14a7d07cb409162d6ce903e0fbef36035f14482f62366eab65934131497e",
      "worktree_digest": "sha256:4d752d414d0cb2db31e6a45b169c12c97534127e119a673763b47c44b3e2078d",
      "untracked_digest": "absent"
    },
    {
      "path": "pyproject.toml",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:6142289c02a8e7c7fb7afe4e06a78f75689f2b07e7f7fa70523a24e929d9c813",
      "index_digest": "sha256:6142289c02a8e7c7fb7afe4e06a78f75689f2b07e7f7fa70523a24e929d9c813",
      "worktree_digest": "sha256:522ee41375d2e2ed9fa558544a27e9bf3a5b1758f6934abb3eb67fde48fd591b",
      "untracked_digest": "absent"
    },
    {
      "path": "tests/webui/test_webui_cometa.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:2d47a8af36d12ba206fa85eaf778eb9b2dba804711944c5bf0fe7a0215746573",
      "index_digest": "sha256:2d47a8af36d12ba206fa85eaf778eb9b2dba804711944c5bf0fe7a0215746573",
      "worktree_digest": "sha256:2d47a8af36d12ba206fa85eaf778eb9b2dba804711944c5bf0fe7a0215746573",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/routers/cometa.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:929759fcc827cccd919fbb61ac1dad52c3bfee907ed5373b0764882b9b45015c",
      "index_digest": "sha256:929759fcc827cccd919fbb61ac1dad52c3bfee907ed5373b0764882b9b45015c",
      "worktree_digest": "sha256:929759fcc827cccd919fbb61ac1dad52c3bfee907ed5373b0764882b9b45015c",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/routers/config.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:b5caa4d6338b9c278fbdc9a63ef6cd16947131395ff3b8b8525936b5aa6b206b",
      "index_digest": "sha256:b5caa4d6338b9c278fbdc9a63ef6cd16947131395ff3b8b8525936b5aa6b206b",
      "worktree_digest": "sha256:dc928df085691de413780b527d5036f45aa87d25c2aedecd46ce14e5733ace81",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/services/cometa.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:c985ee1b5cbfcc6e4d7a35f98f0be74fa0b01ccc68d99d80aa61e400115d17ca",
      "index_digest": "sha256:c985ee1b5cbfcc6e4d7a35f98f0be74fa0b01ccc68d99d80aa61e400115d17ca",
      "worktree_digest": "sha256:c985ee1b5cbfcc6e4d7a35f98f0be74fa0b01ccc68d99d80aa61e400115d17ca",
      "untracked_digest": "absent"
    },
    {
      "path": "webui/services/providers.py",
      "object_kind": {
        "head": "regular",
        "index": "regular",
        "worktree": "regular",
        "untracked": "absent"
      },
      "state": "clean",
      "rename_from": null,
      "rename_to": null,
      "head_digest": "sha256:706fc218432bcfc3b3155cd4a66d8759f5a264cae74cc1181824ba11afa92c97",
      "index_digest": "sha256:706fc218432bcfc3b3155cd4a66d8759f5a264cae74cc1181824ba11afa92c97",
      "worktree_digest": "sha256:296717473e5dac05aa5bf0456f4962c5eb90ff602c14f2e810f12974778c30e5",
      "untracked_digest": "absent"
    }
  ]
}

  primary_symbols:
    - symbol: CodexBackend
      file: cometa/backends/codex.py
      lines: 96-303
      role: 认证消费方；probe/_build_codex 换源到 codex_auth
    - symbol: _auth_ok / _auth_home
      file: cometa/backends/codex.py
      lines: 84-93
      role: 现认证判定（bot 进程 env 视角），收缩为 legacy 检测
    - symbol: BackendConfig
      file: cometa/config.py
      lines: 127-184
      role: env 透传字段已支撑 CODEX_HOME；本计划不改其 schema
    - symbol: providers_service (endpoints/update_endpoints/test_endpoint)
      file: webui/services/providers.py
      lines: 40-180
      role: 三端点交互纪律的范式来源（只参照不修改）
    - symbol: cometa router
      file: webui/routers/cometa.py
      lines: 26-53
      role: 新 auth 端点宿主（require_auth + audit 基建现成）

  related_symbols:
    - relationship: CALLS
      relevance: executor.run_attempt (cometa/executor.py:121) 是 probe 唯一生产调用点——认领期 fail-fast 语义保持
    - relationship: CALLS
      relevance: CometaService.health (cometa/service.py:384-398) 今日不探测后端——前端可见性缺口
    - relationship: FACTORY
      relevance: BackendRegistry.create / default_registry (cometa/backends/registry.py:41-61) 构造后端，不变
    - relationship: REUSES
      relevance: deploy.probe.fetch_endpoint_models —— auth/test 端点复用（providers.py:156 已同款）
    - relationship: TESTS-OF
      relevance: tests/webui/test_webui_cometa.py (cometa_runtime.set_current 注入)；tests/cometa/test_backend_contract.py
    - relationship: EXTERNAL
      relevance: openai_codex 0.159.2 login_api_key/login_chatgpt_device_code/account/logout + CodexConfig(env/config_overrides)（仓库外，site-packages）
    - relationship: EXTERNAL
      relevance: codex 原生 config.toml 的 model_provider/model_providers.*.{base_url,env_key,wire_api}（二进制键命中，T-0 待实机验证）

  execution_path:
    - 用户打开 WebUI cometa 页认证卡片 → GET auth/status（codex_auth.auth_state：读托管 home 文件形状）
    - 自定义端点路线：POST custom-endpoint → 托管 home 写 config.toml + stella_credentials.json → status=ready_custom
    - 提交任务 → worker executor 认领 → probe（托管 home READY）→ _build_codex 注入 CODEX_HOME+STELLA_CODEX_API_KEY → app-server 读 codex_home → turn 执行
    - 设备码路线：POST device-login → 页面展示 code+URL → GET 轮询 → completed → auth.json 落托管 home → status=ready_chatgpt
    - legacy 环境：status 报 legacy_available → 一键 migrate 复制 ~/.codex 到托管 home

  pdg_constraints: [] # 索引无 --pdg 层；中心函数为短线性流程（见 §5），未建 slice

  architectural_patterns:
    - pattern: 三端点 providers 契约（has_api_key / 空串不修改 / test 复用 deploy.probe / 写操作 audit）
      example_location: webui/services/providers.py (endpoints/update_endpoints/test_endpoint)
      usage_guidance: cometa_auth 服务逐条照抄该纪律；唯一有意差异=无 restart_required（认证现读现用）
    - pattern: fail-closed probe（不降级、给可操作 reason）
      example_location: cometa/backends/codex.py (probe, codex.py:131-158)
      usage_guidance: 判定换源不换语义；READY/DEGRADED 放行，其余 fail-closed
    - pattern: router require_auth + audit.record + ApiError 译码
      example_location: webui/routers/cometa.py / webui/services/cometa.py (map_error)
      usage_guidance: 新端点零新基建
    - pattern: 显式后端类型注册表（拒绝动态加载）
      example_location: cometa/backends/registry.py (default_registry)
      usage_guidance: 不为认证引入新后端类型或动态导入

  files_to_modify:
    - file: cometa/backends/codex_auth.py
      symbols: [codex_home_for, auth_state, write_custom_endpoint, backend_spawn_env, start_device_login, poll_device_login, login_with_api_key, account_status, logout]
      intended_change: 新增——托管 home 解析/状态判定/凭据与 config.toml 写入/SDK 登录包装
    - file: cometa/backends/codex.py
      symbols: [probe, _build_codex, _auth_home, _auth_ok]
      intended_change: probe/_build_codex 换源 codex_auth；reason 指名托管路径与 WebUI 入口
    - file: webui/services/cometa_auth.py
      symbols: [status, apply_api_key, apply_custom_endpoint, start_device_login, device_login_status, migrate_legacy, logout, test_endpoint]
      intended_change: 新增——providers 同款服务纪律 + 设备码 session 注册表
    - file: webui/routers/cometa.py
      symbols: [8 个 auth 端点]
      intended_change: 新增端点，require_auth + 写操作 audit + backend_id/type 校验
    - file: dashboard/src/api/cometa.ts
      symbols: [getAuthStatus, applyApiKey, applyCustomEndpoint, startDeviceLogin, getDeviceLogin, migrateLegacy, logoutBackend, testAuthEndpoint]
      intended_change: 新增 client 函数
    - file: dashboard/src/views/CometaPage.vue
      symbols: [认证卡片]
      intended_change: codex 后端选择器 + 五态徽章 + 三路线表单（ProvidersPage 范式）+ legacy 迁移横幅 + 免重启提示
    - file: pyproject.toml
      symbols: ['[project.optional-dependencies].cometa']
      intended_change: cometa = ["openai-codex==0.159.2"]（mcp extra 注释格式）
    - file: docs/cometa.md (+ .en.md)
      symbols: []
      intended_change: 新增——安装/两条认证路线/权限/故障诊断
    - file: tests/cometa/test_codex_auth.py
      symbols: []
      intended_change: 新增单测（见 §8 场景清单）
    - file: tests/webui/test_webui_cometa.py
      symbols: []
      intended_change: 扩展 auth 端点测试（set_current 注入 + fake 托管 home）

  tests:
    - file: tests/cometa/test_codex_auth.py
      scenarios:
        - 显式 env.CODEX_HOME → codex_home_for 返回它；未声明 → STELLA_HOME/cometa/codex_home/<backend_id>
        - 两个 backend_id → 两个不同托管 home（隔离）
        - auth.json 含 tokens → ready_chatgpt；含 OPENAI_API_KEY → ready_api_key；config.toml+凭据 → ready_custom；仅 ~/.codex → legacy；全空 → none
        - write_custom_endpoint 后 config.toml 可被 tomllib 解析且 base_url（含引号/反斜杠用例）正确
        - backend_spawn_env 合并：toml env < CODEX_HOME 注入 < custom key 注入不互相覆盖错误
        - 凭据文件损坏/缺失 → auth_state=none 且 reason 可读
    - file: tests/webui/test_webui_cometa.py
      scenarios:
        - GET auth/status 响应全文不含 api_key 原文（has_api_key 布尔替代）
        - POST api-key 空串 → 304 语义不修改（status 不变）
        - POST custom-endpoint（含合法 base_url/model）→ status=ready_custom；再次提交空 key → 保留原 key
        - POST device-login → 返回 session_id/code/url；GET 轮询 fake handle → state 迁移
        - backend_id 不存在或 type!=codex → 400；cometa 未启用 → 503
        - logout 后 status 回 none

  verification_commands:
    - python -m pytest tests/cometa tests/capability tests/webui/test_webui_cometa.py -q
    - python -m ruff check .
    - MSYS_NO_PATHCONV=1 docker exec -w /repo stella-gitnexus gitnexus status  # 图索引新鲜度（docker gitnexus，宿主 CLI registry foreign）

  risks:
    - R1 设备码登录在受限网络不可用 → T-0 探针先行；不可用则自定义端点为缺省推荐
    - R2 codex 自定义 provider config.toml 行为未经真实运行验证 → T-0 一轮真实 turn 为 DoD 前置
    - R3 凭据文件安全（refresh token/明文 key）→ 零回显 + 权限收紧 + 文档写明位置与删除方式
    - R4 登录用 AsyncCodex 用毕必须 close，否则 app-server 子进程泄漏
    - R5 「免重启」口径前后端与文档必须一致（与 providers 页 restart_required 的有意差异）

  assumptions:
    - A1 SDK login_api_key 写 auth.json 的位置由进程 env CODEX_HOME 决定——T-0 验证（做法：临时 CODEX_HOME 下登录后 stat 文件）
    - A2 codex 0.159.2 自定义 provider config.toml 键集语义与公开文档一致——T-0 一轮真实 turn 验证（做法：指向任意 OpenAI 兼容端点跑一个 min turn）
    - A3 deploy.probe.fetch_endpoint_models 对任意 OpenAI 兼容端点可用（providers 页已在用同一实现）
    - A4 设备码轮询 2s 间隔无速率冲突（codex 侧无已知限制；T-0 观察）

  open_questions:
    - OQ-1 设备码流若在目标网络不可用，登录请求是否要暴露代理字段 UI（toml env 透传已天然支持，先不做 UI）
    - OQ-2 wire_api 首版 UI 是否就给 chat|responses 下拉，还是仅文件层支持默认 chat
    - OQ-3 多 codex 后端共享自定义端点时每 home 重复存 key 是否可接受（首版按每后端隔离）
    - OQ-4 NSIS 离线打包 openai-codex wheel——发布链专项，本计划不含

  avoid:
    - 不要把 key/token 写进 audit、日志、tasks.db、cometa.toml 或任何回显响应
    - 不要改 cometa.toml schema 或 config_hash 语义（认证必须在 config_hash 之外）
    - 不要给 QQ 端增加认证/凭据命令（凭据入口只有 WebUI 管理员路径）
    - 不要热重载 cometa 路由配置（重启语义照旧；托管 home 内的认证文件例外——现读现用）
    - 不要升级 openai-codex 版本（0.159.2 为 M0 冻结矩阵；升级须重跑 M0 探针）
    - 不要重复全文仓库发现——本 pack 已定位全部接入点；执行器只做廉价复核
```

## 12. Assumptions and Open Questions

假设（执行代理执行前须廉价复核，方法见 §11 pack 的 assumptions 字段）：A1 CODEX_HOME 决定 login_api_key 落盘位置；A2 codex 自定义 provider config.toml 键集在 0.159.2 的行为（二进制键命中是间接证据）；A3 fetch_endpoint_models 通用性；A4 设备码轮询频率无冲突。以上全部由 T-0 实机探针收敛为 [verified]。

开放问题：OQ-1 设备码登录的代理字段是否上 UI；OQ-2 wire_api 下拉是否首版暴露；OQ-3 多后端共享端点的凭据重复；OQ-4 NSIS 离线打包 SDK wheel（发布链专项）。

明确推迟（相邻工作，本计划不含）：问题 1 的 auto 委派灰度门（`decide_auto` 无 auto 专属名单）与回复自然化（`_build_summary` 只取 codex 答复首行）——已在本会话早前分析中定位（capability/delegation.py:138-154、cometa/executor.py:677-680），另立计划。

## 13. Definition of Done

1. 全新环境（无 `~/.codex`）：WebUI 自定义端点路线配置 → `auth/status` ready → 提交真实 codex 任务 → succeeded（E2E 手测，记入人工清单）。
2. 设备码路线：登录完成 → status=ready_chatgpt 且 account 信息可见；logout 后回落 none/AUTH_REQUIRED。
3. probe 一致性：toml env 显式声明 CODEX_HOME 时，probe 与 `_build_codex` 解析同一路径（单测证明）；默认托管路径用例齐备。
4. 秘密零回显：status 响应、audit 记录、日志中无 key/token 原文（测试断言响应全文）。
5. 空串=不修改语义有测试。
6. `python -m pytest tests/cometa tests/capability tests/webui/test_webui_cometa.py -q` 与 `python -m ruff check .` 全绿；cometa.toml schema 与 config_hash 语义无变化。
7. T-0 探针结论归档（设备码可用性 + 自定义端点真实 turn 证据）；docs/cometa.md 双语覆盖两条路线与卸载。
