# Stella 桌面壳 v2（Tauri 2）

v2 GUI 的桌面宿主：**加载 WebUI（dashboard/）**，Bot 离线时提供窄契约
（bootstrap / doctor / migrate / 配置 / 启停 / 日志 tail）。与 AstrBot
Desktop 同构（方案 §4 D1/D5、§11）。

## 与 v1（stella-installer/）的关系

- Rust 代码自 v1 移植：嵌入式 Python 引导（python.rs，下载/校验/装依赖）、
  doctor / migrate / start / stop / 日志读取等命令原样保留；
- 移除/替换的部分：
  - 页面级 invoke（用量/插件/人格渲染层）→ 由 dashboard 接管；
  - `list_models`（Rust 直连 /v1/models）→ 改走 `/api/v1/providers/models`；
  - 新增 `desktop_session_secret` 命令：壳启动时生成 ≥48 字符随机秘钥，
    `start_bot` 时注入子进程环境变量 `STELLA_DESKTOP_SESSION_SECRET`；
    dashboard 在 tauri 源下经 invoke 取秘钥换发正式 JWT（回环 + 恒定时间
    比较，webui/routers 的 desktop-session 端点）。
- 关窗语义：CloseRequested → 安全关闭遮罩（dashboard 经 `close-requested`
  事件自绘）→ stop → destroy。stop **不带**「Bot 是否由本 GUI 进程启动」的
  门卫——上次会话留下的 Bot 同样会被停止（否则关窗留孤儿占住服务端口，
  2026-09-24 实测）；跨安装安全由 Python 侧 ownership 校验把守（别的安装或
  手工启动的实例 `deploy stop` 自会拒绝）。停止失败也照常关窗，细节走
  `close-failed` 事件与日志；窗口 1280×800；CSP 收紧（v1 为 null）。

## 布局

```
desktop/
└── src-tauri/
    ├── src/{main,lib,commands,python}.rs   # lib 含秘钥 OnceLock；其余自 v1 移植
    ├── capabilities/ gen/ icons/            # Tauri 2 能力与图标（自 v1）
    └── tauri.conf.json                      # productName=Stella, 1280×800, CSP 收紧
```

dashboard 的构建产物由 CI 拷入 `desktop/dashboard-dist/`
（tauri.conf 的 `frontendDist` 指向它）：发布包离线态加载该目录；
Bot 在线后导航到 `http://127.0.0.1:<PORT>/`（同一套面板）。

本地构建：先 `cp -r dashboard/dist/* desktop/dashboard-dist/`
（目录缺失会导致 `cargo check/build` 直接失败——tauri 在编译期校验
frontendDist 存在性），再 `cargo tauri build`。`cargo check` 已通过
（2026-09-23，含秘钥注入与 wait_bot_ready 命令）。

## 本地构建

```bash
cd desktop/src-tauri
cargo tauri build          # 需 tauri-cli；首次构建会拉取全部 crate
```

发布流水线（M6 后）会先构建 dashboard → 拷入 dashboard-dist → 再跑
`cargo tauri build --bundles nsis`。
