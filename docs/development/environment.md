# 环境准备

中文 | [English](environment.en.md) · [文档总览](../README.md)

## 环境准备

```bash
git clone https://github.com/Eternal-Wanderer-Vegetable/Stella_project.git
cd Stella_project
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

`requirements-dev.txt` 包含 pytest、ruff、numpy 等开发期依赖。numpy 只被 embedding fixture 的向量计算用到，缺失时相关测试会跳过而非报错。

### 开发机的用户数据放在 `StellaData/`

仓库根目录下的 `StellaData/`（整体 gitignore）是本机的**用户数据目录**（`STELLA_HOME`）：

```text
Stella_project/
  StellaData/          ← 你的 .env、记忆库、空间配置、人格、插件数据、日志
    .env  deploy.answers.toml
    memory/  config/spaces/  system_prompts/  data/  logs/
  bot.py  config/  deploy/  memory/  …   ← 代码
```

`config/home.py` 的第 2 条（便携模式）会命中它，于是**仓库、发布包、运行期的相对布局是同一套**
——都是「数据在 `StellaData/` 里」，区别只在这个目录挂在哪一级。

已有的老工作副本（数据散在仓库根上）不受影响：`config/home.py` 的第 3 条会认出「旧布局」并就地使用。
想迁过来的话，把 `.env`、`deploy.answers.toml`、`memory/`、`config/spaces/`、`system_prompts/`、
`data/`、`logs/` 移进 `StellaData/` 即可，路径常量全部跟着 `STELLA_HOME` 走，不用改代码。
`python -m deploy paths` 会告诉你当前解析到了哪里、走的是哪一条规则。

**不要把数据目录提交进仓库**：`.gitignore` 里有 `StellaData/`，`release.yml` 的 rsync
排除清单里也有，`scripts/check_release_layout.py` 会在发布前再拦一道。三层都是刻意的——
这个目录装着真实的 `.env` 与聊天记录，一旦随发布包出门就收不回来。
## v2 控制面（面板与桌面壳）开发

仓库里有三块 v2 GUI 代码（方案与状态见 [docs/webui.md](../guides/webui.md)）：

```bash
# 面板前端（Vue 3 + Vuetify 3）：开发期反代到本机 Bot（8080）
cd dashboard && pnpm install
pnpm dev            # http://localhost:5173
pnpm build          # vue-tsc 类型门禁 + vite 构建 → dist/

# 独立 WebUI 服务器（不起 Bot 也能调鉴权/配置页）
python scripts/dev_webui.py --port 8091

# 桌面壳（Tauri 2）：先填充内嵌面板，再编译
cp -r dashboard/dist/* desktop/dashboard-dist/
cd desktop/src-tauri && cargo tauri build   # 或 cargo check 快速验证

# 忘记面板管理员密码
python scripts/webui_reset_auth.py --yes
```

约定：`webui/` 是叶子包，**不得反向 import `stella_project.plugins.bot_main`**
（宿主注入模式，见 `webui/status_source.py`）；新增顶层 Python 包/目录时必须
同步 `scripts/build_release_package.py` 的 `COMMON_DIRS`（payload 缺目录会让
面板挂载连坐失败，2026-09-24 实测）。
