# GUI 测试启动指令

Stella 桌面图形界面（Release 包里的 `Stella.exe`）源码在 `stella-installer/`（Tauri 2 + 原生 HTML/JS）。
开发/测试有两种启动方式，完整说明见 `stella-installer/README.md`。

## 1. 浏览器预览（最快，无需 Rust 环境，走 mock 数据）

```bat
stella-installer\serve.bat
```

- 启动后自动打开 `http://localhost:8765`，以 `stella-installer/src/` 为文档根
  （ES module + fetch 需要真实 origin，直接双击 HTML 会被 `file://` 的 CORS 拦住）。
- 浏览器里没有 `window.__TAURI__`，前端自动落到 `src/mock/` 的 mock 数据——只适合纯界面调试。
- 只需要 Python（优先 `runtime\python.exe`，其次 PATH 里的 `python` / `py`）。

## 2. 真实桌面窗口（完整功能，调用真实的 deploy 命令）

```bat
cd stella-installer\src-tauri
cargo tauri dev
```

- 需要 Rust 工具链与 tauri-cli（未装时先 `cargo install tauri-cli`）。
- GUI 只是渲染层，业务逻辑全在 Python 侧（`deploy/`）；开发时会回退到 PATH 里的 Python，
  首次运行会自动下载嵌入式 Python 并安装依赖。
