# 发布流程

中文 | [English](release.en.md) · [文档总览](../README.md)

打 tag 后 CI（`.github/workflows/release.yml`）自动打包并发布，产出六类 Windows 产品资产：`Stella-OneClick-Python/Rust-vX.Y.Z-windows-amd64.exe`（单文件安装器）、`Stella-OneClick-Python/Rust-Offline-vX.Y.Z-windows-amd64.exe`（离线安装器，见下）与 `Stella-Standalone-Python/Rust-vX.Y.Z-windows-amd64.zip`（仅本体的解压包），另有 CLI、llama backend 等独立资产。

### OneClick Offline 的离线负载

Offline 变体与在线版**同一份代码、同一个 profile id**，只是 NSIS 资源里多了一份
`offline/` 负载（存在与否决定安装器走本地优先还是联网路径，见
`desktop/src-tauri/src/python.rs` 与 `deploy/bootstrap.py`；发布安装器自 v6 起从 `desktop/src-tauri` 构建，冻结的 v1 在 `stella-installer/`）。负载由
`scripts/build_offline_payload.py` 在 CI 里构建，包含：

- 嵌入式 Python 运行时 zip（哈希从 `python.rs` 的 `PY_VER`/`PY_SHA256` 解析，单一事实来源）；
- `get-pip.py`（`MANIFEST.json` 记录 sha256，安装器校验后配合 `--no-index` 离线装 pip）；
- requirements.txt 的完整 wheel 闭包（`pip wheel` 现场构建，含只有 sdist 的包，如 `qrcode_terminal`）；
- package catalog 声明的全部组件（llama.cpp backend / NapCat / 默认 embedding 模型，文件名 = catalog 的 `artifact` 字段，校验走与在线安装同一条 catalog checksum 路径）；
- playwright 的 chromium-headless-shell（`PLAYWRIGHT_BROWSERS_PATH` 指向随包内核，渲染零下载）。

WebView2 运行时不在负载里，而是由 Tauri 的
`webviewInstallMode: offlineInstaller` 内嵌进 NSIS 安装器本体（约 +127MB）：
安装时先检测注册表，已有 WebView2 则跳过，没有则静默装内嵌的离线安装包，
同样零联网。默认的 `downloadBootstrapper` 需要联网下载运行时，在无 WebView2
的离线机器上 GUI 起不来（2026-09 真实用户反馈），`embedBootstrapper` 也仍需
联网——必须用 `offlineInstaller`。

**修改安装期组件时必须同步检查**：新增 catalog 组件 → 无需改负载脚本（按 catalog 遍历）；
新增 Python 依赖 → 确认 `pip wheel` 能构建出 wheel；升级 playwright → 负载里的内核
revision 必须与新版本一致（脚本现场安装，天然一致）。

### 打 tag 前的检查清单

1. `python -m pytest tests -q` 全绿
2. `ruff check .` 无警告
3. `pyproject.toml` 版本号已更新（CI 会把 tag 与它比对，不一致直接 fail）
4. 改过配置项 → `.env.example` 与 `docs/configuration.md` 已同步
5. `release_assets/RELEASE_NOTES_TEMPLATE.md` 已更新为本版本说明，**破坏性变更必须列明**（例如废弃全部 `NAPCAT_*` 配置）。注意「让用户丢数据」不再是一种合法的升级方式：schema 每 +1 都必须带自动迁移
6. Release 的排除清单独立于 `.gitignore` 维护（见 `release.yml` 的注释）；新增运行期产物或配置文件时，需同时更新排除清单与敏感文件校验的正则
7. **新增顶层目录必须判断该不该进 Release**：开发工具（如 `stella-installer/`，独立分发的 Tauri 安装器）、工具脚本等不能打进用户安装包，需加进 `release.yml` 的 rsync 排除清单与「校验开发目录」的正则，并跑一次手工打包验证
8. `release_assets/start.bat` 里硬编码了 Python 版本与 SHA256；升级 Python patch 版本时需同步更新两处，主次版本变更时还要确认 `python*._pth` 的处理

然后：

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

CI 会自动：校验版本号 → 构造发布目录（排除 `tests/`、`design_docs/`、`scripts/`、`_deprecated/`、`.github/`、`memory/benchmark/` 等）→ 拷入 `release_assets/` 的四个文件并把 bat/txt 转成 CRLF → 打 zip → 创建 GitHub Release。

### 升级嵌入式 Python 时的注意事项

`release_assets/start.bat` 里**硬编码**了：

- `PY_VER`（如 `3.12.10`）
- `PY_ZIP`（embed-amd64 包文件名，随 `PY_VER` 变）
- `PY_SHA256`（python.org 下载页的官方校验值，写错会导致安装永远失败）
- 段 6 里 `python*._pth` 的通配符（`python312._pth` 里的 `312` 对应主次版本，换 Python 时若文件名不再匹配要同步改）

升级 Python 版本时这四处要一并更新，并在本地完整跑一遍 `start.bat` 验证（会产生 `runtime/` 目录，已加入 `.gitignore`）。

> **注意**：发布版 OneClick 安装器的首次安装逻辑在 `desktop/src-tauri/src/python.rs`（`runtime_bootstrap`）里用纯 Rust 复刻了同一流程，`PY_VER` / `PY_SHA256` / 下载镜像常量与 `start.bat` 必须同步修改（有同步测试把关）——安装器不依赖 `start.bat`，它只是备用手动安装方式。冻结的 v1 安装器 `stella-installer/src-tauri/src/python.rs` 里还有一份旧孪生，不再随版本发布。

> **编码约定**：`release_assets/` 里的 `.bat` 使用纯 ASCII，内部注释与输出统一使用英文；发布时仍统一转换为 CRLF，确保 Windows `cmd` 稳定解析。面向用户的 `README-快速开始.txt` 可继续使用 UTF-8 with BOM。

### 嵌入式 Python 的三处必改

Release 包用 Python Embeddable Package 作运行时，它有三个与常规 Python 不同的行为，
两条 bootstrap 路径（命令行的 `start.bat`、发布安装器的 `desktop/src-tauri/src/python.rs`）
都必须处理：

1. **`import site` 默认被注释**（`python3xx._pth` 里）。不取消注释则 pip 装到
   `Lib\site-packages` 的依赖全部 import 不到；
2. **`._pth` 存在时 Python 只按该文件构建 `sys.path`**，等价于带上 `-E -s`，
   且其中的相对路径是**相对 `python.exe` 所在目录**解析的。默认的 `.` 指向
   `runtime\` 而非项目根，因此 `runtime\python.exe -m deploy` 会报
   `No module named deploy`（2026-08-18 实测）。需要追加一行 `..`；
3. **只带标准库，没有 `setuptools` / `wheel`**，而现在的 `get-pip.py` 只装 pip
   （setuptools/wheel 早就从它的默认项里去掉了）。于是任何**只发 sdist、不发 wheel**
   的依赖都装不上——pip 要构建它就得 import `setuptools.build_meta`，报
   `BackendUnavailable: Cannot import 'setuptools.build_meta'`，整条依赖安装退出码 2。
   必须在装 `requirements.txt` **之前**先 `pip install setuptools wheel`。

前两处在「启用 site-packages」段处理，用 `python*._pth` 通配匹配文件名，避免升级
Python 主次版本时漏改；第三处是 `start.bat` 的 `Installing build tools` 段与
`python.rs` 的 `ensure_build_tools()`，两边由
`tests::both_bootstrap_paths_install_build_tools` 钉住不许漂移。

> 第 3 条是 2026-08-26 v3.0.0 预发布的真实事故：`qrcode_terminal` 在 PyPI 上只有源码包，
> 全新解压的发布包装依赖必然失败。**开发机完全不复现**——那里的 `runtime/` 早年被老版
> `get-pip.py` 带上过 `setuptools`，一直沿用至今。

**这类问题 CI 挡不住**：ubuntu runner 上的 import 校验只能验证目录完整性，
`._pth` 的路径行为与「缺 setuptools」都只在真实 Windows 的嵌入式运行时里出现。因此每次改动
`start.bat` 或 `python.rs` 后，必须在**全新解压的目录**里实测一遍（不要复用已装好的目录，
它的 `._pth` 可能已被上一次运行修正过、`site-packages` 里也可能早就有 setuptools，
两者都会掩盖问题）。

> 想在开发机上复现「全新运行时」：把 `runtime\Lib\site-packages` 下的 `setuptools*`、
> `wheel*`、`_distutils_hack`、`distutils-precedence.pth` 临时改名，再跑一次装依赖。
