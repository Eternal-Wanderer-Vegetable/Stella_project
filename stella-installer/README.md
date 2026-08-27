# stella-installer — Stella 桌面安装器

Stella 的 Windows 桌面图形界面（Tauri 2 + 原生 HTML/JS），即 Release 包内的 `Stella.exe`。
它是 `deploy/` 部署工具的渲染层：**业务逻辑全在 Python 侧，这里只负责调用并展示**。

## 功能

四个页面（`src/` 下的静态 HTML，无前端构建步骤）：

| 页面 | 文件 | 作用 |
|---|---|---|
| 运行状态 | `run.html` | 启动/停止 Bot、实时日志、一键复制诊断信息 |
| 配置 | `config.html` | 填写群号/连接/模型信息，写项目根 `.env`（模型列表可从 LM Studio 拉取） |
| 人格设定 | `persona.html` | 按共享空间编辑人格文件 |
| 环境自检 | `doctor.html` | 展示 `deploy doctor` 结果与修复提示 |
| 从旧版本导入 | `migrate.html` | 预览并执行 `deploy migrate`（配置/记忆/人格/插件搬迁 + 数据库升级） |

启动时（`index.html`）先跑一遍自检：未配置且**探测到旧版本安装**时进「从旧版本导入」页，
未配置且没有旧版本进「配置」页，有阻塞问题进「环境自检」页，一切正常则直接进「运行状态」页。

## 架构

- `src-tauri/src/commands.rs` — Tauri command 层：只做「调 `python -m deploy ...` + 转 JSON」，不含业务逻辑
- `src-tauri/src/python.rs` — 定位/引导 Python：优先用 Release 包内的嵌入式运行时（`runtime/python.exe`），开发时回退到 PATH 里的 Python；首次运行会下载嵌入式 Python 并安装依赖（`release_assets/start.bat` 同一流程的纯 Rust 复刻）
- `src/api.js` — 前端对 Tauri 命令的封装；在浏览器里预览（无 `window.__TAURI__`）时自动落到 mock
- `src/mock/` — 结构固定的 mock 数据，供浏览器预览与字段对齐

## 开发

浏览器预览（走 mock 数据，无需 Rust 环境）：

```bat
serve.bat
```

> 预览服务跑在 `http://localhost:8765`，以 `src/` 为文档根——ES module + fetch 需要真实
> origin，`file://` 会被 CORS 拦截导致脚本不执行。

真实桌面环境：

```bash
cd src-tauri
cargo tauri dev
```

## 数据契约

GUI 依赖这几个 `deploy` 命令的输出：`deploy doctor --json`、`deploy config-schema --json`、
`deploy paths`（结构化 JSON），以及 `deploy migrate`（Markdown 报告原文）。
改结构要 bump schema 的 `version` 并同步 `src/mock/`。详见 `docs/development.md` 的「前端契约」。

**用户数据目录不在 Rust 侧判断**：`python::data_root()` 去问 `deploy paths` 要
（判据只有 `config/home.py` 一份）。`.env`、空间配置、人格都读写数据目录；
`.env.example`、`memory/SYSTEM.md`、`pyproject.toml` 与 `runtime/` 属于程序目录。

## 发布

Release CI（`.github/workflows/release.yml`）用 `cargo tauri build --no-bundle` 产出便携版
`Stella.exe`，放进 `Stella-*-win64.zip` 的项目根目录——安装器与 `bot.py` 必须在同一目录，
才能 `python -m deploy` 到它。不做 NSIS/MSI 安装包。