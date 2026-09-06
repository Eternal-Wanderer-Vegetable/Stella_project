# Docker 化部署方案 v1.0

> 状态：已评审（2026-09-07）。阶段 1 已实施：`Dockerfile`、`.dockerignore`、`docker-compose.yml`、`docs/deployment-docker.md`。阶段 2/3 未实施。
> 目标：**零代码改动**，把 Stella 容器化，远程服务器 `docker compose` 一条命令起停；升级 = 换镜像，数据不动。
> 原则：复用项目已有的 `STELLA_HOME`（程序目录 / 用户数据目录分离）设计，不引入新的布局概念。

---

## 0. 现状评估：为什么零代码改动可行

| # | 有利条件 | 证据 |
|---|---|---|
| A1 | 用户数据目录定位的**第一优先级就是 `STELLA_HOME` 环境变量** | `config/home.py:120`（`_resolve` 首先读环境变量） |
| A2 | 配置全部走 `.env`，所有路径类配置有环境变量覆盖；`HOST=0.0.0.0` 默认值天然适配容器 | `config/settings.py`、`.env.example` 顶部 |
| A3 | 代码在 Linux 上运行已被 CI 验证 | `ci.yml` 全部 job 跑 `ubuntu-latest`（3.10/3.11/3.12 全绿） |
| A4 | NapCat（QQ 协议端）本就是独立进程，项目明确不代管（`design_docs/deprecated_napcat_manager.md`） | 容器化只需编排，不需要碰协议端代码 |
| A5 | 优雅停机已内建：uvicorn `timeout_graceful_shutdown=5` + shutdown 钩子清理 Chromium | `bot.py` |

### 0.1 出厂内容 vs 用户数据的边界（实施前调研确认）

镜像里只放「程序」（出厂内容），用户数据一律走 `STELLA_HOME` 挂卷。边界按 git 跟踪情况与代码引用确认：

| 路径 | 归属 | 进镜像？ |
|---|---|---|
| `core/ memory/*.py config/ capability/ astrbot_compat/ extensions/ stella_project/ deploy/ bot.py pyproject.toml requirements.txt` | 程序代码 | ✅ |
| `config/capabilities/*.toml`、`config/participation/*.toml`、`memory/SYSTEM.md`、`.env.example` | 出厂默认（`deploy/manifest.py` 的 MANIFEST_TARGETS 同源） | ✅ |
| `.env*`（example 除外）、`memory/agent_memory.db*`、`data/`、`logs/`、`deploy.answers.toml`、`.stella-state.json` | 用户数据 / 密钥 | ❌ 挂卷 |
| `system_prompts/*.md` | **出厂人格，随包发布**（git 跟踪，`deploy/manifest.py` 的升级哈希清单也登记它）。用户改过的人格放 `STELLA_HOME/system_prompts/`，读取时优先于出厂份 | ✅（用户份走挂卷，优先级更高） |
| `runtime/`（371MB Windows 嵌入式 Python）、`stella-installer/`（5.2GB Tauri GUI）、`release_*/ _deprecated/ docs/ tests/ scripts/ assets/` | Windows 发布形态 / 开发产物，运行期不读（`plugin_scaffold` 对 `docs/` 仅有注释引用） | ❌ |

`data/` 在 git 里只有 `.gitkeep`；运行期 `ASTRBOT_PLUGINS_DIR` 等全部锚定 `STELLA_HOME`（`_user_path`），程序目录下的 `data/` 无人引用，整目录排除安全。

## 1. 目标架构

```
远程服务器
└── docker compose
    ├── stella  (本项目镜像, python:3.12-slim)
    │   ├── ENV STELLA_HOME=/data  TZ=Asia/Shanghai
    │   ├── 卷: ./StellaData → /data   （.env、记忆库、插件、日志全在这）
    │   └── 监听 8080
    ├── napcat  (mlikiowa/napcat-docker 官方镜像)          ← 阶段 2
    │   ├── WebUI 6099（仅首次扫码登录，绑 127.0.0.1 + SSH 隧道）
    │   └── 反向 WS 客户端 → ws://stella:8080/onebot/v11/ws（compose 内网，不暴露）
    └── LLM 端点：出站访问，不进 compose
        ├── 全在线模式：直接填 API 地址（最简单）
        └── 混合模式：LM Studio 在同机宿主机 → http://host.docker.internal:1234
```

**备选拓扑**（支持但不默认推荐）：NapCat 留在用户 Windows 电脑、Stella 在服务器——需把 8080 发布到公网，**必须**两侧配 `ONEBOT_ACCESS_TOKEN`，并建议 Caddy/Nginx TLS 或 WireGuard。阶段 1（NapCat 在别处）即此拓扑，文档两种都写。

## 2. 核心设计决策

| 决策 | 理由 |
|---|---|
| `STELLA_HOME=/data` 挂卷承载全部用户数据 | 直接复用 A1；换镜像 = 升级、卷 = 数据，与项目「升级 = 换掉程序目录」哲学同构 |
| Playwright 浏览器 + 中文字体烤进镜像 | 现状靠 `RENDER_AUTO_INSTALL` 首次渲染时下载（几分钟）；服务器可能没外网或慢。`fonts-noto-cjk` 必须显式装——`--with-deps` 不装字体，缺了中文卡片渲染成豆腐块 |
| 健康检查 `curl /stella/status`（容器内执行） | 复用现有端点；它只接受回环访问（`status_api.py:_is_loopback`），healthcheck 在容器内恰好是回环得 200。外部探活会得 403（403 也证明进程活着），监控要区分语义 |
| 容器内 `PORT` 固定 8080 | 改端口交给 compose 端口映射（`"9090:8080"`），否则 healthcheck 与 NapCat 反向 WS URL 失配 |
| `init: true` + `stop_grace_period: 15s` | uvicorn 已有 5s 优雅停机（在途记忆整合不丢）；`init` 收割 playwright 拉起的 node/chromium 子进程（shutdown 钩子已处理，此为双保险） |
| 非 root（uid 1000）运行 | 写权限只给数据卷；`PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright` 必须同时设——默认缓存路径在 `/root` 下，切用户后找不到浏览器 |
| `TZ=Asia/Shanghai` + tzdata | 主动搭话、消息新鲜度（`RECENT_TAIL_MAX_AGE_MINUTES` 等）都依赖本地时间语义，容器默认 UTC 会全错且无报错 |
| 镜像体积 ~1.1–1.3GB | slim 130MB + 依赖 + 浏览器（~270MB）+ 中文字体。阶段 2 提供 `WITH_RENDER=false` 精简变体（~450MB，不渲染卡片） |
| 只能单实例 | 记忆库是本地 SQLite + 进程内状态，禁止 `--scale` / 多副本 |

## 3. 镜像设计（Dockerfile 要点）

```dockerfile
FROM python:3.12-slim
# tzdata / fonts-noto-cjk / curl（healthcheck 用）
ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright STELLA_HOME=/data
COPY requirements.txt → pip install → playwright install --with-deps chromium-headless-shell
COPY . .            # .dockerignore 挡掉用户数据/密钥/Windows 发布形态
useradd uid 1000 stella；mkdir /data && chown
HEALTHCHECK ... curl -fsS http://127.0.0.1:8080/stella/status
CMD ["python", "bot.py"]
```

构建参数：`PIP_INDEX_URL`（默认官方源；注意部分国内镜像不收录 playwright，见 `requirements.txt` 备注）。

## 4. .dockerignore 要点

**绝不能进镜像**（密钥 / 隐私 / 体积）：

- `.env`、`.env.dev`、`.env.prod`、`.env.backup`、`.env.bak` —— **`.env.example` 必须保留**（`deploy init` 的模板），所以不能写 `.env*`
- `memory/*.db*`、`memory/*.bak`、`data/`、`logs/`、`StellaData/`、`.stella-state.json`、`deploy.answers.toml`、`system_prompts/`
- `runtime/`、`stella-installer/`、`release_assets/`、`release_backup/`、`_deprecated/`（合计 >5.6GB）
- `.git`（91MB）、`.gitnexus/`、缓存、`docs/`、`tests/`、`scripts/`、`design_docs/`、根目录开发探针产物（`windows_raw.json`、`consolidation_probe*` 等含真实群聊数据）

## 5. compose 编排

阶段 1 仅 `stella` 服务（详见根目录 `docker-compose.yml`）：`build: .`、`./StellaData:/data`、`init: true`、`stop_grace_period: 15s`、`restart: unless-stopped`、`extra_hosts: host.docker.internal:host-gateway`（混合模式连宿主机 LM Studio）、`ports: 8080`（NapCat 在别处时必须可达，公网暴露务必配 token）。

阶段 2 增加 `napcat` 服务（`mlikiowa/napcat-docker`）：WebUI 6099 绑 `127.0.0.1`，反向 WS 走 compose 内网 `ws://stella:8080/onebot/v11/ws`，届时 `stella` 的 ports 可撤掉或改绑回环；另加极简 `entrypoint.sh`（检测 `/data/.env` 缺失时打印「先跑 deploy init」引导，再 `exec python bot.py`）。

容器场景下 `deploy start/stop/status`（宿主机进程管理）被 compose 取代；`deploy init` / `deploy doctor` 在容器内依然可用。

## 6. 服务器操作流（docs/deployment-docker.md 覆盖）

- **首次部署**：上传仓库 → `mkdir -p StellaData && chown 1000:1000` → `docker compose build` → `docker compose run --rm stella python -m deploy init`（交互向导写 `/data/.env`）→ `up -d` → NapCat 配反向 WS 指向 `ws://<服务器>:8080/onebot/v11/ws`（+token）→ `docker compose ps` 看 healthy
- **从现有 Windows 安装迁移**：停本机 Bot → 把 `.env`、`memory/`（数据库）、`data/`（插件）、`config/spaces/`、`system_prompts/`（人格）拷入服务器 `./StellaData/` → 起容器（`deploy migrate` 的路径清单两种布局通用）
- **升级**：`git pull && docker compose build && docker compose up -d`（阶段 3 后为 `pull` 镜像）；数据卷不动
- **备份**：整个 `./StellaData/` 目录 tar 一份（SQLite 库 + .env + 插件 + 日志）

## 7. 分阶段实施

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | `Dockerfile` + `.dockerignore` + `docker-compose.yml`（仅 stella，NapCat 在别处）+ `docs/deployment-docker.md` + README 链接 | ✅ 已实施 |
| 2 | compose 集成 napcat 服务 + `entrypoint.sh` 引导 + `WITH_RENDER` 精简镜像构建参数 | ⬜ |
| 3 | GitHub Actions 出镜像到 GHCR（挂 `release.yml` 的 tag 触发，amd64 优先、arm64 可选）；AGPL-3.0 分发镜像时源码 tag 即合规对应 | ⬜ |

## 8. 风险与边界

- **单实例**：SQLite 记忆库 + 进程内状态，禁止多副本。
- **PORT/健康检查耦合**：对外换端口用映射，别改容器内 `PORT`。
- **状态端点回环限制**：外部监控得 403 属预期。
- **公网暴露 8080**：伪造 OneBot 客户端可操纵 Bot，必须 `ONEBOT_ACCESS_TOKEN`（两侧一致）+ 建议 TLS。
- **卷权限**：bind mount 需宿主机 `chown 1000:1000 StellaData`；named volume 由镜像内 `/data` 属主兜底。
- **隐私**：`.env` 与记忆库含密钥和聊天记录，绝不 COPY 进镜像（`.dockerignore` 兜底），卷权限 600 建议。
- **镜像内时区/字体**是最易漏、漏了只出怪症状的两点（搭话时间错、卡片豆腐块），镜像里已显式装好。
