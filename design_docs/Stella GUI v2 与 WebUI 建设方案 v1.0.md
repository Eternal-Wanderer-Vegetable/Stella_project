# Stella GUI v2 与 WebUI 建设方案 v1.0

日期：2026-09-22
状态：**评审定案（2026-09-22，见 §19），可实施**（本文档只做设计，未修改任何代码）
参考基线：AstrBot `master`（2026-09-22 浅克隆于 `E:\stella\_reference\AstrBot`，Dashboard 为 `dashboard/` 内嵌 Vue3 工程）、`design_docs/AstrBot 特性吸收对比报告.md`（2026-09-21）
关联分支：`feat/user-cron-agent`（调度子系统已完成，是本方案 M3 的重要前置）

---

## 1. 目标与非目标

### 1.1 目标

1. **重置 Stella 的 GUI，作为 v2 独立演进**：v2 与现有 `stella-installer/`（Tauri 2 + 原生 HTML/JS，下称 v1）在代码上完全隔离，不允许混杂；v2 稳定后归档 v1（见 §16）。
2. **给 Stella 增加 WebUI**：浏览器直接访问 `http://<host>:<port>/` 即可使用与桌面 GUI 完全相同的控制面——与 AstrBot 的使用方式趋同。
3. **与 AstrBot Dashboard 趋同**：信息架构（侧栏导航、页面划分）、交互范式（workbench 双栏、schema 驱动表单、未保存守卫、toast 反馈）、API 风格（`/api/v1` REST + `{status,message,data}` envelope）、视觉语言（Vuetify 3、明暗主题），使 AstrBot 用户零学习成本迁移到 Stella。**趋同指范式与交互的趋同，不复制 AstrBot 源码**（理由见 §4 D9）。
4. **管理面补齐**：把对比报告确定的五个已落地子系统（插件、MCP、Skills、知识库、定时任务/Cron Agent）从「只读观测 / 群聊指令」升级为「WebUI 全功能管理」。
5. **新增 WebChat**：在 Dashboard 内直接与 Stella 对话（AstrBot ChatUI 的对应物），并与群聊记忆严格隔离。

### 1.2 非目标（本期不做）

- 多用户 / 细粒度 RBAC / 多租户（v2 为单管理员模型，API Key 与只读角色后置，见 §19）。
- 配置热更新（`config/settings.py` 是 import 期一次性读取，v2 保存配置后提示重启生效；改造成热更新不属于本方案）。
- 多平台适配器（Telegram/Discord 等，对比报告列为中长期，本方案只在 `/platforms` 页留出单适配器布局的扩展位）。
- 插件市场「一键全部更新」等批量生态运维功能（多源市场浏览、单插件安装/更新先行；跨源批量更新后置）。
- 语音 Live Chat（AstrBot 的 live_chat 是语音实时对话，依赖 STT/TTS provider；Stella 无此基建）。
- 移动端原生 App / 小程序（响应式布局跟随 Vuetify 默认能力，不做专门优化）。

---

## 2. 现状盘点（结论摘要）

### 2.1 Stella v1 GUI（将被重置的对象）

- 位置 `stella-installer/`：Tauri 2 桌面应用，前端为**零构建**原生 HTML/JS（无 npm），`withGlobalTauri` 直接调 `window.__TAURI__`。
- 功能页：运行状态（启停/日志 tail/链路健康）、用量（只读）、插件（只读）、设置（连接/模型/人格/高级 .env 全量表单）、环境自检（doctor）、旧数据迁移向导。
- **前后端机制**：GUI → Tauri invoke（12 个 Rust command）→ 子进程 `python -m deploy <args>`（stdout JSON）→ 仅 status 一项再经回环 HTTP `GET /stella/status`。三层间接，无写操作 API。
- 离线能力：安装引导（下载嵌入式 Python、装依赖）、doctor、migrate、首启配置向导——这些发生在 Bot 进程运行之前，是 v2 必须保留的桌面壳职责（见 §4 D5）。

### 2.2 Stella 后端可复用的资产

| 资产 | 位置 | 对 v2 的意义 |
|---|---|---|
| 常驻 ASGI app（FastAPI/uvicorn，`HOST:PORT` 默认 8080） | `bot.py` + NoneBot | WebUI 挂载点，**不新增端口**的先例 |
| `/stella/status` 只读状态接口（回环+脱敏+测试钉死） | `stella_project/plugins/bot_main/status_api.py` | v2 `/welcome` 数据源雏形；v1 兼容期保持不变 |
| `.env` 配置 schema 管线 | `deploy/env_schema.py build_schema()`（AST 提取 key/默认/类型/choice/inherits/分组/注释） | v2 配置页直接复用，等价于 AstrBot 的 config metadata |
| 能力清单快照 | `capability/inventory.py snapshot()` | 插件页/扩展页数据源 |
| MCP Manager | `capability/providers/mcp/manager.py`（load_config/start/status/catalog/call_tool） | MCP 页后端；`config/mcp.toml` 为存储 |
| 知识库门面 | `knowledge/service.py`（create_kb/submit/publish/search/acl/kb_status/list_accessible） | 知识库页后端 |
| 调度服务 | `stella_project/plugins/bot_main/scheduling/service.py`（create/list/edit/pause/resume/cancel/run_now/history/audit_log + 配额/权限/审计） | 定时任务页后端，**已具备完整 CRUD** |
| Skills 运行时 | `skills/`（discovery/catalog/runtime/sandbox/audit） | Skills 页后端 |
| 插件加载器 | `astrbot_compat/loader.py`（discover/load_all/initialize/terminate/get_failed）+ `astrbot_compat/config.py`（AstrBotConfig schema→`data/config/<name>_config.json`） | 插件页后端 |
| 用量日账 | `core/llm/usage_store.py`（sqlite 按日、预算判据、快照） | 统计图表数据源 |
| 结构化日志 | `core/logging_sink.py` → `STELLA_HOME/logs/stella.jsonl` | 日志页 SSE tail 数据源 |
| 进程管理 CLI | `deploy/process.py`（start --detach/stop/status）、`deploy/runtime.py`（envelope 契约） | 桌面壳与重启流程复用 |
| 模型拉取 | Rust `list_models`（ureq 直连 `{base_url}/v1/models`）→ v2 改由 Python 端实现 | providers 页「拉取模型」按钮 |

### 2.3 AstrBot Dashboard 参考（详见附录 A）

- 前端：Vue 3.3 + TypeScript + Vuetify 3.7 + Pinia + vue-router(hash) + vue-i18n + Vite；图表 apexcharts；编辑器 Monaco；Markdown 渲染 markstream-vue/markdown-it；i18n 按 `locales/{lang}/{core,features}` 分模块。
- 后端：FastAPI + hypercorn；`/api/v1/*`（OpenAPI 导出）+ legacy `/api/*` 双轨；JWT(HS256, Bearer+Cookie) + 可选 TOTP + API Key scope 体系；登录限流；静态托管 SPA dist 于根路径。
- 侧栏导航：欢迎 / 平台 / 提供商 / 扩展(插件市场·MCP·Skills) / 配置 / 知识库 / 人格 / 数据(统计·会话·日志·Trace) / 更多(会话管理·定时任务·子代理)。
- 页面范式：**workbench 双栏**（左列表右编辑器）、**schema 驱动递归表单**（metadata `{type,description,hint,items,condition}` → string/int/bool/list/dict/file/editor 控件）、**Tab 壳 + 子路由**（数据页/扩展页）、**SSE 流**（POST 发起聊天、logs live 带 Last-Event-ID 续传）。
- 桌面形态：AstrBot Desktop 通过环境变量 `ASTRBOT_DESKTOP_MANAGED=1` + 回环 `X-AstrBot-Desktop-Session` 秘钥头换发 JWT，实现壳内免登录；桌面管理的后端拒绝从 WebUI 自更新/自重启。

---

## 3. 总体形态（一句话版）

> **一套 Dashboard 前端 + 一个 Python WebUI 后端，两种宿主**：
> 浏览器访问 Bot 进程自带的面板（WebUI）；Tauri v2 桌面壳加载同一套面板并在 Bot 离线时提供安装/配置/启停的窄接口（v2 GUI）。v1 GUI 冻结，待 v2 稳定后归档。

```
                         ┌────────────────────────────┐
   浏览器 ──────── HTTP ──►  Bot 进程 (NoneBot ASGI :8080)  │
                         │  ├─ /onebot/v11/ws (NapCat)  │
                         │  ├─ /stella/status (v1 兼容) │
   桌面壳 v2 ── WebView ──►│  ├─ /api/v1/*  (webui 新增)  │
   (Tauri 2)              │  └─ /*        SPA (webui 托管)│
     │ 离线时 invoke       └────────────────────────────┘
     ▼
   python -m deploy (doctor/migrate/init/start/stop/log-tail)   ← 窄契约，仅 Bot 离线时
```

---

## 4. 关键决策记录（D1–D10）

### D1 GUI 与 WebUI 是同一套代码，不是两个项目

**决策**：v2 只建一个前端工程 `dashboard/`（Vue3 SPA）。桌面形态 = Tauri 壳加载该 SPA；浏览器形态 = Bot 进程托管该 SPA。
**理由**：这正是 AstrBot 的模型（AstrBot Desktop 的 webview 加载 core 托管的 Dashboard）。两套界面必然漂移，维护成本双倍；且 Stella v1 已证明「桌面壳只是渲染层」可行。
**后果**：桌面壳离线时需要窄契约兜底（D5）。

### D2 WebUI 后端挂在 Bot 进程内，不新增端口

**决策**：新增顶层 Python 包 `webui/`，以 FastAPI 子应用形式挂到 NoneBot 已有 ASGI app 上（复用 `status_api.setup_status_api()` 的注册先例），API 前缀 `/api/v1`，SPA 由同一端口根路径托管。
**理由**：Stella 的一条既有架构原则就是「不新增端口」（`/stella/status` 的设计注释）；Docker/compose、防火墙、NapCat 反向 WS 配置全部不用动。
**替代方案否决**：独立 uvicorn 端口（管理面与 Bot 分离，可管理 Bot 生命周期）——被否，因为它引入端口协商、第二份鉴权、Docker 双端口暴露，且与既有原则冲突。§19 保留其为未来「带外管理」演进方向。
**挂载顺序风险与对策**：`app.mount("/", ...)` 必须在 OneBot WS 路由与 `/stella/status` 注册**之后**执行（放在 lifespan 最后一个 startup 钩子）。用路由回归测试钉死四类路径：`/onebot/v11/ws`（WS 不被吞）、`/stella/status`（回环 200/非回环 403 不变）、`/api/v1/auth/setup-status`（200）、`/`（SPA index 200）。

### D3 前端技术栈与 AstrBot 同构

**决策**：Vue 3 + TypeScript + Vite + **Vuetify 3** + Pinia + vue-router（hash 模式）+ vue-i18n + apexcharts + Monaco + pnpm。
**理由**：趋同的第一性是交互范式趋同，范式由组件库承载。AstrBot 用 Vuetify 3（Materio 模板风格），Stella 用同一组件库可以用同类组件还原同类布局（导航抽屉、workbench、v-data-table、v-dialog、snackbar）。
**品牌区分**：主题色不抄 AstrBot 紫色系，Stella 定义自己的主题令牌（见 §10.5），但布局结构、组件用法、明暗切换逻辑保持同类。

### D4 API 契约先行，envelope 与路径风格照搬 AstrBot

**决策**：
- 响应统一 `{"status":"ok"|"error", "message":..., "data":...}`（同 AstrBot `responses.py`）；HTTP 状态码只用于 401/403/404/413/429/500。
- 路径统一 `/api/v1/{资源}` REST；schema 与数据分离（`GET /api/v1/xxx/schema` 下发渲染元数据，前端递归渲染）。
- 仓库根新增 `openspec/openapi-v1.yaml` 作为契约源，前端用 openapi-typescript 生成类型化客户端（对齐 AstrBot 的 `generate:api` 流程，但不引入 hey-api 运行时，仅生成 TS 类型 + 手写薄封装，减少运行时依赖）。
**理由**：契约先行让前后端并行开发；AstrBot 用户抓包看到的也是同构请求。

### D5 桌面壳保留「离线窄契约」，而不是把安装逻辑搬进 WebUI

**决策**：Tauri v2 壳（新目录 `desktop/`）只保留 v1 已验证的 7 个离线职责：bootstrap（下载嵌入式 Python/装依赖）、doctor、migrate、读配置、写配置（`deploy init --answers`）、start/stop、日志文件 tail。前端 API 层做 **transport 抽象**：`httpBackend`（默认，Bot 在线）/ `tauriBackend`（探测到 `window.__TAURI__` 且 `/api/v1/status` 不可达时），两者只覆盖上述窄契约，其余页面在离线态显示「后端未运行」占位卡 + 启动按钮。
**理由**：WebUI 由 Bot 进程托管，Bot 没起就没有 WebUI——首装/首配必须有一条不依赖 Bot 进程的路径（v1 的既有能力，不能丢）。但把全部 API 在 Rust 重写一遍不可接受，窄契约是 v1 真实功能集的精确投影，无重复逻辑。
**在线后的免登录**：壳启动 Bot 时生成 ≥32 字符随机 secret 注入子进程环境变量 `STELLA_DESKTOP_SESSION_SECRET`，WebUI 提供 `POST /api/v1/auth/desktop-session`（回环 + `X-Stella-Desktop-Session` 头 + 恒定时间比较）换发正式 JWT——照搬 AstrBot Desktop 机制。

### D6 配置仍以 `.env` 为唯一存储，保存后提示重启

**决策**：WebUI 配置页读写走 `deploy` 既有管线（schema：`env_schema.build_schema()`；写：`deploy env_merge`/`init --answers` 同一入口），不引入第二配置存储。保存成功后返回 `restart_required: true`，前端弹出「立即重启」（走 §D7 的重启流程）。
**理由**：settings.py import 期读取是全项目依赖的事实；引入热更新机制是大手术且与「集中配置常量」的设计哲学冲突。AstrBot 的热配置能力不在本期对齐范围（§1.2）。

### D7 重启流程：WebUI 保存配置 → 桌面壳/CLI 执行重启

**决策**：`POST /api/v1/system/restart` 的实现 = 写既有停止哨兵（`core/stop_signal.py`）+ 通知外部监管者。桌面壳监听 Bot 退出事件自动重启（壳本就持有 `GUI_OWNS_BOT` 语义）；无壳形态（浏览器/Docker）提示用户执行 `stella restart` 或容器重启。WebUI 界面在 Bot 下线后自动切换到「重连中」状态页，恢复后自动重载。
**理由**：进程不能可靠地原地换血；AstrBot Desktop 同样把重启权收归桌面壳（`DESKTOP_MANAGED_RESTART_MESSAGE`）。Docker 形态可后置 `restart: always` 策略（本期文档说明即可）。

### D8 WebChat 走独立 ingress，虚拟群 + 专属空间，零 Schema 变更

**决策**（详见 §13）：Dashboard 聊天不经 OneBot、不经 ai_gateway 的五个监听器，新建 `webui/chat_ingress.py` 直接组装 `ChatContext` 调 `core/pipeline.py`：
- 虚拟 `group_id` 取负整数段（QQ 群号恒为正，天然不冲突），不进 `ALLOWED_GROUPS` → 主动发言/参与度/定时任务对虚拟群天然失效（它们都以白名单/真实群为前提）；
- `group_shared_space` 用专属空间 `webchat`（`config/spaces/webchat.toml`），长期记忆与画像按空间隔离——群聊记忆与 WebChat 记忆物理分库域；
- 消息落库复用 `memory.pre_processors.record_message()`（`source_kind=AT_MENTION` 语义：直接对话），回复写回 `BOT_SELF`；
- M4 先非流式（pipeline 现状为整段返回，SSE 单帧下发 + 前端打字机动画），pipeline 流式改造列为 M5 可选项。

### D9 趋同 = 范式趋同，不复制 AstrBot 源码

**决策**：允许且鼓励对齐 AstrBot 的页面结构、API 形状、交互流、SSE 事件协议；**不允许**复制其前端/后端源码文件（包括其 Materio 商业模板部分），所有组件用 Vuetify 官方组件 + 自建封装实现；AstrBot 源码仅作行为参考（黑盒对齐 + 少量白盒查阅协议字段）。
**理由**：① 对比报告已立红线「不要直接复制 AstrBot 的大规模平台和前端代码」；② AstrBot Dashboard 带 `CodedThemes` 商业模板署名，复制有许可证风险；③ 趋同的用户价值在「操作习惯可迁移」，不在代码同源。

### D10 v1 冻结原则

**决策**：v2 开发期间 `stella-installer/` 进入冻结态——只允许致命缺陷修复，禁止新功能；`docs/`、README 中 GUI 相关文档在 M6 统一切换。发布管线在 M6 前继续用 v1 出包（用户无感），M6 起切换到 v2 壳（§16）。

---

## 5. 目录与代码组织

```
stella_project/
├── dashboard/                      # ★ 新增：v2 前端工程（唯一 GUI 代码，pnpm + Vite）
│   ├── package.json  vite.config.ts  tsconfig.json
│   ├── src/
│   │   ├── api/                    # http.ts（axios+拦截器）、transport.ts（http/tauri 双通道）、v1.ts（语义化封装）
│   │   ├── layouts/                # full（侧栏+顶栏）/ blank（登录、Setup、离线壳页）
│   │   ├── router/                 # hash 路由，MainRoutes + AuthRoutes
│   │   ├── stores/                 # auth / customizer(主题) / toast / common(全局状态)
│   │   ├── components/             # 通用组件：ConfigForm(schema 渲染器)/ConfirmDialog/LogStream/StatusDot…
│   │   ├── views/                  # 每页一个目录（§6）
│   │   ├── composables/
│   │   ├── i18n/locales/{zh-CN,en-US}/{core,features}
│   │   └── theme/                  # StellaTheme / StellaThemeDark
│   └── dist/                       # 构建产物（gitignore；CI 生成）
│
├── desktop/                        # ★ 新增：v2 Tauri 2 桌面壳（不与 v1 共目录）
│   ├── src-tauri/                  # Rust：窄契约 commands（§11）、嵌入式 Python bootstrap（移植自 v1 python.rs）
│   └── resources/dashboard/        # 构建期拷入的 dashboard/dist（发布包内）
│
├── webui/                          # ★ 新增：WebUI 后端包（Python，与 capability/、knowledge/ 平级）
│   ├── app.py                      # create_webui_app()：FastAPI 子应用 + 静态 SPA + 中间件
│   ├── mount.py                    # setup_webui()：注册进 NoneBot app（含挂载顺序保证）
│   ├── auth.py                     # JWT 签发/校验、setup/login/desktop-session、限流
│   ├── security.py                 # scrypt 密码哈希（hashlib 标准库）、secret 管理（STELLA_HOME/webui/auth.json）
│   ├── responses.py                # ok()/error()/ApiError（对齐 AstrBot envelope）
│   ├── schemas.py                  # pydantic 请求模型
│   ├── static.py                   # SPA dist 解析（webui/dist 优先 → desktop resources 回退），版本标记 assets/version
│   ├── audit.py                    # 写操作审计（复用 scheduling 审计风格，落 STELLA_HOME/logs/webui_audit.jsonl）
│   ├── routers/                    # 每域一个 router：status.py config.py providers.py platform.py groups.py
│   │                               #   spaces.py plugins.py mcp.py skills.py knowledge.py scheduling.py
│   │                               #   usage.py logs.py conversations.py chat.py system.py
│   ├── services/                   # 薄服务层：把现有模块门面包装成 API 语义（不复制业务逻辑）
│   └── chat_ingress.py             # WebChat ingress（§13）
│
├── openspec/
│   └── openapi-v1.yaml             # ★ 新增：API 契约（OpenAPI 3.1）
│
├── stella-installer/               # v1：冻结（D10），M6 归档
└── tests/
    └── webui/                      # ★ 新增：test_webui_* 前缀（沿用仓库测试命名惯例）
```

**明确不动的**：`stella-installer/**`（冻结）、`config/settings.py`（只允许**追加** `WEBUI_*` 配置键，见 §9.4）、`core/pipeline.py` 及五监听器优先级（M4 只新增 ingress，不改既有路径）、`astrbot_compat/**`（仅 M3 允许新增「禁用插件」读取点，见 §6.5）。

---

## 6. 信息架构与页面设计

侧栏结构对齐 AstrBot，条目按 Stella 实情裁剪。括号内为 AstrBot 对应物。

```
(blank 布局，无侧栏)
├── /auth/setup          首次初始化向导（创建管理员账号）        (SetupPage)
└── /auth/login          登录                                  (LoginPage)

(full 布局，侧栏 + 顶栏)
├── /welcome             欢迎/总览                             (WelcomePage)
├── /chat                聊天（WebChat）                        (ChatPage)
├── /platforms           平台（OneBot/NapCat 连接）              (PlatformPage)
├── /providers           提供商（模型端点与角色绑定）             (ProviderPage)
├── /extension           扩展                                   (ExtensionPage)
│   ├── /extension/plugins          插件：已装 / 市场 两个子标签
│   ├── /extension/plugins/:id      插件详情（配置/README/工具清单）
│   ├── /extension/mcp              MCP Servers
│   └── /extension/skills           Skills
├── /config              配置（.env 全量 schema 编辑器）          (ConfigPage)
├── /knowledge-base      知识库（列表/详情/文档详情三级路由）      (knowledge-base/*)
├── /persona             人格与空间                              (PersonaPage)
├── /data                数据（Tab 壳 + 子路由）                  (DataPage)
│   ├── /data/statistics    统计图表
│   ├── /data/conversations 会话浏览（只读）
│   ├── /data/logs          日志（SSE live tail）
│   └── /data/trace         决策追踪（thought/参与度/记忆检索轨迹）
├── /cron                定时任务（Stella 的 Cron Agent）         (CronJobPage)
├── /groups              群组与绑定（Stella 特有：群↔空间映射）    (SessionManagement 简化)
└── /settings            设置                                    (Settings)
```

> 与 AstrBot 的差异说明：AstrBot 的「子代理 / 会话管理(按会话绑定 provider)」在 Stella 无对应基建，不设菜单；Stella 的「群组与绑定」在 AstrBot 中分散于 SessionManagement 与平台配置，v2 独立成页更贴合 Stella 的群驱动模型。

### 6.1 /auth/setup 与 /auth/login

- `setup-status`（无需鉴权）：`{setup_required: bool}`。管理员凭据未初始化时强制跳 setup。
- setup 表单：用户名 + 密码 + 确认密码（scrypt 哈希入 `STELLA_HOME/webui/auth.json`，同时生成 jwt_secret）。带语言切换与明暗主题切换（对齐 AstrBot SetupPage 头部）。
- login：账号密码 → 429 限流（令牌桶 5 次/分/IP）→ 签发 JWT（7 天），Bearer 存 localStorage + HttpOnly Cookie 双通道（Cookie 供图片直链/导出下载等无法带头场景）。
- 桌面壳路径：壳持有 secret 时调 `desktop-session` 自动登录，用户全程无感（D5）。

### 6.2 /welcome（总览）

对齐 WelcomePage 的「Onboarding 时间线 + 状态卡」三段式，去掉 AstrBot 的云端公告与外链赞助卡：

1. **Onboarding 时间线**（`v-timeline`，三步，完成态绿点）：
   ① 配置模型端点（`GET /api/v1/providers/endpoints` 有任一 base_url 非空）→ ② 绑定 QQ 群（`allowed_group_count > 0`）→ ③ Bot 在线（`GET /api/v1/status` 的 `pid > 0` 且 OneBot 链路已连接）。每步附「去配置」按钮跳转对应页。
2. **运行状态卡**：版本、PID、uptime、OneBot 链路状态点（复用 `link_status()`）、调度器排队深度、今日 token 总量、预算余量条、当前降级角色徽标。数据 = `/api/v1/status`（v1 `build_payload` 的超集，见 §7.1）。
3. **资源卡**：文档站 / GitHub / 诊断（doctor）三个入口卡。

### 6.3 /chat（WebChat，M4 交付）

布局对齐 AstrBot ChatUI：左侧会话栏（M4 单会话 + 「清空/新会话」；会话列表扩展后置）+ 主区消息流 + 底部输入框。
消息渲染：Markdown（代码高亮）、思考块（Stella 的 thought，可折叠）、图片；「推理过程侧栏」「工具调用卡片」跟随 M5 流式改造一并评估。
传输：`POST /api/v1/chat`（SSE）。事件协议对齐 AstrBot 帧（`{type, data}`：`run_started` / `message_saved` / `error` / `complete`），M4 仅产生单帧整段 + `complete`。
会话持久化：复用记忆库 `group_messages`（虚拟群），历史翻页 API 见 §7.12。

### 6.4 /platforms（平台）

AstrBot 的平台页是多适配器 workbench；Stella 只有一个 OneBot V11 适配器，页面降维为**单卡详情 + 状态面板**（保留 AstrBot 的卡片语言）：

- **连接配置卡**：反向 WS 监听（HOST/PORT，只读展示 + 「在配置页修改」链接）、正向 WS 上游地址列表（`ONEBOT_WS_URLS`，可编辑）、`ONEBOT_ACCESS_TOKEN`（掩码显示，写入走配置管线）。
- **链路状态面板**：心跳时间、探活结果、断开告警历史（`extensions/link_monitor` + `/api/v1/platform/link`）、NapCat 登录二维码引导位（v1 已有 napcat login 测试基建，M3 后评估接入口）。
- 每 5s 轮询状态（对齐 AstrBot PlatformPage 的 5s 轮询范式）。

### 6.5 /extension（扩展，M3 主体）

**6.5.1 插件-已装**（对齐 InstalledPluginsTab）
- 列表（列表/卡片双视图 + 搜索）：logo、名称、版本、作者、启用开关、操作菜单（配置 / 重载 / 卸载 / README）。
- 数据：`astrbot_compat.registry` + `capability/inventory.snapshot()` 合并（工具清单、能力声明认领、可路由、退避状态——v1 插件页已有此数据）。
- 启停实现（**新增机制**）：`data/plugins/.disabled.json`（Stella 自有文件，不污染插件目录）；`astrbot_compat/loader.discover_plugins()` 增加一个**只读过滤点**：出现在 disabled 集合中的目录跳过加载。这是 astrbot_compat 唯一改动，需要 GitNexus impact 评估（registry 为 HIGH 风险符号，约 22 个上游影响点——按对比报告结论「优先在 Registry/Adapter 层增加新实现」，此处仅在 discover 入口加过滤，不动 registry 结构）。
- 重载：复用 `loader` 既有热重载链（`parse_reload_command` 同一条内部路径封装成 API）。
- 配置编辑：`GET /api/v1/plugins/config`（`_conf_schema.json` → AstrBotConfig metadata）+ `PUT`（写 `data/config/<name>_config.json`），前端复用 schema 渲染器。
- 失败插件：`get_failed_plugins()` 列表 + 单独重载。
- 卸载：确认对话框（勾选「同时删除配置/数据目录」）→ 删除目录（审计）。
- 安装：GitHub repo / 直链 zip / 本地上传三入口 → 下载到 `data/plugins/` → **必须过 `deploy plugin-check` 规范校验**（Stella 既有安全闸，比 AstrBot 更严）→ 失败回滚删除。安装为长任务：返回 `task_id` 轮询。
- **市场（多源，评审定案）**：官方市场与自建市场**双支持**——官方市场审核乏力、更新长期滞后，自建源是一等公民：
  - 市场源注册表：`STELLA_HOME/config/plugin_sources.json`（默认内置 AstrBot 官方源一条），条目 `{id, name, url, enabled}`；页面可增删启停。
  - 源格式**兼容 AstrBot 市场 JSON schema**：自建市场按同一格式发布 JSON 即可被 Stella 直接消费，零适配成本。
  - 市场页聚合多源：卡片带来源徽标、按源筛选 chips、按 `name+repo` 去重（同名取 updated 更新者）；「安装」按钮走上述安装流（plugin-check 闸门不变）。
  - 添加/修改源时做 resolve 校验（拉取 + JSON 解析 + 必填字段检查），失败拒绝保存。
  - 仍不做：跨源「一键全部更新」、源内评级与下载统计。

**6.5.2 MCP**（对齐 McpServersSection）
- Server 卡片列表：名称、传输类型（stdio/http）、启用开关、连接状态点、工具数（`manager.status()`）。
- 编辑对话框：名称 + **Monaco JSON 编辑器**（`config/mcp.toml` 的 JSON 视图，stdio/sse/http 三个模板按钮）+ 实时校验 + 「测试连接」（起临时会话列工具，复用 `deploy mcp test` 的内部路径）+ 保存（写 `config/mcp.toml`）。
- 保存/启停后触发 `manager` 重载（bot 进程内热生效；Bot 离线时仅写文件，标注「下次启动生效」）。
- 工具目录抽屉：server → tools（名称/描述/schema 摘要），只读。
- 安全保留：不提供 `MCP_ENABLED=false` 时的绕过；工具进 Capability Registry 的既有路径不变。

**6.5.3 Skills**（对齐 SkillsSection 本地模式，不做 Neo/Shipyard）
- 卡片列表：名称、摘要、来源层（内置 `assets/skills/` / 用户 `data/skills/`）、启用开关、沙箱状态徽标（`sandbox.executor_status()`）。
- 详情抽屉：SKILL.md 渲染 + Monaco 编辑（用户层可编辑可保存；内置层只读 + 「复制到用户层」）。
- 上传：zip → `data/skills/`（校验 SKILL.md 存在）。
- 删除仅限用户层。
- `SKILLS_ENABLED=false` 时页面顶部横幅提示 + 跳转配置页开关。

### 6.6 /config（配置）

完全对齐 ConfigPage 范式，数据源换成 Stella 的 `.env` 管线：

- 顶部 sticky 工具栏：搜索框（按 key/注释过滤）+ 「仅常用」开关（schema 的 `obvious_hint` 字段过滤）+ 保存 FAB + JSON 源码对话框（Monaco 双向：从表单生成 / 应用到表单）+ **未保存 pill**（快照对比守卫，`beforeRouteLeave` 拦截）。
- 主体按 schema 分组（`deploy/env_schema` 已输出分组与注释）渲染成折叠分组表单；控件映射：

| schema 类型 | 控件 |
|---|---|
| bool | switch |
| int/float | 数字输入（带 min/max 时滑杆） |
| choice | 下拉 |
| inherits 键 | 空输入框 + 「留空继承 <父键>」提示（留空**不写入**，延续 env_schema 注释里的 GUI 契约） |
| secret（KEY/TOKEN 类） | 密码框 + 眼睛切换；读取时服务端掩码（`sk-****`），提交空串=不修改 |
| 多值（列表类） | chips 动态增删 |

- 保存 → `PUT /api/v1/config`（服务端走 `deploy env_merge` 语义写 `STELLA_HOME/.env`）→ 响应 `{restart_required: true}` → 弹「立即重启 / 稍后」对话框（走 D7）。
- 高危键白名单：`HOST`/`PORT`/`ONEBOT_*` 等标注「修改后需同步 NapCat」提示。

### 6.7 /knowledge-base（知识库，M3）

三级路由完全对齐 AstrBot（KBList → KBDetail → DocumentDetail），数据源换 `knowledge/service.py`：

- **KBList**：卡片（名称、描述、文档数/chunk 数——`list_accessible_kbs()`）；新建对话框（名称/描述/embedding 参数沿用 `KNOWLEDGE_*` 全局配置，AstrBot 的 per-KB embedding provider 选择不引入——Stella 的 embedding 是全局服务）。
- **KBDetail** 四个标签：
  1. 概览：信息 + 统计大数字（`kb_status()`）。
  2. 文档：表格（名称/状态(生命周期 draft→published)/chunk 数/时间/删除）；**导入对话框**（文件拖拽多选：md/txt/pdf/docx；URL 导入）→ `submit()` → 轮询文档状态至 published/failed（ingest worker 线程已有进度语义）。
  3. 检索测试：query + top_k → `POST .../retrieve`（走 `service.search` 的 ACL 强制检索）→ 结果卡（chunk 定位符、分数徽标、正文）。
  4. 设置/授权：`set_direct_publish` 开关；ACL 表（user/group/space 主体 grant/revoke——对应 `acl.py` 三态主体）。
- 文档详情：chunk 分页列表 + 删除（`archive_document`）。
- 红线保留：知识库证据不进记忆的隔离护栏（`knowledge/isolation.py`）不受页面影响；页面明示「知识库内容不会成为 Stella 的长期记忆」。

### 6.8 /persona（人格与空间）

对齐 PersonaPage 卡片网格，模型换成 Stella 的空间体系（空间=人格载体）：

- 空间卡片：空间名、绑定群（chips，可增删——`qq_groups`）、prompt 摘要（首行+字数）、操作（编辑/删除——有群绑定时删除需先解绑）。
- 编辑对话框：`system_prompt` 大 textarea（Monaco，Markdown 高亮）+ 群号 chips 输入；保存走 `spaces.toml` + `system_prompts/<space>.md` 双写（等价 v1 `save_persona` 的 Rust 逻辑改为 Python API）。
- 新建空间：名称（校验文件名安全）+ 初始 prompt。
- 出厂默认人格：`memory/SYSTEM.md` 只读卡（PROJECT_ROOT 资产，明示「随发布包更新，编辑请新建空间」）。

### 6.9 /data（数据）

Tab 壳 + 子路由，完全对齐 DataPage：

- **统计**（apexcharts）：概览大数字卡（今日 token / 调用数 / 缓存命中率 / 预算余量）→ 近 7/30 天 token 趋势 area 图（`usage_store` 日账按 `(date, role, slot, model)` 聚合）→ 按角色/端点/模型排行 bar 图 → 降级角色时间线（`fallback_states` 快照历史，v2 新增内存环缓冲）。**对齐 StatsPage 但数据源是 Stella 的用量账本**。
- **会话**（只读浏览，对齐 ConversationPage 但砍掉编辑）：按群筛选 + 分页浏览 `group_messages`（时间倒序，含 `source_kind` 标签着色：AT_MENTION/PASSIVE/BOT_SELF）；顶部「短期上下文」抽屉：选中群的 `short_term_context`（话题摘要、尾巴起点）与整合 checkpoint（`consolidation_state`）——这是排障「它为什么接错话」的直接窗口。**不做消息编辑/删除**（记忆一致性风险），导出为 JSONL 下载。
- **日志**：`GET /api/v1/logs/history`（JSONL 尾部 N 行）+ SSE `/api/v1/logs/live`（Last-Event-ID 续传、2s 重连）；开关：自动滚动、级别过滤、隐藏聊天内容（默认开——延续脱敏红线）。对齐 ConsoleDisplayer 范式。
- **追踪（决策轨迹可视化，评审定案：硬性交付）**：Stella 的决策链路（触发→闸门→路由→检索→工具→回复）散在 `memory/trace.py`、`participation_log`、thought 日志与 `ctx.route` 快照里——可视化把「它为什么没说话 / 为什么接错话」从翻日志变成点两下的排障入口。页面两个视图：
  - **轨迹流**：结构化决策事件表（时间 / 群 / 类型徽标：`gate`·`route`·`memory`·`tool`·`participation`·`planner` / 概要），按群、类型、时间过滤，行展开看完整结构化字段；SSE 实时追加（复用 §8.3 广播器，按事件类型过滤）。数据源 = thought 日志结构化消费 + `participation_log` + `memory/trace.py`。
  - **单条消息回放**：从轨迹流或会话页选中一次触发，`GET /api/v1/trace/replay` 聚合该次处理的完整决策链，按时间线纵向呈现：触发方式（@ / 主动 / 插件）→ **闸门判定与原因字符串**（`proactive_gate` 的 `can_speak` reason——「为什么这次没说话」的直接答案）→ Router 三级判定（命中层 / 能力 / 置信度）→ 记忆检索（模式、候选、分数、命中与淘汰原因）→ 工具执行（能力、耗时、summary）→ 上下文预算分配 → 回复（分行、thought 原文）。每一步可展开原始 JSON。
  - 实现边界：回放是**只读聚合查询**（按 `group_id + msg_id/时间窗` 串联既有记录），不新增运行时埋点；若既有轨迹字段不足以串联，允许 additive 补充（走 §17 红线 9 评审）。

### 6.10 /cron（定时任务，M3）

对齐 CronJobPage 范式，模型换成 Stella 调度服务（比 AstrBot 丰富）：

- 任务表（`v-data-table-server`）：群、类型徽标（reminder/agent）、内容摘要、cron 表达式、时区、状态（active/paused/cancelled）、下次触发（`cron` 模块计算）、修订号、操作（详情/立即执行/暂停|恢复/编辑/取消）。
- 筛选：按群（管理员全群视图 / 单群视图）、按类型、按状态。
- 创建/编辑对话框：
  - reminder：群选择、cron 表达式（输入框 + 常用模板下拉：每日 9 点 / 工作日 / 每 15 分钟…，模板生成五段表达式）、时区（IANA 搜索下拉）、提醒内容。
  - agent（管理员）：同上 + 目标描述、通知策略（`notify=always|on_content`）、补跑策略（all/latest）、**工具白名单**编辑器（`allow_tool/deny_tool` 的图形化）。
  - 校验全部复用 `service.create_task/edit_task`（群内配额、cron 严格方言校验、DST 规则原样生效）。
- 详情抽屉：完整字段 + **运行历史**（`history()`：时间/结果/投递回执/跳过原因 `skipped(quota_exceeded)` 等）+ **审计记录**（`audit_log()`）。
- WebUI 操作者身份 = 全局管理员（映射 `SCHEDULING_GLOBAL_ADMINS` 语义），但**群内串行、主动发言闸门、配额全部照旧**——对比报告红线「定时任务不能绕过主动行为闸门」在 WebUI 同样成立，页面上不做任何绕过入口。
- `SCHEDULING_ENABLED=false` 时只读 + 横幅。

### 6.11 /groups（群组与绑定，Stella 特有）

- 群表：群号、所属空间（下拉切换）、静音状态（`group_runtime_state`）、今日活跃度（消息计数）、主动发言开关状态；操作：绑定/解绑空间、静音/取消静音（运行期，写 `ALLOWED_GROUPS` 持久层 + 运行时状态）。
- 「添加群」：群号输入 + 空间选择（对齐 v1 settings persona tab 的心智）。
- 配额面板：主动 @ 配额、冷却、睡眠时段（只读展示 + 跳配置）。

### 6.12 /settings（设置）

左侧分类导航 + 右侧 section（对齐 Settings.vue 布局）：

- **appearance**：明暗主题（light/dark/system）、主题色（Stella 预设色板，运行时 patch Vuetify theme + localStorage——对齐 AstrBot 机制）、语言（zh-CN/en-US）。
- **security**：修改用户名/密码（`PATCH /api/v1/auth/account`）；「注销所有登录态」（轮换 jwt_secret）。
- **maintenance**：环境自检（doctor 报告卡片，复用 `deploy probe/checks` 输出）；数据目录占用统计（STELLA_HOME 各子目录体积——只读）；日志下载打包。备份/恢复、检查更新本期不做（§19）。
- **about**：版本（Python 侧 `_project_version()` + dashboard `assets/version` + 桌面壳版本三方一致性展示）、开源许可（AGPL-3.0）、AstrBot 兼容层说明。

---

## 7. 后端 API 契约（`/api/v1` 全表）

通用约定：envelope `{status, message, data}`；鉴权除标注 `公开` 外全部需要 JWT；写操作记审计（§9.5）。`webui/routers/` 与此表一一对应。

### 7.1 status / system

| 方法 | 路径 | 说明 | 后端落点 |
|---|---|---|---|
| GET | `/status` | 总览聚合：v1 `build_payload` 全量 + `allowed_groups`（已认证，给群号明细）+ `webui` 段（版本、setup 完成、登录用户） | `status_api.build_payload` 复用 |
| POST | `/system/restart` | 写停止哨兵；响应 `{ok, restart_mode: "desktop"\|"manual"}` | `core/stop_signal` |
| GET | `/system/doctor` | 执行环境自检（同步返回报告 JSON） | `deploy/probe.py`+`checks.py` |
| GET | `/system/storage` | STELLA_HOME 子目录体积统计 | 新增只读聚合 |

### 7.2 auth

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/auth/setup-status` | 公开。`{setup_required}` |
| POST | `/auth/setup` | 公开（仅 setup_required 时有效，否则 403）。创建管理员 |
| POST | `/auth/login` | 公开。限流。`{username,password}` → `{token, expires_at, username}` + Set-Cookie |
| POST | `/auth/desktop-session` | 公开。回环 + `X-Stella-Desktop-Session` 头 → JWT（同 AstrBot Desktop 机制） |
| GET | `/auth/me` | 当前用户 |
| PATCH | `/auth/account` | 改用户名/密码（验证旧密码） |
| POST | `/auth/logout` | 清 Cookie（JWT 无状态，前端删 localStorage） |

### 7.3 config / providers / platform / groups / spaces

| 方法 | 路径 | 说明 | 后端落点 |
|---|---|---|---|
| GET | `/config/schema` | `env_schema.build_schema()` 原样 | `deploy/env_schema` |
| GET | `/config` | 当前生效值 + schema 合并视图；secret 掩码 | `.env` 解析（复用 settings 读取语义） |
| PUT | `/config` | 增量写回（继承键留空不写、secret 空串不改）→ `{restart_required}` | `deploy env_merge` 语义 |
| GET | `/providers/endpoints` | 端点槽清单（base_url 掩码） | settings `LLM_ENDPOINT_*` |
| PUT | `/providers/endpoints` | 写回端点槽 → `{restart_required}` | 同上 |
| GET | `/providers/models?base_url&api_key` | 代理拉取 `/v1/models`（api_key 仅本次请求使用，不落盘——沿用 v1 Rust list_models 语义） | 新增 httpx 实现 |
| POST | `/providers/test` | 连通性测试：一次最小 chat 补全，`{ok, latency_ms, error}` | `core/llm/openai_client` 轻量调用 |
| GET | `/providers/roles` | 角色→端点/模型/温度 绑定矩阵 | settings `LLM_ROLE_*` |
| PUT | `/providers/roles` | 写回 → `{restart_required}` | 同上 |
| GET | `/providers/runtime` | 调度器快照 + 降级状态（只读） | `core.llm.snapshot`/`fallback_states` |
| GET | `/platform/onebot` | OneBot 连接配置（token 掩码）+ 反/正向 WS 现状 | settings + `link_status()` |
| PUT | `/platform/onebot` | 写 ws_urls/token → `{restart_required}` | `.env` 管线 |
| GET | `/platform/link` | 实时链路（心跳/探活/告警） | `extensions/link_monitor` |
| GET | `/groups` | 群清单：绑定空间、静音态、活跃度 | `config/spaces` + 记忆库只读查询 |
| PUT | `/groups/bindings` | 批量调整 群↔空间 绑定（审计） | `config/spaces/*.toml` |
| POST | `/groups/{id}/mute` · `/unmute` | 运行期静音开关 | `group_runtime_state` 既有写入口 |

### 7.4 spaces（人格）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/spaces` | 空间清单（绑定群、prompt 摘要、来源：用户/出厂） |
| POST | `/spaces` | 新建（名称安全校验） |
| GET | `/spaces/{name}/prompt` | prompt 全文 |
| PUT | `/spaces/{name}/prompt` | 保存 prompt → `{restart_required: false}`（spaces.py 有 reload） |
| PUT | `/spaces/{name}/bindings` | 修改群绑定 |
| DELETE | `/spaces/{name}` | 删除（有绑定时 409；可选「迁移记忆到空间 X」后续项） |
| GET | `/spaces/default` | 出厂 `memory/SYSTEM.md` 只读 |

### 7.5 plugins / mcp / skills

| 方法 | 路径 | 说明 | 后端落点 |
|---|---|---|---|
| GET | `/plugins` | 清单：元数据+状态+失败清单+工具/能力声明 | `astrbot_compat` + `capability.inventory` |
| GET | `/plugins/failed` · POST `/plugins/failed/{id}/reload` | 失败插件 | `loader.get_failed_plugins` |
| PATCH | `/plugins/enabled` | `{plugin_id, enabled}` → 写 `.disabled.json`（启用态需重载生效） | 新增过滤点 |
| POST | `/plugins/reload` | `{plugin_id}` 热重载 | 既有热重载链 |
| GET/PUT | `/plugins/config?plugin_id` | AstrBotConfig schema + 配置读写 | `astrbot_compat/config.py` |
| GET | `/plugins/readme?plugin_id` | README 渲染源 | 插件目录 |
| POST | `/plugins/install` | `{source: github\|url\|upload}` → `{task_id}`；完成后过 `plugin-check` | `deploy/plugin_check` |
| GET | `/plugins/tasks/{task_id}` | 安装任务轮询 | 新增任务表（内存） |
| DELETE | `/plugins/{plugin_id}` | 卸载（可选删配置/数据） | 目录删除+审计 |
| GET | `/plugins/market?source_id` | 多源聚合列表（`name+repo` 去重；`source_id` 可选筛选；缓存 10min） | 新增 httpx |
| GET/POST | `/plugin-sources` | 市场源注册表（`config/plugin_sources.json`；POST 带 resolve 校验） | 新增 |
| PUT/DELETE | `/plugin-sources/{id}` | 修改/删除源 | 新增 |
| GET | `/mcp/servers` | `mcp.toml` + `manager.status()` 合并 | `capability.providers.mcp` |
| POST/PUT/DELETE | `/mcp/servers[/{name}]` | CRUD（写 `config/mcp.toml`，审计） | 同上 |
| POST | `/mcp/servers/{name}/test` | 试连接并列工具 | `deploy mcp test` 内部路径 |
| GET | `/mcp/servers/{name}/tools` | 工具目录 | `manager.catalog` |
| GET | `/skills` | catalog + 来源层 + sandbox 状态 | `skills/` |
| GET/PUT | `/skills/{name}` | SKILL.md 读/写（内置层 PUT→409，提示复制到用户层） | 同上 |
| POST | `/skills/upload` | zip 导入用户层 | 同上 |
| DELETE | `/skills/{name}` | 仅用户层 | 同上 |

### 7.6 knowledge / scheduling / usage / logs / conversations

| 方法 | 路径 | 说明 | 后端落点 |
|---|---|---|---|
| GET/POST | `/knowledge-bases` | 列表 / 新建 | `knowledge.service` |
| GET/DELETE | `/knowledge-bases/{id}` | 状态 / 归档（`archive_kb`） | 同上 |
| PUT | `/knowledge-bases/{id}` | `set_direct_publish` 等 | 同上 |
| GET/POST | `/knowledge-bases/{id}/documents` | 文档清单 / 导入（multipart 或 `{url}`）→ 文档实体 | `submit()` + `ingest` |
| GET | `/knowledge-bases/{id}/documents/{doc_id}` | 文档详情+ingest 状态（轮询用） | 生命周期状态机 |
| DELETE | `/knowledge-bases/{id}/documents/{doc_id}` | `archive_document`/`unpublish` | 同上 |
| GET | `/knowledge-bases/{id}/chunks?doc_id&page` | chunk 分页 | store 只读 |
| POST | `/knowledge-bases/{id}/retrieve` | `{query, top_k}` 检索测试 | `service.search`（ACL 强制） |
| GET/PUT | `/knowledge-bases/{id}/acl` | ACL grant/revoke 视图 | `acl.py` |
| GET | `/scheduling/tasks?group_id&kind&status` | 任务清单（下次触发时间由服务端算好） | `SchedulingService.list_tasks` |
| POST | `/scheduling/tasks` | 创建（reminder/agent） | `create_task` |
| GET | `/scheduling/tasks/{id}` | 详情 | `show_task` |
| PATCH | `/scheduling/tasks/{id}` | 编辑（cron/tz/text/notify/rev/policy/工具白名单） | `edit_task`/`set_policy` |
| POST | `/scheduling/tasks/{id}/pause` · `/resume` · `/cancel` · `/run-now` | 状态操作 | `pause/resume/cancel/run_now` |
| GET | `/scheduling/tasks/{id}/history` | 运行历史 | `history()` |
| GET | `/scheduling/audit?group_id&limit` | 审计流水 | `audit_log()` |
| GET | `/usage/daily?days` | 日账序列（图表用） | `usage_store` 查询 |
| GET | `/usage/today` | 今日快照+预算+降级 | `usage_snapshot`+`fallback_states` |
| GET | `/logs/history?cursor&limit&level` | JSONL 尾读 | `LOG_DIR` 文件读 |
| GET(SSE) | `/logs/live` | 实时日志流，Last-Event-ID 续传，`: heartbeat` 保活 | logging_sink 订阅（新增进程内广播器） |
| GET | `/trace/history?group_id&type&limit` | 决策轨迹流（gate/route/memory/tool/participation 分型过滤） | `memory/trace.py`+`participation_log`+thought 日志 |
| GET | `/trace/replay?group_id&msg_id` | 单条消息决策回放（触发→闸门原因→路由→检索→工具→回复 全链聚合，只读） | 新增聚合查询 |
| GET | `/conversations?group_id&page` | 消息分页（只读） | `group_messages` 只读 |
| GET | `/conversations/{group_id}/context` | 短期上下文+整合 checkpoint | `short_term_context` 等只读 |
| GET | `/conversations/export?group_id` | JSONL 下载 | 同上 |

### 7.7 chat（WebChat）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/chat/session` | 当前 dashboard 用户的 WebChat 会话元信息（虚拟群号、空间、消息数） |
| POST | `/chat` | SSE。`{message}` → 事件帧见 §8.2 |
| GET | `/chat/messages?before_id&limit` | 历史翻页 |
| POST | `/chat/reset` | 清空当前会话（归档虚拟群消息段，开新段） |

### 7.8 files

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/files` | multipart 上传（KB 导入 / 聊天附件共用），413 上限 50MB，落 `STELLA_HOME/webui/uploads/`（临时区，7 天清理） |

---

## 8. 流式与推送协议

### 8.1 通用 SSE 形状（对齐 AstrBot）

```
POST /api/v1/xxx        响应头: text/event-stream, Cache-Control: no-cache
帧:    data: {"type": "...", ...}\n\n
心跳:  : heartbeat\n\n（≥1s 空闲时）
续传:  请求头 Last-Event-ID（logs/live 场景，服务端按 JSONL 行号游标回放）
```

### 8.2 WebChat 事件帧（M4）

| 帧 | data | 说明 |
|---|---|---|
| `run_started` | `{run_id}` | pipeline 开始执行 |
| `message_saved` | `{id, created_at}` | 用户消息落库确认 |
| `chunk` | `{text}` | M5 流式预留；M4 不产生 |
| `complete` | `{reply_id, lines: string[], thought?: string}` | 整段回复（M4 语义） |
| `error` | `{message}` | 兜底回复语义（pipeline 异常路径原样透传） |

### 8.3 日志流

帧 = `data: {JSONL 原始行对象}\n\n`；`id:` 字段 = 行号游标，供 Last-Event-ID 续传。实现为 `core/logging_sink` 之上的进程内广播器（`asyncio.Queue` 每订阅者一个，慢消费者断供策略：队列满即断开，客户端带游标重连——不许反压聊天链路）。

### 8.4 不引入 WebSocket 的说明

M2–M4 全部用 SSE（单向服务端推）足够，省去 WS 鉴权/心跳/重连三套复杂度。AstrBot 的 `unified-chat/ws` 是其 Live 语音模式与双传输选项的产物，本期不对齐。若 M5 流式改造后需要客户端打断（interrupt），可用 `POST /chat/interrupt`，仍不需 WS。

---

## 9. 鉴权与安全设计

### 9.1 威胁面变化（必须直说）

v1 的 HTTP 面只有 `/stella/status`：回环 + 只读 + 脱敏 + 无凭据。v2 引入**带写操作的鉴权 API 并托管 SPA**，攻击面质变：`HOST=0.0.0.0` 部署（NapCat 异机场景是 Stella 的正式用法）意味着整个管理面对局域网开放。因此：

### 9.2 凭据与令牌

- 存储：`STELLA_HOME/webui/auth.json` = `{username, scrypt(password), jwt_secret, created_at}`；文件权限尽力收紧（Windows 下 ACL 提示项写入 doctor）。
- 密码哈希：`hashlib.scrypt`（标准库，零新依赖，n=2^14, r=8, p=1）。
- JWT：HS256，`exp` 默认 7 天（`WEBUI_TOKEN_TTL_HOURS`）；载荷 `{username, iat, exp}`；**不**放权限范围（单管理员模型）。
- Cookie：`stella_webui_jwt`，HttpOnly + SameSite=Strict；仅作为 Bearer 之外的补充通道。
- 传输安全：默认部署即回环/局域网明文 HTTP；doctor 检出 `HOST=0.0.0.0` 时在 WebUI 顶栏常驻黄色横幅「管理面已暴露到局域网，请确保网络可信或配置反向代理 + HTTPS」。不内置 TLS（与 v1/AstrBot 一致，反代是标准解法）。

### 9.3 登录与账号

- setup 完成前所有写 API 403；`/api/v1/auth/*` 限流：令牌桶 5 req/min/IP（AstrBot 同款限流点：login/setup/desktop-session）。
- desktop-session：secret ≥32 字符、回环强制、恒定时间比较（`secrets.compare_digest`）。
- 「注销所有登录态」= 重置 jwt_secret（旧 token 全失效）。

### 9.4 新增配置键（追加进 `config/settings.py`，全部有保守默认值）

| 键 | 默认 | 说明 |
|---|---|---|
| `WEBUI_ENABLED` | `true` | 总开关；false 时完全不注册路由 |
| `WEBUI_TOKEN_TTL_HOURS` | `168` | JWT 有效期 |
| `WEBUI_LOGIN_RATELIMIT_PER_MIN` | `5` | 登录限流 |
| `WEBUI_MAX_UPLOAD_MB` | `50` | 上传上限 |
| `WEBUI_SERVE_DIST` | `true` | false 时只提供 API（前端开发反代场景） |

新键自动进入 `deploy config-schema` 输出 → v1 高级页与 v2 配置页都可见（schema 管线免费收益）。

### 9.5 审计与脱敏红线

- **审计**：所有非幂等写操作（config/providers/roles/groups/spaces/plugins/mcp/skills/kb/scheduling/system.restart）记 `STELLA_HOME/logs/webui_audit.jsonl`：`{ts, user, via(jwt|desktop), method, path, body_digest(脱敏后摘要), result}`。调度子系统自身的 `audit_log()` 继续生效（双层审计）。
- **脱敏**（延续 status_api 测试钉死的红线）：任何 API 响应不得出现 `api_key` 明文 / `ONEBOT_ACCESS_TOKEN` / prompt 与模型输出原文（chat 页面向用户本人展示自己的会话除外——那是用户自己的数据）；群号仅出现在已认证接口。
- **CORS**：默认同源（不配置 CORS 中间件即为同源）；前端 dev 模式走 Vite proxy，不依赖 CORS。
- **上传**：类型/大小白名单 + 随机文件名落临时区；KB 导入后即转入 knowledge 管控。
- **不做的**：TOTP/验证码（单管理员本地场景收益低，§19 后置）；API Key scope 体系（后置）。

### 9.6 与 v1 面的关系

`/stella/status` 原样保留（回环+脱敏+测试不动）：v1 GUI、`deploy status`、`stella` Rust CLI 继续工作，直到 M6 归档评估。

---

## 10. 前端工程规范

### 10.1 目录与状态

见 §5。Pinia stores 对齐 AstrBot 职责划分：

| store | 职责 |
|---|---|
| `auth` | token/用户名、login/setup/logout、desktop-session 直通、401 全局处理（清 storage → 跳登录） |
| `customizer` | 主题模式（light/dark/system）、主题色、侧栏 mini 状态（localStorage 持久化） |
| `toast` | 全局 snackbar 队列；`useToast().success/error/info/warning`（对齐 AstrBot 反馈范式） |
| `common` | `/status` 轮询缓存、dashboard 版本、全局日志流共享连接（对齐 common store） |

### 10.2 API 层与 transport 抽象（v2 GUI 离线能力的关键）

```ts
// api/transport.ts（示意）
interface Transport { status(): ...; getConfig(): ...; saveConfig(): ...; doctor(): ...;
                      migrate(): ...; start(): ...; stop(): ...; logTail(): ...; }
// httpBackend: axios /api/v1/*；tauriBackend: window.__TAURI__.core.invoke（离线窄契约）
// 选择逻辑：无 __TAURI__ → http；有 __TAURI__ → 先探 /api/v1/auth/setup-status，
//          不通 → tauriBackend（离线模式页：onboarding 向导/doctor/启动），通 → http + desktop-session 免登录
```

其余页面组件只依赖 `api/v1.ts` 的语义化封装；离线时由路由守卫整页导向 `OfflineShell` 布局，不逐页判断。

### 10.3 schema 驱动表单（全项目复用组件）

`components/ConfigForm/`：输入 = AstrBot 风格 metadata（`{type, description, hint, items, condition}`），输出受控值。三处消费：`/config`（env schema 适配器转换）、插件配置（`_conf_schema.json` 原生即是该形状）、KB/调度对话框的局部表单。控件映射见 §6.6 表格。这是前端最重的自研组件，M2 交付并在 M3 复用。

### 10.4 i18n

- `locales/{zh-CN,en-US}/{core,features}`，features 每页一个命名空间；`useModuleI18n('features/welcome')` 用法对齐 AstrBot。
- 首发语言 zh-CN（Stella 现状），en-US 随 M5 覆盖核心导航与高频页；后端返回的错误 message 保持中文原文（与 AstrBot 一致——它的 message 也是中文优先）。

### 10.5 主题

- `theme/StellaTheme.ts` / `StellaThemeDark.ts`：Vuetify theme 对象 + 自定义语义 token（`containerBg/surface/border/chatBubble/...`，命名对齐 AstrBot 令牌体系便于组件代码同构）。
- **品牌色（评审定案：取自 `assets/pic/Stella_logo_origin.jpg` 实测取色）**：
  - 背景基准 = logo 底色**深板岩蓝**，全图均值 **`#171D24`**（主频带 `#182028`–`#202830`）；
  - 强调色 = 星芒金 **`#E5CE9C`**（高光带 `#F8E8C0`），作 secondary / 徽标 / 图表第二系列，**不作主色**；
  - light 主题：primary `#2E3B4E`（板岩蓝提亮一档，按钮/激活态），surface `#F5F7FA`；
  - dark 主题：primary `#8FB0CC`（同色相提亮保证暗底对比度），background 直接用 `#171D24`，card `#1E2732`；
  - 对比度门禁：primary 与 white 文本对比 ≥ 4.5:1，M0 主题文件里加一个断言脚本，避免深底深字。
- `plugins/vuetify.ts` defaults：`VCard rounded="lg"`、`VSnackbar elevation-6`、`VTooltip location="top"` 等与 AstrBot 同款默认值，保证观感一致。
- 明暗切换：`customizer.SET_THEME_MODE` → `theme.global.name`（system 跟随 `prefers-color-scheme`）。

### 10.6 构建与开发流

```bash
cd dashboard && pnpm install
pnpm dev            # vite :5173，proxy /api/v1 → http://127.0.0.1:8080（连真 Bot）
pnpm build          # vue-tsc + vite build → dist/，写 assets/version（git short sha）
pnpm typecheck && pnpm lint
```

---

## 11. 桌面壳 v2（Tauri 2）

### 11.1 职责清单（相对 v1 的增删）

| 保留（自 v1 移植） | 新增 | 移除 |
|---|---|---|
| 嵌入式 Python bootstrap（下载/校验/装依赖/SHA256/断点续传） | desktop-session secret 生成与注入 | 12 个业务 invoke 中的页面级逻辑（usage/plugins/persona 渲染层） |
| `run_deploy` 子进程封装（CREATE_NO_WINDOW、JSON stdout） | Bot 退出监听 → 自动重启（D7，配合 `GUI_OWNS_BOT`） | 自绘的设置/用量/插件页面（由 dashboard 接管） |
| doctor / migrate / config 读写 / start / stop / log tail | webview 源切换（在线→`http://127.0.0.1:PORT`，离线→壳内 dist） | `list_models`（Rust ureq 版，改由 `/api/v1/providers/models`） |
| `data_root()` 缓存与失效语义（v3.1.0 事故注释必须随迁） | | `serve.bat` mock 预览（dashboard 自带 vite dev+mock） |

### 11.2 窗口与生命周期

- 窗口 1280×800（v1 为 1024×576，v2 按 dashboard 布局放宽），`csp` 收紧为只允许 `self` 与 `http://127.0.0.1:PORT`（v1 是 null，v2 借重置之机补上）。
- 关闭语义沿用 v1：CloseRequested → 「安全关闭」遮罩 → await stop（仅当 `GUI_OWNS_BOT`）→ destroy。
- 自动重启策略：`GUI_OWNS_BOT` 且退出码非用户停止 → 延迟 3s 自动重启，上限 3 次（指数退避），超出后停在「启动失败」页并展示日志。

### 11.3 打包

- dashboard 构建产物在 CI 中拷入 `desktop/src-tauri/resources/dashboard/`；壳离线态从资源目录加载（tauri protocol），在线态导航到 `http://127.0.0.1:{PORT}/`。
- NSIS 离线安装器（WebView2 离线引导）沿用 v1 CI 参数；版本号三处同步（Cargo.toml / tauri.conf.json / Python `_FALLBACK_VERSION`）保留同步测试。

---

## 12. 打包、CI 与发布

1. **新增 `dashboard_ci.yml`**：pnpm install → typecheck → lint → build → 上传 dist artifact；对 `dashboard/` 与 `webui/` 的变更必跑。
2. **`ci.yml` 增量**：Python 矩阵加入 `tests/webui/`；`ruff` 覆盖 `webui/`。
3. **release.yml 重构（M6）**：
   - `build-dashboard` job（tag → version 文件）→ 产物同时供 desktop 壳 stage 与 Python 侧 `webui/dist` stage；
   - `build_release_package.py`：`INSTALLER_FILES` 指向 `desktop/`；新增 `--stage-webui` 步骤把 dist 拷入发布包 `webui/dist`（源码/Docker 运行时由此目录服务 SPA）；
   - `.env.example` 增补 `WEBUI_*` 五键（含注释）。
4. **依赖变更**（`requirements.txt` + `pyproject.toml` 同步）：
   - `pyjwt>=2.8`（纯 Python，无 wheel 风险）；
   - `python-multipart`（FastAPI 表单/上传必需；确认 nonebot2[fastapi] 未传递引入，缺则显式钉住）；
   - `build_offline_payload.py` 按 requirements.txt 生成 wheels——两个新依赖自动纳入，CI 增加「离线 payload 内含 jwt/multipart」断言。
5. **Docker**：镜像内 `webui/dist` 随层进入；compose 无端口变化；文档注明「浏览器访问 http://127.0.0.1:8080/」。

---

## 13. WebChat 接入设计（M4 详案）

### 13.1 定位与隔离原则

WebChat 是「管理员在面板里与 Stella 私聊」，不是第二个 QQ 群：

| 维度 | 处理 | 依赖的既有机制 |
|---|---|---|
| 群标识 | 虚拟群 `WEBCHAT_GROUP_BASE - user_index`（负数段，QQ 群号恒正，零冲突） | 无需改 schema |
| 空间 | 专属空间 `webchat`（出厂预置 `config/spaces/webchat.toml`，prompt 可在 /persona 编辑） | `resolve_space` 天然隔离长期记忆/画像 |
| 白名单 | 虚拟群**不进** `ALLOWED_GROUPS` → 主动发言、参与度、定时任务、整合排空对其关闭 | `proactive_gate` 等全部零改动 |
| 落库 | `record_message(source_kind=AT_MENTION)` 直调 + 回复写 `BOT_SELF` | `memory/pre_processors` 复用 |
| 整合 | WebChat 消息**参与**整合（这是对话记忆的来源）但走 `webchat` 空间的独立配额与 checkpoint | `consolidator` 群锁按群号天然隔离 |
| 预算 | WebChat 消耗 CHAT 角色预算，与群聊同池（诚实记账） | `usage_store` 零改动 |
| 工具 | 走同一 Router/Comes 通道（能力对等） | `activate_capabilities` 复用 |

### 13.2 请求链路

```
POST /api/v1/chat {message}
  → chat_ingress: 组装 ChatContext{user_id=<dashboard用户映射>, group_id=虚拟群,
                   group_shared_space="webchat", trigger="reply", intent="", source_kind=AT_MENTION}
  → record_message()（落库）
  → 每-ingress 一把 asyncio.Lock（同群串行，等价群级锁语义）
  → pipeline.run(ctx)（pre hooks 全链：短期上下文/记忆检索/能力激活 原样生效）
  → SSE：message_saved → complete{lines, thought}
```

### 13.3 明确不支持（M4）

多会话并行、文件/图片输入（pipeline 的 vision 路径面向 OneBot 图链，WebChat 附件后置）、打断、群发言代发（**永不支持**——WebChat 不能让 Bot 在 QQ 群里说话，闸门红线）。

---

## 14. 测试与验收策略

| 层 | 内容 | 命名/位置 |
|---|---|---|
| 挂载回归 | 四类路径共存（OneBot WS / status / api / SPA）；`WEBUI_ENABLED=false` 时零注册；挂载顺序断言 | `tests/webui/test_mount.py` |
| 鉴权 | setup→login→JWT 过期/伪造→401；desktop-session 回环+secret；限流 429；`auth.json` 缺失时写 API 全 403 | `test_webui_auth.py` |
| 脱敏 | 全响应扫描断言（沿用 `test_status_api.py` 的反泄漏断言手法：api_key/Bearer/http:// 不出现） | `test_webui_redaction.py` |
| 配置写回 | 继承键留空不写、secret 空串不改、choice 越界拒绝、写后 `deploy init` 幂等重放 | `test_webui_config.py` |
| 子系统门面 | plugins enabled 过滤（discover 层单测）、mcp CRUD→toml 回读、kb 导入状态轮询、scheduling CRUD 走 Service 真实校验（配额/权限原样触发） | `test_webui_plugins.py` 等 |
| WebChat 隔离 | 虚拟群不出现在 ALLOWED_GROUPS/proactive/scheduling 任何查询；`webchat` 空间记忆与群空间零交集；审计双写 | `test_webui_chat_isolation.py` |
| SSE | 日志广播器慢消费者断供、Last-Event-ID 续传、心跳 | `test_webui_sse.py` |
| 前端 | `vue-tsc` 类型门禁；vite 构建门禁；E2E（Playwright，M4 起）：setup→login→配置→重启提示→chat 冒烟 | `dashboard/tests/` |
| Windows 基线 | webui 测试不依赖真实进程树/子进程（沿用现有测试基线认知，避免踩 windows 矩阵已知失败） | 全部用 monkeypatch/临时目录 |

验收里程碑的 demo 脚本（每个 M 结束跑一遍）写入 `design_docs/check_point/`。

---

## 15. 里程碑计划

> 顺序依据对比报告的实施优先级（WebUI/ChatUI 列第 5，但其前置四项已全部落地）。每个里程碑独立可发布、可回滚（v1 始终可用直至 M6）。

### M0 契约与骨架（预计 1.5 周）
- `openspec/openapi-v1.yaml` 首版（auth/status/config/system + 占位 tag）；
- `webui/` 包骨架：mount + auth + responses + audit + 静态托管（dist 缺失时返回引导页「前端未构建」）；
- `dashboard/` 脚手架：Vuetify 主题/布局/路由/toast/i18n/auth store/登录与 setup 页；
- CI（dashboard_ci + Python 矩阵扩展）；
- **验收**：浏览器登录进空壳侧栏；pytest 全绿；v1 与 Bot 行为零变化（现有 165 个测试文件不动一个断言）。

### M1 只读面板与决策轨迹（预计 2 周）
- `/welcome`（状态聚合）、`/data` 四页（统计 / 会话 / 日志 SSE / **追踪 = 轨迹流 + 单条消息回放**，评审定案硬性交付）、providers 运行态只读、平台链路卡、插件只读清单；
- **验收**：信息量 ≥ v1 全部只读页（run/usage/plugins）且新增图表与实时日志；**任意一次「没说话 / 接错话」能在追踪页回放出闸门原因与检索过程**；与 v1 并存对照验收。

### M2 配置与写入面（预计 2 周）
- ConfigForm schema 渲染器；`/config` 全量编辑（含未保存守卫/JSON 源码/掩码）；`/providers` 编辑 + 模型拉取 + 测试；`/platforms` 编辑；`/spaces` 全 CRUD；`/groups` 绑定；`/settings`（security/appearance/about + doctor）；system/restart；
- 桌面壳骨架（Tauri v2：移植 bootstrap/doctor/migrate/start/stop + transport 切换 + desktop-session）；
- **验收**：①纯浏览器完成一次全新部署配置并重启生效；②桌面壳离线完成 bootstrap→doctor→**旧数据迁移（向导，评审定案保留）**→配置→启动→在线直通免登录全流程（v1 全功能替换验证）。

### M3 子系统管理（预计 2.5 周）
- `/extension/plugins`（启停/重载/配置/安装/卸载/**多源市场与源管理** + discover 过滤点 impact 评估）、`/extension/mcp`、`/extension/skills`、`/knowledge-base` 全页、`/cron` 全页；
- **验收**：五大子系统 CRUD 全通；调度操作与群内指令走同一 Service 校验（配额拒绝在 WebUI 可复现）；审计双层落盘。

### M4 WebChat（预计 1.5 周）
- chat_ingress + `/chat` 全页 + SSE 协议（M4 语义）+ 隔离测试；
- **验收**：面板聊天有记忆、有画像、能调工具；与任一群聊的记忆互不可见（isolation 测试钉死）。

### M5 打磨（预计 1 周 + 持续）
- en-US 翻译覆盖、暗色主题走查、空态/错误态补全、性能（首屏分包）、pipeline 流式改造评估（可选，独立设计文档）；
- **验收**：视觉走查对照 AstrBot 截图逐页过。

### M6 发布切换与 v1 归档（预计 1 周 + 观察期）
- release 流水线切换（§12.3）、文档切换（README/START_GUI/docs）、`.env.example` 增补；
- v1 归档动作（§16）；**2 个发布周期观察期**后再删 `stella-installer/` 目录。

---

## 16. v1 归档方案

1. **冻结（立即生效）**：`stella-installer/` 只收致命 bug 修复（D10）。
2. **标记**：M6 切换发布时打 tag `gui-v1-final`，作为 v1 最终形态的永久引用点。
3. **过渡（M6 起 2 个发布周期）**：代码保留在树内但不进发布包；README 指引存量用户迁移；`/stella/status` 保持兼容。
4. **归档**：观察期满后：
   - `git rm -r stella-installer/`（历史永在，`gui-v1-final` tag 可随时检出）；
   - 同步删除 v1 专属测试（Rust 内嵌测试、与 start.bat 的常量同步测试）；
   - `release_assets/` 中 v1 双冗余脚本按新壳契约重生成；
   - 在 `_deprecated/README.md` 登记一行指引（该目录 gitignore，仅作本地提示）。
5. **不迁移的**：v1 无独立数据（配置全在 STELLA_HOME），归档零数据迁移成本。

---

## 17. 相容性红线清单（实现期逐条自查）

1. 不新增监听端口；`/onebot/v11/ws` 与 `/stella/status` 行为逐字节不变（回归测试钉死）。
2. 不改 `config/settings.py` 既有键语义，只追加 `WEBUI_*`。
3. 不改五监听器优先级与 pipeline 既有行为；WebChat 只新增 ingress。
4. 不为 WebUI 绕过任何闸门：主动发言闸门、调度配额、plugin-check、MCP 白名单、知识库-记忆隔离、沙箱默认关。
5. 响应脱敏红线：无 api_key/token 明文回显；统计/状态响应无 prompt 与模型输出。
6. 前端不复制 AstrBot/Materio 源码（D9）；AGPL 头注释随新文件携带。
7. `astrbot_compat` 改动仅限 discover 过滤点一处，且先跑 GitNexus impact（`CapabilityRegistry` HIGH、兼容层 Context MEDIUM——本机 CLI registry 损坏期间按记忆用文本核查兜底，恢复索引后复检）。
8. 测试命名 `test_webui_*`；不碰 `test_scheduling_*` 既有约定；Windows 矩阵测试不做进程树依赖。
9. SQLite 一律 Additive（本方案预期零 schema 变更，若实现中发现需要，先回到本文档评审）。
10. 新增依赖仅 `pyjwt`、`python-multipart`，进离线 payload 断言。

---

## 18. 风险登记册

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| R1 | `app.mount("/")` 与 NoneBot/OneBot 路由顺序冲突 | 高 | 挂载放最后一个 startup 钩子 + 四类路径回归测试；备选方案：SPA 挂 `/webui` 前缀 + 根路径 302（保底不破坏） |
| R2 | `HOST=0.0.0.0` 下管理面暴露 | 高 | 强制鉴权 + 限流 + 审计 + 横幅告警 + doctor 提示；文档给反代/防火墙建议 |
| R3 | 前端工程引入 Node 工具链，破坏「零构建」发布 simplicity | 中 | 构建只发生在 CI/开发机；发布包内仍是静态 dist；嵌入式 Python 运行时无关 |
| R4 | 插件 discover 过滤点影响兼容层（HIGH 符号） | 中 | 只读过滤、先 impact、行为测试覆盖「disabled 文件损坏→全量加载」的失败开放语义 |
| R5 | WebChat 记忆污染群聊（产品级事故） | 中 | 负数群号 + 独立空间 + 不进白名单的三重隔离 + isolation 测试组 |
| R6 | 配置「重启生效」体验落差（AstrBot 是热配置） | 中 | 文档明示 + 一键重启流；长期项：settings 分层加载改造（独立立项） |
| R7 | 双壳并存期（M2–M5）用户困惑 | 低 | 发布包在 M6 前不换壳；CHANGELOG 预告 |
| R8 | SSE 经反代缓冲失效 | 低 | 文档给 nginx `proxy_buffering off` 配置样例；AstrBot 同款问题已有社区解法 |
| R9 | pyjwt/python-multipart 在离线 payload 缺失 | 低 | requirements.txt 单一来源 + CI 断言 |

---

## 19. 评审定案记录（2026-09-22，已拍板）

| # | 议题 | 定案 | 落点 |
|---|---|---|---|
| 1 | 插件禁用标记位置 | 采纳推荐：`data/plugins/.disabled.json`（跟随插件目录、卸载即清理） | §6.5.1 |
| 2 | 市场源策略 | **官方 + 自建双支持**：官方源为默认项，自建源为一等公民（格式兼容 AstrBot 市场 JSON schema，源可增删启停、resolve 校验）。原因：官方市场审核乏力、更新长期滞后 | §6.5.1、§7.5 |
| 3 | WebChat 空间默认值 | 采纳推荐：单管理员 = 单 `webchat` 空间，命名留 `<user>` 扩展位 | §13 |
| 4 | 主题主色 | 参照 `assets/pic/Stella_logo_origin.jpg` **背景色**（实测均值 `#171D24` 深板岩蓝系；星芒金 `#E5CE9C` 为辅助强调色） | §10.5 |
| 5 | 旧版本数据迁移向导 | 保留于 v2 桌面壳，M2 验收流覆盖 | §11.1、§15-M2 |
| 6 | 决策轨迹可视化 | **硬性交付，不是余量项**：轨迹流 + 单条消息回放（触发→闸门原因→路由→检索→工具→回复全链），M1 交付，排障场景写进验收 | §6.9、§7.6、§15-M1 |

---

## 附录 A：AstrBot 参考文件索引

| 主题 | 路径（`E:\stella\_reference\AstrBot\`） |
|---|---|
| 前端路由/侧栏 | `dashboard/src/router/MainRoutes.ts`、`layouts/full/vertical-sidebar/sidebarItem.ts` |
| HTTP 层/拦截器 | `dashboard/src/api/http.ts`、`api/v1.ts` |
| 后端装配 | `astrbot/dashboard/api/app.py`（服务注册表）、`api/router.py`（v1 前缀+scope 写回）、`server.py`（中间件/限流/静态） |
| 鉴权 | `api/auth.py`（JWT/Scope/desktop-session）、`services/auth_service.py`、`core/desktop_runtime.py` |
| 响应 envelope | `astrbot/dashboard/responses.py` |
| 聊天 SSE | `api/chat.py`、`services/chat_service.py`（run_snapshot/断线重连协议） |
| 日志 SSE | `api/logs.py`（history+live, Last-Event-ID） |
| 静态托管 | `api/static_files.py`、`core/dashboard_assets.py`（版本兼容/远端回退） |
| schema 渲染 | `dashboard/src/components/config/`（AstrBotConfig/ConfigItemRenderer） |
| 页面样本 | `views/CronJobPage.vue`、`views/extension/McpServersPage.vue`、`views/knowledge-base/`、`views/stats/StatsPage.vue` |
| API 契约 | `openspec/openapi-v1.yaml`（约 6600 行，scope 扩展字段 `x-astrbot-scope`） |
| 发布 | `.github/workflows/release.yml`（build-dashboard job）、`pyproject.toml` hatch 钩子（wheel 内嵌 dist） |

## 附录 B：Stella 现有模块 → v2 API 映射速查

| v2 域 | Stella 落点 | 备注 |
|---|---|---|
| status | `status_api.build_payload` | 直接复用，webui 加 allowed_groups 明细 |
| config | `deploy/env_schema` + `env_merge` 语义 | v1 高级页同源 |
| providers | settings `LLM_ENDPOINT_*`/`LLM_ROLE_*`、`core/llm/registry.py` | 写 .env，重启生效 |
| platform | `extensions/link_monitor`、settings `ONEBOT_*` | |
| groups | `config/spaces.py`、记忆库 `group_runtime_state` | |
| spaces | `config/spaces/*.toml` + `system_prompts/*.md` + `memory/SYSTEM.md` | v1 save_persona 语义 |
| plugins | `astrbot_compat/loader.py`、`registry.py`、`config.py`、`capability/inventory.py`、`deploy/plugin_check.py` | 新增 `.disabled.json` 过滤点 |
| mcp | `capability/providers/mcp/manager.py`、`config/mcp.toml`、`deploy mcp test` | |
| skills | `skills/`（discovery/catalog/runtime/sandbox） | |
| knowledge | `knowledge/service.py` 全门面 | 零业务逻辑复制 |
| scheduling | `stella_project/plugins/bot_main/scheduling/service.py` | 群内指令与 WebUI 共用同一校验 |
| usage | `core/llm/usage_store.py`、`usage_sink.py` | |
| logs | `core/logging_sink.py` + `STELLA_HOME/logs/stella.jsonl` | 新增广播器 |
| conversations | 记忆库 `group_messages`/`short_term_context`/`consolidation_state` 只读 | |
| chat | `core/pipeline.py` + `memory/pre_processors.record_message` | 新增 `webui/chat_ingress.py` |
| system | `deploy/probe.py`/`checks.py`、`core/stop_signal.py`、`deploy/process.py` | |

## 附录 C：术语对照（AstrBot → Stella v2）

| AstrBot | Stella v2 | 说明 |
|---|---|---|
| Provider（提供商） | 端点槽（`LLM_ENDPOINT_*`） | Stella 槽位固定 5 个，AstrBot 可动态增删 |
| Provider 绑定（default 等） | 角色绑定（`LLM_ROLE_*`） | 语义相同：哪个任务用哪个模型 |
| Platform Adapter | OneBot/NapCat 连接 | Stella 单适配器 |
| Persona | 共享空间（space）的人格 | Stella 人格与空间一一对应 |
| UMO / 会话管理 | 群组与绑定 | |
| 插件市场 | 插件市场（官方 + 自建多源聚合） | 安装后过 Stella 规范校验；源格式兼容 AstrBot 市场 schema |
| Cron Job | 定时任务（reminder/agent） | Stella 多补跑策略/通知策略/工具白名单/审计 |
| 知识库 | 知识库 | 同构；Stella 的 ACL 是 user/group/space 三态 |
| ChatUI | WebChat | Stella 先单会话 |
